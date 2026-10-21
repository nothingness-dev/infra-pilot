"""Run with: python -B -m setup.examples.offline_demo (from repository root)."""

import json

from setup.application import submit_request, supply_information
from setup.completion import complete_request
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
    inspection_inputs = mock_inputs(mock_inspection)
    cases = (
        ("complete_mock_setup", mock_setup, mock_inputs(mock_setup)),
        ("incomplete_mock_request", OperationRequest("mock-incomplete-1", "setup_service", {
            "service_name": "mock-example-app",
        }), None),
        ("unsupported_mock_operation", OperationRequest("mock-unsupported-1", "delete_service"), None),
        ("unavailable_mock_provider", mock_setup, PreparationInputs(
            provider=DependencyInput(False, reason="MOCK: provider module is unavailable"),
        )),
        ("complete_mock_inspection", mock_inspection, inspection_inputs),
        ("pending_mock_triage", mock_inspection, PreparationInputs(
            provider=inspection_inputs.provider,
            triage=mock_result(mock_inspection, "triage", "pending"),
        )),
        ("failed_mock_provider", mock_setup, PreparationInputs(
            provider=mock_result(mock_setup, "provider", "failed"),
        )),
        ("missing_mock_triage", mock_inspection, PreparationInputs(
            provider=inspection_inputs.provider,
        )),
    )
    scenarios = [
        {"name": name, "result": prepare_request(request, inputs).to_dict()}
        for name, request, inputs in cases
    ]
    partial = OperationRequest(mock_setup.request_id, mock_setup.operation, {
        "service_name": mock_setup.details["service_name"],
    })
    completed = complete_request(partial, {
        "service_kind": mock_setup.details["service_kind"], "goal": mock_setup.details["goal"],
    }, mock_inputs(mock_setup))
    changed = complete_request(mock_inspection, {
        "service_target": "mock-other-target-not-a-real-service",
    }, inspection_inputs)
    scenarios.extend((
        {"name": "completed_mock_request", "result": completed.preparation.to_dict()},
        {"name": "changed_target_rejects_old_mock_results", "result": changed.preparation.to_dict()},
    ))
    # Application calls use public request information only, without teammate fixtures.
    public_incomplete = submit_request({
        "request_id": "mock-application-1", "operation": "inspect_service", "details": {},
    })
    public_completed = supply_information(public_incomplete["request"], dict(mock_inspection.details))
    public_control_rejected = submit_request({
        **public_completed["request"], "execution_authorized": True,
    })
    scenarios.extend((
        {"name": "application_missing_information", "result": public_incomplete},
        {"name": "application_complete_without_teammates", "result": public_completed},
        {"name": "application_rejects_public_authorization", "result": public_control_rejected},
    ))
    print(json.dumps({
        "mock_data": True,
        "contract_status": "module-local proposal",
        "verified_teammate_compatibility": False,
        "freshness_evaluated": False,
        "notice": "Offline mock data only. No real outputs, capability checks, authorization, "
                  "or execution. No plan, region, target, or cost defaults are inferred.",
        "scenarios": scenarios,
    }, indent=2))


if __name__ == "__main__":
    main()
