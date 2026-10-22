"""Explicit in-process QA using published Setup and Task 05A implementations.

Run from the isolated reviewed checkout with its source directories first on
PYTHONPATH; see provider/COLLECTION_CONTEXT_DRAFT.md. No shared code is changed.
"""

from dataclasses import replace
import json
import unittest

from fastapi.testclient import TestClient
from infrapilot_triage import ServiceSnapshot
from infrapilot_triage.api import create_app
from infrapilot_triage.redaction import redact_log_message
from setup.diagnosis_api import consume_diagnosis_response
from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import SetupIntegrationError, SnapshotEvidence

from provider import (
    CollectionContextAdapter, CollectionContextError, MockLiaraClient, ServiceBinding, ServiceLog,
)
from provider.examples.context_fixtures import (
    MOCK_CONTEXT_SCENARIOS, build_mock_context, mock_context_binding,
)


def request_for(service_id="MOCK-service"):
    return OperationRequest("mock-integration-request", "inspect_service", {
        "service_target": service_id, "goal": "Review supplied mock observations",
    })


def evidence_for(request, snapshot):
    # This is trusted test orchestration, not frontend metadata or authenticity.
    metadata = ResultMetadata(CONTRACT_VERSION, request.request_id, request.operation,
                              request_fingerprint(request), "provider", "ready", "mock")
    return SnapshotEvidence(snapshot, DependencyInput(True, "mock:provider-context", metadata=metadata))


class SetupProviderCompatibilityTests(unittest.TestCase):
    def test_all_mock_context_cases_survive_provider_diagnosis_and_setup_without_execution(self):
        with TestClient(create_app()) as api:
            for scenario in MOCK_CONTEXT_SCENARIOS:
                with self.subTest(scenario=scenario):
                    prepared = build_mock_context(scenario)
                    envelope = prepared.verify_request(prepared.to_request(), expected_binding=mock_context_binding())
                    snapshot = ServiceSnapshot.model_validate(envelope["snapshot"])
                    request = request_for()
                    response = api.post("/internal/triage/diagnose", json=envelope["snapshot"])
                    self.assertEqual(response.status_code, 200)
                    presentation = consume_diagnosis_response(
                        request, evidence_for(request, snapshot), status_code=response.status_code, payload=response.json(),
                    )
                    output = presentation.to_dict()
                    self.assertEqual(output["snapshot"], envelope["snapshot"])
                    self.assertEqual(output["report"]["data_source"], "mock")
                    self.assertFalse(output["execution_performed"])
                    self.assertFalse(output["execution_authorized"])
                    self.assertTrue(all(item["status"] == "not_executed" for item in output["report"]["actions"]))
                    # Context stays alongside the current response, never silently
                    # inserted into the legacy report or dropped by this test flow.
                    self.assertEqual(prepared.to_request()["collection_context"], envelope["collection_context"])

    def test_new_envelope_is_not_silently_accepted_by_current_diagnosis_endpoint(self):
        with TestClient(create_app()) as api:
            response = api.post("/internal/triage/diagnose", json=build_mock_context().to_request())
        self.assertEqual(response.status_code, 422)

    def test_task05a_log_sanitizer_runs_before_binding_and_setup_retains_same_safe_snapshot(self):
        binding = mock_context_binding()
        client = MockLiaraClient()
        bundle = client.collect_service_observations(binding.project_name, logs_since="since").data
        canary = "MOCK_ESCAPED_PASSWORD_SUFFIX"
        message = 'password="prefix\\"' + canary + '"'
        bundle = replace(bundle, logs=replace(bundle.logs, data=[ServiceLog(message, None, None)]))
        prepared = CollectionContextAdapter(client, provider_scope=binding.provider_scope).from_observations(
            bundle, binding=binding, log_sanitizer=redact_log_message,
        )
        envelope = prepared.to_request()
        request = request_for()
        snapshot = ServiceSnapshot.model_validate(envelope["snapshot"])
        with TestClient(create_app()) as api:
            response = api.post("/internal/triage/diagnose", json=envelope["snapshot"])
        self.assertEqual(response.status_code, 200)
        presentation = consume_diagnosis_response(
            request, evidence_for(request, snapshot), status_code=200, payload=response.json(),
        )
        self.assertNotIn(canary, json.dumps(envelope))
        self.assertNotIn(canary, json.dumps(presentation.to_dict()))
        self.assertEqual(presentation.to_dict()["snapshot"], envelope["snapshot"])
        self.assertEqual(prepared.verify_request(envelope, expected_binding=binding), envelope)

    def test_wrong_target_or_source_fails_at_both_relevant_boundaries(self):
        binding = mock_context_binding()
        prepared = build_mock_context()
        envelope = prepared.to_request()
        snapshot = ServiceSnapshot.model_validate(envelope["snapshot"])
        other = request_for("other-service")
        with self.assertRaises(SetupIntegrationError):
            consume_diagnosis_response(other, evidence_for(other, snapshot), status_code=200, payload={})
        with self.assertRaises(CollectionContextError):
            prepared.verify_request(envelope, expected_binding=replace(binding, service_id="other-service"))
        request = request_for()
        evidence = evidence_for(request, snapshot)
        metadata = replace(evidence.association.metadata, provenance="external")
        wrong_source = replace(evidence, association=replace(
            evidence.association, output_reference="external:provider-context", metadata=metadata,
        ))
        with self.assertRaises(SetupIntegrationError) as caught:
            consume_diagnosis_response(request, wrong_source, status_code=200, payload={})
        self.assertEqual(caught.exception.error.code, "provenance_mismatch")

    def test_changed_setup_brief_or_mismatched_report_is_not_bound_to_current_snapshot(self):
        envelope = build_mock_context().to_request()
        snapshot = ServiceSnapshot.model_validate(envelope["snapshot"])
        request = request_for()
        evidence = evidence_for(request, snapshot)
        changed = replace(request, details={**request.details, "goal": "Changed mock goal"})
        with self.assertRaises(SetupIntegrationError):
            consume_diagnosis_response(changed, evidence, status_code=200, payload={})
        with TestClient(create_app()) as api:
            response = api.post("/internal/triage/diagnose", json=envelope["snapshot"])
        other_report = {**response.json(), "service_id": "other-service"}
        with self.assertRaises(SetupIntegrationError) as caught:
            consume_diagnosis_response(request, evidence, status_code=200, payload=other_report)
        self.assertEqual(caught.exception.error.code, "diagnosis_mismatch")


if __name__ == "__main__":
    unittest.main()
