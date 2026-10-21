"""Deterministic provisional fixtures; no actual teammate compatibility asserted."""

from setup.integration import CONTRACT_VERSION, DependencyInput, ResultMetadata, request_fingerprint


def mock_result(request, source="provider", state="ready"):
    return DependencyInput(
        available=state == "ready",
        output_reference=f"mock:{source}-output" if state == "ready" else None,
        reason=None if state == "ready" else f"MOCK: {source} is {state}",
        metadata=ResultMetadata(
            contract_version=CONTRACT_VERSION,
            request_id=request.request_id,
            operation=request.operation,
            request_fingerprint=request_fingerprint(request),
            source=source,
            state=state,
            provenance="mock",
        ),
    )
