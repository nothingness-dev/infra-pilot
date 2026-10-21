"""Validate a local planning brief, without asserting Liara capabilities."""

from collections.abc import Mapping
from dataclasses import dataclass

from .models import MissingInformation, Operation, OperationRequest, StructuredError


# Provisional local brief fields, not a provider API schema or deployment spec.
_REQUIRED = {
    Operation.SETUP_SERVICE.value: ("service_name", "service_kind", "goal"),
    Operation.INSPECT_SERVICE.value: ("service_target", "goal"),
}
_OPTIONAL = {
    Operation.SETUP_SERVICE.value: ("plan", "region", "budget"),
    Operation.INSPECT_SERVICE.value: (),
}


@dataclass(frozen=True)
class ValidationResult:
    request_id: str | None
    operation: str | None
    collected_information: Mapping[str, str]
    missing_information: tuple[MissingInformation, ...]
    errors: tuple[StructuredError, ...]

    @property
    def is_complete(self) -> bool:
        return not self.missing_information and not self.errors


def validate_request(request: object) -> ValidationResult:
    """Return missing fields and structured errors without mutating the caller.

    Strings are preserved exactly. Blank required strings count as missing;
    wrong types, unknown fields, and unsupported operations are errors.
    """
    if not isinstance(request, OperationRequest):
        return ValidationResult(None, None, {}, (), (
            StructuredError("invalid_request", "Expected an OperationRequest."),
        ))

    missing = []
    errors = []
    collected = {}
    request_id = None
    operation = None
    if not isinstance(request.request_id, str):
        errors.append(StructuredError("invalid_field", "Expected a string.", "request_id"))
    elif not request.request_id.strip():
        missing.append(MissingInformation("request_id", "Provide a request identifier."))
    else:
        request_id = request.request_id

    if not isinstance(request.operation, str):
        errors.append(StructuredError("invalid_field", "Expected a string.", "operation"))
    elif not request.operation.strip():
        missing.append(MissingInformation("operation", "Choose a supported operation."))
    elif request.operation not in _REQUIRED:
        errors.append(StructuredError(
            "unsupported_operation",
            "Supported local operations: setup_service, inspect_service.",
            "operation",
        ))
    else:
        operation = Operation(request.operation).value

    if not isinstance(request.details, Mapping):
        errors.append(StructuredError("invalid_field", "Expected a mapping.", "details"))
    elif operation is not None:
        required = _REQUIRED[operation]
        allowed = (*required, *_OPTIONAL[operation])
        for key, value in request.details.items():
            if not isinstance(key, str) or key not in allowed:
                errors.append(StructuredError(
                    "unknown_field", "Field is not supported for this operation.",
                    f"details.{key}" if isinstance(key, str) else "details",
                ))
            elif not isinstance(value, str):
                errors.append(StructuredError(
                    "invalid_field", "Expected a string.", f"details.{key}",
                ))
            elif value.strip():
                collected[key] = value
            elif key not in required:
                errors.append(StructuredError(
                    "invalid_field", "Omit an unspecified optional field or supply a value.",
                    f"details.{key}",
                ))
        for key in required:
            if key not in request.details or (
                isinstance(request.details[key], str) and not request.details[key].strip()
            ):
                missing.append(MissingInformation(f"details.{key}", f"Provide {key}."))

    return ValidationResult(request_id, operation, collected, tuple(missing), tuple(errors))
