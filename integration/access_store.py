"""Local ownership metadata, separate from identity and both existing schemas."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3

from .request_errors import RequestError
from .request_policy import canonical, digest, hash_value, identifier, positive
from .request_store import SQLiteRequestStore

APPLICATION_ID = 0x49504131
VERSION = "infrapilot-request-ownership/1"
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), request_storage TEXT NOT NULL)",
    "owners": "CREATE TABLE owners (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)",
}
_MAX_BYTES = 1024


@dataclass(frozen=True, repr=False)
class Ownership:
    request_id: str
    owner_ref: str
    binding_ref: str
    revision: int

    def __repr__(self):
        return "Ownership(contents='local_metadata', identity='not_established')"


class SQLiteOwnershipStore:
    """Trusted local metadata; no users, session handles, roles or secrets persist."""

    def __init__(self, path, *, request_store, create=True, timeout=5.0):
        self._connection = None
        try:
            if (type(request_store) is not SQLiteRequestStore or type(create) is not bool
                    or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30):
                raise RequestError("INVALID_DATABASE")
            self.request_storage = request_store.storage_reference()
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
                objects = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
                if app == 0 and version == 0 and not objects and create:
                    for sql in _SCHEMA.values():
                        db.execute(sql)
                    db.execute("INSERT INTO metadata VALUES(1,?)", (self.request_storage,))
                    db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    db.execute("PRAGMA user_version=1")
                elif app != APPLICATION_ID or version != 1:
                    raise RequestError("UNSUPPORTED_DATABASE")
                objects = {(r[0], r[1], r[2]) for r in db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'")}
                if objects != {("table", name, sql) for name, sql in _SCHEMA.items()}:
                    raise RequestError("UNSUPPORTED_DATABASE")
                rows = db.execute("SELECT singleton,request_storage FROM metadata LIMIT 2").fetchall()
                if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] != self.request_storage:
                    raise RequestError("INVALID_DATABASE")
                if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise RequestError("RECORD_CORRUPTED")
        except BaseException as error:
            self.close()
            if isinstance(error, KeyboardInterrupt):
                raise
            SQLiteRequestStore._raise(error)

    def __repr__(self):
        return "SQLiteOwnershipStore(storage='local', authentication='none')"

    def _db(self):
        if self._connection is None:
            raise RequestError("STORE_CLOSED")
        return self._connection

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        self._db()
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _decode(row):
        try:
            if type(row["payload"]) is not str or len(row["payload"]) > _MAX_BYTES:
                raise ValueError()
            value = json.loads(row["payload"])
            if (type(value) is not dict or set(value) != {"version", "request_id", "owner_ref", "binding_ref", "revision"}
                    or value["version"] != VERSION or canonical(value) != row["payload"] or digest(value) != row["digest"]
                    or row["request_id"] != value["request_id"] or not hash_value(value["binding_ref"])):
                raise ValueError()
            identifier(value["request_id"])
            identifier(value["owner_ref"])
            positive(value["revision"])
            return Ownership(value["request_id"], value["owner_ref"], value["binding_ref"], value["revision"])
        except Exception:
            raise RequestError("RECORD_CORRUPTED") from None

    def get(self, request_id):
        identifier(request_id)
        try:
            row = self._db().execute("SELECT request_id,CASE WHEN length(payload)<=? THEN payload END AS payload,digest FROM owners WHERE request_id=?", (_MAX_BYTES, request_id)).fetchone()
            return None if row is None else self._decode(row)
        except Exception as error:
            SQLiteRequestStore._raise(error)

    @staticmethod
    def _payload(owner):
        return {"version": VERSION, "request_id": owner.request_id, "owner_ref": owner.owner_ref,
                "binding_ref": owner.binding_ref, "revision": owner.revision}

    def register(self, request_id, *, owner_ref, binding_ref, checkpoint=None):
        """Trusted composition only. Retry same association; never overwrite an owner."""
        identifier(request_id)
        identifier(owner_ref)
        if not hash_value(binding_ref):
            raise RequestError("INVALID_ARGUMENTS")
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                if checkpoint is not None:
                    checkpoint()
                old = self.get(request_id)
                if old is not None:
                    if old.owner_ref != owner_ref or old.binding_ref != binding_ref:
                        raise RequestError("ACCESS_DENIED")
                    result = old
                else:
                    result = Ownership(request_id, owner_ref, binding_ref, 1)
                    data = self._payload(result)
                    db.execute("INSERT INTO owners VALUES(?,?,?)", (request_id, canonical(data), digest(data)))
                if checkpoint is not None:
                    checkpoint()
                return result
        except Exception as error:
            SQLiteRequestStore._raise(error)

    def transfer(self, request_id, *, owner_ref, expected_revision):
        """Explicit trusted fixture/admin storage control; not a public access operation."""
        identifier(owner_ref)
        positive(expected_revision)
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                old = self.get(request_id)
                if old is None or old.revision != expected_revision:
                    raise RequestError("REVISION_CONFLICT")
                result = Ownership(request_id, owner_ref, old.binding_ref, positive(old.revision + 1))
                data = self._payload(result)
                db.execute("UPDATE owners SET payload=?,digest=? WHERE request_id=?", (canonical(data), digest(data), request_id))
                return result
        except Exception as error:
            SQLiteRequestStore._raise(error)
