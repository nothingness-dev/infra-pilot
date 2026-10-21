import copy
import json
import unittest

from setup.application import submit_request, supply_information
from setup.integration import PreparationInputs
from setup.models import OperationRequest
from setup.tests.fixtures import mock_result


def inspection_payload():
    return {
        "request_id": "mock-public-request",
        "operation": "inspect_service",
        "details": {"service_target": "mock-target", "goal": "Review mock context"},
    }


class ApplicationBoundaryTests(unittest.TestCase):
    def assert_json_preparation(self, result):
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertFalse(result["execution_performed"])
        self.assertFalse(result["execution_authorized"])
        if result["plan"]:
            self.assertFalse(result["plan"]["execution_performed"])
            self.assertFalse(result["plan"]["execution_authorized"])

    def test_valid_public_requests_keep_candidate_plans_when_teammates_are_absent(self):
        setup = {
            "request_id": "mock-setup", "operation": "setup_service",
            "details": {"service_name": "mock-app", "service_kind": "mock-kind", "goal": "Prepare mock setup"},
        }
        for payload, missing in ((setup, {"provider_output"}),
                                 (inspection_payload(), {"provider_output", "triage_output"})):
            with self.subTest(operation=payload["operation"]):
                result = submit_request(payload)
                self.assertEqual(result["state"], "blocked")
                self.assertEqual(result["request"], payload)
                self.assertEqual(result["collected_information"], payload["details"])
                self.assertTrue(result["plan"]["proposed_steps"])
                self.assertEqual(
                    {item["key"] for item in result["plan"]["dependencies"] if item["phase"] == "preparation"},
                    missing,
                )
                self.assertTrue(all(error["code"] == "dependency_unavailable" for error in result["errors"]))
                self.assertTrue(all(not item["available"] for item in result["plan"]["dependencies"]))
                self.assert_json_preparation(result)

    def test_missing_public_information_uses_existing_missing_fields(self):
        payload = {"request_id": "mock-request", "operation": "inspect_service"}
        result = submit_request(payload)
        self.assertEqual(result["state"], "needs_information")
        self.assertEqual(
            {item["field"] for item in result["missing_information"]},
            {"details.service_target", "details.goal"},
        )
        self.assertEqual(result["request"], {**payload, "details": {}})
        self.assertIsNone(result["plan"])
        self.assertFalse(result["errors"])
        empty = submit_request({})
        self.assertEqual(empty["state"], "needs_information")
        self.assertEqual({item["field"] for item in empty["missing_information"]}, {"request_id", "operation"})
        self.assertIsNone(empty["request"])
        self.assert_json_preparation(result)
        self.assert_json_preparation(empty)

    def test_malformed_payloads_return_json_safe_structured_errors(self):
        payloads = (
            None, [], "not-decoded-json", 5, True,
            {**inspection_payload(), "request_id": []},
            {**inspection_payload(), "operation": {}},
            {**inspection_payload(), "details": None},
            {**inspection_payload(), "details": []},
            {**inspection_payload(), "details": {"service_target": {"nested": "value"}, "goal": False}},
            {**inspection_payload(), "details": {"goal": float("nan")}},
            {**inspection_payload(), "details": {1: "value"}},
            {**inspection_payload(), 7: {"unexpected": "value"}},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                result = submit_request(payload)
                self.assertEqual(result["state"], "blocked")
                self.assertTrue(result["errors"])
                self.assertIsNone(result["request"])
                self.assertIsNone(result["plan"])
                self.assert_json_preparation(result)

    def test_unsupported_operations_are_not_reinterpreted(self):
        result = submit_request({**inspection_payload(), "operation": "delete_service"})
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["errors"][0]["code"], "unsupported_operation")
        self.assertIsNone(result["request"])
        self.assertIsNone(result["plan"])
        self.assert_json_preparation(result)

    def test_public_payloads_cannot_declare_dependency_readiness_or_authorization(self):
        payload = inspection_payload()
        request = OperationRequest(**payload)
        internal = PreparationInputs(mock_result(request), mock_result(request, "triage"))
        fields = (
            "provider", "triage", "inputs", "dependency_inputs", "metadata", "available", "trusted",
            "ready", "state", "plan", "approved", "authorized", "execution_authorized", "execution_performed",
        )
        for field in fields:
            with self.subTest(field=field):
                # Valid internal fixtures cannot make an invalid public payload acceptable.
                result = submit_request({**payload, field: True}, dependency_inputs=internal)
                self.assertEqual(result["state"], "blocked")
                self.assertEqual(result["errors"][0]["code"], "unknown_field")
                self.assertEqual(result["errors"][0]["field"], field)
                self.assertIsNone(result["plan"])
                self.assert_json_preparation(result)
        nested = submit_request({**payload, "details": {**payload["details"], "execution_authorized": "true"}})
        self.assertEqual(nested["state"], "blocked")
        self.assertEqual(nested["errors"][0]["field"], "details.execution_authorized")
        self.assert_json_preparation(nested)

    def test_prepared_incomplete_and_blocked_results_use_the_same_serialization(self):
        payload = inspection_payload()
        request = OperationRequest(**payload)
        prepared = submit_request(payload, dependency_inputs=PreparationInputs(
            mock_result(request), mock_result(request, "triage"),
        ))
        incomplete = submit_request({**payload, "details": {}})
        blocked = submit_request(payload)
        self.assertEqual([item["state"] for item in (prepared, incomplete, blocked)],
                         ["plan_prepared", "needs_information", "blocked"])
        for result in (prepared, incomplete, blocked):
            self.assertEqual(set(result), set(prepared))
            self.assert_json_preparation(result)

    def test_payloads_and_returned_snapshots_do_not_share_mutable_information(self):
        payload = inspection_payload()
        before = copy.deepcopy(payload)
        first = submit_request(payload)
        second = submit_request(payload)
        self.assertEqual(first, second)
        self.assertEqual(payload, before)
        first["request"]["details"]["service_target"] = "changed"
        first["collected_information"]["goal"] = "changed"
        first["plan"]["collected_information"]["goal"] = "changed again"
        self.assertEqual(payload, before)
        self.assertEqual(second["request"], before)
        self.assertEqual(first["request"]["details"]["goal"], before["details"]["goal"])

    def test_incremental_completion_keeps_identity_and_reports_remaining_information(self):
        original = {"request_id": "mock-public-request", "operation": "inspect_service", "details": {}}
        first = submit_request(json.loads(json.dumps(original)))
        second = supply_information(first["request"], {"service_target": "mock-target"})
        self.assertEqual(second["state"], "needs_information")
        self.assertEqual([item["field"] for item in second["missing_information"]], ["details.goal"])
        third = supply_information(second["request"], {"goal": "Review mock context"})
        self.assertEqual(third["state"], "blocked")
        self.assertTrue(third["plan"]["proposed_steps"])
        self.assertFalse(third["missing_information"])
        for result in (first, second, third):
            self.assertEqual(result["request"]["request_id"], original["request_id"])
            self.assertEqual(result["request"]["operation"], original["operation"])
            self.assert_json_preparation(result)
        self.assertEqual(original["details"], {})

    def test_malformed_completion_input_and_public_control_fields_are_structured_errors(self):
        payload = inspection_payload()
        request = OperationRequest(**payload)
        internal = PreparationInputs(mock_result(request), mock_result(request, "triage"))
        additions = (None, [], True, "not-an-object", {"goal": []}, {"service_target": None},
                     {"request_id": "other-id"}, {"operation": "setup_service"},
                     {"provider": {"available": True}}, {"dependency_inputs": {"ready": True}},
                     {"execution_authorized": True}, {"execution_performed": True}, {5: "value"})
        for values in additions:
            with self.subTest(additional_information=values):
                result = supply_information(payload, values, dependency_inputs=internal)
                self.assertEqual(result["state"], "blocked")
                self.assertTrue(result["errors"])
                self.assertEqual(result["request_id"], payload["request_id"])
                self.assertIsNone(result["plan"])
                self.assert_json_preparation(result)
        for original in (None, [], {**payload, "approved": True}, {**payload, "details": 5}):
            with self.subTest(original=original):
                result = supply_information(original, {"goal": "Corrected goal"})
                self.assertEqual(result["state"], "blocked")
                self.assertTrue(result["errors"])
                self.assert_json_preparation(result)
        no_identity = supply_information({}, {"goal": "Cannot invent identity"})
        self.assertEqual(no_identity["state"], "needs_information")
        self.assertIsNone(no_identity["request"])
        self.assert_json_preparation(no_identity)

    def test_completion_rechecks_internal_dependency_associations(self):
        payload = inspection_payload()
        request = OperationRequest(**payload)
        internal = PreparationInputs(mock_result(request), mock_result(request, "triage"))
        original_inputs = copy.deepcopy(internal)
        prepared = submit_request(payload, dependency_inputs=internal)
        unchanged = supply_information(prepared["request"], {}, dependency_inputs=internal)
        changed = supply_information(prepared["request"], {"service_target": "mock-other-target"},
                                     dependency_inputs=internal)
        self.assertEqual(prepared["state"], "plan_prepared")
        self.assertEqual(unchanged["state"], "plan_prepared")
        self.assertEqual(changed["state"], "blocked")
        self.assertEqual({error["code"] for error in changed["errors"]}, {"dependency_request_mismatch"})
        self.assertEqual(len(changed["errors"]), 2)
        self.assertEqual(changed["request"]["request_id"], payload["request_id"])
        self.assertEqual(changed["request"]["operation"], payload["operation"])
        self.assertEqual(changed["request"]["details"]["service_target"], "mock-other-target")
        self.assertEqual(internal, original_inputs)
        for result in (prepared, unchanged, changed):
            self.assert_json_preparation(result)

    def test_completion_snapshots_and_results_are_detached_from_caller_inputs(self):
        payload = inspection_payload()
        additions = {"goal": "Prepare another mock review"}
        before_payload, before_additions = copy.deepcopy(payload), copy.deepcopy(additions)
        result = supply_information(payload, additions)
        self.assertEqual(result["request"]["details"]["goal"], additions["goal"])
        self.assertEqual(payload, before_payload)
        self.assertEqual(additions, before_additions)
        self.assert_json_preparation(result)
        result["request"]["details"]["goal"] = "changed"
        result["collected_information"]["goal"] = "changed again"
        self.assertEqual(payload, before_payload)
        self.assertEqual(additions, before_additions)
        invalid_internal = submit_request(payload, dependency_inputs={"provider": {"available": True}})
        self.assertEqual(invalid_internal["state"], "blocked")
        self.assertEqual(invalid_internal["errors"][0]["code"], "invalid_dependency_input")
        self.assert_json_preparation(invalid_internal)


if __name__ == "__main__":
    unittest.main()
