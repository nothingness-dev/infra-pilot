from dataclasses import replace
import unittest

from setup.integration import DependencyInput, request_fingerprint, validate_dependency_input
from setup.models import OperationRequest
from setup.tests.fixtures import mock_result


class ResultAssociationTests(unittest.TestCase):
    def setUp(self):
        self.request = OperationRequest("mock-request", "inspect_service", {
            "service_target": "mock-target", "goal": "Review mock context",
        })
        self.result = mock_result(self.request)

    def codes(self, result, request=None):
        return {error.code for error in validate_dependency_input(
            result, self.request if request is None else request, "provider",
        )}

    def test_compatible_mock_and_external_envelopes_have_explicit_provenance(self):
        self.assertFalse(self.codes(self.result))
        external = replace(self.result, output_reference="external:opaque-result-1", metadata=replace(
            self.result.metadata, provenance="external",
        ))
        self.assertFalse(self.codes(external))

    def test_fingerprint_is_order_independent_but_binds_every_exact_request_value(self):
        reordered = replace(self.request, details=dict(reversed(list(self.request.details.items()))))
        self.assertEqual(request_fingerprint(self.request), request_fingerprint(reordered))
        changed_requests = (
            replace(self.request, request_id="other-request"),
            replace(self.request, details={**self.request.details, "service_target": "other-target"}),
            replace(self.request, details={**self.request.details, "goal": "Changed scope"}),
            replace(self.request, details={**self.request.details, "service_target": " mock-target "}),
            OperationRequest("mock-request", "setup_service", {
                "service_name": "mock-target", "service_kind": "mock-kind", "goal": "Review mock context",
            }),
        )
        for request in changed_requests:
            with self.subTest(request=request):
                self.assertNotEqual(request_fingerprint(self.request), request_fingerprint(request))
                self.assertIn("dependency_request_mismatch", self.codes(self.result, request))
        with self.assertRaises(ValueError):
            request_fingerprint(OperationRequest("mock-request", "inspect_service", {}))

    def test_wrong_request_operation_or_producer_is_explicitly_rejected(self):
        for field, value, code in (
            ("request_id", "another-request", "dependency_request_mismatch"),
            ("operation", "setup_service", "dependency_operation_mismatch"),
            ("source", "triage", "dependency_source_mismatch"),
        ):
            with self.subTest(field=field):
                result = replace(self.result, metadata=replace(self.result.metadata, **{field: value}))
                self.assertIn(code, self.codes(result))

    def test_versions_states_and_provenance_are_checked_without_coercion(self):
        for field, value, code in (
            ("contract_version", "v999", "unsupported_contract_version"),
            ("state", "running", "unsupported_dependency_state"),
            ("state", "pending", "inconsistent_dependency_state"),
            ("provenance", "trusted", "unsupported_provenance"),
            ("provenance", "external", "provenance_mismatch"),
            ("request_fingerprint", "unbound", "invalid_request_fingerprint"),
            ("request_id", [], "invalid_dependency_metadata"),
            ("state", True, "invalid_dependency_metadata"),
            ("contract_version", " ", "invalid_dependency_metadata"),
        ):
            with self.subTest(field=field, value=value):
                result = replace(self.result, metadata=replace(self.result.metadata, **{field: value}))
                self.assertIn(code, self.codes(result))

    def test_unsupported_and_malformed_reference_formats_are_rejected(self):
        for reference in ("https://example.invalid/result", "mock:", "mock:has space", "mock:a/b",
                          "mock:line\nbreak", "external:", "real:report", "mock:گزارش"):
            with self.subTest(reference=reference):
                self.assertIn("invalid_output_reference", self.codes(replace(
                    self.result, output_reference=reference,
                )))

    def test_legacy_available_inputs_and_malformed_metadata_cannot_be_ready(self):
        self.assertIn("dependency_metadata_required", self.codes(DependencyInput(True, "mock:legacy")))
        self.assertIn("invalid_dependency_metadata", self.codes(replace(self.result, metadata={})))
        # A legacy failure remains a usable blocking signal, never a ready result.
        self.assertFalse(self.codes(DependencyInput(False, reason="MOCK: unavailable")))

    def test_recognized_nonready_results_are_well_formed_but_never_available(self):
        for state in ("pending", "failed", "unavailable"):
            with self.subTest(state=state):
                result = mock_result(self.request, state=state)
                self.assertFalse(result.available)
                self.assertFalse(self.codes(result))


if __name__ == "__main__":
    unittest.main()
