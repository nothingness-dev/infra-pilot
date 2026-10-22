"""Contract tests using synthetic fixtures; no external services are contacted."""

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from infrapilot_triage import (
    ActionProposal,
    DataSource,
    DiagnosisReport,
    DiagnosticHypothesis,
    Evidence,
    LogEntry,
    ServiceSnapshot,
    ServiceStatus,
)


def snapshot_payload() -> dict[str, Any]:
    return {"service_id": "fixture-service", "status": "healthy", "data_source": "mock"}


def action_payload() -> dict[str, Any]:
    return {
        "action_id": "review-logs",
        "title": "Review logs",
        "description": "Ask the operator to review available service logs.",
        "risk_level": "low",
        "requires_approval": True,
    }


def report_payload() -> dict[str, Any]:
    return {
        "service_id": "fixture-service",
        "summary": "Synthetic contract fixture only.",
        "data_source": "mock",
        "evidence": [
            {"evidence_id": "e1", "kind": "http", "description": "Fixture HTTP 503."}
        ],
        "hypotheses": [
            {
                "hypothesis_id": "h1",
                "explanation": "Synthetic hypothesis for testing references.",
                "confidence": 0.7,
                "evidence_ids": ["e1"],
            }
        ],
        "actions": [action_payload()],
        "missing_information": ["CPU measurement unavailable."],
        "limitations": ["Synthetic data does not diagnose a real service."],
    }


def test_valid_snapshot_and_json_round_trip() -> None:
    snapshot = ServiceSnapshot(
        **snapshot_payload(),
        http_status=200,
        cpu_usage_percent=12.5,
        ram_usage_mib=128,
        response_time_ms=42,
        logs=[LogEntry(message="  fixture ready\n", level="info")],
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert snapshot.status is ServiceStatus.HEALTHY
    assert snapshot.logs is not None
    assert snapshot.logs[0].message == "  fixture ready\n"
    assert ServiceSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_missing_measurements_and_logs_are_none() -> None:
    snapshot = ServiceSnapshot(**snapshot_payload())
    for field in (
        "http_status", "cpu_usage_percent", "ram_usage_mib",
        "response_time_ms", "logs", "timestamp",
    ):
        assert getattr(snapshot, field) is None
        assert snapshot.model_dump()[field] is None


def test_zero_measurements_and_empty_logs_are_preserved() -> None:
    snapshot = ServiceSnapshot(
        **snapshot_payload(), cpu_usage_percent=0, ram_usage_mib=0,
        response_time_ms=0, logs=[],
    )
    assert snapshot.cpu_usage_percent == 0
    assert snapshot.ram_usage_mib == 0
    assert snapshot.response_time_ms == 0
    assert snapshot.logs == []
    restored = ServiceSnapshot.model_validate_json(snapshot.model_dump_json())
    assert restored.logs == []
    assert restored.cpu_usage_percent == 0


def test_explicit_null_measurements_and_logs() -> None:
    snapshot = ServiceSnapshot(
        **snapshot_payload(), cpu_usage_percent=None, ram_usage_mib=None, logs=None,
    )
    assert snapshot.cpu_usage_percent is None
    assert snapshot.ram_usage_mib is None
    assert snapshot.logs is None


@pytest.mark.parametrize("source", ["real", "mock"])
def test_data_sources_are_explicit_and_preserved(source: str) -> None:
    payload = snapshot_payload() | {"data_source": source}
    snapshot = ServiceSnapshot(**payload)
    report = DiagnosisReport(
        service_id=snapshot.service_id, summary="Contract fixture.", data_source=source,
    )
    assert snapshot.data_source is DataSource(source)
    assert report.model_dump(mode="json")["data_source"] == source


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan"), float("inf"), "0.5", True])
def test_invalid_confidence_is_rejected(confidence: Any) -> None:
    with pytest.raises(ValidationError):
        DiagnosticHypothesis(
            hypothesis_id="h1", explanation="Fixture.", confidence=confidence,
        )


@pytest.mark.parametrize("confidence", [0, 0.5, 1])
def test_confidence_boundaries_are_valid(confidence: float) -> None:
    hypothesis = DiagnosticHypothesis(
        hypothesis_id="h1", explanation="Fixture.", confidence=confidence,
    )
    assert hypothesis.confidence == confidence


def test_action_defaults_to_not_executed() -> None:
    action = ActionProposal(**action_payload())
    assert action.status == "not_executed"
    assert action.requires_approval is True
    other = ActionProposal(**(action_payload() | {"requires_approval": False}))
    assert other.requires_approval is False


@pytest.mark.parametrize("change", [
    {"status": "executed"}, {"risk_level": "safe"},
    {"requires_approval": "false"}, {"requires_approval": 0}, {"action_id": " "},
])
def test_invalid_action_is_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ActionProposal(**(action_payload() | change))


def test_approval_flag_must_be_supplied() -> None:
    payload = action_payload()
    del payload["requires_approval"]
    with pytest.raises(ValidationError):
        ActionProposal(**payload)


@pytest.mark.parametrize("change", [
    {"service_id": " "}, {"service_id": 123}, {"status": "up-ish"},
    {"data_source": "estimated"}, {"http_status": 99}, {"http_status": 600},
    {"http_status": True}, {"http_status": "200"},
    {"cpu_usage_percent": -1}, {"cpu_usage_percent": 101},
    {"cpu_usage_percent": "0"}, {"cpu_usage_percent": False},
    {"ram_usage_mib": -1}, {"response_time_ms": -1},
    {"ram_usage_mib": float("inf")}, {"response_time_ms": float("nan")},
    {"logs": "unavailable"}, {"logs": [{"message": 42}]},
    {"timestamp": "2026-01-01T00:00:00"}, {"timestamp": "not-a-date"},
    {"unexpected": "field"},
])
def test_invalid_snapshot_input_is_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ServiceSnapshot(**(snapshot_payload() | change))


@pytest.mark.parametrize("field", ["service_id", "status", "data_source"])
def test_required_snapshot_fields(field: str) -> None:
    payload = snapshot_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        ServiceSnapshot(**payload)


def test_valid_report_and_json_round_trip() -> None:
    report = DiagnosisReport(**report_payload())
    assert report.hypotheses[0].evidence_ids == [report.evidence[0].evidence_id]
    assert report.missing_information
    assert report.limitations
    assert DiagnosisReport.model_validate_json(report.model_dump_json()) == report


def test_unknown_evidence_reference_is_rejected() -> None:
    payload = report_payload()
    payload["hypotheses"][0]["evidence_ids"] = ["absent"]
    with pytest.raises(ValidationError, match="unknown evidence"):
        DiagnosisReport(**payload)


@pytest.mark.parametrize("collection", ["evidence", "hypotheses", "actions"])
def test_duplicate_report_identifiers_are_rejected(collection: str) -> None:
    payload = report_payload()
    payload[collection].append(payload[collection][0].copy())
    with pytest.raises(ValidationError, match="Duplicate identifiers"):
        DiagnosisReport(**payload)


def test_hypotheses_must_be_ranked_by_confidence() -> None:
    payload = report_payload()
    payload["hypotheses"].append({
        "hypothesis_id": "h2", "explanation": "Second fixture.",
        "confidence": 0.9, "evidence_ids": ["e1"],
    })
    with pytest.raises(ValidationError, match="descending confidence"):
        DiagnosisReport(**payload)
    payload["hypotheses"].reverse()
    assert DiagnosisReport(**payload).hypotheses[0].hypothesis_id == "h2"


def test_empty_reports_do_not_invent_observations() -> None:
    report = DiagnosisReport(
        service_id="fixture-service", summary="No observations supplied.", data_source="mock",
    )
    other = DiagnosisReport(
        service_id="fixture-service", summary="Another fixture.", data_source="mock",
    )
    other.evidence.append(Evidence(evidence_id="e1", kind="status", description="Fixture."))
    assert report.evidence == []
    assert report.hypotheses == []
    assert report.actions == []


@pytest.mark.parametrize("payload", [
    {"evidence_id": "", "kind": "log", "description": "Fixture."},
    {"evidence_id": "e1", "kind": "guess", "description": "Fixture."},
    {"evidence_id": "e1", "kind": "log", "description": " "},
])
def test_invalid_evidence_is_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Evidence(**payload)
