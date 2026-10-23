"""Real read-only composition exercised at urllib, always without the network."""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
from email.message import Message
import io
import json
import logging
import os
import socket
import subprocess
import sys
import unittest
import urllib.error
import urllib.response
from unittest.mock import MagicMock, patch

from infrapilot_triage import engine
from infrapilot_triage import collection_context as triage_context
from infrapilot_triage.authorization import ApprovalGate
from provider import CollectionContextAdapter, LiaraClient, MockLiaraClient, ProviderConfig, ServiceBinding
from provider.environment import read_live_settings
from setup.integration import request_fingerprint
from setup.models import OperationRequest

from integration import readonly, readonly_inspection
from integration.readonly_config import read_inspection_settings
from integration.readonly_report import ReadOnlyError


TOKEN = "canary-private-api-token-6f820"
PROJECT = "canary-private-project"
SCOPE = "canary-private-account"
SERVICE = "canary-private-service"
RAW = "unreviewed-application-secret-f090"
ENV = {"LIARA_API_TOKEN": TOKEN, "LIARA_PROJECT_NAME": PROJECT,
       "LIARA_SERVICE_ID": SERVICE, "LIARA_PROVIDER_SCOPE": SCOPE}
SINCE = "opaque-window-canary"


class ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.socket", "socket.create_connection", "subprocess.Popen"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("External I/O forbidden")))
        for method in ("authorize", "request_approval", "approve", "reject"):
            self.stack.enter_context(patch.object(ApprovalGate, method, side_effect=AssertionError("Approval forbidden")))
        for name in ("diagnose_contextual_request", "preview_mock_contextual_diagnosis"):
            self.stack.enter_context(patch.object(triage_context, name, side_effect=AssertionError("Contextual entry forbidden")))
        self.opener = MagicMock()
        self.factory = self.stack.enter_context(patch("provider.client.urllib.request.build_opener", return_value=self.opener))
        self.responses = {}
        self.requests = []
        self.opener.open.side_effect = self.respond

    def respond(self, request, *, timeout):
        self.requests.append(request)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertGreater(timeout, 0)
        # Allow only the existing collector's three documented API paths.
        suffix = request.full_url.split("/v1/projects/", 1)[1]
        self.assertTrue(suffix == PROJECT or suffix == PROJECT + "/metrics/summary" or suffix.startswith(PROJECT + "/logs?since="))
        capability = "metrics" if suffix.endswith("/metrics/summary") else "logs" if "/logs?" in suffix else "service"
        body = self.responses.get(capability, {
            "service": {"project": {"project_id": PROJECT, "isDeployed": True, "status": "running",
                                    "envs": [{"key": "PASSWORD", "value": RAW}], "unknown": TOKEN}},
            "logs": [{"message": RAW + TOKEN, "type": "stdout", "datetime": "unverified"}],
            "metrics": {"cpuUsage": [{"applet": RAW, "value": ["0.5"]}], "memoryUsage": []},
        }[capability])
        if isinstance(body, BaseException):
            raise body
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return urllib.response.addinfourl(io.BytesIO(raw), Message(), request.full_url, 200)

    def run_inspection(self, environment=None):
        return readonly.run_readonly_inspection(live_read_only=True, environment=ENV if environment is None else environment)

    def invoke(self, environment=None, argv=("--live-read-only",)):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, ENV if environment is None else environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
            code = readonly_inspection.main(argv)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(code, report["exit_code"])
        for secret in (TOKEN, PROJECT, SCOPE, SERVICE, RAW, SINCE, "Authorization", "Bearer"):
            self.assertNotIn(secret, stdout.getvalue())
        return code, report

    def test_complete_collection_actual_engine_once_and_setup_association(self):
        with patch.object(engine, "diagnose", wraps=engine.diagnose) as diagnose, patch.object(
            readonly, "consume_diagnosis", wraps=readonly.consume_diagnosis,
        ) as consume, patch.object(readonly, "attach_collection_diagnosis", wraps=readonly.attach_collection_diagnosis) as attach:
            result = self.run_inspection()
        self.assertEqual(result.summary()["exit_code"], 0)
        diagnose.assert_called_once()
        consume.assert_called_once()
        attach.assert_called_once()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(result.presentation.report.model_dump(mode="json"), result.companion.to_dict()["diagnosis"]["report"])
        self.assertEqual(result.companion.to_dict()["snapshot"], result.prepared.to_request()["snapshot"])
        self.assertEqual(result.companion.to_dict()["request_fingerprint"], request_fingerprint(result.request))
        snapshot = result.presentation.evidence.snapshot
        self.assertEqual(snapshot.data_source.value, "real")
        self.assertEqual(snapshot.status.value, "unknown")
        for key in ("cpu_usage_percent", "ram_usage_mib", "http_status", "response_time_ms", "timestamp", "logs"):
            self.assertIsNone(getattr(snapshot, key))

    def test_safe_complete_cli_and_no_execution_claims(self):
        code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["logs"], {"state": "not_collected", "received": None, "exported": 0, "withheld": 0})
        for key in ("authorization_consumed", "execution_authorized", "execution_performed", "remediation_verified", "identity_verified", "freshness_evaluated"):
            self.assertIs(report[key], False)
        self.assertEqual(report["post_action_evaluation"], "not_performed")
        self.assertEqual(report["production_readiness"], "unresolved")
        for capability in report["capabilities"]:
            self.assertEqual(set(capability), {"capability", "availability", "error_code", "http_status", "retryable"})
        self.assertEqual(set(report["diagnosis"]), {"available", "associated", "counts"})
        self.assertNotIn("snapshot", report)

    def test_cli_with_withheld_logs_contains_no_sensitive_payloads(self):
        code, report = self.invoke({**ENV, "LIARA_LOGS_SINCE": SINCE})
        self.assertEqual(code, 0)
        self.assertEqual(report["logs"], {"state": "withheld", "received": 1, "exported": 0, "withheld": 1})
        self.assertIn("LOG_TEXT_WITHHELD", report["limitations"])

    def test_missing_opt_in_precedes_configuration_and_dependencies(self):
        for flag in (False, None, 1, "true"):
            with self.assertRaises(ReadOnlyError):
                readonly.run_readonly_inspection(live_read_only=flag, environment={})
        for args in ((), ("--mock",), ("--live-read-only", "--token", TOKEN), ("--live",), ("--live-read-only", "--live-read-only")):
            with self.subTest(args_count=len(args)):
                code, _ = self.invoke(argv=args)
                self.assertEqual(code, 3)
        self.factory.assert_not_called()
        self.opener.open.assert_not_called()

    def test_missing_settings_zero_client_construction(self):
        for key in ENV:
            with self.subTest(setting=key):
                environment = dict(ENV)
                del environment[key]
                self.assertEqual(self.invoke(environment)[0], 3)
        self.factory.assert_not_called()

    def test_invalid_settings_and_secret_in_bindings_zero_client_construction(self):
        cases = {
            "LIARA_API_TOKEN": ["", "Bearer " + TOKEN, TOKEN + "\n", "\ud800"],
            "LIARA_PROJECT_NAME": ["", " ", ".", "..", "a\n", "\ud800", TOKEN],
            "LIARA_SERVICE_ID": ["", "invalid service", "../x", "x" * 129, TOKEN, "\ud800"],
            "LIARA_PROVIDER_SCOPE": ["", "invalid scope", "../x", TOKEN],
            "LIARA_LOGS_SINCE": ["", " ", "\ud800"],
            "LIARA_TIMEOUT_SECONDS": ["bad", "0", "-1", "NaN", "Infinity", TOKEN],
            "LIARA_API_BASE_URL": ["http://example.invalid", "https://u:p@example.invalid", "https://example.invalid?key=" + TOKEN],
        }
        for key, values in cases.items():
            for value in values:
                with self.subTest(setting=key, case=values.index(value)):
                    self.assertEqual(self.invoke({**ENV, key: value})[0], 3)
        self.factory.assert_not_called()

    def test_optional_transport_settings_reuse_validation_and_redirect_block(self):
        settings = read_inspection_settings({**ENV, "LIARA_TIMEOUT_SECONDS": "1.25", "LIARA_API_BASE_URL": "https://example.invalid/api/"})
        self.assertEqual(settings.live.config.timeout, 1.25)
        self.assertEqual(settings.live.config.base_url, "https://example.invalid/api")
        self.run_inspection()
        handler = self.factory.call_args.args[0]
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://other.invalid"))

    def test_logs_empty_unavailable_withheld_and_invalid_remain_distinct(self):
        for source, state, received, withheld, exit_code in (([], "empty", 0, 0, 0), (None, "unavailable", None, 0, 1),
                ([{"message": RAW}, {}], "withheld", 2, 2, 0), (b"bad JSON " + TOKEN.encode(), "collection_failed", None, 0, 1)):
            with self.subTest(state=state):
                self.responses["logs"] = source
                result = self.run_inspection({**ENV, "LIARA_LOGS_SINCE": SINCE})
                summary = result.summary()
                self.assertEqual(summary["logs"], {"state": state, "received": received, "exported": 0, "withheld": withheld})
                self.assertEqual(summary["exit_code"], exit_code)
                self.assertNotIn(RAW, json.dumps(result.prepared.to_request()))
                self.assertNotIn(TOKEN, repr(result))
        self.assertEqual(len(self.requests), 12)

    def test_partial_http_failures_preserve_data_and_retryability(self):
        for status, availability, retryable in ((401, "authentication_failed", False), (403, "permission_denied", False),
                (404, "not_found", False), (429, "failed", True), (500, "failed", True), (502, "failed", True), (503, "failed", True), (504, "failed", True)):
            with self.subTest(status=status):
                self.responses["metrics"] = urllib.error.HTTPError("https://example.invalid", status, RAW + TOKEN, {}, io.BytesIO(RAW.encode()))
                result = self.run_inspection()
                self.assertEqual(result.summary()["exit_code"], 1)
                self.assertIsNotNone(result.presentation)
                context = result.prepared.to_request()["collection_context"]
                self.assertEqual(context["capabilities"][0]["availability"], "available")
                item = context["capabilities"][3]
                self.assertEqual((item["availability"], item["http_status"], item["retryable"]), (availability, status, retryable))
                self.assertNotEqual(item["availability"], "unsupported")
                self.assertEqual(result.companion.to_dict()["collection_context"], context)

    def test_timeouts_network_and_invalid_responses_are_partial_not_crashes(self):
        cases = [(socket.timeout(TOKEN), "TIMEOUT"), (urllib.error.URLError(socket.timeout(TOKEN)), "TIMEOUT"),
                 (urllib.error.URLError(RAW), "NETWORK_ERROR"), (b"invalid " + TOKEN.encode(), "INVALID_RESPONSE"),
                 (b'{"cpuUsage": NaN}', "INVALID_RESPONSE")]
        for body, error in cases:
            with self.subTest(error=error):
                self.responses["metrics"] = body
                result = self.run_inspection()
                summary = result.summary()
                self.assertEqual(summary["exit_code"], 1)
                self.assertEqual(summary["capabilities"][3]["error_code"], error)

    def test_total_collection_failure_retains_unknown_snapshot_and_diagnosis(self):
        self.responses.update(service=socket.timeout(RAW), metrics=socket.timeout(TOKEN))
        result = self.run_inspection()
        self.assertEqual(result.summary()["exit_code"], 2)
        self.assertEqual(result.summary()["collection_outcome"], "failed")
        self.assertTrue(result.summary()["diagnosis"]["available"])
        self.assertEqual(result.presentation.report.hypotheses, [])

    def test_all_methods_still_collected_after_component_denial(self):
        self.responses["service"] = urllib.error.HTTPError("https://example.invalid", 403, TOKEN, {}, io.BytesIO())
        result = self.run_inspection({**ENV, "LIARA_LOGS_SINCE": SINCE})
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(result.summary()["exit_code"], 1)
        self.assertEqual(result.summary()["capabilities"][0]["availability"], "permission_denied")
        self.assertEqual(result.summary()["capabilities"][3]["availability"], "available")

    def test_cross_service_scope_project_source_and_request_rejected_before_diagnosis(self):
        original = self.run_inspection()
        bindings = [replace(original.binding, service_id="other"), replace(original.binding, project_name="other"),
                    replace(original.binding, provider_scope="other"), replace(original.binding, is_mock=True)]
        with patch.object(engine, "diagnose") as diagnose:
            for binding in bindings:
                result = readonly.inspect_prepared(original.request, original.prepared, expected_binding=binding)
                self.assertIsNone(result.presentation)
                self.assertEqual(result.error_code, "CONTEXT_REJECTED")
            request = OperationRequest("different", "inspect_service", {"service_target": "other", "goal": "inspect"})
            result = readonly.inspect_prepared(request, original.prepared, expected_binding=original.binding)
            self.assertEqual(result.error_code, "CONTEXT_REJECTED")
        diagnose.assert_not_called()

    def test_mock_reference_never_relabelled_real(self):
        mock = MockLiaraClient()
        binding = ServiceBinding(SERVICE, PROJECT, SCOPE, True)
        prepared = CollectionContextAdapter(mock, provider_scope=SCOPE).collect(binding).data
        request = OperationRequest("test", "inspect_service", {"service_target": SERVICE, "goal": "inspect"})
        result = readonly.inspect_prepared(request, prepared, expected_binding=replace(binding, is_mock=False))
        self.assertIsNone(result.presentation)
        self.assertEqual(result.error_code, "CONTEXT_REJECTED")

    def test_changed_snapshot_context_digest_and_source_are_rejected(self):
        for mutate in (lambda x: x["snapshot"].update(service_id="other"),
                       lambda x: x["snapshot"].update(data_source="mock"),
                       lambda x: x["collection_context"].update(snapshot_digest="sha256:" + "0" * 64),
                       lambda x: x["collection_context"]["capabilities"][0].update(availability="failed")):
            original = self.run_inspection()
            envelope = original.prepared.to_request()
            mutate(envelope)
            with patch.object(engine, "diagnose") as diagnose:
                result = readonly.inspect_prepared(original.request, original.prepared, expected_binding=original.binding,
                                                    submitted_envelope=envelope)
            diagnose.assert_not_called()
            self.assertIsNone(result.presentation)

    def test_context_preservation_failure_does_not_call_diagnosis(self):
        with patch.object(readonly, "preserve_collection_context", side_effect=RuntimeError(RAW)), patch.object(engine, "diagnose") as diagnose:
            result = self.run_inspection()
        diagnose.assert_not_called()
        self.assertIsNotNone(result.prepared)
        self.assertEqual(result.summary()["collection_outcome"], "complete")
        self.assertEqual(result.summary()["stage"], "context")
        self.assertEqual(result.summary()["exit_code"], 2)

    def test_diagnosis_failure_keeps_original_collection_and_companion(self):
        with patch.object(engine, "diagnose", side_effect=RuntimeError(TOKEN + RAW)):
            result = self.run_inspection()
        self.assertIsNotNone(result.prepared)
        self.assertIsNotNone(result.companion)
        summary = result.summary()
        self.assertEqual(summary["stage"], "diagnosis")
        self.assertEqual(summary["error_code"], "DIAGNOSIS_FAILED")
        self.assertEqual(summary["collection_outcome"], "complete")
        self.assertFalse(summary["diagnosis"]["available"])

    def test_wrong_report_target_source_and_invalid_payload_rejected(self):
        real = engine.diagnose
        for change in ({"service_id": "other"}, {"data_source": "mock"}, {"actions": [RAW]}):
            def wrong(snapshot, change=change):
                return real(snapshot).model_copy(update=change)
            with patch.object(engine, "diagnose", side_effect=wrong):
                result = self.run_inspection()
            self.assertNotEqual(result.stage, "complete")
            self.assertIsNone(result.presentation)
            self.assertIsNotNone(result.prepared)
            self.assertEqual(result.summary()["exit_code"], 2)

    def test_failed_attachment_preserves_valid_presentation_and_earlier_data(self):
        with patch.object(readonly, "attach_collection_diagnosis", side_effect=RuntimeError(RAW)):
            result = self.run_inspection()
        self.assertIsNotNone(result.presentation)
        summary = result.summary()
        self.assertEqual(summary["stage"], "association")
        self.assertTrue(summary["diagnosis"]["available"])
        self.assertFalse(summary["diagnosis"]["associated"])
        self.assertEqual(summary["exit_code"], 2)

    def test_changed_report_or_request_after_completion_rejected_on_reuse(self):
        result = self.run_inspection()
        result.presentation.report.summary = RAW
        self.assertEqual(result.summary()["error_code"], "EVIDENCE_MODIFIED")
        with self.assertRaises(ReadOnlyError):
            result.validate()
        result = self.run_inspection()
        result.request.details["goal"] = RAW
        self.assertEqual(result.summary()["error_code"], "EVIDENCE_MODIFIED")

    def test_internal_reprs_and_exception_logging_hide_canaries(self):
        settings = read_inspection_settings(ENV)
        result = self.run_inspection({**ENV, "LIARA_LOGS_SINCE": SINCE})
        log = io.StringIO()
        logger = logging.Logger("readonly-security")
        logger.addHandler(logging.StreamHandler(log))
        for value in (settings, settings.live, settings.binding, result, result.prepared, ReadOnlyError(TOKEN)):
            logger.warning("%s %r", value, value)
        for value in (TOKEN, PROJECT, SCOPE, SERVICE, RAW):
            self.assertNotIn(value, log.getvalue())
        self.assertNotIn(RAW, json.dumps(result.summary()))

    def test_live_export_override_is_rejected_not_sanitized_and_rehashed(self):
        client = LiaraClient(ProviderConfig(TOKEN))
        binding = ServiceBinding(SERVICE, PROJECT, SCOPE, False)
        for state in ("exported", "partial"):
            with self.subTest(state=state):
                self.responses["logs"] = [{"message": "reviewed synthetic"}, {"message": RAW}]
                sanitizer = (lambda _: "reviewed text") if state == "exported" else (
                    lambda text: "reviewed text" if text == "reviewed synthetic" else None)
                prepared = CollectionContextAdapter(client, provider_scope=SCOPE).collect(binding, logs_since=SINCE,
                    log_sanitizer=sanitizer).data
                self.assertEqual(prepared.to_request()["collection_context"]["log_export"]["state"], state)
                request = OperationRequest("test", "inspect_service", {"service_target": SERVICE, "goal": "inspect"})
                with patch.object(engine, "diagnose") as diagnose:
                    result = readonly.inspect_prepared(request, prepared, expected_binding=binding)
                diagnose.assert_not_called()
                self.assertEqual(result.error_code, "CONTEXT_REJECTED")

    def test_unexpected_collector_exception_and_wrong_origin_safe(self):
        for effect in (RuntimeError(TOKEN),):
            with patch.object(CollectionContextAdapter, "collect", side_effect=effect):
                self.assertEqual(self.invoke()[1]["error_code"], "COLLECTION_FAILED")
        with patch.object(CollectionContextAdapter, "collect", return_value=MagicMock(is_mock=True)):
            self.assertEqual(self.invoke()[0], 2)

    def test_cli_dependency_failure_unexpected_exception_and_interrupt(self):
        for error, expected, code in ((ImportError(TOKEN), "DEPENDENCIES_UNAVAILABLE", 2),
                                     (RuntimeError(RAW), "UNEXPECTED_ERROR", 2), (KeyboardInterrupt(), "INTERRUPTED", 130)):
            with patch.object(readonly, "run_readonly_inspection", side_effect=error):
                actual, report = self.invoke()
            self.assertEqual((actual, report["error_code"]), (code, expected))
        with patch.object(engine, "diagnose", side_effect=KeyboardInterrupt()):
            self.assertEqual(self.invoke()[0], 130)

    def test_diagnosis_interrupt_retains_collected_evidence_in_python_result(self):
        with patch.object(engine, "diagnose", side_effect=KeyboardInterrupt()):
            result = self.run_inspection()
        self.assertIsNotNone(result.prepared)
        self.assertIsNotNone(result.companion)
        self.assertEqual(result.summary()["exit_code"], 130)
        self.assertEqual(result.summary()["collection_outcome"], "complete")

    def test_cli_partial_and_total_failure_codes(self):
        self.responses["metrics"] = socket.timeout(TOKEN)
        self.assertEqual(self.invoke()[0], 1)
        self.responses["service"] = socket.timeout(TOKEN)
        self.assertEqual(self.invoke()[0], 2)

    def test_summary_copies_cannot_mutate_retained_evidence(self):
        result = self.run_inspection()
        summary = result.summary()
        summary["capabilities"][0]["availability"] = RAW
        summary["limitations"].clear()
        self.assertEqual(result.summary()["capabilities"][0]["availability"], "available")
        self.assertTrue(result.summary()["limitations"])

    def test_shared_public_configuration_matches_smoke_wrapper(self):
        from provider.examples.live_smoke import _settings
        shared, legacy = read_live_settings(ENV), _settings(ENV)
        self.assertEqual(shared.config.base_url, legacy.config.base_url)
        self.assertEqual(shared.project, legacy.project)
        self.assertEqual(shared.logs_since, legacy.logs_since)

    def test_recomputed_snapshot_hash_cannot_replace_retained_reference(self):
        from infrapilot_triage.collection_context import canonical_context_json
        import hashlib
        original = self.run_inspection()
        envelope = original.prepared.to_request()
        envelope["snapshot"]["logs"] = []
        envelope["collection_context"]["snapshot_digest"] = "sha256:" + hashlib.sha256(canonical_context_json(envelope["snapshot"])).hexdigest()
        with patch.object(engine, "diagnose") as diagnose:
            result = readonly.inspect_prepared(original.request, original.prepared, expected_binding=original.binding, submitted_envelope=envelope)
        diagnose.assert_not_called()
        self.assertEqual(result.error_code, "CONTEXT_REJECTED")
        self.assertIs(result.prepared, original.prepared)

    def test_replaced_consumer_report_and_wrong_attached_companion_fail(self):
        consume = readonly.consume_diagnosis
        def wrong(request, evidence, report):
            return consume(request, evidence, report.model_copy(update={"summary": "replacement"}))
        with patch.object(readonly, "consume_diagnosis", side_effect=wrong):
            result = self.run_inspection()
        self.assertEqual(result.error_code, "ASSOCIATION_FAILED")
        self.assertIsNone(result.presentation)
        self.assertFalse(result.summary()["diagnosis"]["available"])
        other = self.run_inspection()
        with patch.object(readonly, "attach_collection_diagnosis", return_value=MagicMock(
            state="diagnosis_associated", companion=other.companion,
        )):
            result = self.run_inspection()
        self.assertEqual(result.error_code, "ASSOCIATION_FAILED")

    def test_output_pipe_failure_returns_two_without_traceback(self):
        stream = MagicMock()
        stream.write.side_effect = BrokenPipeError(TOKEN)
        stream.fileno.side_effect = OSError()
        stderr = io.StringIO()
        with patch("integration.mock_backend.sys.stdout", stream), redirect_stderr(stderr):
            self.assertEqual(readonly_inspection.main([]), 2)
        self.assertEqual(stderr.getvalue(), "")

    def test_interrupt_during_collection_stops_safely(self):
        self.responses["service"] = KeyboardInterrupt()
        code, report = self.invoke()
        self.assertEqual((code, report["error_code"]), (130, "INTERRUPTED"))
        self.assertEqual(len(self.requests), 1)


class ReadOnlyProcessTests(unittest.TestCase):
    def test_actual_command_lazy_help_optin_config_and_dependencies(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("LIARA_")}
        for no_site, args, settings, expected in (
            (True, ["--help"], {}, 0), (True, [], {}, 3),
            (True, ["--live-read-only"], ENV, 2),
            (False, ["--live-read-only"], {}, 3),
            (False, ["--token", TOKEN], ENV, 3),
        ):
            with self.subTest(no_site=no_site, arguments=len(args)):
                command = [sys.executable, "-B"] + (["-S"] if no_site else [])
                process = subprocess.run(command + ["-m", "integration.readonly_inspection", *args],
                    env={**environment, **settings}, capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, expected)
                self.assertEqual(process.stderr, "")
                self.assertNotIn(TOKEN, process.stdout)
                if args != ["--help"]:
                    self.assertEqual(json.loads(process.stdout)["exit_code"], expected)


if __name__ == "__main__":
    unittest.main()
