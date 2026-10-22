"""Stdlib-only offline checks for the explicitly proposed context boundary."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, replace
import hashlib
import io
import json
import logging
from pathlib import Path
import unittest
from unittest.mock import patch

from provider import (
    COLLECTION_CONTEXT_VERSION, CollectionContextAdapter, CollectionContextError,
    LiaraClient, MockLiaraClient, ProviderConfig, ServiceBinding, ServiceLog, TriageAdapter,
)
from provider.collection_context import MAX_COLLECTION_CONTEXT_BYTES
from provider.examples.context_demo import main
from provider.examples.context_fixtures import (
    MOCK_CONTEXT_SCENARIOS, build_mock_context, mock_context_binding,
)


TOKEN = "context-test-secret-123456"


class CollectionContextTests(unittest.TestCase):
    def setUp(self):
        self.client = MockLiaraClient(ProviderConfig(api_key=TOKEN))
        self.binding = ServiceBinding("opaque-service", "private-project", "private-scope", True)
        self.adapter = CollectionContextAdapter(self.client, provider_scope="private-scope")
        self.bundle = self.client.collect_service_observations("private-project", logs_since="since").data

    def prepare(self, bundle=None, **options):
        return self.adapter.from_observations(
            self.bundle if bundle is None else bundle, binding=self.binding, **options,
        )

    def test_proposed_envelope_roundtrips_against_retained_backend_reference(self):
        prepared = self.prepare()
        request = prepared.to_request()
        self.assertEqual(set(request), {"snapshot", "collection_context"})
        context = request["collection_context"]
        self.assertEqual(context["contract_version"], COLLECTION_CONTEXT_VERSION)
        self.assertEqual(context["service_id"], request["snapshot"]["service_id"])
        self.assertEqual(context["data_source"], "mock")
        self.assertEqual(prepared.verify_request(request, expected_binding=self.binding), request)
        self.assertNotIn("collection_errors", context)

    def test_old_snapshot_and_sidecar_wire_shapes_are_preserved(self):
        legacy = TriageAdapter(self.client).from_observations(self.bundle, service_id=self.binding.service_id)
        current = self.prepare().to_request()
        self.assertEqual(legacy.snapshot.to_request(), current["snapshot"])
        self.assertEqual(set(legacy.to_dict()), {
            "snapshot", "capabilities", "collection_started_at", "collection_finished_at",
            "logs_exported", "logs_withheld", "limitations",
        })
        self.assertEqual(set(legacy.to_dict()["capabilities"][0]), {
            "capability", "availability", "error_code", "http_status", "collected_at",
        })
        self.assertIn("retryable", current["collection_context"]["capabilities"][0])

    def test_fixture_scenarios_are_reproducible_and_entirely_offline(self):
        directory = Path(__file__).parents[1] / "examples" / "fixtures" / "context_v02"
        with patch("socket.socket", side_effect=AssertionError("Network forbidden")), patch(
            "urllib.request.build_opener", side_effect=AssertionError("Opener forbidden"),
        ):
            for scenario in MOCK_CONTEXT_SCENARIOS:
                with self.subTest(scenario=scenario):
                    request = build_mock_context(scenario).to_request()
                    fixture = json.loads((directory / (scenario + ".json")).read_text(encoding="utf-8"))
                    self.assertEqual(request, fixture)
                    self.assertEqual(request["snapshot"]["data_source"], "mock")

    def test_log_states_do_not_turn_withheld_or_missing_entries_into_collected_empty(self):
        expected = {
            "exported": ("exported", 1, 1, 0), "empty": ("empty", 0, 0, 0),
            "unavailable": ("unavailable", None, 0, 0),
            "not_collected": ("not_collected", None, 0, 0),
            "withheld": ("withheld", 1, 0, 1), "partial_logs": ("partial", 2, 1, 1),
            "partial_failure": ("collection_failed", None, 0, 0),
        }
        for scenario, values in expected.items():
            with self.subTest(scenario=scenario):
                request = build_mock_context(scenario).to_request()
                stats = request["collection_context"]["log_export"]
                self.assertEqual(tuple(stats[key] for key in ("state", "received", "exported", "withheld")), values)
                if scenario == "empty":
                    self.assertEqual(request["snapshot"]["logs"], [])
                elif values[2] == 0:
                    self.assertIsNone(request["snapshot"]["logs"])

    def test_unknown_health_metrics_app_http_and_source_time_stay_unknown(self):
        snapshot = self.prepare().to_request()["snapshot"]
        self.assertEqual(snapshot["status"], "unknown")
        for name in ("cpu_usage_percent", "ram_usage_mib", "http_status", "response_time_ms", "timestamp"):
            self.assertIsNone(snapshot[name])

    def test_partial_and_total_failures_keep_context_with_exact_safe_error_semantics(self):
        for mode, state, http_status, retryable in (
            (401, "authentication_failed", 401, False), (403, "permission_denied", 403, False),
            (404, "not_found", 404, False), (429, "failed", 429, True),
            (503, "failed", 503, True), ("timeout", "failed", None, True),
            ("invalid_response", "failed", None, False), ("missing", "unavailable", None, None),
        ):
            with self.subTest(mode=mode):
                client = MockLiaraClient(failure_modes={"metrics": mode})
                result = CollectionContextAdapter(client, provider_scope="private-scope").collect(self.binding)
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, "PARTIAL_COLLECTION")
                metric = result.data.to_request()["collection_context"]["capabilities"][3]
                self.assertEqual((metric["availability"], metric["http_status"], metric["retryable"]),
                                 (state, http_status, retryable))
        result = CollectionContextAdapter(MockLiaraClient(failure_mode=401), provider_scope="private-scope").collect(
            self.binding, logs_since="since",
        )
        self.assertEqual(result.error.code, "COLLECTION_FAILED")
        self.assertIsNotNone(result.data)

    def test_invalid_options_or_scope_fail_before_collection(self):
        for binding in (
            replace(self.binding, provider_scope="other-scope"), replace(self.binding, is_mock=False),
            replace(self.binding, project_name=TOKEN), None,
        ):
            with self.subTest(binding=repr(binding)), patch.object(self.client, "collect_service_observations") as collect:
                with self.assertRaises(CollectionContextError):
                    self.adapter.collect(binding)
                collect.assert_not_called()
        with patch.object(self.client, "collect_service_observations") as collect:
            with self.assertRaises(ValueError):
                self.adapter.collect(self.binding, log_sanitizer=False)
            collect.assert_not_called()

    def test_binding_validation_and_representations_do_not_echo_identifiers_or_token(self):
        for options in (
            {"service_id": ""}, {"service_id": "a/b"}, {"project_name": ".."},
            {"provider_scope": "bad scope"}, {"is_mock": 1}, {"project_name": "\ud800"},
        ):
            with self.subTest(options=repr(options)), self.assertRaises(CollectionContextError):
                replace(self.binding, **options)
        for value in (self.binding, self.prepare(), CollectionContextError(TOKEN)):
            text = repr(value) + str(value)
            self.assertNotIn(TOKEN, text)
            self.assertNotIn("private-project", text)
            self.assertNotIn("private-scope", text)

    def test_wrong_project_or_component_binding_is_rejected_before_log_policy(self):
        for bundle in (
            replace(self.bundle, service_name="other"),
            replace(self.bundle, service=replace(self.bundle.service, data=replace(self.bundle.service.data, service_name="other"))),
            replace(self.bundle, deployment=replace(self.bundle.deployment, data=replace(self.bundle.deployment.data, service_name="other"))),
        ):
            with self.subTest(case=bundle.service_name), patch("builtins.print") as output:
                policy = unittest.mock.Mock(return_value="allowed")
                with self.assertRaises(CollectionContextError):
                    self.prepare(bundle, log_sanitizer=policy)
                policy.assert_not_called()
                output.assert_not_called()

    def test_mixed_origin_or_malformed_observation_is_rejected(self):
        for bundle in (
            replace(self.bundle, is_mock=False),
            replace(self.bundle, metrics=replace(self.bundle.metrics, is_mock=False)),
            replace(self.bundle, metrics=replace(self.bundle.metrics, availability={})),
            replace(self.bundle, metrics=replace(self.bundle.metrics, data="raw invalid body")),
            replace(self.bundle, metrics=replace(self.bundle.metrics, error="raw error")),
        ):
            with self.subTest(case=type(bundle)), self.assertRaises(CollectionContextError):
                self.prepare(bundle)

    def test_different_expected_service_project_scope_or_source_is_rejected(self):
        prepared = self.prepare()
        for binding in (
            replace(self.binding, service_id="other"), replace(self.binding, project_name="other"),
            replace(self.binding, provider_scope="other"), replace(self.binding, is_mock=False), None,
        ):
            with self.subTest(binding=repr(binding)), self.assertRaises(CollectionContextError):
                prepared.verify_request(prepared.to_request(), expected_binding=binding)

    def test_tampering_with_snapshot_or_any_context_is_rejected_even_with_recomputed_digest(self):
        prepared = self.prepare()
        for change in (
            lambda r: r["snapshot"].update(service_id="other"),
            lambda r: r["snapshot"].update(status="healthy"),
            lambda r: r["collection_context"].update(contract_version="0.1"),
            lambda r: r["collection_context"].update(data_source="real"),
            lambda r: r["collection_context"]["capabilities"][3].update(availability="failed"),
            lambda r: r["collection_context"]["limitations"].clear(),
            lambda r: r["collection_context"]["log_export"].update(withheld=0),
            lambda r: r.update(unapproved="field"),
        ):
            request = prepared.to_request()
            change(request)
            digest = json.dumps(request["snapshot"], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            request["collection_context"]["snapshot_digest"] = "sha256:" + hashlib.sha256(digest.encode("ascii")).hexdigest()
            with self.assertRaises(CollectionContextError):
                prepared.verify_request(request, expected_binding=self.binding)

    def test_same_snapshot_does_not_allow_swapped_collection_metadata(self):
        withheld = build_mock_context("withheld")
        unavailable = build_mock_context("unavailable").to_request()
        self.assertEqual(withheld.to_request()["snapshot"], unavailable["snapshot"])
        with self.assertRaises(CollectionContextError):
            withheld.verify_request(unavailable, expected_binding=mock_context_binding())

    def test_detached_copies_and_frozen_reference_prevent_accidental_changes(self):
        prepared = self.prepare()
        request = prepared.to_request()
        request["collection_context"]["limitations"].clear()
        self.assertTrue(prepared.to_request()["collection_context"]["limitations"])
        with self.assertRaises(FrozenInstanceError):
            prepared._canonical_request = b"{}"

    def test_invalid_circular_nonfinite_and_oversized_submissions_fail_safely(self):
        prepared = self.prepare()
        circular = {}
        circular["self"] = circular
        for request in (None, [], TOKEN, circular, {"value": float("nan")}, {"value": float("inf")},
                        {"value": TOKEN + "x" * MAX_COLLECTION_CONTEXT_BYTES}):
            with self.subTest(kind=type(request)), self.assertRaises(CollectionContextError) as caught:
                prepared.verify_request(request, expected_binding=self.binding)
            self.assertNotIn(TOKEN, repr(caught.exception))

    def test_inconsistent_known_collector_times_are_rejected_and_unknown_times_stay_null(self):
        bundle = replace(self.bundle, collection_started_at="2026-10-22T00:00:02Z",
                         collection_finished_at="2026-10-22T00:00:01Z")
        with self.assertRaises(CollectionContextError):
            self.prepare(bundle)
        bundle = replace(self.bundle, collection_started_at="unknown", collection_finished_at=None)
        context = self.prepare(bundle).to_request()["collection_context"]
        self.assertIsNone(context["collection_started_at"])
        self.assertIsNone(context["collection_finished_at"])

    def test_known_token_never_reaches_callback_output_json_repr_logs_or_exception_context(self):
        bundle = replace(self.bundle, logs=replace(self.bundle.logs, data=[ServiceLog(TOKEN, TOKEN, TOKEN)]))
        seen = []

        def policy(message):
            seen.append(message)
            return message + TOKEN

        stdout, stderr, log = io.StringIO(), io.StringIO(), io.StringIO()
        logger = logging.Logger("context-secrets")
        logger.addHandler(logging.StreamHandler(log))
        with redirect_stdout(stdout), redirect_stderr(stderr):
            prepared = self.prepare(bundle, log_sanitizer=policy)
            try:
                try:
                    raise RuntimeError(TOKEN)
                except RuntimeError:
                    raise CollectionContextError(TOKEN)
            except CollectionContextError:
                logger.exception("Rejected context")
        combined = json.dumps(prepared.to_request()) + repr(prepared) + repr(seen) + log.getvalue()
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn("private-project", combined)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")

    def test_invalid_collection_options_preserve_existing_result_and_provenance(self):
        result = self.adapter.collect(self.binding, logs_since=" ")
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertEqual(result.error.code, "INVALID_REQUEST")
        self.assertTrue(result.is_mock)

    def test_projection_failure_is_a_fixed_structured_result(self):
        with patch.object(self.client, "collect_service_observations", return_value=replace(
            self.client.collect_service_observations("private-project"),
            data=replace(self.bundle, service_name="other"),
        )):
            result = self.adapter.collect(self.binding)
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertEqual(result.error.code, "INVALID_COLLECTION_CONTEXT")

    def test_explicit_mock_demo_does_not_echo_arguments_or_construct_live_client(self):
        for args, code in (([], 3), ([TOKEN], 3), (["--mock"], 0)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("socket.socket", side_effect=AssertionError("Network forbidden")), patch(
                "urllib.request.build_opener", side_effect=AssertionError("Opener forbidden"),
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(args), code)
            report = json.loads(stdout.getvalue())
            self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
            if code == 0:
                self.assertEqual(report["snapshot"]["data_source"], "mock")

    def test_live_client_cannot_consume_mock_binding_without_requests(self):
        adapter = CollectionContextAdapter(LiaraClient(ProviderConfig(api_key=TOKEN)), provider_scope="private-scope")
        with patch("urllib.request.OpenerDirector.open") as request:
            with self.assertRaises(CollectionContextError):
                adapter.collect(self.binding)
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
