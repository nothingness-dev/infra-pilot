"""Bounded, local SQLite history of validated inspection summaries.

History never reconstructs PreparedCollection, current workflow state or an
approval. Only allowlisted summaries and opaque association digests persist.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from infrapilot_triage.collection_context import (
    CapabilityContext, Digest, LimitationCode, LogExportContext, context_digest,
    validate_provider_context,
)
from provider import ServiceBinding
from setup.integration import request_fingerprint
from .history_errors import HistoryError, VERSION


_APPLICATION_ID = 0x49504831
_MAX_BYTES = 64 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return "sha256:" + hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _binding_digest(binding):
    if type(binding) is not ServiceBinding:
        raise HistoryError("INVALID_LOOKUP") from None
    # Revalidate even a previously valid frozen object before selecting records.
    try:
        checked = ServiceBinding(**asdict(binding))
        return _digest(asdict(checked))
    except Exception:
        raise HistoryError("INVALID_LOOKUP") from None


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Count = Annotated[StrictInt, Field(ge=0)]


class DiagnosisCounts(_Model):
    evidence: Count
    hypotheses: Count
    actions: Count
    missing_information: Count
    limitations: Count


class HistoryPayload(_Model):
    """Internal history schema, not a new shared snapshot or trust contract."""

    contract_version: Literal["infrapilot-inspection-history/1"] = VERSION
    data_source: Literal["mock", "real"]
    binding_digest: Digest
    request_id_digest: Digest
    request_fingerprint: Digest
    snapshot_digest: Digest
    context_digest: Digest
    report_digest: Digest | None
    stage: Literal["context", "diagnosis", "association", "complete"]
    pipeline_error: Literal["CONTEXT_REJECTED", "DIAGNOSIS_FAILED", "ASSOCIATION_FAILED", "INTERRUPTED"] | None
    capabilities: Annotated[tuple[CapabilityContext, ...], Field(min_length=4, max_length=4)]
    logs: LogExportContext
    limitations: tuple[LimitationCode, ...]
    diagnosis_counts: DiagnosisCounts | None
    application_health: Literal["unknown"] = "unknown"
    cpu_usage_percent: None = None
    ram_usage_mib: None = None
    application_http_status: None = None
    application_response_time_ms: None = None
    source_timestamp: None = None
    history_only: Literal[True] = True
    provenance_verified: Literal[False] = False
    freshness_evaluated: Literal[False] = False
    authorization_consumed: Literal[False] = False
    execution_authorized: Literal[False] = False
    execution_performed: Literal[False] = False
    remediation_verified: Literal[False] = False

    @model_validator(mode="after")
    def consistent_summary(self):
        if tuple(item.capability for item in self.capabilities) != ("service", "deployment", "logs", "metrics"):
            raise ValueError("Ordered capabilities required")
        if (self.report_digest is None) != (self.diagnosis_counts is None):
            raise ValueError("Diagnosis association summary is incomplete")
        if self.stage == "complete" and (self.pipeline_error is not None or self.report_digest is None):
            raise ValueError("Completed pipeline requires a report")
        return self


def _project(inspection):
    # No transport or producer is constructed here. These imports only select
    # actual retained backend types, never user-submitted JSON or dataclasses.
    from .readonly import ReadOnlyInspection
    from .service import CompletedInspection
    try:
        if type(inspection) is ReadOnlyInspection:
            envelope = inspection.validate()
            binding, stage, error = inspection.binding, inspection.stage, inspection.error_code
        elif type(inspection) is CompletedInspection:
            inspection.validate()
            binding, stage, error = inspection.source_binding, "complete", None
            envelope = inspection.prepared.verify_request(inspection.prepared.to_request(), expected_binding=binding)
        else:
            raise ValueError()
        validated = validate_provider_context(envelope)
        context = envelope["collection_context"]
        source = "mock" if binding.is_mock else "real"
        if validated.snapshot.data_source.value != source:
            raise ValueError()
        presentation = inspection.presentation
        report = presentation.report.model_dump(mode="json", warnings=False) if presentation is not None else None
        # Persist no goal, request details, raw IDs, project/scope, log messages,
        # report prose, client config, credentials, environment or API payloads.
        return HistoryPayload(
            data_source=source, binding_digest=_binding_digest(binding),
            request_id_digest=_digest(inspection.request.request_id),
            request_fingerprint=request_fingerprint(inspection.request),
            snapshot_digest=context["snapshot_digest"], context_digest=context_digest(context),
            report_digest=_digest(report) if report is not None else None, stage=stage, pipeline_error=error,
            capabilities=context["capabilities"], logs=context["log_export"], limitations=context["limitations"],
            diagnosis_counts={key: len(report[key]) for key in DiagnosisCounts.model_fields} if report is not None else None,
        )
    except Exception:
        raise HistoryError("INVALID_INSPECTION") from None


@dataclass(frozen=True)
class HistoricalInspection:
    record_id: str
    sequence: int
    stored_at: str
    _payload: str = field(repr=False)

    def to_dict(self):
        return {"record_id": self.record_id, "sequence": self.sequence, "stored_at": self.stored_at,
                "summary": json.loads(self._payload)}


class SQLiteInspectionHistory:
    """Append-only summaries with bounded, binding-scoped reads.

    Caller-selected local file; one connection per instance/thread. SQLite owns
    atomic commit/rollback and cross-connection locking. This is not an ACL or
    encrypted vault; keep the file in an operator-controlled private directory.
    """

    def __init__(self, path, *, create=True, timeout=5.0):
        self._connection = None
        try:
            if (type(create) is not bool or type(timeout) not in (float, int)
                    or not math.isfinite(timeout) or not 0 < timeout <= 30):
                raise HistoryError("INVALID_DATABASE")
            location = Path(path)
            if location.is_symlink() or not location.parent.is_dir():
                raise HistoryError("INVALID_DATABASE")
            if not create and not location.is_file():
                raise HistoryError("INVALID_DATABASE")
            mode = "rwc" if create else "rw"
            self._connection = sqlite3.connect(location.resolve().as_uri() + "?mode=" + mode,
                                               uri=True, timeout=timeout)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA trusted_schema = OFF")
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                app = self._connection.execute("PRAGMA application_id").fetchone()[0]
                version = self._connection.execute("PRAGMA user_version").fetchone()[0]
                tables = self._connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                if app == 0 and version == 0 and not tables and create:
                    self._connection.execute("""CREATE TABLE inspections (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        record_id TEXT NOT NULL UNIQUE, binding_digest TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL, stored_at TEXT NOT NULL, payload TEXT NOT NULL
                    )""")
                    self._connection.execute("CREATE INDEX binding_order ON inspections(binding_digest, sequence)")
                    self._connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    self._connection.execute("PRAGMA user_version = 1")
                elif app != _APPLICATION_ID or version != 1:
                    raise HistoryError("UNSUPPORTED_DATABASE")
        except KeyboardInterrupt:
            self.close()
            raise
        except Exception as error:
            self.close()
            code = error.code if isinstance(error, HistoryError) else "STORAGE_FAILED"
            raise HistoryError(code) from None

    def __repr__(self):
        return "SQLiteInspectionHistory(storage='local', authority='none')"

    def __enter__(self):
        self._db()
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _db(self):
        if self._connection is None:
            raise HistoryError("STORE_CLOSED") from None
        return self._connection

    def _decode(self, row, expected_binding):
        try:
            if row["payload"] is None or len(row["payload"].encode("utf-8")) > _MAX_BYTES:
                raise ValueError()
            data = HistoryPayload.model_validate_json(row["payload"])
            canonical = _json(data.model_dump(mode="json"))
            if (canonical != row["payload"] or _digest(data.model_dump(mode="json")) != row["record_id"]
                    or data.binding_digest != expected_binding or row["binding_digest"] != expected_binding
                    or row["request_fingerprint"] != data.request_fingerprint):
                raise ValueError()
            instant = datetime.fromisoformat(row["stored_at"])
            if instant.tzinfo is None or type(row["sequence"]) is not int or row["sequence"] < 1:
                raise ValueError()
            return HistoricalInspection(row["record_id"], row["sequence"], row["stored_at"], canonical)
        except Exception:
            raise HistoryError("RECORD_CORRUPTED") from None

    def save(self, inspection):
        self._db()
        data = _project(inspection).model_dump(mode="json")
        payload, record_id = _json(data), _digest(data)
        if len(payload.encode("ascii")) > _MAX_BYTES:
            raise HistoryError("INVALID_INSPECTION") from None
        try:
            with self._db() as db:
                db.execute("INSERT OR IGNORE INTO inspections(record_id, binding_digest, request_fingerprint, stored_at, payload) VALUES(?,?,?,?,?)",
                           (record_id, data["binding_digest"], data["request_fingerprint"], datetime.now(timezone.utc).isoformat(), payload))
                row = self._select_one(record_id, data["binding_digest"])
                result = self._decode(row, data["binding_digest"])
            return result
        except HistoryError:
            raise
        except Exception:
            raise HistoryError() from None

    def _select_one(self, record_id, binding_digest):
        return self._db().execute("""SELECT sequence, record_id, binding_digest, request_fingerprint, stored_at,
            CASE WHEN length(payload) <= ? THEN payload ELSE NULL END AS payload
            FROM inspections WHERE record_id = ? AND binding_digest = ?""",
            (_MAX_BYTES, record_id, binding_digest)).fetchone()

    def get(self, record_id, *, expected_binding):
        try:
            if type(record_id) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", record_id) is None:
                raise HistoryError("INVALID_LOOKUP")
            binding = _binding_digest(expected_binding)
            row = self._select_one(record_id, binding)
            return None if row is None else self._decode(row, binding)
        except HistoryError:
            raise
        except Exception:
            raise HistoryError() from None

    def list_for(self, *, expected_binding, limit=20, before_sequence=None, request=None):
        try:
            if (type(limit) is not int or not 1 <= limit <= 100 or
                    (before_sequence is not None and (type(before_sequence) is not int or before_sequence < 1))):
                raise HistoryError("INVALID_LOOKUP")
            binding = _binding_digest(expected_binding)
            conditions, params = ["binding_digest = ?"], [binding]
            if before_sequence is not None:
                conditions.append("sequence < ?")
                params.append(before_sequence)
            if request is not None:
                conditions.append("request_fingerprint = ?")
                params.append(request_fingerprint(request))
            rows = self._db().execute("""SELECT sequence, record_id, binding_digest, request_fingerprint, stored_at,
                CASE WHEN length(payload) <= ? THEN payload ELSE NULL END AS payload
                FROM inspections WHERE """ + " AND ".join(conditions) + " ORDER BY sequence DESC LIMIT ?",
                [_MAX_BYTES, *params, limit]).fetchall()
            return tuple(self._decode(row, binding) for row in rows)
        except HistoryError:
            raise
        except Exception:
            raise HistoryError() from None
