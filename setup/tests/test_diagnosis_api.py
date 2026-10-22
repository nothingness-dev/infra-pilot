"""Consume the actual published API in-process; all evidence is synthetic MOCK."""

from dataclasses import replace
import json
import unittest

from fastapi.testclient import TestClient
from infrapilot_triage import ServiceSnapshot
from infrapilot_triage.api import create_app
from provider import MockLiaraClient

from setup.diagnosis_api import consume_diagnosis_response
from setup.tests.triage_fixtures import problem, service_evidence
from setup.triage import SetupIntegrationError, prepare_diagnosis


class PublishedDiagnosisApiTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(create_app()))

    def consume(self, evidence=None, **fields):
        evidence = evidence or service_evidence()
        response = self.client.post('/internal/triage/diagnose', json=evidence.snapshot.model_dump(mode='json'))
        return consume_diagnosis_response(problem(), evidence, status_code=response.status_code,
                                          payload=response.json() | fields)

    def test_actual_api_report_is_retained_without_reordering_or_dropping_fields(self):
        evidence = service_evidence()
        response = self.client.post('/internal/triage/diagnose', json=evidence.snapshot.model_dump(mode='json'))
        presentation = consume_diagnosis_response(problem(), evidence, status_code=response.status_code,
                                                 payload=response.json())
        self.assertEqual(presentation.to_dict()['report'], response.json())
        self.assertEqual(presentation.report.hypotheses[0].hypothesis_id, 'database_connection_failure')
        self.assertEqual(presentation.report.data_source.value, 'mock')
        self.assertFalse(presentation.execution_authorized)

    def test_api_redaction_is_preserved_in_both_report_and_presented_snapshot(self):
        secret = 'synthetic-secret-value'
        evidence = service_evidence(logs=[{'message': f'Authorization: Bearer {secret}'}])
        presentation = self.consume(evidence)
        self.assertNotIn(secret, json.dumps(presentation.to_dict()))
        self.assertTrue(any('redact' in item.lower() for item in presentation.report.limitations))
        self.assertIn(secret, evidence.snapshot.logs[0].message)  # Caller input was not changed.

    def test_incomplete_evidence_retains_nulls_and_explicit_empty_logs(self):
        for logs in (None, []):
            evidence = service_evidence(status='unknown', http_status=None, cpu_usage_percent=0,
                                        response_time_ms=None, logs=logs, timestamp=None)
            data = self.consume(evidence).to_dict()
            self.assertEqual(data['snapshot']['logs'], logs)
            self.assertIsNone(data['snapshot']['timestamp'])
            self.assertEqual(data['snapshot']['cpu_usage_percent'], 0)
            self.assertTrue(data['report']['missing_information'])

    def test_wrong_target_source_links_or_unknown_fields_cannot_enter_presentation(self):
        for fields in ({'service_id': 'another-service'}, {'data_source': 'real'}, {'approved': True},
                       {'hypotheses': [{'hypothesis_id': 'bad', 'explanation': 'bad', 'confidence': 1,
                                        'evidence_ids': ['not-in-report']}]}):
            with self.subTest(fields=fields), self.assertRaises(SetupIntegrationError):
                self.consume(**fields)

    def test_api_failure_or_unusable_body_is_not_a_diagnosis_and_does_not_echo_secrets(self):
        for status, payload in ((503, {'error': {'message': 'synthetic-secret'}}), (200, []),
                                (True, {}), (200, {'summary': 'synthetic-secret'})):
            with self.subTest(status=status), self.assertRaises(SetupIntegrationError) as caught:
                consume_diagnosis_response(problem(), service_evidence(), status_code=status, payload=payload)
            self.assertNotIn('synthetic-secret', str(caught.exception))

    def test_actual_api_validation_error_stays_an_error(self):
        response = self.client.post('/internal/triage/diagnose', json={'approved': True})
        self.assertEqual(response.status_code, 422)
        with self.assertRaises(SetupIntegrationError):
            consume_diagnosis_response(problem(), service_evidence(), status_code=response.status_code,
                                       payload=response.json())

    def test_actual_provider_native_bundle_is_not_misrepresented_as_normalized_snapshot(self):
        result = MockLiaraClient(failure_modes={'logs': 403}).collect_service_observations(
            'mock-service-A', logs_since='2026-10-22T00:00:00Z')
        self.assertFalse(result.success)
        self.assertTrue(result.is_mock)
        self.assertEqual(result.data.logs.availability, 'permission_denied')
        self.assertIsNone(result.data.metrics.data.cpu_unit)
        self.assertIsNone(result.data.metrics.data.memory_unit)
        self.assertNotIsInstance(result.data, ServiceSnapshot)
        evidence = replace(service_evidence(), snapshot=result.data)
        with self.assertRaises(SetupIntegrationError):
            prepare_diagnosis(problem(), evidence)


if __name__ == '__main__':
    unittest.main()
