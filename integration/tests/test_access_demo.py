"""Safe offline access CLI and independent-process ownership continuation."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from integration import access_demo
from integration.request_errors import RequestError
from integration.history_errors import HistoryError
from .test_access import CANARY, key


class AccessDemoTests(unittest.TestCase):
    def call(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = access_demo.main(args)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(CANARY, stdout.getvalue())
        return result, json.loads(stdout.getvalue())

    def test_all_fixture_scenarios_through_actual_backend(self):
        with TemporaryDirectory() as directory:
            code, allowed = self.call(["--mock", "--scenario", "owner_allowed", "--directory", directory])
            self.assertEqual(code, 0)
            self.assertTrue(allowed["retained_evidence_available"])
            for scenario in access_demo.SCENARIOS:
                if scenario == "owner_allowed":
                    continue
                args = ["--mock", "--scenario", scenario]
                if scenario == "restart_requires_fresh_context":
                    args += ["--directory", directory, "--request-id", allowed["request_id"]]
                result, report = self.call(args)
                self.assertEqual(result, 0 if scenario == "restart_requires_fresh_context" else 4)
                self.assertFalse(report["execution_authorized"])
                self.assertFalse(report["execution_performed"])
                if scenario == "restart_requires_fresh_context":
                    self.assertTrue(report["fresh_context_required"])
                    self.assertTrue(report["reinspection_required"])
                    self.assertFalse(report["retained_evidence_available"])
                else:
                    self.assertEqual(report["error_code"], "ACCESS_DENIED")
                    self.assertNotIn("request_id", report)

    def test_invalid_optin_arguments_and_claim_flags_do_not_construct_composition(self):
        for args in ([], ["--scenario", "owner_allowed"], ["--mock", "--token", CANARY],
                     ["--mock", "--role", "admin"], ["--mock", "--scenario", CANARY],
                     ["--mock", "--request-id", key()], ["--mock", "--scenario", "restart_requires_fresh_context"],
                     ["--mock", "--scenario", "restart_requires_fresh_context", "--request-id", key()]):
            with patch.object(access_demo, "run_demo", side_effect=AssertionError("No construction")):
                result, report = self.call(args)
            self.assertEqual(result, 3)
            self.assertEqual(report["exit_code"], 3)

    def test_run_function_requires_literal_optin_before_files_or_dependencies(self):
        for flag in (False, "true", 1):
            with self.assertRaises(RequestError) as caught:
                access_demo.run_demo(mock=flag)
            self.assertEqual(caught.exception.code, "MOCK_OPT_IN_REQUIRED")
        with self.assertRaises(RequestError):
            access_demo.run_demo(mock=True, scenario=CANARY)

    def test_import_runtime_storage_access_and_interrupt_errors_have_safe_json(self):
        for error, code, expected in ((ImportError(CANARY), 2, "DEPENDENCIES_UNAVAILABLE"),
                                     (RuntimeError(CANARY), 2, "UNEXPECTED_ERROR"),
                                     (RequestError("STORAGE_FAILED"), 2, "STORAGE_FAILED"),
                                     (RequestError("ACCESS_DENIED"), 4, "ACCESS_DENIED"),
                                     (HistoryError(CANARY), 2, "HISTORY_FAILED"),
                                     (KeyboardInterrupt(), 130, "INTERRUPTED")):
            with patch.object(access_demo, "run_demo", side_effect=error):
                result, report = self.call(["--mock"])
            self.assertEqual((result, report["error_code"]), (code, expected))

    def test_interrupt_during_parse_or_output_and_broken_output_are_safe(self):
        with patch.object(access_demo, "_arguments", side_effect=KeyboardInterrupt()):
            self.assertEqual(self.call([])[0], 130)
        with patch.object(access_demo, "write_report", side_effect=KeyboardInterrupt()):
            self.assertEqual(access_demo.main([]), 130)
        for error in (BrokenPipeError(CANARY), OSError(CANARY), ValueError(CANARY)):
            stream, stderr = MagicMock(), io.StringIO()
            stream.write.side_effect = error
            stream.fileno.side_effect = OSError()
            with patch("integration.mock_backend.sys.stdout", stream), redirect_stderr(stderr):
                self.assertEqual(access_demo.main([]), 2)
            self.assertEqual(stderr.getvalue(), "")

    def test_invalid_directory_does_not_create_parent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing"
            code, report = self.call(["--mock", "--directory", str(path)])
            self.assertEqual((code, report["error_code"]), (2, "INVALID_DATABASE"))
            self.assertFalse(path.exists())


GUARD = """
import socket, urllib.request, sys
def forbidden(*a, **k): raise AssertionError('offline access process')
socket.socket = socket.create_connection = urllib.request.build_opener = forbidden
from infrapilot_triage import ApprovalGate
for name in ('authorize', 'request_approval', 'approve', 'reject'): setattr(ApprovalGate,name,forbidden)
from integration.access_demo import main
raise SystemExit(main(sys.argv[1:]))
"""


class AccessProcessTests(unittest.TestCase):
    def setUp(self):
        self.environment = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT") if name in os.environ}
        self.environment["LIARA_API_TOKEN"] = CANARY

    def test_separate_process_ownership_survives_but_context_and_evidence_do_not(self):
        with TemporaryDirectory() as directory:
            prefix = [sys.executable, "-B", "-c", GUARD, "--mock", "--directory", directory]
            created = subprocess.run(prefix + ["--scenario", "owner_allowed"], env=self.environment,
                                     capture_output=True, text=True, timeout=20)
            self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
            first = json.loads(created.stdout)
            reopened = subprocess.run(prefix + ["--scenario", "restart_requires_fresh_context", "--request-id", first["request_id"]],
                                      env=self.environment, capture_output=True, text=True, timeout=20)
            self.assertEqual(reopened.returncode, 0, reopened.stderr + reopened.stdout)
            second = json.loads(reopened.stdout)
            self.assertEqual(second["request_id"], first["request_id"])
            self.assertEqual(second["request_revision"], first["request_revision"])
            self.assertTrue(second["fresh_context_required"])
            self.assertTrue(second["reinspection_required"])
            self.assertFalse(second["retained_evidence_available"])
            self.assertEqual(created.stderr + reopened.stderr, "")
            self.assertNotIn(CANARY, created.stdout + reopened.stdout)
            for file in Path(directory).glob("*.sqlite"):
                self.assertNotIn(CANARY.encode(), file.read_bytes())

    def test_help_optin_and_dependency_errors_work_with_only_standard_library(self):
        with TemporaryDirectory() as directory:
            for args, expected in ((["--help"], 0), ([], 3), (["--mock", "--directory", directory], 2)):
                result = subprocess.run([sys.executable, "-B", "-S", "-m", "integration.access_demo", *args],
                                        env=self.environment, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertNotIn(CANARY, result.stdout)
                self.assertEqual(list(Path(directory).iterdir()), [])
