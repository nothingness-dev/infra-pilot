"""Real approval lifecycle tests using a trusted fixture identity boundary."""

from dataclasses import FrozenInstanceError
from datetime import timedelta
from uuid import UUID

import pytest

from conftest import ApprovalHarness, make_intent
from infrapilot_triage.approvals import ApprovalState, AuditKind, DecisionReason


def test_request_is_pending_and_never_grants_authorization(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending()
    assert str(UUID(request.request_id)) == request.request_id
    assert request.requested_by.subject == "requester"
    assert request.approved_by is None
    assert request.expires_at - request.created_at == timedelta(minutes=5)
    assert request.action.parameters == {"grace_period_seconds": 30}
    assert h.store.get(request.request_id) == request
    denied = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not denied.allowed and denied.reason == DecisionReason.APPROVAL_REQUIRED


def test_sensitive_action_without_approval(approval_harness: ApprovalHarness) -> None:
    result = approval_harness.gate.authorize(make_intent(), authentication=approval_harness.requester)
    assert not result.allowed and result.reason == DecisionReason.APPROVAL_REQUIRED


def test_explicit_approval_and_valid_single_consumption(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    assert request.approved_by.subject == "approver"
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert result.allowed and result.reason == DecisionReason.AUTHORIZED
    assert result.authorization_id is not None
    assert result.action == request.action
    assert result.request.state == ApprovalState.CONSUMED
    assert result.request.consumed_by.subject == "requester"
    assert h.store.get(request.request_id).state == ApprovalState.CONSUMED


def test_rejected_approval_is_terminal(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending()
    rejected = h.gate.reject(request.request_id, authentication=h.approver)
    assert not rejected.allowed and rejected.request.state == ApprovalState.REJECTED
    assert rejected.request.rejected_by.subject == "approver"
    assert not h.gate.approve(request.request_id, authentication=h.approver).allowed
    denied = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not denied.allowed and denied.reason == DecisionReason.REJECTED


def test_approved_request_can_be_revoked_before_consumption(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    result = h.gate.reject(request.request_id, authentication=h.approver)
    assert result.request.state == ApprovalState.REJECTED
    assert not h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id).allowed


@pytest.mark.parametrize("already_approved", [False, True])
def test_expiry_at_exact_deadline_is_terminal(approval_harness: ApprovalHarness, already_approved: bool) -> None:
    h = approval_harness
    request = h.approved(ttl=timedelta(seconds=10)) if already_approved else h.pending(ttl=timedelta(seconds=10))
    h.clock.advance(timedelta(seconds=10))
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.EXPIRED
    assert h.store.get(request.request_id).state == ApprovalState.EXPIRED
    assert not h.gate.approve(request.request_id, authentication=h.approver).allowed
    assert len([event for event in h.store.events if event.kind == AuditKind.EXPIRED]) == 1


def test_cannot_grant_an_already_expired_request(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending(ttl=timedelta(seconds=1))
    h.clock.advance(timedelta(seconds=2))
    decision = h.gate.approve(request.request_id, authentication=h.approver)
    assert not decision.allowed and decision.reason == DecisionReason.EXPIRED


def test_replay_and_reapproval_of_consumed_request_are_denied(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    assert h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id).allowed
    replay = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not replay.allowed and replay.reason == DecisionReason.CONSUMED
    assert not h.gate.approve(request.request_id, authentication=h.approver).allowed
    assert not h.gate.reject(request.request_id, authentication=h.approver).allowed
    assert len([event for event in h.store.events if event.kind == AuditKind.CONSUMED]) == 1


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1), timedelta(minutes=16), "forever"])
def test_expiration_is_bounded(approval_harness: ApprovalHarness, ttl: object) -> None:
    result = approval_harness.gate.request_approval(make_intent(), authentication=approval_harness.requester, ttl=ttl)
    assert not result.allowed and result.reason == DecisionReason.INVALID_EXPIRATION
    assert result.request is None


def test_approval_records_are_immutable_and_ids_unique(approval_harness: ApprovalHarness) -> None:
    first = approval_harness.pending()
    second = approval_harness.pending()
    assert first.request_id != second.request_id
    with pytest.raises(FrozenInstanceError):
        first.state = ApprovalState.APPROVED


def test_approved_request_cannot_be_granted_twice(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    assert not h.gate.approve(request.request_id, authentication=h.approver).allowed
    assert len([event for event in h.store.events if event.kind == AuditKind.GRANTED]) == 1


def test_transaction_rollback_does_not_publish_partial_changes(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending()
    with pytest.raises(RuntimeError):
        with h.store.transaction() as transaction:
            from dataclasses import replace
            transaction.put(replace(request, state=ApprovalState.CONSUMED))
            raise RuntimeError("Synthetic storage failure")
    assert h.store.get(request.request_id).state == ApprovalState.PENDING
