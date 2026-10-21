import json
import unittest
from dataclasses import FrozenInstanceError

from setup.models import PreparationResult, WorkflowState


class PreparationResultTests(unittest.TestCase):
    def test_received_result_is_json_compatible_and_cannot_claim_execution(self):
        result = PreparationResult(
            request_id="local-1",
            state=WorkflowState.RECEIVED,
            state_history=(WorkflowState.RECEIVED,),
            collected_information={"service_name": "example"},
        )
        payload = json.loads(json.dumps(result.to_dict()))
        self.assertEqual(payload["state"], "received")
        self.assertFalse(payload["execution_performed"])
        self.assertFalse(payload["execution_authorized"])
        with self.assertRaises(FrozenInstanceError):
            result.execution_performed = True

    def test_serialized_information_does_not_alias_result(self):
        result = PreparationResult("local-1", WorkflowState.RECEIVED, (), {"goal": "read"})
        payload = result.to_dict()
        payload["collected_information"]["goal"] = "changed"
        self.assertEqual(result.collected_information["goal"], "read")


if __name__ == "__main__":
    unittest.main()
