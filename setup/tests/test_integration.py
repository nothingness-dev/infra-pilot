import unittest

from setup.integration import DependencyInput, PreparationInputs


class IntegrationInputTests(unittest.TestCase):
    def test_explicit_output_and_failure_inputs(self):
        provider = DependencyInput(True, output_reference="mock:provider-1")
        triage = DependencyInput(False, reason="Diagnosis module is unavailable")
        inputs = PreparationInputs(provider=provider, triage=triage)
        self.assertEqual(inputs.provider.output_reference, "mock:provider-1")
        self.assertFalse(inputs.triage.available)

    def test_missing_inputs_have_no_synthetic_outputs(self):
        self.assertIsNone(PreparationInputs().provider)
        self.assertIsNone(PreparationInputs().triage)

    def test_ambiguous_or_malformed_dependency_inputs_are_rejected(self):
        cases = (
            {"available": "false", "output_reference": "mock:provider"},
            {"available": True},
            {"available": True, "output_reference": " "},
            {"available": True, "output_reference": "mock:provider", "reason": "failed"},
            {"available": False},
            {"available": False, "reason": " "},
            {"available": False, "reason": "failed", "output_reference": "mock:provider"},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                DependencyInput(**values)

    def test_callbacks_and_arbitrary_objects_are_not_dependency_inputs(self):
        with self.assertRaises(ValueError):
            PreparationInputs(provider=lambda: None)


if __name__ == "__main__":
    unittest.main()
