"""Actual gate plus temporary SQLite; all identities/actions are synthetic."""

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

from infrapilot_triage import ActionIntent, ActionPolicy, ActionProposal, ApprovalGate, AuthenticatedActor, InMemoryApprovalStore, Permission
from infrapilot_triage.approval_store import StoreUnavailable
from infrapilot_triage.approvals import ApprovalState, AuditKind, DecisionReason
from integration.approval_store import SQLiteApprovalStore
from integration.mock_approval import MockClock
from integration.request_policy import canonical, digest

CANARY = "PRIVATE-AUTHENTICATION-AND-PROPOSAL-CANARY-927"
SCOPE = digest({"account": "synthetic-account", "service": "synthetic-service"})
ASSOCIATION = digest({"request": "synthetic-request", "review": "synthetic-current-review"})
INTENT = ActionIntent(service_id="synthetic-service", action_type="restart_service")


class FixtureIdentity:
    """Opaque volatile fixture sessions; subject strings confer no authority."""

    def __init__(self):
        self.handles = {name: object() for name in ("requester", "approver", "other", "approver2")}
        self.active = set(self.handles)
        self.denied = set()

    def authenticate(self, context):
        for name, handle in self.handles.items():
            if context is handle and name in self.active:
                return AuthenticatedActor(name)
        return None

    def is_authorized(self, actor, action, permission):
        return (actor.subject in self.active and action.service_id in ("synthetic-service", "other-service")
                and (actor.subject, permission) not in self.denied
                and ((actor.subject in ("requester", "other") and permission in (Permission.REQUEST, Permission.EXECUTE))
                     or (actor.subject in ("approver", "approver2") and permission == Permission.APPROVE)))


class ApprovalStorageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("socket.socket", "socket.create_connection", "subprocess.Popen", "urllib.request.build_opener"):
            self.stack.enter_context(patch(name, side_effect=AssertionError("External I/O forbidden")))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "approvals.sqlite"
        self.identity, self.clock, self.policy = FixtureIdentity(), MockClock(), ActionPolicy()
        self.store = self.open()
        self.gate = self.make_gate(self.store)

    def open(self, **options):
        store = SQLiteApprovalStore(self.path, scope_ref=options.pop("scope_ref", SCOPE),
                                    association_ref=options.pop("association_ref", ASSOCIATION), **options)
        self.addCleanup(store.close)
        return store

    def make_gate(self, store, identity=None):
        return ApprovalGate(store=store, identity=self.identity if identity is None else identity,
                            policy=self.policy, clock=self.clock)

    def pending(self, *, gate=None, intent=INTENT, **options):
        decision = (gate or self.gate).request_approval(intent, authentication=self.identity.handles["requester"], **options)
        self.assertEqual(decision.reason, DecisionReason.PENDING)
        return decision.request

    def approved(self, **options):
        request = self.pending(**options)
        decision = self.gate.approve(request.request_id, authentication=self.identity.handles["approver"])
        self.assertEqual(decision.reason, DecisionReason.APPROVED)
        return decision.request

    def consume(self, request, *, gate=None, **options):
        return (gate or self.gate).authorize(INTENT, authentication=self.identity.handles["requester"],
                                             approval_request_id=request.request_id, **options)

    def test_restart_preserves_records_but_rejects_old_sessions_and_actor_claims(self):
        request = self.approved()
        self.store.close()
        restored = self.open(create=False)
        self.assertEqual(restored.get(request.request_id), request)
        self.assertEqual([e.kind for e in restored.events], [AuditKind.REQUESTED, AuditKind.GRANTED])
        fresh = FixtureIdentity()
        gate = self.make_gate(restored, identity=fresh)
        for context in (self.identity.handles["requester"], AuthenticatedActor("requester"), {"subject": "requester", "role": "admin"}, None):
            decision = gate.authorize(INTENT, authentication=context, approval_request_id=request.request_id)
            self.assertFalse(decision.allowed)
        decision = gate.authorize(INTENT, authentication=fresh.handles["requester"], approval_request_id=request.request_id)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, DecisionReason.AUTHORIZED)
        self.assertFalse(self.consume(request, gate=gate).allowed)

    def test_missing_identity_policy_or_store_remains_fail_closed(self):
        request = self.approved()
        for gate in (ApprovalGate(store=self.store, policy=self.policy, clock=self.clock),
                     ApprovalGate(store=self.store, identity=self.identity, clock=self.clock), ApprovalGate()):
            decision = self.consume(request, gate=gate)
            self.assertFalse(decision.allowed)
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.APPROVED)

    def test_unknown_canonical_request_identifier_keeps_existing_gate_semantics(self):
        result = self.gate.approve("00000000-0000-1000-8000-000000000001", authentication=self.identity.handles["approver"])
        self.assertEqual(result.reason, DecisionReason.REQUEST_NOT_FOUND)
        self.assertTrue(result.audit_recorded)

    def test_creation_retry_is_bound_to_actor_action_ttl_and_association(self):
        key = str(uuid4())
        request = self.pending(idempotency_key=key)
        self.assertEqual(self.pending(idempotency_key=key), request)
        self.assertEqual(len(self.store.events), 1)
        for intent, actor, ttl in ((replace_intent(parameters={"grace_period_seconds": 0}), "requester", timedelta(minutes=5)),
                                   (INTENT, "other", timedelta(minutes=5)), (INTENT, "requester", timedelta(seconds=1)),
                                   (replace_intent(service_id="other-service"), "requester", timedelta(minutes=5))):
            decision = self.gate.request_approval(intent, authentication=self.identity.handles[actor], ttl=ttl, idempotency_key=key)
            self.assertEqual(decision.reason, DecisionReason.INVALID_STATE)
        foreign = self.open(association_ref=digest({"different": "request"}))
        decision = self.make_gate(foreign).request_approval(INTENT, authentication=self.identity.handles["requester"], idempotency_key=key)
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.request)

    def test_decision_retries_do_not_append_audits_or_restore_terminal_state(self):
        request = self.pending()
        approve_key, reject_key = str(uuid4()), str(uuid4())
        for _ in range(2):
            self.assertEqual(self.gate.approve(request.request_id, authentication=self.identity.handles["approver"],
                                              idempotency_key=approve_key).reason, DecisionReason.APPROVED)
        self.assertEqual(len(self.store.events), 2)
        for _ in range(2):
            self.assertEqual(self.gate.reject(request.request_id, authentication=self.identity.handles["approver"],
                                             idempotency_key=reject_key).reason, DecisionReason.REJECTED)
        self.assertEqual(len(self.store.events), 3)
        replay = self.gate.approve(request.request_id, authentication=self.identity.handles["approver"], idempotency_key=approve_key)
        self.assertEqual(replay.reason, DecisionReason.REJECTED)
        self.assertFalse(replay.allowed)
        self.assertEqual(len(self.store.events), 3)

    def test_consumption_receipt_survives_restart_but_never_reissues_authorization(self):
        request, key = self.approved(), str(uuid4())
        original = self.consume(request, idempotency_key=key)
        self.assertTrue(original.allowed)
        self.store.close()
        reopened = self.open(create=False)
        replay = self.consume(request, gate=self.make_gate(reopened), idempotency_key=key)
        self.assertEqual(replay.reason, DecisionReason.CONSUMED)
        self.assertFalse(replay.allowed)
        self.assertIsNone(replay.authorization_id)
        self.assertEqual(len(reopened.events), 3)
        self.assertNotIn(original.authorization_id.encode(), self.path.read_bytes())

    def test_key_cannot_change_operation_request_or_actor(self):
        key = str(uuid4())
        first = self.pending(idempotency_key=key)
        second = self.pending()
        for request_id, actor in ((first.request_id, "approver"), (second.request_id, "approver2")):
            result = self.gate.approve(request_id, authentication=self.identity.handles[actor], idempotency_key=key)
            self.assertEqual(result.reason, DecisionReason.INVALID_STATE)
        self.assertEqual(self.store.get(first.request_id).state, ApprovalState.PENDING)

    def test_same_operation_key_cannot_switch_request_or_approver(self):
        first, second, key = self.pending(), self.pending(), str(uuid4())
        self.gate.approve(first.request_id, authentication=self.identity.handles["approver"], idempotency_key=key)
        for request, actor in ((second, "approver"), (first, "approver2")):
            result = self.gate.approve(request.request_id, authentication=self.identity.handles[actor], idempotency_key=key)
            self.assertEqual(result.reason, DecisionReason.INVALID_STATE)
        self.assertEqual(self.store.get(second.request_id).state, ApprovalState.PENDING)

    def test_consumption_key_cannot_switch_to_another_approved_request(self):
        first, second, key = self.approved(), self.approved(), str(uuid4())
        self.assertTrue(self.consume(first, idempotency_key=key).allowed)
        self.assertEqual(self.consume(second, idempotency_key=key).reason, DecisionReason.INVALID_STATE)
        self.assertEqual(self.store.get(second.request_id).state, ApprovalState.APPROVED)

    def test_retry_rechecks_current_permissions_and_cannot_extend_expiration(self):
        key = str(uuid4())
        request = self.pending(idempotency_key=key, ttl=timedelta(seconds=1))
        self.identity.denied.add(("requester", Permission.REQUEST))
        denied = self.gate.request_approval(INTENT, authentication=self.identity.handles["requester"],
                                           ttl=timedelta(seconds=1), idempotency_key=key)
        self.assertEqual(denied.reason, DecisionReason.NOT_AUTHORIZED)
        self.identity.denied.clear()
        self.clock.now = request.expires_at
        result = self.gate.request_approval(INTENT, authentication=self.identity.handles["requester"],
                                           ttl=timedelta(seconds=1), idempotency_key=key)
        self.assertEqual(result.reason, DecisionReason.EXPIRED)
        self.assertEqual(result.request.expires_at, request.expires_at)

    def test_wrong_requester_action_and_revoked_approver_never_consume(self):
        request = self.approved()
        for intent, actor, expected in ((replace_intent(service_id="other-service"), "requester", DecisionReason.ACTION_MISMATCH),
                                       (replace_intent(parameters={"grace_period_seconds": 1}), "requester", DecisionReason.ACTION_MISMATCH),
                                       (INTENT, "other", DecisionReason.REQUESTER_MISMATCH)):
            result = self.gate.authorize(intent, authentication=self.identity.handles[actor], approval_request_id=request.request_id)
            self.assertEqual(result.reason, expected)
        self.identity.active.remove("approver")
        self.assertEqual(self.consume(request).reason, DecisionReason.NOT_AUTHORIZED)
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.APPROVED)

    def test_policy_change_rejects_old_action_fingerprint(self):
        request = self.approved()
        self.policy.VERSION = "triage-approval-v2"
        self.assertEqual(self.consume(request).reason, DecisionReason.ACTION_MISMATCH)

    def test_exact_expiration_rejection_and_consumption_are_terminal(self):
        request = self.approved()
        self.clock.now = request.expires_at
        self.assertEqual(self.consume(request).reason, DecisionReason.EXPIRED)
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.EXPIRED)
        self.clock.now -= timedelta(seconds=1)
        self.assertFalse(self.consume(request).allowed)
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.EXPIRED)

    def race(self, operation):
        other = self.open()
        barrier = Barrier(2)
        gates = (self.gate, self.make_gate(other))
        def run(gate):
            barrier.wait(timeout=5)
            return operation(gate)
        with ThreadPoolExecutor(max_workers=2) as workers:
            return list(workers.map(run, gates))

    def test_two_connections_consume_only_once(self):
        request = self.approved()
        results = self.race(lambda gate: self.consume(request, gate=gate))
        self.assertEqual(sum(result.allowed for result in results), 1)
        self.assertEqual(sum(e.kind == AuditKind.CONSUMED for e in self.store.events), 1)

    def test_two_connections_create_one_idempotent_request(self):
        key = str(uuid4())
        results = self.race(lambda gate: gate.request_approval(INTENT, authentication=self.identity.handles["requester"], idempotency_key=key))
        self.assertEqual(results[0].request.request_id, results[1].request.request_id)
        self.assertEqual(len(self.store.events), 1)

    def test_competing_approvers_cannot_both_grant(self):
        request = self.pending()
        other = self.open()
        barrier = Barrier(2)
        def grant(pair):
            gate, actor = pair
            barrier.wait(timeout=5)
            return gate.approve(request.request_id, authentication=self.identity.handles[actor])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(grant, ((self.gate, "approver"), (self.make_gate(other), "approver2"))))
        self.assertEqual(sum(r.reason == DecisionReason.APPROVED for r in results), 1)
        self.assertEqual(sum(e.kind == AuditKind.GRANTED for e in self.store.events), 1)

    def test_revocation_and_consumption_race_has_one_terminal_winner(self):
        request = self.approved()
        other, barrier = self.open(), Barrier(2)
        def run(revoke):
            barrier.wait(timeout=5)
            return (self.make_gate(other).reject(request.request_id, authentication=self.identity.handles["approver"])
                    if revoke else self.consume(request))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, (True, False)))
        self.assertEqual(sum(result.request is not None for result in results), 1)
        self.assertIn(self.store.get(request.request_id).state, (ApprovalState.CONSUMED, ApprovalState.REJECTED))

    def test_audit_insert_failure_rolls_back_consumption_and_receipt(self):
        request, key = self.approved(), str(uuid4())
        self.store._connection.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audits BEGIN SELECT RAISE(ABORT, 'PRIVATE-AUTHENTICATION-AND-PROPOSAL-CANARY-927'); END")
        result = self.consume(request, idempotency_key=key)
        self.assertEqual(result.reason, DecisionReason.STORAGE_UNAVAILABLE)
        self.assertFalse(result.audit_recorded)
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.APPROVED)
        self.assertEqual(len(self.store.events), 2)
        self.store._connection.execute("DROP TRIGGER fail_audit")
        self.assertTrue(self.consume(request, idempotency_key=key).allowed)

    def test_unaudited_direct_transaction_cannot_commit(self):
        request = self.pending()
        with self.assertRaises(StoreUnavailable):
            with self.store.transaction() as transaction:
                transaction.put(replace(request, state=ApprovalState.APPROVED, approved_by=AuthenticatedActor("approver")))
        self.assertEqual(self.store.get(request.request_id), request)
        self.assertEqual(len(self.store.events), 1)

    def test_record_write_failure_leaves_no_request_or_audit(self):
        self.store._connection.execute("CREATE TRIGGER fail_state BEFORE INSERT ON approvals BEGIN SELECT RAISE(ABORT, 'PRIVATE-AUTHENTICATION-AND-PROPOSAL-CANARY-927'); END")
        result = self.gate.request_approval(INTENT, authentication=self.identity.handles["requester"], idempotency_key=str(uuid4()))
        self.assertEqual(result.reason, DecisionReason.STORAGE_UNAVAILABLE)
        self.assertFalse(result.audit_recorded)
        self.assertEqual(self.store.events, ())
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM approvals").fetchone()[0], 0)

    def test_failed_commit_before_durability_rolls_back_state_audit_and_key(self):
        request, key = self.approved(), str(uuid4())
        connection = self.store._connection
        class Unavailable:
            def __getattr__(self, name):
                return getattr(connection, name)
            def commit(self):
                raise RuntimeError(CANARY)
        self.store._connection = Unavailable()
        try:
            self.assertFalse(self.consume(request, idempotency_key=key).allowed)
        finally:
            self.store._connection = connection
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.APPROVED)
        self.assertEqual(len(self.store.events), 2)
        self.assertTrue(self.consume(request, idempotency_key=key).allowed)

    def test_failed_rollback_discards_the_connection_instead_of_reusing_uncertain_state(self):
        request = self.approved()
        connection = self.store._connection
        class Broken:
            def __getattr__(self, name):
                return getattr(connection, name)
            def commit(self):
                raise RuntimeError(CANARY)
            def rollback(self):
                raise RuntimeError(CANARY)
        self.store._connection = Broken()
        self.assertFalse(self.consume(request).allowed)
        self.assertIsNone(self.store._connection)
        with self.open(create=False) as reopened:
            self.assertEqual(reopened.get(request.request_id).state, ApprovalState.APPROVED)
            self.assertEqual(len(reopened.events), 2)

    def test_ambiguous_commit_fails_closed_and_retry_never_reissues_grant(self):
        request, key = self.approved(), str(uuid4())
        connection = self.store._connection
        class Ambiguous:
            def __getattr__(self, name):
                return getattr(connection, name)
            def commit(self):
                connection.commit()
                raise RuntimeError(CANARY)
        self.store._connection = Ambiguous()
        try:
            result = self.consume(request, idempotency_key=key)
        finally:
            self.store._connection = connection
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, DecisionReason.STORAGE_UNAVAILABLE)
        replay = self.consume(request, idempotency_key=key)
        self.assertEqual(replay.reason, DecisionReason.CONSUMED)
        self.assertFalse(replay.allowed)
        self.assertIsNone(replay.authorization_id)
        self.assertEqual(len(self.store.events), 3)

    def test_closed_and_nested_transactions_and_retained_handles_fail_safely(self):
        with self.store.transaction() as transaction:
            with self.assertRaises(StoreUnavailable):
                with self.store.transaction():
                    pass
        with self.assertRaises(StoreUnavailable):
            transaction.get(str(uuid4()))
        self.store.close()
        self.assertEqual(self.gate.request_approval(INTENT, authentication=self.identity.handles["requester"]).reason, DecisionReason.STORAGE_UNAVAILABLE)

    def test_clock_regression_after_approval_is_not_committed(self):
        request = self.pending()
        self.clock.now += timedelta(seconds=1)
        self.gate.approve(request.request_id, authentication=self.identity.handles["approver"])
        self.clock.now -= timedelta(microseconds=1)
        self.assertFalse(self.consume(request).allowed)
        self.assertEqual(self.store.get(request.request_id).state, ApprovalState.APPROVED)

    def test_invalid_clock_is_not_persisted(self):
        for value in (None, datetime(2026, 1, 1), CANARY):
            self.clock.now = value
            result = self.gate.request_approval(INTENT, authentication=self.identity.handles["requester"])
            self.assertEqual(result.reason, DecisionReason.CLOCK_UNAVAILABLE)
        self.assertEqual(self.store.events, ())

    def test_scope_and_association_are_independently_selected(self):
        request = self.pending()
        with self.assertRaises(StoreUnavailable):
            self.open(scope_ref=digest({"other": "account"}))
        other = self.open(association_ref=digest({"other": "review"}))
        with self.assertRaises(StoreUnavailable):
            other.get(request.request_id)
        self.assertEqual(other.events, ())
        with self.assertRaises(AttributeError):
            self.store.association_ref = ASSOCIATION

    def test_unknown_schema_or_foreign_database_is_not_adopted(self):
        self.store.close()
        for change in ("PRAGMA user_version=2", "PRAGMA application_id=123", "CREATE TABLE unrelated (secret TEXT)"):
            path = Path(self.directory.name) / (str(uuid4()) + ".sqlite")
            with closing(sqlite3.connect(path)) as db:
                db.execute(change)
                db.commit()
            before = path.read_bytes()
            with self.assertRaises(StoreUnavailable) as caught:
                SQLiteApprovalStore(path, scope_ref=SCOPE, association_ref=ASSOCIATION)
            self.assertEqual(before, path.read_bytes())
            self.assertNotIn(CANARY, repr(caught.exception))

    def test_invalid_configuration_and_paths_are_sanitized(self):
        for values in ({"scope_ref": CANARY}, {"association_ref": None}, {"timeout": float("nan")}, {"timeout": True}, {"create": 1}):
            options = {"scope_ref": SCOPE, "association_ref": ASSOCIATION, **values}
            with self.assertRaises(StoreUnavailable) as caught:
                SQLiteApprovalStore(self.path, **options)
            self.assertNotIn(CANARY, str(caught.exception))
        with self.assertRaises(StoreUnavailable):
            SQLiteApprovalStore(Path(self.directory.name) / CANARY / "db", scope_ref=SCOPE, association_ref=ASSOCIATION)

    def test_corrupted_payload_is_rejected_even_with_recomputed_checksum(self):
        request = self.pending()
        db = self.store._connection
        raw = json.loads(db.execute("SELECT payload FROM approvals").fetchone()[0])
        raw["action"]["fingerprint"] = "0" * 64
        db.execute("UPDATE approvals SET payload=?,digest=?", (canonical(raw), digest(raw)))
        self.assertEqual(self.gate.approve(request.request_id, authentication=self.identity.handles["approver"]).reason, DecisionReason.STORAGE_UNAVAILABLE)

    def test_oversized_persisted_data_is_bounded_before_decoding(self):
        request = self.pending()
        db = self.store._connection
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute("UPDATE approvals SET payload=?", ("x" * 9000,))
        self.assertEqual(self.gate.approve(request.request_id, authentication=self.identity.handles["approver"]).reason, DecisionReason.STORAGE_UNAVAILABLE)

    def test_audit_pagination_and_payload_validation(self):
        request = self.approved()
        self.consume(request)
        first = self.store.read_events(limit=1)
        rest = self.store.read_events(after_sequence=first[0][0], limit=2)
        self.assertEqual(len(first) + len(rest), 3)
        for options in ({"limit": 0}, {"limit": 1001}, {"after_sequence": True}):
            with self.assertRaises(StoreUnavailable):
                self.store.read_events(**options)
        db = self.store._connection
        raw = json.loads(db.execute("SELECT payload FROM audits LIMIT 1").fetchone()[0])
        raw["unrestricted"] = CANARY
        db.execute("UPDATE audits SET payload=?,digest=? WHERE sequence=1", (canonical(raw), digest(raw)))
        with self.assertRaises(StoreUnavailable):
            self.store.read_events()

    def test_secrets_do_not_enter_results_audits_database_or_diagnostics(self):
        stdout, stderr, logs = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                denied = self.gate.request_approval(INTENT, authentication=CANARY)
                invalid_key = self.gate.request_approval(INTENT, authentication=self.identity.handles["requester"], idempotency_key=CANARY)
                proposal = replace_intent(proposal=ActionProposal(action_id="restart_service", title=CANARY,
                    description=CANARY, risk_level="high", requires_approval=True))
                request = self.pending(intent=proposal, idempotency_key=str(uuid4()))
                with patch.object(self.identity, "authenticate", side_effect=RuntimeError(CANARY)):
                    self.assertFalse(self.gate.request_approval(INTENT, authentication=CANARY).allowed)
        finally:
            logging.getLogger().removeHandler(handler)
        for text in (stdout.getvalue(), stderr.getvalue(), logs.getvalue(), repr(self.store), repr(denied), repr(invalid_key),
                     repr(request), repr(self.store.events), self.path.read_bytes().decode("latin1")):
            self.assertNotIn(CANARY, text)

    def test_opt_in_idempotency_also_works_with_existing_memory_store(self):
        store = InMemoryApprovalStore()
        gate = self.make_gate(store)
        request = self.pending(gate=gate, idempotency_key=(key := str(uuid4())))
        self.assertEqual(self.pending(gate=gate, idempotency_key=key), request)
        self.assertEqual(len(store.events), 1)

    def test_read_only_gate_behavior_is_preserved_without_an_approval_receipt(self):
        intent = replace_intent(action_type="inspect_metrics")
        result = self.gate.authorize(intent, authentication=self.identity.handles["requester"])
        self.assertTrue(result.allowed)
        self.assertIsNone(result.request)
        self.assertEqual(self.store.events[0].kind, AuditKind.CONSUMED)
        invalid = self.gate.authorize(intent, authentication=self.identity.handles["requester"], idempotency_key=str(uuid4()))
        self.assertFalse(invalid.allowed)


def replace_intent(**changes):
    return ActionIntent.model_validate({**INTENT.model_dump(), **changes})
