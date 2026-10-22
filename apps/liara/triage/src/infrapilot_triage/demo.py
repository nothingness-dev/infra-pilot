"""Explicit offline MOCK demo: in-process HTTP, real engine/gate, no open port.

No demo app, identity, session, or gate exists until run_mock_demo(mock=True).
Nothing here is a production authentication port or an infrastructure executor.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from .api import create_app
from .approval_integration import ApprovalIntegration
from .approval_store import InMemoryApprovalStore
from .approvals import GateDecision
from .authorization import ApprovalGate
from .identity import AuthenticatedActor, Permission
from .policy import ActionIntent, ActionPolicy, ActionType, CanonicalAction
from .schemas import DiagnosisReport, ServiceSnapshot


class _MockIdentity:
    """Two server-installed opaque MOCK sessions with narrow, distinct ACLs."""

    def __init__(self) -> None:
        self.requester_session, self.approver_session = object(), object()
        self.requester, self.approver = AuthenticatedActor("MOCK-requester"), AuthenticatedActor("MOCK-approver")

    def authenticate(self, authentication: object) -> AuthenticatedActor | None:
        if authentication is self.requester_session:
            return self.requester
        if authentication is self.approver_session:
            return self.approver
        return None

    def is_authorized(self, actor: AuthenticatedActor, action: CanonicalAction, permission: Permission) -> bool:
        if action.service_id != "MOCK-service" or action.action_type != ActionType.RESTART_SERVICE:
            return False
        return (
            actor == self.requester and permission in (Permission.REQUEST, Permission.EXECUTE)
        ) or (actor == self.approver and permission == Permission.APPROVE)


def _fixture(filename: str) -> dict[str, Any]:
    directory = Path(__file__).resolve().parents[2] / "examples"
    return json.loads((directory / filename).read_text(encoding="utf-8"))


def _post(client: TestClient, route: str, payload: dict[str, Any], expected: int) -> dict[str, Any]:
    response = client.post(route, json=payload)
    if response.status_code != expected:
        raise RuntimeError("MOCK demo returned an unexpected HTTP status.")
    return {"http_status": response.status_code, "body": response.json()}


def run_mock_demo(*, mock: bool) -> dict[str, Any]:
    """Run the complete isolated story. mock must be exactly True; no files write.

    The restart is a separate MOCK operator-selected example from an existing
    fixture, not a remediation inferred from the database diagnosis. No provider
    capability, live repair, or automatic proposal-to-operation mapping is claimed.
    """
    if mock is not True:
        raise ValueError("Explicit offline MOCK mode is required")
    output: dict[str, Any] = {
        "mode": "MOCK_OFFLINE_IN_PROCESS", "real_liara_connectivity_verified": False,
        "infrastructure_execution_performed": False,
        "operator_note": "Separate MOCK restart example; not a diagnosis-derived remediation or verified provider capability.",
    }
    with TestClient(create_app()) as client:
        output["health"] = client.get("/health").json()
        for label, filename in (("database_http500", "mock_db_http500.request.json"),
                                ("cpu_latency", "mock_cpu_latency.request.json")):
            snapshot = ServiceSnapshot.model_validate(_fixture(filename))
            if snapshot.data_source.value != "mock":
                raise ValueError("Demo accepts only MOCK observations")
            result = _post(client, "/internal/triage/diagnose", snapshot.model_dump(mode="json"), 200)
            DiagnosisReport.model_validate(result["body"])
            output[label] = {"request": snapshot.model_dump(mode="json"), "response": result}
        intent = ActionIntent.model_validate(_fixture("mock_sensitive_pending.request.json"))
        body = {"intent": intent.model_dump(mode="json")}
        output["default_sensitive_route"] = _post(client, "/internal/triage/authorize", body, 503)

    identity, policy, store = _MockIdentity(), ActionPolicy(), InMemoryApprovalStore()
    gate = ApprovalGate(identity=identity, policy=policy, store=store,
                        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    adapter = TypeAdapter(GateDecision)
    application = create_app(
        approval_integration=ApprovalIntegration(policy=policy, gate=gate),
        authentication_resolver=lambda _request: identity.requester_session,
    )
    # This app is private to this synchronous harness. It is never exported to
    # Uvicorn and never reads a client-selected actor or exposes approval mutations.
    with TestClient(application) as client:
        output["policy"] = _post(client, "/internal/triage/policy/evaluate", body["intent"], 200)
        output["unapproved_denial"] = _post(client, "/internal/triage/authorize", body, 403)
        pending = gate.request_approval(intent, authentication=identity.requester_session)
        if pending.request is None or pending.allowed:
            raise RuntimeError("MOCK approval request was not pending.")
        output["mock_pending_python_only"] = adapter.dump_python(pending, mode="json")
        approved_body = {**body, "approval_request_id": pending.request.request_id}
        output["pending_denial"] = _post(client, "/internal/triage/authorize", approved_body, 403)
        approved = gate.approve(pending.request.request_id, authentication=identity.approver_session)
        if approved.allowed or approved.request is None or approved.request.state.value != "approved":
            raise RuntimeError("MOCK independent approval was not granted.")
        output["mock_approved_python_only"] = adapter.dump_python(approved, mode="json")
        output["mock_authorization_not_execution"] = _post(client, "/internal/triage/authorize", approved_body, 200)
        output["replay_denial"] = _post(client, "/internal/triage/authorize", approved_body, 403)
    output["final_mock_approval_state"] = store.get(pending.request.request_id).state.value
    output["audit_kinds"] = [event.kind.value for event in store.events]
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline MOCK-only triage demo; no network server, Liara calls, or execution.")
    parser.add_argument("--mock", action="store_true", required=True, help="Explicitly enable isolated offline MOCK identities")
    args = parser.parse_args()
    print(json.dumps(run_mock_demo(mock=args.mock), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
