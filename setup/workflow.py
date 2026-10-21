"""Offline preparation only: no network, policy evaluation, or execution path."""

from .integration import DependencyInput, PreparationInputs
from .models import (
    Dependency,
    DependencyPhase,
    Operation,
    OperationPlan,
    PreparationResult,
    StructuredError,
    WorkflowState,
    WorkflowStep,
)
from .validation import validate_request


def _external_dependency(key: str, source: DependencyInput | None) -> Dependency:
    if source is None:
        return Dependency(
            key, DependencyPhase.PREPARATION, False,
            "No external output was supplied; the module does not fetch or fabricate it.",
        )
    return Dependency(
        key, DependencyPhase.PREPARATION, source.available,
        "Caller-supplied reference; contents are not validated here."
        if source.available else source.reason,
        source.output_reference,
    )


def _proposed_steps(operation: str) -> tuple[WorkflowStep, ...]:
    steps = [
        WorkflowStep("review_brief", "Review the collected user intent and constraints."),
        WorkflowStep(
            "review_provider_output", "Review the external provider output reference.",
            ("provider_output",),
        ),
    ]
    if operation == Operation.INSPECT_SERVICE.value:
        steps.append(WorkflowStep(
            "review_triage_output",
            "Review the external triage output reference; diagnosis remains triage-owned.",
            ("triage_output",),
        ))
    steps.extend((
        WorkflowStep(
            "resolve_provider_requirements",
            "Have the provider module confirm capabilities, applicable requirements, "
            "remaining user choices, and any cost information before execution.",
            ("provider_capability_validation",),
        ),
        WorkflowStep(
            "obtain_authorization_validation",
            "Refer the completed request to the teammate-owned authorization mechanism.",
            ("authorization_validation",),
        ),
        WorkflowStep(
            "future_execution_handoff",
            "Hand off only after separate capability and authorization validation; "
            "no executor exists in this module.",
            ("provider_capability_validation", "authorization_validation", "operation_executor"),
        ),
    ))
    return tuple(steps)


def prepare_request(
    request: object, inputs: PreparationInputs | None = None,
) -> PreparationResult:
    """Prepare or explain a request; never invoke an external dependency.

    Each call records received -> one terminal preparation state. Missing local
    information is resolved before dependencies. Valid briefs retain a candidate
    plan even when external preparation inputs are unavailable. Resubmission is
    explicit: call again with a new complete request or additional input refs.
    """
    validated = validate_request(request)
    common = {
        "request_id": validated.request_id,
        "collected_information": dict(validated.collected_information),
        "missing_information": validated.missing_information,
    }

    def finish(state: WorkflowState, **values) -> PreparationResult:
        return PreparationResult(
            state=state, state_history=(WorkflowState.RECEIVED, state),
            **common, **values,
        )

    if validated.errors:
        return finish(WorkflowState.BLOCKED, errors=validated.errors)
    if validated.missing_information:
        return finish(WorkflowState.NEEDS_INFORMATION)
    if inputs is not None and not isinstance(inputs, PreparationInputs):
        return finish(WorkflowState.BLOCKED, errors=(StructuredError(
            "invalid_dependency_input", "Expected PreparationInputs or None.", "inputs",
        ),))

    inputs = inputs if inputs is not None else PreparationInputs()
    dependencies = [_external_dependency("provider_output", inputs.provider)]
    if validated.operation == Operation.INSPECT_SERVICE.value:
        dependencies.append(_external_dependency("triage_output", inputs.triage))
    dependencies.extend((
        Dependency(
            "provider_capability_validation", DependencyPhase.EXECUTION, False,
            "Roham's provider capability and requirement validation is outside Stage 1.",
        ),
        Dependency(
            "authorization_validation", DependencyPhase.EXECUTION, False,
            "Setayesh's authorization mechanism is unavailable here; no permission is inferred.",
        ),
        Dependency(
            "operation_executor", DependencyPhase.EXECUTION, False,
            "Stage 1 has no real operation executor.",
        ),
    ))
    plan = OperationPlan(
        request_id=validated.request_id,
        operation=validated.operation,
        collected_information=dict(validated.collected_information),
        missing_information=validated.missing_information,
        proposed_steps=_proposed_steps(validated.operation),
        dependencies=tuple(dependencies),
    )
    errors = tuple(
        StructuredError("dependency_unavailable", item.reason, f"dependencies.{item.key}")
        for item in dependencies
        if item.phase == DependencyPhase.PREPARATION and not item.available
    )
    return finish(
        WorkflowState.BLOCKED if errors else WorkflowState.PLAN_PREPARED,
        plan=plan, errors=errors,
    )
