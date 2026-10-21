import errno
import http.client
import io
import json
import logging
import socket
import unittest
import urllib.error
import urllib.request
import urllib.response
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timedelta
from email.message import Message
from unittest.mock import MagicMock, patch

from provider import (
    ApiUnavailableError, AuthenticationError, InvalidResponseError, LiaraApiClient,
    LiaraClient, LiaraProviderException, NetworkError, ProviderConfig,
    RateLimitError, ResourceNotFoundError, SecretStr, TimeoutError,
)
from provider.exceptions import InvalidRequestError


TOKEN = "private-liara-token-DO-NOT-PRINT"


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.opener = MagicMock()
        self.builder_patch = patch("provider.client.urllib.request.build_opener", return_value=self.opener)
        self.builder_patch.start()
        self.addCleanup(self.builder_patch.stop)
        self.config = ProviderConfig(TOKEN, timeout=2.5)
        self.client = LiaraClient(self.config)

    def response(self, data=None, *, raw=None, status=200):
        response = MagicMock()
        response.status = status
        response.read.return_value = json.dumps(data).encode() if raw is None else raw
        self.opener.open.return_value.__enter__.return_value = response
        self.opener.open.side_effect = None
        return response

    def test_valid_authentication_and_status(self):
        response = self.response({"projects": [{"project_id": "api", "type": "python"}]})
        with patch("provider.client.time.perf_counter", side_effect=[10, 10.025]):
            result = self.client.ping()
        self.assertTrue(result.success)
        self.assertTrue(result.data.connected)
        self.assertAlmostEqual(result.data.latency_ms, 25)
        self.assertIsNone(result.data.account_email)
        self.assertIsNone(result.error)
        self.assertFalse(result.is_mock)
        self.assertFalse(result.data.is_mock)
        self.assertEqual(datetime.fromisoformat(result.data.timestamp).utcoffset(), timedelta(0))
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.iran.liara.ir/v1/projects")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 2.5})
        response.read.assert_called_once_with(self.client.MAX_RESPONSE_BYTES + 1)
        self.opener.open.return_value.__exit__.assert_called_once()

    def test_projects_are_normalized_and_empty_lists_are_successful(self):
        for data in ({"projects": [{"project_id": "api"}]}, [{"project_id": "api"}], {"projects": []}, []):
            with self.subTest(data=data):
                self.response(data)
                result = self.client.list_projects()
                self.assertTrue(result.success)
                self.assertIsInstance(result.data, list)
                self.assertIsNone(result.error)

    def test_http_error_mapping_and_closure(self):
        cases = (
            (401, "AUTHENTICATION_ERROR", False), (403, "AUTHENTICATION_ERROR", False),
            (404, "RESOURCE_NOT_FOUND", False), (429, "RATE_LIMITED", True),
            (500, "API_UNAVAILABLE", True), (502, "API_UNAVAILABLE", True),
            (503, "API_UNAVAILABLE", True), (504, "API_UNAVAILABLE", True),
            (408, "TIMEOUT", True), (400, "PROVIDER_ERROR", False),
            (418, "PROVIDER_ERROR", False), (302, "PROVIDER_ERROR", False),
        )
        for status, code, retryable in cases:
            with self.subTest(status=status):
                body = io.BytesIO(TOKEN.encode())
                self.opener.open.side_effect = urllib.error.HTTPError(
                    "https://example.invalid/" + TOKEN, status, TOKEN, {}, body,
                )
                result = self.client.list_projects()
                self.assertFalse(result.success)
                self.assertIsNone(result.data)
                self.assertEqual(result.error.code, code)
                self.assertEqual(result.error.http_status, status)
                self.assertEqual(result.error.retryable, retryable)
                self.assertNotIn(TOKEN, repr(result))
                self.assertTrue(body.closed)

    def test_non_success_status_without_http_error_is_also_mapped(self):
        response = self.response(raw=TOKEN.encode(), status=403)
        result = self.client.list_projects()
        self.assertEqual(result.error.code, "AUTHENTICATION_ERROR")
        response.read.assert_not_called()

    def test_socket_url_and_connection_timeouts(self):
        errors = (
            socket.timeout(TOKEN), urllib.error.URLError(socket.timeout(TOKEN)),
            OSError(errno.ETIMEDOUT, TOKEN),
            urllib.error.URLError(OSError(errno.ETIMEDOUT, TOKEN)),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.opener.open.side_effect = error
                result = self.client.ping()
                self.assertFalse(result.success)
                self.assertFalse(result.data.connected)
                self.assertEqual(result.error.code, "TIMEOUT")
                self.assertIsNone(result.error.http_status)
                self.assertTrue(result.error.retryable)
                self.assertNotIn(TOKEN, repr(result))

    def test_network_and_protocol_failures(self):
        cases = (
            (urllib.error.URLError(TOKEN), "NETWORK_ERROR"),
            (ConnectionResetError(TOKEN), "NETWORK_ERROR"),
            (http.client.IncompleteRead(TOKEN.encode()), "INVALID_RESPONSE"),
        )
        for error, code in cases:
            with self.subTest(code=code):
                self.opener.open.side_effect = error
                result = self.client.list_projects()
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, code)
                self.assertNotIn(TOKEN, repr(result))

    def test_timeout_during_response_read_is_handled_and_response_closed(self):
        response = self.response({"projects": []})
        response.read.side_effect = socket.timeout(TOKEN)
        self.assertEqual(self.client.list_projects().error.code, "TIMEOUT")
        self.opener.open.return_value.__exit__.assert_called_once()

    def test_malformed_empty_nonfinite_and_oversized_json_are_rejected(self):
        for raw in (b"", b"not-json", b"\xff", b'{"projects": NaN}', b'{"projects": Infinity}'):
            with self.subTest(raw=raw):
                self.response(raw=raw)
                result = self.client.list_projects()
                self.assertFalse(result.success)
                self.assertEqual(result.error.code, "INVALID_RESPONSE")
        self.response(raw=b"x" * 9)
        with patch.object(self.client, "MAX_RESPONSE_BYTES", 8):
            self.assertEqual(self.client.list_projects().error.code, "INVALID_RESPONSE")

    def test_unexpected_project_shapes_cannot_authenticate(self):
        for data in (None, {}, {"projects": None}, {"projects": {}}, {"projects": [1]}, "ok", 1):
            with self.subTest(data=data):
                self.response(data)
                result = self.client.ping()
                self.assertFalse(result.success)
                self.assertFalse(result.data.connected)
                self.assertEqual(result.error.code, "INVALID_RESPONSE")

    def test_no_content_is_valid_transport_but_not_a_project_list(self):
        for status in (204, 205):
            self.response(raw=b"", status=status)
            self.assertTrue(self.client._request("GET", "/v1/example").success)
            self.assertEqual(self.client.list_projects().error.code, "INVALID_RESPONSE")

    def test_query_payload_and_custom_base_url(self):
        client = LiaraClient(ProviderConfig(TOKEN, base_url="https://example.invalid/api/"))
        self.response({"ok": True})
        result = client._request("post", "/v1/example", {"q": "a & b", "id": [1, 2]}, {"hello": "world"})
        self.assertTrue(result.success)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/api/v1/example?q=a+%26+b&id=1&id=2")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"hello": "world"})
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_invalid_requests_make_no_network_call(self):
        cases = (
            {"method": "INVALID"}, {"method": None},
            {"endpoint": "https://evil.invalid/"}, {"endpoint": "//evil.invalid/"},
            {"endpoint": "/\\evil.invalid/"}, {"endpoint": "/x?token=" + TOKEN},
            {"endpoint": "/x#fragment"}, {"endpoint": "/x\r\nInjected: yes"},
            {"endpoint": "relative"}, {"endpoint": None},
            {"params": ["invalid"]}, {"payload": object()}, {"payload": float("nan")},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                arguments = {"method": "GET", "endpoint": "/v1/projects", **overrides}
                result = self.client._request(**arguments)
                self.assertEqual(result.error.code, "INVALID_REQUEST")
        self.opener.open.assert_not_called()

    def test_echoed_token_is_redacted_from_nested_data_and_keys(self):
        self.response({"projects": [{"name": TOKEN, TOKEN: ["Bearer " + TOKEN]}]})
        result = self.client.list_projects()
        self.assertTrue(result.success)
        self.assertNotIn(TOKEN, repr(result))
        self.assertNotIn(TOKEN, json.dumps(asdict(result)))
        self.assertEqual(result.data[0]["name"], "**********")

    def test_client_never_prints_raw_http_or_transport_errors(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            for error in (urllib.error.HTTPError("https://invalid/" + TOKEN, 401, TOKEN, {}, io.BytesIO()),
                          urllib.error.URLError(TOKEN)):
                self.opener.open.side_effect = error
                self.client.ping()
        self.assertEqual(output.getvalue(), "")


class CredentialAndExceptionTests(unittest.TestCase):
    def test_config_and_secret_are_safe_to_format_log_and_convert(self):
        config = ProviderConfig(TOKEN)
        output = io.StringIO()
        logger = logging.Logger("provider-test")
        logger.addHandler(logging.StreamHandler(output))
        logger.warning("config=%s repr=%r secret=%s", config, config, config.api_key)
        for text in (output.getvalue(), str(config), repr(config), str(config.api_key),
                     repr(config.api_key), repr(asdict(config)), json.dumps(config.to_dict())):
            self.assertNotIn(TOKEN, text)
        self.assertEqual(config.api_key.get_secret_value(), TOKEN)
        self.assertIn("**********", str(config))
        with self.assertRaises(FrozenInstanceError):
            config.timeout = 3
        with self.assertRaises(TypeError):
            json.dumps(asdict(config))

    def test_config_defaults_and_client_alias(self):
        config = ProviderConfig(TOKEN)
        self.assertEqual(config.base_url, "https://api.iran.liara.ir")
        self.assertEqual(config.timeout, 10.0)
        self.assertFalse(config.is_mock)
        self.assertIs(LiaraApiClient, LiaraClient)
        self.assertIsInstance(ProviderConfig(SecretStr(TOKEN)).api_key, SecretStr)

    def test_invalid_config_errors_do_not_echo_values(self):
        cases = (
            {"api_key": ""}, {"api_key": None}, {"api_key": "Bearer " + TOKEN},
            {"api_key": TOKEN + "\r\nHeader: injected"}, {"api_key": "non-ascii-\u2603"},
            {"base_url": "http://example.invalid/" + TOKEN},
            {"base_url": "https://" + TOKEN + "@example.invalid"},
            {"base_url": "https://example.invalid/?key=" + TOKEN},
            {"base_url": "https://example.invalid/#" + TOKEN},
            {"base_url": "https://example.invalid/\n" + TOKEN},
            {"base_url": "https://example.invalid:bad"},
            {"base_url": "https://example.invalid:0"},
            {"base_url": "https://[invalid"}, {"base_url": None},
            {"timeout": 0}, {"timeout": -1}, {"timeout": float("nan")},
            {"timeout": float("inf")}, {"timeout": True}, {"timeout": TOKEN},
            {"timeout": 10 ** 500},
            {"is_mock": "yes"},
        )
        for values in cases:
            with self.subTest(fields=list(values)), self.assertRaises(ValueError) as raised:
                ProviderConfig(**{"api_key": TOKEN, **values})
            self.assertNotIn(TOKEN, str(raised.exception))

    def test_every_exception_discards_untrusted_message(self):
        for cls in (LiaraProviderException, AuthenticationError, RateLimitError, TimeoutError,
                    ApiUnavailableError, ResourceNotFoundError, NetworkError, InvalidResponseError,
                    InvalidRequestError):
            with self.subTest(exception=cls.__name__):
                error = cls("Authorization: Bearer " + TOKEN)
                self.assertIsInstance(error, LiaraProviderException)
                for value in (str(error), repr(error), repr(error.args), repr(vars(error)), repr(error.to_error())):
                    self.assertNotIn(TOKEN, value)
                output = io.StringIO()
                logger = logging.Logger("provider-exception-test")
                logger.addHandler(logging.StreamHandler(output))
                logger.error("error=%s repr=%r", error, error)
                self.assertNotIn(TOKEN, output.getvalue())
                self.assertEqual(error.to_error().code, cls.code)
                self.assertEqual(error.to_error().retryable, cls.retryable)
        self.assertEqual(AuthenticationError(http_status=403).to_error().http_status, 403)
        self.assertIsNone(AuthenticationError(http_status=TOKEN).to_error().http_status)


class RedirectTests(unittest.TestCase):
    def test_actual_urllib_redirect_pipeline_does_not_forward_credentials(self):
        # Exercise urllib's real redirect handling without starting a server.
        for code in (301, 302, 303, 307, 308):
            for location in ("https://evil.invalid/collect", "http://evil.invalid/collect", "/other"):
                with self.subTest(code=code, location=location):
                    headers = Message()
                    headers["Location"] = location
                    response = urllib.response.addinfourl(io.BytesIO(), headers, "https://api.iran.liara.ir/v1/projects", code)
                    response.msg = "Redirect"
                    with patch.object(urllib.request.HTTPSHandler, "https_open", return_value=response) as send:
                        result = LiaraClient(ProviderConfig(TOKEN)).list_projects()
                    self.assertFalse(result.success)
                    self.assertEqual(result.error.http_status, code)
                    send.assert_called_once()
                    self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
