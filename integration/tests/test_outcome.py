"""Outcome policy and retention checks against real existing module behavior."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import timedelta, timezone
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from infrapilot_triage import ApprovalGate
from infrapilot_triage import collection_context as triage_context
from infrapilot_triage.schemas import DataSource, LogEntry
from provider.examples.context_fixtures import mock_context_binding
from setup.models import OperationRequest

from integration import outcome, outcome_fixtures, outcome_evidence, service
from integration.mock_approval import MockClock
from integration.outcome import OutcomeEvaluator, SimulatedActionRef
from integration.outcome_demo import main
from integration.outcome_evidence import EvidenceRef, OutcomeError
from integration.outcome_fixtures import run_outcome_demo, synthetic_sample, SCENARIOS
from integration.service import MockSession
from integration.workflow import MOCK_GOAL, MockWorkflow


ROOT = Path(__file__).resolve().parents[2]
CANARY = "PRIVATE_OUTCOME_CANARY_315671"


def assert_no_execution(test, value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("execution_performed", "execution_authorized", "authorization_consumed", "causality_established",
                       "remediation_verified", "real_execution"):
                test.assertIs(item, False)
            assert_no_execution(test, item)
    elif isinstance(value, list):
        for item in value:
            assert_no_execution(test, item)


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.clock = MockClock()
        self.evaluator = OutcomeEvaluator(mock=True, clock=self.clock)
        self.start = self.clock.now

    def sample(self, **changes):
        return synthetic_sample(timestamp=self.clock.now, **changes)

    def pair(self, before=None, after=None):
        first = self.evaluator.evidence.retain_synthetic(self.sample(**(before or {})))
        self.clock.now = self.start + timedelta(seconds=10)
        second = self.evaluator.evidence.retain_synthetic(self.sample(**(after or {})))
        return first, second

    def compare(self, before=None, after=None):
        return self.evaluator.compare(*self.pair(before, after)).to_dict()

    def test_health_order_all_known_transitions_and_unknown_values(self):
        rank = {"healthy": 0, "degraded": 1, "unhealthy": 2}
        for old in (*rank, "unknown"):
            for new in (*rank, "unknown"):
                with self.subTest(old=old, new=new):
                    self.setUp()
                    view = self.compare({"status": old}, {"status": new})
                    if (old == "unknown") != (new == "unknown"):
                        expected = "insufficient_comparable_evidence"
                    elif old == "unknown" or old == new:
                        expected = "no_material_observed_change"
                    else:
                        expected = "observed_improvement" if rank[new] < rank[old] else "observed_deterioration"
                    self.assertEqual(view["observation_result"], expected)
                    assert_no_execution(self, view)

    def test_real_symptom_thresholds_determine_latency_direction(self):
        threshold = self.evaluator.thresholds.slow_response_ms
        for old, new, expected in ((threshold, threshold - 0.01, "observed_improvement"),
                                   (threshold - 0.01, threshold, "observed_deterioration"),
                                   (threshold + 1000, threshold + 10, "no_material_observed_change"),
                                   (0.0, threshold - 0.01, "no_material_observed_change")):
            self.setUp()
            with patch.object(outcome, "extract_symptoms", wraps=outcome.extract_symptoms) as extract:
                view = self.compare({"response_time_ms": old}, {"response_time_ms": new})
            self.assertEqual(extract.call_count, 2)
            self.assertEqual(view["observation_result"], expected)

    def test_http_server_error_indicator_does_not_order_arbitrary_status_codes(self):
        for old, new, expected in ((500, 200, "observed_improvement"), (200, 503, "observed_deterioration"),
                                   (200, 404, "no_material_observed_change"), (503, 500, "no_material_observed_change")):
            self.setUp()
            view = self.compare({"http_status": old}, {"http_status": new})
            self.assertEqual(view["observation_result"], expected)
            self.assertIn("HTTP_NON_SERVER_ERRORS_NOT_CLASSIFIED", view["limitations"])

    def test_mixed_changes_preserve_both_supporting_directions(self):
        view = self.compare({"status": "unhealthy", "response_time_ms": 300.0},
                            {"status": "healthy", "response_time_ms": 2000.0})
        self.assertEqual(view["observation_result"], "mixed_changes")
        changes = {item["field"]: item["change"] for item in view["changes"]}
        self.assertEqual(changes["status"], "improved")
        self.assertEqual(changes["response_time_ms"], "deteriorated")

    def test_resource_reductions_alone_do_not_establish_service_improvement(self):
        base = {"status": "unknown", "http_status": None, "response_time_ms": None}
        view = self.compare({**base, "cpu_usage_percent": 99.0, "ram_usage_mib": 5000.0},
                            {**base, "cpu_usage_percent": 0.0, "ram_usage_mib": 0.0})
        self.assertEqual(view["observation_result"], "insufficient_comparable_evidence")
        resources = view["changes"][-2:]
        self.assertEqual([row["delta"] for row in resources], [-99.0, -5000.0])
        self.assertTrue(all(row["change"] == "context_only" for row in resources))

    def test_missing_or_new_primary_evidence_is_not_zero_or_a_disappeared_failure(self):
        for old, new in ((500, None), (None, 200)):
            self.setUp()
            view = self.compare({"http_status": old}, {"http_status": new, "status": "healthy"})
            self.assertEqual(view["observation_result"], "insufficient_comparable_evidence")
            self.assertIn("PRIMARY_EVIDENCE_COVERAGE_CHANGED", view["limitations"])
            row = next(row for row in view["changes"] if row["field"] == "http_status")
            self.assertEqual((row["before"], row["after"]), (old, new))
            self.assertEqual(row["change"], "not_comparable")

    def test_log_absence_and_fewer_hypotheses_cannot_drive_an_improvement(self):
        before, after = self.pair({"logs": [LogEntry(message="database connection refused", level="error")]}, {"logs": []})
        self.assertGreater(len(self.evaluator.evidence.check(before).presentation.report.hypotheses),
                           len(self.evaluator.evidence.check(after).presentation.report.hypotheses))
        view = self.evaluator.compare(before, after).to_dict()
        self.assertEqual(view["observation_result"], "no_material_observed_change")
        self.assertEqual(view["evidence"]["after"]["logs"]["state"], "empty")

    def test_unrecognized_sensitive_log_text_is_never_exported_in_outcome(self):
        view = self.compare({"logs": [LogEntry(message=CANARY)]}, {"logs": None})
        self.assertNotIn(CANARY, json.dumps(view))
        self.assertEqual(view["evidence"]["before"]["logs"]["state"], "present_not_compared")
        self.assertEqual(view["evidence"]["after"]["logs"]["state"], "unavailable")

    def test_actual_setup_diagnosis_and_sanitization_run_for_controlled_samples(self):
        with patch.object(outcome_evidence, "prepare_diagnosis", wraps=outcome_evidence.prepare_diagnosis) as prepare, patch.object(
            outcome_evidence, "sanitize_snapshot", wraps=outcome_evidence.sanitize_snapshot,
        ) as sanitize:
            before, after = self.pair({"logs": [LogEntry(message="password=" + CANARY)]})
        self.assertEqual((prepare.call_count, sanitize.call_count), (2, 2))
        message = self.evaluator.evidence.check(before).presentation.evidence.snapshot.logs[0].message
        self.assertNotIn(CANARY, message)
        self.assertNotIn(CANARY, json.dumps(self.evaluator.compare(before, after).to_dict()))

    def test_provider_context_errors_counts_and_unknown_measurements_are_preserved(self):
        for scenario, state in (("partial_collection", "collection_failed"), ("empty_logs", "empty"),
                                ("missing_logs", "unavailable"), ("withheld_logs", "withheld"), ("partial_logs", "partial")):
            with self.subTest(scenario=scenario):
                result = run_outcome_demo(mock=True, scenario=scenario)
                view = result.to_dict()
                self.assertEqual(result.exit_code, 1)
                after = view["evidence"]["after"]
                self.assertEqual(after["logs"]["state"], state)
                self.assertEqual(after["measurements"]["status"], "unknown")
                self.assertIsNone(after["measurements"]["cpu_usage_percent"])
                if scenario == "partial_collection":
                    errors = [item for item in after["collection_context"]["capabilities"] if item["error_code"]]
                    self.assertEqual([item["http_status"] for item in errors], [403, 429])
                    self.assertEqual([item["retryable"] for item in errors], [False, True])
                if scenario == "partial_logs":
                    self.assertEqual(after["logs"], {"state": "partial", "received": 2, "exported": 1, "withheld": 1})
                self.assertIn("PROVIDER_FIXTURE_COLLECTION_ORDER_NOT_ESTABLISHED", view["limitations"])

    def test_provider_scope_is_validated_against_independent_backend_binding(self):
        inspection = MockSession(mock=True, request=self.evaluator.evidence.request).inspect()
        other = OutcomeEvaluator(mock=True, binding=replace(mock_context_binding(), provider_scope="MOCK-other"))
        with self.assertRaises(OutcomeError) as error:
            other.evidence.retain_provider(inspection)
        self.assertEqual(error.exception.code, "SCOPE_MISMATCH")

    def test_provider_and_canonical_sources_are_not_interchangeable(self):
        inspection = MockSession(mock=True, request=self.evaluator.evidence.request).inspect()
        first = self.evaluator.evidence.retain_provider(inspection)
        second = self.evaluator.evidence.retain_synthetic(self.sample())
        result = self.evaluator.compare(first, second)
        self.assertEqual(result.to_dict()["error_code"], "SOURCE_MISMATCH")
        self.assertIsNotNone(result.to_dict()["evidence"]["before"])

    def test_equal_provider_fixture_times_never_become_ordered_source_observations(self):
        first = self.evaluator.evidence.retain_provider(MockSession(mock=True, request=self.evaluator.evidence.request).inspect())
        self.clock.now += timedelta(days=30)
        second = self.evaluator.evidence.retain_provider(MockSession(mock=True, request=self.evaluator.evidence.request).inspect())
        view = self.evaluator.compare(first, second).to_dict()
        self.assertEqual(view["evaluation_state"], "insufficient_evidence")
        self.assertIsNone(view["evidence"]["before"]["observation_timestamp"])
        self.assertEqual(view["evidence"]["before"]["collection_context"]["collection_started_at"],
                         view["evidence"]["after"]["collection_context"]["collection_started_at"])

    def test_controlled_semantics_mismatch_withholds_comparison(self):
        first = self.evaluator.evidence.retain_synthetic(self.sample())
        self.clock.now += timedelta(seconds=10)
        second = self.evaluator.evidence.retain_synthetic(self.sample(status="healthy"), semantics="controlled-app-probe/2")
        view = self.evaluator.compare(first, second).to_dict()
        self.assertEqual(view["observation_result"], "insufficient_comparable_evidence")
        self.assertIn("MEASUREMENT_SEMANTICS_MISMATCH", view["limitations"])

    def test_unknown_measurement_semantics_cannot_be_asserted_by_arbitrary_text(self):
        with self.assertRaises(OutcomeError) as error:
            self.evaluator.evidence.retain_synthetic(self.sample(), semantics=CANARY)
        self.assertEqual(error.exception.code, "SEMANTICS_UNVERIFIED")
        self.assertNotIn(CANARY, repr(error.exception))

    def test_ordering_future_missing_and_freshness_boundaries(self):
        for offset, now, expected in ((0, 10, "OBSERVATION_ORDER_AMBIGUOUS_OR_REVERSED"),
                                      (-1, 10, "OBSERVATION_ORDER_AMBIGUOUS_OR_REVERSED"),
                                      (11, 10, "OBSERVATION_TIME_IN_FUTURE"),
                                      (None, 10, "OBSERVATION_TIME_UNVERIFIED"),
                                      (10, 61, "CONTROLLED_SAMPLE_TOO_OLD"), (10, 60, None)):
            self.setUp()
            first = self.evaluator.evidence.retain_synthetic(self.sample())
            sample = synthetic_sample(timestamp=None if offset is None else self.start + timedelta(seconds=offset))
            second = self.evaluator.evidence.retain_synthetic(sample)
            self.clock.now = self.start + timedelta(seconds=now)
            view = self.evaluator.compare(first, second).to_dict()
            if expected:
                self.assertEqual(view["evaluation_state"], "insufficient_evidence")
                self.assertIn(expected, view["limitations"])
            else:
                self.assertEqual(view["evaluation_state"], "evaluated")

    def test_timezone_equivalent_instants_are_not_artificially_ordered(self):
        first = self.evaluator.evidence.retain_synthetic(self.sample())
        equivalent = self.start.astimezone(timezone(timedelta(hours=3, minutes=30)))
        second = self.evaluator.evidence.retain_synthetic(synthetic_sample(timestamp=equivalent))
        self.assertEqual(self.evaluator.compare(first, second).exit_code, 1)

    def test_source_instants_do_not_override_reversed_retention_order_or_same_reference(self):
        later = self.evaluator.evidence.retain_synthetic(synthetic_sample(timestamp=self.start + timedelta(seconds=10)))
        earlier = self.evaluator.evidence.retain_synthetic(self.sample())
        self.clock.now += timedelta(seconds=10)
        for before, after in ((earlier, later), (earlier, earlier)):
            view = self.evaluator.compare(before, after).to_dict()
            self.assertEqual(view["evaluation_state"], "insufficient_evidence")
            self.assertIn("RETAINED_COLLECTION_ORDER_NOT_ESTABLISHED", view["limitations"])

    def test_bad_after_preserves_valid_before_and_rejects_json_or_foreign_reference(self):
        first = self.evaluator.evidence.retain_synthetic(self.sample())
        foreign = OutcomeEvaluator(mock=True).evidence.retain_synthetic(self.sample())
        for invalid in (None, {}, {"snapshot_digest": "sha256:" + "0" * 64}, object.__new__(EvidenceRef), foreign):
            result = self.evaluator.compare(first, invalid)
            self.assertEqual(result.exit_code, 3)
            self.assertIsNotNone(result.to_dict()["evidence"]["before"])
            self.assertIsNone(result.to_dict()["evidence"]["after"])

    def test_invalid_before_does_not_export_untrusted_after(self):
        after = self.evaluator.evidence.retain_synthetic(self.sample())
        view = self.evaluator.compare({"token": CANARY}, after).to_dict()
        self.assertEqual(view["evidence"], {"before": None, "after": None})
        self.assertNotIn(CANARY, json.dumps(view))

    def test_mutated_retained_snapshot_report_context_request_and_source_fail_closed(self):
        for mutation in ("snapshot", "report", "request", "source", "context", "scope"):
            self.setUp()
            with self.subTest(mutation=mutation):
                if mutation == "context":
                    first = self.evaluator.evidence.retain_provider(MockSession(mock=True, request=self.evaluator.evidence.request).inspect())
                    second = self.evaluator.evidence.retain_provider(MockSession(mock=True, request=self.evaluator.evidence.request).inspect())
                else:
                    first, second = self.pair()
                entry = self.evaluator.evidence._entries[second]
                if mutation == "snapshot":
                    entry.presentation.evidence.snapshot.response_time_ms = 1.0
                elif mutation == "report":
                    entry.presentation.report.summary = CANARY
                elif mutation == "request":
                    entry.request.details["goal"] = CANARY
                elif mutation == "source":
                    entry.presentation.evidence.snapshot.data_source = DataSource.REAL
                elif mutation == "scope":
                    entry.binding = replace(entry.binding, provider_scope="MOCK-other")
                else:
                    entry.context["snapshot_digest"] = "sha256:" + "0" * 64
                result = self.evaluator.compare(first, second)
                self.assertEqual(result.exit_code, 3)
                self.assertIsNotNone(result.to_dict()["evidence"]["before"])
                self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_bad_capture_field_values_do_not_leak_via_pydantic_warnings_or_exceptions(self):
        stream = io.StringIO()
        sample = self.sample()
        sample.data_source = CANARY
        with redirect_stderr(stream), self.assertRaises(OutcomeError) as error:
            self.evaluator.evidence.retain_synthetic(sample)
        self.assertNotIn(CANARY, stream.getvalue() + repr(error.exception))

    def test_rejected_error_objects_cannot_smuggle_untrusted_error_codes(self):
        error = OutcomeError()
        error.code = CANARY
        view = self.evaluator.rejection(error).to_dict()
        self.assertEqual(view["error_code"], "UNEXPECTED_ERROR")
        self.assertNotIn(CANARY, json.dumps(view))

    def test_service_request_scope_and_source_capture_errors_are_specific(self):
        cases = (("service", "SERVICE_MISMATCH"), ("request", "REQUEST_MISMATCH"),
                 ("scope", "SCOPE_MISMATCH"), ("source", "SOURCE_MISMATCH"))
        for kind, code in cases:
            sample, options = self.sample(), {}
            if kind == "service":
                sample.service_id = CANARY
            elif kind == "source":
                sample.data_source = DataSource.REAL
            elif kind == "scope":
                options["binding"] = replace(mock_context_binding(), provider_scope="MOCK-other")
            else:
                options["request"] = OperationRequest("MOCK-other", "inspect_service", {"service_target": "MOCK-service", "goal": MOCK_GOAL})
            with self.assertRaises(OutcomeError) as error:
                self.evaluator.evidence.retain_synthetic(sample, **options)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn(CANARY, repr(error.exception))

    def test_private_refs_cannot_be_constructed_from_serialized_data(self):
        for cls in (EvidenceRef, SimulatedActionRef):
            with self.assertRaises(OutcomeError):
                cls()
        before, after = self.pair()
        result = self.evaluator.compare(before, after, simulation={"executed": True, "approved": True})
        self.assertEqual(result.to_dict()["error_code"], "INVALID_ACTION_REFERENCE")
        self.assertEqual(result.to_dict()["action"]["status"], "unknown_unverified")

    def test_simulated_action_requires_exact_original_before_binding_and_bracketing(self):
        first = self.evaluator.evidence.retain_synthetic(self.sample())
        self.clock.now += timedelta(seconds=5)
        simulation = self.evaluator.record_simulated_action(first, mock=True)
        self.clock.now += timedelta(seconds=5)
        second = self.evaluator.evidence.retain_synthetic(self.sample(status="healthy"))
        result = self.evaluator.compare(first, second, simulation=simulation)
        view = result.to_dict()
        self.assertEqual(view["action"]["status"], "simulated")
        self.assertEqual(view["post_action_evaluation"], "simulated_only")
        assert_no_execution(self, view)
        duplicate = self.evaluator.evidence.retain_synthetic(synthetic_sample(timestamp=self.start))
        self.assertEqual(self.evaluator.compare(duplicate, second, simulation=simulation).to_dict()["error_code"], "ACTION_MISMATCH")
        too_early = self.evaluator.evidence.retain_synthetic(synthetic_sample(timestamp=self.start + timedelta(seconds=2)))
        blocked = self.evaluator.compare(first, too_early, simulation=simulation).to_dict()
        self.assertIn("SIMULATED_ACTION_NOT_BETWEEN_OBSERVATIONS", blocked["limitations"])

    def test_foreign_or_changed_canonical_action_record_is_not_an_execution_claim(self):
        before, after = self.pair()
        forged = object.__new__(SimulatedActionRef)
        self.assertEqual(self.evaluator.compare(before, after, simulation=forged).exit_code, 3)
        simulation = self.evaluator.record_simulated_action(before, mock=True)
        original = self.evaluator._actions[simulation]
        self.evaluator._actions[simulation] = (*original[:2], replace(original[2], parameters_json='{"grace_period_seconds":60}'), original[3])
        self.assertEqual(self.evaluator.compare(before, after, simulation=simulation).to_dict()["error_code"], "ACTION_MISMATCH")

    def test_existing_approved_workflow_is_not_executed_and_commands_keep_their_semantics(self):
        result = run_outcome_demo(mock=True, scenario="approved_not_executed")
        view = result.to_dict()
        self.assertEqual((result.exit_code, view["evaluation_state"]), (4, "not_performed"))
        self.assertEqual(view["action"]["status"], "not_performed")
        self.assertEqual(view["post_action_evaluation"], "not_performed")
        self.assertIsNone(view["evidence"]["after"])
        assert_no_execution(self, view)
        from integration.workflow import run_mock_workflow
        original = run_mock_workflow(mock=True, scenario="approved_not_executed").to_dict()
        self.assertEqual(original["post_action_evaluation"], "not_performed")
        self.assertEqual(original["state"], "approved_not_executed")
        self.assertEqual(self.evaluator.evaluate_unexecuted_workflow(original).exit_code, 3)

    def test_changed_workflow_action_binding_does_not_reach_post_action_evaluation(self):
        workflow = MockWorkflow(mock=True)
        workflow.submit({"request_id": "MOCK-workflow-request", "operation": "inspect_service",
                         "details": {"service_target": "MOCK-service", "goal": MOCK_GOAL}})
        workflow.inspect()
        workflow.review_action()
        workflow.operator_example("approved_not_executed")
        workflow._operator.intent.parameters["grace_period_seconds"] = 100
        self.assertEqual(self.evaluator.evaluate_unexecuted_workflow(workflow).exit_code, 3)

    def test_no_network_process_live_config_authorization_or_new_approval_for_comparison(self):
        forbidden = AssertionError("Offline comparison only")
        with ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "urllib.request.build_opener", "subprocess.Popen",
                           "os.getenv", "provider.examples.live_smoke.run_from_environment"):
                stack.enter_context(patch(target, side_effect=forbidden))
            authorize = stack.enter_context(patch.object(ApprovalGate, "authorize", side_effect=forbidden))
            production = stack.enter_context(patch.object(triage_context, "diagnose_contextual_request", side_effect=forbidden))
            for scenario in SCENARIOS:
                result = run_outcome_demo(mock=True, scenario=scenario)
                self.assertNotEqual(result.to_dict()["evaluation_state"], "failed", scenario)
                assert_no_execution(self, result.to_dict())
            authorize.assert_not_called()
            production.assert_not_called()
        with patch.object(ApprovalGate, "request_approval", side_effect=forbidden), patch.object(ApprovalGate, "approve", side_effect=forbidden):
            self.assertEqual(run_outcome_demo(mock=True, scenario="simulated_improvement").exit_code, 0)

    def test_safe_clock_and_component_failures_retain_valid_before_evidence(self):
        before, after = self.pair()
        self.evaluator.clock = lambda: None
        view = self.evaluator.compare(before, after).to_dict()
        self.assertEqual(view["error_code"], "CLOCK_UNAVAILABLE")
        self.assertIsNotNone(view["evidence"]["before"])
        self.evaluator.clock = self.clock
        with patch.object(outcome, "extract_symptoms", side_effect=RuntimeError(CANARY)):
            result = self.evaluator.compare(before, after)
        self.assertEqual(result.exit_code, 2)
        self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_unexpected_second_collection_failure_keeps_completed_before_summary(self):
        first = MockSession(mock=True, scenario="exported", request=self.evaluator.evidence.request)
        with patch.object(outcome_fixtures, "MockSession", side_effect=[first, RuntimeError(CANARY)]):
            result = run_outcome_demo(mock=True, scenario="partial_collection")
        self.assertEqual(result.exit_code, 2)
        self.assertIsNotNone(result.to_dict()["evidence"]["before"])
        self.assertIsNone(result.to_dict()["evidence"]["after"])
        self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_opt_in_precedes_dependencies_and_canary_errors_suppress_context(self):
        for options in ({}, {"mock": 1}, {"mock": True, "scenario": CANARY}):
            with patch.object(outcome_fixtures, "OutcomeEvaluator") as construct, self.assertRaises(OutcomeError) as caught:
                run_outcome_demo(**options)
            construct.assert_not_called()
            self.assertNotIn(CANARY, repr(caught.exception))
        stream = io.StringIO()
        logger = logging.Logger("outcome-errors")
        logger.addHandler(logging.StreamHandler(stream))
        try:
            try:
                raise RuntimeError(CANARY)
            except RuntimeError:
                raise OutcomeError(CANARY)
        except OutcomeError:
            logger.exception("Evaluation blocked")
        self.assertNotIn(CANARY, stream.getvalue())

    def test_outputs_summaries_and_reprs_are_detached_from_retained_objects(self):
        before, after = self.pair()
        result = self.evaluator.compare(before, after)
        view = result.to_dict()
        view["evidence"]["before"]["measurements"]["status"] = CANARY
        summary = self.evaluator.evidence.summary(before)
        summary["measurements"]["status"] = CANARY
        self.assertNotIn(CANARY, json.dumps(result.to_dict()) + repr(result) + repr(before) + repr(self.evaluator))
        self.assertEqual(self.evaluator.compare(before, after).exit_code, 0)

    def test_runtime_imports_no_test_harness_and_works_outside_repository_cwd(self):
        result = subprocess.run([sys.executable, "-B", "-c",
            "import sys; from integration.outcome_fixtures import run_outcome_demo; "
            "r=run_outcome_demo(mock=True,scenario='simulated_improvement'); "
            "assert r.exit_code==0; assert not any('.tests' in name for name in sys.modules)"],
            cwd=ROOT.parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


class OutcomeCliTests(unittest.TestCase):
    def cli(self, args, no_site=False):
        return subprocess.run([sys.executable, "-B", *(["-S"] if no_site else []), "-m", "integration.outcome_demo", *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)

    def test_all_scenarios_execute_real_cli_with_expected_exit_and_safe_json(self):
        success = {"improvement", "no_change", "deterioration", "mixed_changes", "simulated_improvement"}
        rejected = {"service_mismatch", "request_mismatch", "action_mismatch", "source_mismatch", "scope_mismatch",
                    "tampered_snapshot", "tampered_context", "bad_after"}
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.cli(["--mock", "--scenario", scenario])
                expected = 4 if scenario == "approved_not_executed" else 0 if scenario in success else 3 if scenario in rejected else 1
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stderr, "")
                view = json.loads(result.stdout)
                self.assertNotEqual(view["evaluation_state"], "failed")
                assert_no_execution(self, view)

    def test_help_missing_opt_in_arguments_and_missing_dependencies_are_safe(self):
        for args in ([], ["--mock", "--scenario", CANARY], ["--mock", "--token", CANARY], ["--mo"]):
            result = self.cli(args)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stderr, "")
            self.assertNotIn(CANARY, result.stdout + result.stderr)
        for args, code in (([], 3), (["--help"], 0), (["--mock"], 2)):
            result = self.cli(args, no_site=True)
            self.assertEqual(result.returncode, code)
            self.assertEqual(result.stderr, "")

    def test_unexpected_exception_interruption_and_output_failure_do_not_print_diagnostics(self):
        for error, expected in ((RuntimeError(CANARY), 2), (KeyboardInterrupt(), 130)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(outcome_fixtures, "run_outcome_demo", side_effect=error), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(["--mock"]), expected)
            self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue())
        stream = unittest.mock.Mock()
        stream.write.side_effect = BrokenPipeError(CANARY)
        stream.fileno.side_effect = OSError()
        with patch("integration.mock_backend.sys.stdout", stream):
            self.assertEqual(main(["--mock"]), 2)

    def test_lazy_import_exceptions_cannot_leak_tracebacks(self):
        import builtins
        original = builtins.__import__

        def broken(name, *args, **kwargs):
            if name == "outcome_fixtures":
                raise RuntimeError(CANARY)
            return original(name, *args, **kwargs)

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("builtins.__import__", side_effect=broken), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--mock"])
        self.assertEqual(code, 2)
        self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
