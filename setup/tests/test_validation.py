import copy
import unittest
from types import MappingProxyType

from setup.models import Operation, OperationRequest
from setup.validation import validate_request


class RequestValidationTests(unittest.TestCase):
    def test_setup_brief_preserves_explicit_choices_without_provider_validation(self):
        details = {
            "service_name": "Mock app", "service_kind": "user-specified-kind",
            "goal": "Prepare a service setup brief", "plan": "unverified-plan",
            "region": "unverified-region", "budget": "user-supplied limit",
        }
        result = validate_request(OperationRequest("req-1", Operation.SETUP_SERVICE, details))
        self.assertTrue(result.is_complete)
        self.assertEqual(result.collected_information, details)

    def test_inspection_requires_an_explicit_target_and_goal(self):
        result = validate_request(OperationRequest("req-1", "inspect_service", {}))
        self.assertEqual(
            [item.field for item in result.missing_information],
            ["details.service_target", "details.goal"],
        )
        self.assertFalse(result.is_complete)
        self.assertFalse(result.errors)

    def test_blank_required_values_are_missing_and_no_defaults_are_invented(self):
        result = validate_request(OperationRequest("req-1", "setup_service", {
            "service_name": "  ", "service_kind": "mock-kind",
        }))
        self.assertEqual(
            {item.field for item in result.missing_information},
            {"details.service_name", "details.goal"},
        )
        self.assertEqual(result.collected_information, {"service_kind": "mock-kind"})

    def test_unsupported_operations_are_explicit(self):
        for operation in ("delete_service", "unknown", "SETUP_SERVICE"):
            with self.subTest(operation=operation):
                result = validate_request(OperationRequest("req-1", operation))
                self.assertEqual(result.errors[0].code, "unsupported_operation")
                self.assertIsNone(result.operation)

    def test_missing_envelope_fields_are_reported(self):
        result = validate_request(OperationRequest(" ", " "))
        self.assertEqual(
            [item.field for item in result.missing_information], ["request_id", "operation"],
        )

    def test_malformed_requests_return_errors_instead_of_coercing_values(self):
        cases = (
            None, {"operation": "setup_service"},
            OperationRequest(12, "setup_service"),
            OperationRequest("req-1", False),
            OperationRequest("req-1", "setup_service", None),
            OperationRequest("req-1", "setup_service", []),
            OperationRequest("req-1", "setup_service", {"service_name": 5}),
            OperationRequest("req-1", "setup_service", {"service_kind": {"nested": True}}),
            OperationRequest("req-1", "setup_service", {"plan": " "}),
            OperationRequest("req-1", "setup_service", {"region_typo": "somewhere"}),
            OperationRequest("req-1", "setup_service", {"authorization": "approved"}),
            OperationRequest("req-1", "setup_service", {False: "value"}),
            OperationRequest("req-1", "inspect_service", {"plan": "wrong operation"}),
        )
        for request in cases:
            with self.subTest(request=request):
                result = validate_request(request)
                self.assertTrue(result.errors)
                self.assertFalse(result.is_complete)

    def test_validation_preserves_input_and_returns_independent_collected_values(self):
        details = {"service_target": " exact-target ", "goal": "Read mock context"}
        original = copy.deepcopy(details)
        result = validate_request(OperationRequest(
            "req-1", "inspect_service", MappingProxyType(details),
        ))
        self.assertTrue(result.is_complete)
        self.assertEqual(details, original)
        self.assertEqual(result.collected_information["service_target"], " exact-target ")
        result.collected_information["goal"] = "changed"
        self.assertEqual(details, original)


if __name__ == "__main__":
    unittest.main()
