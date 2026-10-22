"""Tests of evidence specificity and conservative diagnostic heuristics."""

from typing import Any

import pytest

from infrapilot_triage import LogEntry, ServiceSnapshot
from infrapilot_triage.rules import conflicting_indicators, evaluate_rules
from infrapilot_triage.symptoms import ExtractedSymptoms, extract_symptoms


def observations(**changes: Any) -> ExtractedSymptoms:
    return extract_symptoms(ServiceSnapshot.model_validate({
        "service_id": "fixture", "status": "unknown", "data_source": "mock", **changes,
    }))


@pytest.mark.parametrize("message,expected", [
    ("database connection refused", "database_connection_failure"),
    ("OOMKilled", "out_of_memory"),
    ("Unhandled exception", "application_error"),
])
def test_specific_log_evidence_outranks_generic_http(message: str, expected: str) -> None:
    extracted = observations(http_status=500, logs=[LogEntry(message=message, level="error")])
    hypotheses = {finding.hypothesis.hypothesis_id: finding.hypothesis for finding in evaluate_rules(extracted)}
    assert hypotheses[expected].confidence > hypotheses["http_server_error"].confidence
    assert "log-0001" in hypotheses[expected].evidence_ids


def test_http_500_alone_does_not_invent_a_specific_cause() -> None:
    findings = evaluate_rules(observations(http_status=500))
    assert [f.hypothesis.hypothesis_id for f in findings] == ["http_server_error"]
    assert findings[0].hypothesis.evidence_ids == ["http-status"]


def test_high_ram_alone_does_not_establish_exhaustion() -> None:
    findings = evaluate_rules(observations(ram_usage_mib=4096))
    assert [f.hypothesis.hypothesis_id for f in findings] == ["high_memory_usage"]
    assert "cannot be confirmed" in findings[0].hypothesis.explanation


def test_cpu_and_latency_have_stronger_support_than_cpu_alone() -> None:
    alone = evaluate_rules(observations(cpu_usage_percent=95))[0].hypothesis
    joint = evaluate_rules(observations(cpu_usage_percent=95, response_time_ms=2000))[0].hypothesis
    assert joint.confidence > alone.confidence
    assert set(joint.evidence_ids) == {"cpu-usage", "response-time"}
    assert alone.evidence_ids == ["cpu-usage"]


def test_oom_evidence_can_support_memory_exhaustion_without_ram_metrics() -> None:
    extracted = observations(logs=[LogEntry(message="OOMKilled")])
    hypothesis = evaluate_rules(extracted)[0].hypothesis
    assert hypothesis.hypothesis_id == "out_of_memory"
    assert hypothesis.evidence_ids == ["log-0001"]


def test_conflicting_healthy_state_reduces_confidence_and_is_disclosed() -> None:
    logs = [LogEntry(message="database connection failed")]
    uncertain = observations(status="healthy", http_status=500, logs=logs)
    ordinary = observations(status="unknown", http_status=500, logs=logs)
    assert evaluate_rules(uncertain)[0].hypothesis.confidence < evaluate_rules(ordinary)[0].hypothesis.confidence
    assert any("conflicts" in message for message in conflicting_indicators(uncertain))


@pytest.mark.parametrize("state", ["unhealthy", "degraded"])
def test_successful_http_does_not_erase_bad_health(state: str) -> None:
    extracted = observations(status=state, http_status=200)
    assert evaluate_rules(extracted)
    assert any("successful HTTP" in message for message in conflicting_indicators(extracted))


def test_all_candidates_reference_only_supplied_observations() -> None:
    extracted = observations(
        status="unhealthy", http_status=500, cpu_usage_percent=95,
        ram_usage_mib=2048, response_time_ms=3000,
        logs=[LogEntry(message="OOMKilled"), LogEntry(message="database connection failed")],
    )
    identifiers = {e.evidence_id for e in extracted.evidence}
    for finding in evaluate_rules(extracted):
        assert finding.hypothesis.evidence_ids
        assert set(finding.hypothesis.evidence_ids) <= identifiers
        assert 0 <= finding.hypothesis.confidence <= 1
