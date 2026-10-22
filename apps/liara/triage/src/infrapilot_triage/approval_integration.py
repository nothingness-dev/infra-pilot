"""Thin internal adapter over the existing policy and gate; no approval mutations."""

from .api_contracts import PolicyEvaluationResponse
from .approvals import DecisionReason, GateDecision
from .authorization import ApprovalGate
from .policy import ActionCategory, ActionIntent, ActionPolicy, PolicyDecision


class ApprovalIntegration:
    """Install only from trusted server composition, never from HTTP body data.

    Evaluation is informational and grants no authorization. authorize delegates
    every actual permission/lifecycle/audit check to the existing Task 3 gate.
    """

    def __init__(self, *, policy: ActionPolicy | None = None, gate: ApprovalGate | None = None) -> None:
        self._policy = policy
        self._gate = gate

    def evaluate(self, intent: ActionIntent) -> PolicyEvaluationResponse:
        unavailable = PolicyDecision(False, ActionCategory.DENIED, True, "policy_unavailable")
        if self._policy is None:
            return PolicyEvaluationResponse(policy=unavailable)
        try:
            decision = self._policy.classify(intent)
            if (
                not isinstance(decision, PolicyDecision)
                or type(decision.allowed) is not bool
                or type(decision.requires_approval) is not bool
                or not isinstance(decision.category, ActionCategory)
                or decision.reason not in {
                    "classified", "unsupported_action", "invalid_or_unknown_action", "policy_unavailable",
                }
            ):
                return PolicyEvaluationResponse(policy=unavailable)
            # Reuse the existing canonical classifier, not a second rule table.
            if decision.allowed and decision != ActionPolicy.classify(self._policy, intent):
                return PolicyEvaluationResponse(policy=unavailable)
            if not decision.allowed and (
                decision.action is not None or decision.category != ActionCategory.DENIED
                or not decision.requires_approval
            ):
                return PolicyEvaluationResponse(policy=unavailable)
            return PolicyEvaluationResponse(policy=decision)
        except Exception:
            return PolicyEvaluationResponse(policy=unavailable)

    def authorize(
        self, intent: ActionIntent, *, authentication: object | None = None,
        approval_request_id: str | None = None,
    ) -> GateDecision:
        if self._gate is None:
            return GateDecision(False, DecisionReason.STORAGE_UNAVAILABLE)
        try:
            decision = self._gate.authorize(
                intent, authentication=authentication, approval_request_id=approval_request_id,
            )
            if not isinstance(decision, GateDecision) or type(decision.allowed) is not bool:
                return GateDecision(False, DecisionReason.AUTHORIZATION_UNAVAILABLE)
            return decision
        except Exception:
            return GateDecision(False, DecisionReason.AUTHORIZATION_UNAVAILABLE)
