"""Small stateless completion helper; request identity is never patched."""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from .integration import PreparationInputs
from .models import OperationRequest, PreparationResult, StructuredError, WorkflowState
from .validation import validate_request
from .workflow import prepare_request


@dataclass(frozen=True)
class RequestCompletion:
    request: OperationRequest | None
    preparation: PreparationResult


def complete_request(
    request: object,
    additional_information: object,
    inputs: PreparationInputs | None = None,
) -> RequestCompletion:
    """Merge detail values into a detached request and revalidate preparation.

    The original must have established identity and a supported operation.
    Additional information patches details only. It can replace incorrect values;
    it cannot change the request ID or operation. Supplied dependency results are
    checked against the full updated brief, never silently rebound or cached.
    """
    initial = validate_request(request)
    if (initial.request_id is None or initial.operation is None
            or not isinstance(request.details, Mapping)):
        return RequestCompletion(None, prepare_request(request, inputs))

    updated = OperationRequest(request.request_id, request.operation, dict(request.details))
    if not isinstance(additional_information, Mapping):
        result = prepare_request(updated, inputs)
        blocked = replace(
            result, state=WorkflowState.BLOCKED,
            state_history=(WorkflowState.RECEIVED, WorkflowState.BLOCKED), plan=None,
            errors=(*result.errors, StructuredError(
                "invalid_additional_information", "Expected a mapping of detail fields.",
                "additional_information",
            )),
        )
        return RequestCompletion(updated, blocked)

    updated = replace(updated, details={**updated.details, **additional_information})
    return RequestCompletion(updated, prepare_request(updated, inputs))
