"""Offline HTTP boundary and retained-object workflow for the local UI."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from integration.ui_backend import create_ui_app

ORIGIN = {"Origin": "http://127.0.0.1:4173"}


class UiBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_ui_app(mock=True, data_directory=self.root)
        self.client = self.new_client()
        self.headers = self.bootstrap(self.client)

    def new_client(self):
        client = TestClient(self.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def bootstrap(self, client):
        response = client.post("/api/ui/session", json={}, headers=ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        return {**ORIGIN, "X-UI-CSRF": response.json()["csrf"]}

    def state(self, client=None):
        response = (client or self.client).get("/api/ui/state")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_explicit_mock_and_existing_directory_required(self):
        for kwargs in ({}, {"mock": False, "data_directory": self.root},
                       {"mock": True, "data_directory": self.root / "missing"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                create_ui_app(**kwargs)

    def test_real_pipeline_null_metrics_and_four_log_accounting_states(self):
        state = self.state()
        self.assertEqual(state["source"], "mock")
        self.assertFalse(state["real_available"])
        self.assertEqual(len(state["records"]), 4)
        self.assertEqual({r["context"]["log_export"]["state"] for r in state["records"]},
                         {"collection_failed", "exported", "withheld", "empty"})
        for record in state["records"]:
            self.assertEqual(record["snapshot"]["status"], "unknown")
            self.assertIsNone(record["snapshot"]["cpu_usage_percent"])
            self.assertIsNone(record["snapshot"]["timestamp"])
            self.assertNotIn("logs", record["snapshot"])
            self.assertFalse(record["execution_performed"])
            self.assertTrue(record["lifecycle_is_demo"])

    def test_get_never_recollects_or_rediagnoses_and_bootstrap_is_idempotent(self):
        before = self.state()
        with patch("integration.ui_backend.MockSession.inspect", side_effect=AssertionError("recollection")):
            self.assertEqual(before, self.state())
            self.assertEqual(self.bootstrap(self.client), self.headers)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_origin_host_csrf_and_session_boundaries(self):
        approval = self.state()["approvals"][0]
        url = f'/api/ui/approvals/{approval["id"]}/decision'
        body = {"decision": "approve", "revision": approval["revision"]}
        for headers in ({}, {"Origin": "http://evil.invalid"}, ORIGIN,
                        {**ORIGIN, "X-UI-CSRF": "wrong"}):
            self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/ui/state", headers={"Host": "evil.invalid"}).status_code, 400)
        self.assertEqual(self.new_client().get("/api/ui/state").status_code, 401)
        self.assertEqual(self.state()["approvals"][0]["state"], "pending")

    def test_client_cannot_supply_roles_identity_or_unknown_fields(self):
        item = self.state()["approvals"][0]
        for field in ("actor", "role", "service_id", "authentication", "execution_authorized"):
            body = {"decision": "approve", "revision": item["revision"], field: "forged"}
            self.assertEqual(self.client.post(f'/api/ui/approvals/{item["id"]}/decision',
                             json=body, headers=self.headers).status_code, 422)

    def test_actual_gate_approve_does_not_authorize_or_consume_and_cannot_reverse(self):
        item = self.state()["approvals"][0]
        url = f'/api/ui/approvals/{item["id"]}/decision'
        response = self.client.post(url, json={"decision": "approve", "revision": item["revision"]}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        current = self.state()["approvals"][0]
        self.assertEqual(current["state"], "approved")
        self.assertFalse(current["can_decide"])
        self.assertEqual([e["kind"] for e in current["audit"]], ["approval_requested", "approval_granted"])
        for flag in ("execution_authorized", "execution_performed", "authorization_consumed", "identity_verified"):
            self.assertFalse(response.json()[flag])
        self.client.post(url, json={"decision": "reject", "revision": item["revision"]}, headers=self.headers)
        self.assertEqual(self.state()["approvals"][0]["state"], "approved")

    def test_reject_and_session_isolation(self):
        other = self.new_client()
        other_headers = self.bootstrap(other)
        first = self.state()["approvals"][0]
        second = self.state(other)["approvals"][0]
        self.assertNotEqual(first["id"], second["id"])
        url = f'/api/ui/approvals/{first["id"]}/decision'
        body = {"decision": "reject", "revision": first["revision"]}
        self.assertEqual(other.post(url, json=body, headers=other_headers).status_code, 404)
        self.assertEqual(self.client.post(url, json=body, headers=other_headers).status_code, 403)
        self.assertEqual(self.client.post(url, json=body, headers=self.headers).status_code, 200)
        self.assertEqual(self.state()["approvals"][0]["state"], "rejected")
        self.assertEqual(self.state(other)["approvals"][0]["state"], "pending")

    def test_expiration_is_enforced_by_existing_gate(self):
        item = self.state()["approvals"][0]
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        with patch("integration.ui_backend.datetime") as clock:
            clock.now.return_value = later
            response = self.client.post(f'/api/ui/approvals/{item["id"]}/decision',
                json={"revision": item["revision"], "decision": "approve"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "expired")
        self.assertFalse(response.json()["execution_authorized"])
        self.assertIn("approval_expired", [event["kind"] for event in self.state()["approvals"][0]["audit"]])

    def test_session_count_is_bounded(self):
        for _ in range(7):
            self.bootstrap(self.new_client())
        self.assertEqual(self.new_client().post("/api/ui/session", json={}, headers=ORIGIN).status_code, 429)

    def test_refresh_invalidates_old_revision_and_preserves_historical_audit(self):
        before = self.state()
        record, approval = before["records"][0], before["approvals"][0]
        url = f'/api/ui/reports/{record["id"]}/refresh'
        response = self.client.post(url, json={"revision": record["revision"]}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        after = self.state()
        self.assertNotEqual(after["records"][0]["revision"], record["revision"])
        self.assertEqual(after["records"][1:], before["records"][1:])
        self.assertTrue(after["approvals"][0]["historical"])
        self.assertFalse(after["approvals"][0]["can_decide"])
        for path, body in ((url, {"revision": record["revision"]}),
                           (f'/api/ui/approvals/{approval["id"]}/decision',
                            {"revision": approval["revision"], "decision": "approve"})):
            self.assertEqual(self.client.post(path, json=body, headers=self.headers).status_code, 409)
        new = after["records"][0]
        self.assertEqual(self.client.post(f'/api/ui/reports/{new["id"]}/approval',
                         json={"revision": new["revision"]}, headers=self.headers).status_code, 200)

    def test_export_allowlist_no_prose_logs_auth_or_raw_response(self):
        response = self.client.get("/api/ui/reports/INC-024/export")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"profile", "source", "historical", "report_id", "created_at", "counts",
                                   "capabilities", "authorization_consumed", "execution_authorized",
                                   "execution_performed", "identity_verified", "remediation_verified"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertNotIn(self.headers["X-UI-CSRF"], response.text)

    def test_invalid_body_safe_errors_and_no_executor_route(self):
        secret = "synthetic-secret-never-echo"
        response = self.client.post("/api/ui/session", content=secret, headers={**ORIGIN, "Content-Type": "application/json"})
        self.assertEqual(response.json(), {"error_code": "INVALID_REQUEST"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(secret, response.text)
        self.assertEqual(self.client.post("/api/ui/session", json={"extra": secret}, headers=ORIGIN).status_code, 422)
        self.assertEqual(self.client.post("/api/ui/session", content="x" * 1025,
                         headers={**ORIGIN, "Content-Type": "application/json"}).status_code, 413)
        self.assertEqual(self.client.get("/api/ui/reports/missing/export").status_code, 404)
        self.assertEqual(self.client.post("/api/ui/execute", json={}, headers=self.headers).status_code, 404)

    def test_collection_failure_is_fixed_error_without_traceback(self):
        item = self.state()["records"][0]
        with patch("integration.ui_backend.MockSession.inspect", side_effect=RuntimeError("synthetic-private-text")):
            response = self.client.post('/api/ui/reports/INC-024/refresh', json={"revision": item["revision"]}, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error_code": "UI_UNAVAILABLE"})
        self.assertEqual(self.state()["records"][0], item)

    def test_static_spa_and_api_fallback_separation(self):
        static = self.root / "static"
        static.mkdir()
        (static / "index.html").write_text("<main>Mock UI</main>")
        app = create_ui_app(mock=True, data_directory=self.root, static_directory=static)
        with TestClient(app, base_url="http://localhost") as client:
            self.assertEqual(client.get("/incidents/INC-024").text, "<main>Mock UI</main>")
            self.assertEqual(client.get("/api/unknown").status_code, 404)
            self.assertEqual(client.get("/api").status_code, 404)
            self.assertIn("frame-ancestors 'none'", client.get("/").headers["content-security-policy"])
            self.assertEqual(client.get("/..%2f..%2foutside").status_code, 404)


    def test_expired_sessions_release_capacity_and_deny_old_cookie_without_restart(self):
        from integration.ui_backend import UiSession
        stamp = [1000.0]
        app = create_ui_app(mock=True, data_directory=self.root, clock=lambda: stamp[0], session_ttl=60)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            old_cookie = None
            for _ in range(8):
                client.cookies.clear()
                response = client.post("/api/ui/session", json={}, headers=ORIGIN)
                self.assertEqual(response.status_code, 200)
                old_cookie = old_cookie or client.cookies.get("infrapilot_mock")
            client.cookies.clear()
            self.assertEqual(client.post("/api/ui/session", json={}, headers=ORIGIN).status_code, 429)
            stamp[0] += 61
            client.cookies.set("infrapilot_mock", old_cookie)
            with patch("integration.ui_backend.UiSession.close", autospec=True, side_effect=UiSession.close) as close:
                self.assertEqual(client.get("/api/ui/state").status_code, 401)
                self.assertEqual(close.call_count, 8)
            client.cookies.clear()
            self.assertEqual(client.post("/api/ui/session", json={}, headers=ORIGIN).status_code, 200)
            self.assertEqual(client.get("/api/ui/state").status_code, 200)

    def test_setup_plan_is_durable_scoped_idempotent_and_explicitly_unsupported(self):
        from uuid import uuid4
        from integration.ui_setup import SetupPlans
        body = {"idempotency_key": str(uuid4()), "service_id": "new-mock-service", "platform": "python",
                "plan": "standard-1gb", "custom_domain": "app.example.com", "environment_keys": ["DATABASE_URL"]}
        first = self.client.post("/api/ui/setup-requests", json=body, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        saved = first.json()
        self.assertEqual(saved["brief"]["service_id"], body["service_id"])
        self.assertEqual((saved["operation"], saved["state"]), ("setup_service", "blocked"))
        self.assertFalse(saved["execution_authorized"])
        retry = self.client.post("/api/ui/setup-requests", json=body, headers=self.headers)
        self.assertEqual(retry.json(), saved)
        self.assertEqual(self.state()["setup_requests"], [saved])
        path = next(self.root.iterdir()) / "setup.sqlite"
        self.assertEqual(SetupPlans(path).list(), [saved])
        conflict = self.client.post("/api/ui/setup-requests", json={**body, "service_id": "different-service"}, headers=self.headers)
        self.assertEqual(conflict.status_code, 409)
        other = self.new_client()
        self.bootstrap(other)
        self.assertEqual(self.state(other)["setup_requests"], [])

    def test_expiry_preserves_newer_active_session_and_csrf(self):
        stamp = [1000.0]
        app = create_ui_app(mock=True, data_directory=self.root, clock=lambda: stamp[0], session_ttl=60)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            client.post("/api/ui/session", json={}, headers=ORIGIN)
            expired = client.cookies.get("infrapilot_mock")
            stamp[0] += 50
            client.cookies.clear()
            response = client.post("/api/ui/session", json={}, headers=ORIGIN)
            active = client.cookies.get("infrapilot_mock")
            headers = {**ORIGIN, "X-UI-CSRF": response.json()["csrf"]}
            stamp[0] += 11
            client.cookies.clear()
            client.cookies.set("infrapilot_mock", expired)
            self.assertEqual(client.get("/api/ui/state").status_code, 401)
            client.cookies.clear()
            client.cookies.set("infrapilot_mock", active)
            state = client.get("/api/ui/state").json()
            record = state["records"][0]
            self.assertEqual(client.post(f"/api/ui/reports/{record['id']}/refresh",
                json={"revision": record["revision"]}, headers=headers).status_code, 200)

    def test_setup_rejects_invalid_data_secrets_and_missing_csrf_without_echo(self):
        from uuid import uuid4
        body = {"idempotency_key": str(uuid4()), "service_id": "new-mock-service", "platform": "python", "plan": "standard-1gb"}
        self.assertEqual(self.client.post("/api/ui/setup-requests", json=body, headers=ORIGIN).status_code, 403)
        for patch_value in ({"service_id": "../other"}, {"platform": "unknown"}, {"plan": "production-paid"},
                            {"environment_keys": ["KEY", "KEY"]}, {"custom_domain": "bad..example.com"},
                            {"environment_values": {"DATABASE_URL": "synthetic-private-canary"}}):
            response = self.client.post("/api/ui/setup-requests", json={**body, **patch_value}, headers=self.headers)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn("synthetic-private-canary", response.text)
        self.assertEqual(self.state()["setup_requests"], [])

    def test_setup_uses_existing_planner_and_canonical_retry(self):
        from uuid import uuid4
        from integration.ui_setup import prepare_request
        body = {"idempotency_key": str(uuid4()), "service_id": "planned-mock", "platform": "python",
                "plan": "standard-1gb", "custom_domain": "APP.EXAMPLE.COM", "environment_keys": ["Z_KEY", "A_KEY"]}
        with patch("integration.ui_setup.prepare_request", wraps=prepare_request) as prepare:
            saved = self.client.post("/api/ui/setup-requests", json=body, headers=self.headers).json()
            self.assertTrue(prepare.called)
        self.assertEqual(saved["preparation"]["state"], "blocked")
        self.assertIn("future_execution_handoff", saved["preparation"]["step_keys"])
        self.assertIn("operation_executor", saved["preparation"]["missing_dependencies"])
        retry = self.client.post("/api/ui/setup-requests", json={**body, "custom_domain": "app.example.com",
            "environment_keys": ["A_KEY", "Z_KEY"]}, headers=self.headers)
        self.assertEqual(retry.json(), saved)

    def test_setup_corrupt_retained_records_fail_closed_without_echo(self):
        import sqlite3
        from uuid import uuid4
        body = {"idempotency_key": str(uuid4()), "service_id": "safe-mock", "platform": "python", "plan": "standard-1gb"}
        self.assertEqual(self.client.post("/api/ui/setup-requests", json=body, headers=self.headers).status_code, 200)
        path = next(self.root.iterdir()) / "setup.sqlite"
        from contextlib import closing
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE setup_plans SET payload=?", ('{"secret":"synthetic-private-canary"}',))
        response = self.client.get("/api/ui/state")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("synthetic-private-canary", response.text)

    def test_setup_policy_change_and_size_limit_remain_safe(self):
        from types import SimpleNamespace
        from uuid import uuid4
        body = {"idempotency_key": str(uuid4()), "service_id": "safe-mock", "platform": "python", "plan": "standard-1gb"}
        with patch("integration.ui_setup.ActionPolicy.classify", return_value=SimpleNamespace(allowed=True)):
            response = self.client.post("/api/ui/setup-requests", json=body, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "SETUP_POLICY_CHANGED")
        oversized = self.client.post("/api/ui/setup-requests", content="x" * 4097,
            headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.state()["setup_requests"], [])

    def test_setup_limits_records_but_allows_retry_at_capacity(self):
        from integration.ui_setup import SetupInput, SetupPlans
        from uuid import uuid4
        store = SetupPlans(self.root / "capacity.sqlite")
        first = None
        for _ in range(100):
            body = SetupInput(idempotency_key=str(uuid4()), service_id="safe-mock", platform="python", plan="standard-1gb")
            saved = store.create(body, "2026-10-23T00:00:00+00:00")
            first = first or (body, saved)
        self.assertEqual(store.create(first[0], "2026-10-23T00:00:00+00:00"), first[1])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            store.create(SetupInput(idempotency_key=str(uuid4()), service_id="safe-mock", platform="python", plan="standard-1gb"),
                "2026-10-23T00:00:00+00:00")
        self.assertEqual(caught.exception.status_code, 429)

    def test_setup_rejected_secret_does_not_reach_output_logs_or_database(self):
        import io
        import logging
        from contextlib import redirect_stdout, redirect_stderr
        from uuid import uuid4
        canary = "synthetic-private-canary"
        stdout, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                response = self.client.post("/api/ui/setup-requests", headers=self.headers, json={
                    "idempotency_key": str(uuid4()), "service_id": "safe-mock", "platform": "python", "plan": "standard-1gb",
                    "environment_values": {"DATABASE_URL": canary}})
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual(response.status_code, 422)
        for value in (response.text, stdout.getvalue(), stderr.getvalue(), logs.getvalue()):
            self.assertNotIn(canary, value)
        for path in self.root.rglob("*.sqlite"):
            self.assertNotIn(canary.encode(), path.read_bytes())

    def test_session_bootstrap_does_not_extend_server_expiry(self):
        stamp = [1000.0]
        app = create_ui_app(mock=True, data_directory=self.root, clock=lambda: stamp[0], session_ttl=60)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            first = client.post("/api/ui/session", json={}, headers=ORIGIN)
            csrf = first.json()["csrf"]
            stamp[0] += 50
            retry = client.post("/api/ui/session", json={}, headers=ORIGIN)
            self.assertEqual(retry.json()["csrf"], csrf)
            self.assertIn("Max-Age=10", retry.headers["set-cookie"])
            stamp[0] += 11
            self.assertEqual(client.get("/api/ui/state").status_code, 401)

    def test_multiple_approvals_keep_request_audit_association(self):
        record = self.state()["records"][0]
        response = self.client.post(f'/api/ui/reports/{record["id"]}/approval',
            json={"revision": record["revision"]}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        approvals = self.state()["approvals"]
        self.assertEqual(len(approvals), 2)
        first, second = approvals
        self.client.post(f'/api/ui/approvals/{first["id"]}/decision',
            json={"revision": first["revision"], "decision": "approve"}, headers=self.headers)
        current = {item["id"]: item for item in self.state()["approvals"]}
        self.assertEqual([item["kind"] for item in current[first["id"]]["audit"]], ["approval_requested", "approval_granted"])
        self.assertEqual([item["kind"] for item in current[second["id"]]["audit"]], ["approval_requested"])


if __name__ == "__main__":
    unittest.main()
