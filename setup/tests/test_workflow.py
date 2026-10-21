import copy
import json
import unittest
from contextlib import ExitStack
from types import MappingProxyType
from unittest.mock import patch

from setup.integration import DependencyInput, PreparationInputs
from setup.models import DependencyPhase, OperationRequest, WorkflowState
from setup.workflow import prepare_request


def setup_request(details=None):
    return OperationRequest("mock-request", "setup_service", details if details is not None else {
        "service_name": "mock-app", "service_kind": "mock-kind", "goal": "Prepare a mock brief",
    })


def inspection_request():
    return OperationRequest("mock-inspection", "inspect_service", {
        "service_target": "mock-target", "goal": "Review mock evidence",
    })


def ready_inputs():
    return PreparationInputs(
        provider=DependencyInput(True, output_reference="mock:provider-output"),
        triage=DependencyInput(True, output_reference="mock:triage-output"),
    )


class RequestPreparationTests(unittest.TestCase):
    def test_complete_setup_returns_a_structured_proposed_plan(self):
        result = prepare_request(setup_request(), ready_inputs())
        self.assertEqual(result.state, WorkflowState.PLAN_PREPARED)
        self.assertEqual(result.state_history, (WorkflowState.RECEIVED, WorkflowState.PLAN_PREPARED))
        self.assertEqual(result.plan.collected_information["service_name"], "mock-app")
        self.assertTrue(result.plan.proposed_steps)
        self.assertFalse(result.errors)
        self.assertFalse(result.missing_information)
        self.assertNotIn("plan", result.plan.collected_information)
        self.assertNotIn("region", result.plan.collected_information)
        self.assertNotIn("budget", result.plan.collected_information)

    def test_complete_inspection_carries_references_without_inventing_diagnosis(self):
        result = prepare_request(inspection_request(), ready_inputs())
        self.assertEqual(result.state, WorkflowState.PLAN_PREPARED)
        refs = {item.key: item.output_reference for item in result.plan.dependencies}
        self.assertEqual(refs["provider_output"], "mock:provider-output")
        self.assertEqual(refs["triage_output"], "mock:triage-output")
        self.assertNotIn("diagnosis", result.to_dict()["plan"])
        self.assertNotIn("action_proposal", result.to_dict()["plan"])

    def test_setup_does_not_require_triage(self):
        result = prepare_request(setup_request(), PreparationInputs(
            provider=ready_inputs().provider,
            triage=DependencyInput(False, reason="Mock triage unavailable"),
        ))
        self.assertEqual(result.state, WorkflowState.PLAN_PREPARED)
        self.assertNotIn("triage_output", {item.key for item in result.plan.dependencies})

    def test_incomplete_brief_returns_missing_information_without_a_plan(self):
        result = prepare_request(setup_request({"service_name": "mock-app"}))
        self.assertEqual(result.state, WorkflowState.NEEDS_INFORMATION)
        self.assertEqual(
            {item.field for item in result.missing_information},
            {"details.service_kind", "details.goal"},
        )
        self.assertEqual(result.collected_information, {"service_name": "mock-app"})
        self.assertIsNone(result.plan)
        self.assertFalse(result.errors)

    def test_unsupported_operation_is_blocked_with_a_structured_error(self):
        result = prepare_request(OperationRequest("mock-request", "delete_service"))
        self.assertEqual(result.state, WorkflowState.BLOCKED)
        self.assertEqual(result.errors[0].code, "unsupported_operation")
        self.assertIsNone(result.plan)

    def test_missing_external_outputs_block_but_preserve_candidate_plan(self):
        result = prepare_request(inspection_request())
        self.assertEqual(result.state, WorkflowState.BLOCKED)
        self.assertIsNotNone(result.plan)
        self.assertEqual(
            {item.field for item in result.errors},
            {"dependencies.provider_output", "dependencies.triage_output"},
        )
        self.assertTrue(all(error.code == "dependency_unavailable" for error in result.errors))
        self.assertTrue(all(not item.available for item in result.plan.dependencies))
        self.assertTrue(all(item.output_reference is None for item in result.plan.dependencies))

    def test_explicit_dependency_failure_surfaces_its_reason(self):
        result = prepare_request(inspection_request(), PreparationInputs(
            provider=ready_inputs().provider,
            triage=DependencyInput(False, reason="Mock triage module unavailable"),
        ))
        self.assertEqual(result.state, WorkflowState.BLOCKED)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].message, "Mock triage module unavailable")
        self.assertEqual(result.errors[0].field, "dependencies.triage_output")

    def test_ready_plan_still_has_unavailable_execution_dependencies(self):
        result = prepare_request(inspection_request(), ready_inputs())
        execution = [d for d in result.plan.dependencies if d.phase == DependencyPhase.EXECUTION]
        self.assertEqual({d.key for d in execution}, {
            "provider_capability_validation", "authorization_validation", "operation_executor",
        })
        self.assertTrue(all(not dependency.available for dependency in execution))
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.plan.execution_authorized)
        self.assertFalse(result.execution_performed)
        self.assertFalse(result.plan.execution_performed)

    def test_invalid_request_and_integration_shapes_are_structured_errors(self):
        for request in (None, {}, OperationRequest("req", "setup_service", {"goal": False})):
            with self.subTest(request=request):
                result = prepare_request(request)
                self.assertEqual(result.state, WorkflowState.BLOCKED)
                self.assertTrue(result.errors)
                self.assertIsNone(result.plan)
        result = prepare_request(setup_request(), inputs={"provider": "pretend-output"})
        self.assertEqual(result.errors[0].code, "invalid_dependency_input")
        self.assertIsNone(result.plan)

    def test_processing_is_repeatable_and_does_not_alias_caller_input(self):
        details = dict(setup_request().details)
        original = copy.deepcopy(details)
        request = setup_request(MappingProxyType(details))
        inputs = ready_inputs()
        original_inputs = copy.deepcopy(inputs)
        first = prepare_request(request, inputs)
        second = prepare_request(request, inputs)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(details, original)
        self.assertEqual(inputs, original_inputs)
        first.plan.collected_information["service_name"] = "changed"
        first.collected_information["goal"] = "changed"
        self.assertEqual(details, original)
        self.assertEqual(second.plan.collected_information, original)
        self.assertEqual(first.collected_information["service_name"], "mock-app")

    def test_resubmission_can_resolve_blocking_without_mutating_previous_result(self):
        request = inspection_request()
        blocked = prepare_request(request)
        before = blocked.to_dict()
        prepared = prepare_request(request, ready_inputs())
        self.assertEqual(prepared.state, WorkflowState.PLAN_PREPARED)
        self.assertEqual(blocked.to_dict(), before)

    def test_preparation_paths_cannot_use_network_files_or_external_commands(self):
        # Fail immediately on common network, file, or process side effects.
        # This exercises real workflow code; no workflow behavior is mocked.
        cases = (
            (setup_request(), ready_inputs()),
            (inspection_request(), ready_inputs()),
            (inspection_request(), None),
            (setup_request({}), None),
            (OperationRequest("mock-request", "delete_service"), None),
            (setup_request(), PreparationInputs(
                provider=DependencyInput(False, reason="Mock provider unavailable"),
            )),
        )
        with ExitStack() as stack:
            for target in ("socket.socket", "socket.create_connection", "subprocess.Popen",
                           "os.system", "builtins.open", "io.open"):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            for request, inputs in cases:
                with self.subTest(request=request, inputs=inputs):
                    payload = json.loads(json.dumps(prepare_request(request, inputs).to_dict()))
                    self.assertFalse(payload["execution_performed"])
                    self.assertFalse(payload["execution_authorized"])
                    self.assertIn(payload["state"], {"needs_information", "plan_prepared", "blocked"})


if __name__ == "__main__":
    unittest.main()
