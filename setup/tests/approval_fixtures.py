"""Synthetic opaque sessions for the actual gate; never a login implementation."""

from datetime import datetime, timedelta, timezone

from infrapilot_triage import (
    ActionIntent, ActionPolicy, ApprovalGate, AuthenticatedActor, InMemoryApprovalStore, Permission,
)

from setup.approval_workflow import SetupApprovalWorkflow
from setup.tests.triage_fixtures import problem, service_evidence
from setup.triage import prepare_diagnosis


class FixtureIdentity:
    """Exact preinstalled object identity, target and permissions; no user IDs accepted."""

    def __init__(self):
        self.requester_session, self.approver_session = object(), object()
        self.allowed = True
        self.requester_can_approve = False

    def authenticate(self, authentication):
        if authentication is self.requester_session:
            return AuthenticatedActor('fixture-requester')
        if authentication is self.approver_session:
            return AuthenticatedActor('fixture-approver')
        return None

    def is_authorized(self, actor, action, permission):
        if not self.allowed or action.service_id != 'mock-service-A':
            return False
        return ((actor.subject == 'fixture-requester' and (permission == Permission.REQUEST
                 or (permission == Permission.APPROVE and self.requester_can_approve)))
                or (actor.subject == 'fixture-approver' and permission == Permission.APPROVE))


class ApprovalFixture:
    """Real gate/policy/store with explicit mock observations and fixture sessions."""

    def __init__(self):
        self.request = problem()
        self.presentation = prepare_diagnosis(self.request, service_evidence())
        self.proposal_id = 'review_resource_configuration'
        self.now = datetime(2026, 10, 22, tzinfo=timezone.utc)
        self.identity = FixtureIdentity()
        self.policy = ActionPolicy()
        self.store = InMemoryApprovalStore()
        self.gate = ApprovalGate(identity=self.identity, policy=self.policy, store=self.store, clock=lambda: self.now)
        self.workflow = SetupApprovalWorkflow(gate=self.gate, policy=self.policy)

    def review(self, *, intent=None):
        # Explicit test-only reviewed mapping; not automatic recommendation dispatch
        # or a statement that a provider supports this operation/quantity.
        intent = intent or ActionIntent(service_id='mock-service-A', action_type='change_resources',
                                        parameters={'cpu_millicores': 500})
        return self.workflow.review_action(self.request, self.presentation, self.proposal_id, intent=intent)

    def pending(self):
        review = self.review()
        return self.workflow.request_approval(review.binding, request=self.request, presentation=self.presentation,
                                              authentication=self.identity.requester_session)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
