from contextlib import ExitStack
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from setup.integration import DependencyInput, PreparationInputs
from setup.models import DependencyPhase, OperationRequest, WorkflowState
from setup.tests.fixtures import mock_result
from setup.workflow import prepare_request


class IntegratedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.request = OperationRequest("mock-request", "inspect_service", {
            "service_target": "mock-target", "goal": "Review mock context",
        })
        self.provider = mock_result(self.request)
        self.triage = mock_result(self.request, "triage")

    def prepare(self, provider):
        return prepare_request(self.request, PreparationInputs(provider, self.triage))

    def test_ready_reference_provenance_and_version_survive_serialization(self):
        external = replace(self.provider, output_reference="external:unverified-fixture", metadata=replace(
            self.provider.metadata, provenance="external",
        ))
        result = self.prepare(external)
        self.assertEqual(result.state, WorkflowState.PLAN_PREPARED)
        dependencies = result.to_dict()["plan"]["dependencies"]
        self.assertEqual(dependencies[0]["provenance"], "external")
        self.assertEqual(dependencies[1]["provenance"], "mock")
        self.assertEqual(dependencies[0]["reported_state"], "ready")
        self.assertEqual(dependencies[0]["contract_version"], self.provider.metadata.contract_version)
        self.assertFalse(result.execution_authorized)

    def test_missing_pending_failed_and_unavailable_inputs_are_explicitly_blocked(self):
        cases = [(None, "dependency_unavailable")]
        cases.extend((mock_result(self.request, state=state), f"dependency_{state}")
                     for state in ("pending", "failed", "unavailable"))
        for provider, code in cases:
            with self.subTest(code=code):
                result = self.prepare(provider)
                self.assertEqual(result.state, WorkflowState.BLOCKED)
                self.assertEqual(result.errors[0].code, code)
                self.assertFalse(result.plan.dependencies[0].available)
                self.assertIsNotNone(result.plan)

    def test_malformed_mismatched_or_legacy_results_never_establish_readiness(self):
        changed_request = replace(self.request, details={**self.request.details, "service_target": "other-target"})
        cases = (
            (DependencyInput(True, "mock:legacy"), "dependency_metadata_required"),
            (replace(self.provider, metadata={"untrusted": object()}), "invalid_dependency_metadata"),
            (replace(self.provider, output_reference="mock:invalid reference"), "invalid_output_reference"),
            (mock_result(changed_request), "dependency_request_mismatch"),
            (mock_result(replace(self.request, request_id="other-request")), "dependency_request_mismatch"),
            (self.triage, "dependency_source_mismatch"),
            (replace(self.provider, metadata=replace(self.provider.metadata, operation="setup_service")),
             "dependency_operation_mismatch"),
            (replace(self.provider, metadata=replace(self.provider.metadata, contract_version="v999")),
             "unsupported_contract_version"),
            (replace(self.provider, metadata=replace(self.provider.metadata, state="executing")),
             "unsupported_dependency_state"),
            (replace(self.provider, metadata=replace(self.provider.metadata, provenance="external")),
             "provenance_mismatch"),
        )
        for provider, code in cases:
            with self.subTest(code=code):
                result = self.prepare(provider)
                self.assertEqual(result.state, WorkflowState.BLOCKED)
                self.assertIn(code, {error.code for error in result.errors})
                self.assertTrue(all(error.field.startswith("dependencies.provider_output") for error in result.errors))
                self.assertFalse(result.plan.dependencies[0].available)
                self.assertIsNone(result.plan.dependencies[0].output_reference)
                json.dumps(result.to_dict())  # No malformed caller objects may leak into output.

    def test_every_integrated_outcome_is_side_effect_free_and_cannot_claim_execution(self):
        inputs = [self.provider, None, DependencyInput(True, "mock:legacy")]
        inputs.extend(mock_result(self.request, state=state) for state in ("pending", "failed", "unavailable"))
        with ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "subprocess.Popen", "os.system",
                           "builtins.open", "io.open"):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            for provider in inputs:
                with self.subTest(provider=provider):
                    payload = json.loads(json.dumps(self.prepare(provider).to_dict()))
                    for item in (payload, payload["plan"]):
                        self.assertFalse(item["execution_performed"])
                        self.assertFalse(item["execution_authorized"])
                    for dependency in payload["plan"]["dependencies"]:
                        if dependency["phase"] == DependencyPhase.EXECUTION.value:
                            self.assertFalse(dependency["available"])


if __name__ == "__main__":
    unittest.main()
