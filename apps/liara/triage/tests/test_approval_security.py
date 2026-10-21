"""Concurrency, dependency failures, audit secrecy, and anti-bypass regressions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import socket
import subprocess
from threading import Barrier
from typing import Any, Iterator
from uuid import uuid4

import pytest

from conftest import ApprovalHarness, make_intent
from infrapilot_triage import ActionProposal
from infrapilot_triage.approval_store import ApprovalTransaction, InMemoryApprovalStore, StoreUnavailable
from infrapilot_triage.approvals import ApprovalRequest, ApprovalState, AuditEvent, AuditKind, DecisionReason
from infrapilot_triage.authorization import ApprovalGate
from infrapilot_triage.policy import ActionCategory, PolicyDecision


def test_concurrent_consumption_across_gate_instances_is_atomic(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    second_gate = ApprovalGate(identity=h.identity, policy=h.policy, store=h.store, clock=h.clock)
    barrier = Barrier(16)

    def attempt(index: int):
        barrier.wait(timeout=5)
        gate = h.gate if index % 2 else second_gate
        return gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)

    with ThreadPoolExecutor(max_workers=16) as pool:
        decisions = list(pool.map(attempt, range(16)))
    assert sum(decision.allowed for decision in decisions) == 1
    assert all(decision.reason == DecisionReason.CONSUMED for decision in decisions if not decision.allowed)
    assert h.store.get(request.request_id).state == ApprovalState.CONSUMED
    assert sum(event.kind == AuditKind.CONSUMED for event in h.store.events) == 1


def test_reentrant_identity_callbacks_cannot_double_consume(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness
    request = h.approved()
    original = h.identity.is_authorized
    nested = []

    def reentrant(actor, action, permission):
        if actor.subject == "approver":
            nested.append(h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id))
        return original(actor, action, permission)

    monkeypatch.setattr(h.identity, "is_authorized", reentrant)
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert result.allowed
    assert len(nested) == 1 and not nested[0].allowed
    assert sum(event.kind == AuditKind.CONSUMED for event in h.store.events) == 1


def test_every_required_audit_event_is_structured_and_linked(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    first = h.approved()
    assert h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=first.request_id).allowed
    assert not h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=first.request_id).allowed
    second = h.pending()
    h.gate.reject(second.request_id, authentication=h.approver)
    third = h.pending(ttl=timedelta(seconds=1))
    h.clock.advance(timedelta(seconds=1))
    h.gate.approve(third.request_id, authentication=h.approver)
    events = h.store.events
    assert {event.kind for event in events} == set(AuditKind)
    assert len({event.event_id for event in events}) == len(events)
    assert all(event.occurred_at.tzinfo is not None for event in events)
    assert all(event.request_id in (first.request_id, second.request_id, third.request_id) for event in events)
    assert all(event.fingerprint == first.action.fingerprint for event in events)
    assert all("parameters" not in asdict(event) for event in events)


def test_audit_never_records_context_proposal_parameters_or_exception_text(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness
    marker = "DO-NOT-RECORD-SYNTHETIC-CREDENTIAL"
    proposal = ActionProposal(
        action_id="display", title=marker, description=marker,
        risk_level="low", requires_approval=False,
    )
    h.gate.request_approval(make_intent(proposal=proposal), authentication=h.requester)
    h.gate.authorize(make_intent(), authentication=marker)
    h.gate.approve(marker, authentication=h.approver)
    h.gate.authorize(make_intent(parameters={"api_token": marker}), authentication=h.requester)

    def failed_authentication(_context: object) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(h.identity, "authenticate", failed_authentication)
    denied = h.gate.authorize(make_intent(), authentication=h.requester)
    assert marker not in repr(denied)
    assert marker not in json.dumps([asdict(event) for event in h.store.events], default=str)


def test_unrecognized_target_identifiers_do_not_enter_audit_payloads(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    marker = "ghp_" + "x" * 40  # Deliberately synthetic, not a credential.
    for authentication in (h.requester, None):
        intent = make_intent(service_id=marker)
        assert not h.gate.authorize(intent, authentication=authentication).allowed
        assert not h.gate.request_approval(intent, authentication=authentication).allowed
    assert marker not in json.dumps([asdict(event) for event in h.store.events], default=str)
    assert all(event.service_id is None for event in h.store.events)


class _UnavailableStore:
    def transaction(self):
        raise StoreUnavailable("Synthetic store outage")


def test_storage_unavailable_denies_even_inspections(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    gate = ApprovalGate(identity=h.identity, policy=h.policy, store=_UnavailableStore(), clock=h.clock)
    result = gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester)
    assert not result.allowed and not result.audit_recorded
    assert result.reason == DecisionReason.STORAGE_UNAVAILABLE


class _FailAuditTransaction:
    def __init__(self, transaction: ApprovalTransaction) -> None:
        self.transaction = transaction

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self.transaction.get(request_id)

    def put(self, request: ApprovalRequest) -> None:
        self.transaction.put(request)

    def record(self, event: AuditEvent) -> None:
        raise StoreUnavailable("Synthetic audit outage")


class _AuditOutageStore:
    def __init__(self, delegate: InMemoryApprovalStore) -> None:
        self.delegate = delegate

    @contextmanager
    def transaction(self) -> Iterator[ApprovalTransaction]:
        with self.delegate.transaction() as transaction:
            yield _FailAuditTransaction(transaction)


def test_audit_failure_rolls_back_consumption_and_never_allows(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    before = h.store.events
    gate = ApprovalGate(identity=h.identity, policy=h.policy, store=_AuditOutageStore(h.store), clock=h.clock)
    result = gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and not result.audit_recorded
    assert h.store.get(request.request_id).state == ApprovalState.APPROVED
    assert h.store.events == before
    assert h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id).allowed


def test_unavailable_or_invalid_policy_fails_closed(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness

    def unavailable(_intent):
        raise RuntimeError("Synthetic policy outage")

    monkeypatch.setattr(h.policy, "classify", unavailable)
    assert not h.gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester).allowed
    monkeypatch.setattr(h.policy, "classify", lambda intent: None)
    assert not h.gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester).allowed


def test_policy_is_rechecked_after_identity_calls(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness
    request = h.approved()
    original = h.policy.classify
    calls = 0

    def changed_policy(intent):
        nonlocal calls
        calls += 1
        return original(intent) if calls == 1 else PolicyDecision(False, ActionCategory.DENIED, True, "unsupported_action")

    monkeypatch.setattr(h.policy, "classify", changed_policy)
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed
    assert calls == 2
    assert h.store.get(request.request_id).state == ApprovalState.APPROVED


@pytest.mark.parametrize("malformed", ["truthy-allowed", "missing-approval", "sensitive-marked-safe", "sensitive-disguised-readonly"])
def test_malformed_policy_information_cannot_allow(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch, malformed: str) -> None:
    h = approval_harness
    from dataclasses import replace
    ordinary = h.policy.classify(make_intent())
    if malformed == "truthy-allowed":
        changed = replace(ordinary, allowed="yes")
    elif malformed == "missing-approval":
        changed = replace(ordinary, requires_approval=None)
    elif malformed == "sensitive-disguised-readonly":
        changed = replace(ordinary, category=ActionCategory.READ_ONLY, requires_approval=False)
    else:
        changed = replace(ordinary, requires_approval=False)
    monkeypatch.setattr(h.policy, "classify", lambda intent: changed)
    result = h.gate.authorize(make_intent(), authentication=h.requester)
    assert not result.allowed and result.reason == DecisionReason.POLICY_UNAVAILABLE


def test_unverified_identity_dictionary_from_boundary_is_denied(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness
    monkeypatch.setattr(h.identity, "authenticate", lambda context: {"subject": "approver", "verified": True})
    assert not h.gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester).allowed


def test_missing_or_naive_clock_denies(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    for clock in (lambda: None, lambda: datetime(2026, 1, 1)):
        gate = ApprovalGate(identity=h.identity, policy=h.policy, store=h.store, clock=clock)
        result = gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester)
        assert not result.allowed and result.reason == DecisionReason.CLOCK_UNAVAILABLE


def test_clock_rollback_before_creation_denies(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    h.clock.advance(timedelta(seconds=-1))
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.CLOCK_UNAVAILABLE


def test_restart_loses_approvals_and_never_treats_ids_as_authority(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    restarted = ApprovalGate(identity=h.identity, policy=h.policy, store=InMemoryApprovalStore(), clock=h.clock)
    result = restarted.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.REQUEST_NOT_FOUND


def test_fabricated_identifiers_and_action_type_substitution_are_denied(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    assert not h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=str(uuid4())).allowed
    request = h.approved()
    changed = make_intent(action_type="change_resources", parameters={"ram_mib": 512})
    result = h.gate.authorize(changed, authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.ACTION_MISMATCH


def test_gate_has_no_network_or_process_execution(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Authorization attempted network or process execution")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    request = h.approved()
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert result.allowed and result.reason == DecisionReason.AUTHORIZED


def test_retained_transaction_handles_cannot_modify_committed_state(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending()
    with h.store.transaction() as transaction:
        retained = transaction
    from dataclasses import replace
    retained.put(replace(request, state=ApprovalState.CONSUMED))
    assert h.store.get(request.request_id).state == ApprovalState.PENDING
