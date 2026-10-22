"""Setup-owned association adapter for the published, unversioned triage models.

These imports require triage's documented Python/Pydantic environment. Legacy
Setup imports remain standard-library only. No provider is called here.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Literal

from infrapilot_triage import DiagnosisReport, ServiceSnapshot, diagnose
from pydantic import ValidationError

from .application import submit_request, supply_information
from .integration import (
    CONTRACT_VERSION, DependencyInput, request_fingerprint, validate_dependency_input,
)
from .models import Operation, OperationRequest, StructuredError
from .validation import validate_request


class SetupIntegrationError(ValueError):
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.error = StructuredError(code, message, field)


@dataclass(frozen=True)
class SnapshotEvidence:
    """Canonical payload plus Setup association, supplied by trusted orchestration.

    Metadata and source labels establish association only, not authenticity.
    Do not decode this internal object directly from frontend request fields.
    """

    snapshot: ServiceSnapshot
    association: DependencyInput


def _snapshot(request: OperationRequest, evidence: SnapshotEvidence) -> ServiceSnapshot:
    validated = validate_request(request)
    if not validated.is_complete:
        raise SetupIntegrationError("invalid_request", "Complete the valid Setup brief first.")
    if validated.operation != Operation.INSPECT_SERVICE.value:
        raise SetupIntegrationError(
            "unsupported_diagnosis_operation", "Diagnosis requires an existing inspect_service target."
        )
    if not isinstance(evidence, SnapshotEvidence) or not isinstance(evidence.association, DependencyInput):
        raise SetupIntegrationError("invalid_evidence", "Expected internally associated service evidence.")
    errors = validate_dependency_input(evidence.association, request, "provider")
    if errors:
        error = errors[0]
        raise SetupIntegrationError(error.code, error.message, error.field)
    if not evidence.association.available:
        raise SetupIntegrationError("evidence_unavailable", "Service observations are unavailable.")
    if not isinstance(evidence.snapshot, ServiceSnapshot):
        raise SetupIntegrationError("invalid_snapshot", "Expected the canonical ServiceSnapshot.")
    try:
        snapshot = ServiceSnapshot.model_validate(evidence.snapshot.model_dump(warnings=False))
    except ValidationError:
        raise SetupIntegrationError("invalid_snapshot", "ServiceSnapshot validation failed.") from None
    if snapshot.service_id != validated.collected_information["service_target"]:
        raise SetupIntegrationError("target_mismatch", "Snapshot target differs from the exact requested target.")
    expected_source = "mock" if evidence.association.metadata.provenance == "mock" else "real"
    if snapshot.data_source.value != expected_source:
        raise SetupIntegrationError("provenance_mismatch", "Snapshot and association sources disagree.")
    return snapshot


def _digest(request: OperationRequest, evidence: SnapshotEvidence, report: DiagnosisReport) -> str:
    data = {
        "request_fingerprint": request_fingerprint(request),
        "reference": evidence.association.output_reference,
        "metadata": asdict(evidence.association.metadata),
        "snapshot": evidence.snapshot.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class DiagnosisPresentation:
    request: OperationRequest
    evidence: SnapshotEvidence
    report: DiagnosisReport
    binding: str
    execution_performed: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict:
        validate_presentation(self.request, self)
        return {
            "contract_version": CONTRACT_VERSION,
            "request_id": self.request.request_id,
            "request_fingerprint": request_fingerprint(self.request),
            "binding": self.binding,
            "output_reference": self.evidence.association.output_reference,
            "association": asdict(self.evidence.association.metadata),
            "snapshot": self.evidence.snapshot.model_dump(mode="json"),
            "report": self.report.model_dump(mode="json"),
            "freshness_evaluated": False,
            "provenance_verified": False,
            "execution_performed": False,
            "execution_authorized": False,
        }


def consume_diagnosis(
    request: OperationRequest, evidence: SnapshotEvidence, report: DiagnosisReport,
) -> DiagnosisPresentation:
    """Bind an actual producer report retained by trusted backend orchestration."""
    snapshot = _snapshot(request, evidence)
    if not isinstance(report, DiagnosisReport):
        raise SetupIntegrationError("invalid_diagnosis", "Expected the canonical DiagnosisReport.")
    try:
        report = DiagnosisReport.model_validate(report.model_dump(warnings=False))
    except ValidationError:
        raise SetupIntegrationError("invalid_diagnosis", "DiagnosisReport validation failed.") from None
    current = OperationRequest(request.request_id, request.operation, dict(request.details))
    detached = SnapshotEvidence(snapshot, evidence.association)
    presentation = DiagnosisPresentation(current, detached, report, _digest(current, detached, report))
    validate_presentation(current, presentation)
    return presentation


def prepare_diagnosis(request: OperationRequest, evidence: SnapshotEvidence) -> DiagnosisPresentation:
    """Run the actual engine on supplied observations, retaining its complete report."""
    snapshot = _snapshot(request, evidence)
    return consume_diagnosis(request, evidence, diagnose(snapshot))


def validate_presentation(request: OperationRequest, presentation: DiagnosisPresentation) -> None:
    """Revalidate mutable canonical payloads and exact brief/snapshot/report binding.

    This digest is not a signature. Presentation objects stay in trusted backend
    code; a JSON presentation is never accepted as an approval or execution token.
    """
    if not isinstance(presentation, DiagnosisPresentation):
        raise SetupIntegrationError("invalid_diagnosis", "Expected a backend DiagnosisPresentation.")
    snapshot = _snapshot(request, presentation.evidence)
    if request_fingerprint(request) != request_fingerprint(presentation.request):
        raise SetupIntegrationError("request_mismatch", "Diagnosis belongs to a different brief.")
    try:
        report = DiagnosisReport.model_validate(presentation.report.model_dump(warnings=False))
    except (ValidationError, AttributeError):
        raise SetupIntegrationError("invalid_diagnosis", "DiagnosisReport validation failed.") from None
    if report.service_id != snapshot.service_id or report.data_source != snapshot.data_source:
        raise SetupIntegrationError("diagnosis_mismatch", "Report target or source differs from its snapshot.")
    if _digest(request, presentation.evidence, report) != presentation.binding:
        raise SetupIntegrationError("diagnosis_modified", "The retained diagnosis payload has changed.")


@dataclass(frozen=True)
class DiagnosisWorkflow:
    preparation: dict
    state: str
    diagnosis: DiagnosisPresentation | None = None
    errors: tuple[StructuredError, ...] = ()

    def to_dict(self) -> dict:
        # Roundtrip detaches the existing JSON application response.
        return {
            "request": json.loads(json.dumps(self.preparation["request"])),
            "preparation": json.loads(json.dumps(self.preparation)),
            "state": self.state,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "errors": [asdict(error) for error in self.errors],
            "execution_performed": False,
            "execution_authorized": False,
        }


def _present(preparation: dict, evidence: SnapshotEvidence | None) -> DiagnosisWorkflow:
    # The legacy reference-only workflow remains blocked without opaque provider
    # and triage references. It does not invalidate a complete, accepted brief.
    input_errors = any(error["code"] != "dependency_unavailable" for error in preparation["errors"])
    if input_errors or preparation["missing_information"] or preparation["request"] is None:
        return DiagnosisWorkflow(preparation, preparation["state"])
    if evidence is None:
        return DiagnosisWorkflow(preparation, "evidence_required", errors=(StructuredError(
            "evidence_required", "Supply an associated canonical ServiceSnapshot; no provider snapshot API is wired."
        ),))
    request = OperationRequest(**preparation["request"])
    try:
        diagnosis = prepare_diagnosis(request, evidence)
    except SetupIntegrationError as exc:
        return DiagnosisWorkflow(preparation, "blocked", errors=(exc.error,))
    return DiagnosisWorkflow(preparation, "diagnosis_presented", diagnosis)


def submit_problem(payload: object, *, evidence: SnapshotEvidence | None = None) -> DiagnosisWorkflow:
    """Reuse submit_request; diagnosis presentation does not promote its legacy plan."""
    return _present(submit_request(payload), evidence)


def supply_problem_information(
    request_payload: object, additional_information: object, *, evidence: SnapshotEvidence | None = None,
) -> DiagnosisWorkflow:
    return _present(supply_information(request_payload, additional_information), evidence)
