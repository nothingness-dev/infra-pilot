"""SQLite implementation of the existing Triage ApprovalStore, not a policy."""

from contextlib import contextmanager, suppress
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import UUID

from infrapilot_triage.approval_store import ApprovalReceipt, StoreUnavailable
from infrapilot_triage.approvals import ApprovalRequest, ApprovalState, AuditEvent, AuditKind, DecisionReason
from infrapilot_triage.identity import AuthenticatedActor
from infrapilot_triage.policy import ActionIntent, ActionPolicy, ActionType
from .request_policy import canonical, digest, hash_value

APPLICATION_ID = 0x49504141
SCHEMA_VERSION = 1
_LIMIT = 8192
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), scope_ref TEXT NOT NULL)",
    "approvals": "CREATE TABLE approvals (request_id TEXT PRIMARY KEY, association_ref TEXT NOT NULL, payload TEXT NOT NULL CHECK(length(payload)<=8192), digest TEXT NOT NULL)",
    "audits": "CREATE TABLE audits (sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, association_ref TEXT NOT NULL, request_id TEXT, occurred_at TEXT NOT NULL, payload TEXT NOT NULL CHECK(length(payload)<=8192), digest TEXT NOT NULL)",
    "receipts": "CREATE TABLE receipts (key_digest TEXT PRIMARY KEY, association_ref TEXT NOT NULL, payload TEXT NOT NULL CHECK(length(payload)<=8192), digest TEXT NOT NULL)",
}
_REASONS = {
    AuditKind.REQUESTED: DecisionReason.PENDING, AuditKind.GRANTED: DecisionReason.APPROVED,
    AuditKind.REJECTED: DecisionReason.REJECTED, AuditKind.EXPIRED: DecisionReason.EXPIRED,
    AuditKind.CONSUMED: DecisionReason.AUTHORIZED,
}


def _fail():
    raise StoreUnavailable("Approval storage unavailable.") from None


def _uuid(value):
    # Match the existing gate's lookup grammar, including unknown canonical IDs.
    if type(value) is not str or len(value) != 36 or str(UUID(value)) != value:
        raise ValueError()
    return value


def _hex(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError()
    return value


def _time(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError()
    return value.astimezone(timezone.utc).isoformat()


def _actor(value):
    if type(value) is not AuthenticatedActor:
        raise ValueError()
    return AuthenticatedActor(value.subject).subject


def _request_payload(request):
    if type(request) is not ApprovalRequest or type(request.state) is not ApprovalState:
        raise ValueError()
    action = request.action
    if (type(action.policy_version) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", action.policy_version) is None):
        raise ValueError()
    policy = ActionPolicy()
    policy.VERSION = action.policy_version
    checked = policy.classify(ActionIntent(service_id=action.service_id, action_type=action.action_type.value,
                                          parameters=action.parameters))
    if checked.action != action or not checked.requires_approval or not checked.allowed:
        raise ValueError()
    created, expires = _time(request.created_at), _time(request.expires_at)
    if not timedelta(0) < request.expires_at - request.created_at <= timedelta(minutes=15):
        raise ValueError()
    requester = _actor(request.requested_by)
    approved = _actor(request.approved_by) if request.approved_by is not None else None
    rejected = _actor(request.rejected_by) if request.rejected_by is not None else None
    consumed = _actor(request.consumed_by) if request.consumed_by is not None else None
    if approved == requester or rejected == requester:
        raise ValueError()
    state = request.state
    if ((state == ApprovalState.PENDING and any((approved, rejected, consumed)))
            or (state == ApprovalState.APPROVED and (approved is None or rejected or consumed))
            or (state == ApprovalState.REJECTED and (rejected is None or consumed))
            or (state == ApprovalState.EXPIRED and (rejected or consumed))
            or (state == ApprovalState.CONSUMED and (approved is None or rejected or consumed != requester))):
        raise ValueError()
    return {"request_id": _uuid(request.request_id), "action": asdict(action), "requested_by": requester,
            "created_at": created, "expires_at": expires, "state": state.value,
            "approved_by": approved, "rejected_by": rejected, "consumed_by": consumed}


def _decode_request(value):
    # These actor objects are historical subject references only. No session,
    # permissions or verified principal is restored; the gate authenticates anew.
    action = value["action"]
    policy = ActionPolicy()
    policy.VERSION = action["policy_version"]
    checked = policy.classify(ActionIntent(service_id=action["service_id"], action_type=action["action_type"],
                                          parameters=json.loads(action["parameters_json"])))
    subject = lambda name: None if value[name] is None else AuthenticatedActor(value[name])
    request = ApprovalRequest(value["request_id"], checked.action, subject("requested_by"),
                              datetime.fromisoformat(value["created_at"]), datetime.fromisoformat(value["expires_at"]),
                              ApprovalState(value["state"]), subject("approved_by"), subject("rejected_by"), subject("consumed_by"))
    if canonical(_request_payload(request)) != canonical(value):
        raise ValueError()
    return request


def _event_payload(event):
    if type(event) is not AuditEvent or type(event.kind) is not AuditKind or type(event.reason) is not DecisionReason:
        raise ValueError()
    if event.kind != AuditKind.DENIED and _REASONS[event.kind] != event.reason:
        raise ValueError()
    if event.kind == AuditKind.DENIED and event.reason in (DecisionReason.PENDING, DecisionReason.APPROVED, DecisionReason.AUTHORIZED):
        raise ValueError()
    value = asdict(event)
    value["event_id"] = _uuid(event.event_id)
    value["occurred_at"] = _time(event.occurred_at)
    if event.request_id is not None:
        _uuid(event.request_id)
    if event.actor_id is not None:
        AuthenticatedActor(event.actor_id)
    if event.service_id is not None:
        ActionIntent(service_id=event.service_id, action_type="inspect_service")
    if event.action_type is not None and type(event.action_type) is not ActionType:
        raise ValueError()
    if event.fingerprint is not None:
        _hex(event.fingerprint)
    if event.kind not in (AuditKind.DENIED, AuditKind.CONSUMED) and event.request_id is None:
        raise ValueError()
    return value


def _decode_event(value):
    event = AuditEvent(**{**value, "occurred_at": datetime.fromisoformat(value["occurred_at"]),
                          "kind": AuditKind(value["kind"]), "reason": DecisionReason(value["reason"]),
                          "action_type": ActionType(value["action_type"]) if value["action_type"] else None})
    if canonical(_event_payload(event)) != canonical(value):
        raise ValueError()
    return event


class _Transaction:
    def __init__(self, store):
        self.store, self.active = store, True
        self.changes, self.events, self.receipts = [], [], []

    def _db(self):
        if not self.active:
            _fail()
        return self.store._db()

    def _row(self, table, column, key):
        # Identifiers below are internal constants, never caller-controlled SQL.
        row = self._db().execute(f"SELECT association_ref, CASE WHEN length(payload)<=? THEN payload END AS payload,digest FROM {table} WHERE {column}=?",
                                 (_LIMIT, key)).fetchone()
        if row is None:
            return None
        if row[0] != self.store.association_ref:
            _fail()
        return self.store._value(row[1], row[2])

    def get(self, request_id):
        _uuid(request_id)
        value = self._row("approvals", "request_id", request_id)
        if value is None:
            return None
        request = _decode_request(value)
        if request.request_id != request_id:
            _fail()
        return request

    def put(self, request):
        value = _request_payload(request)
        old = self.get(request.request_id)
        if old == request:
            return
        if old is None:
            if request.state != ApprovalState.PENDING:
                _fail()
            self._db().execute("INSERT INTO approvals VALUES(?,?,?,?)", (request.request_id, self.store.association_ref, canonical(value), digest(value)))
        else:
            if (old.action != request.action or old.requested_by != request.requested_by
                    or old.created_at != request.created_at or old.expires_at != request.expires_at
                    or request.state not in {ApprovalState.PENDING: (ApprovalState.APPROVED, ApprovalState.REJECTED, ApprovalState.EXPIRED),
                                            ApprovalState.APPROVED: (ApprovalState.REJECTED, ApprovalState.EXPIRED, ApprovalState.CONSUMED)}.get(old.state, ())
                    or (old.approved_by is not None and old.approved_by != request.approved_by)):
                _fail()
            self._db().execute("UPDATE approvals SET payload=?,digest=? WHERE request_id=?", (canonical(value), digest(value), request.request_id))
        self.changes.append((old, request))

    def record(self, event):
        value = _event_payload(event)
        if event.request_id is not None:
            previous = self._db().execute("SELECT occurred_at FROM audits WHERE association_ref=? AND request_id=? ORDER BY sequence DESC LIMIT 1",
                                          (self.store.association_ref, event.request_id)).fetchone()
            if previous is not None and event.occurred_at < datetime.fromisoformat(previous[0]):
                _fail()
        self._db().execute("INSERT INTO audits(event_id,association_ref,request_id,occurred_at,payload,digest) VALUES(?,?,?,?,?,?)",
                           (event.event_id, self.store.association_ref, event.request_id, value["occurred_at"], canonical(value), digest(value)))
        self.events.append(event)

    def receipt(self, key_digest):
        _hex(key_digest)
        value = self._row("receipts", "key_digest", key_digest)
        if value is None:
            return None
        receipt = ApprovalReceipt(**value)
        self._check_receipt(receipt)
        if receipt.key_digest != key_digest:
            _fail()
        return receipt

    def _check_receipt(self, receipt):
        if type(receipt) is not ApprovalReceipt:
            _fail()
        _hex(receipt.key_digest)
        _hex(receipt.fingerprint)
        AuthenticatedActor(receipt.actor_id)
        request = self.get(receipt.request_id)
        if request is None or request.action.fingerprint != receipt.fingerprint:
            _fail()
        actors = {"request": request.requested_by, "approve": request.approved_by,
                  "reject": request.rejected_by, "authorize": request.consumed_by}
        if receipt.operation not in actors or actors[receipt.operation] is None or actors[receipt.operation].subject != receipt.actor_id:
            _fail()
        expected = (request.expires_at - request.created_at) // timedelta(microseconds=1) if receipt.operation == "request" else 0
        if type(receipt.ttl_microseconds) is not int or receipt.ttl_microseconds != expected:
            _fail()

    def remember(self, receipt):
        self._check_receipt(receipt)
        if self.receipt(receipt.key_digest) is not None:
            _fail()
        value = asdict(receipt)
        self._db().execute("INSERT INTO receipts VALUES(?,?,?,?)", (receipt.key_digest, self.store.association_ref, canonical(value), digest(value)))
        self.receipts.append(receipt)

    def validate(self):
        kinds = {ApprovalState.PENDING: AuditKind.REQUESTED, ApprovalState.APPROVED: AuditKind.GRANTED,
                 ApprovalState.REJECTED: AuditKind.REJECTED, ApprovalState.EXPIRED: AuditKind.EXPIRED, ApprovalState.CONSUMED: AuditKind.CONSUMED}
        for old, new in self.changes:
            kind = kinds[new.state]
            actor = {ApprovalState.PENDING: new.requested_by, ApprovalState.APPROVED: new.approved_by,
                     ApprovalState.REJECTED: new.rejected_by, ApprovalState.CONSUMED: new.consumed_by}.get(new.state)
            matches = [event for event in self.events if event.request_id == new.request_id and event.kind == kind
                       and event.service_id == new.action.service_id and event.action_type == new.action.action_type
                       and event.fingerprint == new.action.fingerprint and (actor is None or event.actor_id == actor.subject)]
            if len(matches) != 1 or matches[0].occurred_at < new.created_at:
                _fail()
            if (new.state == ApprovalState.EXPIRED) != (matches[0].occurred_at >= new.expires_at):
                _fail()
        for receipt in self.receipts:
            state = {"request": ApprovalState.PENDING, "approve": ApprovalState.APPROVED,
                     "reject": ApprovalState.REJECTED, "authorize": ApprovalState.CONSUMED}[receipt.operation]
            if not any(new.request_id == receipt.request_id and new.state == state for _, new in self.changes):
                _fail()


class SQLiteApprovalStore:
    """Backend-owned scoped store. Historical subject IDs convey no permission.

    BEGIN IMMEDIATE serializes the entire existing gate transaction, including
    trusted identity checks. Use fast bounded identity ports; no transaction retry.
    """

    def __init__(self, path, *, scope_ref, association_ref, create=True, timeout=5.0):
        self._connection = None
        self._lock, self._active = RLock(), False
        try:
            if (not hash_value(scope_ref) or not hash_value(association_ref) or type(create) is not bool
                    or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30):
                _fail()
            self._scope_ref, self._association_ref = scope_ref, association_ref
            location = Path(path)
            if location.is_symlink() or not location.parent.is_dir() or (not create and not location.is_file()):
                _fail()
            self._connection = sqlite3.connect(location.resolve().as_uri() + ("?mode=rwc" if create else "?mode=rw"),
                                               uri=True, timeout=timeout, isolation_level=None, check_same_thread=False)
            db = self._connection
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            app, version = db.execute("PRAGMA application_id").fetchone()[0], db.execute("PRAGMA user_version").fetchone()[0]
            objects = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
            if app == 0 and version == 0 and not objects and create:
                for sql in _SCHEMA.values():
                    db.execute(sql)
                db.execute("INSERT INTO metadata VALUES(1,?)", (scope_ref,))
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
            elif app != APPLICATION_ID or version != SCHEMA_VERSION:
                _fail()
            objects = set(db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"))
            if objects != {("table", name, sql) for name, sql in _SCHEMA.items()}:
                _fail()
            if db.execute("SELECT singleton,scope_ref FROM metadata LIMIT 2").fetchall() != [(1, scope_ref)]:
                _fail()
            if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                _fail()
            db.commit()
        except BaseException as error:
            if self._connection is not None:
                with suppress(Exception):
                    self._connection.rollback()
                with suppress(Exception):
                    self._connection.close()
                self._connection = None
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            _fail()

    def __repr__(self):
        return "SQLiteApprovalStore(storage='local', authentication='not_restored', execution='absent')"

    @property
    def scope_ref(self):
        return self._scope_ref

    @property
    def association_ref(self):
        return self._association_ref

    def _db(self):
        if self._connection is None:
            _fail()
        return self._connection

    @staticmethod
    def _value(payload, checksum):
        if type(payload) is not str or len(payload.encode("utf-8")) > _LIMIT:
            _fail()
        value = json.loads(payload)
        if type(value) is not dict or canonical(value) != payload or digest(value) != checksum:
            _fail()
        return value

    @contextmanager
    def transaction(self):
        with self._lock:
            if self._active:
                _fail()
            self._active = True
            transaction = _Transaction(self)
            try:
                self._db().execute("BEGIN IMMEDIATE")
                yield transaction
                transaction.validate()
                self._db().commit()
            except BaseException as error:
                if self._connection is not None:
                    try:
                        self._connection.rollback()
                    except Exception:
                        broken, self._connection = self._connection, None
                        with suppress(Exception):
                            broken.close()
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                _fail()
            finally:
                transaction.active = False
                self._active = False

    def get(self, request_id):
        with self.transaction() as transaction:
            return transaction.get(request_id)

    def read_events(self, *, after_sequence=0, limit=100, request_id=None):
        try:
            if type(after_sequence) is not int or not 0 <= after_sequence <= 2**63 - 1 or type(limit) is not int or not 1 <= limit <= 1000:
                _fail()
            if request_id is not None:
                _uuid(request_id)
            condition = " AND request_id=?" if request_id is not None else ""
            parameters = [_LIMIT, self.association_ref, after_sequence]
            if request_id is not None:
                parameters.append(request_id)
            parameters.append(limit)
            with self._lock:
                rows = self._db().execute("SELECT sequence,CASE WHEN length(payload)<=? THEN payload END,digest,event_id,request_id,occurred_at FROM audits WHERE association_ref=? AND sequence>?" + condition + " ORDER BY sequence LIMIT ?",
                                          parameters).fetchall()
                result = []
                for sequence, payload, checksum, event_id, request_id, occurred_at in rows:
                    event = _decode_event(self._value(payload, checksum))
                    if event.event_id != event_id or event.request_id != request_id or _time(event.occurred_at) != occurred_at:
                        _fail()
                    result.append((sequence, event))
                return tuple(result)
        except Exception:
            _fail()

    def events_for(self, request_id):
        """Only request-associated events; unassociated denials are excluded."""
        page = self.read_events(request_id=request_id, limit=1000)
        if page and self.read_events(request_id=request_id, after_sequence=page[-1][0], limit=1):
            _fail()
        return tuple(event for _, event in page)

    @property
    def events(self):
        page = self.read_events(limit=1000)
        if page and self.read_events(after_sequence=page[-1][0], limit=1):
            _fail()  # Never silently truncate the compatibility snapshot.
        return tuple(event for _, event in page)

    def close(self):
        with self._lock:
            if self._active:
                _fail()
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    _fail()
                finally:
                    self._connection = None

    def __enter__(self):
        self._db()
        return self

    def __exit__(self, *args):
        self.close()
