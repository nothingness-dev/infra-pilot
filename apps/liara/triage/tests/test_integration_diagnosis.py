"""QA scenarios traverse real HTTP validation, extraction, rules, and reporting."""

from typing import Any

from fastapi.testclient import TestClient
import pytest

from infrapilot_triage.api import create_app
from infrapilot_triage.schemas import DiagnosisReport, ServiceSnapshot


CASES = [
    pytest.param({"http_status": 500, "logs": [{"message": "PostgreSQL connection refused"}]},
                 "database_connection_failure", {"http-status", "log-0001"}, id="db-http500"),
    pytest.param({"cpu_usage_percent": 97, "response_time_ms": 2400},
                 "cpu_saturation", {"cpu-usage", "response-time"}, id="slow-high-cpu"),
    pytest.param({"ram_usage_mib": 1536, "logs": [{"message": "OOMKilled"}]},
                 "out_of_memory", {"ram-usage", "log-0001"}, id="memory-with-oom"),
    pytest.param({"ram_usage_mib": 1536, "logs": []},
                 "high_memory_usage", {"ram-usage"}, id="memory-without-oom"),
    pytest.param({"status": "healthy"}, None, set(), id="healthy-incomplete"),
    pytest.param({"response_time_ms": 2400, "logs": None},
                 "response_latency", {"response-time"}, id="missing-cpu-logs"),
    pytest.param({"http_status": 500, "logs": None},
                 "http_server_error", {"http-status"}, id="missing-logs"),
    pytest.param({"logs": [{"message": "PostgreSQL connection refused"}],
                  "timestamp": "2026-01-01T00:00:00Z"},
                 "database_connection_failure", {"log-0001"}, id="provider-like-partial"),
]


@pytest.mark.parametrize("source", ["mock", "real"])
@pytest.mark.parametrize("changes,top,support", CASES)
def test_http_scenario_preserves_only_supplied_observations(
    changes: dict[str, Any], top: str | None, support: set[str], source: str,
) -> None:
    snapshot = ServiceSnapshot.model_validate({
        "service_id": "QA-synthetic-service", "status": "unknown", "data_source": source, **changes,
    })
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json=snapshot.model_dump(mode="json"))
    assert response.status_code == 200
    report = DiagnosisReport.model_validate(response.json())
    assert report.service_id == snapshot.service_id and report.data_source == snapshot.data_source
    assert (report.hypotheses[0].hypothesis_id if report.hypotheses else None) == top
    expected_evidence = {"service-status"}
    for field, identifier in (("http_status", "http-status"), ("cpu_usage_percent", "cpu-usage"),
                              ("ram_usage_mib", "ram-usage"), ("response_time_ms", "response-time")):
        if getattr(snapshot, field) is not None:
            expected_evidence.add(identifier)
    if snapshot.logs:
        expected_evidence.update(f"log-{index:04d}" for index, _entry in enumerate(snapshot.logs, 1))
    observed = {item.evidence_id for item in report.evidence}
    assert observed == expected_evidence  # No synthetic telemetry or log entries.
    assert all(item.evidence_ids and set(item.evidence_ids) <= observed for item in report.hypotheses)
    if top:
        assert support <= set(report.hypotheses[0].evidence_ids)
    assert report.hypotheses == sorted(report.hypotheses, key=lambda item: (-item.confidence, item.hypothesis_id))
    assert all(item.status == "not_executed" for item in report.actions)
    assert any("heuristic" in item.lower() for item in report.limitations)
    assert any("provenance" in item.lower() for item in report.limitations)
    assert any("memory limit" in item.lower() for item in report.limitations)
    if snapshot.logs is None:
        assert any("logs are unavailable" in item for item in report.missing_information)
    if snapshot.cpu_usage_percent is None:
        assert any("CPU" in item for item in report.missing_information)
        assert "cpu_saturation" not in {item.hypothesis_id for item in report.hypotheses}
    assert any("Mock observations" in item for item in report.limitations) == (source == "mock")
    if top == "high_memory_usage":
        assert "out_of_memory" not in {item.hypothesis_id for item in report.hypotheses}
    if top in {"database_connection_failure", "cpu_saturation", "out_of_memory", "high_memory_usage"}:
        assert any(item.requires_approval for item in report.actions)


def test_invalid_partial_provider_envelope_requires_reviewed_normalization() -> None:
    # Illustrative provider-shaped data, not imported provider contracts or a
    # mapping implementation. The shared snapshot schema must not silently widen.
    raw = {"service_name": "QA-synthetic-service", "is_mock": True,
           "metrics": {"availability": "unverified", "cpu_unit": None}}
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json=raw)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "QA-synthetic-service" not in response.text


def test_advisory_sensitive_recommendation_creates_no_approval() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json={
            "service_id": "QA-synthetic-service", "status": "unknown", "data_source": "mock",
            "http_status": 500, "logs": [{"message": "PostgreSQL connection refused"}],
        })
        report = DiagnosisReport.model_validate(response.json())
        sensitive = next(item for item in report.actions if item.requires_approval)
        assert sensitive.action_id == "review_database_configuration"
        # This is a recommendation identifier, not a canonical operation.
        denied = client.post("/internal/triage/authorize", json={"intent": {
            "service_id": report.service_id, "action_type": sensitive.action_id,
        }})
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "approval_integration_unavailable"
    assert sensitive.status == "not_executed"
