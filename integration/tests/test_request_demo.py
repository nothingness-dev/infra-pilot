"""Safe CLI boundaries and real separate-process Mock continuation."""

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

from integration import request_demo
from integration.history_errors import HistoryError
from integration.request_errors import RequestError
from .test_requests import CANARY, key


class RequestCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "requests.sqlite")
        self.history = str(Path(self.directory.name) / "history.sqlite")
        self.prefix = ["--mock", "--database", self.database]

    def call(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = request_demo.main(arguments)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(CANARY, stdout.getvalue())
        return code, json.loads(stdout.getvalue())

    def test_valid_create_complete_inspect_show_events_and_history(self):
        code, first = self.call(self.prefix + ["create", "--target", "--key", key()])
        self.assertEqual(code, 0)
        request_id = first["request"]["request_id"]
        complete = self.prefix + ["complete", "--request-id", request_id, "--expected-revision", "1", "--key", key(), "--goal", "review"]
        code, completed = self.call(complete)
        self.assertEqual(code, 0)
        self.assertEqual(completed["request"]["revision"], 2)
        code, inspection = self.call(self.prefix + ["inspect", "--request-id", request_id, "--expected-revision", "2", "--key", key(), "--history-database", self.history])
        self.assertEqual(code, 0)
        self.assertEqual(inspection["historical_summary"]["summary"]["capabilities"][3]["http_status"], 429)
        for command in ("show", "events", "history"):
            args = self.prefix + [command, "--request-id", request_id]
            if command == "history":
                args += ["--history-database", self.history]
            code, view = self.call(args)
            self.assertEqual(code, 0)
            self.assertTrue(view["reinspection_required"])
            self.assertFalse(view["execution_authorized"])

    def test_optin_invalid_arguments_and_credential_flags_never_open_storage(self):
        for arguments in ([], ["--database", self.database, "create", "--key", key()],
                          self.prefix + ["create", "--token", CANARY],
                          self.prefix + ["create", "--key", key(), "--goal", CANARY],
                          self.prefix + ["create", "--key", CANARY],
                          self.prefix + ["create", "--key", key(), "--request-id", key()],
                          self.prefix + ["show", "--request-id", key(), "--goal", "review"],
                          self.prefix + ["inspect", "--request-id", key(), "--key", key(), "--expected-revision", "1"],
                          self.prefix + ["events", "--request-id", key(), "--limit", "101"],
                          self.prefix + ["events", "--request-id", key(), "--before-revision", "0"],
                          self.prefix + ["show", "--request-id", key(), "--revision", "1"],
                          self.prefix + ["create", "--key", key(), "--scenario", CANARY]):
            code, report = self.call(arguments)
            self.assertEqual(code, 3)
            self.assertEqual(report["exit_code"], 3)
            self.assertFalse(Path(self.database).exists())

    def test_same_request_history_path_rejected_before_any_database_created(self):
        code, report = self.call(self.prefix + ["inspect", "--request-id", key(), "--key", key(), "--expected-revision", "1", "--history-database", self.database])
        self.assertEqual((code, report["error_code"]), (2, "INVALID_DATABASE"))
        self.assertFalse(Path(self.database).exists())

    def test_conflict_and_invalid_completion_exit_codes(self):
        _, created = self.call(self.prefix + ["create", "--key", key()])
        request_id = created["request"]["request_id"]
        code, _ = self.call(self.prefix + ["complete", "--request-id", request_id, "--key", key(), "--expected-revision", "2", "--goal", "review"])
        self.assertEqual(code, 4)
        code, report = self.call(self.prefix + ["inspect", "--request-id", request_id, "--key", key(), "--expected-revision", "1", "--history-database", self.history])
        self.assertEqual((code, report["error_code"]), (3, "INCOMPLETE_REQUEST"))

    def test_dependency_runtime_history_and_interrupt_errors_are_fixed_safe_json(self):
        for error, expected, code in ((ImportError(CANARY), "DEPENDENCIES_UNAVAILABLE", 2),
                                     (RuntimeError(CANARY), "UNEXPECTED_ERROR", 2),
                                     (HistoryError(CANARY), "HISTORY_FAILED", 2),
                                     (RequestError("STORAGE_BUSY"), "STORAGE_BUSY", 2),
                                     (KeyboardInterrupt(), "INTERRUPTED", 130)):
            with patch.object(request_demo, "run", side_effect=error):
                result, report = self.call(self.prefix + ["create", "--key", key()])
            self.assertEqual((result, report["error_code"]), (code, expected))

    def test_keyboard_interrupt_while_parsing_and_writing_does_not_escape(self):
        with patch.object(request_demo, "_arguments", side_effect=KeyboardInterrupt()):
            self.assertEqual(self.call([])[0], 130)
        with patch.object(request_demo, "write_report", side_effect=KeyboardInterrupt()):
            self.assertEqual(request_demo.main([]), 130)

    def test_broken_and_closed_output_return_storage_runtime_exit_without_diagnostics(self):
        for error in (BrokenPipeError(CANARY), ValueError(CANARY), OSError(CANARY)):
            stream = MagicMock()
            stream.write.side_effect = error
            stream.fileno.side_effect = OSError()
            stderr = io.StringIO()
            with patch("integration.mock_backend.sys.stdout", stream), redirect_stderr(stderr):
                self.assertEqual(request_demo.main([]), 2)
            self.assertEqual(stderr.getvalue(), "")

    def test_run_requires_literal_optin_independently_of_parser(self):
        args = request_demo._arguments(self.prefix + ["create", "--key", key()])
        for flag in (False, 1, "true"):
            args.mock = flag
            with self.assertRaises(RequestError):
                request_demo.run(args)
        self.assertFalse(Path(self.database).exists())


# Every child that exercises composition has network and approval entry points
# disabled before the command executes. No listener, subprocess tool or executor.
GUARD = """
import socket, urllib.request, sys
def forbidden(*a, **k): raise AssertionError('offline process boundary')
socket.socket = socket.create_connection = urllib.request.build_opener = forbidden
from infrapilot_triage import ApprovalGate
for name in ('authorize', 'approve', 'reject', 'request_approval'): setattr(ApprovalGate, name, forbidden)
from integration.request_demo import main
"""


class RequestProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "requests.sqlite")
        self.history = str(Path(self.directory.name) / "history.sqlite")
        self.prefix = ["--mock", "--database", self.database]
        self.environment = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT") if name in os.environ}
        # An ignored canary proves this offline path does not consume a live setting.
        self.environment["LIARA_API_TOKEN"] = CANARY

    def process(self, args, *, script=None, expected=0):
        result = subprocess.run([sys.executable, "-B", "-c", GUARD + (script or "raise SystemExit(main(sys.argv[1:]))"), *self.prefix, *args],
                                env=self.environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(CANARY, result.stdout)
        return json.loads(result.stdout) if result.stdout else None

    def test_true_separate_process_create_complete_inspect_reload_history(self):
        first = self.process(["create", "--target", "--key", key()])
        request_id = first["request"]["request_id"]
        second = self.process(["complete", "--request-id", request_id, "--key", key(), "--expected-revision", "1", "--goal", "review"])
        self.assertEqual(second["request"]["revision"], 2)
        third = self.process(["inspect", "--request-id", request_id, "--key", key(), "--expected-revision", "2", "--history-database", self.history])
        self.assertTrue(third["retained_evidence_available"])
        fourth = self.process(["history", "--request-id", request_id, "--history-database", self.history])
        self.assertEqual(fourth["historical_summary"], third["historical_summary"])
        self.assertEqual(fourth["request"]["fingerprint"], second["request"]["fingerprint"])
        self.assertFalse(fourth["retained_evidence_available"])
        self.assertTrue(fourth["reinspection_required"])
        events = self.process(["events", "--request-id", request_id, "--limit", "2"])
        self.assertEqual([e["request"]["revision"] for e in events["events"]], [5, 4])
        for path in (self.database, self.history):
            self.assertNotIn(CANARY.encode(), Path(path).read_bytes())

    def test_real_process_death_leaves_explicit_pending_stage_and_can_recover(self):
        created = self.process(["create", "--target", "--goal", "review", "--key", key()])
        request_id, attempt = created["request"]["request_id"], key()
        script = """
import os
from integration import requests
requests.MockSession = lambda **kwargs: os._exit(97)
raise SystemExit(main(sys.argv[1:]))
"""
        self.process(["inspect", "--request-id", request_id, "--key", attempt, "--expected-revision", "1", "--history-database", self.history], script=script, expected=97)
        pending = self.process(["show", "--request-id", request_id])
        self.assertEqual(pending["request"]["state"], "inspecting")
        self.assertTrue(pending["recovery_required"])
        rejected = self.process(["inspect", "--request-id", request_id, "--key", attempt, "--expected-revision", "1", "--history-database", self.history], expected=4)
        self.assertEqual(rejected["error_code"], "RECOVERY_REQUIRED")
        recovered = self.process(["recover", "--request-id", request_id, "--key", key(), "--expected-revision", "2"])
        self.assertEqual(recovered["request"]["revision"], 3)
        inspected = self.process(["inspect", "--request-id", request_id, "--key", key(), "--expected-revision", "3", "--history-database", self.history])
        self.assertEqual(inspected["request"]["state"], "inspection_recorded")
        self.assertFalse(inspected["execution_performed"])

    def test_stdlib_help_invalid_optin_and_missing_dependencies_never_create_database(self):
        for args, expected in ((["--help"], 0), ([], 3), (["--mock", "--database", self.database, "create", "--key", key()], 2)):
            result = subprocess.run([sys.executable, "-B", "-S", "-m", "integration.request_demo", *args], env=self.environment,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertNotIn(CANARY, result.stdout)
            self.assertFalse(Path(self.database).exists())
