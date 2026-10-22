"""Smoke-runner tests never require credentials or network access."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from email.message import Message
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
import urllib.response
from unittest.mock import MagicMock, patch

from provider import LiaraClient, ProviderResult, StructuredError
from provider.examples import live_smoke


TOKEN = "private-live-smoke-test-token"
PROJECT = "private-project-name"
RAW_LOG = "private-application-log-content"
RAW_ENV = "private-application-password"
SINCE = "2026-01-01T00:00:00Z"
METHODS = {
    "service": "get_service", "deployment": "get_deployment_status", "logs": "get_logs",
    "metrics": "get_metrics", "releases": "list_releases",
}


class LiveSmokeTests(unittest.TestCase):
    def setUp(self):
        guard = patch("socket.socket", side_effect=AssertionError("Smoke tests must remain offline"))
        guard.start()
        self.addCleanup(guard.stop)
        factory = patch("provider.examples.live_smoke.LiaraClient")
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.client = MagicMock(spec=LiaraClient)
        self.factory.return_value = self.client
        self.environment = {"LIARA_API_TOKEN": TOKEN, "LIARA_PROJECT_NAME": PROJECT, "LIARA_LOGS_SINCE": SINCE}
        self.reset_results()

    def reset_results(self):
        self.client.reset_mock()
        for method in METHODS.values():
            call = getattr(self.client, method)
            call.side_effect = None
            call.return_value = ProviderResult(True, {
                "Authorization": "Bearer " + TOKEN, "logs": [RAW_LOG],
                "envs": {"PASSWORD": RAW_ENV},
            })

    def invoke(self, environment=None, argv=()):
        stdout, stderr = io.StringIO(), io.StringIO()
        # Supply a plain mapping so invalid Unicode can be tested even on OSes
        # whose native environment rejects it before our validation runs.
        with patch.object(live_smoke.os, "environ", dict(self.environment if environment is None else environment)):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = live_smoke.main(argv)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["exit_code"], code)
        for secret in (TOKEN, PROJECT, RAW_LOG, RAW_ENV, SINCE, "Authorization", "Bearer"):
            self.assertNotIn(secret, stdout.getvalue())
            self.assertNotIn(secret, repr(report))
        return code, report

    def test_full_success_emits_only_allowlisted_summary_fields(self):
        code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(set(report), {"status", "exit_code", "checks"})
        self.assertEqual([item["capability"] for item in report["checks"]], list(METHODS))
        for check in report["checks"]:
            self.assertEqual(set(check), {"capability", "status", "error_code", "http_status", "checked_at", "duration_ms"})
            self.assertEqual(check["status"], "available")
            self.assertIsNone(check["error_code"])
            # Successful ProviderResult does not expose an HTTP response status.
            self.assertIsNone(check["http_status"])
            self.assertTrue(math.isfinite(check["duration_ms"]))
            self.assertGreaterEqual(check["duration_ms"], 0)
            instant = datetime.fromisoformat(check["checked_at"].replace("Z", "+00:00"))
            self.assertEqual(instant.utcoffset(), timedelta(0))
        self.client.get_service.assert_called_once_with(PROJECT)
        self.client.get_deployment_status.assert_called_once_with(PROJECT)
        self.client.get_logs.assert_called_once_with(PROJECT, since=SINCE)
        self.client.get_metrics.assert_called_once_with(PROJECT)
        self.client.list_releases.assert_called_once_with(PROJECT)
        self.assertFalse(self.factory.call_args.args[0].is_mock)

    def test_missing_logs_since_is_skipped_and_does_not_make_success_partial(self):
        environment = {key: value for key, value in self.environment.items() if key != "LIARA_LOGS_SINCE"}
        code, report = self.invoke(environment)
        self.assertEqual(code, 0)
        check = report["checks"][2]
        self.assertEqual(check["status"], "skipped")
        self.assertIsNone(check["duration_ms"])
        self.assertIsNone(check["http_status"])
        self.assertIsNone(check["error_code"])
        self.client.get_logs.assert_not_called()

    def test_invalid_settings_fail_before_client_construction(self):
        cases = [
            {}, {"LIARA_API_TOKEN": TOKEN}, {"LIARA_PROJECT_NAME": PROJECT},
            {**self.environment, "LIARA_API_TOKEN": ""},
            {**self.environment, "LIARA_API_TOKEN": "Bearer " + TOKEN},
            {**self.environment, "LIARA_API_TOKEN": TOKEN + "\r\nInjected: yes"},
        ]
        cases.extend({**self.environment, "LIARA_PROJECT_NAME": value} for value in ("", " ", ".", "..", "a\n", "\ud800"))
        cases.extend({**self.environment, "LIARA_LOGS_SINCE": value} for value in ("", " ", "\ud800"))
        cases.extend({**self.environment, "LIARA_API_BASE_URL": value} for value in (
            "", "http://example.invalid/", "https://user:password@example.invalid", "https://example.invalid?key=" + TOKEN,
        ))
        cases.extend({**self.environment, "LIARA_TIMEOUT_SECONDS": value} for value in ("", "bad", "0", "-1", "NaN", "Infinity"))
        for environment in cases:
            with self.subTest(keys=list(environment)):
                code, report = self.invoke(environment)
                self.assertEqual(code, 3)
                self.assertEqual(report["status"], "invalid_configuration")
                self.assertEqual(report["error_code"], "INVALID_CONFIGURATION")
                self.assertEqual(report["checks"], [])
        self.factory.assert_not_called()
        self.assertEqual(self.client.mock_calls, [])

    def test_optional_api_url_and_timeout_reuse_provider_config_validation(self):
        code, report = self.invoke({**self.environment,
            "LIARA_API_BASE_URL": "https://example.invalid/api/", "LIARA_TIMEOUT_SECONDS": "2.5",
        })
        self.assertEqual(code, 0)
        config = self.factory.call_args.args[0]
        self.assertEqual(config.base_url, "https://example.invalid/api")
        self.assertEqual(config.timeout, 2.5)
        self.assertEqual(config.api_key.get_secret_value(), TOKEN)
        self.assertNotIn(TOKEN, repr(config))

    def test_each_check_continues_after_http_or_transport_failure(self):
        cases = (
            (401, "AUTHENTICATION_ERROR", "authentication_failed"),
            (403, "AUTHENTICATION_ERROR", "permission_denied"),
            (404, "RESOURCE_NOT_FOUND", "not_found"),
            (429, "RATE_LIMITED", "failed"), (503, "API_UNAVAILABLE", "failed"),
            (None, "TIMEOUT", "failed"), (None, "INVALID_RESPONSE", "failed"),
        )
        for capability, method in METHODS.items():
            for status, error_code, state in cases:
                with self.subTest(capability=capability, status=status, error_code=error_code):
                    self.reset_results()
                    getattr(self.client, method).return_value = ProviderResult(False, error=StructuredError(error_code, TOKEN, status, True))
                    code, report = self.invoke()
                    self.assertEqual(code, 1)
                    check = next(item for item in report["checks"] if item["capability"] == capability)
                    self.assertEqual(check["status"], state)
                    self.assertEqual(check["error_code"], error_code)
                    self.assertEqual(check["http_status"], status)
                    self.assertEqual(sum(item["status"] == "available" for item in report["checks"]), 4)
                    for name in METHODS.values():
                        getattr(self.client, name).assert_called_once()

    def test_all_failed_checks_use_full_failure_exit_code(self):
        for method in METHODS.values():
            getattr(self.client, method).return_value = ProviderResult(False, error=StructuredError("TIMEOUT", TOKEN, None, True))
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(all(item["status"] == "failed" for item in report["checks"]))

    def test_missing_data_is_unavailable_and_empty_data_is_available(self):
        for method in METHODS.values():
            getattr(self.client, method).return_value = ProviderResult(True, None)
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertTrue(all(item["status"] == "unavailable" for item in report["checks"]))
        self.client.get_logs.return_value = ProviderResult(True, [])
        code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["checks"][2]["status"], "available")

    def test_unexpected_exception_is_sanitized_and_remaining_checks_run(self):
        self.client.get_service.side_effect = RuntimeError(TOKEN + RAW_LOG + RAW_ENV)
        code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["checks"][0]["error_code"], "UNEXPECTED_ERROR")
        self.client.list_releases.assert_called_once()

    def test_client_initialization_failure_has_no_raw_diagnostics(self):
        self.factory.side_effect = RuntimeError(TOKEN + RAW_LOG)
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["error_code"], "CLIENT_INITIALIZATION_FAILED")
        self.assertEqual(report["checks"], [])
        self.assertEqual(self.client.mock_calls, [])

    def test_mock_results_cannot_pass_as_live_access_checks(self):
        for method in METHODS.values():
            getattr(self.client, method).return_value = ProviderResult(True, TOKEN, is_mock=True)
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertTrue(all(item["error_code"] == "MOCK_RESULT" for item in report["checks"]))

    def test_inconsistent_results_are_rejected_without_serializing_them(self):
        error = StructuredError("NETWORK_ERROR", TOKEN, None, True)
        for result in ({"raw": TOKEN}, ProviderResult("yes", TOKEN),
                       ProviderResult(True, TOKEN, error), ProviderResult(False),
                       ProviderResult(False, error=TOKEN)):
            with self.subTest(kind=type(result).__name__):
                self.client.get_service.return_value = result
                code, report = self.invoke()
                self.assertEqual(code, 1)
                self.assertEqual(report["checks"][0]["error_code"], "INVALID_CLIENT_RESULT")

    def test_untrusted_error_fields_are_not_copied_to_output(self):
        for status in (TOKEN, True, 403.0, 999, None):
            self.client.get_service.return_value = ProviderResult(False, error=StructuredError(TOKEN, RAW_LOG, status, True))
            code, report = self.invoke()
            self.assertEqual(code, 1)
            self.assertEqual(report["checks"][0]["error_code"], "PROVIDER_ERROR")
            self.assertIsNone(report["checks"][0]["http_status"])

    def test_command_line_arguments_are_rejected_without_echo_or_network(self):
        for arguments in (("--token", TOKEN), (TOKEN,), ("--help",)):
            code, report = self.invoke(argv=arguments)
            self.assertEqual(code, 3)
            self.assertEqual(report["checks"], [])
        with patch.object(sys, "argv", ["live_smoke", "--token", TOKEN]):
            self.assertEqual(self.invoke(argv=None)[0], 3)
        self.factory.assert_not_called()

    def test_interrupt_returns_a_fixed_report_without_traceback(self):
        self.client.get_metrics.side_effect = KeyboardInterrupt(TOKEN)
        code, report = self.invoke()
        self.assertEqual(code, 130)
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["error_code"], "INTERRUPTED")
        self.client.list_releases.assert_not_called()

    def test_top_level_unexpected_failure_has_safe_json(self):
        with patch.object(live_smoke, "run_from_environment", side_effect=RuntimeError(TOKEN)):
            code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["error_code"], "UNEXPECTED_ERROR")

    def test_closed_output_pipe_does_not_leak_an_exception(self):
        class ClosedPipe:
            def write(self, value):
                raise BrokenPipeError(TOKEN)
        stderr = io.StringIO()
        with patch.dict(os.environ, self.environment, clear=True):
            with redirect_stdout(ClosedPipe()), redirect_stderr(stderr):
                self.assertEqual(live_smoke.main([]), 2)
        self.assertEqual(stderr.getvalue(), "")

    def test_real_client_reuses_read_only_transport_and_discards_payloads(self):
        self.factory.side_effect = LiaraClient
        opener = MagicMock()
        requests = []
        def respond(request, **kwargs):
            requests.append(request)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
            self.assertTrue(request.full_url.startswith("https://api.iran.liara.ir/v1/projects/" + PROJECT))
            if "/logs?" in request.full_url:
                payload = [{"message": RAW_LOG + TOKEN, "type": "stdout"}]
            elif "/metrics/summary" in request.full_url:
                payload = {"cpuUsage": [{"applet": "private-applet", "value": ["0"]}]}
            elif "/releases?" in request.full_url:
                payload = {"releases": [], "total": 0}
            else:
                payload = {"project": {"_id": "private-provider-id", "project_id": PROJECT,
                                       "isDeployed": False, "envs": [{"value": RAW_ENV}]}}
            return urllib.response.addinfourl(
                io.BytesIO(json.dumps(payload).encode()), Message(), request.full_url, 200,
            )
        opener.open.side_effect = respond
        with patch("provider.client.urllib.request.build_opener", return_value=opener):
            code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 5)
        self.assertTrue(requests[-1].full_url.endswith("/releases?page=1&count=10"))
        self.assertNotIn("private-provider-id", repr(report))
        self.assertNotIn("private-applet", repr(report))

    def test_real_entrypoint_rejects_missing_configuration_without_traceback(self):
        environment = os.environ.copy()
        for key in ("LIARA_API_TOKEN", "LIARA_PROJECT_NAME", "LIARA_LOGS_SINCE", "LIARA_API_BASE_URL", "LIARA_TIMEOUT_SECONDS"):
            environment.pop(key, None)
        result = subprocess.run(
            [sys.executable, "-B", "-m", "provider.examples.live_smoke"],
            cwd=Path(__file__).resolve().parents[2], env=environment,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["error_code"], "INVALID_CONFIGURATION")
        self.assertEqual(result.stderr, "")

    def test_real_closed_output_pipe_exits_without_shutdown_traceback(self):
        environment = os.environ.copy()
        environment.pop("LIARA_API_TOKEN", None)
        environment.pop("LIARA_PROJECT_NAME", None)
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "provider.examples.live_smoke"],
            cwd=Path(__file__).resolve().parents[2], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        process.stdout.close()
        try:
            process.wait(timeout=15)
            diagnostics = process.stderr.read()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stderr.close()
        self.assertEqual(diagnostics, "")
        self.assertEqual(process.returncode, 2)


if __name__ == "__main__":
    unittest.main()
