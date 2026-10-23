"""Official project envelope and explicit account scope, with no network."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from email.message import Message
import io
import json
import socket
import unittest
import urllib.error
import urllib.response
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

from provider import LiaraClient, MockLiaraClient, ProviderConfig, ProviderResult, StructuredError
from provider.diagnostics import check_project_access, summarize_result
from provider.environment import read_live_settings

TOKEN = "diagnostic-private-token-canary"
PROJECT = "exact-project"
TEAM = "private-team-canary"
RAW = "private-response-canary"


class AccessDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("socket.socket", side_effect=AssertionError("Network forbidden")))
        self.opener = MagicMock()
        self.stack.enter_context(patch("provider.client.urllib.request.build_opener", return_value=self.opener))
        self.client = LiaraClient(ProviderConfig(TOKEN))

    def body(self, value=None, *, raw=None):
        self.opener.open.side_effect = None
        self.opener.open.return_value = urllib.response.addinfourl(
            io.BytesIO(json.dumps(value).encode() if raw is None else raw), Message(), "https://api.liara.ir", 200)

    def check(self, expected):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            report = check_project_access(self.client, PROJECT)
        self.assertEqual(report["status"], expected)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        for private in (TOKEN, PROJECT, TEAM, RAW, "Authorization", "Bearer"):
            self.assertNotIn(private, json.dumps(report))
        self.assertGreaterEqual(report["duration_ms"], 0)
        self.assertTrue(report["checked_at"])
        return report

    def test_documented_envelope_resolves_exact_project_id_and_discards_raw_fields(self):
        self.body({"projects": [{"_id": RAW, "project_id": PROJECT, "envs": [TOKEN], "name": TEAM}]})
        report = self.check("target_resolved")
        self.assertTrue(report["target_resolved"])
        self.assertEqual((report["projects_count"], report["identifiable_projects"]), (1, 1))
        self.opener.open.assert_called_once()

    def test_preserves_legacy_normalized_bare_list(self):
        self.body([{"project_id": PROJECT}])
        self.check("target_resolved")

    def test_genuine_empty_list_is_distinct_from_absent_target(self):
        self.body({"projects": []})
        self.assertEqual(self.check("empty_project_list")["error_code"], "NO_PROJECTS_VISIBLE")
        self.body({"projects": [{"project_id": "different"}]})
        self.assertEqual(self.check("target_not_listed")["error_code"], "TARGET_NOT_LISTED")

    def test_does_not_match_database_id_name_public_hostname_case_or_substring(self):
        for name in ("another", PROJECT.upper(), PROJECT + "-other", PROJECT + ".liara.run"):
            with self.subTest(case=name):
                self.body({"projects": [{"_id": PROJECT, "name": PROJECT, "project_id": name}]})
                self.assertFalse(self.check("target_not_listed")["target_resolved"])

    def test_missing_identifier_and_ambiguous_target_are_invalid(self):
        for items in ([{"_id": PROJECT}], [{"project_id": " "}], [{"project_id": 1}],
                      [{"project_id": PROJECT}, {"project_id": PROJECT}]):
            with self.subTest(items=len(items)):
                self.body({"projects": items})
                self.assertEqual(self.check("invalid_response")["error_code"], "INVALID_RESPONSE")

    def test_unknown_envelopes_never_become_empty_success(self):
        for value in (None, {}, {"data": []}, {"projects": None}, {"projects": {}}, {"projects": [None]}):
            with self.subTest(shape=type(value).__name__):
                self.body(value)
                report = self.check("invalid_response")
                self.assertIsNone(report["projects_count"])
                self.assertFalse(report["target_resolved"])
        self.body(raw=b"not JSON " + TOKEN.encode())
        self.check("invalid_response")

    def test_http_failures_have_distinct_safe_outcomes(self):
        for status, state, retry in ((401, "authentication_failed", False), (403, "permission_denied", False),
                (404, "not_found", False), (429, "rate_limited", True), (500, "api_unavailable", True),
                (502, "api_unavailable", True), (503, "api_unavailable", True), (504, "api_unavailable", True)):
            with self.subTest(status=status):
                self.opener.open.side_effect = urllib.error.HTTPError(TOKEN, status, RAW + TOKEN, {}, io.BytesIO(TOKEN.encode()))
                report = self.check(state)
                self.assertEqual(report["http_status"], status)
                self.assertIs(report["retryable"], retry)
                self.assertIsNone(report["projects_count"])

    def test_timeout_network_and_unexpected_errors_are_sanitized(self):
        for error, state in ((socket.timeout(TOKEN), "timeout"), (urllib.error.URLError(TOKEN), "network_error"),
                             (RuntimeError(TOKEN), "failed")):
            with self.subTest(state=state):
                self.opener.open.side_effect = error
                self.check(state)

    def test_invalid_target_or_mock_does_no_io(self):
        for project in (None, "", "..", "a\n"):
            self.assertEqual(check_project_access(self.client, project)["status"], "invalid_configuration")
        self.assertEqual(check_project_access(MockLiaraClient(), PROJECT)["error_code"], "MOCK_RESULT")
        self.opener.open.assert_not_called()

    def test_result_summary_never_exports_payload_messages_or_untrusted_codes(self):
        for value in (None, ProviderResult(True, TOKEN, is_mock=True), ProviderResult(True, TOKEN, StructuredError(TOKEN, RAW, 200, False)),
                      ProviderResult(False, error=StructuredError(TOKEN, TOKEN, True, TOKEN))):
            summary = summarize_result(value)
            self.assertNotIn(TOKEN, json.dumps(summary))
            self.assertNotIn(RAW, repr(summary))
            self.assertEqual(summary["status"], "failed")
        self.assertEqual(summarize_result(ProviderResult(True))["status"], "unavailable")

    def test_scoped_response_size_redirect_and_timeout_limits_survive(self):
        self.client = LiaraClient(ProviderConfig(TOKEN, team_id=TEAM, timeout=1.25))
        self.body(raw=b"x" * (self.client.MAX_RESPONSE_BYTES + 1))
        self.check("invalid_response")
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 1.25)
        self.opener.open.side_effect = urllib.error.HTTPError(TOKEN, 302, TOKEN, {"Location": "https://other.invalid"}, io.BytesIO())
        self.check("failed")
        handler = self.stack.enter_context(patch("provider.client.urllib.request.build_opener"))
        LiaraClient(ProviderConfig(TOKEN, team_id=""))
        self.assertIsNone(handler.call_args.args[0].redirect_request(None, None, 302, "", {}, "https://other.invalid"))


class AccountScopeTests(unittest.TestCase):
    def test_optional_scope_preserves_environment_contract_and_hides_identifier(self):
        for value in (None, "", TEAM):
            env = {"LIARA_API_TOKEN": TOKEN, "LIARA_PROJECT_NAME": PROJECT}
            if value is not None:
                env["LIARA_TEAM_ID"] = value
            config = read_live_settings(env).config
            self.assertEqual(config.team_id, value)
            self.assertNotIn(TEAM, repr(config))
            self.assertNotIn(TEAM, json.dumps(config.to_dict()))
            self.assertNotIn(TOKEN, repr(config))

    def test_invalid_scope_is_rejected_without_echo(self):
        for value in (1, False, "a b", "a\n", "é", "\ud800", "a" * 129, TOKEN, "prefix" + TOKEN):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ValueError) as caught:
                    ProviderConfig(TOKEN, team_id=value)
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_scope_applies_consistently_to_all_read_operations(self):
        for scope in (None, "", TEAM + "&x=y"):
            with self.subTest(scope_supplied=scope is not None), patch("provider.client.urllib.request.build_opener") as factory:
                client = LiaraClient(ProviderConfig(TOKEN, team_id=scope))
                seen = []

                def respond(request, **kwargs):
                    seen.append(request)
                    path = urlsplit(request.full_url).path
                    data = {"projects": []} if path == "/v1/projects" else [] if path.endswith("/logs") else {"releases": []} if path.endswith("/releases") else {} if path.endswith("/metrics/summary") else {"project": {"project_id": PROJECT}}
                    return urllib.response.addinfourl(io.BytesIO(json.dumps(data).encode()), Message(), request.full_url, 200)

                factory.return_value.open.side_effect = respond
                for call in (client.list_projects, lambda: client.get_service(PROJECT), lambda: client.get_deployment_status(PROJECT),
                             lambda: client.get_logs(PROJECT, since="explicit & window"), lambda: client.get_metrics(PROJECT),
                             lambda: client.list_releases(PROJECT, page=2, count=3)):
                    self.assertTrue(call().success)
                self.assertEqual(len(seen), 6)
                for request in seen:
                    query = parse_qs(urlsplit(request.full_url).query, keep_blank_values=True)
                    self.assertEqual(query.get("teamID"), None if scope is None else [scope])
                    self.assertEqual(request.get_method(), "GET")
                query = parse_qs(urlsplit(seen[-1].full_url).query)
                self.assertEqual((query["page"], query["count"]), (["2"], ["3"]))

    def test_scope_cannot_be_overridden_and_params_are_not_mutated(self):
        with patch("provider.client.urllib.request.build_opener") as factory:
            client = LiaraClient(ProviderConfig(TOKEN, team_id=TEAM))
            params = {"teamID": "other"}
            self.assertEqual(client._request("GET", "/v1/projects", params=params).error.code, "INVALID_REQUEST")
            self.assertEqual(params, {"teamID": "other"})
            factory.return_value.open.assert_not_called()
