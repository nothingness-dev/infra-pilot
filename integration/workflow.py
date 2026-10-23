"""Versioned, offline request-to-review orchestration using existing modules.

This fixture profile accepts only controlled Mock brief text; it is not a
free-text or production intake API. Each instance retains its own current brief,
collection and approval example. There is no HTTP route or execution path.
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Callable

from infrapilot_triage import ActionIntent
from provider.examples.context_fixtures import MOCK_CONTEXT_SCENARIOS
from setup.application import submit_request, supply_information
from setup.approval_workflow import SetupApprovalWorkflow, execution_readiness
from setup.integration import CONTRACT_VERSION, DependencyInput, PreparationInputs, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import SetupIntegrationError

from .errors import MockIntegrationError
from .mock_approval import MockClock, OperatorApprovalExample
from .service import MockSession


WORKFLOW_VERSION = "infrapilot-request-approval/1-mock"
MOCK_GOAL = "Review this synthetic service collection"
_GOALS = (MOCK_GOAL, "Review this synthetic service again")
SCENARIOS = (
    "complete", "complete_information", "needs_information", "invalid_completion",
    "changed_target", "partial_failure", "empty", "unavailable", "not_collected", "withheld", "partial_logs",
    "unmapped_action", "policy_denied", "approval_pending", "approved_not_executed",
    "approval_rejected", "approval_expired", "unauthenticated", "permission_denied",
)
_APPROVAL_SCENARIOS = (
    "approval_pending", "approved_not_executed", "approval_rejected", "approval_expired",
    "unauthenticated", "permission_denied",
)
_REQUEST = {"request_id": "MOCK-workflow-request", "operation": "inspect_service"}
_FLAGS = {"authorization_consumed": False, "execution_authorized": False, "execution_performed": False}


def _datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("Workflow output is not JSON compatible.")


def _copy(value):
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False, default=_datetime))


@dataclass(frozen=True)
class WorkflowResult:
    _json: str = field(repr=False)
    exit_code: int

    def to_dict(self) -> dict:
        return json.loads(self._json)


class MockWorkflow:
    """Reusable single-session backend API. No JSON can establish trust.

    The limited fixture vocabulary prevents free-form user text, including
    accidentally supplied credentials, from reaching component serializers.
    Shared Setup input models remain unchanged. A revised accepted brief
    invalidates the previous inspection and approval; stale objects cannot be
    transferred to a new collection. This class is not thread-safe or durable.
    """

    def __init__(self, *, mock: bool = False, collection_scenario: str = "exported",
                 clock: Callable[[], datetime] | None = None, approval_store_factory=None):
        if mock is not True:
            raise MockIntegrationError("MOCK_OPT_IN_REQUIRED") from None
        if type(collection_scenario) is not str or collection_scenario not in MOCK_CONTEXT_SCENARIOS:
            raise MockIntegrationError("INVALID_SCENARIO") from None
        self._collection_scenario = collection_scenario
        self._clock = clock if clock is not None else MockClock()
        self._approval_store_factory = approval_store_factory
        self._accepted = None
        self._stages = {}
        self._inspection = None
        self._operator = None
        self._review = None
        self._invalid = False
        self._failed = False

    def __repr__(self):
        return "MockWorkflow(mode='mock', execution='disabled')"

    def close(self):
        if self._operator is not None:
            self._operator.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _result(self, state, stage, code=0, *, error=None):
        collection = self._stages.get("collection")
        collection_status = "not_collected"
        if collection is not None:
            attempted = [item for item in collection["collection_context"]["capabilities"]
                         if item["availability"] != "not_collected"]
            collection_status = "complete" if all(item["availability"] == "available" for item in attempted) else "partial"
        data = {
            "contract_version": WORKFLOW_VERSION, "mode": "mock", "state": state, "stage": stage,
            "collection_scenario": self._collection_scenario, "stages": self._stages,
            "collection_status": collection_status,
            "error_code": error, "execution": execution_readiness(),
            "post_action_evaluation": "not_performed", "remediation_verified": False,
            "production_readiness": "unresolved", **_FLAGS,
        }
        return WorkflowResult(json.dumps(data, ensure_ascii=True, allow_nan=False, sort_keys=True, default=_datetime), code)

    def _perform(self, stage, operation):
        self._active_stage = stage
        try:
            return operation()
        except (SetupIntegrationError, MockIntegrationError):
            # Raw component error details/fields are not part of this boundary.
            self._failed = True
            return self._result("failed", self._active_stage, 2, error="ASSOCIATION_OR_COMPONENT_FAILURE")
        except Exception:
            self._failed = True
            return self._result("failed", self._active_stage, 2, error="UNEXPECTED_STAGE_FAILURE")

    @staticmethod
    def _fixture_brief(snapshot):
        if type(snapshot) is not dict:
            return False
        details = snapshot["details"]
        return (snapshot["request_id"] == _REQUEST["request_id"]
                and snapshot["operation"] == _REQUEST["operation"]
                and set(details) <= {"service_target", "goal"}
                and details.get("service_target", "MOCK-service") == "MOCK-service"
                and details.get("goal", MOCK_GOAL) in _GOALS)

    def _invalidate(self):
        self.close()
        self._inspection, self._operator, self._review = None, None, None
        self._failed = False
        for name in ("collection", "preparation", "inspection", "action_review", "operator_example"):
            self._stages.pop(name, None)

    def _accept(self, response, stage):
        # Setup returns candidate plans blocked on absent dependencies. That is
        # distinct from invalid intake. Do not fabricate provider/triage refs.
        invalid = any(item["code"] != "dependency_unavailable" for item in response["errors"])
        if invalid or not self._fixture_brief(response["request"]):
            self._invalid = True
            self._accepted = None
            # Error field names in upstream validation can contain rejected input.
            self._stages[stage] = {"state": "rejected", "error_code": "INVALID_MOCK_BRIEF"}
            return self._result("invalid_request", stage, 3, error="INVALID_MOCK_BRIEF")
        self._invalid = False
        self._accepted = _copy(response["request"])
        self._stages[stage] = _copy(response)
        if response["missing_information"]:
            return self._result("needs_information", stage, 4)
        return self._result("ready_for_collection", stage)

    def submit(self, payload: object) -> WorkflowResult:
        def operation():
            self._invalidate()
            self._stages = {}
            self._accepted = None
            return self._accept(submit_request(payload), "intake")
        return self._perform("intake", operation)

    def supply_information(self, additional_information: object) -> WorkflowResult:
        def operation():
            self._invalidate()
            if self._accepted is None:
                return self._result("invalid_request", "completion", 3, error="ACCEPTED_BRIEF_REQUIRED")
            response = supply_information(self._accepted, additional_information)
            return self._accept(response, "completion")
        return self._perform("completion", operation)

    def inspect(self) -> WorkflowResult:
        def operation():
            if self._failed:
                return self._result("failed", "collection", 2, error="RESUBMIT_BRIEF_REQUIRED")
            if self._invalid or self._accepted is None or not self._fixture_brief(self._accepted):
                return self._result("invalid_request", "collection", 3, error="ACCEPTED_BRIEF_REQUIRED")
            if self._stages.get("completion", self._stages["intake"])["missing_information"]:
                return self._result("needs_information", "collection", 4)
            if self._inspection is None:
                request = OperationRequest(**self._accepted)
                # Initial candidate plan already exists in intake/completion.
                self._active_stage = "collection"
                session = MockSession(mock=True, scenario=self._collection_scenario,
                                      service_id=self._accepted["details"]["service_target"], request=request)
                self._stages["collection"] = session.collection_request()
                self._active_stage = "diagnosis"
                inspection = session.inspect()
                self._inspection = inspection
                self._stages["inspection"] = inspection.result.to_dict()
                # Only now do actual retained outputs justify associated refs.
                self._active_stage = "preparation"
                provider_input = inspection.presentation.evidence.association
                triage_input = DependencyInput(True, "mock:workflow-diagnosis", metadata=ResultMetadata(
                    CONTRACT_VERSION, request.request_id, request.operation, request_fingerprint(request),
                    "triage", "ready", "mock",
                ))
                self._stages["preparation"] = submit_request(self._accepted, dependency_inputs=PreparationInputs(
                    provider=provider_input, triage=triage_input,
                ))
                if self._stages["preparation"]["state"] != "plan_prepared":
                    raise MockIntegrationError("SETUP_ASSOCIATION_FAILED")
            self._inspection.validate()
            return self._result("diagnosis_available", "diagnosis", self._inspection.result.exit_code)
        return self._perform("diagnosis", operation)

    def _current(self):
        if self._inspection is None or self._invalid or self._failed or self._accepted is None:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED")
        self._inspection.validate()
        if request_fingerprint(OperationRequest(**self._accepted)) != request_fingerprint(self._inspection.request):
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED")

    def review_action(self, proposal_id: str = "collect_observability", *, deny_example: bool = False) -> WorkflowResult:
        def operation():
            self._current()
            self._review = None
            self._stages.pop("action_review", None)
            # This sole reviewed mapping means "collect available observations".
            # No sensitive operation is inferred from any diagnosis proposal.
            if type(proposal_id) is not str or proposal_id != "collect_observability" or not any(
                item.action_id == proposal_id for item in self._inspection.presentation.report.actions
            ):
                self._stages["action_review"] = {"state": "action_unmapped", "error_code": "NO_REVIEWED_MAPPING"}
                return self._result("action_unmapped", "action_review", 4, error="NO_REVIEWED_MAPPING")
            if type(deny_example) is not bool:
                return self._result("invalid_request", "action_review", 3, error="INVALID_MOCK_OPTION")
            # Separate, explicitly labelled operator-selected denied example.
            intent = ActionIntent(service_id="MOCK-service", action_type=(
                "delete_service" if deny_example else "refresh_observations"
            ))
            workflow = SetupApprovalWorkflow()
            review = workflow.review_action(self._inspection.request, self._inspection.presentation,
                                            proposal_id, intent=intent)
            self._review = review
            self._stages["action_review"] = {
                "relationship": ("separate_operator_selected_denied_example_not_diagnosis_derived"
                                 if deny_example else "reviewed_observation_recommendation_mapping"),
                "result": review.to_dict(),
            }
            state = "policy_reviewed_not_executed" if review.policy.allowed else "policy_denied"
            return self._result(state, "action_review", self._inspection.result.exit_code if review.policy.allowed else 4,
                                error=None if review.policy.allowed else review.policy.reason)
        return self._perform("action_review", operation)

    def operator_example(self, outcome: str = "approval_pending") -> WorkflowResult:
        def operation():
            self._current()
            if type(outcome) is not str or outcome not in _APPROVAL_SCENARIOS:
                return self._result("invalid_request", "approval", 3, error="INVALID_MOCK_OPTION")
            if self._review is None or not self._review.policy.allowed or self._operator is not None:
                return self._result("blocked", "approval", 4, error="CURRENT_ACTION_REVIEW_REQUIRED")
            if self._operator is not None:
                self._operator.close()
            self._operator = OperatorApprovalExample(self._inspection, clock=self._clock,
                                                     store_factory=self._approval_store_factory)
            example = self._operator
            example.identity.permitted = outcome != "permission_denied"
            decision = example.request(authentication=(
                None if outcome == "unauthenticated" else example.identity.requester_session
            ))
            self._stages["operator_example"] = _copy(example.to_dict())
            if decision.request is not None and outcome in (
                "approved_not_executed", "approval_rejected", "approval_expired",
            ):
                if outcome == "approval_expired":
                    # The runner installs a mutable synthetic clock; alternate
                    # clocks must be advanced by their backend owner, not here.
                    if isinstance(self._clock, MockClock):
                        self._clock.now = decision.request.expires_at
                decision = example.decide(approve=outcome != "approval_rejected",
                                          authentication=example.identity.approver_session)
                self._stages["operator_example"] = _copy(example.to_dict())
            states = {
                "approval_pending": "approval_pending", "approval_approved": "approved_not_executed",
                "approval_rejected": "approval_rejected", "approval_expired": "approval_expired",
                "unauthenticated": "unauthenticated", "not_authorized": "permission_denied",
            }
            state = states.get(decision.reason.value, "approval_blocked")
            return self._result(state, "approval", 4, error=(None if decision.request else decision.reason.value))
        return self._perform("approval", operation)


def run_mock_workflow(*, mock=False, scenario="complete", approval_store_factory=None) -> WorkflowResult:
    """Allowlisted scenario runner; the reusable session supplies the behavior."""
    if mock is not True:
        raise MockIntegrationError("MOCK_OPT_IN_REQUIRED") from None
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise MockIntegrationError("INVALID_SCENARIO") from None
    collection = scenario if scenario in MOCK_CONTEXT_SCENARIOS else "exported"
    with MockWorkflow(mock=True, collection_scenario=collection, approval_store_factory=approval_store_factory) as workflow:
        return _run_workflow(workflow, scenario)


def _run_workflow(workflow, scenario):
    details = {} if scenario in ("complete_information", "needs_information", "invalid_completion", "changed_target") else {
        "service_target": "MOCK-service", "goal": MOCK_GOAL,
    }
    result = workflow.submit({**_REQUEST, "details": details})
    if result.exit_code == 3 or scenario == "needs_information":
        return result
    if not details:
        completion = {"service_target": "MOCK-service", "goal": MOCK_GOAL}
        if scenario == "invalid_completion":
            completion = {"approved": True}
        elif scenario == "changed_target":
            completion["service_target"] = "MOCK-other-service"
        result = workflow.supply_information(completion)
        if result.exit_code:
            return result
    result = workflow.inspect()
    if result.exit_code not in (0, 1):
        return result
    result = workflow.review_action("unmapped" if scenario == "unmapped_action" else "collect_observability",
                                    deny_example=scenario == "policy_denied")
    if scenario in _APPROVAL_SCENARIOS and result.exit_code in (0, 1):
        return workflow.operator_example(scenario)
    return result
