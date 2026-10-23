"""Offline persistence, atomicity and retained-object boundary verification."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import logging
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
import warnings
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

from infrapilot_triage import ApprovalGate, collection_context as triage_context
from provider import MockLiaraClient
from provider.examples.context_fixtures import mock_context_binding
from setup import application
from setup.integration import request_fingerprint

from integration import request_policy, requests as runtime, service
from integration.history import SQLiteInspectionHistory
from integration.history_errors import HistoryError
from integration.request_errors import RequestError
from integration.request_policy import GOALS, TARGET, canonical, digest, operation
from integration.request_store import APPLICATION_ID, SQLiteRequestStore
from integration.requests import PersistentMockRequests
from integration.outcome_evidence import EvidenceLedger, OutcomeError


CANARY = "PRIVATE-REQUEST-CANARY-938147"
BRIEF = {"service_target": TARGET, "goal": GOALS["review"]}


def key():
    return uuid4().hex


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.socket", "socket.create_connection", "subprocess.Popen", "urllib.request.build_opener"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("No external I/O")))
        for method in ("authorize", "request_approval", "approve", "reject"):
            self.stack.enter_context(patch.object(ApprovalGate, method, side_effect=AssertionError("No approval")))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "requests.sqlite"
        self.history_path = Path(self.directory.name) / "history.sqlite"
        self.store = self.open()
        self.workflow = PersistentMockRequests(self.store, mock=True)
        self.history = SQLiteInspectionHistory(self.history_path)
        self.addCleanup(self.history.close)

    def open(self, **kwargs):
        store = SQLiteRequestStore(self.path, **kwargs)
        self.addCleanup(store.close)
        return store

    def create(self, brief=None):
        return self.workflow.create(BRIEF if brief is None else brief, idempotency_key=key())["request"]

    def inspect(self, request=None, **kwargs):
        request = request or self.create()
        return self.workflow.inspect(request["request_id"], expected_revision=request["revision"],
                                     idempotency_key=key(), history=self.history, **kwargs)["request"]

    def error(self, code, call):
        with self.assertRaises(RequestError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception) + repr(caught.exception))

    def test_actual_setup_intake_and_completion_survive_reopen(self):
        with patch.object(request_policy, "submit_request", wraps=application.submit_request) as intake:
            first = self.create({"service_target": TARGET})
        self.assertEqual(intake.call_count, 1)
        self.assertEqual(first["state"], "needs_information")
        self.assertIsNone(first["fingerprint"])
        self.store.close()
        store = self.open(create=False)
        workflow = PersistentMockRequests(store, mock=True)
        self.assertEqual(workflow.get(first["request_id"])["request"], first)
        with patch.object(request_policy, "supply_information", wraps=application.supply_information) as complete:
            second = workflow.supply_information(first["request_id"], {"goal": GOALS["review"]}, expected_revision=1, idempotency_key=key())["request"]
        self.assertEqual(complete.call_count, 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["brief_revision"], 2)
        self.assertEqual(second["state"], "ready_for_inspection")
        self.assertEqual(second["fingerprint"], request_fingerprint(operation(second["request_id"], BRIEF)))
        self.assertEqual([e["request"]["revision"] for e in workflow.events(first["request_id"])], [2, 1])

    def test_missing_target_and_both_missing_are_valid_incomplete_briefs(self):
        for brief in ({}, {"goal": GOALS["review"]}):
            request = self.create(brief)
            self.assertEqual(request["state"], "needs_information")
            self.error("INCOMPLETE_REQUEST", lambda: self.inspect(request))
            self.assertEqual(len(self.workflow.events(request["request_id"])), 1)

    def test_invalid_completion_preserves_request_and_events(self):
        request = self.create()
        for brief in ({"goal": CANARY}, {"goal": " " + GOALS["review"]}, {"service_target": "other"},
                      {"credentials": {"token": CANARY}}, {CANARY: "value"}, {"goal": None}, [], None):
            self.error("INVALID_REQUEST", lambda: self.workflow.supply_information(request["request_id"], brief, expected_revision=1, idempotency_key=key()))
        self.assertEqual(self.store.get(request["request_id"]), request)
        self.assertEqual(len(self.workflow.events(request["request_id"])), 1)

    def test_actual_pipeline_once_and_allowlisted_history_partial_semantics(self):
        request = self.create()
        retry = key()
        with patch.object(MockLiaraClient, "collect_service_observations", autospec=True,
                          side_effect=MockLiaraClient.collect_service_observations) as collect, patch.object(
                triage_context, "diagnose", wraps=triage_context.diagnose) as diagnose, patch.object(
                service, "consume_diagnosis", wraps=service.consume_diagnosis) as consume:
            first = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=retry, history=self.history)
            again = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=retry, history=self.history)
            self.workflow.events(request["request_id"])
            summary = self.workflow.historical_summary(request["request_id"], history=self.history)["summary"]
        self.assertEqual((collect.call_count, diagnose.call_count, consume.call_count), (1, 1, 1))
        self.assertEqual(first, again)
        self.assertEqual(first["request"]["revision"], 4)
        self.assertEqual(summary["capabilities"][2]["http_status"], 403)
        self.assertEqual(summary["capabilities"][3]["http_status"], 429)
        self.assertEqual(summary["application_health"], "unknown")
        self.assertIsNone(summary["cpu_usage_percent"])
        self.assertIsNone(summary["ram_usage_mib"])
        self.assertFalse(first["execution_authorized"])
        self.assertEqual(self.workflow.current_inspection(request["request_id"], expected_revision=4).request.request_id, request["request_id"])

    def test_all_actual_scenarios_preserve_missing_empty_withheld_and_partial(self):
        for scenario in request_policy.SCENARIOS:
            request = self.inspect(scenario=scenario)
            actual = self.workflow.current_inspection(request["request_id"], expected_revision=request["revision"])
            summary = self.workflow.historical_summary(request["request_id"], history=self.history)["summary"]
            self.assertEqual(summary["logs"], actual.prepared.to_request()["collection_context"]["log_export"])
            self.assertTrue(summary["history_only"])

    def test_restart_requires_new_original_objects_and_does_not_autocollect(self):
        recorded = self.inspect()
        self.store.close()
        reopened = PersistentMockRequests(self.open(create=False), mock=True)
        with patch.object(runtime, "MockSession", side_effect=AssertionError("No automatic collection")):
            view = reopened.get(recorded["request_id"])
            reopened.events(recorded["request_id"])
            self.assertIsNotNone(reopened.historical_summary(recorded["request_id"], history=self.history))
            self.error("REINSPECTION_REQUIRED", lambda: reopened.current_inspection(recorded["request_id"], expected_revision=4))
        self.assertTrue(view["reinspection_required"])
        self.assertFalse(view["retained_evidence_available"])
        fresh = reopened.inspect(recorded["request_id"], expected_revision=4, idempotency_key=key(), history=self.history)
        self.assertTrue(fresh["retained_evidence_available"])
        self.assertEqual(fresh["request"]["brief_revision"], recorded["brief_revision"])

    def test_brief_update_invalidates_retained_objects_preserving_old_history(self):
        recorded = self.inspect()
        changed = self.workflow.supply_information(recorded["request_id"], {"goal": GOALS["review_again"]}, expected_revision=4, idempotency_key=key())["request"]
        self.assertEqual((changed["revision"], changed["brief_revision"]), (5, 2))
        self.assertNotEqual(changed["fingerprint"], recorded["fingerprint"])
        self.assertIsNone(changed["history_id"])
        self.error("REVISION_CONFLICT", lambda: self.workflow.current_inspection(recorded["request_id"], expected_revision=4))
        self.error("REINSPECTION_REQUIRED", lambda: self.workflow.current_inspection(recorded["request_id"], expected_revision=5))
        old = self.workflow.historical_summary(recorded["request_id"], history=self.history, revision=4)
        self.assertEqual(old["summary"]["request_fingerprint"], recorded["fingerprint"])
        self.assertIsNone(self.workflow.historical_summary(recorded["request_id"], history=self.history))

    def test_noop_completion_advances_transition_but_preserves_brief_and_association(self):
        request = self.inspect()
        changed = self.workflow.supply_information(request["request_id"], {}, expected_revision=4, idempotency_key=key())["request"]
        self.assertEqual(changed["brief_revision"], 1)
        self.assertEqual(changed["history_id"], request["history_id"])
        self.assertIsNotNone(self.workflow.current_inspection(request["request_id"], expected_revision=5))

    def test_retained_request_binding_source_and_evidence_mismatches(self):
        changes = [lambda i: i.request.details.update(goal=GOALS["review_again"]),
                   lambda i: object.__setattr__(i, "request", replace(i.request, request_id=key())),
                   lambda i: object.__setattr__(i, "source_binding", replace(i.source_binding, service_id="other")),
                   lambda i: object.__setattr__(i, "source_binding", replace(i.source_binding, project_name="other")),
                   lambda i: object.__setattr__(i, "source_binding", replace(i.source_binding, provider_scope="other")),
                   lambda i: object.__setattr__(i, "source_binding", replace(i.source_binding, is_mock=False)),
                   lambda i: setattr(i.presentation.evidence.snapshot, "service_id", "other"),
                   lambda i: setattr(i.presentation.evidence.snapshot, "data_source", "real"),
                   lambda i: setattr(i.presentation.report, "summary", CANARY),
                   lambda i: object.__setattr__(i, "prepared", i.prepared.to_request())]
        for change in changes:
            request = self.inspect()
            inspection = self.workflow.current_inspection(request["request_id"], expected_revision=4)
            change(inspection)
            self.error("EVIDENCE_MISMATCH", lambda: self.workflow.current_inspection(request["request_id"], expected_revision=4))

    def test_cross_request_and_different_current_brief_cannot_reuse_retained_objects(self):
        first, second = self.inspect(), self.inspect()
        self.workflow._retained[(second["request_id"], second["attempt_id"])] = self.workflow._retained[(first["request_id"], first["attempt_id"])]
        self.error("EVIDENCE_MISMATCH", lambda: self.workflow.current_inspection(second["request_id"], expected_revision=4))
        self.assertIsNotNone(self.workflow.current_inspection(first["request_id"], expected_revision=4))

    def test_expected_binding_is_selected_independently_of_retained_object(self):
        request = self.inspect()
        with patch.object(runtime, "mock_context_binding", return_value=replace(mock_context_binding(), provider_scope="changed")):
            self.error("EVIDENCE_MISMATCH", lambda: self.workflow.current_inspection(request["request_id"], expected_revision=4))
            self.error("HISTORY_FAILED", lambda: self.workflow.historical_summary(request["request_id"], history=self.history))

    def test_create_and_completion_receipts_idempotent_across_connections(self):
        token = key()
        first = self.workflow.create({}, idempotency_key=token)
        other = PersistentMockRequests(self.open(), mock=True)
        self.assertEqual(first, other.create({}, idempotency_key=token))
        request_id = first["request"]["request_id"]
        update_key = key()
        updated = other.supply_information(request_id, BRIEF, expected_revision=1, idempotency_key=update_key)
        self.assertEqual(updated, other.supply_information(request_id, BRIEF, expected_revision=1, idempotency_key=update_key))
        self.assertEqual(len(other.events(request_id)), 2)
        replay = self.workflow.create({}, idempotency_key=token)
        self.assertFalse(replay["is_current_revision"])
        self.assertEqual(replay["request"]["revision"], 1)

    def test_key_reused_for_other_content_operation_request_revision_or_scenario_rejected(self):
        token = key()
        request = self.workflow.create({}, idempotency_key=token)["request"]
        self.error("IDEMPOTENCY_CONFLICT", lambda: self.workflow.create(BRIEF, idempotency_key=token))
        self.error("IDEMPOTENCY_CONFLICT", lambda: self.workflow.supply_information(request["request_id"], BRIEF, expected_revision=1, idempotency_key=token))
        token = key()
        complete = self.workflow.supply_information(request["request_id"], BRIEF, expected_revision=1, idempotency_key=token)["request"]
        for request_id, revision, brief in ((key(), 1, BRIEF), (request["request_id"], 2, BRIEF), (request["request_id"], 1, {})):
            self.error("IDEMPOTENCY_CONFLICT", lambda: self.workflow.supply_information(request_id, brief, expected_revision=revision, idempotency_key=token))
        token = key()
        self.workflow.inspect(complete["request_id"], expected_revision=2, idempotency_key=token, history=self.history)
        self.error("IDEMPOTENCY_CONFLICT", lambda: self.workflow.inspect(complete["request_id"], expected_revision=2, idempotency_key=token, history=self.history, scenario="empty"))

    def test_inspection_replay_after_restart_returns_only_historical_receipt(self):
        request, token = self.create(), key()
        recorded = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        reopened = PersistentMockRequests(self.open(), mock=True)
        with patch.object(runtime, "MockSession", side_effect=AssertionError("No replay collection")):
            replay = reopened.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual(replay["request"], recorded["request"])
        self.assertTrue(replay["reinspection_required"])
        self.assertFalse(replay["execution_authorized"])

    def test_concurrent_stale_revision_writers_accept_exactly_one(self):
        request = self.create({})
        barrier = Barrier(2)
        def update(index):
            with SQLiteRequestStore(self.path) as store:
                workflow = PersistentMockRequests(store, mock=True)
                barrier.wait(timeout=5)
                try:
                    return workflow.supply_information(request["request_id"], {"goal": list(GOALS.values())[index]}, expected_revision=1, idempotency_key=key())["request"]["revision"]
                except RequestError as error:
                    return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, range(2)))
        self.assertCountEqual(results, [2, "REVISION_CONFLICT"])
        self.assertEqual(len(self.workflow.events(request["request_id"])), 2)

    def test_concurrent_identical_create_has_single_request_and_event(self):
        token, barrier = key(), Barrier(2)
        def create(_):
            with SQLiteRequestStore(self.path) as store:
                workflow = PersistentMockRequests(store, mock=True)
                barrier.wait(timeout=5)
                return workflow.create({}, idempotency_key=token)["request"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.workflow.events(results[0]["request_id"])), 1)

    def test_busy_timeout_is_bounded_and_retry_not_partially_written(self):
        request = self.create({})
        other = PersistentMockRequests(self.open(timeout=0.01), mock=True)
        self.store._connection.execute("BEGIN IMMEDIATE")
        token = key()
        try:
            self.error("STORAGE_BUSY", lambda: other.supply_information(request["request_id"], BRIEF, expected_revision=1, idempotency_key=token))
        finally:
            self.store._connection.rollback()
        self.assertEqual(self.store.get(request["request_id"]), request)
        self.assertEqual(other.supply_information(request["request_id"], BRIEF, expected_revision=1, idempotency_key=token)["request"]["revision"], 2)

    def test_event_failure_rolls_back_brief_and_receipt(self):
        request = self.create({})
        self.store._connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'fixed failure'); END")
        token = key()
        self.error("STORAGE_FAILED", lambda: self.workflow.supply_information(request["request_id"], BRIEF, expected_revision=1, idempotency_key=token))
        self.assertEqual(self.store.get(request["request_id"]), request)
        self.store._connection.execute("DROP TRIGGER fail_event")
        self.assertEqual(self.workflow.supply_information(request["request_id"], BRIEF, expected_revision=1, idempotency_key=token)["request"]["revision"], 2)

    def test_keyboard_interrupt_inside_transaction_rolls_back_every_write(self):
        original = self.store._write
        def interrupt(*args):
            original(*args)
            raise KeyboardInterrupt()
        token = key()
        with patch.object(self.store, "_write", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.workflow.create({}, idempotency_key=token)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM requests").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM receipts").fetchone()[0], 0)
        self.assertEqual(self.workflow.create({}, idempotency_key=token)["request"]["revision"], 1)

    def test_generated_id_collision_cannot_overwrite_an_accepted_brief(self):
        request = self.create()
        with patch.object(runtime, "uuid4", return_value=SimpleNamespace(hex=request["request_id"])):
            self.error("STORAGE_FAILED", lambda: self.workflow.create({}, idempotency_key=key()))
        self.assertEqual(self.store.get(request["request_id"]), request)
        self.assertEqual(len(self.workflow.events(request["request_id"])), 1)

    def test_missing_pending_receipt_rolls_back_recovery(self):
        request, token = self.create(), key()
        with patch.object(runtime, "MockSession", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.store._connection.execute("DELETE FROM receipts WHERE key=?", (token,))
        self.store._connection.commit()
        self.error("RECORD_CORRUPTED", lambda: self.workflow.recover(request["request_id"], expected_revision=2, idempotency_key=key()))
        self.assertEqual(self.store.get(request["request_id"])["revision"], 2)

    def test_collection_error_persists_explicit_failure_and_retry_does_not_recollect(self):
        request, token = self.create(), key()
        with patch.object(runtime, "MockSession", side_effect=RuntimeError(CANARY)) as collect:
            for _ in range(2):
                self.error("COLLECTION_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        self.assertEqual(collect.call_count, 1)
        state = self.store.get(request["request_id"])
        self.assertEqual(state["state"], "inspection_failed")
        self.assertIsNone(state["history_id"])

    def test_interrupted_collection_requires_explicit_recovery_then_fresh_inspection(self):
        request, token = self.create(), key()
        with patch.object(runtime, "MockSession", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        reopened = PersistentMockRequests(self.open(), mock=True)
        view = reopened.get(request["request_id"])
        self.assertEqual(view["request"]["state"], "inspecting")
        self.assertTrue(view["recovery_required"])
        self.error("RECOVERY_REQUIRED", lambda: reopened.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        self.error("RECOVERY_REQUIRED", lambda: reopened.inspect(request["request_id"], expected_revision=2, idempotency_key=key(), history=self.history))
        recovery_key = key()
        recovered = reopened.recover(request["request_id"], expected_revision=2, idempotency_key=recovery_key)
        self.assertEqual(recovered, reopened.recover(request["request_id"], expected_revision=2, idempotency_key=recovery_key))
        self.assertEqual(recovered["request"]["state"], "ready_for_inspection")
        replay = reopened.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual(replay["request"], recovered["request"])
        recorded = reopened.inspect(request["request_id"], expected_revision=3, idempotency_key=key(), history=self.history)
        self.assertTrue(recorded["retained_evidence_available"])

    def test_history_failure_pending_and_same_process_retry_reuses_actual_inspection(self):
        request, token = self.create(), key()
        with patch.object(service, "build_mock_context", wraps=service.build_mock_context) as collect, patch.object(
                triage_context, "diagnose", wraps=triage_context.diagnose) as diagnose:
            with patch.object(self.history, "save", side_effect=HistoryError()):
                self.error("HISTORY_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
            pending = self.store.get(request["request_id"])
            self.assertEqual(pending["state"], "awaiting_history")
            self.assertIsNone(pending["history_id"])
            result = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual((collect.call_count, diagnose.call_count), (1, 1))
        self.assertEqual(result["request"]["state"], "inspection_recorded")

    def test_noop_completion_during_pending_inspection_requires_recovery(self):
        request, token = self.create(), key()
        with patch.object(runtime, "MockSession", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.error("RECOVERY_REQUIRED", lambda: self.workflow.supply_information(request["request_id"], {}, expected_revision=2, idempotency_key=key()))
        self.assertEqual(self.store.get(request["request_id"])["revision"], 2)

    def test_recovery_receipt_replay_does_not_discard_newer_retained_evidence(self):
        request, token = self.create(), key()
        with patch.object(runtime, "MockSession", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        recovery = key()
        self.workflow.recover(request["request_id"], expected_revision=2, idempotency_key=recovery)
        completed = self.workflow.inspect(request["request_id"], expected_revision=3, idempotency_key=key(), history=self.history)["request"]
        replay = self.workflow.recover(request["request_id"], expected_revision=2, idempotency_key=recovery)
        self.assertFalse(replay["is_current_revision"])
        self.assertIsNotNone(self.workflow.current_inspection(request["request_id"], expected_revision=completed["revision"]))

    def test_interrupted_history_write_preserves_pending_and_same_instance_can_retry(self):
        request, token = self.create(), key()
        with patch.object(self.history, "save", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual(self.store.get(request["request_id"])["state"], "awaiting_history")
        with patch.object(runtime, "MockSession", side_effect=AssertionError("No new collector")):
            finished = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertTrue(finished["retained_evidence_available"])

    def test_history_must_be_saved_and_read_back_before_request_links_it(self):
        other = self.inspect()
        foreign = self.history.get(other["history_id"], expected_binding=mock_context_binding())
        request, token = self.create(), key()
        with patch.object(self.history, "save", return_value=foreign):
            self.error("HISTORY_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        self.assertIsNone(self.store.get(request["request_id"])["history_id"])
        with patch.object(self.history, "get", return_value=None):
            self.error("HISTORY_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        self.assertEqual(self.store.get(request["request_id"])["state"], "awaiting_history")

    def test_stored_complete_status_remains_historical_even_with_recomputed_checksums(self):
        request = self.create()
        forged = {**request, "state": "inspection_recorded", "attempt_id": key(), "scenario": "empty", "history_id": digest("forged")}
        db = self.store._connection
        db.execute("UPDATE requests SET payload=?,digest=? WHERE request_id=?", (canonical(forged), digest(forged), request["request_id"]))
        db.execute("UPDATE events SET payload=?,digest=? WHERE request_id=?", (canonical(forged), digest(forged), request["request_id"]))
        db.commit()
        loaded = PersistentMockRequests(self.open(), mock=True)
        view = loaded.get(request["request_id"])
        self.assertTrue(view["reinspection_required"])
        self.assertFalse(view["execution_authorized"])
        self.error("REINSPECTION_REQUIRED", lambda: loaded.current_inspection(request["request_id"], expected_revision=1))
        self.error("HISTORY_FAILED", lambda: loaded.historical_summary(request["request_id"], history=self.history))

    def test_historical_json_cannot_become_an_outcome_reference(self):
        request = self.inspect()
        summary = self.workflow.historical_summary(request["request_id"], history=self.history)
        ledger = EvidenceLedger(mock=True, request=operation(request["request_id"], request["details"]))
        for historical in (summary, summary["summary"], self.workflow.get(request["request_id"])):
            with self.assertRaises(OutcomeError) as caught:
                ledger.retain_provider(historical)
            self.assertEqual(caught.exception.code, "REFERENCE_REQUIRED")

    def test_unexpected_database_trigger_and_same_columns_wrong_schema_rejected(self):
        self.store._connection.execute("CREATE TRIGGER sqlitex_hidden AFTER INSERT ON requests BEGIN SELECT 1; END")
        self.error("UNSUPPORTED_DATABASE", lambda: self.open())
        self.store._connection.execute("DROP TRIGGER sqlitex_hidden")
        self.store._connection.execute("ALTER TABLE receipts RENAME TO previous_receipts")
        self.store._connection.execute("CREATE TABLE receipts(key,command_digest,pending,payload,digest)")
        self.store._connection.execute("DROP TABLE previous_receipts")
        self.error("UNSUPPORTED_DATABASE", lambda: self.open())

    def test_oversized_and_noncanonical_stored_payloads_fail_without_echoing(self):
        request = self.create()
        for payload in (" " * 5000 + CANARY, json.dumps(request, indent=2), CANARY):
            self.store._connection.execute("UPDATE requests SET payload=? WHERE request_id=?", (payload, request["request_id"]))
            self.store._connection.commit()
            self.error("RECORD_CORRUPTED", lambda: self.workflow.get(request["request_id"]))

    def test_failure_before_history_pending_commit_reuses_cached_producer_on_retry(self):
        request, token = self.create(), key()
        with patch.object(service, "build_mock_context", wraps=service.build_mock_context) as collect:
            with patch.object(self.store, "_advance_attempt", side_effect=RequestError("STORAGE_FAILED")):
                self.error("STORAGE_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
            result = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(result["request"]["state"], "inspection_recorded")

    def test_history_commit_then_request_failure_retries_without_duplicate_summary(self):
        request, token = self.create(), key()
        original = self.store._advance_attempt
        def fail_finish(*args, **kwargs):
            if kwargs["state"] == "inspection_recorded":
                raise RequestError("STORAGE_FAILED")
            return original(*args, **kwargs)
        with patch.object(self.store, "_advance_attempt", side_effect=fail_finish):
            self.error("STORAGE_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        original_records = self.history.list_for(expected_binding=mock_context_binding())
        self.assertEqual(len(original_records), 1)
        self.assertIsNone(self.store.get(request["request_id"])["history_id"])
        with patch.object(runtime, "MockSession", side_effect=AssertionError("No duplicate pipeline")):
            result = self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual(self.history.list_for(expected_binding=mock_context_binding()), original_records)
        self.assertEqual(result["request"]["history_id"], original_records[0].record_id)

    def test_restart_pending_history_does_not_link_or_reconstruct_orphan(self):
        request, token = self.create(), key()
        with patch.object(self.history, "save", side_effect=HistoryError()):
            self.error("HISTORY_FAILED", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        other = PersistentMockRequests(self.open(), mock=True)
        self.error("RECOVERY_REQUIRED", lambda: other.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        self.assertTrue(other.get(request["request_id"])["recovery_required"])
        self.assertIsNone(other.historical_summary(request["request_id"], history=self.history))

    def test_update_during_collection_cannot_attach_old_inspection(self):
        request, token = self.create(), key()
        other = PersistentMockRequests(self.open(), mock=True)
        original = runtime.MockSession
        def collect(**kwargs):
            other.supply_information(request["request_id"], {"goal": GOALS["review_again"]}, expected_revision=2, idempotency_key=key())
            return original(**kwargs)
        with patch.object(runtime, "MockSession", side_effect=collect):
            self.error("REVISION_CONFLICT", lambda: self.workflow.inspect(request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
        current = self.store.get(request["request_id"])
        self.assertEqual(current["state"], "ready_for_inspection")
        self.assertIsNone(current["history_id"])
        self.assertEqual(self.history.list_for(expected_binding=mock_context_binding()), ())

    def test_pagination_bounded_order_and_cross_request_isolation(self):
        request, other = self.create({}), self.create({})
        for revision in range(1, 6):
            self.workflow.supply_information(request["request_id"], {}, expected_revision=revision, idempotency_key=key())
        page = self.workflow.events(request["request_id"], limit=2)
        self.assertEqual([item["request"]["revision"] for item in page], [6, 5])
        second = self.workflow.events(request["request_id"], limit=2, before_revision=5)
        self.assertEqual([item["request"]["revision"] for item in second], [4, 3])
        self.assertEqual(len(self.workflow.events(other["request_id"])), 1)
        self.assertEqual(self.workflow.events(request["request_id"], before_revision=1), [])
        for limit in (0, 101, True, "2"):
            self.error("INVALID_LOOKUP", lambda: self.workflow.events(request["request_id"], limit=limit))
        for cursor in (0, True, CANARY):
            self.error("INVALID_LOOKUP", lambda: self.workflow.events(request["request_id"], before_revision=cursor))
        for invalid in (CANARY, "' OR 1=1--", None, [], "1" * 33):
            self.error("INVALID_LOOKUP", lambda: self.workflow.get(invalid))
        self.error("NOT_FOUND", lambda: self.workflow.get(key()))

    def test_corrupt_or_forged_flags_cannot_be_displayed_as_authority(self):
        request = self.create()
        value = {**request, "execution_authorized": True, "approved": True, "token": CANARY}
        self.store._connection.execute("UPDATE requests SET payload=?,digest=? WHERE request_id=?", (canonical(value), digest(value), request["request_id"]))
        self.store._connection.commit()
        self.error("RECORD_CORRUPTED", lambda: self.workflow.get(request["request_id"]))

    def test_missing_or_mismatched_latest_event_rejected(self):
        request = self.create()
        self.store._connection.execute("DELETE FROM events WHERE request_id=?", (request["request_id"],))
        self.store._connection.commit()
        self.error("RECORD_CORRUPTED", lambda: self.workflow.get(request["request_id"]))

    def test_foreign_unsupported_corrupt_and_history_databases_rejected_without_migration(self):
        for suffix, sql in (("foreign", "CREATE TABLE private(value TEXT)"),
                            ("newer", f"PRAGMA application_id={APPLICATION_ID}"),
                            ("copied", f"PRAGMA application_id={APPLICATION_ID}")):
            path = Path(self.directory.name) / (suffix + ".sqlite")
            with closing(sqlite3.connect(path)) as db:
                db.execute(sql)
                if suffix != "foreign":
                    db.execute("PRAGMA user_version=" + ("2" if suffix == "newer" else "1"))
                db.commit()
            before = path.read_bytes()
            self.error("UNSUPPORTED_DATABASE", lambda: SQLiteRequestStore(path))
            self.assertEqual(path.read_bytes(), before)
        self.error("UNSUPPORTED_DATABASE", lambda: SQLiteRequestStore(self.history_path))
        corrupt = Path(self.directory.name) / "corrupt.sqlite"
        corrupt.write_bytes(CANARY.encode())
        self.error("STORAGE_FAILED", lambda: SQLiteRequestStore(corrupt))
        self.assertEqual(corrupt.read_bytes(), CANARY.encode())

    def test_invalid_database_timeout_paths_and_explicit_close(self):
        for timeout in (True, 0, -1, float("nan"), float("inf"), 31, "1"):
            self.error("INVALID_DATABASE", lambda: SQLiteRequestStore(self.path, timeout=timeout))
        self.error("INVALID_DATABASE", lambda: SQLiteRequestStore(Path(self.directory.name) / "missing.sqlite", create=False))
        self.store.close()
        self.store.close()
        self.error("STORE_CLOSED", lambda: self.store.get(key()))

    def test_controlled_policy_privacy_in_errors_repr_logs_json_and_database(self):
        stdout, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        logger = logging.Logger("requests-safe")
        logger.addHandler(logging.StreamHandler(logs))
        with redirect_stdout(stdout), redirect_stderr(stderr):
            for brief in ({"goal": CANARY}, {"Authorization": "Bearer " + CANARY}, {"service_target": CANARY},
                          {"config": {"api_key": CANARY}}, {"goal": {"nested": CANARY}}):
                with self.assertRaises(RequestError) as caught:
                    self.workflow.create(brief, idempotency_key=key())
                logger.warning("%r %r %r", self.workflow, self.store, caught.exception)
            request = self.inspect(scenario="exported")
            safe = self.workflow.get(request["request_id"])
            summary = self.workflow.historical_summary(request["request_id"], history=self.history)
        self.store.close()
        self.history.close()
        text = stdout.getvalue() + stderr.getvalue() + logs.getvalue() + json.dumps([safe, summary])
        self.assertNotIn(CANARY, text)
        self.assertNotIn("Synthetic application started", text)
        for path in (self.path, self.history_path):
            for secret in (CANARY, "Synthetic application started", "mock-project", "mock-account", "Authorization"):
                self.assertNotIn(secret.encode(), path.read_bytes())

    def test_mutated_pydantic_values_cannot_leak_through_warning_diagnostics(self):
        request = self.inspect()
        inspection = self.workflow.current_inspection(request["request_id"], expected_revision=4)
        inspection.presentation.report.summary = {CANARY: CANARY}
        stdout, stderr = io.StringIO(), io.StringIO()
        with warnings.catch_warnings(record=True) as captured, redirect_stdout(stdout), redirect_stderr(stderr):
            warnings.simplefilter("always")
            self.error("EVIDENCE_MISMATCH", lambda: self.workflow.current_inspection(request["request_id"], expected_revision=4))
        self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue() + str(captured))

    def test_literal_optin_and_json_never_mints_current_evidence(self):
        for optin in (False, 1, "true", None):
            self.error("MOCK_OPT_IN_REQUIRED", lambda: PersistentMockRequests(self.store, mock=optin))
        request = self.inspect()
        historical = self.workflow.historical_summary(request["request_id"], history=self.history)
        for item in (historical, self.workflow.get(request["request_id"]), historical["summary"]):
            self.error("INVALID_LOOKUP", lambda: self.workflow.current_inspection(item, expected_revision=4))
        forged_cache = self.workflow._retained.copy()
        forged_cache[(request["request_id"], request["attempt_id"])] = (1, request["fingerprint"], historical)
        self.workflow._retained = forged_cache
        self.error("EVIDENCE_MISMATCH", lambda: self.workflow.current_inspection(request["request_id"], expected_revision=4))
