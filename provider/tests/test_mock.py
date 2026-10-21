import unittest
from dataclasses import replace
from unittest.mock import patch

from provider import LiaraClient, MockLiaraClient, ProviderConfig


class MockClientTests(unittest.TestCase):
    def setUp(self):
        # Any accidental urllib construction or socket access fails the test.
        for target in ("provider.client.urllib.request.build_opener", "socket.socket"):
            guard = patch(target, side_effect=AssertionError("Mock must remain offline"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_default_mock_ping_and_projects_work_without_credentials(self):
        client = MockLiaraClient()
        projects = client.list_projects()
        ping = client.ping()
        self.assertTrue(projects.success)
        self.assertTrue(projects.is_mock)
        self.assertEqual(len(projects.data), 2)
        self.assertEqual(projects.data[0]["project_id"], "infrapilot-api")
        self.assertTrue(ping.success)
        self.assertTrue(ping.data.connected)
        self.assertTrue(ping.is_mock)
        self.assertTrue(ping.data.is_mock)
        self.assertIsNone(ping.data.account_email)
        self.assertIsNone(ping.error)

    def test_mock_flag_on_regular_client_has_identical_offline_behavior(self):
        client = LiaraClient(ProviderConfig("", is_mock=True))
        self.assertTrue(client.list_projects().is_mock)
        self.assertTrue(client.ping().data.connected)

    def test_live_config_is_copied_and_forced_to_mock(self):
        config = ProviderConfig("private-token")
        client = MockLiaraClient(config)
        self.assertFalse(config.is_mock)
        self.assertTrue(client.config.is_mock)
        self.assertTrue(client.list_projects().is_mock)
        self.assertEqual(config, replace(client.config, is_mock=False))

    def test_named_failures_and_http_statuses_are_structured(self):
        cases = (
            ("unauthorized", "AUTHENTICATION_ERROR", 401, False),
            ("forbidden", "AUTHENTICATION_ERROR", 403, False),
            ("rate_limit", "RATE_LIMITED", 429, True),
            ("not_found", "RESOURCE_NOT_FOUND", 404, False),
            ("unavailable", "API_UNAVAILABLE", 503, True),
            ("timeout", "TIMEOUT", None, True),
            (401, "AUTHENTICATION_ERROR", 401, False),
            (504, "API_UNAVAILABLE", 504, True),
            (400, "PROVIDER_ERROR", 400, False),
        )
        for mode, code, status, retryable in cases:
            with self.subTest(mode=mode):
                client = MockLiaraClient(failure_mode=mode)
                for result in (client.list_projects(), client.ping()):
                    self.assertFalse(result.success)
                    self.assertTrue(result.is_mock)
                    self.assertEqual(result.error.code, code)
                    self.assertEqual(result.error.http_status, status)
                    self.assertEqual(result.error.retryable, retryable)
                self.assertFalse(client.ping().data.connected)
                self.assertTrue(client.ping().data.is_mock)

    def test_empty_account_is_connected_with_no_projects(self):
        client = MockLiaraClient(failure_mode="empty")
        self.assertEqual(client.list_projects().data, [])
        self.assertTrue(client.ping().data.connected)
        self.assertTrue(client.list_projects().is_mock)

    def test_fixtures_are_fresh_on_each_call_and_between_clients(self):
        client = MockLiaraClient()
        first = client.list_projects().data
        first[0]["project_id"] = "changed"
        first.clear()
        self.assertEqual(client.list_projects().data[0]["project_id"], "infrapilot-api")
        self.assertEqual(MockLiaraClient().list_projects().data[0]["project_id"], "infrapilot-api")

    def test_unknown_mock_endpoint_and_invalid_request_are_marked_mock(self):
        client = MockLiaraClient()
        for method, endpoint, code in (
            ("GET", "/missing", "RESOURCE_NOT_FOUND"),
            ("POST", "/v1/projects", "RESOURCE_NOT_FOUND"),
            ("GET", "https://evil.invalid/", "INVALID_REQUEST"),
        ):
            result = client._request(method, endpoint)
            self.assertTrue(result.is_mock)
            self.assertEqual(result.error.code, code)

    def test_invalid_mode_or_config_is_rejected_with_safe_message(self):
        for mode in ("secret-invalid-mode", 200, 600, True, [], {}):
            with self.subTest(mode=mode), self.assertRaises(ValueError) as raised:
                MockLiaraClient(failure_mode=mode)
            self.assertNotIn("secret-invalid-mode", str(raised.exception))
        for cls in (LiaraClient, MockLiaraClient):
            with self.assertRaises(ValueError):
                cls("secret-invalid-config")


if __name__ == "__main__":
    unittest.main()
