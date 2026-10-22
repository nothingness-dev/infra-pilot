"""Attack tests against the real authorization gate, not a mocked decision."""

from datetime import timedelta
from typing import Any

import pytest

from conftest import ApprovalHarness, make_intent
from infrapilot_triage import ActionProposal
from infrapilot_triage.approvals import ApprovalState, DecisionReason
from infrapilot_triage.authorization import ApprovalGate
from infrapilot_triage.identity import AuthenticatedActor, Permission
from infrapilot_triage.policy import ActionType


@pytest.mark.parametrize("operation", ["inspect_service", "inspect_logs", "inspect_metrics", "refresh_observations"])
def test_inspection_requires_identity_and_current_target_permission(approval_harness: ApprovalHarness, operation: str) -> None:
    h = approval_harness
    intent = make_intent(action_type=operation)
    assert not h.gate.authorize(intent).allowed
    assert not h.gate.authorize(intent, authentication=h.outsider).allowed
    result = h.gate.authorize(intent, authentication=h.requester)
    assert result.allowed and result.action.action_type == operation
    assert result.request is None


def test_an_agent_cannot_mark_a_sensitive_operation_safe(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    proposal = ActionProposal(
        action_id="restart_service", title="Safe operation", description="Untrusted assertion.",
        risk_level="low", requires_approval=False,
    )
    result = h.gate.authorize(make_intent(proposal=proposal), authentication=h.requester)
    assert not result.allowed and result.reason == DecisionReason.APPROVAL_REQUIRED
    assert proposal.status == "not_executed"


def test_returned_payload_never_dispatches_the_untrusted_proposal(approval_harness: ApprovalHarness) -> None:
    proposal = ActionProposal(
        action_id="restart_service", title="Restart", description="Agent display metadata.",
        risk_level="low", requires_approval=False,
    )
    result = approval_harness.gate.authorize(
        make_intent(action_type="inspect_service", proposal=proposal), authentication=approval_harness.requester,
    )
    assert result.allowed
    assert result.action.action_type == ActionType.INSPECT_SERVICE
    assert result.action.parameters == {}
    assert proposal.status == "not_executed"


@pytest.mark.parametrize("operation", ["delete_service", "execute_command", "unknown_operation"])
def test_unknown_and_destructive_operations_never_get_approval(approval_harness: ApprovalHarness, operation: str) -> None:
    h = approval_harness
    intent = make_intent(action_type=operation)
    assert not h.gate.authorize(intent, authentication=h.requester).allowed
    assert h.gate.request_approval(intent, authentication=h.requester).request is None


def test_approval_cannot_be_reused_for_another_service(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    result = h.gate.authorize(make_intent(service_id="service-B"), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.ACTION_MISMATCH
    assert h.store.get(request.request_id).state == ApprovalState.APPROVED


def test_parameter_substitution_is_denied(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    changed = make_intent(parameters={"grace_period_seconds": 0})
    result = h.gate.authorize(changed, authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.ACTION_MISMATCH


def test_mutating_the_original_parameters_cannot_change_saved_approval(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    intent = make_intent(parameters={"grace_period_seconds": 30})
    request = h.approved(intent)
    intent.parameters["grace_period_seconds"] = 0
    assert not h.gate.authorize(intent, authentication=h.requester, approval_request_id=request.request_id).allowed
    assert h.store.get(request.request_id).action.parameters == {"grace_period_seconds": 30}


def test_equivalent_canonical_defaults_are_the_same_action(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    intent = make_intent(parameters={"grace_period_seconds": 30})
    assert h.gate.authorize(intent, authentication=h.requester, approval_request_id=request.request_id).allowed


def test_approval_cannot_be_transferred_to_another_requester(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    result = h.gate.authorize(make_intent(), authentication=h.other, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.REQUESTER_MISMATCH


def test_unverified_actor_identifiers_and_constructed_actors_are_not_credentials(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending()
    for forged in (None, "approver", AuthenticatedActor("approver"), {"subject": "approver", "verified": True}):
        decision = h.gate.approve(request.request_id, authentication=forged)
        assert not decision.allowed
        assert h.store.get(request.request_id).state == ApprovalState.PENDING


def test_unauthorized_approver_and_wrong_target_approver_are_denied(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.pending()
    assert not h.gate.approve(request.request_id, authentication=h.outsider).allowed
    h.identity.permissions.remove(("approver", "service-A", ActionType.RESTART_SERVICE, Permission.APPROVE))
    assert not h.gate.approve(request.request_id, authentication=h.approver).allowed
    assert h.store.get(request.request_id).state == ApprovalState.PENDING


def test_self_approval_is_denied_even_with_an_approval_role(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    h.identity.permissions.add(("requester", "service-A", ActionType.RESTART_SERVICE, Permission.APPROVE))
    request = h.pending()
    result = h.gate.approve(request.request_id, authentication=h.requester)
    assert not result.allowed and result.reason == DecisionReason.SELF_APPROVAL


@pytest.mark.parametrize("revocation", ["requester_permission", "approver_permission", "approver_account"])
def test_permissions_are_rechecked_at_consumption(approval_harness: ApprovalHarness, revocation: str) -> None:
    h = approval_harness
    request = h.approved()
    if revocation == "requester_permission":
        h.identity.permissions.remove(("requester", "service-A", ActionType.RESTART_SERVICE, Permission.EXECUTE))
    elif revocation == "approver_permission":
        h.identity.permissions.remove(("approver", "service-A", ActionType.RESTART_SERVICE, Permission.APPROVE))
    else:
        h.identity.active.remove("approver")
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed
    assert h.store.get(request.request_id).state == ApprovalState.APPROVED


def test_policy_version_change_invalidates_existing_approval(approval_harness: ApprovalHarness) -> None:
    h = approval_harness
    request = h.approved()
    h.policy.VERSION = "new-policy"
    result = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not result.allowed and result.reason == DecisionReason.ACTION_MISMATCH


def test_expiry_is_rechecked_after_authorization_boundary_calls(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness
    request = h.approved(ttl=timedelta(seconds=1))
    original = h.identity.is_authorized

    def slow_check(actor, action, permission):
        result = original(actor, action, permission)
        if actor.subject == "approver":
            h.clock.advance(timedelta(seconds=2))
        return result

    monkeypatch.setattr(h.identity, "is_authorized", slow_check)
    decision = h.gate.authorize(make_intent(), authentication=h.requester, approval_request_id=request.request_id)
    assert not decision.allowed and decision.reason == DecisionReason.EXPIRED
    assert h.store.get(request.request_id).state == ApprovalState.EXPIRED


@pytest.mark.parametrize("missing", ["identity", "policy", "store"])
def test_missing_trusted_dependencies_fail_closed(approval_harness: ApprovalHarness, missing: str) -> None:
    h = approval_harness
    dependencies = {"identity": h.identity, "policy": h.policy, "store": h.store}
    dependencies[missing] = None
    gate = ApprovalGate(**dependencies, clock=h.clock)
    assert not gate.authorize(make_intent(), authentication=h.requester).allowed


def test_default_gate_is_not_an_allowing_demo(approval_harness: ApprovalHarness) -> None:
    assert not ApprovalGate().authorize(make_intent(action_type="inspect_service"), authentication=approval_harness.requester).allowed


@pytest.mark.parametrize("boundary_method", ["authenticate", "is_authorized"])
def test_identity_or_permission_backend_failure_denies(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch, boundary_method: str) -> None:
    h = approval_harness

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Synthetic identity backend unavailable")

    monkeypatch.setattr(h.identity, boundary_method, unavailable)
    assert not h.gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester).allowed


def test_nonboolean_authorization_responses_fail_closed(approval_harness: ApprovalHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    h = approval_harness
    monkeypatch.setattr(h.identity, "is_authorized", lambda *args: "yes")
    assert not h.gate.authorize(make_intent(action_type="inspect_service"), authentication=h.requester).allowed
