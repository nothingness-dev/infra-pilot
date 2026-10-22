"""HTTP scenarios use the actual engine; fault injection is limited to errors."""

import json

from fastapi.testclient import TestClient
import pytest

from infrapilot_triage import engine
from infrapilot_triage.api import create_app
from infrapilot_triage.schemas import DiagnosisReport, ServiceSnapshot


@pytest.fixture
def client():
    with TestClient(create_app()) as value:
        yield value


def snapshot(**changes):
    return {"service_id": "MOCK-service", "status": "unknown", "data_source": "mock", **changes}


@pytest.mark.parametrize("payload,top", [
    (snapshot(status="unhealthy", http_status=500, logs=[
        {"message": "PostgreSQL connection refused", "level": "error"},
    ]), "database_connection_failure"),
    (snapshot(cpu_usage_percent=97, response_time_ms=2400), "cpu_saturation"),
    (snapshot(status="healthy"), None),
    (snapshot(http_status=500), "http_server_error"),
])
def test_diagnosis_matches_actual_engine(client, payload, top):
    response = client.post("/internal/triage/diagnose", json=payload)
    assert response.status_code == 200
    report = DiagnosisReport.model_validate(response.json())
    assert report.model_dump(mode="json") == engine.diagnose(ServiceSnapshot.model_validate(payload)).model_dump(mode="json")
    assert (report.hypotheses[0].hypothesis_id if report.hypotheses else None) == top
    assert all(action.status == "not_executed" for action in report.actions)
    evidence_ids = {item.evidence_id for item in report.evidence}
    assert all(set(item.evidence_ids) <= evidence_ids for item in report.hypotheses)


@pytest.mark.parametrize("source", ["real", "mock"])
def test_source_label_is_preserved_not_verified(client, source):
    response = client.post("/internal/triage/diagnose", json=snapshot(data_source=source))
    assert response.status_code == 200
    assert response.json()["data_source"] == source


def test_missing_observations_are_not_zero_or_empty(client):
    missing = client.post("/internal/triage/diagnose", json=snapshot(status="healthy")).json()
    measured = client.post("/internal/triage/diagnose", json=snapshot(
        status="healthy", cpu_usage_percent=0, ram_usage_mib=0, response_time_ms=0, logs=[],
    )).json()
    assert len(missing["missing_information"]) > len(measured["missing_information"])
    assert {"cpu-usage", "ram-usage", "response-time"}.isdisjoint(item["evidence_id"] for item in missing["evidence"])
    assert {"cpu-usage", "ram-usage", "response-time"} <= {item["evidence_id"] for item in measured["evidence"]}
    assert missing["limitations"]
    assert not missing["hypotheses"]


def test_ranking_and_serialization_are_stable(client):
    payload = snapshot(status="healthy", http_status=500, cpu_usage_percent=99, response_time_ms=3000,
                       logs=[{"message": "database connection refused"}])
    first = client.post("/internal/triage/diagnose", json=payload)
    second = client.post("/internal/triage/diagnose", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    body = first.json()
    assert body["hypotheses"][0]["hypothesis_id"] == "database_connection_failure"
    assert any("conflict" in value.lower() for value in body["limitations"])
    assert [item["confidence"] for item in body["hypotheses"]] == sorted(
        [item["confidence"] for item in body["hypotheses"]], reverse=True,
    )
    assert first.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("changes", [
    {"cpu_usage_percent": -1}, {"cpu_usage_percent": 101}, {"cpu_usage_percent": "secret-value"},
    {"ram_usage_mib": -1}, {"logs": "secret-value"}, {"http_status": 999},
    {"http_status": True}, {"status": "secret-value"}, {"data_source": "fabricated"},
    {"user_id": "secret-value", "role": "admin"}, {"timestamp": "secret-value"},
])
def test_validation_errors_never_echo_inputs(client, changes):
    response = client.post("/internal/triage/diagnose", json=snapshot(**changes))
    assert response.status_code == 422
    assert response.json() == {"error": {
        "code": "validation_error", "message": "Request does not match the required schema.",
    }}
    assert "secret-value" not in response.text


@pytest.mark.parametrize("body", ['{"password":"DO_NOT_LEAK"', 'null', '[]'])
def test_malformed_or_wrong_shape_json_is_safe(client, body):
    response = client.post("/internal/triage/diagnose", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "DO_NOT_LEAK" not in response.text


def test_internal_exception_has_no_secret_or_traceback(client, monkeypatch, caplog):
    def broken(_snapshot):
        raise RuntimeError("password=DO_NOT_LEAK")
    monkeypatch.setattr(engine, "diagnose", broken)
    response = client.post("/internal/triage/diagnose", json=snapshot())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "DO_NOT_LEAK" not in response.text + caplog.text
    assert "Traceback" not in response.text + caplog.text


def test_invalid_internal_response_has_safe_error(client, monkeypatch, caplog):
    monkeypatch.setattr(engine, "diagnose", lambda _snapshot: {"password": "DO_NOT_LEAK"})
    response = client.post("/internal/triage/diagnose", json=snapshot())
    assert response.status_code == 500
    assert "DO_NOT_LEAK" not in response.text + caplog.text
    assert response.json()["error"]["code"] == "internal_error"


def test_health_is_process_only_and_does_not_diagnose(client, monkeypatch):
    def forbidden(_snapshot):
        pytest.fail("Health must not call the diagnosis engine")
    monkeypatch.setattr(engine, "diagnose", forbidden)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "component": "triage_api", "scope": "process_only"}
    assert response.headers["cache-control"] == "no-store"


def test_openapi_defines_existing_contracts(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    assert {"ServiceSnapshot", "DiagnosisReport", "ActionIntent", "GateDecision", "ErrorResponse"} <= schemas.keys()
    assert schemas["ServiceSnapshot"]["additionalProperties"] is False
    assert client.get("/docs").status_code == 404


@pytest.mark.parametrize("method,path,code", [("get", "/missing", 404), ("post", "/health", 405)])
def test_http_errors_are_structured(client, method, path, code):
    response = getattr(client, method)(path)
    assert response.status_code == code
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("message,secret", [
    ("PostgreSQL connection refused password=DO_NOT_LEAK", "DO_NOT_LEAK"),
    ('PostgreSQL connection refused {"password": "DO_NOT_LEAK"}', "DO_NOT_LEAK"),
    ("database connection refused postgres://user:DO_NOT_LEAK@db:5432/app", "DO_NOT_LEAK"),
    ("database connection refused Authorization: Bearer DO_NOT_LEAK", "DO_NOT_LEAK"),
    ('database connection refused {"Authorization": "Bearer DO_NOT_LEAK"}', "DO_NOT_LEAK"),
    ("database connection refused api_key='DO_NOT_LEAK'", "DO_NOT_LEAK"),
    ("database connection refused -----BEGIN PRIVATE KEY-----\nDO_NOT_LEAK\n-----END PRIVATE KEY-----", "DO_NOT_LEAK"),
    ("database connection refused ghp_" + "A" * 36, "ghp_" + "A" * 36),
])
def test_recognizable_credentials_are_redacted_before_diagnosis(client, message, secret):
    payload = snapshot(http_status=500, logs=[{"message": message, "level": "error"}])
    original = json.dumps(payload)
    response = client.post("/internal/triage/diagnose", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert secret not in response.text
    assert "[REDACTED" in response.text
    assert report["hypotheses"][0]["hypothesis_id"] == "database_connection_failure"
    assert any("redacted" in item for item in report["limitations"])
    assert json.dumps(payload) == original
