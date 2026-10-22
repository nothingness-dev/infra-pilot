"""Synthetic symptom fixtures; no provider or real service is involved."""

from typing import Any

import pytest
from pydantic import ValidationError

from infrapilot_triage import LogEntry, ServiceSnapshot
from infrapilot_triage.symptoms import DiagnosisThresholds, Symptom, extract_symptoms


def snapshot(**changes: Any) -> ServiceSnapshot:
    return ServiceSnapshot.model_validate({
        "service_id": "fixture", "status": "unknown", "data_source": "mock", **changes,
    })


def test_missing_metrics_and_logs_produce_no_measurements() -> None:
    observations = extract_symptoms(snapshot())
    assert [e.evidence_id for e in observations.evidence] == ["service-status"]
    assert observations.signals == ()
    assert any("CPU" in message for message in observations.missing_information)
    assert any("RAM" in message for message in observations.missing_information)
    assert any("logs are unavailable" in message for message in observations.missing_information)


def test_zero_is_an_observation_and_empty_logs_are_collected() -> None:
    observations = extract_symptoms(snapshot(
        cpu_usage_percent=0, ram_usage_mib=0, response_time_ms=0, logs=[],
    ))
    metrics = [e for e in observations.evidence if e.kind == "metric"]
    assert len(metrics) == 3
    assert all(": 0 " in e.description for e in metrics)
    assert observations.signals == ()
    assert not any("measurement is unavailable" in message for message in observations.missing_information)
    assert not any("logs are unavailable" in message for message in observations.missing_information)
    assert any("log collection is empty" in message for message in observations.limitations)


@pytest.mark.parametrize("status", [500, 503, 599])
def test_server_error_range(status: int) -> None:
    observations = extract_symptoms(snapshot(http_status=status))
    assert observations.supporting_ids(Symptom.HTTP_SERVER_ERROR) == ("http-status",)


@pytest.mark.parametrize("status", [200, 302, 400, 404])
def test_other_http_statuses_are_not_server_errors(status: int) -> None:
    assert not extract_symptoms(snapshot(http_status=status)).has(Symptom.HTTP_SERVER_ERROR)


@pytest.mark.parametrize("message", [
    "Database connection failed",
    "psycopg2.OperationalError: could not connect to server",
    "PostgreSQL connection refused",
    "MySQL connection timeout",
    "Redis ECONNREFUSED",
    "MongoDB unavailable",
    "database connection pool exhausted",
])
def test_database_failure_requires_context_and_failure(message: str) -> None:
    observations = extract_symptoms(snapshot(logs=[LogEntry(message=message)]))
    assert observations.supporting_ids(Symptom.DATABASE_CONNECTION_FAILURE) == ("log-0001",)


@pytest.mark.parametrize("message", [
    "Database connection successful",
    "Connection refused while calling the payments API",
    "database connection failed: false",
    "No database connection failure detected",
])
def test_unrelated_or_negated_connections_are_not_database_failures(message: str) -> None:
    observations = extract_symptoms(snapshot(logs=[LogEntry(message=message)]))
    assert not observations.has(Symptom.DATABASE_CONNECTION_FAILURE)


@pytest.mark.parametrize("message", [
    "OOMKilled", "Out of memory: Killed process 123", "out-of-memory",
    "MemoryError", "cannot allocate memory", "OOM event detected",
])
def test_explicit_oom_log_indicators(message: str) -> None:
    observations = extract_symptoms(snapshot(logs=[LogEntry(message=message)]))
    assert observations.has(Symptom.OUT_OF_MEMORY)


@pytest.mark.parametrize("message", ["No OOM events detected", "OOM: false", "process exited with code 137"])
def test_negation_and_exit_code_alone_do_not_establish_oom(message: str) -> None:
    observations = extract_symptoms(snapshot(logs=[LogEntry(message=message)]))
    assert not observations.has(Symptom.OUT_OF_MEMORY)


def test_thresholds_apply_inclusively_and_can_be_configured() -> None:
    thresholds = DiagnosisThresholds(high_cpu_percent=90, high_ram_mib=512, slow_response_ms=800)
    observations = extract_symptoms(snapshot(
        cpu_usage_percent=90, ram_usage_mib=512, response_time_ms=800,
    ), thresholds=thresholds)
    assert observations.has(Symptom.HIGH_CPU)
    assert observations.has(Symptom.HIGH_RAM)
    assert observations.has(Symptom.SLOW_RESPONSE)
    lower = extract_symptoms(snapshot(
        cpu_usage_percent=89, ram_usage_mib=511, response_time_ms=799,
    ), thresholds=thresholds)
    assert lower.signals == ()


@pytest.mark.parametrize("changes", [
    {"high_cpu_percent": 101}, {"high_cpu_percent": 0}, {"high_cpu_percent": True},
    {"high_ram_mib": -1}, {"high_ram_mib": float("nan")}, {"high_ram_mib": "1024"},
    {"slow_response_ms": 0}, {"slow_response_ms": float("inf")},
])
def test_invalid_threshold_configuration(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        DiagnosisThresholds(**changes)


def test_blank_logs_are_disclosed_and_log_ids_preserve_positions() -> None:
    observations = extract_symptoms(snapshot(logs=[
        LogEntry(message="  "), LogEntry(message="  OOMKilled\n"),
    ]))
    assert observations.supporting_ids(Symptom.OUT_OF_MEMORY) == ("log-0002",)
    assert observations.evidence[-1].description.endswith(r'"  OOMKilled\n"')
    assert any("blank" in message for message in observations.limitations)
    assert any("partial or historical" in message for message in observations.limitations)


def test_repeated_signals_keep_all_distinct_evidence_references() -> None:
    observations = extract_symptoms(snapshot(logs=[
        LogEntry(message="database connection refused"),
        LogEntry(message="database connection failed"),
    ]))
    assert observations.supporting_ids(Symptom.DATABASE_CONNECTION_FAILURE) == ("log-0001", "log-0002")


def test_input_is_copied_and_mutated_models_are_revalidated() -> None:
    original = snapshot(cpu_usage_percent=10, logs=[LogEntry(message="ready")])
    before = original.model_dump_json()
    observations = extract_symptoms(original)
    assert observations.snapshot is not original
    assert observations.snapshot.logs is not original.logs
    assert original.model_dump_json() == before
    original.cpu_usage_percent = 101
    with pytest.raises(ValidationError):
        extract_symptoms(original)


def test_requires_snapshot_contract() -> None:
    with pytest.raises(TypeError, match="ServiceSnapshot"):
        extract_symptoms({"service_id": "fixture"})  # type: ignore[arg-type]
