"""Behavioral tests for actual request/collection/diagnosis/approval composition."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import timedelta
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from infrapilot_triage import collection_context as triage_context
from infrapilot_triage import ApprovalGate, ApprovalState, Permission
from provider import MockLiaraClient
from setup import application, approval_workflow

from integration import service, workflow
from integration.errors import MockIntegrationError
from integration.mock_approval import MockClock, OperatorApprovalExample
from integration.workflow import MOCK_GOAL, MockWorkflow, SCENARIOS, run_mock_workflow
from integration.workflow_demo import main


ROOT = Path(__file__).resolve().parents[2]
CANARY = "PRIVATE_WORKFLOW_CANARY_83173"


def payload(**details):
    return {"request_id": "MOCK-workflow-request", "operation": "inspect_service", "details": {
        "service_target": "MOCK-service", "goal": MOCK_GOAL, **details,
    }}


def ready_session(**options):
    session = MockWorkflow(mock=True, **options)
    session.submit(payload())
    result = session.inspect()
    if result.exit_code not in (0, 1):
        raise AssertionError("Expected an actual completed Mock inspection")
    return session


def non_executing(test, value):
    if isinstance(value, dict):
        for name, item in value.items():
            if name in ("authorization_consumed", "authorization_granted", "execution_authorized",
                        "execution_performed", "remediation_verified"):
                test.assertIs(item, False)
            if name == "authorization_id":
                test.assertIsNone(item)
            non_executing(test, item)
    elif isinstance(value, list):
        for item in value:
            non_executing(test, item)


class WorkflowTests(unittest.TestCase):
    def test_real_stages_run_once_and_setup_preparation_uses_actual_associations(self):
        with patch.object(workflow, "submit_request", wraps=application.submit_request) as submit, patch.object(
            workflow, "supply_information", wraps=application.supply_information,
        ) as complete, patch.object(
            MockLiaraClient, "collect_service_observations", autospec=True,
            side_effect=MockLiaraClient.collect_service_observations,
        ) as collect, patch.object(triage_context, "diagnose", wraps=triage_context.diagnose) as diagnose, patch.object(
            service, "consume_diagnosis", wraps=service.consume_diagnosis,
        ) as consume, patch.object(
            approval_workflow.SetupApprovalWorkflow, "review_action", autospec=True,
            side_effect=approval_workflow.SetupApprovalWorkflow.review_action,
        ) as review:
            result = run_mock_workflow(mock=True, scenario="complete_information")
        view = result.to_dict()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((submit.call_count, complete.call_count, collect.call_count,
                          diagnose.call_count, consume.call_count, review.call_count), (2, 1, 1, 1, 1, 1))
        stages = view["stages"]
        self.assertEqual(stages["intake"]["state"], "needs_information")
        self.assertEqual(stages["completion"]["state"], "blocked")
        self.assertEqual(stages["preparation"]["state"], "plan_prepared")
        presentation = stages["inspection"]["presentation"]
        fingerprint = presentation["request_fingerprint"]
        self.assertEqual(stages["action_review"]["result"]["binding"]["request_fingerprint"], fingerprint)
        self.assertEqual(stages["action_review"]["result"]["binding"]["diagnosis_binding"],
                         presentation["diagnosis"]["binding"])
        self.assertEqual(stages["collection"]["collection_context"], presentation["collection_context"])
        self.assertEqual([item["available"] for item in stages["preparation"]["plan"]["dependencies"]],
                         [True, True, False, False, False])
        non_executing(self, view)

    def test_incomplete_intake_cannot_collect_review_or_approve(self):
        with patch.object(service, "build_mock_context") as collect, patch.object(ApprovalGate, "request_approval") as gate:
            session = MockWorkflow(mock=True)
            result = session.submit({**payload(), "details": {}})
            self.assertEqual(result.to_dict()["state"], "needs_information")
            self.assertEqual(session.inspect().exit_code, 4)
            self.assertEqual(session.review_action().exit_code, 2)
            self.assertEqual(session.operator_example().exit_code, 2)
            collect.assert_not_called()
            gate.assert_not_called()

    def test_rejected_inputs_and_unknown_field_names_never_reach_serialized_output(self):
        cases = [
            None, CANARY, {**payload(), CANARY: CANARY}, payload(**{CANARY: CANARY}),
            payload(goal="password=" + CANARY), {**payload(), "request_id": CANARY},
            payload(service_target=CANARY), {**payload(), "operation": CANARY},
        ]
        with patch.object(service, "build_mock_context") as collect:
            for value in cases:
                with self.subTest(value_type=type(value).__name__):
                    session = MockWorkflow(mock=True)
                    result = session.submit(value)
                    self.assertEqual(result.exit_code, 3)
                    self.assertEqual(session.inspect().exit_code, 3)
                    self.assertNotIn(CANARY, json.dumps(result.to_dict()) + repr(session) + repr(result))
            collect.assert_not_called()

    def test_completion_preserves_identity_rejects_envelope_claims_and_changed_target(self):
        for extra in ({"request_id": CANARY}, {"operation": CANARY}, {"approved": True},
                      {CANARY: CANARY}, {"service_target": CANARY}, [CANARY]):
            with self.subTest(extra_type=type(extra).__name__):
                session = MockWorkflow(mock=True)
                session.submit({**payload(), "details": {}})
                with patch.object(service, "build_mock_context") as collect:
                    result = session.supply_information(extra)
                    self.assertEqual(result.exit_code, 3)
                    self.assertEqual(session.inspect().exit_code, 3)
                    collect.assert_not_called()
                self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_multiple_information_steps_and_cached_inspection_do_not_repeat_diagnosis(self):
        session = MockWorkflow(mock=True)
        session.submit({**payload(), "details": {}})
        self.assertEqual(session.supply_information({"service_target": "MOCK-service"}).exit_code, 4)
        self.assertEqual(session.supply_information({"goal": MOCK_GOAL}).exit_code, 0)
        with patch.object(triage_context, "diagnose", wraps=triage_context.diagnose) as diagnose:
            first, second = session.inspect(), session.inspect()
        self.assertEqual(first.to_dict(), second.to_dict())
        diagnose.assert_called_once()

    def test_revision_invalidates_old_inspection_review_and_approval(self):
        session = ready_session()
        session.review_action()
        session.operator_example()
        old = session._operator
        result = session.supply_information({"goal": "Review this synthetic service again"})
        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(session._inspection)
        self.assertIsNone(session._operator)
        self.assertNotIn("operator_example", result.to_dict()["stages"])
        self.assertEqual(session.operator_example().exit_code, 2)
        self.assertEqual(old.store.get(old._identifier).state, ApprovalState.PENDING)
        session.submit(payload())
        session.inspect()
        session.review_action()
        session.operator_example()
        self.assertIsNot(session._operator.store, old.store)

    def test_collection_scenarios_keep_partial_errors_log_counts_and_unknown_telemetry(self):
        for scenario in ("partial_failure", "empty", "unavailable", "withheld", "partial_logs", "not_collected"):
            with self.subTest(scenario=scenario):
                result = run_mock_workflow(mock=True, scenario=scenario)
                output = result.to_dict()
                view = output["stages"]["inspection"]["presentation"]
                self.assertEqual(output["collection_status"], "partial" if scenario in ("partial_failure", "unavailable") else "complete")
                self.assertEqual(result.exit_code, 1 if scenario in ("partial_failure", "unavailable") else 0)
                self.assertEqual(view["snapshot"]["status"], "unknown")
                for key in ("cpu_usage_percent", "ram_usage_mib", "response_time_ms", "timestamp", "http_status"):
                    self.assertIsNone(view["snapshot"][key])
                if scenario == "partial_failure":
                    self.assertEqual([item["http_status"] for item in view["display"]["collection_errors"]], [403, 429])
                if scenario == "empty":
                    self.assertEqual(view["snapshot"]["logs"], [])
                if scenario == "withheld":
                    self.assertIsNone(view["snapshot"]["logs"])
                    self.assertEqual(view["collection_context"]["log_export"]["withheld"], 1)
                if scenario == "partial_logs":
                    self.assertEqual(view["collection_context"]["log_export"],
                                     {"state": "partial", "received": 2, "exported": 1, "withheld": 1})
                non_executing(self, output)

    def test_only_explicit_mapping_selects_read_only_intent_and_unknown_proposals_are_unmapped(self):
        session = ready_session()
        output = session.review_action().to_dict()
        action = output["stages"]["action_review"]["result"]["binding"]["canonical_action"]
        self.assertEqual(action["action_type"], "refresh_observations")
        self.assertEqual(action["parameters"], {})
        for proposal in (CANARY, "restart_service", True):
            result = session.review_action(proposal)
            self.assertEqual((result.exit_code, result.to_dict()["state"]), (4, "action_unmapped"))
            self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_actual_policy_denies_operator_selected_destructive_example(self):
        result = run_mock_workflow(mock=True, scenario="policy_denied")
        review = result.to_dict()["stages"]["action_review"]
        self.assertEqual(result.exit_code, 4)
        self.assertFalse(review["result"]["policy_decision"]["allowed"])
        self.assertEqual(review["result"]["policy_decision"]["reason"], "unsupported_action")
        self.assertIn("not_diagnosis_derived", review["relationship"])

    def test_mock_approval_states_are_real_records_with_original_gate_fields(self):
        expected = {
            "approval_pending": ("pending", ["approval_requested"]),
            "approved_not_executed": ("approved", ["approval_requested", "approval_granted"]),
            "approval_rejected": ("rejected", ["approval_requested", "approval_rejected"]),
            "approval_expired": ("expired", ["approval_requested", "approval_expired", "authorization_denied"]),
            "unauthenticated": (None, ["authorization_denied"]),
            "permission_denied": (None, ["authorization_denied"]),
        }
        for scenario, (state, kinds) in expected.items():
            with self.subTest(scenario=scenario):
                result = run_mock_workflow(mock=True, scenario=scenario)
                view = result.to_dict()
                example = view["stages"]["operator_example"]
                self.assertEqual((result.exit_code, view["state"]), (4, scenario))
                current = example["current_approval"]
                self.assertEqual(current["state"] if current else None, state)
                self.assertEqual([event["kind"] for event in example["audit_events"]], kinds)
                self.assertIn("not_diagnosis_derived", example["relationship"])
                self.assertEqual(example["provider_operation_support"], "unverified")
                for decision in example["decisions"]:
                    self.assertFalse(decision["allowed"])
                    self.assertTrue(decision["audit_recorded"])
                if state == "approved":
                    self.assertNotEqual(current["requested_by"], current["approved_by"])
                    self.assertIsNone(current["consumed_by"])
                non_executing(self, view)

    def test_partial_collection_does_not_disappear_when_approval_is_blocked(self):
        session = ready_session(collection_scenario="partial_failure")
        session.review_action()
        result = session.operator_example("approved_not_executed")
        self.assertEqual(result.exit_code, 4)
        self.assertEqual(result.to_dict()["collection_status"], "partial")
        self.assertEqual(len(result.to_dict()["stages"]["inspection"]["presentation"]["display"]["collection_errors"]), 2)

    def test_clock_is_injectable_and_approval_expires_at_exact_boundary(self):
        clock = MockClock()
        session = ready_session(clock=clock)
        example = OperatorApprovalExample(session._inspection, clock=clock)
        pending = example.request(authentication=example.identity.requester_session)
        clock.now = pending.request.expires_at - timedelta(microseconds=1)
        approved = example.decide(approve=True, authentication=example.identity.approver_session)
        self.assertEqual(approved.request.state, ApprovalState.APPROVED)
        clock.now = pending.request.expires_at
        expired = example.decide(approve=False, authentication=example.identity.approver_session)
        self.assertEqual(expired.reason.value, "approval_expired")
        self.assertEqual(example.store.get(pending.request.request_id).state, ApprovalState.EXPIRED)

    def test_foreign_session_cannot_grant_and_no_mock_identity_has_execute_permission(self):
        session = ready_session()
        first = OperatorApprovalExample(session._inspection, clock=MockClock())
        second = OperatorApprovalExample(session._inspection, clock=MockClock())
        pending = first.request(authentication=first.identity.requester_session)
        denied = first.decide(approve=True, authentication=second.identity.approver_session)
        self.assertEqual(denied.reason.value, "unauthenticated")
        self.assertEqual(first.store.get(pending.request.request_id).state, ApprovalState.PENDING)
        for actor in (first.identity.requester, first.identity.approver):
            self.assertFalse(first.identity.is_authorized(actor, first.review.policy.action, Permission.EXECUTE))
        self.assertEqual(second.store.events, ())

    def test_request_target_snapshot_context_report_and_action_tampering_fail_before_transition(self):
        for change in ("request", "target", "snapshot", "context", "report", "action", "foreign_inspection"):
            with self.subTest(change=change):
                session = ready_session()
                example = OperatorApprovalExample(session._inspection, clock=MockClock())
                example.request(authentication=example.identity.requester_session)
                if change == "request":
                    example.inspection.request.details["goal"] = "Review this synthetic service again"
                elif change == "target":
                    example.inspection.request.details["service_target"] = "MOCK-other"
                elif change == "snapshot":
                    example.inspection.presentation.evidence.snapshot.service_id = "MOCK-other"
                elif change == "context":
                    altered = example.inspection.result.to_dict()
                    altered["presentation"]["collection_context"]["limitations"] = []
                    bad = service.MockResult(json.dumps(altered), 0)
                    example.inspection = replace(example.inspection, result=bad)
                elif change == "report":
                    example.inspection.presentation.report.summary = CANARY
                elif change == "action":
                    example.intent.parameters["grace_period_seconds"] = 40
                else:
                    example.inspection = ready_session(collection_scenario="withheld")._inspection
                with patch.object(example.gate, "approve") as approve:
                    with self.assertRaises((MockIntegrationError, ValueError)):
                        example.decide(approve=True, authentication=example.identity.approver_session)
                    approve.assert_not_called()
                self.assertEqual(example.store.get(example._identifier).state, ApprovalState.PENDING)

    def test_orchestrator_rechecks_accepted_request_and_detects_mutated_retained_report(self):
        for change in ("request", "report"):
            session = ready_session()
            if change == "request":
                session._accepted["details"]["goal"] = "Review this synthetic service again"
            else:
                session._inspection.presentation.report.summary = CANARY
            result = session.review_action()
            self.assertEqual(result.exit_code, 2)
            self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_failed_diagnosis_retains_valid_collection_and_cannot_be_retried_as_success(self):
        session = MockWorkflow(mock=True)
        session.submit(payload())
        with patch.object(triage_context, "diagnose", side_effect=RuntimeError(CANARY)):
            result = session.inspect()
        output = result.to_dict()
        self.assertEqual((result.exit_code, output["stage"]), (2, "diagnosis"))
        self.assertIn("collection_context", output["stages"]["collection"])
        self.assertEqual(output["collection_status"], "complete")
        self.assertNotIn("inspection", output["stages"])
        self.assertEqual(session.inspect().exit_code, 2)
        self.assertNotIn(CANARY, json.dumps(output))

    def test_late_failure_keeps_prior_outputs_and_safe_pending_approval(self):
        for where in ("preparation", "review", "approve"):
            with self.subTest(where=where):
                session = MockWorkflow(mock=True)
                session.submit(payload())
                if where == "preparation":
                    with patch.object(workflow, "submit_request", side_effect=RuntimeError(CANARY)):
                        result = session.inspect()
                    self.assertEqual(session.inspect().exit_code, 2)
                else:
                    session.inspect()
                    if where == "review":
                        with patch.object(approval_workflow.SetupApprovalWorkflow, "review_action", side_effect=RuntimeError(CANARY)):
                            result = session.review_action()
                    else:
                        session.review_action()
                        with patch.object(workflow.OperatorApprovalExample, "decide", side_effect=RuntimeError(CANARY)):
                            result = session.operator_example("approved_not_executed")
                        self.assertEqual(result.to_dict()["stages"]["operator_example"]["current_approval"]["state"], "pending")
                self.assertEqual(result.exit_code, 2)
                self.assertIn("inspection", result.to_dict()["stages"])
                self.assertNotIn(CANARY, json.dumps(result.to_dict()))

    def test_collection_exception_retains_intake_and_no_diagnosis_or_approval_is_started(self):
        session = MockWorkflow(mock=True)
        session.submit(payload())
        with patch.object(service, "build_mock_context", side_effect=RuntimeError(CANARY)), patch.object(
            triage_context, "diagnose",
        ) as diagnose, patch.object(ApprovalGate, "request_approval") as approve:
            result = session.inspect()
        view = result.to_dict()
        self.assertEqual((result.exit_code, view["stage"]), (2, "collection"))
        self.assertIn("intake", view["stages"])
        self.assertNotIn("inspection", view["stages"])
        self.assertNotIn(CANARY, json.dumps(view))
        diagnose.assert_not_called()
        approve.assert_not_called()

    def test_repeated_operator_example_is_blocked_without_second_request_or_grant(self):
        session = ready_session()
        session.review_action()
        first = session.operator_example("approved_not_executed")
        with patch.object(ApprovalGate, "request_approval") as request, patch.object(ApprovalGate, "approve") as approve:
            second = session.operator_example("approved_not_executed")
        self.assertEqual(second.to_dict()["state"], "blocked")
        self.assertEqual(first.to_dict()["stages"]["operator_example"], second.to_dict()["stages"]["operator_example"])
        request.assert_not_called()
        approve.assert_not_called()

    def test_rejected_example_cannot_be_reapproved_and_revoked_mock_permission_fails_closed(self):
        session = ready_session()
        example = OperatorApprovalExample(session._inspection, clock=MockClock())
        example.request(authentication=example.identity.requester_session)
        example.identity.permitted = False
        denied = example.decide(approve=True, authentication=example.identity.approver_session)
        self.assertEqual(denied.reason.value, "not_authorized")
        example.identity.permitted = True
        example.decide(approve=False, authentication=example.identity.approver_session)
        denied = example.decide(approve=True, authentication=example.identity.approver_session)
        self.assertEqual(denied.reason.value, "approval_rejected")
        self.assertEqual(example.store.get(example._identifier).state, ApprovalState.REJECTED)

    def test_invalid_clock_returns_original_fail_closed_gate_decision(self):
        session = ready_session(clock=lambda: None)
        session.review_action()
        result = session.operator_example()
        example = result.to_dict()["stages"]["operator_example"]
        self.assertEqual(result.exit_code, 4)
        self.assertEqual(example["decisions"][0]["reason"], "clock_unavailable")
        self.assertFalse(example["decisions"][0]["audit_recorded"])
        self.assertIsNone(example["current_approval"])
        non_executing(self, result.to_dict())

    def test_no_network_live_config_processes_authorization_consumption_or_test_imports(self):
        forbidden = AssertionError("Offline non-consuming workflow")
        with ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "urllib.request.build_opener", "subprocess.Popen",
                           "os.getenv", "provider.examples.live_smoke.run_from_environment"):
                stack.enter_context(patch(target, side_effect=forbidden))
            authorize = stack.enter_context(patch.object(ApprovalGate, "authorize", side_effect=forbidden))
            production = stack.enter_context(patch.object(triage_context, "diagnose_contextual_request", side_effect=forbidden))
            for scenario in SCENARIOS:
                output = run_mock_workflow(mock=True, scenario=scenario).to_dict()
                self.assertNotEqual(output["state"], "failed", scenario)
                non_executing(self, output)
            authorize.assert_not_called()
            production.assert_not_called()
        # Check runtime imports in a fresh process, not test-runner sys.modules.
        probe = subprocess.run([sys.executable, "-B", "-c",
            "import sys; from integration.workflow import run_mock_workflow; "
            "run_mock_workflow(mock=True,scenario='approved_not_executed'); "
            "assert not any('.tests' in x or x.endswith('.demo') for x in sys.modules)"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_raw_log_canary_is_withheld_before_any_workflow_binding_or_output(self):
        import provider.fixtures
        original = provider.fixtures.mock_payload

        def sensitive(capability, *args):
            if capability == "logs":
                return [{"message": "Authorization: Bearer " + CANARY, "type": "stdout", "datetime": None}]
            return original(capability, *args)

        output, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with patch("provider.client.mock_payload", side_effect=sensitive), redirect_stdout(output), redirect_stderr(stderr):
                result = run_mock_workflow(mock=True, scenario="approved_not_executed")
        finally:
            logging.getLogger().removeHandler(handler)
        text = json.dumps(result.to_dict()) + repr(result) + output.getvalue() + stderr.getvalue() + logs.getvalue()
        self.assertNotIn(CANARY, text)
        self.assertEqual(result.to_dict()["stages"]["collection"]["collection_context"]["log_export"]["state"], "withheld")

    def test_opt_in_configuration_validation_precedes_all_components(self):
        with patch.object(service, "build_mock_context") as collect:
            for options in ({}, {"mock": 1}, {"mock": True, "scenario": CANARY}, {"mock": True, "scenario": []}):
                with self.assertRaises(MockIntegrationError) as caught:
                    run_mock_workflow(**options)
                self.assertNotIn(CANARY, repr(caught.exception))
            collect.assert_not_called()

    def test_results_are_detached_and_repr_does_not_dump_payloads(self):
        session = ready_session()
        first = session.review_action()
        view = first.to_dict()
        view["stages"]["inspection"]["presentation"]["snapshot"]["logs"] = CANARY
        self.assertNotIn(CANARY, json.dumps(first.to_dict()) + repr(first) + repr(session) + repr(session._inspection))

    def test_invalid_review_options_cannot_reuse_previous_allowed_review(self):
        session = ready_session()
        session.review_action()
        self.assertEqual(session.review_action(deny_example=CANARY).exit_code, 3)
        self.assertEqual(session.operator_example().exit_code, 4)

    def test_backend_session_rejects_invalid_custom_request_before_collection(self):
        from setup.models import OperationRequest
        with patch.object(service, "build_mock_context") as collect:
            for request in (OperationRequest("MOCK-id", "inspect_service", {}),
                            OperationRequest("MOCK-id", "inspect_service", {"service_target": "MOCK-other", "goal": MOCK_GOAL})):
                with self.assertRaises(MockIntegrationError):
                    service.MockSession(mock=True, request=request)
            collect.assert_not_called()


class WorkflowCliTests(unittest.TestCase):
    def run_cli(self, args, *, no_site=False):
        return subprocess.run([sys.executable, "-B", *(["-S"] if no_site else []),
                               "-m", "integration.workflow_demo", *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=30)

    def test_all_documented_scenarios_execute_actual_cli_with_expected_status_and_exit(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.run_cli(["--mock", "--scenario", scenario])
                expected = (3 if scenario in ("invalid_completion", "changed_target") else
                            1 if scenario in ("partial_failure", "unavailable") else
                            0 if scenario in ("complete", "complete_information", "empty", "not_collected", "withheld", "partial_logs") else 4)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stderr, "")
                output = json.loads(result.stdout)
                self.assertNotEqual(output["state"], "failed")
                non_executing(self, output)

    def test_safe_argument_failures_help_and_dependencies(self):
        for args in ([], ["--mock", "--token", CANARY], ["--mock", "--scenario", CANARY], ["--mo"]):
            result = self.run_cli(args)
            self.assertEqual(result.returncode, 3)
            self.assertNotIn(CANARY, result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")
        for args, code in (([], 3), (["--mock"], 2), (["--help"], 0)):
            result = self.run_cli(args, no_site=True)
            self.assertEqual(result.returncode, code)
            self.assertEqual(result.stderr, "")

    def test_unexpected_failure_interrupt_and_broken_pipe_are_safe(self):
        for error, code in ((RuntimeError(CANARY), 2), (KeyboardInterrupt(), 130)):
            output, stderr = io.StringIO(), io.StringIO()
            with patch.object(workflow, "run_mock_workflow", side_effect=error), redirect_stdout(output), redirect_stderr(stderr):
                self.assertEqual(main(["--mock"]), code)
            self.assertNotIn(CANARY, output.getvalue() + stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
        stream = unittest.mock.Mock()
        stream.write.side_effect = BrokenPipeError(CANARY)
        stream.fileno.side_effect = OSError()
        with patch("integration.mock_backend.sys.stdout", stream):
            self.assertEqual(main(["--mock"]), 2)
        stream.write.side_effect = ValueError(CANARY)
        with patch("integration.mock_backend.sys.stdout", stream):
            self.assertEqual(main(["--mock"]), 2)


if __name__ == "__main__":
    unittest.main()
