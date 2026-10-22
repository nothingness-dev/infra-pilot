"""Offline tests for the provider-local draft projection; no framework imports."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from provider import (
    LiaraClient, MockLiaraClient, ProviderConfig, ProviderResult, ServiceLog,
    StructuredError, TriageAdapter,
)
from provider.examples.triage_handoff import mock_handoff
from provider.fixtures import mock_payload


TOKEN = "test-secret-provider-123456"


class TriageAdapterTests(unittest.TestCase):
    def setUp(self):
        self.client = MockLiaraClient(ProviderConfig(api_key=TOKEN))
        self.adapter = TriageAdapter(self.client)
        self.bundle = self.client.collect_service_observations(
            "private-project", logs_since="opaque-since",
        ).data

    def project(self, bundle=None, **options):
        return self.adapter.from_observations(
            self.bundle if bundle is None else bundle, service_id="opaque-service-1", **options,
        )

    def test_fixture_is_reproducible_and_entirely_offline(self):
        with patch("socket.socket", side_effect=AssertionError("Network forbidden")), patch(
            "urllib.request.build_opener", side_effect=AssertionError("Opener forbidden"),
        ):
            handoff = mock_handoff()
        path = Path(__file__).parents[1] / "examples" / "mock_triage_snapshot.json"
        self.assertEqual(handoff.snapshot.to_request(), json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(handoff.snapshot.data_source, "mock")
        self.assertEqual(handoff.logs_exported, 1)

    def test_native_running_and_deployed_do_not_imply_health_or_normalized_metrics(self):
        request = self.project().snapshot.to_request()
        self.assertEqual(request["status"], "unknown")
        for key in ("http_status", "response_time_ms", "cpu_usage_percent", "ram_usage_mib", "timestamp"):
            self.assertIsNone(request[key])
        self.assertEqual(len(request), 9)
        self.assertNotIn("capabilities", request)
        self.assertNotIn("private-project", json.dumps(self.project().to_dict()))

    def test_default_withholds_nonempty_logs_but_preserves_availability(self):
        handoff = self.project()
        self.assertIsNone(handoff.snapshot.logs)
        self.assertEqual(handoff.logs_withheld, 1)
        self.assertEqual(handoff.capabilities[2].availability, "available")
        self.assertIn("LOG_TEXT_WITHHELD", handoff.limitations)

    def test_empty_and_missing_logs_are_distinct(self):
        for mode, expected in (("empty", []), ("missing", None)):
            with self.subTest(mode=mode):
                result = TriageAdapter(MockLiaraClient(failure_modes={"logs": mode})).collect(
                    "test", service_id="opaque", logs_since="opaque",
                )
                self.assertEqual(result.data.snapshot.to_request()["logs"], expected)

    def test_missing_messages_and_failed_sanitizer_keep_other_valid_entries(self):
        logs = [ServiceLog(None, None, None), ServiceLog("boom", "error", "bad-time"),
                ServiceLog("", "stdout", "2026-01-01T00:00:00Z"), ServiceLog("ok", None, None)]
        bundle = replace(self.bundle, logs=replace(self.bundle.logs, data=logs))

        def reviewed(message):
            if message == "boom":
                raise RuntimeError(TOKEN)
            return message

        handoff = self.project(bundle, log_sanitizer=reviewed)
        self.assertEqual([log.message for log in handoff.snapshot.logs], ["", "ok"])
        self.assertEqual(handoff.logs_withheld, 2)
        self.assertIn("LOG_EXPORT_INCOMPLETE", handoff.limitations)
        for log in handoff.snapshot.logs:
            self.assertEqual(log.level, "unknown")
            self.assertIsNone(log.timestamp)

    def test_all_withheld_nonempty_logs_are_not_reported_as_empty(self):
        for value in (None, 1, [], "\ud800"):
            with self.subTest(value=repr(value)):
                handoff = self.project(log_sanitizer=lambda message: value)
                self.assertIsNone(handoff.snapshot.logs)
                self.assertEqual(handoff.logs_withheld, 1)

    def test_all_http_and_transport_failures_preserve_valid_component_data(self):
        cases = (
            (401, "authentication_failed", "AUTHENTICATION_ERROR"),
            (403, "permission_denied", "AUTHENTICATION_ERROR"),
            (404, "not_found", "RESOURCE_NOT_FOUND"),
            (429, "failed", "RATE_LIMITED"), (503, "failed", "API_UNAVAILABLE"),
            ("timeout", "failed", "TIMEOUT"), ("invalid_response", "failed", "INVALID_RESPONSE"),
        )
        for mode, state, code in cases:
            with self.subTest(mode=mode):
                result = TriageAdapter(MockLiaraClient(failure_modes={"metrics": mode})).collect(
                    "test", service_id="opaque", logs_since="since", log_sanitizer=lambda text: text,
                )
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, "PARTIAL_COLLECTION")
                self.assertEqual(result.data.capabilities[3].availability, state)
                self.assertEqual(result.data.capabilities[3].error_code, code)
                self.assertEqual(result.data.logs_exported, 1)

    def test_total_failure_and_skipped_logs_do_not_fabricate_evidence(self):
        result = TriageAdapter(MockLiaraClient(failure_mode=401)).collect("test", service_id="opaque")
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "COLLECTION_FAILED")
        self.assertIsNone(result.data.snapshot.logs)
        self.assertEqual(result.data.capabilities[2].availability, "not_collected")
        self.assertEqual(result.data.snapshot.status, "unknown")

    def test_invalid_collection_options_return_existing_failure(self):
        result = self.adapter.collect("..", service_id="opaque")
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertEqual(result.error.code, "INVALID_REQUEST")

    def test_invalid_binding_or_sanitizer_rejected_before_collection_without_echo(self):
        for service_id in (None, "", " spaces ", "x/y", TOKEN, "x" * 129, "\ud800"):
            with self.subTest(service_id=repr(service_id)), patch.object(
                self.client, "collect_service_observations",
            ) as collect:
                with self.assertRaises(ValueError) as caught:
                    self.adapter.collect("test", service_id=service_id)
                collect.assert_not_called()
                self.assertNotIn(TOKEN, str(caught.exception))
        with self.assertRaises(ValueError):
            self.project(log_sanitizer="not-callable")

    def test_mixed_or_relabelled_provenance_is_rejected(self):
        bad = (
            replace(self.bundle, is_mock=False),
            replace(self.bundle, is_mock=1),
            replace(self.bundle, logs=replace(self.bundle.logs, is_mock=False)),
            replace(self.bundle, metrics=replace(self.bundle.metrics, availability="failed")),
            replace(self.bundle, logs=replace(self.bundle.logs, data=None)),
        )
        for bundle in bad:
            with self.subTest(bundle=type(bundle)):
                with self.assertRaises(ValueError):
                    self.project(bundle)
        live_adapter = TriageAdapter(LiaraClient(ProviderConfig(api_key=TOKEN)))
        with self.assertRaises(ValueError):
            live_adapter.from_observations(self.bundle, service_id="opaque")

    def test_safe_json_repr_stdout_stderr_and_callback_input_do_not_leak_token(self):
        source = replace(self.bundle, logs=replace(
            self.bundle.logs, data=[ServiceLog("prefix " + TOKEN, TOKEN, TOKEN)],
        ))
        seen = []

        def reviewed(message):
            seen.append(message)
            return message + TOKEN

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            handoff = self.project(source, log_sanitizer=reviewed)
        text = json.dumps(handoff.to_dict()) + repr(handoff) + str(handoff) + repr(seen)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("prefix", repr(handoff))
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")

    def test_raw_error_messages_codes_and_invalid_times_are_not_exported(self):
        error = StructuredError(TOKEN, TOKEN, True, True)
        source = replace(self.bundle, metrics=replace(
            self.bundle.metrics, data=None, error=error, availability="failed", collected_at=TOKEN,
        ), collection_started_at=TOKEN, collection_finished_at="2026-01-01T00:00:00")
        handoff = self.project(source)
        self.assertNotIn(TOKEN, json.dumps(handoff.to_dict()))
        self.assertEqual(handoff.capabilities[3].error_code, "PROVIDER_ERROR")
        self.assertIsNone(handoff.capabilities[3].http_status)
        self.assertIsNone(handoff.capabilities[3].collected_at)
        self.assertIsNone(handoff.collection_started_at)
        self.assertIsNone(handoff.collection_finished_at)

    def test_detached_request_mutation_does_not_change_handoff(self):
        handoff = self.project(log_sanitizer=lambda text: text)
        request = handoff.snapshot.to_request()
        request["logs"][0]["message"] = "changed"
        self.assertNotEqual(request, handoff.snapshot.to_request())

    def test_live_provenance_with_mocked_existing_transport_uses_only_gets(self):
        client = LiaraClient(ProviderConfig(api_key=TOKEN))
        calls = []
        def request(method, endpoint, params=None, payload=None):
            calls.append((method, endpoint))
            capability = "logs" if endpoint.endswith("/logs") else (
                "metrics" if endpoint.endswith("/metrics/summary") else "service"
            )
            return ProviderResult(True, mock_payload(capability, "test", params, None))

        with patch.object(client, "_request", side_effect=request):
            result = TriageAdapter(client).collect("test", service_id="opaque", logs_since="since")
        self.assertTrue(result.success)
        self.assertFalse(result.is_mock)
        self.assertEqual(result.data.snapshot.data_source, "real")
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(method == "GET" for method, endpoint in calls))
        # The fixture above tests provenance mapping, not authenticated live access.


if __name__ == "__main__":
    unittest.main()
