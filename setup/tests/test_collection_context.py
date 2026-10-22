"""Synthetic PR #12 fixture checks; run through the pinned QA bootstrap."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from setup.collection_context import (
        CollectionCompanion, attach_collection_diagnosis, consume_collection_diagnosis_response,
        preserve_collection_context, _display,
    )
except ModuleNotFoundError as error:
    if error.name == "provider.collection_context":
        raise unittest.SkipTest("Use setup/qa/run_collection_context_checks.py for pending Provider PR #12.") from None
    raise

from infrapilot_triage import ServiceSnapshot
from infrapilot_triage import ApprovalGate
from infrapilot_triage.api import create_app
from infrapilot_triage.redaction import redact_log_message
from fastapi.testclient import TestClient
import provider
from provider import CollectionContextAdapter, LiaraClient, MockLiaraClient, ProviderConfig, ServiceLog
from provider.examples.context_fixtures import MOCK_CONTEXT_SCENARIOS, build_mock_context, mock_context_binding

from setup.application import submit_request
from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import SetupIntegrationError, SnapshotEvidence
from setup.triage import prepare_diagnosis, consume_diagnosis
from setup.approval_workflow import SetupApprovalWorkflow


def request_for(target="MOCK-service"):
    return OperationRequest("mock-context-request", "inspect_service", {
        "service_target": target, "goal": "Review only these synthetic observations",
    })


def evidence_for(request, prepared, *, provenance="mock"):
    snapshot = ServiceSnapshot.model_validate(prepared.to_request()["snapshot"])
    metadata = ResultMetadata(CONTRACT_VERSION, request.request_id, request.operation,
                              request_fingerprint(request), "provider", "ready", provenance)
    return SnapshotEvidence(snapshot, DependencyInput(True, f"{provenance if provenance == 'mock' else 'external'}:provider-context", metadata=metadata))


def preserve(prepared, request=None, evidence=None, binding=None):
    request = request or request_for()
    return preserve_collection_context(request, evidence or evidence_for(request, prepared),
                                       prepared=prepared, expected_binding=binding or mock_context_binding())


class CollectionContextBoundaryTests(unittest.TestCase):
    def test_all_actual_fixtures_preserve_exact_context_snapshot_and_digest_semantics(self):
        directory = Path(provider.__file__).parent / "examples/fixtures/context_v02"
        for scenario in MOCK_CONTEXT_SCENARIOS:
            with self.subTest(scenario=scenario):
                fixture = json.loads((directory / f"{scenario}.json").read_text(encoding="utf-8"))
                prepared = build_mock_context(scenario)
                self.assertEqual(prepared.to_request(), fixture)
                outcome = preserve(prepared)
                self.assertEqual(outcome.state, "context_preserved")
                data = outcome.to_dict()["companion"]
                self.assertEqual(data["collection_context"], fixture["collection_context"])
                self.assertEqual(data["snapshot"], fixture["snapshot"])
                canonical = json.dumps(data["snapshot"], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
                self.assertEqual(data["collection_context"]["snapshot_digest"], "sha256:" + hashlib.sha256(canonical.encode("ascii")).hexdigest())
                self.assertFalse(data["execution_performed"])
                self.assertFalse(data["execution_authorized"])
                self.assertFalse(data["authorization_consumed"])
                self.assertEqual(data["production_readiness"], "unresolved")
                self.assertNotIn("mock-project", json.dumps(data))
                self.assertNotIn("mock-account", json.dumps(data))

    def test_partial_failure_retains_successes_and_denial_rate_limit_retry_hints(self):
        data = preserve(build_mock_context("partial_failure")).to_dict()["companion"]
        capabilities = {item["capability"]: item for item in data["collection_context"]["capabilities"]}
        self.assertEqual(capabilities["service"]["availability"], "available")
        self.assertEqual(capabilities["deployment"]["availability"], "available")
        self.assertEqual(capabilities["logs"]["availability"], "permission_denied")
        self.assertEqual(capabilities["logs"]["http_status"], 403)
        self.assertFalse(capabilities["logs"]["retryable"])
        self.assertEqual(capabilities["metrics"]["http_status"], 429)
        self.assertTrue(capabilities["metrics"]["retryable"])
        self.assertEqual(data["display"]["collection_state"], "partial_failure")
        self.assertEqual(len(data["display"]["collection_errors"]), 2)
        self.assertIsNone(data["snapshot"]["cpu_usage_percent"])
        self.assertIsNone(data["snapshot"]["timestamp"])

    def test_empty_unavailable_discarded_skipped_and_partial_logs_are_distinct(self):
        expected = {
            "empty": ("collected_empty", 0, 0, 0, []),
            "unavailable": ("data_unavailable", None, 0, 0, None),
            "withheld": ("deliberately_withheld", 1, 0, 1, None),
            "not_collected": ("not_collected", None, 0, 0, None),
            "partial_logs": ("partially_exported", 2, 1, 1, "surviving"),
        }
        for scenario, values in expected.items():
            with self.subTest(scenario=scenario):
                data = preserve(build_mock_context(scenario)).to_dict()["companion"]
                logs = data["display"]["logs"]
                self.assertEqual(tuple(logs[key] for key in ("display_state", "received", "exported", "withheld")), values[:4])
                if values[4] == "surviving":
                    self.assertEqual(data["snapshot"]["logs"][0]["message"], "Synthetic application started")
                else:
                    self.assertEqual(data["snapshot"]["logs"], values[4])

    def test_same_snapshot_digest_does_not_collapse_different_contexts(self):
        withheld = preserve(build_mock_context("withheld")).to_dict()["companion"]
        unavailable = preserve(build_mock_context("unavailable")).to_dict()["companion"]
        self.assertEqual(withheld["snapshot"], unavailable["snapshot"])
        self.assertEqual(withheld["collection_context"]["snapshot_digest"], unavailable["collection_context"]["snapshot_digest"])
        self.assertNotEqual(withheld["companion_binding"], unavailable["companion_binding"])

    def test_request_service_snapshot_and_source_mismatches_fail_closed(self):
        request = request_for()
        prepared = build_mock_context("exported")
        evidence = evidence_for(request, prepared)
        changed_request = replace(request, details={**request.details, "goal": "Different goal"})
        changed_snapshot = evidence.snapshot.model_copy(update={"status": "healthy"})
        source = replace(evidence.association.metadata, provenance="external")
        variants = (
            (replace(request, request_id="other-request"), evidence, mock_context_binding()),
            (changed_request, evidence, mock_context_binding()),
            (request_for("other-service"), evidence, mock_context_binding()),
            (request, replace(evidence, snapshot=changed_snapshot), mock_context_binding()),
            (request, evidence, replace(mock_context_binding(), project_name="other-project")),
            (request, evidence, replace(mock_context_binding(), provider_scope="other-scope")),
            (request, replace(evidence, association=replace(evidence.association, output_reference="external:provider-context", metadata=source)), mock_context_binding()),
        )
        for current, supplied, binding in variants:
            with self.subTest(target=current.details["service_target"]):
                outcome = preserve_collection_context(current, supplied, prepared=prepared, expected_binding=binding)
                self.assertEqual(outcome.state, "blocked")
                self.assertIsNone(outcome.to_dict()["companion"])

    def test_missing_or_forged_frontend_reference_cannot_establish_provenance(self):
        prepared = build_mock_context()
        request = request_for()
        evidence = evidence_for(request, prepared)
        for reference in (None, prepared.to_request(), {"approved": True, "binding": "sha256:" + "a" * 64}):
            outcome = preserve_collection_context(request, evidence, prepared=reference, expected_binding=mock_context_binding())
            self.assertEqual(outcome.state, "unresolved")
            self.assertEqual(outcome.errors[0].code, "producer_reference_required")
            self.assertIsNone(outcome.to_dict()["companion"])
        rejected = submit_request({"request_id": request.request_id, "operation": request.operation,
                                   "details": request.details, "collection_context": prepared.to_request()})
        self.assertEqual(rejected["errors"][0]["code"], "unknown_field")
        with self.assertRaises(SetupIntegrationError):
            CollectionCompanion()

    def test_sanitization_before_binding_with_actual_escaped_quote_fix_and_no_sensitive_output(self):
        binding = mock_context_binding()
        token = "MOCK_TOKEN_VALUE_ONLY"
        canary = "MOCK_ESCAPED_PASSWORD_SUFFIX"
        client = MockLiaraClient(ProviderConfig(api_key=token))
        bundle = client.collect_service_observations(binding.project_name, logs_since="synthetic").data
        message = 'password="prefix\\"' + canary + '" ' + token
        bundle = replace(bundle, logs=replace(bundle.logs, data=[ServiceLog(message, None, None)]))
        adapter = CollectionContextAdapter(client, provider_scope=binding.provider_scope)
        capture = io.StringIO()
        with redirect_stdout(capture), redirect_stderr(capture), self.assertNoLogs():
            safe = adapter.from_observations(bundle, binding=binding, log_sanitizer=redact_log_message)
            outcome = preserve(safe)
            displayed = json.dumps(outcome.to_dict()) + repr(outcome) + repr(outcome.companion)
            self.assertEqual(outcome.state, "context_preserved")
            unsafe = adapter.from_observations(bundle, binding=binding, log_sanitizer=lambda value: value)
            with patch("setup.collection_context._binding", side_effect=AssertionError("Must sanitize before associating")):
                blocked = preserve(unsafe)
            self.assertEqual(blocked.state, "blocked")
            self.assertEqual(blocked.errors[0].code, "sanitization_order_conflict")
            displayed += json.dumps(blocked.to_dict()) + repr(blocked)
        for secret in (token, canary):
            self.assertNotIn(secret, displayed + capture.getvalue())
        self.assertIn(canary, bundle.logs.data[0].message)  # Caller data was not modified.

    def test_detached_payload_and_mutated_evidence_cannot_reappear_as_verified(self):
        outcome = preserve(build_mock_context("exported"))
        first = outcome.to_dict()
        first["companion"]["collection_context"]["limitations"].clear()
        self.assertTrue(outcome.to_dict()["companion"]["collection_context"]["limitations"])
        outcome.companion.evidence.snapshot.logs[0].message = "password=MOCK_LATE_SECRET"
        data = outcome.to_dict()
        self.assertEqual(data["state"], "blocked")
        self.assertIsNone(data["companion"])
        self.assertNotIn("MOCK_LATE_SECRET", json.dumps(data))

    def test_unknown_collector_times_and_reserved_outcomes_are_not_fabricated(self):
        binding = mock_context_binding()
        client = MockLiaraClient()
        bundle = client.collect_service_observations(binding.project_name).data
        for state in ("unsupported", "unverified"):
            observations = replace(bundle, logs=replace(bundle.logs, availability=state, data=None),
                                   collection_started_at=None, collection_finished_at=None)
            prepared = CollectionContextAdapter(client, provider_scope=binding.provider_scope).from_observations(observations, binding=binding)
            data = preserve(prepared).to_dict()["companion"]
            self.assertIsNone(data["collection_context"]["collection_started_at"])
            self.assertIsNone(data["collection_context"]["collection_finished_at"])
            self.assertEqual(data["display"]["logs"]["display_state"], state)
            self.assertIsNone(data["snapshot"]["logs"])

    def test_real_label_is_a_synthetic_provenance_claim_not_readiness_or_live_access(self):
        binding = replace(mock_context_binding(), is_mock=False)
        mock = MockLiaraClient()
        bundle = mock.collect_service_observations(binding.project_name).data
        bundle = replace(bundle, is_mock=False, **{name: replace(getattr(bundle, name), is_mock=False)
                                                for name in ("service", "deployment", "logs", "metrics")})
        # Construct the real-mode configuration but forbid every collection/network call.
        with patch("socket.socket.connect", side_effect=AssertionError("No live access")):
            client = LiaraClient(ProviderConfig(api_key="MOCK_SYNTHETIC_CONFIG_ONLY", is_mock=False))
            prepared = CollectionContextAdapter(client, provider_scope=binding.provider_scope).from_observations(bundle, binding=binding)
            request = request_for()
            evidence = evidence_for(request, prepared, provenance="external")
            data = preserve(prepared, request, evidence, binding).to_dict()["companion"]
        self.assertEqual(data["display"]["source_claim"], "real")
        self.assertFalse(data["display"]["provenance_verified"])
        self.assertFalse(data["display"]["freshness_evaluated"])
        self.assertEqual(data["production_readiness"], "unresolved")
        self.assertFalse(data["execution_authorized"])

    def test_unknown_outcome_is_explicit_and_not_successful_empty(self):
        context = build_mock_context("empty").to_request()["collection_context"]
        context["log_export"]["state"] = "future_unknown_outcome"
        display = _display(context)
        self.assertEqual(display["logs"]["display_state"], "unknown")
        self.assertEqual(display["logs"]["state"], "future_unknown_outcome")

    def test_new_producer_version_requires_review_instead_of_automatic_acceptance(self):
        # Simulate an installed producer publishing a new version through its
        # actual factory; Setup's reviewed version must not follow it silently.
        with patch("provider.collection_context.COLLECTION_CONTEXT_VERSION", "provider-collection-context/future-draft"):
            prepared = build_mock_context("empty")
        outcome = preserve(prepared)
        self.assertEqual(outcome.state, "blocked")
        self.assertEqual(outcome.errors[0].code, "unsupported_collection_contract")
        self.assertIsNone(outcome.to_dict()["companion"])


class CollectionDiagnosisCompatibilityTests(unittest.TestCase):
    def test_actual_api_and_existing_consumer_keep_full_diagnosis_and_separate_bindings(self):
        request = request_for()
        with TestClient(create_app()) as api:
            for scenario in MOCK_CONTEXT_SCENARIOS:
                with self.subTest(scenario=scenario):
                    prepared = build_mock_context(scenario)
                    original = preserve(prepared).companion
                    response = api.post("/internal/triage/diagnose", json=prepared.to_request()["snapshot"])
                    self.assertEqual(response.status_code, 200)
                    outcome = consume_collection_diagnosis_response(request, original, status_code=200, payload=response.json())
                    self.assertEqual(outcome.state, "diagnosis_associated")
                    data = outcome.to_dict()["companion"]
                    self.assertEqual(data["diagnosis"]["report"], response.json())
                    self.assertEqual(data["diagnosis"]["snapshot"], data["snapshot"])
                    self.assertEqual(data["collection_context"], prepared.to_request()["collection_context"])
                    self.assertNotEqual(original.binding, outcome.companion.binding)
                    existing = consume_diagnosis(request, original.evidence, outcome.companion.diagnosis.report)
                    self.assertEqual(existing.binding, data["diagnosis"]["binding"])
                    self.assertNotEqual(data["companion_binding"], existing.binding)
                    self.assertNotIn("collection_context", data["diagnosis"]["report"])
                    self.assertTrue(all(action["status"] == "not_executed" for action in data["diagnosis"]["report"]["actions"]))

    def test_changed_request_snapshot_report_and_source_reference_invalidate_attachment(self):
        request = request_for()
        prepared = build_mock_context("exported")
        companion = preserve(prepared).companion
        presentation = prepare_diagnosis(request, companion.evidence)
        changed = replace(request, details={**request.details, "goal": "Changed goal"})
        self.assertEqual(attach_collection_diagnosis(changed, companion, presentation).state, "blocked")
        self.assertEqual(attach_collection_diagnosis(request, companion.to_dict(), presentation).state, "blocked")
        changed_evidence = replace(companion.evidence, association=replace(companion.evidence.association, output_reference="mock:another-source"))
        other_presentation = prepare_diagnosis(request, changed_evidence)
        failed = attach_collection_diagnosis(request, companion, other_presentation)
        self.assertEqual(failed.errors[0].code, "context_diagnosis_mismatch")
        other_snapshot = preserve(build_mock_context("empty")).companion
        self.assertEqual(attach_collection_diagnosis(request, other_snapshot, presentation).state, "blocked")
        presentation.report.summary = "MOCK_MUTATED_REPORT_SECRET"
        failed = attach_collection_diagnosis(request, companion, presentation)
        self.assertEqual(failed.state, "blocked")
        self.assertNotIn("MOCK_MUTATED_REPORT_SECRET", json.dumps(failed.to_dict()))

    def test_failure_bodies_and_frontend_companion_metadata_never_escape(self):
        request = request_for()
        companion = preserve(build_mock_context()).companion
        for status, payload in ((503, {"trace": "MOCK_PRIVATE_TRACE"}), (200, {"summary": "MOCK_PRIVATE_TRACE"}), (True, {})):
            outcome = consume_collection_diagnosis_response(request, companion, status_code=status, payload=payload)
            self.assertEqual(outcome.state, "blocked")
            self.assertIsNone(outcome.to_dict()["companion"])
            self.assertNotIn("MOCK_PRIVATE_TRACE", json.dumps(outcome.to_dict()) + repr(outcome))
        forged = consume_collection_diagnosis_response(request, companion.to_dict(), status_code=200, payload={})
        self.assertEqual(forged.errors[0].code, "backend_companion_required")

    def test_no_new_approval_authorization_consumption_or_execution_is_invoked(self):
        request = request_for()
        with patch.object(ApprovalGate, "authorize", side_effect=AssertionError("Consumption forbidden")), \
                patch.object(SetupApprovalWorkflow, "request_approval", side_effect=AssertionError("Approval forbidden")), \
                patch.object(SetupApprovalWorkflow, "approve", side_effect=AssertionError("Approval forbidden")), \
                patch.object(SetupApprovalWorkflow, "reject", side_effect=AssertionError("Approval forbidden")), \
                patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            companion = preserve(build_mock_context("partial_logs")).companion
            report = prepare_diagnosis(request, companion.evidence)
            outcome = attach_collection_diagnosis(request, companion, report)
            data = outcome.to_dict()["companion"]
        self.assertEqual(outcome.state, "diagnosis_associated")
        self.assertEqual(data["execution"]["state"], "execution_disabled")
        self.assertFalse(data["execution_authorized"])
        self.assertFalse(data["execution_performed"])
        self.assertFalse(data["authorization_consumed"])


if __name__ == "__main__":
    unittest.main()
