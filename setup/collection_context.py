"""Opt-in Setup companion for Provider's exact draft context; no execution path.

These normal producer imports require the reviewed Provider/Triage packages in
server composition. No checkout path or test fixture is a runtime dependency.
Only backend-retained objects may enter this boundary; none is a JSON credential.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Literal

from infrapilot_triage.redaction import sanitize_snapshot
from provider.collection_context import (
    MAX_COLLECTION_CONTEXT_BYTES, PreparedCollection, ServiceBinding,
)
from provider.exceptions import CollectionContextError

from .integration import request_fingerprint
from .models import OperationRequest, StructuredError
from .approval_workflow import execution_readiness
from .triage import (
    DiagnosisPresentation, SetupIntegrationError, SnapshotEvidence, _snapshot, validate_presentation,
)


COMPANION_VERSION = "setup-collection-companion/1-proposal"
SUPPORTED_PROVIDER_CONTEXT_VERSION = "provider-collection-context/0.2-draft"


def _fail(code: str, message: str) -> None:
    raise SetupIntegrationError(code, message) from None


def _request_fingerprint(request: OperationRequest) -> str:
    try:
        return request_fingerprint(request)
    except (TypeError, ValueError, AttributeError):
        _fail("invalid_request", "Supply the current complete backend Setup brief.")


def _canonical(value: dict) -> bytes:
    """Same documented encoding; separate, bounded Setup companion hash domain."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    chunks, size = [], 0
    try:
        for chunk in encoder.iterencode(value):
            size += len(chunk)
            if size > MAX_COLLECTION_CONTEXT_BYTES:
                _fail("companion_too_large", "The proposed companion exceeds its local JSON limit.")
            chunks.append(chunk)
        return "".join(chunks).encode("ascii")
    except SetupIntegrationError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid_collection_context", "Collection context cannot be associated safely.")


def _sha(value: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _checked_export(request, evidence, prepared, expected_binding) -> tuple[dict, SnapshotEvidence]:
    if type(prepared) is not PreparedCollection or type(expected_binding) is not ServiceBinding:
        _fail("producer_reference_required", "Retain the producer reference and resolve its binding in backend state.")
    snapshot = _snapshot(request, evidence)
    try:
        envelope = prepared.verify_request(prepared.to_request(), expected_binding=expected_binding)
    except (CollectionContextError, TypeError, ValueError, AttributeError):
        _fail("provider_binding_mismatch", "The retained Provider reference does not match the backend service binding.")
    context = envelope["collection_context"]
    if context["contract_version"] != SUPPORTED_PROVIDER_CONTEXT_VERSION:
        _fail("unsupported_collection_contract", "Collection context version requires a new team agreement.")
    if (snapshot.service_id != context["service_id"] or snapshot.service_id != expected_binding.service_id
            or snapshot.data_source.value != context["data_source"]
            or expected_binding.is_mock != (context["data_source"] == "mock")):
        _fail("context_source_mismatch", "Context, service evidence and backend binding disagree.")
    if _canonical(snapshot.model_dump(mode="json")) != _canonical(envelope["snapshot"]):
        _fail("context_snapshot_mismatch", "Context does not describe the retained snapshot evidence.")
    # Producer's digest covers its policy-reviewed export, not raw observations.
    if context["snapshot_digest"] != _sha(envelope["snapshot"]):
        _fail("provider_digest_mismatch", "The exported snapshot is not covered by its stated Provider digest.")
    sanitized, changed = sanitize_snapshot(snapshot)
    if changed or _canonical(sanitized.model_dump(mode="json")) != _canonical(envelope["snapshot"]):
        _fail("sanitization_order_conflict", "Sanitize at the producer boundary before exporting and binding context.")
    # No hash or display is built over a second, differently sanitized payload.
    return envelope, SnapshotEvidence(sanitized, evidence.association)


def _binding(request, evidence, envelope, diagnosis) -> str:
    return _sha({
        "contract_version": COMPANION_VERSION,
        "request_fingerprint": _request_fingerprint(request),
        "source_evidence": asdict(evidence.association),
        "provider_envelope": envelope,
        "diagnosis_binding": diagnosis.binding if diagnosis else None,
    })


def _display(context: dict) -> dict:
    logs = next(item for item in context["capabilities"] if item["capability"] == "logs")
    export = context["log_export"]
    states = {
        "empty": "collected_empty", "unavailable": "data_unavailable",
        "not_collected": "not_collected", "collection_failed": "collection_failed",
        "withheld": "deliberately_withheld", "partial": "partially_exported", "exported": "exported",
        "unsupported": "unsupported", "unverified": "unverified",
    }
    return {
        "source_claim": context["data_source"],
        "collection_state": "partial_failure" if any(item["error_code"] for item in context["capabilities"]) else "no_component_error_reported",
        "logs": {**export, "display_state": states.get(export["state"], "unknown"),
                 "availability": logs["availability"]},
        # A single derived view, not a second independently mutable error store.
        "collection_errors": [dict(item) for item in context["capabilities"] if item["error_code"] is not None],
        "provenance_verified": False, "freshness_evaluated": False,
        "sanitizer_policy_revision": None,
    }


@dataclass(frozen=True, init=False)
class CollectionCompanion:
    """Server-retained companion, never reconstructed from client metadata.

    Payloads are revalidated before display/Diagnosis use. The original Provider
    reference also binds private project/scope; neither is exported to the UI.
    All digests are consistency aids, not authenticity or authorization proofs.
    """

    _request: OperationRequest = field(repr=False)
    evidence: SnapshotEvidence = field(repr=False)
    _prepared: PreparedCollection = field(repr=False)
    _service_binding: ServiceBinding = field(repr=False)
    _envelope_bytes: bytes = field(repr=False)
    diagnosis: DiagnosisPresentation | None = field(repr=False)
    binding: str

    def __new__(cls):
        _fail("backend_companion_required", "Use the trusted Setup companion boundary, not submitted metadata.")

    def to_dict(self) -> dict:
        envelope = _validate_companion(self._request, self)
        context = envelope["collection_context"]
        return {
            "contract_version": COMPANION_VERSION,
            "state": "diagnosis_associated" if self.diagnosis else "context_preserved",
            "request_id": self._request.request_id,
            "request_fingerprint": _request_fingerprint(self._request),
            "source_evidence": {"output_reference": self.evidence.association.output_reference,
                                "association": asdict(self.evidence.association.metadata)},
            "snapshot": envelope["snapshot"], "collection_context": context,
            "companion_binding": self.binding,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "display": _display(context),
            "production_readiness": "unresolved", "authorization_consumed": False,
            "execution": execution_readiness(),
            "execution_authorized": False, "execution_performed": False,
        }


def _validate_companion(request, companion) -> dict:
    if type(companion) is not CollectionCompanion:
        _fail("backend_companion_required", "Resolve the companion from retained backend state.")
    if _request_fingerprint(request) != _request_fingerprint(companion._request):
        _fail("context_request_mismatch", "Collection companion belongs to another complete Setup brief.")
    envelope, evidence = _checked_export(request, companion.evidence, companion._prepared, companion._service_binding)
    if _canonical(envelope) != companion._envelope_bytes:
        _fail("collection_context_modified", "The retained collection context changed.")
    if companion.diagnosis is not None:
        validate_presentation(request, companion.diagnosis)
        if (_canonical(companion.diagnosis.evidence.snapshot.model_dump(mode="json")) != _canonical(envelope["snapshot"])
                or companion.diagnosis.evidence.association != evidence.association):
            _fail("context_diagnosis_mismatch", "Diagnosis does not describe this snapshot and source evidence.")
    if companion.binding != _binding(request, evidence, envelope, companion.diagnosis):
        _fail("collection_context_modified", "The retained companion association changed.")
    return envelope


def _make_companion(request, evidence, prepared, service_binding, envelope, diagnosis=None):
    current = OperationRequest(request.request_id, request.operation, dict(request.details))
    result = object.__new__(CollectionCompanion)
    for key, value in {
        "_request": current, "evidence": evidence, "_prepared": prepared,
        "_service_binding": service_binding, "_envelope_bytes": _canonical(envelope),
        "diagnosis": diagnosis, "binding": _binding(current, evidence, envelope, diagnosis),
    }.items():
        object.__setattr__(result, key, value)
    _validate_companion(current, result)
    return result


@dataclass(frozen=True)
class CollectionContextOutcome:
    state: Literal["context_preserved", "diagnosis_associated", "blocked", "unresolved"]
    companion: CollectionCompanion | None = field(default=None, repr=False)
    errors: tuple[StructuredError, ...] = ()

    def to_dict(self) -> dict:
        try:
            data = self.companion.to_dict() if self.companion else None
        except SetupIntegrationError as error:
            return _rejected(error).to_dict()
        return {"state": self.state, "companion": data, "errors": [asdict(error) for error in self.errors],
                "authorization_consumed": False, "execution_authorized": False, "execution_performed": False}


def _rejected(error: SetupIntegrationError) -> CollectionContextOutcome:
    state = "unresolved" if error.error.code == "producer_reference_required" else "blocked"
    return CollectionContextOutcome(state, errors=(error.error,))


def preserve_collection_context(
    request: OperationRequest, evidence: SnapshotEvidence, *,
    prepared: PreparedCollection | None = None, expected_binding: ServiceBinding | None = None,
) -> CollectionContextOutcome:
    """Trusted orchestration only; a client envelope cannot create provenance."""
    try:
        envelope, sanitized = _checked_export(request, evidence, prepared, expected_binding)
        companion = _make_companion(request, sanitized, prepared, expected_binding, envelope)
        return CollectionContextOutcome("context_preserved", companion)
    except SetupIntegrationError as error:
        return _rejected(error)


def attach_collection_diagnosis(
    request: OperationRequest, companion: CollectionCompanion, presentation: DiagnosisPresentation,
) -> CollectionContextOutcome:
    """Associate an existing Diagnosis; neither mutate it nor reinterpret approval."""
    try:
        envelope = _validate_companion(request, companion)
        # _make_companion validates the existing binding, snapshot, source and
        # current request again before exposing the new companion association.
        attached = _make_companion(request, companion.evidence, companion._prepared,
                                   companion._service_binding, envelope, presentation)
        return CollectionContextOutcome("diagnosis_associated", attached)
    except SetupIntegrationError as error:
        return _rejected(error)


def consume_collection_diagnosis_response(
    request: OperationRequest, companion: CollectionCompanion, *, status_code: int, payload: object,
) -> CollectionContextOutcome:
    """Reuse the published Setup API consumer with retained backend evidence only.

    The current HTTP endpoint accepts just the snapshot. Transport and session
    validation remain with trusted orchestration; this function makes no call.
    """
    from .diagnosis_api import consume_diagnosis_response

    try:
        _validate_companion(request, companion)
        presentation = consume_diagnosis_response(request, companion.evidence,
                                                status_code=status_code, payload=payload)
        return attach_collection_diagnosis(request, companion, presentation)
    except SetupIntegrationError as error:
        return _rejected(error)
