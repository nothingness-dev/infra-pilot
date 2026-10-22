"""Process-local Mock evidence retention. Output JSON cannot create a reference."""

from dataclasses import dataclass
import json

from infrapilot_triage.redaction import sanitize_snapshot
from infrapilot_triage.schemas import ServiceSnapshot
from provider import ServiceBinding
from provider.examples.context_fixtures import mock_context_binding
from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import SnapshotEvidence, prepare_diagnosis, validate_presentation

from .service import CompletedInspection


_CODES = {
    "REFERENCE_REQUIRED", "INVALID_EVIDENCE", "INVALID_REQUEST", "SERVICE_MISMATCH", "SCOPE_MISMATCH",
    "SOURCE_MISMATCH", "REQUEST_MISMATCH", "EVIDENCE_MODIFIED", "SEMANTICS_UNVERIFIED",
    "MOCK_OPT_IN_REQUIRED", "INVALID_SCENARIO", "INVALID_ACTION_REFERENCE", "ACTION_MISMATCH",
    "CLOCK_UNAVAILABLE", "DEPENDENCIES_UNAVAILABLE", "INVALID_ARGUMENTS", "UNEXPECTED_ERROR", "INTERRUPTED",
}
SEMANTICS = ("controlled-app-probe/1", "controlled-app-probe/2")
FIELDS = ("status", "http_status", "response_time_ms", "cpu_usage_percent", "ram_usage_mib")


class OutcomeError(ValueError):
    """Fixed diagnostics only; neither repr nor implicit chains contain input."""

    def __init__(self, code="UNEXPECTED_ERROR"):
        self.code = code if type(code) is str and code in _CODES else "UNEXPECTED_ERROR"
        super().__init__("Outcome evaluation could not proceed: " + self.code)
        self.__suppress_context__ = True


def canonical(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


class EvidenceRef:
    __slots__ = ()

    def __new__(cls):
        raise OutcomeError("REFERENCE_REQUIRED") from None

    def __repr__(self):
        return "EvidenceRef(mode='mock', contents='retained')"


@dataclass(repr=False)
class _Entry:
    reference: str
    kind: str
    binding: ServiceBinding
    request: OperationRequest
    presentation: object
    inspection: CompletedInspection | None
    original_snapshot: str
    context: dict | None
    semantics: str | None
    sequence: int


class EvidenceLedger:
    """Trusted fixture composition, not production identity or a public intake.

    Provider entries retain the actual producer objects. Controlled canonical
    entries use Setup's actual diagnosis/evidence binding, never PreparedCollection.
    The two source kinds cannot be silently mixed in a comparison.
    """

    def __init__(self, *, mock=False, request=None, binding=None):
        if mock is not True:
            raise OutcomeError("MOCK_OPT_IN_REQUIRED") from None
        try:
            self.binding = binding if binding is not None else mock_context_binding()
            request = request if request is not None else OperationRequest(
                "MOCK-workflow-request", "inspect_service", {
                    "service_target": "MOCK-service", "goal": "Review this synthetic service collection",
                },
            )
            if (type(self.binding) is not ServiceBinding or self.binding.is_mock is not True
                    or type(request) is not OperationRequest or request.operation != "inspect_service"
                    or request.details["service_target"] != self.binding.service_id):
                raise OutcomeError("INVALID_REQUEST")
            self.request = OperationRequest(request.request_id, request.operation, dict(request.details))
            self.fingerprint = request_fingerprint(self.request)
        except OutcomeError:
            raise
        except Exception:
            raise OutcomeError("INVALID_REQUEST") from None
        self._entries = {}
        self._sequence = 0

    def __repr__(self):
        return "EvidenceLedger(mode='mock')"

    def _retain(self, kind, binding, request, presentation, inspection, context, semantics):
        reference = object.__new__(EvidenceRef)
        snapshot = presentation.evidence.snapshot
        self._sequence += 1
        entry = _Entry("MOCK-evidence-" + str(self._sequence), kind, binding, request,
                       presentation, inspection, canonical(snapshot.model_dump(mode="json")), context, semantics, self._sequence)
        self._entries[reference] = entry
        try:
            self.check(reference)
        except Exception:
            del self._entries[reference]
            raise
        return reference

    def retain_provider(self, inspection: CompletedInspection) -> EvidenceRef:
        try:
            if type(inspection) is not CompletedInspection:
                raise OutcomeError("REFERENCE_REQUIRED")
            inspection.validate()
            if inspection.source_binding.service_id != self.binding.service_id:
                raise OutcomeError("SERVICE_MISMATCH")
            if inspection.source_binding.is_mock is not self.binding.is_mock:
                raise OutcomeError("SOURCE_MISMATCH")
            if inspection.source_binding != self.binding:
                raise OutcomeError("SCOPE_MISMATCH")
            envelope = inspection.prepared.verify_request(
                inspection.prepared.to_request(), expected_binding=self.binding,
            )
            return self._retain("provider_mock", inspection.source_binding, inspection.request,
                                inspection.presentation, inspection, envelope["collection_context"], None)
        except OutcomeError:
            raise
        except Exception:
            raise OutcomeError("EVIDENCE_MODIFIED") from None

    def retain_synthetic(self, snapshot: ServiceSnapshot, *, semantics=SEMANTICS[0], binding=None, request=None) -> EvidenceRef:
        """Backend-only canonical fixture input, not data claimed from Liara.

        Semantics 1/2 explicitly define independent controlled app-probe series
        with known %, MiB, ms units and source sample instants. Equal identifiers
        assert the same synthetic workload/probe definition; no live semantics
        are inferred from canonical field names or collector timestamps.
        """
        try:
            if type(snapshot) is not ServiceSnapshot:
                raise OutcomeError("INVALID_EVIDENCE")
            if type(semantics) is not str or semantics not in SEMANTICS:
                raise OutcomeError("SEMANTICS_UNVERIFIED")
            # Avoid Pydantic warning diagnostics echoing mutated field values.
            snapshot = ServiceSnapshot.model_validate(snapshot.model_dump(warnings=False))
            snapshot, _ = sanitize_snapshot(snapshot)
            if snapshot.data_source.value != "mock":
                raise OutcomeError("SOURCE_MISMATCH")
            actual_request = request if request is not None else self.request
            actual_binding = binding if binding is not None else self.binding
            if snapshot.service_id != self.binding.service_id:
                raise OutcomeError("SERVICE_MISMATCH")
            if actual_binding != self.binding:
                raise OutcomeError("SCOPE_MISMATCH")
            if request_fingerprint(actual_request) != self.fingerprint:
                raise OutcomeError("REQUEST_MISMATCH")
            metadata = ResultMetadata(CONTRACT_VERSION, actual_request.request_id, actual_request.operation,
                                      self.fingerprint, "provider", "ready", "mock")
            evidence = SnapshotEvidence(snapshot, DependencyInput(True, "mock:controlled-canonical", metadata=metadata))
            presentation = prepare_diagnosis(actual_request, evidence)
            return self._retain("controlled_canonical", actual_binding, presentation.request,
                                presentation, None, None, semantics)
        except OutcomeError:
            raise
        except Exception:
            raise OutcomeError("INVALID_EVIDENCE") from None

    def check(self, reference: EvidenceRef) -> _Entry:
        try:
            if type(reference) is not EvidenceRef or reference not in self._entries:
                raise OutcomeError("REFERENCE_REQUIRED")
            entry = self._entries[reference]
            if request_fingerprint(self.request) != self.fingerprint or request_fingerprint(entry.request) != self.fingerprint:
                raise OutcomeError("REQUEST_MISMATCH")
            if entry.binding.service_id != self.binding.service_id:
                raise OutcomeError("SERVICE_MISMATCH")
            if entry.binding != self.binding:
                raise OutcomeError("SCOPE_MISMATCH")
            snapshot = entry.presentation.evidence.snapshot
            if snapshot.service_id != self.binding.service_id:
                raise OutcomeError("SERVICE_MISMATCH")
            if snapshot.data_source.value != "mock" or entry.binding.is_mock is not True:
                raise OutcomeError("SOURCE_MISMATCH")
            validate_presentation(entry.request, entry.presentation)
            if canonical(snapshot.model_dump(mode="json")) != entry.original_snapshot:
                raise OutcomeError("EVIDENCE_MODIFIED")
            if entry.inspection is not None:
                entry.inspection.validate()
                original = entry.inspection.prepared.verify_request(
                    entry.inspection.prepared.to_request(), expected_binding=self.binding,
                )
                if original["collection_context"] != entry.context or original["snapshot"] != snapshot.model_dump(mode="json"):
                    raise OutcomeError("EVIDENCE_MODIFIED")
            return entry
        except OutcomeError:
            raise
        except Exception:
            raise OutcomeError("EVIDENCE_MODIFIED") from None

    def summary(self, reference: EvidenceRef) -> dict:
        entry = self.check(reference)
        snapshot = entry.presentation.evidence.snapshot.model_dump(mode="json")
        context = entry.context
        # Never export raw logs, diagnosis prose, input IDs or private scopes.
        return json.loads(canonical({
            "reference": entry.reference, "source_kind": entry.kind, "data_source": "mock",
            "request_fingerprint": self.fingerprint, "diagnosis_binding": entry.presentation.binding,
            "measurement_semantics": entry.semantics,
            "measurements": {field: snapshot[field] for field in FIELDS},
            "observation_timestamp": snapshot["timestamp"],
            "collection_context": context,
            "logs": (context["log_export"] if context else {
                "state": "unavailable" if snapshot["logs"] is None else ("empty" if not snapshot["logs"] else "present_not_compared"),
                "received": None if snapshot["logs"] is None else len(snapshot["logs"]),
            }),
            "diagnosis_limitations": list(entry.presentation.report.limitations),
            "provenance_verified": False, "source_freshness_verified": False,
        }))
