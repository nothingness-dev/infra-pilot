"""Run with: python -B -m setup.examples.offline_demo (from repository root)."""

import json

from setup.integration import (
    CONTRACT_VERSION, DependencyInput, PreparationInputs, ResultMetadata, request_fingerprint,
)
from setup.models import OperationRequest
from setup.workflow import prepare_request


def mock_result(request: OperationRequest, source: str, state: str = "ready") -> DependencyInput:
    """Provisional mock envelope; identifies no real teammate output or approval."""
    return DependencyInput(
        available=state == "ready",
        output_reference=f"mock:{source}-output-not-real" if state == "ready" else None,
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


def mock_inputs(request: OperationRequest) -> PreparationInputs:
    return PreparationInputs(mock_result(request, "provider"), mock_result(request, "triage"))


def main() -> None:
    mock_setup = OperationRequest("mock-setup-1", "setup_service", {
        "service_name": "mock-example-app",
        "service_kind": "mock-kind-not-a-provider-capability",
        "goal": "Prepare an offline setup brief only",
    })
    mock_inspection = OperationRequest("mock-inspect-1", "inspect_service", {
        "service_target": "mock-target-not-a-real-service",
        "goal": "Prepare a review of mock external output references",
    })
    cases = (
        ("complete_mock_setup", mock_setup, mock_inputs(mock_setup)),
        ("incomplete_mock_request", OperationRequest("mock-incomplete-1", "setup_service", {
            "service_name": "mock-example-app",
        }), None),
        ("unsupported_mock_operation", OperationRequest("mock-unsupported-1", "delete_service"), None),
        ("unavailable_mock_provider", mock_setup, PreparationInputs(
            provider=DependencyInput(False, reason="MOCK: provider module is unavailable"),
        )),
        ("complete_mock_inspection", mock_inspection, mock_inputs(mock_inspection)),
    )
    print(json.dumps({
        "mock_data": True,
        "notice": "Offline mock data only. No real outputs, capability checks, authorization, "
                  "or execution. No plan, region, target, or cost defaults are inferred.",
        "scenarios": [
            {"name": name, "result": prepare_request(request, inputs).to_dict()}
            for name, request, inputs in cases
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
