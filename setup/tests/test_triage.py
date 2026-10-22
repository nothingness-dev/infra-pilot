"""Integration tests call the actual published Diagnosis engine and canonical models."""

from dataclasses import asdict, replace
import json
import unittest
from unittest.mock import patch

from infrapilot_triage import DiagnosisReport, diagnose

from setup.integration import DependencyInput
from setup.models import OperationRequest
from setup.tests.triage_fixtures import changed_metadata, problem, service_evidence
from setup.triage import (
    SetupIntegrationError, prepare_diagnosis, submit_problem, supply_problem_information,
    validate_presentation,
)


class DiagnosisIntegrationTests(unittest.TestCase):
    def test_actual_report_preserves_rank_evidence_limitations_actions_and_provenance(self):
        request, evidence = problem(), service_evidence()
        result = prepare_diagnosis(request, evidence)
        data = result.to_dict()
        self.assertEqual(data["report"], diagnose(evidence.snapshot).model_dump(mode="json"))
        self.assertEqual(result.report.hypotheses[0].hypothesis_id, "database_connection_failure")
        self.assertEqual(data["snapshot"]["data_source"], "mock")
        self.assertEqual(data["association"]["provenance"], "mock")
        self.assertEqual(data["snapshot"]["timestamp"], "2026-10-22T00:00:00Z")
        self.assertTrue(data["report"]["limitations"])
        self.assertTrue(all(a["status"] == "not_executed" for a in data["report"]["actions"]))
        self.assertFalse(data["execution_authorized"])
        self.assertFalse(data["freshness_evaluated"])
        self.assertEqual(DiagnosisReport.model_validate(data["report"]), result.report)
        json.dumps(data, allow_nan=False)

    def test_missing_observations_and_zero_empty_logs_remain_distinct(self):
        for logs in (None, []):
            with self.subTest(logs=logs):
                evidence = service_evidence(status="unknown", http_status=None, cpu_usage_percent=0,
                                            response_time_ms=None, logs=logs, timestamp=None)
                data = prepare_diagnosis(problem(), evidence).to_dict()
                self.assertIsNone(data["snapshot"]["http_status"])
                self.assertEqual(data["snapshot"]["cpu_usage_percent"], 0)
                self.assertEqual(data["snapshot"]["logs"], logs)
                self.assertIsNone(data["snapshot"]["timestamp"])
                self.assertEqual(data["report"]["hypotheses"], [])
                self.assertTrue(data["report"]["missing_information"])

    def test_exact_request_target_version_source_state_and_reference_checks(self):
        evidence = service_evidence()
        cases = [
            changed_metadata(evidence, request_id="other"),
            changed_metadata(evidence, request_fingerprint="sha256:" + "0" * 64),
            changed_metadata(evidence, contract_version="future-v2"),
            changed_metadata(evidence, source="triage"),
            changed_metadata(evidence, state="pending"),
            changed_metadata(evidence, provenance="external"),
            replace(evidence, association=replace(evidence.association, output_reference="https://invalid")),
            replace(evidence, snapshot=evidence.snapshot.model_copy(update={"service_id": "other"})),
            replace(evidence, snapshot=evidence.snapshot.model_copy(update={"data_source": "real"})),
            replace(evidence, snapshot=evidence.snapshot.model_copy(update={"http_status": True})),
        ]
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(SetupIntegrationError):
                    prepare_diagnosis(problem(), item)
        with self.assertRaises(SetupIntegrationError):
            prepare_diagnosis(problem(), replace(evidence, association=DependencyInput(False, reason="unavailable")))

    def test_changed_target_or_goal_cannot_rebind_existing_evidence(self):
        evidence = service_evidence()
        for request in (problem(service_target="mock-service-B"), problem(goal="different problem"),
                        problem(service_target=" mock-service-A ")):
            with self.assertRaises(SetupIntegrationError):
                prepare_diagnosis(request, evidence)

    def test_mutable_canonical_models_are_revalidated_at_boundaries(self):
        result = prepare_diagnosis(problem(), service_evidence())
        result.report.summary = "Replaced summary"
        with self.assertRaisesRegex(SetupIntegrationError, "changed"):
            result.to_dict()
        result = prepare_diagnosis(problem(), service_evidence())
        result.report.hypotheses[0].evidence_ids.append("nonexistent")
        with self.assertRaises(SetupIntegrationError):
            validate_presentation(problem(), result)

    def test_report_target_and_source_mismatch_rejected(self):
        result = prepare_diagnosis(problem(), service_evidence())
        for fields in ({"service_id": "other"}, {"data_source": "real"}):
            report = DiagnosisReport.model_validate(result.report.model_dump() | fields)
            with self.assertRaises(SetupIntegrationError):
                validate_presentation(problem(), replace(result, report=report))

    def test_application_reuses_existing_submission_and_incremental_completion(self):
        payload = asdict(problem())
        first = submit_problem({**payload, "details": {}})
        self.assertEqual(first.state, "needs_information")
        self.assertIsNone(first.diagnosis)
        completed = supply_problem_information(first.to_dict()["request"], payload["details"],
                                                evidence=service_evidence())
        self.assertEqual(completed.state, "diagnosis_presented")
        self.assertEqual(completed.to_dict()["request"], payload)
        # Legacy preparation stays blocked; no opaque reference is invented to promote it.
        self.assertEqual(completed.preparation["state"], "blocked")
        self.assertFalse(completed.to_dict()["execution_performed"])
        stale = supply_problem_information(payload, {"goal": "changed"}, evidence=service_evidence())
        self.assertEqual(stale.state, "blocked")

    def test_no_evidence_no_automatic_provider_calls_or_synthetic_report(self):
        result = submit_problem(asdict(problem()))
        self.assertEqual(result.state, "evidence_required")
        self.assertIsNone(result.diagnosis)
        result = submit_problem({**asdict(problem()), "approved": True}, evidence=service_evidence())
        self.assertEqual(result.state, "blocked")
        self.assertIsNone(result.diagnosis)
        request = OperationRequest("setup", "setup_service", {
            "service_name": "mock", "service_kind": "unknown", "goal": "prepare only",
        })
        with self.assertRaises(SetupIntegrationError):
            prepare_diagnosis(request, service_evidence())

    def test_diagnosis_flow_cannot_use_network_processes_or_provider_operations(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("No I/O allowed during diagnosis composition")
        with patch("socket.socket", forbidden), patch("subprocess.Popen", forbidden), patch("os.system", forbidden):
            result = prepare_diagnosis(problem(), service_evidence())
            self.assertEqual(result.report.data_source.value, "mock")


if __name__ == "__main__":
    unittest.main()
