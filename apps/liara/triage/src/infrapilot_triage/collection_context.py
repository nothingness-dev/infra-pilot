"""Local compatibility proposal for Provider PR #12, NOT an approved contract.

Validation establishes shape/consistency only. It never authenticates a mapping,
retains a producer reference, authorizes an action, or installs an HTTP route.
Only the explicit MOCK preview calls diagnosis; the production entry fails closed.
"""

from datetime import datetime
import hashlib
import json
from typing import Annotated, Literal, NoReturn, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator, model_validator

from .engine import diagnose
from .policy import ServiceIdentifier
from .redaction import sanitize_snapshot
from .schemas import DataSource, DiagnosisReport, ServiceSnapshot


PROVIDER_CONTEXT_VERSION = "provider-collection-context/0.2-draft"
CONTEXTUAL_DIAGNOSIS_VERSION = "triage-contextual-diagnosis/0.2-draft"
MAX_CONTEXT_BYTES = 4 * 1024 * 1024
Digest = Annotated[StrictStr, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Count = Annotated[StrictInt, Field(ge=0)]
Availability = Literal[
    "available", "unavailable", "not_collected", "permission_denied",
    "authentication_failed", "not_found", "failed", "unsupported", "unverified",
]
SafeErrorCode = Literal[
    "AUTHENTICATION_ERROR", "RATE_LIMITED", "TIMEOUT", "API_UNAVAILABLE",
    "RESOURCE_NOT_FOUND", "NETWORK_ERROR", "INVALID_RESPONSE", "INVALID_REQUEST",
    "PROVIDER_ERROR", "PARTIAL_COLLECTION", "COLLECTION_FAILED",
]
LimitationCode = Literal[
    "HEALTH_STATUS_UNVERIFIED", "APPLICATION_HTTP_NOT_MEASURED", "CPU_RAM_UNITS_UNVERIFIED",
    "SOURCE_TIMESTAMPS_UNVERIFIED", "LOG_WINDOW_COMPLETENESS_UNVERIFIED",
    "DEPLOYMENT_RELEASE_FIELDS_NOT_IN_DRAFT", "LOG_TEXT_WITHHELD",
    "LOG_EXPORT_INCOMPLETE", "LOG_TIME_AND_LEVEL_UNVERIFIED",
]


class ContextCompatibilityError(ValueError):
    """Safe codes/messages only; never include submitted values or validators."""
    def __init__(self, code: Literal[
        "invalid_collection_context", "unsupported_context_version", "untrusted_service_mapping",
        "mock_opt_in_required", "real_preview_disabled", "sanitization_order_conflict", "unreviewed_mock_logs",
    ] = "invalid_collection_context") -> None:
        self.code = code
        super().__init__(code)


def canonical_context_json(payload: dict) -> bytes:
    """Provider's documented finite ASCII JSON encoding; bounded to its 4 MiB."""
    if type(payload) is not dict:
        raise ContextCompatibilityError()
    chunks: list[str] = []
    size = 0
    try:
        for chunk in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).iterencode(payload):
            size += len(chunk)
            if size > MAX_CONTEXT_BYTES:
                raise ContextCompatibilityError()
            chunks.append(chunk)
        return "".join(chunks).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ContextCompatibilityError() from None


def context_digest(payload: dict) -> str:
    """Consistency aid only: neither a signature nor proof of service identity."""
    return "sha256:" + hashlib.sha256(canonical_context_json(payload)).hexdigest()


def _instant(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Aware collector instant required")
    return moment


class _DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityContext(_DraftModel):
    capability: Literal["service", "deployment", "logs", "metrics"]
    availability: Availability
    error_code: SafeErrorCode | None
    http_status: Annotated[StrictInt, Field(ge=100, le=599)] | None
    collected_at: StrictStr | None
    retryable: StrictBool | None

    @field_validator("collected_at")
    @classmethod
    def aware_time(cls, value: str | None) -> str | None:
        if value is not None:
            _instant(value)
        return value  # Preserve original JSON spelling, including +00:00 vs Z.

    @model_validator(mode="after")
    def safe_failure_semantics(self) -> Self:
        if self.error_code is None and (self.http_status is not None or self.retryable is not None):
            raise ValueError("Error metadata requires its authoritative capability error")
        if self.availability in ("available", "not_collected") and self.error_code is not None:
            raise ValueError("Contradictory capability outcome")
        expected = {"authentication_failed": 401, "permission_denied": 403, "not_found": 404}
        if self.availability in expected and (self.error_code is None or self.http_status != expected[self.availability]):
            raise ValueError("Contradictory HTTP collection outcome")
        return self


class LogExportContext(_DraftModel):
    state: Literal["empty", "withheld", "partial", "exported", "not_collected", "unavailable",
                   "collection_failed", "unsupported", "unverified"]
    received: Count | None
    exported: Count
    withheld: Count


class ProviderCollectionContext(_DraftModel):
    contract_version: Literal["provider-collection-context/0.2-draft"]
    service_id: ServiceIdentifier
    data_source: DataSource
    snapshot_digest: Digest
    collection_started_at: StrictStr | None
    collection_finished_at: StrictStr | None
    capabilities: Annotated[tuple[CapabilityContext, ...], Field(min_length=4, max_length=4)]
    log_export: LogExportContext
    limitations: tuple[LimitationCode, ...]

    @field_validator("collection_started_at", "collection_finished_at")
    @classmethod
    def aware_time(cls, value: str | None) -> str | None:
        if value is not None:
            _instant(value)
        return value

    @model_validator(mode="after")
    def ordered_collection(self) -> Self:
        if tuple(item.capability for item in self.capabilities) != ("service", "deployment", "logs", "metrics"):
            raise ValueError("Require the four ordered Provider capabilities")
        if self.collection_started_at is not None and self.collection_finished_at is not None:
            lower, upper = _instant(self.collection_started_at), _instant(self.collection_finished_at)
            if lower > upper or any(item.collected_at is not None and not lower <= _instant(item.collected_at) <= upper
                                    for item in self.capabilities):
                raise ValueError("Contradictory collector times")
        return self

    @property
    def collection_errors(self) -> tuple[CapabilityContext, ...]:
        """Derived immutable view; not another stored/serialized error collection."""
        return tuple(item for item in self.capabilities if item.error_code is not None)


class ProviderContextEnvelope(_DraftModel):
    snapshot: ServiceSnapshot
    collection_context: ProviderCollectionContext

    @model_validator(mode="after")
    def snapshot_consistency(self) -> Self:
        snapshot, context = self.snapshot, self.collection_context
        if snapshot.service_id != context.service_id or snapshot.data_source != context.data_source:
            raise ValueError("Snapshot/context target or source mismatch")
        if context_digest(snapshot.model_dump(mode="json")) != context.snapshot_digest:
            raise ValueError("Snapshot digest mismatch")
        if snapshot.status.value != "unknown" or any(getattr(snapshot, field) is not None for field in (
            "cpu_usage_percent", "ram_usage_mib", "http_status", "response_time_ms", "timestamp",
        )):
            raise ValueError("This pinned Provider draft does not establish those observations")
        if snapshot.logs and any(entry.level.value != "unknown" or entry.timestamp is not None for entry in snapshot.logs):
            raise ValueError("This Provider draft has not verified log levels or source times")
        logs, export, capability = snapshot.logs, context.log_export, context.capabilities[2]
        if capability.availability == "available":
            if export.received is None or export.received != export.exported + export.withheld:
                raise ValueError("Log source/export accounting mismatch")
            state = "empty" if export.received == 0 else (
                "withheld" if export.exported == 0 else ("partial" if export.withheld else "exported")
            )
            if export.state != state or (state == "withheld" and logs is not None) or (
                state != "withheld" and (logs is None or len(logs) != export.exported)
            ):
                raise ValueError("Log disposition mismatch")
        else:
            expected = {"not_collected", "unavailable", "unsupported", "unverified"}
            state = capability.availability if capability.availability in expected else "collection_failed"
            if export.state != state or logs is not None or export.received is not None or export.exported or export.withheld:
                raise ValueError("Unavailable logs cannot become collected-empty")
        sanitized, changed = sanitize_snapshot(snapshot)
        if changed or sanitized.model_dump(mode="json") != snapshot.model_dump(mode="json"):
            raise ValueError("Sanitize recognizable credentials before binding")
        return self


class ContextCorrelation(_DraftModel):
    """Untrusted lookup claims until independently resolved by trusted backend."""
    service_id: ServiceIdentifier
    service_binding_ref: ServiceIdentifier
    collection_ref: ServiceIdentifier
    snapshot_digest: Digest
    collection_context_digest: Digest


class DraftContextualDiagnosisRequest(ProviderContextEnvelope):
    correlation: ContextCorrelation

    @model_validator(mode="after")
    def correlation_consistency(self) -> Self:
        if (self.correlation.service_id != self.snapshot.service_id
                or self.correlation.snapshot_digest != self.collection_context.snapshot_digest
                or self.correlation.collection_context_digest != context_digest(self.collection_context.model_dump(mode="json"))):
            raise ValueError("Correlation claims disagree with the submitted envelope")
        return self


class DraftContextualDiagnosisResponse(_DraftModel):
    """Actual offline preview shape; not a live HTTP success or trust receipt."""
    contract_version: Literal["triage-contextual-diagnosis/0.2-draft"] = CONTEXTUAL_DIAGNOSIS_VERSION
    integration_status: Literal["mock_preview_only"] = "mock_preview_only"
    diagnosis_report: DiagnosisReport
    collection_context: ProviderCollectionContext
    correlation: ContextCorrelation
    trusted_mapping_verified: Literal[False] = False
    provenance_verified: Literal[False] = False
    authorization_granted: Literal[False] = False
    execution_performed: Literal[False] = False
    limitations: tuple[str, ...] = (
        "INTERNAL DRAFT proposal; no contextual HTTP route or approved shared contract exists.",
        "MOCK-only preview. Caller IDs/digests do not verify service/project identity or retained collection association.",
        "Trusted backend resolution, retained full-envelope verification and current Setup binding checks remain unavailable here.",
    )

    @model_validator(mode="after")
    def mock_response_consistency(self) -> Self:
        if (self.diagnosis_report.data_source != DataSource.MOCK
                or self.collection_context.data_source != DataSource.MOCK
                or self.diagnosis_report.service_id != self.collection_context.service_id
                or self.correlation.service_id != self.collection_context.service_id
                or self.correlation.snapshot_digest != self.collection_context.snapshot_digest
                or self.correlation.collection_context_digest != context_digest(self.collection_context.model_dump(mode="json"))):
            raise ValueError("Inconsistent MOCK preview response")
        return self


_Envelope = TypeVar("_Envelope", bound=ProviderContextEnvelope)


def _validated(payload: object, model: type[_Envelope]) -> _Envelope:
    try:
        raw = json.loads(canonical_context_json(payload))
        context = raw.get("collection_context")
        if isinstance(context, dict) and context.get("contract_version") not in (None, PROVIDER_CONTEXT_VERSION):
            raise ContextCompatibilityError("unsupported_context_version")
        return model.model_validate(raw)
    except ContextCompatibilityError:
        raise
    except (ValidationError, TypeError, ValueError, OverflowError, RecursionError):
        raise ContextCompatibilityError() from None


def validate_provider_context(payload: object) -> ProviderContextEnvelope:
    """Strict structural compatibility only. No mapping/provenance is verified."""
    return _validated(payload, ProviderContextEnvelope)


def validate_contextual_request(payload: object) -> DraftContextualDiagnosisRequest:
    """Validate the proposed request, never accepting correlation claims as proof."""
    return _validated(payload, DraftContextualDiagnosisRequest)


def diagnose_contextual_request(_payload: object) -> NoReturn:
    """Deliberately fail closed: no approved trust resolver is installed/implemented.

    There is no caller flag or supplied mapping that enables this entry. Review
    the proposed contract and implement real backend resolution before changing it.
    """
    raise ContextCompatibilityError("untrusted_service_mapping")


def preview_mock_contextual_diagnosis(payload: object, *, mock: bool = False) -> DraftContextualDiagnosisResponse:
    """Offline opt-in only; returns real engine output and the original context."""
    if mock is not True:
        raise ContextCompatibilityError("mock_opt_in_required")
    request = validate_contextual_request(payload)
    if request.snapshot.data_source != DataSource.MOCK:
        raise ContextCompatibilityError("real_preview_disabled")
    # This preview has only Provider's exact synthetic fixture log-review policy.
    # A submitted 'exported' label cannot approve arbitrary log bodies for output.
    if request.snapshot.logs and any(entry.message != "Synthetic application started" for entry in request.snapshot.logs):
        raise ContextCompatibilityError("unreviewed_mock_logs")
    return DraftContextualDiagnosisResponse(
        diagnosis_report=diagnose(request.snapshot), collection_context=request.collection_context,
        correlation=request.correlation,
    )
