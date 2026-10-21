import copy
from types import MappingProxyType
import unittest

from setup.completion import complete_request
from setup.integration import PreparationInputs
from setup.models import OperationRequest, WorkflowState
from setup.tests.fixtures import mock_result
from setup.workflow import prepare_request


class RequestCompletionTests(unittest.TestCase):
    def test_incremental_completion_preserves_identity_and_remaining_information(self):
        details = {"service_name": "mock-app"}
        request = OperationRequest("mock-request", "setup_service", MappingProxyType(details))
        additions = {"service_kind": "mock-kind"}
        first = complete_request(request, MappingProxyType(additions))
        self.assertEqual(first.preparation.state, WorkflowState.NEEDS_INFORMATION)
        self.assertEqual([item.field for item in first.preparation.missing_information], ["details.goal"])
        second = complete_request(first.request, {"goal": "Prepare a mock brief"})
        self.assertEqual(second.request.request_id, "mock-request")
        self.assertEqual(second.request.operation, "setup_service")
        self.assertEqual(second.preparation.state, WorkflowState.BLOCKED)
        self.assertFalse(second.preparation.missing_information)
        third = complete_request(second.request, {}, PreparationInputs(
            provider=mock_result(second.request),
        ))
        self.assertEqual(third.preparation.state, WorkflowState.PLAN_PREPARED)
        self.assertEqual(details, {"service_name": "mock-app"})
        self.assertEqual(additions, {"service_kind": "mock-kind"})
        third.request.details["service_name"] = "changed"
        self.assertEqual(details, {"service_name": "mock-app"})
        self.assertEqual(second.request.details["service_name"], "mock-app")

    def test_changed_target_invalidates_old_results_and_new_associations_restore_readiness(self):
        request = OperationRequest("mock-request", "inspect_service", {
            "service_target": "mock-target", "goal": "Review mock context",
        })
        inputs = PreparationInputs(mock_result(request), mock_result(request, "triage"))
        before_request, before_inputs = copy.deepcopy(request), copy.deepcopy(inputs)
        original_result = prepare_request(request, inputs).to_dict()
        updated = complete_request(request, {"service_target": "mock-other-target"}, inputs)
        self.assertEqual(updated.preparation.state, WorkflowState.BLOCKED)
        self.assertEqual({error.code for error in updated.preparation.errors}, {"dependency_request_mismatch"})
        self.assertEqual(len(updated.preparation.errors), 2)
        self.assertEqual(request, before_request)
        self.assertEqual(inputs, before_inputs)
        self.assertEqual(prepare_request(request, inputs).to_dict(), original_result)
        fresh = PreparationInputs(mock_result(updated.request), mock_result(updated.request, "triage"))
        prepared = complete_request(updated.request, {}, fresh)
        self.assertEqual(prepared.preparation.state, WorkflowState.PLAN_PREPARED)

    def test_changed_optional_choices_invalidate_results_but_identical_values_do_not(self):
        request = OperationRequest("mock-request", "setup_service", {
            "service_name": "mock-app", "service_kind": "mock-kind", "goal": "Prepare a mock brief",
            "plan": "user-plan", "region": "user-region", "budget": "user-limit",
        })
        inputs = PreparationInputs(provider=mock_result(request))
        for field in ("service_name", "service_kind", "goal", "plan", "region", "budget"):
            with self.subTest(field=field):
                changed = complete_request(request, {field: "different-value"}, inputs)
                self.assertEqual(changed.preparation.state, WorkflowState.BLOCKED)
                self.assertEqual(changed.preparation.errors[0].code, "dependency_request_mismatch")
                same = complete_request(request, {field: request.details[field]}, inputs)
                self.assertEqual(same.preparation.state, WorkflowState.PLAN_PREPARED)

    def test_invalid_additions_cannot_change_identity_or_claim_execution(self):
        request = OperationRequest("mock-request", "inspect_service", {
            "service_target": "mock-target", "goal": "Review mock context",
        })
        inputs = PreparationInputs(mock_result(request), mock_result(request, "triage"))
        original = copy.deepcopy(request)
        for additions in (None, [], "goal", {"goal": 5}, {"unexpected": "value"},
                          {"request_id": "other-id"}, {"operation": "setup_service"}, {False: "value"}):
            with self.subTest(additions=additions):
                completed = complete_request(request, additions, inputs)
                self.assertEqual(completed.request.request_id, "mock-request")
                self.assertEqual(completed.request.operation, "inspect_service")
                self.assertEqual(completed.preparation.state, WorkflowState.BLOCKED)
                self.assertTrue(completed.preparation.errors)
                self.assertFalse(completed.preparation.execution_authorized)
                self.assertFalse(completed.preparation.execution_performed)
                self.assertEqual(request, original)

    def test_missing_identity_unsupported_operations_and_invalid_originals_are_not_reinvented(self):
        for request in (None, {}, OperationRequest(" ", "inspect_service"),
                        OperationRequest("mock-request", "unknown"),
                        OperationRequest("mock-request", "inspect_service", None)):
            with self.subTest(request=request):
                completed = complete_request(request, {"goal": "Review mock context"})
                self.assertIsNone(completed.request)
                self.assertNotEqual(completed.preparation.state, WorkflowState.PLAN_PREPARED)
                self.assertFalse(completed.preparation.execution_authorized)
                self.assertFalse(completed.preparation.execution_performed)

    def test_completion_revalidates_corrected_values_and_does_not_fill_defaults(self):
        request = OperationRequest("mock-request", "setup_service", {
            "service_name": "mock-app", "service_kind": 5, "goal": " ",
        })
        completed = complete_request(request, {"service_kind": "mock-kind", "goal": "Prepare mock setup"})
        self.assertFalse(completed.preparation.missing_information)
        self.assertEqual(completed.preparation.state, WorkflowState.BLOCKED)  # Provider is still absent.
        self.assertEqual(set(completed.request.details), {"service_name", "service_kind", "goal"})
        self.assertEqual(request.details["service_kind"], 5)


if __name__ == "__main__":
    unittest.main()
