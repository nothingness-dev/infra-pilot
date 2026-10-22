"""Review/approval presentation using triage's actual policy and gate.

Trusted backend objects only. No authenticator, durable store, HTTP API,
authorization consumer or operation executor is implemented in this module.
"""

from dataclasses import dataclass

from infrapilot_triage import (
    ActionIntent, ActionPolicy, ApprovalGate, ApprovalState, CanonicalAction,
    DecisionReason, GateDecision, PolicyDecision,
)
from infrapilot_triage.approval_integration import ApprovalIntegration
from pydantic import ValidationError

from .integration import request_fingerprint
from .models import OperationRequest
from .triage import DiagnosisPresentation, SetupIntegrationError, validate_presentation


def _action(action: CanonicalAction | None) -> dict | None:
    if action is None:
        return None
    return {
        "service_id": action.service_id, "action_type": action.action_type.value,
        "parameters": action.parameters, "policy_version": action.policy_version,
        "fingerprint": action.fingerprint,
    }


def execution_readiness() -> dict:
    """Always refuse real operations, even after an approved policy lifecycle."""
    return {
        "state": "execution_disabled", "execution_authorized": False,
        "execution_performed": False,
        "blockers": [
            "production_authentication_and_target_acl_not_integrated",
            "durable_approval_and_workflow_binding_storage_not_integrated",
            "provider_capability_validation_not_integrated",
            "real_operation_execution_not_implemented",
        ],
    }


@dataclass(frozen=True)
class BoundAction:
    request_id: str
    request_fingerprint: str
    diagnosis_binding: str
    proposal_id: str
    intent: ActionIntent
    canonical: CanonicalAction

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id, "request_fingerprint": self.request_fingerprint,
            "diagnosis_binding": self.diagnosis_binding, "proposal_id": self.proposal_id,
            "canonical_action": _action(self.canonical),
        }


@dataclass(frozen=True)
class ActionReview:
    policy: PolicyDecision
    binding: BoundAction | None

    def to_dict(self) -> dict:
        reason = self.policy.reason
        if self.policy.allowed:
            reason = (DecisionReason.APPROVAL_REQUIRED if self.policy.requires_approval
                      else DecisionReason.APPROVAL_NOT_REQUIRED).value
        return {
            "state": "policy_decision_returned", "approval_reason": reason,
            "policy_decision": {
                "allowed": self.policy.allowed, "category": self.policy.category.value,
                "requires_approval": self.policy.requires_approval, "reason": self.policy.reason,
                "action": _action(self.policy.action),
            },
            "binding": self.binding.to_dict() if self.binding else None,
            "execution": execution_readiness(),
            "execution_authorized": False, "execution_performed": False,
        }


@dataclass(frozen=True)
class ApprovalUpdate:
    binding: BoundAction
    decision: GateDecision
    approval_request_id: str | None

    def to_dict(self) -> dict:
        decision, approval = self.decision, self.decision.request
        request = None
        if approval is not None:
            request = {
                "request_id": approval.request_id, "action": _action(approval.action),
                "requested_by": {"subject": approval.requested_by.subject},
                "created_at": approval.created_at.isoformat(),
                "expires_at": approval.expires_at.isoformat(), "state": approval.state.value,
                "approved_by": ({"subject": approval.approved_by.subject}
                                if approval.approved_by else None),
                "rejected_by": ({"subject": approval.rejected_by.subject}
                                if approval.rejected_by else None),
                "consumed_by": ({"subject": approval.consumed_by.subject}
                                if approval.consumed_by else None),
            }
        return {
            "state": decision.reason.value, "approval_request_id": self.approval_request_id,
            "binding": self.binding.to_dict(),
            "gate_decision": {
                "allowed": decision.allowed, "reason": decision.reason.value,
                "action": _action(decision.action), "request": request,
                "authorization_id": decision.authorization_id,
                "audit_recorded": decision.audit_recorded,
            },
            "execution": execution_readiness(),
            "execution_authorized": False, "execution_performed": False,
        }


class SetupApprovalWorkflow:
    """Process-local trusted workflow binding; production persistence is unfinished.

    Install the actual gate and policy in server composition, never from a client.
    This object does not call ApprovalGate.authorize, consume grants, or execute.
    Losing this registry fails closed even if a separate approval store survives.
    """

    def __init__(self, *, gate: ApprovalGate | None = None, policy: ActionPolicy | None = None):
        if gate is not None and not isinstance(gate, ApprovalGate):
            raise TypeError("Install an actual ApprovalGate in trusted backend code.")
        if policy is not None and not isinstance(policy, ActionPolicy):
            raise TypeError("Install the actual ActionPolicy in trusted backend code.")
        self._gate = gate if gate is not None else ApprovalGate()
        self._policy = policy if policy is not None else ActionPolicy()
        self._classification = ApprovalIntegration(policy=self._policy)
        self._requests: dict[str, BoundAction] = {}

    def review_action(
        self, request: OperationRequest, presentation: DiagnosisPresentation,
        proposal_id: str, *, intent: ActionIntent | None = None,
    ) -> ActionReview:
        validate_presentation(request, presentation)
        proposal = next((p for p in presentation.report.actions if p.action_id == proposal_id), None)
        if proposal is None:
            raise SetupIntegrationError("proposal_not_found", "Select a proposal in the current Diagnosis report.")
        if not isinstance(intent, ActionIntent):
            raise SetupIntegrationError(
                "action_mapping_required", "Trusted backend code must supply an explicitly reviewed canonical ActionIntent."
            )
        try:
            supplied = ActionIntent.model_validate(intent.model_dump(warnings=False))
        except ValidationError:
            raise SetupIntegrationError("invalid_action", "Canonical ActionIntent validation failed.") from None
        if supplied.service_id != presentation.report.service_id:
            raise SetupIntegrationError("target_mismatch", "Action target differs from the current report.")
        if supplied.proposal is not None and supplied.proposal != proposal:
            raise SetupIntegrationError("proposal_mismatch", "Action metadata differs from the selected proposal.")
        # Proposal ID/text/risk never select an operation or parameters.
        supplied = ActionIntent.model_validate(supplied.model_dump() | {"proposal": proposal.model_dump()})
        # Reuse the published informational bridge's fail-closed handling of
        # unavailable/malformed policies; do not copy its rule table into Setup.
        decision = self._classification.evaluate(supplied).policy
        binding = None
        if decision.allowed and decision.action is not None:
            binding = BoundAction(request.request_id, request_fingerprint(request), presentation.binding,
                                  proposal_id, supplied, decision.action)
        return ActionReview(decision, binding)

    def _current(
        self, binding: BoundAction, request: OperationRequest, presentation: DiagnosisPresentation,
    ) -> None:
        validate_presentation(request, presentation)
        if not isinstance(binding, BoundAction):
            raise SetupIntegrationError("invalid_binding", "Expected a backend action binding.")
        if (binding.request_id != request.request_id
                or binding.request_fingerprint != request_fingerprint(request)
                or binding.diagnosis_binding != presentation.binding):
            raise SetupIntegrationError("stale_binding", "Refresh Diagnosis and review the current request again.")
        proposal = next((p for p in presentation.report.actions if p.action_id == binding.proposal_id), None)
        if proposal is None or binding.intent.proposal != proposal:
            raise SetupIntegrationError("proposal_mismatch", "The bound proposal has changed.")
        current = self._classification.evaluate(binding.intent).policy
        if not current.allowed or current.action != binding.canonical:
            raise SetupIntegrationError(DecisionReason.ACTION_MISMATCH.value,
                                        "The canonical action or policy version has changed.")

    @staticmethod
    def _update(binding: BoundAction, decision: GateDecision, identifier: str | None) -> ApprovalUpdate:
        if (not isinstance(decision, GateDecision) or decision.allowed is not False
                or not isinstance(decision.reason, DecisionReason)
                or type(decision.audit_recorded) is not bool or decision.authorization_id is not None
                or (decision.action is not None and decision.action != binding.canonical)
                or (decision.request is not None and decision.request.action != binding.canonical)):
            raise SetupIntegrationError("invalid_gate_decision", "Approval transition returned an inconsistent decision.")
        if decision.request is not None and decision.request.request_id != identifier:
            raise SetupIntegrationError("invalid_gate_decision", "Approval request identity is inconsistent.")
        return ApprovalUpdate(binding, decision, identifier)

    def request_approval(
        self, binding: BoundAction, *, request: OperationRequest,
        presentation: DiagnosisPresentation, authentication: object | None = None,
    ) -> ApprovalUpdate:
        self._current(binding, request, presentation)
        decision = self._gate.request_approval(binding.intent, authentication=authentication)
        identifier = decision.request.request_id if decision.request else None
        update = self._update(binding, decision, identifier)
        if decision.request is not None and decision.request.state == ApprovalState.PENDING:
            self._requests[identifier] = binding
        return update

    def _decide(
        self, approve: bool, binding: BoundAction, approval_request_id: str | None, *,
        request: OperationRequest, presentation: DiagnosisPresentation, authentication: object | None,
    ) -> ApprovalUpdate:
        self._current(binding, request, presentation)
        if not isinstance(approval_request_id, str) or approval_request_id not in self._requests:
            raise SetupIntegrationError(DecisionReason.REQUEST_NOT_FOUND.value,
                                        "No workflow-bound approval request is available; request a fresh review.")
        if self._requests[approval_request_id] != binding:
            raise SetupIntegrationError(DecisionReason.ACTION_MISMATCH.value,
                                        "Approval belongs to another request, Diagnosis, proposal or action.")
        method = self._gate.approve if approve else self._gate.reject
        decision = method(approval_request_id, authentication=authentication)
        return self._update(binding, decision, approval_request_id)

    def approve(
        self, binding: BoundAction, approval_request_id: str | None, *, request: OperationRequest,
        presentation: DiagnosisPresentation, authentication: object | None = None,
    ) -> ApprovalUpdate:
        return self._decide(True, binding, approval_request_id, request=request,
                            presentation=presentation, authentication=authentication)

    def reject(
        self, binding: BoundAction, approval_request_id: str | None, *, request: OperationRequest,
        presentation: DiagnosisPresentation, authentication: object | None = None,
    ) -> ApprovalUpdate:
        return self._decide(False, binding, approval_request_id, request=request,
                            presentation=presentation, authentication=authentication)
