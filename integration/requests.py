"""Local Mock continuation over real Setup, Provider, Triage and summary history.

Stored briefs are data only. The sole current-evidence cache contains original
producer objects from THIS instance; no deserialization populates that cache.
No approval, identity, executor, live client or environment lookup is involved.
"""

from uuid import uuid4

from provider.examples.context_fixtures import mock_context_binding
from setup.validation import validate_request
from .composition import validate_retained_inspection
from .history import SQLiteInspectionHistory
from .request_errors import RequestError, VERSION
from .request_policy import accept, details, digest, fingerprint, identifier, operation, positive, SCENARIOS
from .request_store import SQLiteRequestStore
from .service import CompletedInspection, MockSession


class PersistentMockRequests:
    """One backend instance/thread, explicit Mock opt-in, finite brief vocabulary.

    Returned dictionaries are detached observations/receipts, never capabilities.
    ``expected_revision`` is required even for read-only current-evidence use.
    """

    def __init__(self, store, *, mock=False):
        if mock is not True:
            raise RequestError("MOCK_OPT_IN_REQUIRED") from None
        if type(store) is not SQLiteRequestStore:
            raise RequestError("INVALID_DATABASE") from None
        self._store = store
        self._retained = {}

    def __repr__(self):
        return "PersistentMockRequests(mode='mock', authority='none')"

    def _view(self, value):
        # No stored flags, identity claims, prose or reports participate here.
        is_current = self._store.get(value["request_id"]) == value
        present = is_current and (value["request_id"], value["attempt_id"]) in self._retained
        if present and value["state"] == "inspection_recorded":
            self._validate(value)
        return {"request_profile": VERSION, "request": value, "data_source": "mock",
                "operation": "inspect_service",
                "missing_information": [item.field for item in validate_request(operation(value["request_id"], value["details"])).missing_information],
                "historical_status": True, "is_current_revision": is_current,
                "retained_evidence_available": present and value["state"] == "inspection_recorded",
                "reinspection_required": value["state"] == "inspection_recorded" and not present,
                "recovery_required": is_current and value["state"] in ("inspecting", "awaiting_history") and not present,
                "authorization_consumed": False, "execution_authorized": False,
                "execution_performed": False, "remediation_verified": False}

    def create(self, brief, *, idempotency_key):
        brief = details(brief)
        identifier(idempotency_key)

        def transition(_):
            request_id = uuid4().hex
            accepted = accept(request_id, brief)
            fp = fingerprint(request_id, accepted)
            return {"request_id": request_id, "revision": 1, "brief_revision": 1,
                    "details": accepted, "fingerprint": fp,
                    "state": "needs_information" if fp is None else "ready_for_inspection",
                    "attempt_id": None, "scenario": None, "history_id": None, "error_code": None}

        value = self._store._mutate(key=idempotency_key, command=["create", brief], request_id=None,
                                    expected_revision=None, transition=transition, kind="created")
        return self._view(value)

    def supply_information(self, request_id, additional_information, *, expected_revision, idempotency_key):
        brief = details(additional_information)
        identifier(request_id)
        positive(expected_revision)

        def transition(old):
            accepted = accept(request_id, brief, previous=old["details"])
            changed = accepted != old["details"]
            if not changed and old["state"] in ("inspecting", "awaiting_history"):
                raise RequestError("RECOVERY_REQUIRED")
            # A no-op still records an accepted transition, but retains evidence association.
            if not changed:
                return {**old, "revision": old["revision"] + 1}
            fp = fingerprint(request_id, accepted)
            return {**old, "revision": old["revision"] + 1, "brief_revision": old["brief_revision"] + 1,
                    "details": accepted, "fingerprint": fp,
                    "state": "needs_information" if fp is None else "ready_for_inspection",
                    "attempt_id": None, "scenario": None, "history_id": None, "error_code": None}

        value = self._store._mutate(key=idempotency_key, command=["supply", request_id, expected_revision, brief],
                                    request_id=request_id, expected_revision=expected_revision,
                                    transition=transition, kind="information_supplied")
        # Invalidate all old process-local associations when the accepted brief changed.
        current = self._store.get(request_id)
        for key, (brief_revision, _, _) in tuple(self._retained.items()):
            if key[0] == request_id and brief_revision != current["brief_revision"]:
                del self._retained[key]
        return self._view(value)

    def get(self, request_id):
        return self._view(self._store.get(request_id))

    def events(self, request_id, *, limit=20, before_revision=None):
        # Intentionally historical; never inspects or diagnoses.
        return self._store.events(request_id, limit=limit, before_revision=before_revision)

    def _validate(self, value):
        try:
            brief_revision, fp, inspection = self._retained[(value["request_id"], value["attempt_id"])]
            if (type(inspection) is not CompletedInspection or brief_revision != value["brief_revision"]
                    or fp != value["fingerprint"] or inspection.request != operation(value["request_id"], value["details"])
                    or fingerprint(inspection.request.request_id, inspection.request.details) != fp
                    or inspection.source_binding != mock_context_binding()):
                raise ValueError()
            # Expected binding selected afresh from backend configuration, never from SQLite/JSON.
            validate_retained_inspection(inspection.request, inspection.prepared, mock_context_binding(),
                                         inspection.companion, inspection.presentation)
            inspection.validate()
            return inspection
        except Exception:
            raise RequestError("EVIDENCE_MISMATCH") from None

    def current_inspection(self, request_id, *, expected_revision):
        positive(expected_revision)
        value = self._store.get(request_id)
        if value["revision"] != expected_revision:
            raise RequestError("REVISION_CONFLICT")
        if value["state"] != "inspection_recorded" or (request_id, value["attempt_id"]) not in self._retained:
            raise RequestError("REINSPECTION_REQUIRED")
        return self._validate(value)

    def inspect(self, request_id, *, expected_revision, idempotency_key, history, scenario="partial_failure"):
        identifier(request_id)
        identifier(idempotency_key)
        positive(expected_revision)
        if type(scenario) is not str or scenario not in SCENARIOS or type(history) is not SQLiteInspectionHistory:
            raise RequestError("INVALID_ARGUMENTS")
        started = []

        def transition(old):
            if old["fingerprint"] is None:
                raise RequestError("INCOMPLETE_REQUEST")
            if old["state"] in ("inspecting", "awaiting_history"):
                raise RequestError("RECOVERY_REQUIRED")
            started.append(True)
            return {**old, "revision": old["revision"] + 1, "state": "inspecting", "attempt_id": idempotency_key,
                    "scenario": scenario, "history_id": None, "error_code": None}

        value = self._store._mutate(key=idempotency_key, command=["inspect", request_id, expected_revision, scenario],
                                    request_id=request_id, expected_revision=expected_revision,
                                    transition=transition, kind="inspection_started", pending=True)
        if value["state"] not in ("inspecting", "awaiting_history"):
            if value["state"] == "inspection_failed":
                raise RequestError("COLLECTION_FAILED")
            return {**self._view(value), "historical_summary": self.historical_summary(
                request_id, history=history, revision=value["revision"],
            )}  # Durable receipt; never recollect on replay.
        current = self._store.get(request_id)
        if current != value:
            raise RequestError("REVISION_CONFLICT")
        key = (request_id, idempotency_key)
        if value["state"] == "inspecting":
            if key not in self._retained:
                # Only the transaction callback can tag a NEW start. SQLite cannot mint it.
                if not started:
                    raise RequestError("RECOVERY_REQUIRED")
                try:
                    inspection = MockSession(mock=True, scenario=scenario,
                                             request=operation(request_id, value["details"])).inspect()
                    self._retained[key] = (value["brief_revision"], value["fingerprint"], inspection)
                    self._validate(value)
                except KeyboardInterrupt:
                    raise
                except Exception:
                    self._retained.pop(key, None)
                    self._store._advance_attempt(request_id, revision=value["revision"], attempt_id=idempotency_key,
                                                  state="inspection_failed", error="COLLECTION_FAILED")
                    raise RequestError("COLLECTION_FAILED") from None
            else:
                self._validate(value)
            value = self._store._advance_attempt(request_id, revision=value["revision"], attempt_id=idempotency_key,
                                                  state="awaiting_history")
        elif key not in self._retained:
            raise RequestError("RECOVERY_REQUIRED")
        inspection = self._validate(value)
        try:
            saved = history.save(inspection)
            if history.get(saved.record_id, expected_binding=mock_context_binding()) != saved:
                raise ValueError()
            self._verify_history(value, saved)
        except KeyboardInterrupt:
            raise
        except Exception:
            raise RequestError("HISTORY_FAILED") from None
        # If interrupted here, re-saving the SAME retained inspection is idempotent.
        value = self._store._advance_attempt(request_id, revision=value["revision"], attempt_id=idempotency_key,
                                              state="inspection_recorded", history_id=saved.record_id)
        return {**self._view(value), "historical_summary": saved.to_dict()}

    def recover(self, request_id, *, expected_revision, idempotency_key):
        abandoned = []

        def transition(old):
            if old["state"] not in ("inspecting", "awaiting_history"):
                raise RequestError("INVALID_REQUEST")
            abandoned.append(old["attempt_id"])
            return {**old, "revision": old["revision"] + 1, "state": "ready_for_inspection",
                    "attempt_id": None, "scenario": None, "history_id": None, "error_code": "INTERRUPTED"}

        value = self._store._mutate(key=idempotency_key, command=["recover", request_id, expected_revision],
                                    request_id=request_id, expected_revision=expected_revision,
                                    transition=transition, kind="recovered")
        for attempt in abandoned:
            self._retained.pop((request_id, attempt), None)
        return self._view(value)

    @staticmethod
    def _verify_history(value, saved):
        summary = saved.to_dict()["summary"]
        if (summary["request_fingerprint"] != value["fingerprint"]
                or summary["request_id_digest"] != digest(value["request_id"])
                or summary["data_source"] != "mock"):
            raise RequestError("EVIDENCE_MISMATCH")

    def historical_summary(self, request_id, *, history, revision=None):
        if type(history) is not SQLiteInspectionHistory:
            raise RequestError("INVALID_ARGUMENTS")
        value = self._store.get(request_id)
        if revision is not None:
            positive(revision)
            events = self._store.events(request_id, limit=1, before_revision=revision + 1)
            if not events or events[0]["request"]["revision"] != revision:
                raise RequestError("NOT_FOUND")
            value = events[0]["request"]
        if value["history_id"] is None:
            return None
        try:
            saved = history.get(value["history_id"], expected_binding=mock_context_binding())
            if saved is None:
                raise ValueError()
            self._verify_history(value, saved)
            return saved.to_dict()
        except Exception:
            raise RequestError("HISTORY_FAILED") from None
