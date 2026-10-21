"""Offline preparation only: no network, policy evaluation, or execution path."""

from .integration import (
    CONTRACT_VERSION,
    PROVENANCES,
    RESULT_STATES,
    DependencyInput,
    PreparationInputs,
    ResultMetadata,
    validate_dependency_input,
)
from .models import (
    Dependency,
    DependencyPhase,
    Operation,
    OperationPlan,
    OperationRequest,
    PreparationResult,
    StructuredError,
    WorkflowState,
    WorkflowStep,
)
from .validation import validate_request


def _external_dependency(
    role: str, source: DependencyInput | None, request: OperationRequest,
) -> tuple[Dependency, tuple[StructuredError, ...]]:
    key = f"{role}_output"
    field = f"dependencies.{key}"
    if source is None:
        dependency = Dependency(
            key, DependencyPhase.PREPARATION, False,
            "No external output was supplied; the module does not fetch or fabricate it.",
        )
        return dependency, (StructuredError("dependency_unavailable", dependency.reason, field),)
    errors = tuple(
        StructuredError(error.code, error.message, f"{field}.{error.field}" if error.field else field)
        for error in validate_dependency_input(source, request, role)
    )
    metadata = source.metadata if isinstance(source.metadata, ResultMetadata) else None
    # Never serialize malformed metadata values or publish an unusable reference.
    state = (
        metadata.state
        if metadata and isinstance(metadata.state, str) and metadata.state in RESULT_STATES else None
    )
    provenance = (
        metadata.provenance
        if metadata and isinstance(metadata.provenance, str) and metadata.provenance in PROVENANCES else None
    )
    version = CONTRACT_VERSION if metadata and metadata.contract_version == CONTRACT_VERSION else None
    dependency = Dependency(
        key, DependencyPhase.PREPARATION, source.available and not errors,
        errors[0].message if errors else (
            "Associated reference only; payload, authenticity, and freshness are not validated."
            if source.available else source.reason
        ),
        source.output_reference if not errors else None,
        reported_state=state, provenance=provenance, contract_version=version,
    )
    if not errors and not source.available:
        errors = (StructuredError(f"dependency_{state or 'unavailable'}", source.reason, field),)
    return dependency, errors


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
    current_request = OperationRequest(
        validated.request_id, validated.operation, dict(validated.collected_information),
    )
    provider, provider_errors = _external_dependency("provider", inputs.provider, current_request)
    dependencies = [provider]
    errors = list(provider_errors)
    if validated.operation == Operation.INSPECT_SERVICE.value:
        triage, triage_errors = _external_dependency("triage", inputs.triage, current_request)
        dependencies.append(triage)
        errors.extend(triage_errors)
    dependencies.extend((
        Dependency(
            "provider_capability_validation", DependencyPhase.EXECUTION, False,
            "Roham's provider capability and requirement validation is outside this preparation module.",
        ),
        Dependency(
            "authorization_validation", DependencyPhase.EXECUTION, False,
            "Setayesh's authorization mechanism is unavailable here; no permission is inferred.",
        ),
        Dependency(
            "operation_executor", DependencyPhase.EXECUTION, False,
            "This preparation module has no real operation executor.",
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
    return finish(
        WorkflowState.BLOCKED if errors else WorkflowState.PLAN_PREPARED,
        plan=plan, errors=tuple(errors),
    )
