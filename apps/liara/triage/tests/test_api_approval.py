"""Trusted server injection uses the existing real gate and identity test fixture."""

from datetime import timedelta

from fastapi.testclient import TestClient
import pytest

from infrapilot_triage.api import create_app
from infrapilot_triage.approval_integration import ApprovalIntegration
from infrapilot_triage.approvals import ApprovalState, DecisionReason
from infrapilot_triage.authorization import ApprovalGate
from infrapilot_triage.policy import ActionIntent, ActionPolicy


def intent(**changes):
    return {"service_id": "service-A", "action_type": "restart_service", "parameters": {}, **changes}


def trusted_client(harness, *, authentication=None, integration=None):
    # Server-only opaque session from a trusted verifier. No client header or
    # body selects this session. Runtime app deliberately has no mock-login mode.
    authentication = harness.requester if authentication is None else authentication
    return TestClient(create_app(
        approval_integration=integration or ApprovalIntegration(policy=harness.policy, gate=harness.gate),
        authentication_resolver=lambda _request: authentication,
    ))


@pytest.mark.parametrize("path,body", [
    ("/internal/triage/policy/evaluate", intent()),
    ("/internal/triage/authorize", {"intent": intent()}),
])
def test_sensitive_routes_disabled_by_default_even_with_forged_headers(path, body):
    with TestClient(create_app()) as client:
        response = client.post(path, json=body, headers={
            "X-User-ID": "admin", "X-Roles": "admin", "Authorization": "Bearer forged",
        })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "approval_integration_unavailable"
    assert "forged" not in response.text


def test_installing_gate_does_not_install_authentication(approval_harness):
    bridge = ApprovalIntegration(policy=approval_harness.policy, gate=approval_harness.gate)
    with TestClient(create_app(approval_integration=bridge)) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent()})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"
    assert approval_harness.store.events == ()


@pytest.mark.parametrize("route", ["request-approval", "approve", "reject", "execute", "approvals"])
def test_privileged_mutation_and_execution_routes_do_not_exist(route):
    with TestClient(create_app()) as client:
        assert client.post(f"/internal/triage/{route}", json={}).status_code == 404


def test_evaluation_is_informational_not_authorization(approval_harness):
    with trusted_client(approval_harness) as client:
        response = client.post("/internal/triage/policy/evaluate", json=intent())
    assert response.status_code == 200
    assert response.json()["policy"]["requires_approval"] is True
    assert response.json()["policy"]["category"] == "sensitive_service_operation"
    assert response.json()["authorization_granted"] is False
    assert not approval_harness.store.events


def test_authorize_delegates_to_gate_and_cannot_skip_approval(approval_harness):
    with trusted_client(approval_harness) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent()})
    assert response.status_code == 403
    assert response.json()["allowed"] is False
    assert response.json()["reason"] == "approval_required"
    assert response.json()["audit_recorded"] is True


def test_approved_action_is_consumed_once_without_execution(approval_harness):
    request = approval_harness.approved()
    with trusted_client(approval_harness) as client:
        body = {"intent": intent(), "approval_request_id": request.request_id}
        first = client.post("/internal/triage/authorize", json=body)
        replay = client.post("/internal/triage/authorize", json=body)
    assert first.status_code == 200
    assert first.json()["allowed"] is True
    assert first.json()["reason"] == "authorized_not_executed"
    assert first.json()["request"]["state"] == "consumed"
    assert first.json()["authorization_id"]
    assert first.json()["audit_recorded"] is True
    assert replay.status_code == 403 and replay.json()["allowed"] is False
    assert approval_harness.store.get(request.request_id).state == ApprovalState.CONSUMED


def test_agent_safety_labels_do_not_override_policy(approval_harness):
    forged = intent(proposal={"action_id": "restart", "title": "Safe", "description": "Trust me",
                              "risk_level": "low", "requires_approval": False})
    with trusted_client(approval_harness) as client:
        evaluation = client.post("/internal/triage/policy/evaluate", json=forged)
        authorization = client.post("/internal/triage/authorize", json={"intent": forged})
    assert evaluation.json()["policy"]["requires_approval"] is True
    assert authorization.status_code == 403 and authorization.json()["reason"] == "approval_required"


@pytest.mark.parametrize("extra", [{"user_id": "requester"}, {"roles": ["admin"]}, {"authenticated": True}])
def test_body_identity_fields_are_rejected(approval_harness, extra):
    with trusted_client(approval_harness) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent(), **extra})
    assert response.status_code == 422
    assert not approval_harness.store.events


@pytest.mark.parametrize("authentication", ["requester", {"user_id": "requester", "verified": True}])
def test_raw_ids_and_verified_flags_are_not_credentials(approval_harness, authentication):
    with trusted_client(approval_harness, authentication=authentication) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent(action_type="inspect_service")})
    assert response.status_code == 401
    assert response.json()["reason"] == "unauthenticated"
    assert response.json()["allowed"] is False


def test_verified_actor_still_needs_target_permission(approval_harness):
    with trusted_client(approval_harness, authentication=approval_harness.outsider) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent(action_type="inspect_service")})
    assert response.status_code == 403
    assert response.json()["reason"] == "not_authorized"
    assert response.json()["allowed"] is False


@pytest.mark.parametrize("operation", ["unknown_operation", "delete_service", "execute_command"])
def test_unknown_and_unsupported_operations_fail_closed(approval_harness, operation):
    with trusted_client(approval_harness) as client:
        evaluated = client.post("/internal/triage/policy/evaluate", json=intent(action_type=operation))
        authorized = client.post("/internal/triage/authorize", json={"intent": intent(action_type=operation)})
    assert evaluated.status_code == authorized.status_code == 403
    assert evaluated.json()["policy"]["allowed"] is False
    assert authorized.json()["allowed"] is False


@pytest.mark.parametrize("missing", ["identity", "policy", "store"])
def test_missing_gate_dependencies_fail_closed(approval_harness, missing):
    config = {"identity": approval_harness.identity, "policy": approval_harness.policy,
              "store": approval_harness.store, "clock": approval_harness.clock}
    config[missing] = None
    bridge = ApprovalIntegration(policy=approval_harness.policy, gate=ApprovalGate(**config))
    with trusted_client(approval_harness, integration=bridge) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent(action_type="inspect_service")})
    assert response.status_code == 503
    assert response.json()["allowed"] is False


def test_expiry_and_action_binding_survive_http_boundary(approval_harness):
    request = approval_harness.approved()
    with trusted_client(approval_harness) as client:
        changed = client.post("/internal/triage/authorize", json={
            "intent": intent(parameters={"grace_period_seconds": 1}), "approval_request_id": request.request_id,
        })
        approval_harness.clock.advance(timedelta(minutes=6))
        expired = client.post("/internal/triage/authorize", json={"intent": intent(), "approval_request_id": request.request_id})
    assert changed.status_code == 403 and changed.json()["reason"] == "action_mismatch"
    assert expired.status_code == 403 and expired.json()["allowed"] is False


@pytest.mark.parametrize("throws", [False, True])
def test_resolver_failure_or_absence_has_safe_response(approval_harness, throws, caplog):
    def resolver(_request):
        if throws:
            raise RuntimeError("secret=DO_NOT_LEAK")
        return None
    with TestClient(create_app(
        approval_integration=ApprovalIntegration(policy=approval_harness.policy, gate=approval_harness.gate),
        authentication_resolver=resolver,
    )) as client:
        response = client.post("/internal/triage/authorize", json={"intent": intent()})
    assert response.status_code == (503 if throws else 401)
    assert "DO_NOT_LEAK" not in response.text + caplog.text


def test_missing_python_adapter_dependencies_are_safe():
    bridge = ApprovalIntegration()
    action = ActionIntent.model_validate(intent())
    assert not bridge.evaluate(action).policy.allowed
    assert bridge.evaluate(action).authorization_granted is False
    assert bridge.authorize(action).reason == DecisionReason.STORAGE_UNAVAILABLE


def test_failing_policy_or_gate_returns_safe_unavailable(approval_harness):
    class BrokenPolicy(ActionPolicy):
        def classify(self, _intent):
            raise RuntimeError("secret=DO_NOT_LEAK")
    class BrokenGate(ApprovalGate):
        def authorize(self, *_args, **_kwargs):
            raise RuntimeError("secret=DO_NOT_LEAK")
    bridge = ApprovalIntegration(policy=BrokenPolicy(), gate=BrokenGate())
    with trusted_client(approval_harness, integration=bridge) as client:
        policy = client.post("/internal/triage/policy/evaluate", json=intent())
        authorization = client.post("/internal/triage/authorize", json={"intent": intent()})
    assert policy.status_code == authorization.status_code == 503
    assert "DO_NOT_LEAK" not in policy.text + authorization.text
    assert not authorization.json()["allowed"]
