"""Run with: python -B -m setup.examples.offline_demo (from repository root)."""

import json

from setup.integration import DependencyInput, PreparationInputs
from setup.models import OperationRequest
from setup.workflow import prepare_request


def main() -> None:
    # These references identify no real snapshots, reports, services, or approvals.
    mock_inputs = PreparationInputs(
        provider=DependencyInput(True, output_reference="mock:provider-output-not-real"),
        triage=DependencyInput(True, output_reference="mock:triage-output-not-real"),
    )
    mock_setup = OperationRequest("mock-setup-1", "setup_service", {
        "service_name": "mock-example-app",
        "service_kind": "mock-kind-not-a-provider-capability",
        "goal": "Prepare an offline setup brief only",
    })
    cases = (
        ("complete_mock_setup", mock_setup, mock_inputs),
        ("incomplete_mock_request", OperationRequest("mock-incomplete-1", "setup_service", {
            "service_name": "mock-example-app",
        }), None),
        ("unsupported_mock_operation", OperationRequest("mock-unsupported-1", "delete_service"), None),
        ("unavailable_mock_provider", mock_setup, PreparationInputs(
            provider=DependencyInput(False, reason="MOCK: provider module is unavailable"),
        )),
        ("complete_mock_inspection", OperationRequest("mock-inspect-1", "inspect_service", {
            "service_target": "mock-target-not-a-real-service",
            "goal": "Prepare a review of mock external output references",
        }), mock_inputs),
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
