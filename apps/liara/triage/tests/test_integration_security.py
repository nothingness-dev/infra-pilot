"""API plus real gate: atomic replay resistance and trusted dependency outages."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import json
from threading import Barrier
from typing import Iterator

from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from conftest import ApprovalHarness, make_intent
from infrapilot_triage.api import create_app
from infrapilot_triage.approval_integration import ApprovalIntegration
from infrapilot_triage.approval_store import ApprovalTransaction, InMemoryApprovalStore, StoreUnavailable
from infrapilot_triage.approvals import ApprovalState, AuditKind, GateDecision
from infrapilot_triage.authorization import ApprovalGate


def api_for(harness: ApprovalHarness, gate: ApprovalGate | None = None):
    return create_app(
        approval_integration=ApprovalIntegration(policy=harness.policy, gate=gate or harness.gate),
        authentication_resolver=lambda _request: harness.requester,
    )


def test_parallel_http_replay_across_apps_shares_atomic_approval(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    second_gate = ApprovalGate(identity=h.identity, policy=h.policy, store=h.store, clock=h.clock)
    barrier = Barrier(8)
    clients = [TestClient(api_for(h)), TestClient(api_for(h, second_gate))]
    body = {"intent": make_intent().model_dump(mode="json"), "approval_request_id": request.request_id}

    def consume(index: int) -> tuple[int, GateDecision]:
        barrier.wait(timeout=10)
        response = clients[index % 2].post("/internal/triage/authorize", json=body)
        return response.status_code, TypeAdapter(GateDecision).validate_python(response.json())

    with clients[0], clients[1], ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(consume, range(8)))
    assert sum(status == 200 and decision.allowed for status, decision in decisions) == 1
    assert sum(status == 403 and not decision.allowed for status, decision in decisions) == 7
    assert h.store.get(request.request_id).state == ApprovalState.CONSUMED
    assert sum(event.kind == AuditKind.CONSUMED for event in h.store.events) == 1
    assert all(decision.audit_recorded for _status, decision in decisions)


@pytest.mark.parametrize("change", [
    {"service_id": "service-B"}, {"parameters": {"grace_period_seconds": 1}},
    {"action_type": "change_resources", "parameters": {"ram_mib": 512}},
])
def test_action_substitution_does_not_consume_approval(approval_harness: ApprovalHarness, change: dict) -> None:
    h = approval_harness
    request = h.approved()
    with TestClient(api_for(h)) as client:
        response = client.post("/internal/triage/authorize", json={
            "intent": make_intent(**change).model_dump(mode="json"), "approval_request_id": request.request_id,
        })
    assert response.status_code == 403 and response.json()["reason"] == "action_mismatch"
    assert not response.json()["allowed"]
    assert h.store.get(request.request_id).state == ApprovalState.APPROVED


def test_expiry_at_exact_deadline_is_denied_over_http(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    h.clock.advance(timedelta(minutes=5))
    with TestClient(api_for(h)) as client:
        response = client.post("/internal/triage/authorize", json={
            "intent": make_intent().model_dump(mode="json"), "approval_request_id": request.request_id,
        })
    assert response.status_code == 403 and response.json()["reason"] == "approval_expired"
    assert h.store.get(request.request_id).state == ApprovalState.EXPIRED


@pytest.mark.parametrize("method", ["authenticate", "is_authorized"])
def test_identity_and_acl_outages_are_safe_http_denials(
    approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch, method: str, caplog,
) -> None:
    h = approval_harness
    def unavailable(*_args):
        raise RuntimeError("password=QA_MUST_NOT_LEAK")
    monkeypatch.setattr(h.identity, method, unavailable)
    with TestClient(api_for(h)) as client:
        response = client.post("/internal/triage/authorize", json={"intent": make_intent().model_dump(mode="json")})
    assert response.status_code == 503
    assert response.json()["allowed"] is False
    assert "QA_MUST_NOT_LEAK" not in response.text + caplog.text


class _AuditFailure:
    def __init__(self, transaction: ApprovalTransaction) -> None:
        self.get, self.put = transaction.get, transaction.put

    def record(self, _event) -> None:
        raise StoreUnavailable("password=QA_MUST_NOT_LEAK")


class _OutageStore:
    def __init__(self, store: InMemoryApprovalStore, *, fail_commit: bool) -> None:
        self.store, self.fail_commit = store, fail_commit

    @contextmanager
    def transaction(self) -> Iterator[ApprovalTransaction]:
        with self.store.transaction() as transaction:
            yield transaction if self.fail_commit else _AuditFailure(transaction)
            if self.fail_commit:
                raise StoreUnavailable("password=QA_MUST_NOT_LEAK")


@pytest.mark.parametrize("fail_commit", [False, True], ids=["audit-append", "transaction-commit"])
def test_persistence_failure_rolls_back_http_consumption(
    approval_harness: ApprovalHarness, fail_commit: bool, caplog,
) -> None:
    h = approval_harness
    request = h.approved()
    previous_events = h.store.events
    gate = ApprovalGate(identity=h.identity, policy=h.policy,
                        store=_OutageStore(h.store, fail_commit=fail_commit), clock=h.clock)
    with TestClient(api_for(h, gate)) as client:
        response = client.post("/internal/triage/authorize", json={
            "intent": make_intent().model_dump(mode="json"), "approval_request_id": request.request_id,
        })
    assert response.status_code == 503
    assert response.json()["allowed"] is False and response.json()["audit_recorded"] is False
    assert response.json()["reason"] == "storage_or_audit_unavailable"
    assert h.store.get(request.request_id).state == ApprovalState.APPROVED
    assert h.store.events == previous_events
    assert "QA_MUST_NOT_LEAK" not in response.text + caplog.text


def test_untrusted_body_cannot_install_dependencies_or_change_default_app(approval_harness: ApprovalHarness) -> None:
    with TestClient(create_app()) as default, TestClient(api_for(approval_harness)) as configured:
        body = {"intent": make_intent(action_type="inspect_service").model_dump(mode="json")}
        assert configured.post("/internal/triage/authorize", json=body).status_code == 200
        forged = default.post("/internal/triage/authorize", json={
            **body, "identity": {"verified": True}, "policy": {"allowed": True},
        }, headers={"X-User-ID": "requester", "X-Roles": "admin"})
        assert forged.status_code == 503
        assert default.post("/internal/triage/authorize", json=body).status_code == 503


def test_unknown_recommendation_identifier_is_not_a_policy_operation(approval_harness: ApprovalHarness) -> None:
    with TestClient(api_for(approval_harness)) as client:
        response = client.post("/internal/triage/authorize", json={"intent":
            make_intent(action_type="review_database_configuration").model_dump(mode="json")})
    assert response.status_code == 403
    assert response.json()["reason"] == "invalid_or_unknown_action"
    assert response.json()["allowed"] is False


def test_json_escaped_credential_is_redacted_in_full() -> None:
    message = "PostgreSQL connection refused " + json.dumps({"password": 'prefix"QA_MUST_NOT_LEAK'})
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json={
            "service_id": "QA-synthetic-service", "status": "unknown", "data_source": "mock",
            "logs": [{"message": message}],
        })
    assert response.status_code == 200
    assert "QA_MUST_NOT_LEAK" not in response.text
    assert "[REDACTED]" in response.text
    assert response.json()["hypotheses"][0]["hypothesis_id"] == "database_connection_failure"
