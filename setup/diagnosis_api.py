"""Consume the published triage API response; no API server or HTTP client here."""

from infrapilot_triage import DiagnosisReport
from infrapilot_triage.redaction import sanitize_snapshot
from pydantic import ValidationError

from .models import OperationRequest
from .triage import (
    DiagnosisPresentation, SetupIntegrationError, SnapshotEvidence, _snapshot, consume_diagnosis,
)


def consume_diagnosis_response(
    request: OperationRequest, evidence: SnapshotEvidence, *, status_code: int, payload: object,
) -> DiagnosisPresentation:
    """Trusted server response only, never a frontend-supplied report.

    The server orchestration layer calls the existing POST /internal/triage/diagnose
    and passes its decoded response here. An error is not a successful Diagnosis.
    No endpoint, transport, retry, route registration or provenance claim is added.
    """
    snapshot = _snapshot(request, evidence)
    if type(status_code) is not int or status_code != 200:
        raise SetupIntegrationError("diagnosis_api_error", "Diagnosis API did not return a successful report.")
    if not isinstance(payload, dict):
        raise SetupIntegrationError("invalid_diagnosis", "Diagnosis API returned an unusable report.")
    try:
        report = DiagnosisReport.model_validate(payload)
    except ValidationError:
        # Producer validation details can contain sensitive original values.
        raise SetupIntegrationError("invalid_diagnosis", "Diagnosis API returned an unusable report.") from None
    # Reuse the producer's exact sanitizer so UI presentation does not reintroduce
    # credentials from the original snapshot alongside the redacted API report.
    sanitized, _ = sanitize_snapshot(snapshot)
    return consume_diagnosis(request, SnapshotEvidence(sanitized, evidence.association), report)
