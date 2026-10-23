"""Request access/ownership tests over actual offline component composition."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
import logging
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from infrapilot_triage import ApprovalGate, collection_context
from infrapilot_triage.identity import AuthenticatedActor
from provider import MockLiaraClient
from provider.examples.context_fixtures import mock_context_binding
from setup import application

from integration import request_policy, requests, service
from integration.access import ProtectedMockRequests
from integration.access_identity import AccessContext, MockRequestIdentity, RequestPermission, ResolvedAccess, binding_reference
from integration.access_store import APPLICATION_ID, SQLiteOwnershipStore
from integration.history import SQLiteInspectionHistory
from integration.request_errors import RequestError
from integration.request_policy import GOALS, TARGET, canonical, digest
from integration.request_store import SQLiteRequestStore

CANARY = "PRIVATE-ACCESS-CANARY-197382"
BRIEF = {"service_target": TARGET, "goal": GOALS["review"]}


def key():
    return uuid4().hex


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for name in ("socket.socket", "socket.create_connection", "subprocess.Popen", "urllib.request.build_opener"):
            self.guards.enter_context(patch(name, side_effect=AssertionError("Offline only")))
        for name in ("request_approval", "approve", "reject", "authorize"):
            self.guards.enter_context(patch.object(ApprovalGate, name, side_effect=AssertionError("No gate operation")))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.store = SQLiteRequestStore(self.path / "requests.sqlite")
        self.addCleanup(self.store.close)
        self.owners = SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=self.store)
        self.addCleanup(self.owners.close)
        self.history = SQLiteInspectionHistory(self.path / "history.sqlite")
        self.addCleanup(self.history.close)
        self.now = [datetime.now(timezone.utc)]
        self.identity = MockRequestIdentity(mock=True, clock=lambda: self.now[0])
        self.owner, self.other = self.identity.issue(), self.identity.issue("other")
        self.backend = self.facade()

    def facade(self, *, identity=None, expected_binding=None):
        return ProtectedMockRequests(self.store, self.owners, identity=self.identity if identity is None else identity,
                                     expected_binding=expected_binding, mock=True)

    def create(self, brief=None, **kwargs):
        return self.backend.create(self.owner, BRIEF if brief is None else brief, idempotency_key=key(), **kwargs)["request"]

    def inspect(self, request=None):
        request = request or self.create()
        return self.backend.inspect(self.owner, request["request_id"], expected_revision=request["revision"],
                                    idempotency_key=key(), history=self.history)["request"]

    def error(self, code, action):
        with self.assertRaises(RequestError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, repr(caught.exception) + str(caught.exception))

    def test_authorized_owner_actual_setup_collector_engine_companion_history_once(self):
        token = key()
        with patch.object(request_policy, "submit_request", wraps=application.submit_request) as intake, patch.object(
                request_policy, "supply_information", wraps=application.supply_information) as complete, patch.object(
                MockLiaraClient, "collect_service_observations", autospec=True, side_effect=MockLiaraClient.collect_service_observations) as collect, patch.object(
                collection_context, "diagnose", wraps=collection_context.diagnose) as diagnose:
            request = self.create({"service_target": TARGET})
            self.backend.supply_information(self.owner, request["request_id"], {"goal": GOALS["review"]}, expected_revision=1, idempotency_key=key())
            result = self.backend.inspect(self.owner, request["request_id"], expected_revision=2, idempotency_key=token, history=self.history)
            replay = self.backend.inspect(self.owner, request["request_id"], expected_revision=2, idempotency_key=token, history=self.history)
            self.backend.get(self.owner, request["request_id"])
            self.backend.events(self.owner, request["request_id"])
            summary = self.backend.historical_summary(self.owner, request["request_id"], history=self.history)["summary"]
        self.assertEqual((intake.call_count, complete.call_count, collect.call_count, diagnose.call_count), (1, 1, 1, 1))
        self.assertEqual(result, replay)
        self.assertEqual(result["request"]["revision"], 5)
        self.assertEqual(summary["capabilities"][2]["http_status"], 403)
        self.assertEqual(summary["capabilities"][3]["http_status"], 429)
        self.assertIsNone(summary["cpu_usage_percent"])
        self.assertEqual(summary["application_health"], "unknown")
        self.assertFalse(result["execution_authorized"])
        self.backend.current_inspection(self.owner, request["request_id"], expected_revision=5).validate()

    def test_unconfigured_identity_boundary_is_denied_before_lower_level(self):
        backend = ProtectedMockRequests(self.store, self.owners, mock=True)
        with patch.object(backend._workflow, "create", side_effect=AssertionError("No intake")):
            self.error("ACCESS_DENIED", lambda: backend.create(self.owner, BRIEF, idempotency_key=key()))

    def test_forged_missing_or_foreign_contexts_cannot_become_identity(self):
        request = self.create()
        foreign = MockRequestIdentity(mock=True).issue()
        claims = ResolvedAccess(AuthenticatedActor("1" * 32), 1, frozenset(RequestPermission), (mock_context_binding(),))
        for context in (None, {}, {"subject": "1" * 32, "roles": ["admin"], "token": CANARY},
                        AuthenticatedActor("1" * 32), claims, foreign, object.__new__(AccessContext), CANARY, object()):
            self.error("ACCESS_DENIED", lambda: self.backend.get(context, request["request_id"]))
        self.error("ACCESS_DENIED", AccessContext)

    def test_expiration_revocation_bad_clock_and_backwards_clock_fail_closed(self):
        request = self.create()
        self.now[0] += timedelta(seconds=300)
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, request["request_id"]))
        fresh = self.identity.issue()
        self.identity.revoke(fresh)
        self.error("ACCESS_DENIED", lambda: self.backend.get(fresh, request["request_id"]))
        for value in (None, datetime.now(), self.now[0] - timedelta(days=1)):
            context = self.identity.issue()
            original = self.now[0]
            self.now[0] = value
            self.error("ACCESS_DENIED", lambda: self.backend.get(context, request["request_id"]))
            self.now[0] = original
        with patch.object(self.identity, "_clock", side_effect=RuntimeError(CANARY)):
            self.error("ACCESS_DENIED", lambda: self.identity.issue())

    def test_expired_or_clock_rollback_context_cannot_revive_when_clock_changes(self):
        issued = self.now[0]
        self.now[0] += timedelta(seconds=301)
        self.assertIsNone(self.identity.resolve(self.owner))
        self.now[0] = issued
        self.assertIsNone(self.identity.resolve(self.owner))
        context = self.identity.issue()
        self.now[0] += timedelta(seconds=20)
        self.assertIsNotNone(self.identity.resolve(context))
        self.now[0] -= timedelta(seconds=5)
        self.assertIsNone(self.identity.resolve(context))
        self.now[0] += timedelta(seconds=10)
        self.assertIsNone(self.identity.resolve(context))

    def test_wrong_owner_all_operations_denied_without_workflow_reads_or_writes(self):
        request = self.inspect()
        request_id = request["request_id"]
        actions = [lambda: self.backend.get(self.other, request_id), lambda: self.backend.events(self.other, request_id),
                   lambda: self.backend.supply_information(self.other, request_id, BRIEF, expected_revision=4, idempotency_key=key()),
                   lambda: self.backend.inspect(self.other, request_id, expected_revision=4, idempotency_key=key(), history=self.history),
                   lambda: self.backend.recover(self.other, request_id, expected_revision=4, idempotency_key=key()),
                   lambda: self.backend.current_inspection(self.other, request_id, expected_revision=4),
                   lambda: self.backend.historical_summary(self.other, request_id, history=self.history)]
        with patch.object(self.store, "get", side_effect=AssertionError("No request lookup")):
            for action in actions:
                self.error("ACCESS_DENIED", action)
        # Unauthorized guesses cannot discard the actual owner's cached evidence.
        self.assertTrue(self.backend.get(self.owner, request_id)["retained_evidence_available"])

    def test_missing_unknown_invalid_and_unowned_ids_have_same_denial(self):
        request = self.create()
        bare = requests.PersistentMockRequests(self.store, mock=True).create(BRIEF, idempotency_key=key())["request"]
        for request_id in (request["request_id"], bare["request_id"], key(), CANARY, "' OR 1=1--", None):
            self.error("ACCESS_DENIED", lambda: self.backend.get(self.other, request_id))
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, bare["request_id"]))

    def test_independent_operation_permissions_are_enforced(self):
        request = self.create()
        operations = {
            RequestPermission.CREATE: lambda c: self.backend.create(c, BRIEF, idempotency_key=key()),
            RequestPermission.READ: lambda c: self.backend.get(c, request["request_id"]),
            RequestPermission.COMPLETE: lambda c: self.backend.supply_information(c, request["request_id"], {}, expected_revision=1, idempotency_key=key()),
            RequestPermission.INSPECT: lambda c: self.backend.inspect(c, request["request_id"], expected_revision=1, idempotency_key=key(), history=self.history),
            RequestPermission.HISTORY: lambda c: self.backend.historical_summary(c, request["request_id"], history=self.history),
            RequestPermission.RECOVER: lambda c: self.backend.recover(c, request["request_id"], expected_revision=1, idempotency_key=key()),
        }
        for permission, operation in operations.items():
            self.identity.configure("owner", permissions=frozenset(set(RequestPermission) - {permission}))
            context = self.identity.issue()
            self.error("ACCESS_DENIED", lambda: operation(context))
        self.identity.configure("owner", permissions=frozenset({RequestPermission.INSPECT}))
        context = self.identity.issue()
        self.error("ACCESS_DENIED", lambda: self.backend.inspect(context, request["request_id"], expected_revision=1, idempotency_key=key(), history=self.history))

    def test_service_grants_and_independent_expected_binding_cover_every_dimension(self):
        request = self.create()
        for change in ({"service_id": "other"}, {"project_name": "other"}, {"provider_scope": "other"}, {"is_mock": False}):
            different = replace(mock_context_binding(), **change)
            self.identity.configure("owner", bindings=(different,))
            self.error("ACCESS_DENIED", lambda: self.backend.get(self.identity.issue(), request["request_id"]))
            self.error("ACCESS_DENIED", lambda: self.facade(expected_binding=different).get(self.identity.issue(), request["request_id"]))
        self.identity.configure("owner", bindings=())
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.identity.issue(), request["request_id"]))

    def test_idempotency_key_is_scoped_to_owner_and_full_binding(self):
        token = key()
        first = self.backend.create(self.owner, BRIEF, idempotency_key=token)
        second = self.backend.create(self.other, BRIEF, idempotency_key=token)
        self.assertNotEqual(first["request"]["request_id"], second["request"]["request_id"])
        self.assertEqual(first, self.backend.create(self.owner, BRIEF, idempotency_key=token))
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.other, first["request"]["request_id"]))
        self.error("IDEMPOTENCY_CONFLICT", lambda: self.backend.create(self.owner, {}, idempotency_key=token))
        self.identity.configure("owner", bindings=(replace(mock_context_binding(), provider_scope="other"),))
        self.error("ACCESS_DENIED", lambda: self.backend.create(self.identity.issue(), BRIEF, idempotency_key=token))

    def test_authorization_precedes_cached_receipts_and_retained_evidence(self):
        request, token = self.create(), key()
        self.backend.inspect(self.owner, request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.identity.configure("owner", permissions=frozenset())
        for action in (lambda: self.backend.inspect(self.owner, request["request_id"], expected_revision=1, idempotency_key=token, history=self.history),
                       lambda: self.backend.current_inspection(self.owner, request["request_id"], expected_revision=4)):
            self.error("ACCESS_DENIED", action)
        self.identity.configure("owner", permissions=frozenset(RequestPermission))
        self.owner = self.identity.issue()
        self.assertTrue(self.backend.get(self.owner, request["request_id"])["reinspection_required"])
        self.error("REINSPECTION_REQUIRED", lambda: self.backend.current_inspection(self.owner, request["request_id"], expected_revision=4))

    def test_grant_changes_invalidate_old_context_even_if_permissions_restored(self):
        self.identity.configure("owner", permissions=frozenset())
        self.identity.configure("owner", permissions=frozenset(RequestPermission))
        self.error("ACCESS_DENIED", lambda: self.backend.create(self.owner, BRIEF, idempotency_key=key()))

    def test_revocation_during_collection_stops_before_diagnosis_or_current_link(self):
        request = self.create()
        original = requests.MockSession
        def collect(**kwargs):
            session = original(**kwargs)
            self.identity.revoke(self.owner)
            return session
        with patch.object(requests, "MockSession", side_effect=collect), patch.object(collection_context, "diagnose", wraps=collection_context.diagnose) as diagnose:
            self.error("ACCESS_DENIED", lambda: self.inspect(request))
        self.assertEqual(diagnose.call_count, 0)
        current = self.store.get(request["request_id"])
        self.assertEqual(current["state"], "inspecting")
        self.assertIsNone(current["history_id"])
        self.assertEqual(self.history.list_for(expected_binding=mock_context_binding()), ())

    def test_access_storage_failure_after_collection_remains_pending_and_is_not_collection_failure(self):
        request = self.create()
        original = requests.MockSession
        with ExitStack() as stack:
            def collect(**kwargs):
                session = original(**kwargs)
                stack.enter_context(patch.object(self.owners, "get", side_effect=RequestError("STORAGE_BUSY")))
                return session
            with patch.object(requests, "MockSession", side_effect=collect), patch.object(collection_context, "diagnose", wraps=collection_context.diagnose) as diagnose:
                self.error("STORAGE_BUSY", lambda: self.inspect(request))
        self.assertEqual(diagnose.call_count, 0)
        current = self.store.get(request["request_id"])
        self.assertEqual(current["state"], "inspecting")
        self.assertIsNone(current["error_code"])

    def test_owner_transfer_during_collection_cannot_attach_to_new_owner(self):
        request = self.create()
        original = requests.MockSession
        def collect(**kwargs):
            session = original(**kwargs)
            self.owners.transfer(request["request_id"], owner_ref="2" * 32, expected_revision=1)
            return session
        with patch.object(requests, "MockSession", side_effect=collect):
            self.error("ACCESS_DENIED", lambda: self.inspect(request))
        self.assertTrue(self.backend.get(self.other, request["request_id"])["recovery_required"])
        self.backend.recover(self.other, request["request_id"], expected_revision=2, idempotency_key=key())
        result = self.backend.inspect(self.other, request["request_id"], expected_revision=3, idempotency_key=key(), history=self.history)
        self.assertTrue(result["retained_evidence_available"])

    def test_revocation_during_actual_diagnosis_cannot_link_or_export_result(self):
        request = self.create()
        original = collection_context.diagnose
        def diagnose(snapshot):
            result = original(snapshot)
            self.identity.revoke(self.owner)
            return result
        with patch.object(collection_context, "diagnose", side_effect=diagnose) as engine:
            self.error("ACCESS_DENIED", lambda: self.inspect(request))
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(self.store.get(request["request_id"])["state"], "inspecting")
        self.assertFalse(self.backend._workflow._retained)
        self.assertEqual(self.history.list_for(expected_binding=mock_context_binding()), ())

    def test_revocation_after_history_commit_leaves_unlinked_historical_artifact(self):
        request = self.create()
        original = self.history.save
        def save(inspection):
            result = original(inspection)
            self.identity.configure("owner", permissions=frozenset())
            return result
        with patch.object(self.history, "save", side_effect=save):
            self.error("ACCESS_DENIED", lambda: self.inspect(request))
        current = self.store.get(request["request_id"])
        self.assertEqual(current["state"], "awaiting_history")
        self.assertIsNone(current["history_id"])
        self.assertEqual(len(self.history.list_for(expected_binding=mock_context_binding())), 1)
        self.identity.configure("owner", permissions=frozenset(RequestPermission))
        self.owner = self.identity.issue()
        self.assertTrue(self.backend.get(self.owner, request["request_id"])["recovery_required"])

    def test_permission_loss_before_transaction_commit_rolls_back_request_event_and_receipt(self):
        request = self.create({"service_target": TARGET})
        original = self.store._write
        def write(*args):
            result = original(*args)
            self.identity.revoke(self.owner)
            return result
        with patch.object(self.store, "_write", side_effect=write):
            self.error("ACCESS_DENIED", lambda: self.backend.supply_information(self.owner, request["request_id"], {"goal": GOALS["review"]}, expected_revision=1, idempotency_key=key()))
        self.assertEqual(self.store.get(request["request_id"]), request)
        self.assertEqual(len(self.store.events(request["request_id"])), 1)

    def test_failed_ownership_registration_leaves_inaccessible_request_and_retry_is_idempotent(self):
        token = key()
        with patch.object(request_policy, "submit_request", wraps=application.submit_request) as intake:
            with patch.object(self.owners, "register", side_effect=RequestError("STORAGE_FAILED")):
                self.error("STORAGE_FAILED", lambda: self.backend.create(self.owner, BRIEF, idempotency_key=token))
            request_id = self.store._connection.execute("SELECT request_id FROM requests").fetchone()[0]
            self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, request_id))
            result = self.backend.create(self.owner, BRIEF, idempotency_key=token)
        self.assertEqual(intake.call_count, 1)
        self.assertEqual(result["request"]["request_id"], request_id)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM requests").fetchone()[0], 1)

    def test_ownership_registration_revocation_rolls_back_metadata(self):
        original = self.owners._payload
        def payload(owner):
            self.identity.revoke(self.owner)
            return original(owner)
        with patch.object(self.owners, "_payload", side_effect=payload):
            self.error("ACCESS_DENIED", lambda: self.create())
        self.assertEqual(self.owners._connection.execute("SELECT count(*) FROM owners").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM requests").fetchone()[0], 1)

    def test_old_owner_create_receipt_cannot_override_explicit_transfer(self):
        token = key()
        request = self.backend.create(self.owner, BRIEF, idempotency_key=token)["request"]
        self.owners.transfer(request["request_id"], owner_ref="2" * 32, expected_revision=1)
        self.error("ACCESS_DENIED", lambda: self.backend.create(self.owner, BRIEF, idempotency_key=token))
        self.assertEqual(self.backend.get(self.other, request["request_id"])["request"], request)

    def test_changed_ownership_revision_invalidates_retained_evidence_even_when_owner_returns(self):
        request = self.inspect()
        self.owners.transfer(request["request_id"], owner_ref="2" * 32, expected_revision=1)
        self.owners.transfer(request["request_id"], owner_ref="1" * 32, expected_revision=2)
        self.assertTrue(self.backend.get(self.owner, request["request_id"])["reinspection_required"])

    def test_close_reopen_retains_ownership_but_never_context_or_evidence(self):
        request = self.inspect()
        self.owners.close()
        self.store.close()
        with SQLiteRequestStore(self.path / "requests.sqlite", create=False) as store, SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=store, create=False) as owners:
            identity = MockRequestIdentity(mock=True)
            backend = ProtectedMockRequests(store, owners, identity=identity, mock=True)
            self.error("ACCESS_DENIED", lambda: backend.get(self.owner, request["request_id"]))
            context = identity.issue()
            view = backend.get(context, request["request_id"])
            self.assertTrue(view["reinspection_required"])
            self.error("REINSPECTION_REQUIRED", lambda: backend.current_inspection(context, request["request_id"], expected_revision=4))
            self.assertIsNotNone(backend.historical_summary(context, request["request_id"], history=self.history))

    def test_interrupted_attempt_recovery_keeps_access_checks_and_reinspection(self):
        request = self.create()
        with patch.object(requests, "MockSession", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.inspect(request)
        self.error("ACCESS_DENIED", lambda: self.backend.recover(self.other, request["request_id"], expected_revision=2, idempotency_key=key()))
        recovered = self.backend.recover(self.owner, request["request_id"], expected_revision=2, idempotency_key=key())["request"]
        self.assertEqual(recovered["state"], "ready_for_inspection")
        self.assertEqual(self.inspect(recovered)["state"], "inspection_recorded")

    def test_forged_ownership_flags_cannot_establish_identity_or_privilege(self):
        request = self.create()
        record = self.owners.get(request["request_id"])
        payload = {**self.owners._payload(record), "roles": ["admin"], "approved": True, "token": CANARY}
        self.owners._connection.execute("UPDATE owners SET payload=?,digest=? WHERE request_id=?", (canonical(payload), digest(payload), request["request_id"]))
        self.owners._connection.commit()
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, request["request_id"]))

    def test_owner_binding_cannot_be_swapped_by_matching_alias(self):
        request = self.create()
        owner = self.owners.get(request["request_id"])
        data = {**self.owners._payload(owner), "binding_ref": binding_reference(replace(mock_context_binding(), provider_scope="other"))}
        self.owners._connection.execute("UPDATE owners SET payload=?,digest=? WHERE request_id=?", (canonical(data), digest(data), request["request_id"]))
        self.owners._connection.commit()
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, request["request_id"]))

    def test_wrong_request_database_cannot_reuse_ownership_store(self):
        before = (self.path / "owners.sqlite").read_bytes()
        with SQLiteRequestStore(self.path / "different.sqlite") as other:
            self.error("INVALID_DATABASE", lambda: SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=other))
            self.error("INVALID_DATABASE", lambda: ProtectedMockRequests(other, self.owners, identity=self.identity, mock=True))
        self.assertEqual((self.path / "owners.sqlite").read_bytes(), before)

    def test_ownership_schema_foreign_history_newer_and_corrupt_files_are_not_migrated(self):
        for name in ("requests.sqlite", "history.sqlite"):
            self.error("UNSUPPORTED_DATABASE", lambda: SQLiteOwnershipStore(self.path / name, request_store=self.store))
        for name, data in (("corrupt.sqlite", CANARY.encode()),):
            path = self.path / name
            path.write_bytes(data)
            self.error("STORAGE_FAILED", lambda: SQLiteOwnershipStore(path, request_store=self.store))
            self.assertEqual(path.read_bytes(), data)
        path = self.path / "future.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=2")
            db.commit()
        before = path.read_bytes()
        self.error("UNSUPPORTED_DATABASE", lambda: SQLiteOwnershipStore(path, request_store=self.store))
        self.assertEqual(path.read_bytes(), before)

    def test_lock_timeout_then_same_create_retry_recovers_unregistered_request(self):
        with SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=self.store, timeout=0.01) as owners:
            backend = ProtectedMockRequests(self.store, owners, identity=self.identity, mock=True)
            token = key()
            self.owners._connection.execute("BEGIN IMMEDIATE")
            try:
                self.error("STORAGE_BUSY", lambda: backend.create(self.owner, BRIEF, idempotency_key=token))
            finally:
                self.owners._connection.rollback()
            self.assertEqual(backend.create(self.owner, BRIEF, idempotency_key=token)["request"]["revision"], 1)
            self.assertEqual(self.store._connection.execute("SELECT count(*) FROM requests").fetchone()[0], 1)

    def test_concurrent_same_owner_create_registers_once(self):
        token, barrier = key(), Barrier(2)
        def create(_):
            with SQLiteRequestStore(self.path / "requests.sqlite") as store, SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=store) as owners:
                identity = MockRequestIdentity(mock=True)
                backend = ProtectedMockRequests(store, owners, identity=identity, mock=True)
                barrier.wait(timeout=5)
                return backend.create(identity.issue(), BRIEF, idempotency_key=token)["request"]["request_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(create, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.owners._connection.execute("SELECT count(*) FROM owners").fetchone()[0], 1)

    def test_safe_canaries_in_rejected_contexts_briefs_errors_repr_logs_and_databases(self):
        stdout, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        logger = logging.Logger("access-safe")
        logger.addHandler(logging.StreamHandler(logs))
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.error("ACCESS_DENIED", lambda: self.backend.create({"Authorization": CANARY}, BRIEF, idempotency_key=key()))
            self.error("INVALID_REQUEST", lambda: self.backend.create(self.owner, {"goal": CANARY}, idempotency_key=key()))
            with patch.object(self.identity, "resolve", side_effect=RuntimeError(CANARY)):
                self.error("ACCESS_DENIED", lambda: self.create())
            request = self.inspect()
            view = self.backend.get(self.owner, request["request_id"])
            summary = self.backend.historical_summary(self.owner, request["request_id"], history=self.history)
            logger.warning("%r %r %r %r %r", self.identity, self.owner, self.backend, self.owners, RequestError(CANARY))
        self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue() + logs.getvalue() + json.dumps([view, summary]))
        self.history.close()
        self.owners.close()
        self.store.close()
        for name in ("requests.sqlite", "owners.sqlite", "history.sqlite"):
            for secret in (CANARY, "Authorization", "Synthetic application started", "mock-account", "mock-project"):
                self.assertNotIn(secret.encode(), (self.path / name).read_bytes())

    def test_malformed_trusted_resolver_outputs_are_denied(self):
        request = self.create()
        grant = self.identity.resolve(self.owner)
        for output in (True, {"actor": "1" * 32}, replace(grant, actor="1" * 32),
                       replace(grant, permissions=frozenset({"read_request"})), replace(grant, generation=True),
                       replace(grant, bindings=(CANARY,)), replace(grant, actor=AuthenticatedActor(CANARY))):
            with patch.object(self.identity, "resolve", return_value=output):
                self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, request["request_id"]))

    def test_ownership_change_during_history_read_is_not_exposed(self):
        request = self.inspect()
        original = self.history.get
        def read(*args, **kwargs):
            result = original(*args, **kwargs)
            self.owners.transfer(request["request_id"], owner_ref="2" * 32, expected_revision=1)
            return result
        with patch.object(self.history, "get", side_effect=read):
            self.error("ACCESS_DENIED", lambda: self.backend.historical_summary(self.owner, request["request_id"], history=self.history))

    def test_same_owner_cross_request_history_reference_is_rejected(self):
        first, second = self.inspect(), self.inspect()
        swapped = {**second, "history_id": first["history_id"]}
        db = self.store._connection
        db.execute("UPDATE requests SET payload=?,digest=? WHERE request_id=?", (canonical(swapped), digest(swapped), second["request_id"]))
        db.execute("UPDATE events SET payload=?,digest=? WHERE request_id=? AND revision=?", (canonical(swapped), digest(swapped), second["request_id"], second["revision"]))
        db.commit()
        self.error("HISTORY_FAILED", lambda: self.backend.historical_summary(self.owner, second["request_id"], history=self.history))

    def test_create_revocation_inside_request_transaction_leaves_no_rows_or_receipt(self):
        original = self.store._write
        def write(*args):
            result = original(*args)
            self.identity.revoke(self.owner)
            return result
        with patch.object(self.store, "_write", side_effect=write):
            self.error("ACCESS_DENIED", lambda: self.create())
        for table in ("requests", "events", "receipts"):
            self.assertEqual(self.store._connection.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)
        self.assertEqual(self.owners._connection.execute("SELECT count(*) FROM owners").fetchone()[0], 0)

    def test_stale_ownership_transfers_accept_exactly_one_writer(self):
        request = self.create()
        barrier = Barrier(2)
        def transfer(index):
            with SQLiteRequestStore(self.path / "requests.sqlite") as store, SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=store) as owners:
                barrier.wait(timeout=5)
                try:
                    return owners.transfer(request["request_id"], owner_ref=str(index + 2) * 32, expected_revision=1).revision
                except RequestError as error:
                    return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(transfer, range(2)))
        self.assertCountEqual(results, [2, "REVISION_CONFLICT"])

    def test_ownership_store_limits_schema_checks_and_failed_constructor_cleanup(self):
        for timeout in (True, 0, -1, float("nan"), float("inf"), 31):
            self.error("INVALID_DATABASE", lambda: SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=self.store, timeout=timeout))
        self.error("INVALID_DATABASE", lambda: SQLiteOwnershipStore(self.path / "absent.sqlite", request_store=self.store, create=False))
        request = self.create()
        self.owners._connection.execute("UPDATE owners SET payload=? WHERE request_id=?", (" " * 1100 + CANARY, request["request_id"]))
        self.owners._connection.commit()
        self.error("ACCESS_DENIED", lambda: self.backend.get(self.owner, request["request_id"]))
        self.owners._connection.execute("CREATE TRIGGER sqlitex_extra AFTER INSERT ON owners BEGIN SELECT 1; END")
        self.error("UNSUPPORTED_DATABASE", lambda: SQLiteOwnershipStore(self.path / "owners.sqlite", request_store=self.store))
        self.owners.close()
        # Failed constructors left no handle preventing deletion/rename on Windows.
        (self.path / "owners.sqlite").rename(self.path / "rejected-owners.sqlite")

    def test_reentrant_facade_call_does_not_clear_outer_access_checkpoint(self):
        request = self.create()
        original = self.store._write
        def write(*args):
            self.error("ACCESS_DENIED", lambda: self.backend.get(self.other, request["request_id"]))
            return original(*args)
        with patch.object(self.store, "_write", side_effect=write):
            updated = self.backend.supply_information(self.owner, request["request_id"], {}, expected_revision=1, idempotency_key=key())
        self.assertEqual(updated["request"]["revision"], 2)

    def test_checkpoint_history_failure_retry_does_not_repeat_collection(self):
        request, token = self.create(), key()
        with patch.object(service, "build_mock_context", wraps=service.build_mock_context) as collect:
            with patch.object(self.history, "save", side_effect=RequestError("STORAGE_FAILED")):
                self.error("HISTORY_FAILED", lambda: self.backend.inspect(self.owner, request["request_id"], expected_revision=1, idempotency_key=token, history=self.history))
            result = self.backend.inspect(self.owner, request["request_id"], expected_revision=1, idempotency_key=token, history=self.history)
        self.assertEqual(collect.call_count, 1)
        self.assertTrue(result["retained_evidence_available"])

    def test_explicit_optin_cleanup_and_production_contextual_entrypoint_remain_closed(self):
        for flag in (False, "true", 1):
            self.error("MOCK_OPT_IN_REQUIRED", lambda: MockRequestIdentity(mock=flag))
            self.error("MOCK_OPT_IN_REQUIRED", lambda: ProtectedMockRequests(self.store, self.owners, mock=flag))
        self.owners.close()
        self.owners.close()
        self.error("STORE_CLOSED", lambda: self.owners.get(key()))
        with self.assertRaises(collection_context.ContextCompatibilityError):
            collection_context.diagnose_contextual_request({"subject": "1" * 32, "approved": True})
