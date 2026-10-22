"""Explicit offline MOCK diagnosis/approval demo using the tested fixture identity.

There is no runtime mock login, network call or provider operation. The imported
fixture is test-only wiring of the real policy/gate/in-memory store, not an IdP.
"""

import json

from infrapilot_triage import ApprovalState

from setup.approval_workflow import SetupApprovalWorkflow
from setup.tests.approval_fixtures import ApprovalFixture


def run_demo() -> dict:
    fixture = ApprovalFixture()
    review = fixture.review()
    pending = fixture.pending()
    approved = fixture.workflow.approve(
        pending.binding, pending.approval_request_id,
        request=fixture.request, presentation=fixture.presentation,
        authentication=fixture.identity.approver_session,
    )
    rejected = fixture.workflow.reject(
        pending.binding, pending.approval_request_id,
        request=fixture.request, presentation=fixture.presentation,
        authentication=fixture.identity.approver_session,
    )
    default = SetupApprovalWorkflow()
    unconfigured = default.request_approval(
        review.binding, request=fixture.request, presentation=fixture.presentation,
    )
    if (approved.decision.request.state != ApprovalState.APPROVED
            or rejected.decision.request.state != ApprovalState.REJECTED
            or any(result.to_dict()['execution_authorized'] for result in (pending, approved, rejected))):
        raise AssertionError('Offline approval presentation must never authorize execution')
    return {
        'data_source': 'mock', 'identity_source': 'test_only_opaque_session_fixture',
        'storage': 'volatile_in_memory', 'real_operations_performed': False,
        'diagnosis': fixture.presentation.to_dict(), 'review': review.to_dict(),
        'pending': pending.to_dict(), 'approved_not_executed': approved.to_dict(),
        'rejected': rejected.to_dict(), 'default_unconfigured': unconfigured.to_dict(),
        'audit_kinds': [event.kind.value for event in fixture.store.events],
    }


if __name__ == '__main__':
    print(json.dumps(run_demo(), indent=2, allow_nan=False))
