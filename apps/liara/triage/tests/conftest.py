"""Trusted identity fixtures for tests only; not a production authenticator."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from infrapilot_triage.approval_store import InMemoryApprovalStore
from infrapilot_triage.approvals import ApprovalRequest, ApprovalState
from infrapilot_triage.authorization import ApprovalGate
from infrapilot_triage.identity import AuthenticatedActor, Permission
from infrapilot_triage.policy import ActionIntent, ActionPolicy, ActionType, CanonicalAction


class TestClock:
    __test__ = False

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class TestIdentityBoundary:
    """Preinstalled opaque sessions and ACLs simulate a trusted verifier, not a gate."""

    __test__ = False

    def __init__(self) -> None:
        self.sessions: dict[object, AuthenticatedActor] = {}
        self.active: set[str] = set()
        self.permissions: set[tuple[str, str, ActionType, Permission]] = set()

    def install_session(self, subject: str) -> object:
        actor = AuthenticatedActor(subject)
        handle = object()
        self.sessions[handle] = actor
        self.active.add(subject)
        return handle

    def authenticate(self, authentication: object) -> AuthenticatedActor | None:
        try:
            actor = self.sessions.get(authentication)
        except TypeError:
            return None
        return actor if actor is not None and actor.subject in self.active else None

    def is_authorized(self, actor: AuthenticatedActor, action: CanonicalAction, permission: Permission) -> bool:
        return actor.subject in self.active and (
            actor.subject, action.service_id, action.action_type, permission
        ) in self.permissions


def make_intent(**changes: Any) -> ActionIntent:
    return ActionIntent.model_validate({
        "service_id": "service-A", "action_type": "restart_service", "parameters": {}, **changes,
    })


@dataclass
class ApprovalHarness:
    gate: ApprovalGate
    store: InMemoryApprovalStore
    identity: TestIdentityBoundary
    policy: ActionPolicy
    clock: TestClock
    requester: object
    approver: object
    other: object
    outsider: object

    def pending(self, intent: ActionIntent | None = None, **options: Any) -> ApprovalRequest:
        result = self.gate.request_approval(intent or make_intent(), authentication=self.requester, **options)
        assert not result.allowed
        assert result.request is not None and result.request.state == ApprovalState.PENDING
        return result.request

    def approved(self, intent: ActionIntent | None = None, **options: Any) -> ApprovalRequest:
        request = self.pending(intent, **options)
        result = self.gate.approve(request.request_id, authentication=self.approver)
        assert not result.allowed
        assert result.request is not None and result.request.state == ApprovalState.APPROVED
        return result.request


@pytest.fixture
def approval_harness() -> ApprovalHarness:
    identity = TestIdentityBoundary()
    handles = {name: identity.install_session(name) for name in ("requester", "approver", "other", "outsider")}
    for service in ("service-A", "service-B"):
        for action in ActionType:
            for subject in ("requester", "other"):
                for permission in (Permission.REQUEST, Permission.EXECUTE):
                    identity.permissions.add((subject, service, action, permission))
            identity.permissions.add(("approver", service, action, Permission.APPROVE))
    clock = TestClock()
    store = InMemoryApprovalStore()
    policy = ActionPolicy()
    gate = ApprovalGate(identity=identity, policy=policy, store=store, clock=clock)
    return ApprovalHarness(gate, store, identity, policy, clock, **handles)
