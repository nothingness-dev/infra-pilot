"""Real composition at mocked urllib; these are NOT live verification records."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from email.message import Message
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import urllib.error
import urllib.response
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

from infrapilot_triage import engine
from infrapilot_triage import collection_context as triage_context
from infrapilot_triage.authorization import ApprovalGate
from integration import live_verification, readonly, readonly_inspection
from integration.history import SQLiteInspectionHistory
from integration.readonly_config import read_inspection_settings
from integration.readonly_report import ReadOnlyError
from provider import LiaraClient, MockLiaraClient

TOKEN = "verification-token-canary-621"
PROJECT = "verification-project-canary"
TEAM = "verification-team-canary"
RAW = "verification-raw-log-canary"
ENV = {"LIARA_API_TOKEN": TOKEN, "LIARA_PROJECT_NAME": PROJECT,
       "LIARA_SERVICE_ID": "private-service-canary", "LIARA_PROVIDER_SCOPE": "private-namespace-canary",
       "LIARA_API_BASE_URL": "https://api.liara.ir"}
SINCE = "private-window-canary"


class LiveVerificationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.socket", "socket.create_connection", "subprocess.Popen"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("External I/O forbidden")))
        for method in ("authorize", "request_approval", "approve", "reject"):
            self.stack.enter_context(patch.object(ApprovalGate, method, side_effect=AssertionError("Approval forbidden")))
        for name in ("diagnose_contextual_request", "preview_mock_contextual_diagnosis"):
            self.stack.enter_context(patch.object(triage_context, name, side_effect=AssertionError("Production/Mock intake forbidden")))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "summary.sqlite"
        self.opener = MagicMock()
        self.factory = self.stack.enter_context(patch("provider.client.urllib.request.build_opener", return_value=self.opener))
        self.requests = []
        self.responses = {
            "projects": {"projects": [{"_id": RAW, "project_id": PROJECT, "extra": TOKEN}]},
            "service": {"project": {"project_id": PROJECT, "isDeployed": True, "status": "running",
                                    "envs": [{"key": "PASSWORD", "value": RAW}], "extra": TOKEN}},
            "metrics": {"cpuUsage": [{"applet": RAW, "value": ["0.5"]}], "memoryUsage": []},
            "logs": [{"message": RAW + TOKEN, "type": "stdout", "datetime": RAW}],
            "releases": {"releases": [{"_id": RAW, "envs": [{"value": TOKEN}]}]},
        }
        self.opener.open.side_effect = self.respond

    def respond(self, request, *, timeout):
        self.requests.append(request)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertGreater(timeout, 0)
        self.assertEqual(urlsplit(request.full_url).hostname, "api.liara.ir")
        path = urlsplit(request.full_url).path
        capability = {"/v1/projects": "projects", "/v1/projects/" + PROJECT: "service",
                      "/v1/projects/" + PROJECT + "/metrics/summary": "metrics",
                      "/v1/projects/" + PROJECT + "/logs": "logs",
                      "/v1/projects/" + PROJECT + "/releases": "releases"}[path]
        body = self.responses[capability]
        if isinstance(body, BaseException):
            raise body
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return urllib.response.addinfourl(io.BytesIO(raw), Message(), request.full_url, 200)

    def verify(self, environment=None, *, history=True):
        report = live_verification.run_verification(live_read_only=True, environment=ENV if environment is None else environment,
                                                     history_database=self.database if history else None)
        self.assert_private(json.dumps(report))
        for key in ("identity_verified", "freshness_evaluated", "authorization_consumed", "execution_authorized",
                    "execution_performed", "remediation_verified"):
            self.assertIs(report[key], False)
        return report

    def assert_private(self, text):
        for secret in (*ENV.values(), TEAM, RAW, SINCE, "Authorization", "Bearer"):
            if secret.startswith("https:"):
                continue
            self.assertNotIn(secret, text)

    def invoke(self, args=("--live-read-only", "--verify-access"), environment=None):
        stdout, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with patch.dict(os.environ, ENV if environment is None else environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
                code = readonly_inspection.main(args)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assert_private(stdout.getvalue() + stderr.getvalue() + logs.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(code, report["exit_code"])
        return code, report

    def test_complete_pipeline_and_history_run_once_with_one_client(self):
        with patch.object(engine, "diagnose", wraps=engine.diagnose) as diagnose, patch.object(
                readonly, "consume_diagnosis", wraps=readonly.consume_diagnosis) as consume, patch.object(
                live_verification, "inspect_with_client", wraps=live_verification.inspect_with_client) as inspect:
            report = self.verify()
        self.assertEqual((report["status"], report["exit_code"]), ("complete", 0))
        self.factory.assert_called_once()
        diagnose.assert_called_once()
        consume.assert_called_once()
        inspect.assert_called_once()
        self.assertEqual(len(self.requests), 4)  # list + details + metrics + releases
        self.assertEqual(len({r.full_url for r in self.requests}), 4)
        self.assertEqual(report["inspection"]["logs"]["state"], "not_collected")
        self.assertEqual(report["releases"]["status"], "available")
        self.assertEqual(report["history"]["status"], "recorded")
        binding = read_inspection_settings(ENV).binding
        with SQLiteInspectionHistory(self.database, create=False) as history:
            records = history.list_for(expected_binding=binding)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].record_id, report["history"]["record_id"])
            summary = records[0].to_dict()["summary"]
        self.assertEqual(summary["application_health"], "unknown")
        for key in ("cpu_usage_percent", "ram_usage_mib", "application_http_status", "application_response_time_ms", "source_timestamp"):
            self.assertIsNone(summary[key])
        self.assertIs(summary["history_only"], True)
        self.assertIs(summary["provenance_verified"], False)
        self.assert_private(self.database.read_bytes().decode("latin1"))

    def test_explicit_scope_consistent_on_all_requests_and_logs_withheld(self):
        for scope in ("", TEAM):
            with self.subTest(personal=scope == ""):
                self.requests.clear()
                report = self.verify({**ENV, "LIARA_TEAM_ID": scope, "LIARA_LOGS_SINCE": SINCE})
                self.assertEqual(report["account_scope"], "personal" if scope == "" else "team")
                self.assertEqual(len(self.requests), 5)
                for request in self.requests:
                    self.assertEqual(parse_qs(urlsplit(request.full_url).query, keep_blank_values=True)["teamID"], [scope])
                self.assertEqual(report["inspection"]["logs"], {"state": "withheld", "received": 1, "exported": 0, "withheld": 1})
                self.assert_private(self.database.read_bytes().decode("latin1"))

    def test_unresolved_or_invalid_listing_stops_collection_and_storage(self):
        cases = (({"projects": []}, "empty_project_list"), ({"projects": [{"project_id": "other", "_id": PROJECT}]}, "target_not_listed"),
                 ({"data": []}, "invalid_response"), ({"projects": [None]}, "invalid_response"),
                 ({"projects": [{"_id": PROJECT}]}, "invalid_response"), (b"invalid " + TOKEN.encode(), "invalid_response"))
        for body, state in cases:
            with self.subTest(state=state):
                self.requests.clear()
                self.responses["projects"] = body
                with patch.object(engine, "diagnose", side_effect=AssertionError("No diagnosis before resolution")):
                    report = self.verify()
                self.assertEqual(report["project_access"]["status"], state)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(len(self.requests), 1)
                self.assertIsNone(report["inspection"])
                self.assertIsNone(report["releases"])
                self.assertFalse(self.database.exists())

    def test_access_http_failures_do_not_guess_alternate_host(self):
        for status, state in ((401, "authentication_failed"), (403, "permission_denied"), (404, "not_found"),
                              (429, "rate_limited"), (503, "api_unavailable")):
            with self.subTest(status=status):
                self.requests.clear()
                self.responses["projects"] = urllib.error.HTTPError(TOKEN, status, TOKEN + RAW, {}, io.BytesIO(TOKEN.encode()))
                report = self.verify()
                self.assertEqual(report["project_access"]["status"], state)
                self.assertEqual(report["project_access"]["http_status"], status)
                self.assertEqual(len(self.requests), 1)
                self.assertFalse(self.database.exists())

    def test_access_transport_failures(self):
        for error, state in ((socket.timeout(TOKEN), "timeout"), (urllib.error.URLError(TOKEN), "network_error")):
            self.responses["projects"] = error
            self.assertEqual(self.verify()["project_access"]["status"], state)

    def test_partial_capabilities_and_release_errors_preserve_valid_diagnosis(self):
        for status in (401, 403, 404, 429, 503):
            with self.subTest(status=status):
                self.responses["metrics"] = urllib.error.HTTPError(TOKEN, status, TOKEN, {}, io.BytesIO(TOKEN.encode()))
                self.responses["releases"] = socket.timeout(TOKEN)
                report = self.verify(history=False)
                self.assertEqual((report["status"], report["exit_code"]), ("partial", 1))
                self.assertEqual(report["inspection"]["capabilities"][0]["availability"], "available")
                self.assertEqual(report["inspection"]["capabilities"][3]["http_status"], status)
                self.assertTrue(report["inspection"]["diagnosis"]["associated"])
                self.assertEqual(report["releases"]["error_code"], "TIMEOUT")

    def test_all_capabilities_failed_is_failure_even_when_listing_succeeds(self):
        for name in ("service", "metrics", "releases"):
            self.responses[name] = urllib.error.HTTPError(TOKEN, 404, TOKEN, {}, io.BytesIO())
        report = self.verify()
        self.assertEqual((report["status"], report["exit_code"]), ("failed", 2))
        self.assertTrue(report["inspection"]["diagnosis"]["associated"])
        self.assertEqual(report["history"]["status"], "recorded")

    def test_release_invalid_or_empty_responses_remain_distinct(self):
        for body, state, code in ((b"bad JSON", "failed", 1), (None, "unavailable", 1), ({"releases": []}, "available", 0)):
            self.responses["releases"] = body
            report = self.verify(history=False)
            self.assertEqual((report["releases"]["status"], report["exit_code"]), (state, code))

    def test_later_diagnosis_failure_keeps_collected_context_and_history(self):
        with patch.object(engine, "diagnose", side_effect=RuntimeError(TOKEN + RAW)):
            report = self.verify()
        self.assertEqual(report["error_code"], "DIAGNOSIS_FAILED")
        self.assertEqual(report["inspection"]["capabilities"][0]["availability"], "available")
        self.assertEqual(report["releases"]["status"], "available")
        self.assertEqual(report["history"]["status"], "recorded")

    def test_history_failure_keeps_earlier_safe_summaries(self):
        with patch.object(live_verification, "SQLiteInspectionHistory", side_effect=RuntimeError(TOKEN)):
            report = self.verify()
        self.assertEqual((report["error_code"], report["exit_code"]), ("HISTORY_FAILED", 2))
        self.assertTrue(report["inspection"]["diagnosis"]["associated"])
        self.assertEqual(report["releases"]["status"], "available")
        self.assertEqual(report["history"]["status"], "failed")

    def test_mock_client_cannot_be_promoted_into_live_verification(self):
        with patch.object(live_verification, "LiaraClient", return_value=MockLiaraClient()):
            report = self.verify()
        self.assertEqual(report["project_access"]["error_code"], "MOCK_RESULT")
        self.opener.open.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_collection_continuation_rejects_a_different_client_configuration(self):
        selected = read_inspection_settings(ENV)
        foreign = LiaraClient(read_inspection_settings({**ENV, "LIARA_TEAM_ID": TEAM}).live.config)
        result = readonly.inspect_with_client(foreign, selected)
        self.assertEqual(result.summary()["error_code"], "COLLECTION_FAILED")
        self.opener.open.assert_not_called()

    def test_literal_opt_in_and_settings_validate_before_client(self):
        for flag in (False, None, 1, "true"):
            with self.assertRaises(ReadOnlyError):
                live_verification.run_verification(live_read_only=flag, environment=ENV)
        for key in ("LIARA_API_TOKEN", "LIARA_PROJECT_NAME", "LIARA_SERVICE_ID", "LIARA_PROVIDER_SCOPE"):
            env = dict(ENV)
            del env[key]
            self.assertEqual(self.invoke(environment=env)[0], 3)
        for key, value in (("LIARA_API_BASE_URL", "https://other.invalid"), ("LIARA_API_BASE_URL", "https://api.liara.ir/path"),
                           ("LIARA_API_BASE_URL", "https://api.liara.ir:444"), ("LIARA_TEAM_ID", TOKEN),
                           ("LIARA_TIMEOUT_SECONDS", "NaN"), ("LIARA_PROJECT_NAME", "..")):
            self.assertEqual(self.invoke(environment={**ENV, key: value})[0], 3)
        self.factory.assert_not_called()

    def test_bad_history_path_fails_before_network(self):
        for path in (self.database.parent / "absent" / "db", self.database.parent / TOKEN):
            with self.assertRaises(ReadOnlyError) as caught:
                live_verification.run_verification(live_read_only=True, environment=ENV, history_database=path)
            self.assert_private(str(caught.exception) + repr(caught.exception))
        self.factory.assert_not_called()

    def test_cli_success_privacy_and_safe_error_output(self):
        code, report = self.invoke(args=("--live-read-only", "--verify-access", "--history-database", str(self.database)))
        self.assertEqual(code, 0)
        self.assertEqual(report["history"]["status"], "recorded")
        self.responses["projects"] = urllib.error.HTTPError(TOKEN, 403, TOKEN + RAW, {}, io.BytesIO(TOKEN.encode()))
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(report["project_access"]["status"], "permission_denied")
        self.responses["projects"] = RuntimeError(TOKEN)
        self.assertEqual(self.invoke()[0], 2)

    def test_cli_invalid_and_duplicate_arguments_never_construct_client(self):
        for args in (("--verify-access",), ("--live-read-only", "--history-database", str(self.database)),
                     ("--live-read-only", "--verify-access", "--verify-access"),
                     ("--live-read-only", "--verify-access", "--history-database=a", "--history-database=b"),
                     ("--live-read-only", "--verify-access", "--token", TOKEN)):
            self.assertEqual(self.invoke(args=args)[0], 3)
        self.factory.assert_not_called()

    def test_interrupted_access_has_safe_exit_and_no_storage(self):
        self.responses["projects"] = KeyboardInterrupt()
        self.assertEqual(self.invoke()[0], 130)
        self.assertFalse(self.database.exists())

    def test_interrupted_diagnosis_keeps_evidence_and_stops_further_io(self):
        with patch.object(engine, "diagnose", side_effect=KeyboardInterrupt()):
            report = self.verify()
        self.assertEqual((report["exit_code"], report["error_code"]), (130, "INTERRUPTED"))
        self.assertEqual(report["inspection"]["capabilities"][0]["availability"], "available")
        self.assertIsNone(report["releases"])
        self.assertEqual(len(self.requests), 3)
        self.assertFalse(self.database.exists())

    def test_interrupted_release_preserves_prior_inspection_and_does_not_archive(self):
        self.responses["releases"] = KeyboardInterrupt()
        report = self.verify()
        self.assertEqual(report["exit_code"], 130)
        self.assertTrue(report["inspection"]["diagnosis"]["associated"])
        self.assertEqual(report["releases"]["status"], "interrupted")
        self.assertFalse(self.database.exists())

    def test_interrupted_history_never_claims_successful_persistence(self):
        with patch.object(live_verification, "SQLiteInspectionHistory", side_effect=KeyboardInterrupt()):
            report = self.verify()
        self.assertEqual(report["exit_code"], 130)
        self.assertTrue(report["inspection"]["diagnosis"]["associated"])
        self.assertEqual(report["releases"]["status"], "available")
        self.assertEqual(report["history"], {"status": "interrupted", "record_id": None})


class VerificationBootstrapTests(unittest.TestCase):
    def test_stdlib_only_help_and_missing_dependencies_are_safe(self):
        for args, expected in ((("--help",), 0), (("--live-read-only", "--verify-access"), 2)):
            with self.subTest(arguments=len(args)):
                run = subprocess.run([sys.executable, "-B", "-S", "-m", "integration.readonly_inspection", *args],
                                     env={**os.environ, **ENV}, cwd=Path(__file__).resolve().parents[2],
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, expected)
                self.assertEqual(run.stderr, "")
                self.assertNotIn(TOKEN, run.stdout)
                if expected:
                    self.assertEqual(json.loads(run.stdout)["error_code"], "DEPENDENCIES_UNAVAILABLE")
