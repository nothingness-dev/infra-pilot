"""Explicit optional QA against the teammate's draft; not a runtime dependency.

Run with triage's dependencies installed and its src directory on PYTHONPATH:
python -B -m unittest discover -s provider/qa -v
"""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from infrapilot_triage.api import create_app
from infrapilot_triage.schemas import DiagnosisReport, ServiceSnapshot
from provider import MockLiaraClient, TriageAdapter
from provider.examples.triage_handoff import mock_handoff


class DraftCompatibilityTests(unittest.TestCase):
    def test_generated_and_committed_fixture_validate_without_schema_extensions(self):
        fixture = Path(__file__).parents[1] / "examples" / "mock_triage_snapshot.json"
        for request in (mock_handoff().snapshot.to_request(), json.loads(fixture.read_text(encoding="utf-8"))):
            with self.subTest(source=request["data_source"]):
                snapshot = ServiceSnapshot.model_validate(request)
                self.assertEqual(snapshot.model_dump(mode="json"), request)

    def test_sidecar_is_deliberately_not_an_endpoint_request(self):
        with self.assertRaises(ValidationError):
            ServiceSnapshot.model_validate(mock_handoff().to_dict())

    def test_actual_diagnose_endpoint_accepts_provider_payload_without_network(self):
        # Start ASGI first: Windows asyncio uses a loopback socketpair internally.
        # The actual request has no HTTP listener or external network transport.
        with TestClient(create_app()) as client:
            with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
                response = client.post("/internal/triage/diagnose", json=mock_handoff().snapshot.to_request())
        self.assertEqual(response.status_code, 200)
        report = DiagnosisReport.model_validate(response.json())
        self.assertEqual(report.service_id, "MOCK-service")
        self.assertEqual(report.data_source.value, "mock")
        self.assertTrue(report.missing_information)
        self.assertTrue(all(action.status == "not_executed" for action in report.actions))

    def test_partial_and_unavailable_bundles_produce_valid_conservative_requests(self):
        for mode in (401, 403, 404, 429, "timeout", "missing", "empty", "invalid_response"):
            with self.subTest(mode=mode):
                result = TriageAdapter(MockLiaraClient(failure_modes={"logs": mode})).collect(
                    "mock-project", service_id="MOCK-service", logs_since="since",
                )
                snapshot = ServiceSnapshot.model_validate(result.data.snapshot.to_request())
                self.assertEqual(snapshot.status.value, "unknown")
                self.assertIsNone(snapshot.cpu_usage_percent)
                self.assertIsNone(snapshot.ram_usage_mib)
                with TestClient(create_app()) as client:
                    response = client.post("/internal/triage/diagnose", json=snapshot.model_dump(mode="json"))
                self.assertEqual(response.status_code, 200)
                DiagnosisReport.model_validate(response.json())


if __name__ == "__main__":
    unittest.main()
