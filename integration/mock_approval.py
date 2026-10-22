"""Isolated operator-selected MOCK example, never diagnosis-derived remediation.

Only the existing Triage gate changes approval state. No authorization is
consumed. The local binding prevents attaching this example to another brief,
diagnosis, context or canonical action; it is not production authentication.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

from infrapilot_triage import (
    ActionIntent, ActionPolicy, ApprovalGate, AuthenticatedActor, InMemoryApprovalStore, Permission,
)
from infrapilot_triage.approval_integration import ApprovalIntegration
from infrapilot_triage.approvals import GateDecision
from setup.integration import request_fingerprint

from .errors import MockIntegrationError
from .service import CompletedInspection


class MockClock:
    """Synthetic aware clock. It never claims an observation's source time."""

    def __init__(self):
        self.now = datetime(2026, 10, 23, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Identity:
    def __init__(self, action):
        self.requester_session, self.approver_session = object(), object()
        self.requester = AuthenticatedActor("MOCK-workflow-requester")
        self.approver = AuthenticatedActor("MOCK-workflow-approver")
        self.action = action
        self.permitted = True

    def authenticate(self, authentication):
        if authentication is self.requester_session:
            return self.requester
        if authentication is self.approver_session:
            return self.approver
        return None

    def is_authorized(self, actor, action, permission):
        if not self.permitted or action != self.action:
            return False
        return ((actor == self.requester and permission == Permission.REQUEST)
                or (actor == self.approver and permission == Permission.APPROVE))


class OperatorApprovalExample:
    """Trusted in-process MOCK composition; no client-selected identities/actions.

    A restart with fixed parameters is explicitly chosen by this fixture's
    operator, independently of the report. Policy acceptance is not evidence
    that Liara supports it. This class has no execution/authorize method.
    """

    def __init__(self, inspection: CompletedInspection, *, clock: Callable[[], datetime]):
        inspection.validate()
        self.inspection = inspection
        self.intent = ActionIntent(service_id="MOCK-service", action_type="restart_service",
                                   parameters={"grace_period_seconds": 30})
        self.policy = ActionPolicy()
        self.review = ApprovalIntegration(policy=self.policy).evaluate(self.intent)
        if not self.review.policy.allowed or self.review.policy.action is None:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        self._binding = self._current_binding()
        self.identity = _Identity(self.review.policy.action)
        self.store = InMemoryApprovalStore()
        self.gate = ApprovalGate(identity=self.identity, policy=self.policy, store=self.store, clock=clock)
        self._identifier = None
        self._decisions = []

    def __repr__(self):
        return "OperatorApprovalExample(mode='mock', execution='disabled')"

    def _current_binding(self):
        self.inspection.validate()
        decision = self.policy.classify(self.intent)
        if not decision.allowed or decision.action != self.review.policy.action:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        return (request_fingerprint(self.inspection.request), self.inspection.presentation.binding,
                self.inspection.companion.binding, decision.action)

    def _check(self):
        if self._current_binding() != self._binding:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        if self._identifier is not None:
            current = self.store.get(self._identifier)
            if current is None or current.action != self._binding[3]:
                raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None

    def _record(self, decision: GateDecision) -> GateDecision:
        # Retain the original gate record, including its FALSE allowed field.
        if (decision.allowed is not False or decision.authorization_id is not None
                or (decision.action is not None and decision.action != self._binding[3])
                or (decision.request is not None and (
                    decision.request.action != self._binding[3]
                    or decision.request.request_id != self._identifier))):
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        self._decisions.append(asdict(decision))
        return decision

    def request(self, *, authentication: object | None) -> GateDecision:
        self._check()
        if self._identifier is not None:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        decision = self.gate.request_approval(self.intent, authentication=authentication)
        self._identifier = decision.request.request_id if decision.request else None
        return self._record(decision)

    def decide(self, *, approve: bool, authentication: object | None) -> GateDecision:
        self._check()
        if type(approve) is not bool or self._identifier is None:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        method = self.gate.approve if approve else self.gate.reject
        return self._record(method(self._identifier, authentication=authentication))

    def to_dict(self) -> dict:
        self._check()
        current = self.store.get(self._identifier) if self._identifier else None
        return {
            "relationship": "separate_operator_selected_mock_example_not_diagnosis_derived",
            "provider_operation_support": "unverified",
            "identity_source": "isolated_opaque_mock_sessions",
            "storage": "volatile_in_memory", "clock_source": "synthetic_injected_clock",
            "request_fingerprint": self._binding[0], "diagnosis_binding": self._binding[1],
            "companion_binding": self._binding[2],
            "review": self.review.model_dump(mode="json"),
            "decisions": self._decisions,
            "current_approval": asdict(current) if current else None,
            "audit_events": [asdict(event) for event in self.store.events],
            "authorization_consumed": False, "execution_authorized": False, "execution_performed": False,
        }
