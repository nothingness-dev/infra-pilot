from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, replace
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from infrapilot_triage import collection_context as triage_context
from infrapilot_triage.authorization import ApprovalGate
from provider import MockLiaraClient
from setup.integration import DependencyInput
from setup.triage import SnapshotEvidence

from integration import service
from integration.errors import MockIntegrationError
from integration.mock_backend import main
from integration.service import MockSession, SCENARIOS, run_mock_backend


CANARY = "MOCK_PRIVATE_SECRET_CANARY_987654"
ROOT = Path(__file__).resolve().parents[2]


def assert_no_execution(test, value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("authorization_consumed", "authorization_granted", "execution_authorized", "execution_performed"):
                test.assertIs(item, False)
            assert_no_execution(test, item)
    elif isinstance(value, list):
        for item in value:
            assert_no_execution(test, item)


class BackendTests(unittest.TestCase):
    def test_actual_three_component_flow_diagnoses_once_and_retains_original_values(self):
        collect = MockLiaraClient.collect_service_observations
        with patch.object(MockLiaraClient, "collect_service_observations", autospec=True, side_effect=collect) as collector, patch.object(
            triage_context, "diagnose", wraps=triage_context.diagnose,
        ) as engine, patch.object(service, "consume_diagnosis", wraps=service.consume_diagnosis) as consumer, patch.object(
            service, "attach_collection_diagnosis", wraps=service.attach_collection_diagnosis,
        ) as companion:
            session = MockSession(mock=True)
            envelope = session.collection_request()
            result = session.finish().to_dict()
        self.assertEqual((collector.call_count, engine.call_count, consumer.call_count, companion.call_count), (1, 1, 1, 1))
        presentation = result["presentation"]
        self.assertEqual(presentation["snapshot"], envelope["snapshot"])
        self.assertEqual(presentation["collection_context"], envelope["collection_context"])
        self.assertEqual(presentation["diagnosis"]["report"]["data_source"], "mock")
        self.assertEqual(result["triage_preview"]["integration_status"], "mock_preview_only")
        self.assertTrue(presentation["diagnosis"]["report"]["missing_information"])
        assert_no_execution(self, result)

    def test_all_scenarios_preserve_log_semantics_and_unknown_measurements(self):
        states = {
            "exported": ("exported", 1, 0), "empty": ("empty", 0, 0),
            "unavailable": ("unavailable", 0, 0), "not_collected": ("not_collected", 0, 0),
            "withheld": ("withheld", 0, 1), "partial_logs": ("partial", 1, 1),
            "partial_failure": ("collection_failed", 0, 0),
        }
        for scenario, expected in states.items():
            with self.subTest(scenario=scenario):
                result = run_mock_backend(mock=True, scenario=scenario)
                output = result.to_dict()
                snapshot = output["presentation"]["snapshot"]
                context = output["presentation"]["collection_context"]
                export = context["log_export"]
                self.assertEqual(tuple(export[k] for k in ("state", "exported", "withheld")), expected)
                self.assertEqual(snapshot["status"], "unknown")
                for name in ("cpu_usage_percent", "ram_usage_mib", "http_status", "response_time_ms", "timestamp"):
                    self.assertIsNone(snapshot[name])
                self.assertEqual(result.exit_code, 1 if scenario in ("unavailable", "partial_failure") else 0)
                if scenario == "empty":
                    self.assertEqual(snapshot["logs"], [])
                elif not expected[1]:
                    self.assertIsNone(snapshot["logs"])
                assert_no_execution(self, output)

    def test_partial_failures_preserve_both_codes_and_derived_setup_view(self):
        output = run_mock_backend(mock=True).to_dict()
        context = output["presentation"]["collection_context"]
        errors = output["presentation"]["display"]["collection_errors"]
        self.assertEqual(errors, [item for item in context["capabilities"] if item["error_code"] is not None])
        self.assertEqual([item["http_status"] for item in errors], [403, 429])
        self.assertEqual([item["retryable"] for item in errors], [False, True])
        self.assertEqual(output["status"], "partial")
        self.assertEqual(output["presentation"]["state"], "diagnosis_associated")

    def test_opt_in_and_allowlisted_service_selection_precede_collection(self):
        with patch.object(service, "build_mock_context") as collect:
            for options in ({}, {"mock": 1}, {"mock": True, "scenario": CANARY},
                            {"mock": True, "service_id": CANARY}, {"mock": True, "scenario": []}):
                with self.subTest(options=repr(options)), self.assertRaises(MockIntegrationError) as caught:
                    run_mock_backend(**options)
                self.assertNotIn(CANARY, repr(caught.exception))
            collect.assert_not_called()

    def test_mutated_snapshot_context_version_and_source_fail_before_diagnosis(self):
        session = MockSession(mock=True)
        for change in (
            lambda r: r["snapshot"].update(service_id="other"),
            lambda r: r["snapshot"].update(data_source="real"),
            lambda r: r["collection_context"].update(contract_version=CANARY),
            lambda r: r["collection_context"]["capabilities"][2].update(http_status=404),
            lambda r: r["collection_context"]["limitations"].clear(),
            lambda r: r.update(extra=CANARY),
        ):
            request = session.collection_request()
            change(request)
            request["collection_context"]["snapshot_digest"] = triage_context.context_digest(request["snapshot"])
            with patch.object(triage_context, "diagnose") as engine:
                with self.assertRaises(MockIntegrationError) as caught:
                    session.finish(request)
                engine.assert_not_called()
            self.assertEqual(caught.exception.code, "CONTEXT_REJECTED")
            self.assertNotIn(CANARY, str(caught.exception))

    def test_identical_snapshot_cannot_accept_swapped_collection_metadata(self):
        withheld = MockSession(mock=True, scenario="withheld")
        unavailable = MockSession(mock=True, scenario="unavailable")
        self.assertEqual(withheld.collection_request()["snapshot"], unavailable.collection_request()["snapshot"])
        with self.assertRaises(MockIntegrationError):
            withheld.finish(unavailable.collection_request())

    def test_project_scope_or_service_binding_change_is_rejected(self):
        for changes in ({"project_name": "other"}, {"provider_scope": "other"},
                        {"service_id": "other"}, {"is_mock": False}):
            with self.subTest(changes=changes):
                session = MockSession(mock=True)
                session._binding = replace(session._binding, **changes)
                with self.assertRaises(MockIntegrationError) as caught:
                    session.finish()
                self.assertEqual(caught.exception.code, "CONTEXT_REJECTED")

    def test_changed_setup_request_snapshot_or_source_association_fails_before_diagnosis(self):
        for mutation in ("request", "snapshot", "source"):
            with self.subTest(mutation=mutation):
                session = MockSession(mock=True)
                if mutation == "request":
                    session._request.details["goal"] = "Changed request"
                elif mutation == "snapshot":
                    session._evidence.snapshot.service_id = "other-service"
                else:
                    association = session._evidence.association
                    metadata = replace(association.metadata, provenance="external")
                    session._evidence = SnapshotEvidence(session._evidence.snapshot, DependencyInput(
                        True, "external:other", metadata=metadata,
                    ))
                with patch.object(triage_context, "diagnose") as engine:
                    with self.assertRaises(MockIntegrationError) as caught:
                        session.finish()
                    engine.assert_not_called()
                self.assertEqual(caught.exception.code, "SETUP_ASSOCIATION_FAILED")

    def test_mismatched_generated_report_is_rejected(self):
        session = MockSession(mock=True)
        original = triage_context.diagnose

        def wrong_report(snapshot):
            report = original(snapshot)
            report.service_id = "other-service"
            return report

        with patch.object(triage_context, "diagnose", side_effect=wrong_report):
            with self.assertRaises(MockIntegrationError) as caught:
                session.finish()
        self.assertEqual(caught.exception.code, "DIAGNOSIS_FAILED")

    def test_fixture_log_policy_withholds_sensitive_text_before_associations(self):
        import provider.fixtures
        original = provider.fixtures.mock_payload

        def sensitive(capability, *args):
            if capability == "logs":
                return [{"message": "password=" + CANARY, "type": "stdout", "datetime": None}]
            return original(capability, *args)

        with patch("provider.client.mock_payload", side_effect=sensitive):
            session = MockSession(mock=True, scenario="exported")
            envelope = session.collection_request()
            result = session.finish()
        text = json.dumps(envelope) + json.dumps(result.to_dict()) + repr(session) + repr(result)
        self.assertNotIn(CANARY, text)
        self.assertEqual(envelope["collection_context"]["log_export"]["state"], "withheld")
        self.assertEqual(envelope["collection_context"]["log_export"]["withheld"], 1)

    def test_detached_return_values_do_not_change_retained_state(self):
        session = MockSession(mock=True)
        request = session.collection_request()
        request["snapshot"]["service_id"] = "changed"
        result = session.finish()
        output = result.to_dict()
        output["presentation"]["collection_context"]["limitations"].clear()
        self.assertTrue(result.to_dict()["presentation"]["collection_context"]["limitations"])
        self.assertEqual(session.collection_request()["snapshot"]["service_id"], "MOCK-service")
        with self.assertRaises(FrozenInstanceError):
            result._json = CANARY

    def test_no_external_io_environment_configuration_or_approval_call(self):
        forbidden = AssertionError("Mock integration must stay offline and non-consuming")
        with ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "urllib.request.build_opener", "subprocess.Popen",
                           "provider.examples.live_smoke.run_from_environment", "os.getenv"):
                stack.enter_context(patch(target, side_effect=forbidden))
            for method in ("authorize", "request_approval", "approve", "reject"):
                stack.enter_context(patch.object(ApprovalGate, method, side_effect=forbidden))
            production = stack.enter_context(patch.object(triage_context, "diagnose_contextual_request", side_effect=forbidden))
            for scenario in SCENARIOS:
                assert_no_execution(self, run_mock_backend(mock=True, scenario=scenario).to_dict())
            production.assert_not_called()

    def test_component_exceptions_cannot_leak_through_public_boundary_or_logging(self):
        output, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        logger = logging.Logger("integration-safe-errors")
        logger.addHandler(logging.StreamHandler(logs))
        with patch.object(service, "build_mock_context", side_effect=RuntimeError(CANARY)), redirect_stdout(output), redirect_stderr(stderr):
            try:
                run_mock_backend(mock=True)
            except MockIntegrationError as error:
                logger.exception("Mock failure")
                self.assertNotIn(CANARY, repr(error))
            else:
                self.fail("Expected a safe integration failure")
        self.assertNotIn(CANARY, logs.getvalue() + output.getvalue() + stderr.getvalue())


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        return subprocess.run([sys.executable, "-B", "-m", "integration.mock_backend", *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=30)

    def test_actual_cli_runs_all_scenarios_with_documented_exit_codes(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.run_cli(["--mock", "--scenario", scenario])
                self.assertEqual(result.returncode, 1 if scenario in ("unavailable", "partial_failure") else 0, result.stderr)
                self.assertEqual(result.stderr, "")
                output = json.loads(result.stdout)
                self.assertEqual(output["scenario"], scenario)
                assert_no_execution(self, output)

    def test_missing_opt_in_invalid_arguments_and_values_do_not_echo_sensitive_inputs(self):
        for args in ([], ["--token", CANARY], ["--mock", "--scenario", CANARY], ["--mock", "--service", CANARY]):
            with self.subTest(args=args):
                result = self.run_cli(args)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(result.stderr, "")
                self.assertNotIn(CANARY, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_opt_in_validation_and_safe_missing_dependencies_without_site_packages(self):
        for args, code in (([], 3), (["--mock"], 2)):
            result = subprocess.run([sys.executable, "-B", "-S", "-m", "integration.mock_backend", *args],
                                    cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, code)
            self.assertEqual(result.stderr, "")
            self.assertIn("error_code", json.loads(result.stdout))

    def test_cli_unexpected_failure_interrupt_and_output_failure_are_safe(self):
        for error, expected in ((RuntimeError(CANARY), 2), (KeyboardInterrupt(), 130)):
            output, stderr = io.StringIO(), io.StringIO()
            with patch.object(service, "run_mock_backend", side_effect=error), redirect_stdout(output), redirect_stderr(stderr):
                self.assertEqual(main(["--mock"]), expected)
            self.assertNotIn(CANARY, output.getvalue() + stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
        stream = unittest.mock.Mock()
        stream.write.side_effect = BrokenPipeError(CANARY)
        stream.fileno.side_effect = OSError()
        with patch("integration.mock_backend.sys.stdout", stream):
            self.assertEqual(main(["--mock"]), 2)

    def test_help_is_static_and_does_not_run_backend(self):
        with patch.object(service, "run_mock_backend") as run:
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
