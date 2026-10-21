"""Data-only references to teammate outputs; no adapters or policies."""

from dataclasses import dataclass, fields
import hashlib
import json
import re

from .models import OperationRequest, StructuredError
from .validation import validate_request


CONTRACT_VERSION = "setup-integration-v1"
RESULT_STATES = ("ready", "pending", "failed", "unavailable")
PROVENANCES = ("mock", "external")
_REFERENCE = re.compile(r"(mock|external):[A-Za-z0-9][A-Za-z0-9._-]*")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class ResultMetadata:
    """Provisional coordination envelope, not a provider/diagnosis payload.

    All fields are caller assertions. Matching them establishes structure and
    association only, never authenticity, freshness, or authorization.
    """

    contract_version: str
    request_id: str
    operation: str
    request_fingerprint: str
    source: str
    state: str
    provenance: str


def request_fingerprint(request: OperationRequest) -> str:
    """Bind the entire valid brief, including identity and exact detail strings.

    Canonicalization is a local proposal. A digest is not a signature or proof
    of trust. Any change to the brief requires newly associated result metadata.
    """
    validated = validate_request(request)
    if not validated.is_complete:
        raise ValueError("a fingerprint requires a complete, valid request brief")
    canonical = json.dumps({
        "contract_version": CONTRACT_VERSION,
        "request_id": validated.request_id,
        "operation": validated.operation,
        "details": dict(validated.collected_information),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class DependencyInput:
    """A caller-supplied output reference or an explicit unavailability reason.

    Availability describes a preparation input, never permission to execute.
    The producer retains ownership of the referenced payload and its schema.
    """

    available: bool
    output_reference: str | None = None
    reason: str | None = None
    metadata: ResultMetadata | None = None

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise ValueError("available must be a boolean")
        if self.available:
            if not isinstance(self.output_reference, str) or not self.output_reference.strip():
                raise ValueError("an available input requires a nonblank output reference")
            if self.reason is not None:
                raise ValueError("an available input cannot have an unavailability reason")
        else:
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError("an unavailable input requires a nonblank reason")
            if self.output_reference is not None:
                raise ValueError("an unavailable input cannot carry an output reference")


@dataclass(frozen=True)
class PreparationInputs:
    """Optional external results; absent inputs are unavailable, never fabricated."""

    provider: DependencyInput | None = None
    triage: DependencyInput | None = None

    def __post_init__(self) -> None:
        for value in (self.provider, self.triage):
            if value is not None and not isinstance(value, DependencyInput):
                raise ValueError("preparation inputs must be DependencyInput objects or None")


def validate_dependency_input(
    source: DependencyInput, request: OperationRequest, expected_source: str,
) -> tuple[StructuredError, ...]:
    """Check an external envelope against a complete brief without resolving it.

    Legacy unavailable inputs remain usable as blocking signals. A legacy
    available boolean/reference without metadata must never establish readiness.
    Metadata is checked here so malformed envelopes yield structured errors.
    """
    if not isinstance(source, DependencyInput):
        return (StructuredError("invalid_dependency_input", "Expected DependencyInput."),)
    metadata = source.metadata
    if metadata is None:
        if not source.available:
            return ()
        return (StructuredError(
            "dependency_metadata_required", "An available input requires associated result metadata.",
            "metadata",
        ),)
    if not isinstance(metadata, ResultMetadata):
        return (StructuredError(
            "invalid_dependency_metadata", "Expected ResultMetadata.", "metadata",
        ),)
    errors = [
        StructuredError("invalid_dependency_metadata", "Expected a nonblank string.", f"metadata.{item.name}")
        for item in fields(metadata)
        if not isinstance(getattr(metadata, item.name), str) or not getattr(metadata, item.name).strip()
    ]
    if errors:
        return tuple(errors)
    if metadata.contract_version != CONTRACT_VERSION:
        return (StructuredError(
            "unsupported_contract_version", "Unsupported provisional coordination contract version.",
            "metadata.contract_version",
        ),)

    def error(code: str, message: str, field: str) -> None:
        errors.append(StructuredError(code, message, field))

    if metadata.request_id != request.request_id:
        error("dependency_request_mismatch", "Result belongs to a different request.", "metadata.request_id")
    if metadata.operation != request.operation:
        error("dependency_operation_mismatch", "Result operation does not match the request.", "metadata.operation")
    if not _FINGERPRINT.fullmatch(metadata.request_fingerprint):
        error("invalid_request_fingerprint", "Expected sha256 followed by a lowercase hexadecimal digest.",
              "metadata.request_fingerprint")
    elif metadata.request_fingerprint != request_fingerprint(request):
        error("dependency_request_mismatch", "Result does not match the current complete request brief.",
              "metadata.request_fingerprint")
    if metadata.source != expected_source:
        error("dependency_source_mismatch", "Result source does not match the dependency slot.", "metadata.source")
    if metadata.state not in RESULT_STATES:
        error("unsupported_dependency_state", "Unrecognized dependency state.", "metadata.state")
    elif source.available != (metadata.state == "ready"):
        error("inconsistent_dependency_state", "Availability contradicts the reported state.", "metadata.state")
    if metadata.provenance not in PROVENANCES:
        error("unsupported_provenance", "Expected mock or external provenance.", "metadata.provenance")
    if source.available:
        match = _REFERENCE.fullmatch(source.output_reference)
        if match is None:
            error("invalid_output_reference", "Expected mock:<id> or external:<id> using ASCII letters, digits, . _ -.",
                  "output_reference")
        elif match.group(1) != metadata.provenance:
            error("provenance_mismatch", "Reference prefix and declared provenance disagree.", "metadata.provenance")
    return tuple(errors)
