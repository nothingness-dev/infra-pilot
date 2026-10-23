"""Persistence, association, corruption and privacy tests with no live I/O."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from infrapilot_triage.authorization import ApprovalGate
from provider import ServiceBinding
from setup.models import OperationRequest

from integration.history import HistoryError, HistoricalInspection, SQLiteInspectionHistory
from integration import history_demo, history as history_module
from integration.service import MockSession, SCENARIOS
from . import test_readonly as readonly_fixture


CANARY = "PRIVATE-HISTORY-CANARY-8293"


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.socket", "socket.create_connection", "subprocess.Popen", "urllib.request.build_opener"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("History must remain offline")))
        for method in ("authorize", "request_approval", "approve", "reject"):
            self.stack.enter_context(patch.object(ApprovalGate, method, side_effect=AssertionError("No approval in history")))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "history.sqlite"
        self.inspection = MockSession(mock=True, scenario="partial_failure").inspect()
        self.binding = self.inspection.source_binding

    def open(self, **kwargs):
        history = SQLiteInspectionHistory(self.path, **kwargs)
        self.addCleanup(history.close)
        return history

    def real_inspection(self, *, fail_diagnosis=False):
        fixture = readonly_fixture.ReadOnlyTests()
        fixture.setUp()
        try:
            if fail_diagnosis:
                from infrapilot_triage import engine
                with patch.object(engine, "diagnose", side_effect=RuntimeError(CANARY)):
                    return fixture.run_inspection()
            return fixture.run_inspection()
        finally:
            fixture.doCleanups()

    def test_save_close_reopen_preserves_real_component_summaries(self):
        with self.open() as history:
            saved = history.save(self.inspection)
        with self.open(create=False) as reopened:
            self.assertEqual(saved, reopened.get(saved.record_id, expected_binding=self.binding))
            self.assertEqual(reopened.list_for(expected_binding=self.binding), (saved,))
        data = saved.to_dict()["summary"]
        self.assertEqual(data["data_source"], "mock")
        self.assertEqual(data["capabilities"][2]["http_status"], 403)
        self.assertEqual(data["capabilities"][3]["http_status"], 429)
        self.assertTrue(data["capabilities"][3]["retryable"])
        self.assertEqual(data["snapshot_digest"], self.inspection.prepared.to_request()["collection_context"]["snapshot_digest"])

    def test_idempotent_retry_returns_original_record_and_time(self):
        history = self.open()
        first = history.save(self.inspection)
        second = history.save(self.inspection)
        self.assertEqual(first, second)
        self.assertEqual(len(history.list_for(expected_binding=self.binding)), 1)

    def test_actual_mock_scenarios_preserve_log_counts_and_unknown_telemetry(self):
        history = self.open()
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                inspection = MockSession(mock=True, scenario=scenario).inspect()
                summary = history.save(inspection).to_dict()["summary"]
                context = inspection.prepared.to_request()["collection_context"]
                self.assertEqual(summary["logs"], context["log_export"])
                self.assertEqual(summary["capabilities"], context["capabilities"])
                self.assertEqual(summary["application_health"], "unknown")
                for key in ("cpu_usage_percent", "ram_usage_mib", "application_http_status", "application_response_time_ms", "source_timestamp"):
                    self.assertIsNone(summary[key])
        self.assertEqual(len(history.list_for(expected_binding=self.binding)), len(SCENARIOS))

    def test_readonly_inspection_is_archived_without_relabeling(self):
        inspection = self.real_inspection()
        history = self.open()
        saved = history.save(inspection)
        self.assertEqual(saved.to_dict()["summary"]["data_source"], "real")
        history.close()
        for sensitive in (readonly_fixture.TOKEN, readonly_fixture.PROJECT, readonly_fixture.SCOPE,
                          readonly_fixture.SERVICE, readonly_fixture.RAW):
            self.assertNotIn(sensitive, json.dumps(saved.to_dict()))
            self.assertNotIn(sensitive.encode(), self.path.read_bytes())

    def test_later_failure_keeps_earlier_evidence_in_history(self):
        inspection = self.real_inspection(fail_diagnosis=True)
        summary = self.open().save(inspection).to_dict()["summary"]
        self.assertEqual(summary["pipeline_error"], "DIAGNOSIS_FAILED")
        self.assertEqual(summary["stage"], "diagnosis")
        self.assertIsNone(summary["diagnosis_counts"])
        self.assertIsNone(summary["report_digest"])
        self.assertEqual(summary["capabilities"][0]["availability"], "available")

    def test_wrong_source_binding_and_modified_request_or_report_rejected(self):
        for mutate in (lambda i: i.request.details.update(goal=CANARY),
                       lambda i: setattr(i.presentation.report, "summary", CANARY),
                       lambda i: object.__setattr__(i, "source_binding", replace(i.source_binding, provider_scope="other"))):
            inspection = MockSession(mock=True).inspect()
            mutate(inspection)
            with self.assertRaises(HistoryError) as caught:
                self.open().save(inspection)
            self.assertEqual(caught.exception.code, "INVALID_INSPECTION")

    def test_json_and_historical_record_cannot_mint_trusted_inspection(self):
        history = self.open()
        saved = history.save(self.inspection)
        for submitted in (saved, saved.to_dict(), self.inspection.result.to_dict(), MagicMock()):
            with self.subTest(kind=type(submitted).__name__), self.assertRaises(HistoryError):
                history.save(submitted)

    def test_binding_scoped_reads_reject_other_service_scope_project_and_source(self):
        history = self.open()
        saved = history.save(self.inspection)
        for change in ({"service_id": "other"}, {"project_name": "other"}, {"provider_scope": "other"}, {"is_mock": False}):
            with self.subTest(field=next(iter(change))):
                other = replace(self.binding, **change)
                self.assertIsNone(history.get(saved.record_id, expected_binding=other))
                self.assertEqual(history.list_for(expected_binding=other), ())

    def test_request_filter_uses_exact_full_brief_fingerprint(self):
        history = self.open()
        saved = history.save(self.inspection)
        self.assertEqual(history.list_for(expected_binding=self.binding, request=self.inspection.request), (saved,))
        other = OperationRequest(self.inspection.request.request_id, "inspect_service",
                                 {**self.inspection.request.details, "goal": CANARY})
        self.assertEqual(history.list_for(expected_binding=self.binding, request=other), ())

    def test_pagination_is_bounded_stable_and_newest_first(self):
        history = self.open()
        saved = [history.save(MockSession(mock=True, scenario=scenario).inspect()) for scenario in SCENARIOS]
        first = history.list_for(expected_binding=self.binding, limit=2)
        self.assertEqual(first, tuple(reversed(saved[-2:])))
        remaining = history.list_for(expected_binding=self.binding, before_sequence=first[-1].sequence)
        self.assertEqual(remaining, tuple(reversed(saved[:-2])))
        for limit in (0, -1, 101, True, 1.5, CANARY):
            with self.subTest(limit_type=type(limit).__name__), self.assertRaises(HistoryError):
                history.list_for(expected_binding=self.binding, limit=limit)
        for cursor in (0, -1, True, CANARY):
            with self.assertRaises(HistoryError):
                history.list_for(expected_binding=self.binding, before_sequence=cursor)

    def test_unknown_record_and_invalid_identifier_do_not_echo_input(self):
        history = self.open()
        self.assertIsNone(history.get("sha256:" + "0" * 64, expected_binding=self.binding))
        for value in (CANARY, "'; DROP TABLE inspections; --", None):
            with self.assertRaises(HistoryError) as caught:
                history.get(value, expected_binding=self.binding)
            self.assertNotIn(CANARY, str(caught.exception))
        self.assertEqual(history.list_for(expected_binding=self.binding), ())

    def test_corrupted_payload_is_not_silently_skipped_or_returned(self):
        history = self.open()
        saved = history.save(self.inspection)
        payload = saved.to_dict()["summary"]
        payload["diagnosis_counts"]["evidence"] += 1
        history._connection.execute("UPDATE inspections SET payload=?", (json.dumps(payload),))
        history._connection.commit()
        for read in (lambda: history.get(saved.record_id, expected_binding=self.binding),
                     lambda: history.list_for(expected_binding=self.binding)):
            with self.assertRaises(HistoryError) as caught:
                read()
            self.assertEqual(caught.exception.code, "RECORD_CORRUPTED")

    def test_oversized_and_nonfinite_database_payloads_fail_closed(self):
        for payload in ("x" * (history_module._MAX_BYTES + 1), '{"value":NaN}'):
            history = self.open()
            saved = history.save(self.inspection)
            history._connection.execute("UPDATE inspections SET payload=?", (payload,))
            history._connection.commit()
            with self.assertRaises(HistoryError):
                history.get(saved.record_id, expected_binding=self.binding)
            history.close()
            self.path.unlink()

    def test_database_metadata_mismatch_and_foreign_tables_are_preserved(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE foreign_data(value TEXT)")
            db.execute("INSERT INTO foreign_data VALUES('preserve')")
            db.commit()
        with self.assertRaises(HistoryError) as caught:
            self.open()
        self.assertEqual(caught.exception.code, "UNSUPPORTED_DATABASE")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT value FROM foreign_data").fetchone()[0], "preserve")

    def test_newer_schema_version_is_rejected_without_downgrade(self):
        history = self.open()
        history.close()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version = 2")
        with self.assertRaises(HistoryError):
            self.open()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_invalid_database_paths_timeout_and_missing_read_database(self):
        for path, options in ((self.path, {"create": False}), (self.path / "missing.sqlite", {}),
                              (self.path, {"timeout": 0}), (self.path, {"timeout": True}),
                              (self.path, {"timeout": float("nan")}), (self.path, {"create": "yes"})):
            with self.assertRaises(HistoryError):
                SQLiteInspectionHistory(path, **options)
        self.assertFalse(self.path.exists())
        self.path.write_bytes(b"not a SQLite database " + CANARY.encode())
        with self.assertRaises(HistoryError) as caught:
            self.open()
        self.assertNotIn(CANARY, repr(caught.exception))

    def test_failed_write_rolls_back_and_retry_succeeds(self):
        history = self.open()
        history._connection.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON inspections BEGIN SELECT RAISE(ABORT, 'PRIVATE-HISTORY-CANARY-8293'); END")
        history._connection.commit()
        with self.assertRaises(HistoryError) as caught:
            history.save(self.inspection)
        self.assertNotIn(CANARY, str(caught.exception))
        self.assertEqual(history.list_for(expected_binding=self.binding), ())
        history._connection.execute("DROP TRIGGER fail_insert")
        history._connection.commit()
        self.assertIsInstance(history.save(self.inspection), HistoricalInspection)

    def test_busy_database_returns_safe_error_and_recovers(self):
        first = self.open()
        second = self.open(timeout=0.01)
        first._connection.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(HistoryError):
                second.save(self.inspection)
        finally:
            first._connection.rollback()
        self.assertIsNotNone(second.save(self.inspection))

    def test_multiple_connections_serialize_writes_and_deduplicate_retries(self):
        self.open().close()
        inspections = [MockSession(mock=True, scenario=scenario).inspect() for scenario in SCENARIOS[:3]]
        def save(inspection):
            with SQLiteInspectionHistory(self.path) as history:
                return history.save(inspection).record_id
        with ThreadPoolExecutor(max_workers=3) as pool:
            ids = list(pool.map(save, inspections * 2))
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(len(self.open().list_for(expected_binding=self.binding)), 3)

    def test_detached_outputs_do_not_mutate_records(self):
        history = self.open()
        saved = history.save(self.inspection)
        detached = saved.to_dict()
        detached["summary"]["execution_performed"] = True
        detached["summary"]["capabilities"].clear()
        self.assertFalse(saved.to_dict()["summary"]["execution_performed"])
        self.assertEqual(len(history.get(saved.record_id, expected_binding=self.binding).to_dict()["summary"]["capabilities"]), 4)

    def test_secrets_logs_prose_and_raw_identifiers_never_persist(self):
        request = OperationRequest(CANARY + "-request", "inspect_service",
            {"service_target": "MOCK-service", "goal": CANARY + "-goal"})
        inspection = MockSession(mock=True, scenario="withheld", request=request).inspect()
        history = self.open()
        saved = history.save(inspection)
        output = json.dumps(saved.to_dict())
        history.close()
        for sensitive in (CANARY, "MOCK-service", "mock-project", "mock-account", "Synthetic application"):
            self.assertNotIn(sensitive, output)
            self.assertNotIn(sensitive.encode(), self.path.read_bytes())
        logger = logging.Logger("history-safe")
        log = io.StringIO()
        logger.addHandler(logging.StreamHandler(log))
        logger.warning("%r %r %r", history, saved, HistoryError(CANARY))
        self.assertNotIn(CANARY, log.getvalue())
        self.assertNotIn(str(self.path), repr(history))

    def test_history_is_not_current_authority_or_remediation(self):
        saved = self.open().save(self.inspection)
        summary = saved.to_dict()["summary"]
        self.assertTrue(summary["history_only"])
        for name in ("provenance_verified", "freshness_evaluated", "authorization_consumed", "execution_authorized", "execution_performed", "remediation_verified"):
            self.assertIs(summary[name], False)
        with self.assertRaises(HistoryError):
            self.open().save(saved)

    def test_close_is_idempotent_and_operations_fail_safely_after_close(self):
        history = self.open()
        saved = history.save(self.inspection)
        history.close()
        history.close()
        for operation in (lambda: history.save(self.inspection), lambda: history.get(saved.record_id, expected_binding=self.binding),
                          lambda: history.list_for(expected_binding=self.binding)):
            with self.assertRaises(HistoryError) as caught:
                operation()
            self.assertEqual(caught.exception.code, "STORE_CLOSED")

    def test_demo_records_and_lists_without_recollection(self):
        report = history_demo.run_demo(database=self.path)
        self.assertEqual(report["returned_count"], 1)
        with patch("integration.service.MockSession", side_effect=AssertionError("No new collection")):
            listed = history_demo.run_demo(database=self.path, list_only=True)
        self.assertEqual(listed["records"], report["records"])
        self.assertEqual(listed["status"], "history_read")

    def test_cli_invalid_arguments_errors_interrupt_and_output_failure(self):
        for args in ([], ["--database", str(self.path)], ["--mock", "--token", CANARY]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = history_demo.main(args)
            self.assertEqual(code, 3)
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn(CANARY, stdout.getvalue())
        for error, expected in ((RuntimeError(CANARY), 2), (ImportError(CANARY), 2), (KeyboardInterrupt(), 130)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(history_demo, "run_demo", side_effect=error), redirect_stdout(stdout), redirect_stderr(stderr):
                code = history_demo.main(["--mock", "--database", str(self.path)])
            self.assertEqual(code, expected)
            self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue())
        stream = MagicMock()
        stream.write.side_effect = BrokenPipeError(CANARY)
        stream.fileno.side_effect = OSError()
        with patch("integration.mock_backend.sys.stdout", stream):
            self.assertEqual(history_demo.main([]), 2)


class HistoryProcessTests(unittest.TestCase):
    def test_separate_process_restart_lists_same_record_without_secrets(self):
        with TemporaryDirectory() as directory:
            database = str(Path(directory) / "history.sqlite")
            env = {key: value for key, value in os.environ.items() if not key.startswith("LIARA_")}
            command = [sys.executable, "-B", "-m", "integration.history_demo", "--mock", "--database", database]
            first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
            second = subprocess.run(command + ["--list"], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual((first.returncode, second.returncode), (0, 0))
            self.assertEqual(first.stderr + second.stderr, "")
            self.assertEqual(json.loads(first.stdout)["records"], json.loads(second.stdout)["records"])

    def test_help_and_invalid_optin_work_without_composition_dependencies(self):
        for args, expected in ((["--help"], 0), ([], 3), (["--mock", "--database", "unused.sqlite"], 2)):
            result = subprocess.run([sys.executable, "-B", "-S", "-m", "integration.history_demo", *args],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, expected)
            self.assertEqual(result.stderr, "")
