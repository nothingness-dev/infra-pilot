"""Clearly synthetic service observations; never provider-derived measurements."""

from dataclasses import replace
from datetime import datetime, timezone

from infrapilot_triage import ServiceSnapshot

from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint
from setup.models import OperationRequest
from setup.triage import SnapshotEvidence


def problem(**details):
    return OperationRequest("mock-problem-1", "inspect_service", {
        "service_target": "mock-service-A", "goal": "Investigate the supplied synthetic failure", **details,
    })


def service_evidence(request=None, **observations):
    request = request or problem()
    snapshot = ServiceSnapshot.model_validate({
        "service_id": request.details["service_target"], "status": "unhealthy", "data_source": "mock",
        "http_status": 503, "cpu_usage_percent": 95, "response_time_ms": 2000,
        "timestamp": datetime(2026, 10, 22, tzinfo=timezone.utc),
        "logs": [{"message": "Synthetic fixture: PostgreSQL connection refused", "level": "error"}],
        **observations,
    })
    metadata = ResultMetadata(CONTRACT_VERSION, request.request_id, request.operation,
                              request_fingerprint(request), "provider", "ready", "mock")
    return SnapshotEvidence(snapshot, DependencyInput(True, "mock:service-evidence-1", metadata=metadata))


def changed_metadata(evidence, **fields):
    return replace(evidence, association=replace(evidence.association,
                   metadata=replace(evidence.association.metadata, **fields)))
