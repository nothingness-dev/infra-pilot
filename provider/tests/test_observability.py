"""Provider-local observations tested at the existing urllib boundary."""

from dataclasses import asdict
from datetime import datetime
from email.message import Message
import io
import json
import socket
import unittest
import urllib.error
import urllib.response
from unittest.mock import MagicMock, patch

from provider import LiaraClient, MockLiaraClient, ProviderConfig


TOKEN = "private-observability-test-token"
SINCE = "2026-01-01T00:00:00Z"


class ObservationClientTests(unittest.TestCase):
    def setUp(self):
        self.opener = MagicMock()
        guard = patch("provider.client.urllib.request.build_opener", return_value=self.opener)
        guard.start()
        self.addCleanup(guard.stop)
        self.client = LiaraClient(ProviderConfig(TOKEN))

    def response(self, data=None, *, raw=None):
        body = json.dumps(data).encode() if raw is None else raw
        response = urllib.response.addinfourl(io.BytesIO(body), Message(), "https://example.invalid", 200)
        self.opener.open.side_effect = None
        self.opener.open.return_value = response
        return response

    def methods(self):
        return (
            lambda: self.client.get_service("api"),
            lambda: self.client.get_deployment_status("api"),
            lambda: self.client.get_logs("api", since=SINCE),
            lambda: self.client.get_metrics("api"),
            lambda: self.client.list_releases("api"),
        )

    def test_service_fields_are_selected_and_environment_secrets_are_omitted(self):
        response = self.response({"project": {
            "_id": "provider-id", "project_id": "api", "status": "native-state",
            "type": "python", "isDeployed": False,
            "envs": [{"key": "PASSWORD", "value": "environment-private-secret"}],
            "unknown": "environment-private-secret",
        }})
        result = self.client.get_service("api")
        self.assertTrue(result.success)
        self.assertFalse(result.is_mock)
        self.assertEqual(result.data.provider_id, "provider-id")
        self.assertEqual(result.data.native_status, "native-state")
        self.assertIs(result.data.is_deployed, False)
        self.assertNotIn("environment-private-secret", repr(result))
        self.assertNotIn("envs", json.dumps(asdict(result)))
        self.assertTrue(response.closed)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.iran.liara.ir/v1/projects/api")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)

    def test_project_identity_mismatch_is_rejected(self):
        self.response({"project": {"project_id": "other-service", "status": "running"}})
        self.assertEqual(self.client.get_service("api").error.code, "INVALID_RESPONSE")

    def test_deployment_preserves_native_status_and_false_flag(self):
        self.response({"project": {"isDeployed": False, "status": "unknown-native-state"}})
        result = self.client.get_deployment_status("api")
        self.assertTrue(result.success)
        self.assertIs(result.data.is_deployed, False)
        self.assertEqual(result.data.native_status, "unknown-native-state")
        self.assertFalse(hasattr(result.data, "healthy"))
        self.opener.open.assert_called_once()

    def test_logs_keep_source_strings_and_encode_since_as_a_query_value(self):
        self.response([{"message": "message", "type": "native-level", "datetime": "opaque-time"}, {}])
        result = self.client.get_logs("api", since="opaque since & query=yes")
        self.assertTrue(result.success)
        self.assertEqual(result.data[0].native_datetime, "opaque-time")
        self.assertEqual(result.data[0].native_type, "native-level")
        self.assertIsNone(result.data[1].message)
        self.assertIn("?since=opaque+since+%26+query%3Dyes", self.opener.open.call_args.args[0].full_url)

    def test_metrics_preserve_zero_strings_series_and_unknown_units(self):
        self.response({
            "cpuUsage": [{"applet": "a", "value": [0, "0", 0.25]}, {}],
            "memoryUsage": [], "disksUsage": [{"name": "disk", "size": "12", "usage": "0"}],
        })
        result = self.client.get_metrics("api")
        self.assertTrue(result.success)
        self.assertEqual(result.data.cpu_usage[0].values, (0, "0", 0.25))
        self.assertIsNone(result.data.cpu_usage[1].values)
        self.assertEqual(result.data.memory_usage, ())
        self.assertEqual(result.data.disks_usage[0].usage, "0")
        self.assertIsNone(result.data.cpu_unit)
        self.assertIsNone(result.data.memory_unit)
        self.assertIsNone(result.data.disk_unit)
        json.dumps(asdict(result), allow_nan=False)

    def test_release_page_preserves_order_native_states_and_metadata(self):
        self.response({"releases": [
            {"_id": "second", "state": "unknown-state", "createdAt": "source-time"},
            {"_id": "first", "state": "another-state", "envs": {"SECRET": TOKEN}},
        ], "total": 12, "currentRelease": "first", "readyReleasesCount": 0})
        result = self.client.list_releases("api", page=2, count=5)
        self.assertTrue(result.success)
        self.assertEqual([item.provider_id for item in result.data.releases], ["second", "first"])
        self.assertEqual(result.data.releases[0].native_state, "unknown-state")
        self.assertEqual(result.data.ready_releases_count, 0)
        self.assertEqual(result.data.current_release, "first")
        self.assertEqual((result.data.page, result.data.count), (2, 5))
        self.assertTrue(self.opener.open.call_args.args[0].full_url.endswith("/releases?page=2&count=5"))

    def test_explicit_missing_data_remains_none(self):
        for method in self.methods():
            with self.subTest(method=method):
                self.response(None)
                result = method()
                self.assertTrue(result.success)
                self.assertIsNone(result.data)
        for payload, method in (
            ({"project": {}}, lambda: self.client.get_service("api")),
            ({"project": {"_id": "id"}}, lambda: self.client.get_deployment_status("api")),
            ({}, lambda: self.client.get_metrics("api")),
            ({}, lambda: self.client.list_releases("api")),
        ):
            self.response(payload)
            self.assertIsNone(method().data)

    def test_empty_collections_remain_available_empty_collections(self):
        self.response([])
        self.assertEqual(self.client.get_logs("api", since=SINCE).data, [])
        self.response({"releases": [], "total": 0})
        self.assertEqual(self.client.list_releases("api").data.releases, ())
        self.response({"cpuUsage": [], "memoryUsage": []})
        result = self.client.get_metrics("api")
        self.assertEqual(result.data.cpu_usage, ())
        self.assertIsNone(result.data.disks_usage)

    def test_every_observation_method_maps_http_failures_without_secret_echo(self):
        for method in self.methods():
            for status, code in ((401, "AUTHENTICATION_ERROR"), (403, "AUTHENTICATION_ERROR"),
                                 (404, "RESOURCE_NOT_FOUND"), (429, "RATE_LIMITED"),
                                 (500, "API_UNAVAILABLE"), (502, "API_UNAVAILABLE"),
                                 (503, "API_UNAVAILABLE"), (504, "API_UNAVAILABLE")):
                with self.subTest(status=status, method=method):
                    self.opener.open.side_effect = urllib.error.HTTPError(
                        "https://example.invalid/" + TOKEN, status, TOKEN, {}, io.BytesIO(TOKEN.encode()),
                    )
                    result = method()
                    self.assertFalse(result.success)
                    self.assertEqual(result.error.code, code)
                    self.assertEqual(result.error.http_status, status)
                    self.assertNotIn(TOKEN, repr(result))
                    self.assertIsNone(result.data)

    def test_every_observation_method_handles_timeout_bad_json_and_network_failure(self):
        for method in self.methods():
            for error, code in (
                (socket.timeout(TOKEN), "TIMEOUT"),
                (urllib.error.URLError(socket.timeout(TOKEN)), "TIMEOUT"),
                (urllib.error.URLError(TOKEN), "NETWORK_ERROR"),
            ):
                self.opener.open.side_effect = error
                result = method()
                self.assertEqual(result.error.code, code)
                self.assertNotIn(TOKEN, repr(result))
            self.response(raw=TOKEN.encode())
            self.assertEqual(method().error.code, "INVALID_RESPONSE")

    def test_invalid_payload_shapes_are_structured_failures(self):
        cases = (
            ({}, lambda: self.client.get_service("api")),
            ({"project": []}, lambda: self.client.get_service("api")),
            ({"project": {"isDeployed": "false"}}, lambda: self.client.get_deployment_status("api")),
            ({"project": {"status": 1}}, lambda: self.client.get_service("api")),
            ({"logs": []}, lambda: self.client.get_logs("api", since=SINCE)),
            ([1], lambda: self.client.get_logs("api", since=SINCE)),
            ([{"message": 1}], lambda: self.client.get_logs("api", since=SINCE)),
            ([], lambda: self.client.get_metrics("api")),
            ({"cpuUsage": {}}, lambda: self.client.get_metrics("api")),
            ({"cpuUsage": [1]}, lambda: self.client.get_metrics("api")),
            ({"cpuUsage": [{"value": [True]}]}, lambda: self.client.get_metrics("api")),
            ({"cpuUsage": [{"value": [[1]]}]}, lambda: self.client.get_metrics("api")),
            ({"memoryUsage": [{"applet": 1}]}, lambda: self.client.get_metrics("api")),
            ({"disksUsage": [{"usage": 0}]}, lambda: self.client.get_metrics("api")),
            ({"releases": [1]}, lambda: self.client.list_releases("api")),
            ({"releases": [{"state": False}]}, lambda: self.client.list_releases("api")),
            ({"total": True}, lambda: self.client.list_releases("api")),
            ({"total": -1}, lambda: self.client.list_releases("api")),
        )
        for data, method in cases:
            with self.subTest(data=data):
                self.response(data)
                self.assertEqual(method().error.code, "INVALID_RESPONSE")

    def test_invalid_arguments_do_not_make_network_requests(self):
        for name in (None, [], 1, "", " ", ".", "..", "api\n", "api\x7f", "\ud800"):
            for call in (
                lambda: self.client.get_service(name), lambda: self.client.get_deployment_status(name),
                lambda: self.client.get_logs(name, since=SINCE), lambda: self.client.get_metrics(name),
                lambda: self.client.list_releases(name), lambda: self.client.collect_service_observations(name),
            ):
                self.assertEqual(call().error.code, "INVALID_REQUEST")
        for since in (None, "", " ", 1, []):
            self.assertEqual(self.client.get_logs("api", since=since).error.code, "INVALID_REQUEST")
        for page, count in ((0, 10), (True, 10), (1, False), (1.0, 2), (1, -1)):
            self.assertEqual(self.client.list_releases("api", page=page, count=count).error.code, "INVALID_REQUEST")
        for kwargs in ({"include_metrics": 1}, {"logs_since": ""}, {"logs_since": []}):
            self.assertEqual(self.client.collect_service_observations("api", **kwargs).error.code, "INVALID_REQUEST")
        self.opener.open.assert_not_called()

    def test_service_name_is_a_single_encoded_path_component(self):
        self.response({"project": {"_id": "id"}})
        self.client.get_service("a/b?c#d %")
        self.assertTrue(self.opener.open.call_args.args[0].full_url.endswith("/a%2Fb%3Fc%23d%20%25"))

    def test_large_log_response_is_rejected_instead_of_silently_truncated(self):
        response = self.response([{"message": "large log message"}])
        with patch.object(self.client, "MAX_RESPONSE_BYTES", 8):
            result = self.client.get_logs("api", since=SINCE)
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "INVALID_RESPONSE")
        self.assertIsNone(result.data)
        self.assertTrue(response.closed)

    def test_token_echo_is_redacted_from_each_new_result(self):
        cases = (
            ({"project": {"_id": TOKEN, "status": TOKEN}}, lambda: self.client.get_service(TOKEN)),
            ({"project": {"status": TOKEN}}, lambda: self.client.get_deployment_status(TOKEN)),
            ([{"message": "Bearer " + TOKEN, "datetime": TOKEN}], lambda: self.client.get_logs(TOKEN, since=TOKEN)),
            ({"cpuUsage": [{"applet": TOKEN, "value": [TOKEN]}]}, lambda: self.client.get_metrics(TOKEN)),
            ({"releases": [{"_id": TOKEN}], "currentRelease": TOKEN}, lambda: self.client.list_releases(TOKEN)),
        )
        for data, method in cases:
            self.response(data)
            result = method()
            self.assertTrue(result.success)
            self.assertNotIn(TOKEN, str(result))
            self.assertNotIn(TOKEN, json.dumps(asdict(result), allow_nan=False))

    def test_real_transport_collection_preserves_valid_data_after_log_failure(self):
        def send(request, **kwargs):
            if request.full_url.endswith("/logs?since=" + SINCE.replace(":", "%3A")):
                raise urllib.error.HTTPError(request.full_url, 403, TOKEN, {}, io.BytesIO())
            data = {"cpuUsage": []} if request.full_url.endswith("/metrics/summary") else {"project": {"isDeployed": False}}
            return urllib.response.addinfourl(io.BytesIO(json.dumps(data).encode()), Message(), request.full_url, 200)
        self.opener.open.side_effect = send
        result = self.client.collect_service_observations("api", logs_since=SINCE)
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "PARTIAL_COLLECTION")
        self.assertFalse(result.is_mock)
        self.assertEqual(result.data.logs.availability, "permission_denied")
        self.assertEqual(result.data.logs.error.http_status, 403)
        self.assertIs(result.data.deployment.data.is_deployed, False)
        self.assertEqual(result.data.metrics.availability, "available")
        self.assertEqual(self.opener.open.call_count, 3)
        self.assertNotIn(TOKEN, repr(result))


class OfflineObservationTests(unittest.TestCase):
    def setUp(self):
        for target in ("provider.client.urllib.request.build_opener", "provider.client.urllib.request.Request", "socket.socket"):
            guard = patch(target, side_effect=AssertionError("Offline clients must not access transport"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_all_new_methods_are_offline_and_labelled_mock(self):
        for client in (MockLiaraClient(), LiaraClient(ProviderConfig("", is_mock=True))):
            for result in (client.get_service("api"), client.get_deployment_status("api"),
                           client.get_logs("api", since=SINCE), client.get_metrics("api"),
                           client.list_releases("api"), client.collect_service_observations("api", logs_since=SINCE)):
                self.assertTrue(result.success)
                self.assertTrue(result.is_mock)
                json.dumps(asdict(result), allow_nan=False)

    def test_default_collection_skips_logs_and_derives_deployment_without_extra_request(self):
        client = MockLiaraClient()
        with patch.object(client, "_request", wraps=client._request) as request:
            result = client.collect_service_observations("api", include_metrics=False)
        self.assertTrue(result.success)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result.data.logs.availability, "not_collected")
        self.assertIsNone(result.data.logs.collected_at)
        self.assertEqual(result.data.metrics.availability, "not_collected")
        self.assertEqual(result.data.service.collected_at, result.data.deployment.collected_at)

    def test_partial_failure_keeps_valid_observations(self):
        client = MockLiaraClient(failure_modes={"logs": 403, "metrics": "timeout"})
        result = client.collect_service_observations("api", logs_since=SINCE)
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "PARTIAL_COLLECTION")
        self.assertTrue(result.error.retryable)
        self.assertTrue(result.is_mock)
        self.assertTrue(result.data.is_mock)
        self.assertEqual(result.data.service.availability, "available")
        self.assertEqual(result.data.deployment.availability, "available")
        self.assertEqual(result.data.logs.availability, "permission_denied")
        self.assertEqual(result.data.metrics.error.code, "TIMEOUT")
        self.assertIsNone(result.data.logs.data)

    def test_401_403_404_and_missing_are_not_reported_as_unsupported(self):
        for mode, state in ((401, "authentication_failed"), (403, "permission_denied"),
                            (404, "not_found"), (429, "failed"), ("missing", "unavailable")):
            result = MockLiaraClient(failure_mode=mode).collect_service_observations("api", logs_since=SINCE)
            self.assertFalse(result.success)
            self.assertEqual(result.error.code, "COLLECTION_FAILED")
            for component in (result.data.service, result.data.deployment, result.data.logs, result.data.metrics):
                self.assertEqual(component.availability, state)
                self.assertTrue(component.is_mock)
                self.assertIsNone(component.data)

    def test_empty_observation_arrays_are_distinct_from_unavailable_data(self):
        result = MockLiaraClient(failure_mode="empty").collect_service_observations("api", logs_since=SINCE)
        self.assertEqual(result.data.service.availability, "unavailable")
        self.assertEqual(result.data.logs.availability, "available")
        self.assertEqual(result.data.logs.data, [])
        self.assertEqual(result.data.metrics.data.cpu_usage, ())

    def test_per_capability_modes_copy_input_and_can_override_global_failure(self):
        modes = {"service": None, "metrics": "missing"}
        client = MockLiaraClient(failure_mode=401, failure_modes=modes)
        modes["service"] = 503
        result = client.collect_service_observations("api")
        self.assertEqual(result.data.service.availability, "available")
        self.assertEqual(result.data.metrics.availability, "unavailable")

    def test_mock_release_pagination_and_fresh_results(self):
        client = MockLiaraClient()
        first, second = client.list_releases("api", count=1), client.list_releases("api", page=2, count=1)
        self.assertNotEqual(first.data.releases[0].provider_id, second.data.releases[0].provider_id)
        self.assertEqual(client.list_releases("api", page=3, count=1).data.releases, ())
        logs = client.get_logs("api", since=SINCE).data
        logs.clear()
        self.assertEqual(len(client.get_logs("api", since=SINCE).data), 1)

    def test_invalid_mock_modes_and_mappings_have_safe_errors(self):
        for modes in ([], "secret", {"unknown-secret": 401}, {"logs": "unknown-secret"}):
            with self.assertRaises(ValueError) as raised:
                MockLiaraClient(failure_modes=modes)
            self.assertNotIn("secret", str(raised.exception))

    def test_raw_mock_requests_with_missing_required_query_return_errors(self):
        client = MockLiaraClient()
        for endpoint, params in (
            ("/v1/projects/api/releases", None),
            ("/v1/projects/api/releases", {"page": 1}),
            ("/v1/projects/api/logs", None),
            ("/v1/projects/api/logs", {"since": ""}),
        ):
            result = client._request("GET", endpoint, params=params)
            self.assertFalse(result.success)
            self.assertTrue(result.is_mock)
            self.assertEqual(result.error.code, "INVALID_REQUEST")

    def test_collection_times_are_aware_and_all_nested_data_remains_redacted(self):
        result = MockLiaraClient(ProviderConfig(TOKEN)).collect_service_observations(TOKEN, logs_since=TOKEN)
        self.assertNotIn(TOKEN, repr(result))
        self.assertNotIn(TOKEN, json.dumps(asdict(result), allow_nan=False))
        for timestamp in (result.data.collection_started_at, result.data.collection_finished_at,
                          result.data.service.collected_at, result.data.logs.collected_at, result.data.metrics.collected_at):
            self.assertIsNotNone(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo)

    def test_invalid_response_modes_are_reported_for_each_capability(self):
        client = MockLiaraClient(failure_mode="invalid_response")
        for result in (client.get_service("api"), client.get_deployment_status("api"),
                       client.get_logs("api", since=SINCE), client.get_metrics("api"), client.list_releases("api")):
            self.assertFalse(result.success)
            self.assertEqual(result.error.code, "INVALID_RESPONSE")
            self.assertTrue(result.is_mock)


if __name__ == "__main__":
    unittest.main()
