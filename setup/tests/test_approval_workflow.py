"""Setup integration calls actual policy/gate/store, with fixture identity only."""

import json
import unittest
from unittest.mock import patch

from infrapilot_triage import (
    ActionIntent, ActionPolicy, ApprovalGate, ApprovalState, AuditKind, DecisionReason,
    InMemoryApprovalStore,
)

from setup.approval_workflow import SetupApprovalWorkflow, execution_readiness
from setup.tests.approval_fixtures import ApprovalFixture
from setup.tests.triage_fixtures import problem, service_evidence
from setup.triage import SetupIntegrationError, prepare_diagnosis


class ApprovalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = ApprovalFixture()

    def decide(self, method, pending, **fields):
        return method(pending.binding, pending.approval_request_id,
                      request=self.h.request, presentation=self.h.presentation,
                      authentication=self.h.identity.approver_session, **fields)

    def test_policy_required_is_independent_of_advisory_proposal_flags(self):
        review = self.h.review()
        self.assertEqual(review.to_dict()['state'], 'policy_decision_returned')
        self.assertEqual(review.to_dict()['approval_reason'], DecisionReason.APPROVAL_REQUIRED.value)
        self.assertEqual(review.policy, self.h.policy.classify(review.binding.intent))
        self.assertEqual(review.binding.canonical.parameters, {'cpu_millicores': 500})
        self.assertFalse(review.to_dict()['execution_authorized'])
        self.assertEqual(self.h.store.events, ())
        read_only = self.h.review(intent=ActionIntent(service_id='mock-service-A', action_type='inspect_metrics'))
        self.assertEqual(read_only.to_dict()['approval_reason'], DecisionReason.APPROVAL_NOT_REQUIRED.value)
        self.assertFalse(read_only.to_dict()['execution_authorized'])

    def test_pending_approved_then_revoked_never_authorizes_or_executes(self):
        with patch.object(self.h.gate, 'authorize', side_effect=AssertionError('Must not consume authorization')):
            pending = self.h.pending()
            self.assertEqual(pending.decision.reason, DecisionReason.PENDING)
            self.assertEqual(pending.decision.request.state, ApprovalState.PENDING)
            approved = self.decide(self.h.workflow.approve, pending)
            self.assertEqual(approved.decision.reason, DecisionReason.APPROVED)
            self.assertEqual(approved.decision.request.approved_by.subject, 'fixture-approver')
            rejected = self.decide(self.h.workflow.reject, pending)
        self.assertEqual(rejected.decision.reason, DecisionReason.REJECTED)
        self.assertEqual(self.h.store.get(pending.approval_request_id).state, ApprovalState.REJECTED)
        for update in (pending, approved, rejected):
            data = update.to_dict()
            self.assertFalse(data['gate_decision']['allowed'])
            self.assertIsNone(data['gate_decision']['authorization_id'])
            self.assertFalse(data['execution_authorized'])
            self.assertFalse(data['execution_performed'])
            self.assertEqual(data['execution']['state'], 'execution_disabled')
            self.assertTrue(data['execution']['blockers'])
            json.dumps(data, allow_nan=False)
        self.assertEqual([e.kind for e in self.h.store.events],
                         [AuditKind.REQUESTED, AuditKind.GRANTED, AuditKind.REJECTED])
        self.assertTrue(all(a.status == 'not_executed' for a in self.h.presentation.report.actions))

    def test_rejected_request_is_terminal_and_cannot_be_reapproved(self):
        pending = self.h.pending()
        rejected = self.decide(self.h.workflow.reject, pending)
        repeated = self.decide(self.h.workflow.approve, pending)
        self.assertEqual(rejected.decision.reason, DecisionReason.REJECTED)
        self.assertEqual(repeated.decision.reason, DecisionReason.REJECTED)
        self.assertEqual(self.h.store.get(pending.approval_request_id).state, ApprovalState.REJECTED)

    def test_missing_authentication_or_frontend_claims_never_create_approval(self):
        binding = self.h.review().binding
        for authentication in (None, True, False, 'fixture-requester', {'subject': 'fixture-requester', 'approved': True}):
            with self.subTest(authentication=authentication):
                update = self.h.workflow.request_approval(binding, request=self.h.request,
                                                          presentation=self.h.presentation,
                                                          authentication=authentication)
                self.assertEqual(update.decision.reason, DecisionReason.UNAUTHENTICATED)
                self.assertIsNone(update.approval_request_id)
                self.assertFalse(update.to_dict()['execution_authorized'])

    def test_default_gate_and_missing_identity_or_policy_fail_closed(self):
        fixtures = [
            (SetupApprovalWorkflow(), DecisionReason.STORAGE_UNAVAILABLE),
            (SetupApprovalWorkflow(gate=ApprovalGate(policy=self.h.policy, store=InMemoryApprovalStore())),
             DecisionReason.IDENTITY_UNAVAILABLE),
            (SetupApprovalWorkflow(gate=ApprovalGate(identity=self.h.identity, store=InMemoryApprovalStore())),
             DecisionReason.POLICY_UNAVAILABLE),
        ]
        for workflow, reason in fixtures:
            review = workflow.review_action(self.h.request, self.h.presentation, self.h.proposal_id,
                                             intent=self.h.review().binding.intent)
            update = workflow.request_approval(review.binding, request=self.h.request,
                                                presentation=self.h.presentation,
                                                authentication=self.h.identity.requester_session)
            self.assertEqual(update.decision.reason, reason)
            self.assertFalse(update.to_dict()['execution_authorized'])

    def test_requester_cannot_self_approve_and_frontend_boolean_cannot_approve(self):
        pending = self.h.pending()
        self.h.identity.requester_can_approve = True
        for authentication, reason in ((self.h.identity.requester_session, DecisionReason.SELF_APPROVAL),
                                        (True, DecisionReason.UNAUTHENTICATED)):
            update = self.h.workflow.approve(pending.binding, pending.approval_request_id,
                                             request=self.h.request, presentation=self.h.presentation,
                                             authentication=authentication)
            self.assertEqual(update.decision.reason, reason)
            self.assertEqual(self.h.store.get(pending.approval_request_id).state, ApprovalState.PENDING)

    def test_changed_request_target_report_proposal_parameters_and_version_are_refused(self):
        pending = self.h.pending()
        changed = problem(goal='A different problem')
        current = prepare_diagnosis(changed, service_evidence(changed))
        with self.assertRaises(SetupIntegrationError) as caught:
            self.h.workflow.approve(pending.binding, pending.approval_request_id,
                                     request=changed, presentation=current,
                                     authentication=self.h.identity.approver_session)
        self.assertEqual(caught.exception.error.code, 'stale_binding')
        other = problem(service_target='mock-service-B')
        with self.assertRaises(SetupIntegrationError):
            self.h.workflow.request_approval(pending.binding, request=other,
                                             presentation=prepare_diagnosis(other, service_evidence(other)))
        self.h.presentation.report.summary = 'Changed retained report'
        with self.assertRaises(SetupIntegrationError):
            self.decide(self.h.workflow.approve, pending)
        self.h = ApprovalFixture()
        pending = self.h.pending()
        pending.binding.intent.parameters['cpu_millicores'] = 750
        with self.assertRaises(SetupIntegrationError):
            self.decide(self.h.workflow.approve, pending)
        self.h = ApprovalFixture()
        pending = self.h.pending()
        self.h.policy.VERSION = 'future-policy-v2'
        with self.assertRaises(SetupIntegrationError):
            self.decide(self.h.workflow.approve, pending)

    def test_same_canonical_action_cannot_transfer_approval_to_other_proposal_or_problem(self):
        pending = self.h.pending()
        alternate = self.h.workflow.review_action(self.h.request, self.h.presentation, 'inspect_cpu_load',
                                                  intent=ActionIntent(service_id='mock-service-A',
                                                  action_type='change_resources', parameters={'cpu_millicores': 500}))
        self.assertEqual(alternate.binding.canonical, pending.binding.canonical)
        with self.assertRaises(SetupIntegrationError) as caught:
            self.h.workflow.approve(alternate.binding, pending.approval_request_id,
                                     request=self.h.request, presentation=self.h.presentation,
                                     authentication=self.h.identity.approver_session)
        self.assertEqual(caught.exception.error.code, DecisionReason.ACTION_MISMATCH.value)
        changed = problem(goal='Independent workflow for the same service')
        presentation = prepare_diagnosis(changed, service_evidence(changed))
        review = self.h.workflow.review_action(changed, presentation, self.h.proposal_id,
                                               intent=ActionIntent(service_id='mock-service-A',
                                               action_type='change_resources', parameters={'cpu_millicores': 500}))
        with self.assertRaises(SetupIntegrationError):
            self.h.workflow.reject(review.binding, pending.approval_request_id,
                                    request=changed, presentation=presentation,
                                    authentication=self.h.identity.approver_session)

    def test_missing_unknown_or_restart_lost_workflow_binding_is_unusable(self):
        pending = self.h.pending()
        for identifier in (None, True, 'not-a-request', '00000000-0000-0000-0000-000000000000'):
            with self.subTest(identifier=identifier), self.assertRaises(SetupIntegrationError) as caught:
                self.h.workflow.approve(pending.binding, identifier, request=self.h.request,
                                         presentation=self.h.presentation,
                                         authentication=self.h.identity.approver_session)
            self.assertEqual(caught.exception.error.code, DecisionReason.REQUEST_NOT_FOUND.value)
        restarted = SetupApprovalWorkflow(gate=self.h.gate, policy=self.h.policy)
        with self.assertRaises(SetupIntegrationError):
            restarted.approve(pending.binding, pending.approval_request_id, request=self.h.request,
                               presentation=self.h.presentation,
                               authentication=self.h.identity.approver_session)
        self.assertEqual(self.h.store.get(pending.approval_request_id).state, ApprovalState.PENDING)

    def test_expired_approval_and_revoked_acl_use_actual_gate_reasons(self):
        pending = self.h.pending()
        self.h.identity.allowed = False
        denied = self.decide(self.h.workflow.approve, pending)
        self.assertEqual(denied.decision.reason, DecisionReason.NOT_AUTHORIZED)
        self.h.identity.allowed = True
        self.h.advance(300)
        expired = self.decide(self.h.workflow.approve, pending)
        self.assertEqual(expired.decision.reason, DecisionReason.EXPIRED)
        self.assertEqual(self.h.store.get(pending.approval_request_id).state, ApprovalState.EXPIRED)

    def test_no_automatic_mapping_and_no_use_of_frontend_binding_or_changed_proposal(self):
        for intent in (None, {'action_type': 'restart_service'}, True):
            with self.subTest(intent=intent), self.assertRaises(SetupIntegrationError):
                self.h.workflow.review_action(self.h.request, self.h.presentation, self.h.proposal_id, intent=intent)
        for proposal_id in ('missing-proposal', True):
            with self.assertRaises(SetupIntegrationError):
                self.h.workflow.review_action(self.h.request, self.h.presentation, proposal_id,
                                               intent=ActionIntent(service_id='mock-service-A', action_type='inspect_service'))
        with self.assertRaises(SetupIntegrationError):
            self.h.workflow.request_approval(self.h.review().binding.to_dict(), request=self.h.request,
                                             presentation=self.h.presentation)
        wrong = self.h.review().binding.intent.model_copy(update={'service_id': 'other-target'})
        with self.assertRaises(SetupIntegrationError):
            self.h.review(intent=wrong)
        wrong = self.h.review().binding.intent.model_copy(update={'proposal': self.h.presentation.report.actions[0]})
        with self.assertRaises(SetupIntegrationError):
            self.h.review(intent=wrong)

    def test_denied_actions_and_unavailable_or_malformed_policies_create_no_binding(self):
        denied = self.h.review(intent=ActionIntent(service_id='mock-service-A', action_type='execute_command'))
        self.assertFalse(denied.policy.allowed)
        self.assertIsNone(denied.binding)
        for output in (None, True, {'allowed': True}):
            class BrokenPolicy(ActionPolicy):
                def classify(self, intent):
                    return output
            workflow = SetupApprovalWorkflow(policy=BrokenPolicy())
            review = workflow.review_action(self.h.request, self.h.presentation, self.h.proposal_id,
                                             intent=self.h.review().binding.intent)
            self.assertEqual(review.policy.reason, 'policy_unavailable')
            self.assertIsNone(review.binding)

    def test_audit_failure_does_not_create_or_grant_approval(self):
        class FailingStore(InMemoryApprovalStore):
            fail = True
            def transaction(self):
                if self.fail:
                    raise RuntimeError('synthetic storage outage')
                return super().transaction()
        store = FailingStore()
        gate = ApprovalGate(identity=self.h.identity, policy=self.h.policy, store=store, clock=lambda: self.h.now)
        workflow = SetupApprovalWorkflow(gate=gate, policy=self.h.policy)
        binding = self.h.review().binding
        denied = workflow.request_approval(binding, request=self.h.request, presentation=self.h.presentation,
                                             authentication=self.h.identity.requester_session)
        self.assertEqual(denied.decision.reason, DecisionReason.STORAGE_UNAVAILABLE)
        self.assertFalse(denied.decision.audit_recorded)
        store.fail = False
        pending = workflow.request_approval(binding, request=self.h.request, presentation=self.h.presentation,
                                              authentication=self.h.identity.requester_session)
        store.fail = True
        denied = workflow.approve(binding, pending.approval_request_id, request=self.h.request,
                                   presentation=self.h.presentation, authentication=self.h.identity.approver_session)
        self.assertEqual(denied.decision.reason, DecisionReason.STORAGE_UNAVAILABLE)
        self.assertEqual(store.get(pending.approval_request_id).state, ApprovalState.PENDING)

    def test_workflow_has_no_provider_network_process_or_authorization_consumption(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('No real operation or authorization consumption permitted')
        with patch('socket.socket', forbidden), patch('subprocess.Popen', forbidden), patch('os.system', forbidden), \
                patch.object(self.h.gate, 'authorize', forbidden):
            pending = self.h.pending()
            update = self.decide(self.h.workflow.approve, pending)
        self.assertEqual(update.decision.request.state, ApprovalState.APPROVED)
        self.assertFalse(update.to_dict()['execution_authorized'])
        self.assertEqual(execution_readiness()['state'], 'execution_disabled')
        self.assertFalse(hasattr(self.h.workflow, 'execute'))


if __name__ == '__main__':
    unittest.main()
