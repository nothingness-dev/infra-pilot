"""Checked-in MOCK fixtures must agree with actual engine/gate serialization."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from infrapilot_triage.api import create_app
from infrapilot_triage.api_contracts import AuthorizationRequest
from infrapilot_triage.approvals import ApprovalState, DecisionReason, GateDecision
from infrapilot_triage.example_payloads import build_mock_examples
from infrapilot_triage.policy import ActionIntent, ActionPolicy


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["mock_db_http500", "mock_cpu_latency", "mock_healthy_incomplete"])
def test_checked_in_diagnosis_fixtures_are_actual_api_outputs(name):
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json=load(f"{name}.request.json"))
    assert response.status_code == 200
    assert response.json() == load(f"{name}.response.json")
    assert response.json()["data_source"] == "mock"
    assert all(action["status"] == "not_executed" for action in response.json()["actions"])


@pytest.mark.parametrize("mock", [False, None, 1, "true"])
def test_fixture_generation_requires_explicit_mock_mode(mock):
    with pytest.raises(ValueError, match="MOCK"):
        build_mock_examples(mock=mock)


def test_offline_generator_uses_real_pending_and_denied_gate_decisions():
    examples = build_mock_examples(mock=True)
    adapter = TypeAdapter(GateDecision)
    pending = adapter.validate_python(examples["mock_sensitive_pending.response.json"])
    denied = adapter.validate_python(examples["mock_authorization_denied.response.json"])
    assert pending.reason == DecisionReason.PENDING and pending.request.state == ApprovalState.PENDING
    assert pending.audit_recorded and not pending.allowed and pending.authorization_id is None
    assert denied.reason == DecisionReason.UNAUTHENTICATED and not denied.allowed
    assert denied.request is None and denied.authorization_id is None
    assert len(examples) == 10


def test_checked_in_pending_approval_is_bound_to_canonical_action():
    intent = ActionIntent.model_validate(load("mock_sensitive_pending.request.json"))
    decision = TypeAdapter(GateDecision).validate_python(load("mock_sensitive_pending.response.json"))
    canonical = ActionPolicy().classify(intent).action
    assert decision.request.action == canonical
    assert decision.request.state == ApprovalState.PENDING
    assert decision.request.requested_by.subject == "MOCK-requester"
    assert not decision.allowed and decision.reason == DecisionReason.PENDING


def test_checked_in_denial_has_no_approval_or_authorization():
    request = AuthorizationRequest.model_validate(load("mock_authorization_denied.request.json"))
    decision = TypeAdapter(GateDecision).validate_python(load("mock_authorization_denied.response.json"))
    assert request.intent.service_id == "MOCK-service"
    assert decision.reason == DecisionReason.UNAUTHENTICATED
    assert not decision.allowed and decision.authorization_id is None and decision.request is None
