"""Versioned request revisions, events and mutation receipts, never evidence.

One connection per instance/thread. Only backend code calls mutation callbacks;
no callback runs collection, diagnosis, history writes or arbitrary caller code.
"""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3

from .request_errors import RequestError
from .request_policy import canonical, details, digest, fingerprint, hash_value, identifier, positive, SCENARIOS

APPLICATION_ID = 0x49505231
MAX_BYTES = 4096
_SCHEMA = {
    "requests": "CREATE TABLE requests (request_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)",
    "events": "CREATE TABLE events (request_id TEXT NOT NULL, revision INTEGER NOT NULL, kind TEXT NOT NULL, stored_at TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(request_id,revision))",
    "receipts": "CREATE TABLE receipts (key TEXT PRIMARY KEY, command_digest TEXT NOT NULL, pending INTEGER NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)",
}
STATES = frozenset({"needs_information", "ready_for_inspection", "inspecting", "awaiting_history",
                    "inspection_recorded", "inspection_failed"})
EVENTS = frozenset({"created", "information_supplied", "inspection_started", "history_pending",
                    "inspection_recorded", "inspection_failed", "recovered"})
FIELDS = frozenset({"request_id", "revision", "brief_revision", "details", "fingerprint", "state",
                    "attempt_id", "scenario", "history_id", "error_code"})


def checked(value):
    """Strict storage projection; unknown/forged fields fail closed before output."""
    try:
        if type(value) is not dict or set(value) != FIELDS:
            raise ValueError()
        identifier(value["request_id"])
        positive(value["revision"])
        positive(value["brief_revision"])
        if value["brief_revision"] > value["revision"] or details(value["details"]) != value["details"]:
            raise ValueError()
        fp = fingerprint(value["request_id"], value["details"])
        if value["fingerprint"] != fp or value["state"] not in STATES:
            raise ValueError()
        state = value["state"]
        if (state == "needs_information") != (fp is None):
            raise ValueError()
        active = state in ("inspecting", "awaiting_history", "inspection_recorded", "inspection_failed")
        if active:
            identifier(value["attempt_id"])
            if type(value["scenario"]) is not str or value["scenario"] not in SCENARIOS:
                raise ValueError()
        elif value["attempt_id"] is not None or value["scenario"] is not None:
            raise ValueError()
        if state == "inspection_recorded":
            if not hash_value(value["history_id"]):
                raise ValueError()
        elif value["history_id"] is not None:
            raise ValueError()
        if value["error_code"] not in (None, "COLLECTION_FAILED", "INTERRUPTED"):
            raise ValueError()
        if state == "inspection_failed" and value["error_code"] != "COLLECTION_FAILED":
            raise ValueError()
        return json.loads(canonical(value))
    except Exception:
        raise RequestError("RECORD_CORRUPTED") from None


class SQLiteRequestStore:
    """Internal local persistence, not an authenticated service or encrypted vault."""

    def __init__(self, path, *, create=True, timeout=5.0):
        self._connection = None
        try:
            if type(create) is not bool or type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 30:
                raise RequestError("INVALID_DATABASE")
            location = Path(path)
            if location.is_symlink() or not location.parent.is_dir() or (not create and not location.is_file()):
                raise RequestError("INVALID_DATABASE")
            self._connection = sqlite3.connect(location.resolve().as_uri() + ("?mode=rwc" if create else "?mode=rw"), uri=True, timeout=timeout)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA trusted_schema=OFF")
            with self._connection as db:
                db.execute("BEGIN IMMEDIATE")
                app = db.execute("PRAGMA application_id").fetchone()[0]
                version = db.execute("PRAGMA user_version").fetchone()[0]
                objects = db.execute("SELECT type, name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
                if app == 0 and version == 0 and not objects and create:
                    for sql in _SCHEMA.values():
                        db.execute(sql)
                    db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    db.execute("PRAGMA user_version=1")
                elif app != APPLICATION_ID or version != 1:
                    raise RequestError("UNSUPPORTED_DATABASE")
                # Reject unexpected schema objects (including triggers/views), even with copied identifiers.
                objects = {(r[0], r[1], r[2]) for r in db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'")}
                if objects != {("table", name, sql) for name, sql in _SCHEMA.items()}:
                    raise RequestError("UNSUPPORTED_DATABASE")
                if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise RequestError("RECORD_CORRUPTED")
        except BaseException as error:
            self.close()
            if isinstance(error, KeyboardInterrupt):
                raise
            self._raise(error)

    def __repr__(self):
        return "SQLiteRequestStore(storage='local', authority='none')"

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        self._db()
        return self

    def __exit__(self, *args):
        self.close()

    def _db(self):
        if self._connection is None:
            raise RequestError("STORE_CLOSED") from None
        return self._connection

    def storage_reference(self):
        """Local path association for companion storage, never identity/authentication.

        Moving a request database requires an explicit companion-storage decision.
        The raw filesystem path is neither returned nor logged.
        """
        try:
            name = self._db().execute("PRAGMA database_list").fetchone()[2]
            return digest({"request_storage_path_v1": os.path.normcase(str(Path(name).resolve()))})
        except Exception as error:
            self._raise(error)

    @staticmethod
    def _raise(error):
        code = error.code if isinstance(error, RequestError) else "STORAGE_FAILED"
        if isinstance(error, sqlite3.OperationalError) and getattr(error, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            code = "STORAGE_BUSY"
        raise RequestError(code) from None

    @staticmethod
    def _decode(row):
        try:
            if row is None or type(row["payload"]) is not str or len(row["payload"]) > MAX_BYTES:
                raise ValueError()
            value = checked(json.loads(row["payload"]))
            if canonical(value) != row["payload"] or digest(value) != row["digest"]:
                raise ValueError()
            return value
        except Exception:
            raise RequestError("RECORD_CORRUPTED") from None

    def _get(self, request_id):
        row = self._db().execute("SELECT request_id,revision,CASE WHEN length(payload)<=? THEN payload END AS payload,digest FROM requests WHERE request_id=?", (MAX_BYTES, request_id)).fetchone()
        if row is None:
            raise RequestError("NOT_FOUND")
        value = self._decode(row)
        if value["request_id"] != request_id or value["revision"] != row["revision"]:
            raise RequestError("RECORD_CORRUPTED")
        event = self._db().execute("SELECT CASE WHEN length(payload)<=? THEN payload END AS payload,digest FROM events WHERE request_id=? AND revision=?", (MAX_BYTES, request_id, value["revision"])).fetchone()
        if self._decode(event) != value:
            raise RequestError("RECORD_CORRUPTED")
        return value

    def get(self, request_id):
        identifier(request_id)
        try:
            # One read transaction prevents a racing writer splitting row/event observations.
            with self._db() as db:
                db.execute("BEGIN")
                return self._get(request_id)
        except Exception as error:
            self._raise(error)

    def events(self, request_id, *, limit=20, before_revision=None):
        identifier(request_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise RequestError("INVALID_LOOKUP")
        if before_revision is not None:
            positive(before_revision)
        try:
            with self._db() as db:
                db.execute("BEGIN")
                current = self._get(request_id)
                rows = db.execute("SELECT request_id,revision,kind,stored_at,CASE WHEN length(payload)<=? THEN payload END AS payload,digest FROM events WHERE request_id=? AND revision<? ORDER BY revision DESC LIMIT ?", (MAX_BYTES, request_id, before_revision or current["revision"] + 1, limit)).fetchall()
                output = []
                for row in rows:
                    value = self._decode(row)
                    try:
                        instant = datetime.fromisoformat(row["stored_at"])
                    except (ValueError, TypeError):
                        raise RequestError("RECORD_CORRUPTED") from None
                    if (value["request_id"] != request_id or value["revision"] != row["revision"]
                            or row["kind"] not in EVENTS or instant.tzinfo is None
                            or instant.astimezone(timezone.utc).isoformat() != row["stored_at"]):
                        raise RequestError("RECORD_CORRUPTED")
                    output.append({"kind": row["kind"], "stored_at": row["stored_at"], "request": value})
                return output
        except Exception as error:
            self._raise(error)

    def _receipt(self, key, command_digest):
        row = self._db().execute("SELECT command_digest,pending,CASE WHEN length(payload)<=? THEN payload END AS payload,digest FROM receipts WHERE key=?", (MAX_BYTES, key)).fetchone()
        if row is None:
            return None
        if not hash_value(row["command_digest"]) or type(row["pending"]) is not int or row["pending"] not in (0, 1):
            raise RequestError("RECORD_CORRUPTED")
        if row["command_digest"] != command_digest:
            raise RequestError("IDEMPOTENCY_CONFLICT")
        value = self._decode(row)
        if bool(row["pending"]) != (value["state"] in ("inspecting", "awaiting_history")):
            raise RequestError("RECORD_CORRUPTED")
        return value

    def _write(self, value, kind):
        value = checked(value)
        if kind not in EVENTS or len(canonical(value)) > MAX_BYTES:
            raise RequestError("RECORD_CORRUPTED")
        payload, checksum = canonical(value), digest(value)
        db = self._db()
        if value["revision"] == 1:
            db.execute("INSERT INTO requests VALUES(?,?,?,?)", (value["request_id"], 1, payload, checksum))
        else:
            updated = db.execute("UPDATE requests SET revision=?,payload=?,digest=? WHERE request_id=? AND revision=?",
                                 (value["revision"], payload, checksum, value["request_id"], value["revision"] - 1))
            if updated.rowcount != 1:
                raise RequestError("REVISION_CONFLICT")
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (value["request_id"], value["revision"], kind, datetime.now(timezone.utc).isoformat(), payload, checksum))
        return value

    def _mutate(self, *, key, command, request_id, expected_revision, transition, kind, pending=False, checkpoint=None):
        identifier(key)
        if request_id is not None:
            identifier(request_id)
            positive(expected_revision)
        command_digest = digest(command)
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                if checkpoint is not None:
                    checkpoint()
                replay = self._receipt(key, command_digest)
                if replay is not None:
                    if checkpoint is not None:
                        checkpoint()
                    return replay
                old = None if request_id is None else self._get(request_id)
                if old is not None and old["revision"] != expected_revision:
                    raise RequestError("REVISION_CONFLICT")
                value = transition(old)
                if old is not None and (value["request_id"] != request_id or value["revision"] != old["revision"] + 1):
                    raise RequestError("RECORD_CORRUPTED")
                value = self._write(value, kind)
                if kind == "recovered":
                    # Close the abandoned operation's receipt; replay never recollects.
                    updated = db.execute("UPDATE receipts SET pending=0,payload=?,digest=? WHERE pending=1 AND key=?", (canonical(value), digest(value), old["attempt_id"]))
                    if updated.rowcount != 1:
                        raise RequestError("RECORD_CORRUPTED")
                db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (key, command_digest, int(pending), canonical(value), digest(value)))
                if checkpoint is not None:
                    checkpoint()
                return value
        except Exception as error:
            self._raise(error)

    def _advance_attempt(self, request_id, *, revision, attempt_id, state, history_id=None, error=None, checkpoint=None):
        """Internal CAS handoff; collection/history are deliberately outside this transaction."""
        identifier(request_id)
        positive(revision)
        identifier(attempt_id)
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                if checkpoint is not None:
                    checkpoint()
                old = self._get(request_id)
                if old["revision"] != revision or old["attempt_id"] != attempt_id:
                    raise RequestError("REVISION_CONFLICT")
                allowed = {("inspecting", "awaiting_history"), ("inspecting", "inspection_failed"), ("awaiting_history", "inspection_recorded")}
                if (old["state"], state) not in allowed:
                    raise RequestError("REVISION_CONFLICT")
                value = self._write({**old, "revision": revision + 1, "state": state, "history_id": history_id, "error_code": error},
                                    "history_pending" if state == "awaiting_history" else state)
                cursor = db.execute("UPDATE receipts SET pending=?,payload=?,digest=? WHERE key=? AND pending=1", (int(state == "awaiting_history"), canonical(value), digest(value), attempt_id))
                if cursor.rowcount != 1:
                    raise RequestError("RECORD_CORRUPTED")
                if checkpoint is not None:
                    checkpoint()
                return value
        except Exception as error:
            self._raise(error)
