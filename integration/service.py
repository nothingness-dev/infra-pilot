"""Thin, in-process Mock profile over the actual three component implementations.

No HTTP transport, live configuration, approval operation or infrastructure tool.
Retained objects live only for this mock session; no real trust is asserted.
"""

from dataclasses import dataclass, field
import json
from types import MappingProxyType

from infrapilot_triage.collection_context import (
    ContextCompatibilityError, context_digest, preview_mock_contextual_diagnosis,
    validate_provider_context,
)
from infrapilot_triage.schemas import ServiceSnapshot
from provider import CollectionContextError, PreparedCollection, ServiceBinding
from provider.examples.context_fixtures import MOCK_CONTEXT_SCENARIOS, build_mock_context
from setup.collection_context import CollectionCompanion, attach_collection_diagnosis, preserve_collection_context
from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import DiagnosisPresentation, SetupIntegrationError, SnapshotEvidence, consume_diagnosis, validate_presentation
from setup.validation import validate_request

from .errors import MockIntegrationError


INTEGRATION_PROFILE = "infrapilot-mock-backend/1"
SCENARIOS = MOCK_CONTEXT_SCENARIOS
# Backend-owned fixture configuration. These values never come from an envelope.
_SERVICES = MappingProxyType({
    "MOCK-service": ServiceBinding("MOCK-service", "mock-project", "mock-account", True),
})


@dataclass(frozen=True)
class MockResult:
    """Detached output copies; serializers cannot mutate retained backend state."""

    _json: str = field(repr=False)
    exit_code: int

    def to_dict(self) -> dict:
        return json.loads(self._json)


@dataclass(frozen=True, repr=False)
class CompletedInspection:
    """Backend-retained objects for continuation, never decoded from JSON.

    The detached result is a historical output. Revalidate current mutable
    producer objects before every subsequent action review/approval transition.
    """

    result: MockResult
    request: OperationRequest
    presentation: DiagnosisPresentation
    companion: CollectionCompanion
    prepared: PreparedCollection
    source_binding: ServiceBinding

    def validate(self) -> None:
        validate_presentation(self.request, self.presentation)
        current = self.companion.to_dict()
        envelope = self.prepared.verify_request(self.prepared.to_request(), expected_binding=self.source_binding)
        if (current != self.result.to_dict()["presentation"]
                or current["diagnosis"] != self.presentation.to_dict()
                or envelope != {"snapshot": current["snapshot"], "collection_context": current["collection_context"]}):
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None

    def __repr__(self):
        return "CompletedInspection(mode='mock')"


class MockSession:
    """An internal session, never reconstructed from submitted JSON or identifiers."""

    def __init__(self, *, mock=False, scenario="partial_failure", service_id="MOCK-service", request=None):
        try:
            self._initialize(mock=mock, scenario=scenario, service_id=service_id, request=request)
        except MockIntegrationError:
            raise
        except Exception:
            raise MockIntegrationError() from None

    def _initialize(self, *, mock, scenario, service_id, request):
        if mock is not True:
            raise MockIntegrationError("MOCK_OPT_IN_REQUIRED") from None
        if type(scenario) is not str or scenario not in SCENARIOS:
            raise MockIntegrationError("INVALID_SCENARIO") from None
        if type(service_id) is not str or service_id not in _SERVICES:
            raise MockIntegrationError("UNKNOWN_MOCK_SERVICE") from None
        self._scenario = scenario
        self._binding = _SERVICES[service_id]
        if request is None:
            request = OperationRequest("mock-request-" + scenario, "inspect_service", {
                "service_target": service_id, "goal": "Review this synthetic service collection",
            })
        valid = validate_request(request)
        if (not valid.is_complete or valid.operation != "inspect_service"
                or valid.collected_information["service_target"] != service_id):
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        self._request = OperationRequest(request.request_id, request.operation, dict(request.details))
        # Existing Provider fixture producer really calls MockLiaraClient,
        # collects observations and normalizes them. No stored diagnosis is read.
        self._prepared = build_mock_context(scenario)
        envelope = self._prepared.verify_request(self._prepared.to_request(), expected_binding=self._binding)
        metadata = ResultMetadata(
            CONTRACT_VERSION, self._request.request_id, self._request.operation,
            request_fingerprint(self._request), "provider", "ready", "mock",
        )
        # 'ready' means the canonical snapshot input exists, not complete
        # observability or a healthy application. Capability outcomes stay intact.
        self._evidence = SnapshotEvidence(
            ServiceSnapshot.model_validate(envelope["snapshot"]),
            DependencyInput(True, "mock:collection-" + scenario, metadata=metadata),
        )

    def __repr__(self):
        return "MockSession(mode='mock')"

    def collection_request(self) -> dict:
        if type(self._prepared) is not PreparedCollection:
            raise MockIntegrationError("CONTEXT_REJECTED") from None
        return self._prepared.to_request()

    def finish(self, submitted_envelope: dict | None = None) -> MockResult:
        """Verify, diagnose once, then bind the actual report with the Setup companion.

        Optional submitted data is compared to the original retained object, not
        used to mint another trusted reference. This method is not an HTTP route.
        """
        return self.inspect(submitted_envelope).result

    def inspect(self, submitted_envelope: dict | None = None) -> CompletedInspection:
        """Same collection/diagnosis path, retaining objects for backend workflow."""
        try:
            return self._finish(submitted_envelope)
        except MockIntegrationError:
            raise
        except Exception:
            raise MockIntegrationError() from None

    def _finish(self, submitted_envelope):
        try:
            if type(self._prepared) is not PreparedCollection:
                raise CollectionContextError()
            envelope = self._prepared.verify_request(
                self._prepared.to_request() if submitted_envelope is None else submitted_envelope,
                expected_binding=self._binding,
            )
            validated = validate_provider_context(envelope)
            if validated.snapshot.data_source.value != "mock":
                raise CollectionContextError()
        except (CollectionContextError, ContextCompatibilityError):
            raise MockIntegrationError("CONTEXT_REJECTED") from None

        preserved = preserve_collection_context(
            self._request, self._evidence, prepared=self._prepared, expected_binding=self._binding,
        )
        if preserved.state != "context_preserved" or preserved.companion is None:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        contextual = {
            **envelope,
            "correlation": {
                "service_id": self._binding.service_id,
                "service_binding_ref": "MOCK-fixture-binding",
                "collection_ref": "MOCK-collection-" + self._scenario,
                "snapshot_digest": envelope["collection_context"]["snapshot_digest"],
                "collection_context_digest": context_digest(envelope["collection_context"]),
            },
        }
        try:
            # The production contextual entry stays fail-closed and is never used.
            preview = preview_mock_contextual_diagnosis(contextual, mock=True)
        except Exception:
            raise MockIntegrationError("DIAGNOSIS_FAILED") from None
        try:
            presentation = consume_diagnosis(
                self._request, preserved.companion.evidence, preview.diagnosis_report,
            )
            attached = attach_collection_diagnosis(self._request, preserved.companion, presentation)
            if attached.state != "diagnosis_associated" or attached.companion is None:
                raise MockIntegrationError("SETUP_ASSOCIATION_FAILED")
            setup_view = attached.companion.to_dict()
        except SetupIntegrationError:
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        # Preserve the producer's report/context verbatim in the Setup serializer.
        if (setup_view["collection_context"] != preview.collection_context.model_dump(mode="json")
                or setup_view["diagnosis"]["report"] != preview.diagnosis_report.model_dump(mode="json")):
            raise MockIntegrationError("SETUP_ASSOCIATION_FAILED") from None
        attempted = [item for item in envelope["collection_context"]["capabilities"]
                     if item["availability"] != "not_collected"]
        complete = all(item["availability"] == "available" for item in attempted)
        result = {
            "integration_profile": INTEGRATION_PROFILE, "mode": "mock",
            "scenario": self._scenario, "status": "complete" if complete else "partial",
            "triage_preview": {
                key: value for key, value in preview.model_dump(mode="json").items()
                if key not in ("diagnosis_report", "collection_context")
            },
            "presentation": setup_view,
            "production_readiness": "unresolved", "authorization_consumed": False,
            "execution_authorized": False, "execution_performed": False,
        }
        output = MockResult(json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True), 0 if complete else 1)
        return CompletedInspection(output, self._request, presentation, attached.companion, self._prepared, self._binding)


def run_mock_backend(*, mock=False, scenario="partial_failure", service_id="MOCK-service") -> MockResult:
    return MockSession(mock=mock, scenario=scenario, service_id=service_id).finish()
