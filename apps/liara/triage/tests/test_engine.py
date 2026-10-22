"""Scenario and regression tests for the public diagnosis entry point."""

from datetime import datetime, timezone
import socket
import subprocess
from typing import Any

import pytest

from infrapilot_triage import (
    DiagnosisReport, DiagnosisThresholds, DiagnosticHypothesis, LogEntry,
    ServiceSnapshot, diagnose,
)
from infrapilot_triage.rules import RuleFinding
from infrapilot_triage.symptoms import ExtractedSymptoms


def snapshot(**changes: Any) -> ServiceSnapshot:
    return ServiceSnapshot.model_validate({
        "service_id": "fixture", "status": "unknown", "data_source": "mock", **changes,
    })


@pytest.mark.parametrize("logs", [None, []])
def test_http_500_without_log_content(logs: list[LogEntry] | None) -> None:
    report = diagnose(snapshot(http_status=500, logs=logs))
    assert [h.hypothesis_id for h in report.hypotheses] == ["http_server_error"]
    assert report.hypotheses[0].evidence_ids == ["http-status"]
    assert any(a.action_id == "inspect_application_errors" for a in report.actions)
    assert any(a.action_id == "collect_observability" for a in report.actions)
    if logs is None:
        assert any("logs are unavailable" in m for m in report.missing_information)
    else:
        assert any("log collection is empty" in m for m in report.limitations)


def test_http_500_with_application_logs() -> None:
    report = diagnose(snapshot(http_status=500, logs=[
        LogEntry(message="Unhandled exception processing request", level="error"),
    ]))
    assert report.hypotheses[0].hypothesis_id == "application_error"
    assert "log-0001" in report.hypotheses[0].evidence_ids
    assert len([a for a in report.actions if a.action_id == "inspect_application_errors"]) == 1


def test_database_connection_failure_and_sensitive_recommendation() -> None:
    report = diagnose(snapshot(http_status=500, logs=[LogEntry(message="PostgreSQL connection refused")]))
    assert report.hypotheses[0].hypothesis_id == "database_connection_failure"
    assert set(report.hypotheses[0].evidence_ids) == {"log-0001", "http-status"}
    action = next(a for a in report.actions if a.action_id == "review_database_configuration")
    assert action.requires_approval
    assert action.status == "not_executed"


def test_high_cpu_with_slow_response() -> None:
    report = diagnose(snapshot(cpu_usage_percent=95, response_time_ms=2500))
    assert report.hypotheses[0].hypothesis_id == "cpu_saturation"
    assert set(report.hypotheses[0].evidence_ids) == {"cpu-usage", "response-time"}
    assert any(a.action_id == "review_resource_configuration" and a.requires_approval for a in report.actions)


def test_latency_with_missing_cpu_does_not_assume_cpu_saturation() -> None:
    report = diagnose(snapshot(response_time_ms=2500))
    assert [h.hypothesis_id for h in report.hypotheses] == ["response_latency"]
    assert not any(e.evidence_id == "cpu-usage" for e in report.evidence)
    assert any("CPU" in m for m in report.missing_information)


def test_high_ram_and_oom_evidence() -> None:
    report = diagnose(snapshot(ram_usage_mib=2048, logs=[LogEntry(message="OOMKilled")]))
    assert report.hypotheses[0].hypothesis_id == "out_of_memory"
    assert set(report.hypotheses[0].evidence_ids) == {"ram-usage", "log-0001"}
    assert any(a.action_id == "review_memory_configuration" and a.requires_approval for a in report.actions)


def test_high_ram_without_oom_remains_a_capacity_question() -> None:
    report = diagnose(snapshot(ram_usage_mib=2048))
    assert report.hypotheses[0].hypothesis_id == "high_memory_usage"
    assert "cannot be confirmed" in report.hypotheses[0].explanation
    assert any("memory limit" in limitation for limitation in report.limitations)


@pytest.mark.parametrize("state", ["unhealthy", "degraded"])
def test_bad_service_state_without_metrics(state: str) -> None:
    report = diagnose(snapshot(status=state))
    assert report.hypotheses[0].hypothesis_id == f"service_{state}"
    assert report.hypotheses[0].evidence_ids == ["service-status"]
    assert any(a.action_id == "inspect_service_health" for a in report.actions)


def test_incomplete_logs_and_missing_metrics_remain_explicit() -> None:
    report = diagnose(snapshot(http_status=500, logs=[LogEntry(message=""), LogEntry(message="request failed")]))
    assert any("blank" in m for m in report.limitations)
    assert any("partial or historical" in m for m in report.limitations)
    assert any("RAM" in m for m in report.missing_information)
    assert any("CPU" in m for m in report.missing_information)
    assert not any(e.evidence_id == "log-0001" for e in report.evidence)
    assert any(e.evidence_id == "log-0002" for e in report.evidence)


def test_healthy_service_with_incomplete_observability_is_not_declared_problem_free() -> None:
    report = diagnose(snapshot(status="healthy", http_status=200))
    assert report.hypotheses == []
    assert report.missing_information
    assert "incomplete observability" in report.summary
    assert [a.action_id for a in report.actions] == ["collect_observability"]


def test_no_failure_evidence_does_not_invent_a_hypothesis() -> None:
    report = diagnose(snapshot())
    assert report.hypotheses == []
    assert "Insufficient" in report.summary


def test_complete_zero_measurements_are_preserved() -> None:
    report = diagnose(snapshot(
        status="healthy", http_status=200, cpu_usage_percent=0,
        ram_usage_mib=0, response_time_ms=0, logs=[LogEntry(message="ready")],
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    assert report.hypotheses == []
    assert report.missing_information == []
    assert report.actions == []
    assert {"cpu-usage", "ram-usage", "response-time"} <= {e.evidence_id for e in report.evidence}


def test_conflicting_indicators_remain_visible() -> None:
    report = diagnose(snapshot(status="healthy", http_status=200, logs=[LogEntry(message="OOMKilled")]))
    assert report.hypotheses[0].hypothesis_id == "out_of_memory"
    assert any("conflicts" in m for m in report.limitations)
    assert any("successful HTTP" in m for m in report.limitations)
    assert {"service-status", "http-status", "log-0001"} <= {e.evidence_id for e in report.evidence}


@pytest.mark.parametrize("source", ["real", "mock"])
def test_source_and_service_identifier_are_preserved(source: str) -> None:
    report = diagnose(snapshot(service_id="service-A", data_source=source))
    assert report.service_id == "service-A"
    assert report.data_source == source
    assert any("Mock observations" in m for m in report.limitations) == (source == "mock")


def test_report_is_deterministic_ranked_linked_and_serializable() -> None:
    original = snapshot(
        status="unhealthy", http_status=500, cpu_usage_percent=95,
        ram_usage_mib=2048, response_time_ms=2000,
        logs=[LogEntry(message="OOMKilled"), LogEntry(message="database connection failed")],
    )
    before = original.model_dump_json()
    first = diagnose(original)
    assert diagnose(original).model_dump_json() == first.model_dump_json()
    assert original.model_dump_json() == before
    assert first.hypotheses[0].hypothesis_id == "out_of_memory"
    assert [h.confidence for h in first.hypotheses] == sorted((h.confidence for h in first.hypotheses), reverse=True)
    identifiers = {e.evidence_id for e in first.evidence}
    assert all(h.evidence_ids and set(h.evidence_ids) <= identifiers for h in first.hypotheses)
    assert len(first.actions) == len({a.action_id for a in first.actions})
    assert all(a.status == "not_executed" for a in first.actions)
    assert all(a.requires_approval for a in first.actions if a.risk_level in ("medium", "high"))
    assert DiagnosisReport.model_validate_json(first.model_dump_json()) == first


def test_equal_confidence_uses_identifier_as_stable_tiebreaker(monkeypatch: pytest.MonkeyPatch) -> None:
    from infrapilot_triage import engine

    def candidates(_observations: ExtractedSymptoms) -> tuple[RuleFinding, ...]:
        return tuple(RuleFinding(DiagnosticHypothesis(
            hypothesis_id=name, explanation="Synthetic tie fixture.", confidence=0.5,
            evidence_ids=["http-status"],
        ), ()) for name in ("z-cause", "a-cause"))

    monkeypatch.setattr(engine, "evaluate_rules", candidates)
    assert [h.hypothesis_id for h in diagnose(snapshot(http_status=500)).hypotheses] == ["a-cause", "z-cause"]


def test_public_threshold_configuration() -> None:
    report = diagnose(snapshot(cpu_usage_percent=80), thresholds=DiagnosisThresholds(high_cpu_percent=75))
    assert report.hypotheses[0].hypothesis_id == "cpu_saturation"


def test_diagnosis_has_no_network_or_process_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Diagnosis attempted a network connection or process execution")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    report = diagnose(snapshot(http_status=500, logs=[LogEntry(message="database connection failed")]))
    assert report.hypotheses
    assert all(a.status == "not_executed" for a in report.actions)
