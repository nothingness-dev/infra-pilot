"""Fixture-based triage checks: exact sanitized Provider PR #12 blobs, no provider import."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from infrapilot_triage.api import create_app
from infrapilot_triage.collection_context import (
    ContextCompatibilityError, context_digest, diagnose_contextual_request,
    preview_mock_contextual_diagnosis, validate_contextual_request, validate_provider_context,
)
from infrapilot_triage.engine import diagnose
from infrapilot_triage.schemas import DiagnosisReport, ServiceSnapshot


FIXTURES = Path(__file__).parent / "fixtures/provider_context_v02"
SCENARIOS = ("empty", "exported", "not_collected", "partial_failure", "partial_logs", "unavailable", "withheld")


def payload(name: str = "partial_failure") -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def proposed_request(name: str = "partial_failure") -> dict:
    value = payload(name)
    context = value["collection_context"]
    value["correlation"] = {
        "service_id": value["snapshot"]["service_id"], "service_binding_ref": "MOCK-binding-1",
        "collection_ref": f"MOCK-collection-{name}", "snapshot_digest": context["snapshot_digest"],
        "collection_context_digest": context_digest(context),
    }
    return value


def test_fixture_bytes_match_verified_provider_revision() -> None:
    manifest = json.loads((FIXTURES / "SOURCE.json").read_text(encoding="utf-8"))
    assert manifest["revision"] == "66655e6f21b70717948122bc521b72f54b9d91a8"
    assert manifest["pull_request"] == 12
    assert set(manifest["fixtures"]) == {f"{name}.json" for name in SCENARIOS}
    for name, source in manifest["fixtures"].items():
        assert source["source_path"] == f"provider/examples/fixtures/context_v02/{name}"
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == source["sha256"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_original_context_values_survive_validation_and_preview(name: str) -> None:
    original = payload(name)
    envelope = validate_provider_context(original)
    assert envelope.model_dump(mode="json") == original
    assert envelope.snapshot.status.value == "unknown"
    assert envelope.snapshot.cpu_usage_percent is None and envelope.snapshot.ram_usage_mib is None
    assert envelope.snapshot.http_status is None and envelope.snapshot.response_time_ms is None
    result = preview_mock_contextual_diagnosis(proposed_request(name), mock=True)
    assert result.collection_context.model_dump(mode="json") == original["collection_context"]
    assert result.diagnosis_report.model_dump() == diagnose(envelope.snapshot).model_dump()
    assert result.integration_status == "mock_preview_only"
    assert not result.trusted_mapping_verified and not result.provenance_verified
    assert not result.authorization_granted and not result.execution_performed
    assert all(item.status == "not_executed" for item in result.diagnosis_report.actions)


@pytest.mark.parametrize("name,state,received,exported,withheld", [
    ("empty", "empty", 0, 0, 0), ("exported", "exported", 1, 1, 0),
    ("not_collected", "not_collected", None, 0, 0),
    ("unavailable", "unavailable", None, 0, 0), ("withheld", "withheld", 1, 0, 1),
    ("partial_logs", "partial", 2, 1, 1), ("partial_failure", "collection_failed", None, 0, 0),
])
def test_log_export_dispositions_and_withheld_counts(name, state, received, exported, withheld) -> None:
    envelope = validate_provider_context(payload(name))
    assert envelope.collection_context.log_export.model_dump() == {
        "state": state, "received": received, "exported": exported, "withheld": withheld,
    }
    assert (envelope.snapshot.logs == []) == (state == "empty")
    if state in ("withheld", "unavailable", "not_collected", "collection_failed"):
        assert envelope.snapshot.logs is None


def test_distinct_failures_remain_structured_under_capabilities() -> None:
    context = validate_provider_context(payload()).collection_context
    errors = context.collection_errors
    assert [(item.capability, item.availability, item.error_code, item.http_status, item.retryable) for item in errors] == [
        ("logs", "permission_denied", "AUTHENTICATION_ERROR", 403, False),
        ("metrics", "failed", "RATE_LIMITED", 429, True),
    ]
    assert "collection_errors" not in context.model_dump(mode="json")
    assert context.collection_errors == context.collection_errors
    assert context.collection_started_at == "2026-10-22T00:00:00+00:00"


@pytest.mark.parametrize("mutation", [
    lambda p: p["collection_context"].update(service_id="another-service"),
    lambda p: p["collection_context"].update(data_source="real"),
    lambda p: p["snapshot"].update(service_id="another-service"),
    lambda p: p["snapshot"].update(logs=[]),
    lambda p: p["snapshot"].update(cpu_usage_percent=0),
    lambda p: p["collection_context"]["log_export"].update(withheld=0, received=0, state="empty"),
    lambda p: p["collection_context"]["capabilities"].pop(),
    lambda p: p["collection_context"]["capabilities"][0].update(capability="logs"),
    lambda p: p["collection_context"]["capabilities"][0].update(http_status=500),
    lambda p: p["collection_context"].update(collection_finished_at="2026-10-21T00:00:00Z"),
    lambda p: p["collection_context"].update(collection_started_at="2026-10-22T00:00:00"),
    lambda p: p["collection_context"]["capabilities"][0].update(collected_at="2027-01-01T00:00:00Z"),
    lambda p: p["collection_context"]["log_export"].update(exported=True),
    lambda p: p["collection_context"].update(collection_errors=[]),
])
def test_mismatched_or_inconsistent_context_is_rejected(mutation) -> None:
    value = payload("withheld")
    mutation(value)
    with pytest.raises(ContextCompatibilityError):
        validate_provider_context(value)


@pytest.mark.parametrize("version", ["0.2", "provider-collection-context/0.1", "future-version"])
def test_wrong_context_version_has_safe_rejection(version: str) -> None:
    value = payload()
    value["collection_context"]["contract_version"] = version
    with pytest.raises(ContextCompatibilityError) as error:
        validate_provider_context(value)
    assert error.value.code == "unsupported_context_version"


@pytest.mark.parametrize("mutation", [
    lambda p: p["correlation"].update(service_id="another-service"),
    lambda p: p["correlation"].update(collection_context_digest="sha256:" + "0" * 64),
    lambda p: p["correlation"].update(snapshot_digest="sha256:" + "0" * 64),
    lambda p: p["correlation"].update(trusted=True),
    lambda p: p.update(user_id="admin", verified=True),
])
def test_proposed_correlation_claims_cannot_override_consistency(mutation) -> None:
    value = proposed_request()
    mutation(value)
    with pytest.raises(ContextCompatibilityError):
        validate_contextual_request(value)


@pytest.mark.parametrize("value", [None, "claimed-mapping", {"trusted": True}, {"user_id": "admin"}])
def test_missing_or_caller_claimed_mapping_always_fails_closed(value) -> None:
    with pytest.raises(ContextCompatibilityError) as error:
        diagnose_contextual_request(value)
    assert error.value.code == "untrusted_service_mapping"


def test_recomputed_hashes_are_not_backend_identity_proof() -> None:
    value = proposed_request()
    value["snapshot"]["service_id"] = "forged-service"
    value["collection_context"]["service_id"] = "forged-service"
    value["collection_context"]["snapshot_digest"] = context_digest(value["snapshot"])
    value["correlation"].update(service_id="forged-service", snapshot_digest=value["collection_context"]["snapshot_digest"],
                                collection_context_digest=context_digest(value["collection_context"]))
    validate_contextual_request(value)  # Consistent shape is possible for a forged claim.
    with pytest.raises(ContextCompatibilityError, match="untrusted_service_mapping"):
        diagnose_contextual_request(value)


@pytest.mark.parametrize("mock", [False, None, 1, "true"])
def test_preview_requires_explicit_mock_opt_in(mock) -> None:
    with pytest.raises(ContextCompatibilityError, match="mock_opt_in_required"):
        preview_mock_contextual_diagnosis(proposed_request(), mock=mock)


def test_real_label_never_enables_preview_or_production() -> None:
    value = proposed_request()
    value["snapshot"]["data_source"] = value["collection_context"]["data_source"] = "real"
    value["collection_context"]["snapshot_digest"] = context_digest(value["snapshot"])
    value["correlation"].update(snapshot_digest=value["collection_context"]["snapshot_digest"],
                                collection_context_digest=context_digest(value["collection_context"]))
    with pytest.raises(ContextCompatibilityError, match="real_preview_disabled"):
        preview_mock_contextual_diagnosis(value, mock=True)
    with pytest.raises(ContextCompatibilityError, match="untrusted_service_mapping"):
        diagnose_contextual_request(value)


@pytest.mark.parametrize("target", ["error_code", "raw_response", "limitations"])
def test_raw_errors_and_unknown_limitation_text_are_not_exported(target: str, caplog) -> None:
    value = payload()
    if target == "limitations":
        value["collection_context"]["limitations"].append("password=DO_NOT_EXPORT")
    else:
        value["collection_context"]["capabilities"][2][target] = "password=DO_NOT_EXPORT"
    with pytest.raises(ContextCompatibilityError) as error:
        validate_provider_context(value)
    assert "DO_NOT_EXPORT" not in str(error.value) + repr(error.value) + caplog.text


def test_recognizable_log_credentials_require_sanitizing_before_binding() -> None:
    value = payload("exported")
    value["snapshot"]["logs"][0]["message"] = "password=DO_NOT_EXPORT"
    value["collection_context"]["snapshot_digest"] = context_digest(value["snapshot"])
    with pytest.raises(ContextCompatibilityError) as error:
        validate_provider_context(value)
    assert "DO_NOT_EXPORT" not in str(error.value)


def test_mock_preview_cannot_approve_unreviewed_log_bodies() -> None:
    value = proposed_request("exported")
    value["snapshot"]["logs"][0]["message"] = "custom credential DO_NOT_EXPORT"
    value["collection_context"]["snapshot_digest"] = context_digest(value["snapshot"])
    value["correlation"].update(snapshot_digest=value["collection_context"]["snapshot_digest"],
                                collection_context_digest=context_digest(value["collection_context"]))
    with pytest.raises(ContextCompatibilityError, match="unreviewed_mock_logs") as error:
        preview_mock_contextual_diagnosis(value, mock=True)
    assert "DO_NOT_EXPORT" not in str(error.value)


def test_exact_draft_request_response_examples_match_actual_preview() -> None:
    examples = Path(__file__).resolve().parents[1] / "examples/context_v02"
    request = json.loads((examples / "mock_partial_failure.request.json").read_text(encoding="utf-8"))
    response = json.loads((examples / "mock_partial_failure.response.json").read_text(encoding="utf-8"))
    assert request["snapshot"] == payload()["snapshot"]
    assert request["collection_context"] == payload()["collection_context"]
    assert preview_mock_contextual_diagnosis(request, mock=True).model_dump(mode="json") == response


@pytest.mark.parametrize("name", SCENARIOS)
def test_old_endpoint_and_report_behavior_stay_unchanged(name: str) -> None:
    value = payload(name)
    original = deepcopy(value)
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json=value["snapshot"])
        assert client.post("/internal/triage/diagnose", json=value).status_code == 422
        assert client.post("/internal/triage/diagnose-contextual", json=proposed_request(name)).status_code == 404
        assert client.post("/internal/triage/authorize", json={"intent": {
            "service_id": "MOCK-service", "action_type": "restart_service",
        }}).status_code == 503
    assert response.status_code == 200
    report = DiagnosisReport.model_validate(response.json())
    assert report.model_dump() == diagnose(ServiceSnapshot.model_validate(value["snapshot"])).model_dump()
    assert value == original


@pytest.mark.parametrize("value", [None, [], {}, {"snapshot": {}}, {"collection_context": {}}])
def test_invalid_or_incomplete_envelope_has_safe_error(value) -> None:
    with pytest.raises(ContextCompatibilityError):
        validate_provider_context(value)
