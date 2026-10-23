"""Local, explicit read-only composition. This is not a production API route.

Trusted Python consumers retain these objects; never deserialize them from a
caller. Only summary() is suitable for CLI export. No approval code is invoked.
"""

from dataclasses import dataclass
from uuid import uuid4

from infrapilot_triage import engine
from infrapilot_triage.collection_context import validate_provider_context
from infrapilot_triage.schemas import DiagnosisReport, ServiceSnapshot
from provider import CollectionContextAdapter, LiaraClient, PreparedCollection, ProviderResult, ServiceBinding
from setup.collection_context import CollectionCompanion, attach_collection_diagnosis, preserve_collection_context
from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import DiagnosisPresentation, SnapshotEvidence, consume_diagnosis
from setup.validation import validate_request

from .composition import validate_retained_inspection
from .readonly_config import read_inspection_settings
from .readonly_report import LIMITATIONS, ReadOnlyError, empty_summary


@dataclass(frozen=True, repr=False)
class ReadOnlyInspection:
    """Retained evidence, including valid earlier stages after a later failure."""

    request: OperationRequest
    binding: ServiceBinding
    stage: str
    error_code: str | None = None
    prepared: PreparedCollection | None = None
    companion: CollectionCompanion | None = None
    presentation: DiagnosisPresentation | None = None

    def __repr__(self):
        return "ReadOnlyInspection(source='real', contents='retained')"

    def _envelope(self, submitted_envelope=None):
        if type(self.prepared) is not PreparedCollection or type(self.binding) is not ServiceBinding or self.binding.is_mock is not False:
            raise ReadOnlyError("CONTEXT_REJECTED") from None
        request = validate_request(self.request)
        if (not request.is_complete or request.operation != "inspect_service"
                or request.collected_information["service_target"] != self.binding.service_id):
            raise ReadOnlyError("CONTEXT_REJECTED") from None
        envelope = self.prepared.verify_request(
            self.prepared.to_request() if submitted_envelope is None else submitted_envelope,
            expected_binding=self.binding,
        )
        validated = validate_provider_context(envelope)
        if validated.snapshot.data_source.value != "real":
            raise ReadOnlyError("CONTEXT_REJECTED") from None
        # This path never opts into exporting live text, even if a replaced
        # producer accidentally supplies an otherwise valid exported snapshot.
        if envelope["snapshot"]["logs"] not in (None, []) or envelope["collection_context"]["log_export"]["exported"] != 0:
            raise ReadOnlyError("CONTEXT_REJECTED") from None
        return envelope

    def validate(self):
        """Recheck mutable downstream payloads before trusted reuse or summary."""
        try:
            envelope = self._envelope()
            if self.companion is not None:
                view = validate_retained_inspection(
                    self.request, self.prepared, self.binding, self.companion, self.presentation,
                )
                if self.stage == "complete" and (self.presentation is None or view["diagnosis"] is None):
                    raise ValueError()
            elif self.presentation is not None or self.stage == "complete":
                raise ValueError()
            return envelope
        except Exception:
            raise ReadOnlyError("EVIDENCE_MODIFIED") from None

    def summary(self):
        """Allowlisted data-free JSON; never serialize raw reports or identifiers."""
        if self.prepared is None:
            return empty_summary(error=self.error_code, stage="collection")
        try:
            envelope = self.validate()
        except Exception:
            return empty_summary(error="EVIDENCE_MODIFIED", stage="validation")
        context = envelope["collection_context"]
        attempted = [item for item in context["capabilities"] if item["availability"] != "not_collected"]
        count = sum(item["availability"] == "available" for item in attempted)
        outcome = "complete" if count == len(attempted) and attempted else "partial" if count else "failed"
        code = (0 if outcome == "complete" else 1 if outcome == "partial" else 2) if self.error_code is None else 2
        if self.error_code == "INTERRUPTED":
            code = 130
        report = empty_summary(code=code, stage=self.stage, error=self.error_code)
        report.update(status=outcome if self.error_code is None else "failed", collection_outcome=outcome,
                      error_code=self.error_code if self.error_code is None else report["error_code"])
        report["capabilities"] = [
            {key: item[key] for key in ("capability", "availability", "error_code", "http_status", "retryable")}
            for item in context["capabilities"]
        ]
        report["logs"] = dict(context["log_export"])
        report["limitations"] = [item for item in context["limitations"] if item in LIMITATIONS]
        if self.presentation is not None:
            diagnosis = self.presentation.report
            report["diagnosis"] = {
                "available": True, "associated": self.companion.diagnosis is not None,
                "counts": {key: len(getattr(diagnosis, key)) for key in
                           ("evidence", "hypotheses", "actions", "missing_information", "limitations")},
            }
        return report


def inspect_prepared(request: OperationRequest, prepared: PreparedCollection, *, expected_binding: ServiceBinding,
                     submitted_envelope: dict | None = None) -> ReadOnlyInspection:
    """Pure collection continuation; requires the original independent binding.

    No network, Mock preview, production contextual entry, or gate is used here.
    """
    stage, companion, presentation = "context", None, None
    try:
        current = OperationRequest(request.request_id, request.operation, dict(request.details))
        retained = ReadOnlyInspection(current, expected_binding, stage, prepared=prepared)
        envelope = retained._envelope(submitted_envelope)
        metadata = ResultMetadata(CONTRACT_VERSION, current.request_id, current.operation,
                                  request_fingerprint(current), "provider", "ready", "external")
        evidence = SnapshotEvidence(ServiceSnapshot.model_validate(envelope["snapshot"]),
                                    DependencyInput(True, "external:readonly-" + uuid4().hex, metadata=metadata))
        preserved = preserve_collection_context(current, evidence, prepared=prepared, expected_binding=expected_binding)
        if preserved.state != "context_preserved" or preserved.companion is None:
            raise ReadOnlyError("CONTEXT_REJECTED")
        companion = preserved.companion
        stage = "diagnosis"
        # An independent copy prevents a faulty engine from changing the
        # preserved canonical evidence before association checks run.
        report = engine.diagnose(ServiceSnapshot.model_validate(envelope["snapshot"]))
        if not isinstance(report, DiagnosisReport):
            raise ReadOnlyError("DIAGNOSIS_FAILED")
        report = DiagnosisReport.model_validate(report.model_dump(warnings=False))
        original_report = report.model_dump(mode="json")
        stage = "association"
        candidate = consume_diagnosis(current, companion.evidence, report)
        validate_retained_inspection(current, prepared, expected_binding, companion, candidate)
        if candidate.to_dict()["report"] != original_report:
            raise ReadOnlyError("ASSOCIATION_FAILED")
        presentation = candidate
        attached = attach_collection_diagnosis(current, companion, presentation)
        if attached.state != "diagnosis_associated" or attached.companion is None:
            raise ReadOnlyError("ASSOCIATION_FAILED")
        view = validate_retained_inspection(current, prepared, expected_binding, attached.companion, presentation)
        if view["diagnosis"]["report"] != original_report:
            raise ReadOnlyError("ASSOCIATION_FAILED")
        result = ReadOnlyInspection(current, expected_binding, "complete", prepared=prepared,
                                    companion=attached.companion, presentation=presentation)
        result.validate()
        return result
    except KeyboardInterrupt:
        return ReadOnlyInspection(request, expected_binding, stage, "INTERRUPTED", prepared, companion, presentation)
    except Exception:
        error = {"context": "CONTEXT_REJECTED", "diagnosis": "DIAGNOSIS_FAILED", "association": "ASSOCIATION_FAILED"}[stage]
        return ReadOnlyInspection(request, expected_binding, stage, error, prepared, companion, presentation)


def _inspection_request(expected):
    return OperationRequest("readonly-" + uuid4().hex, "inspect_service", {
        "service_target": expected.service_id, "goal": "Inspect supplied read-only observations",
    })


def inspect_with_client(client, settings) -> ReadOnlyInspection:
    """Trusted composition continuation using the same validated live transport.

    Callers own opt-in/configuration. No second client or diagnosis is created.
    This is not a JSON/public intake or an authenticated ownership assertion.
    """
    expected = settings.binding
    request = _inspection_request(expected)
    try:
        if client.config is not settings.live.config or client.config.is_mock is not False:
            raise ValueError()
        adapter = CollectionContextAdapter(client, provider_scope=expected.provider_scope)
        collected = adapter.collect(expected, logs_since=settings.live.logs_since)
        if (not isinstance(collected, ProviderResult) or collected.is_mock is not False
                or type(collected.data) is not PreparedCollection):
            return ReadOnlyInspection(request, expected, "collection", "COLLECTION_FAILED")
        return inspect_prepared(request, collected.data, expected_binding=expected)
    except KeyboardInterrupt:
        raise
    except Exception:
        return ReadOnlyInspection(request, expected, "collection", "COLLECTION_FAILED")


def run_readonly_inspection(*, live_read_only=False, environment=None) -> ReadOnlyInspection:
    """Explicit operator-local entry point; credentials are process-env only.

    An injected mapping is for trusted embedding/testing, never HTTP input.
    All configuration validates before the real client's constructor or I/O.
    """
    if live_read_only is not True:
        raise ReadOnlyError("LIVE_OPT_IN_REQUIRED") from None
    if environment is None:
        import os
        environment = os.environ
    settings = read_inspection_settings(environment)
    try:
        client = LiaraClient(settings.live.config)
        return inspect_with_client(client, settings)
    except KeyboardInterrupt:
        raise
    except Exception:
        return ReadOnlyInspection(_inspection_request(settings.binding), settings.binding, "collection", "COLLECTION_FAILED")
