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


if __name__ == "__main__":
    unittest.main()
