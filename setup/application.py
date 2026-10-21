"""Provisional JSON application boundary; no HTTP, storage, or execution.

Public payloads contain request information only. ``dependency_inputs`` is a
separate, keyword-only input for internal orchestration, never a public field.
It remains subject to domain association checks and cannot authorize execution.
"""

from dataclasses import replace

from .integration import PreparationInputs
from .models import OperationRequest, PreparationResult, StructuredError, WorkflowState
from .validation import validate_request
from .workflow import prepare_request


_REQUEST_FIELDS = ("request_id", "operation", "details")


def _decode_request(payload: object) -> tuple[OperationRequest | None, tuple[StructuredError, ...]]:
    if not isinstance(payload, dict):
        return None, (StructuredError("invalid_request", "Expected a JSON object.", "payload"),)
    errors = tuple(
        StructuredError(
            "unknown_field", "Only request_id, operation, and details are public request fields.",
            key if isinstance(key, str) else None,
        )
        for key in payload if key not in _REQUEST_FIELDS
    )
    # Empty values represent absent information for existing domain validation;
    # no operational target, choice, or identifier is generated here.
    return OperationRequest(
        payload.get("request_id", ""), payload.get("operation", ""), payload.get("details", {}),
    ), errors


def _response(
    result: PreparationResult,
    request: OperationRequest | None,
    payload_errors: tuple[StructuredError, ...] = (),
) -> dict:
    if payload_errors:
        result = replace(
            result, state=WorkflowState.BLOCKED,
            state_history=(WorkflowState.RECEIVED, WorkflowState.BLOCKED),
            errors=payload_errors, plan=None,
        )
    snapshot = None
    if request is not None and not payload_errors:
        validated = validate_request(request)
        if not validated.errors and validated.request_id is not None and validated.operation is not None:
            snapshot = {
                "request_id": validated.request_id,
                "operation": validated.operation,
                "details": dict(validated.collected_information),
            }
    # Keep the existing preparation representation, adding only a safe request
    # snapshot for stateless continuation. Rejected arbitrary values are not echoed.
    return {**result.to_dict(), "request": snapshot}


def submit_request(payload: object, *, dependency_inputs: PreparationInputs | None = None) -> dict:
    """Prepare a decoded JSON request and return JSON-compatible state/plan.

    Allowed payload keys: request_id, operation, details. Unknown envelope fields
    block the request. Detail fields and values use existing domain validation.
    Missing teammate inputs give the ordinary blocked candidate-plan outcome.
    Nothing is stored; resubmitting the returned ``request`` reevaluates it.
    """
    request, errors = _decode_request(payload)
    result = prepare_request(request, None if errors else dependency_inputs)
    return _response(result, request, errors)
