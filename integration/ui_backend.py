"""Explicit loopback MOCK UI adapter. No default app, live provider or executor."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import secrets
import json
from threading import RLock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .approval_store import SQLiteApprovalStore
from .history import SQLiteInspectionHistory
from .mock_approval import MockClock, OperatorApprovalExample
from .service import MockSession

CATALOG = (("INC-024", "partial_failure", "جمع‌آوری ناقص شواهد", "active"),
           ("INC-023", "exported", "بازبینی شواهد موجود", "review"),
           ("INC-022", "withheld", "متن لاگ منتشر نشده است", "review"),
           ("INC-021", "empty", "مجموعهٔ لاگ خالی", "closed"))
FLAGS = {"authorization_consumed": False, "execution_authorized": False, "execution_performed": False,
         "remediation_verified": False, "identity_verified": False}
SAFE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; img-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}


def error_response(code, status):
    return JSONResponse({"error_code": code}, status_code=status, headers=SAFE_HEADERS)


def now():
    return datetime.now(timezone.utc).isoformat()


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RevisionInput(EmptyInput):
    revision: str = Field(min_length=36, max_length=36)


class DecisionInput(RevisionInput):
    decision: str = Field(pattern="^(approve|reject)$")


@dataclass
class Record:
    identifier: str
    scenario: str
    title: str
    lifecycle: str
    inspection: object
    revision: str
    created_at: str
    history_id: str


class UiSession:
    """Retained objects and opaque identities never leave this process."""

    def __init__(self, directory):
        self.directory, self.csrf = directory, secrets.token_urlsafe(32)
        self.records, self.approvals = {}, {}
        self.clock = MockClock()
        try:
            with SQLiteInspectionHistory(directory / "history.sqlite") as history:
                for identifier, scenario, title, lifecycle in CATALOG:
                    inspection = MockSession(mock=True, scenario=scenario).inspect()
                    saved = history.save(inspection)
                    self.records[identifier] = Record(identifier, scenario, title, lifecycle, inspection,
                                                      str(uuid4()), now(), saved.record_id)
            self.request_approval("INC-024", self.records["INC-024"].revision)
        except BaseException:
            self.close()
            raise

    def close(self):
        for value in self.approvals.values():
            if value.get("operator") is not None:
                value["operator"].close()

    def record(self, identifier, revision=None):
        record = self.records.get(identifier)
        if record is None:
            raise HTTPException(404, "NOT_FOUND")
        if revision is not None and record.revision != revision:
            raise HTTPException(409, "STALE_REVISION")
        record.inspection.validate()
        return record

    def request_approval(self, identifier, revision):
        record = self.record(identifier, revision)
        if len(self.approvals) >= 100:
            raise HTTPException(429, "SESSION_LIMIT")
        self.clock.now = datetime.now(timezone.utc)
        operator = OperatorApprovalExample(record.inspection, clock=self.clock,
            store_factory=lambda **refs: SQLiteApprovalStore(self.directory / "approval.sqlite", **refs))
        try:
            result = operator.request(authentication=operator.identity.requester_session)
            if result.request is None:
                raise HTTPException(503, "APPROVAL_UNAVAILABLE")
            public_id = "APR-" + uuid4().hex[:8].upper()
            self.approvals[public_id] = {"operator": operator, "record_id": identifier,
                "revision": revision, "historical": False, "snapshot": None}
            return public_id
        except BaseException:
            operator.close()
            raise

    def approval_view(self, identifier, entry):
        if entry["historical"]:
            return {**entry["snapshot"], "historical": True, "can_decide": False}
        raw = entry["operator"].to_dict()
        current = raw["current_approval"]
        policy = raw["review"]["policy"]
        parameters = json.loads(policy["action"]["parameters_json"])
        return {"id": identifier, "record_id": entry["record_id"], "revision": entry["revision"],
            "state": current["state"].value, "created_at": current["created_at"].isoformat(),
            "expires_at": current["expires_at"].isoformat(), "historical": False,
            "operation": "restart_service", "separate_demo": True,
            "grace_period_seconds": parameters["grace_period_seconds"], "policy_category": policy["category"],
            "can_decide": current["state"].value == "pending", "audit": [
                {"kind": event["kind"].value, "reason": event["reason"].value,
                 "occurred_at": event["occurred_at"].isoformat()} for event in raw["audit_events"]], **FLAGS}

    def decide(self, identifier, body):
        entry = self.approvals.get(identifier)
        if entry is None:
            raise HTTPException(404, "NOT_FOUND")
        self.record(entry["record_id"], body.revision)
        if entry["historical"] or entry["revision"] != body.revision:
            raise HTTPException(409, "STALE_REVISION")
        if self.approval_view(identifier, entry)["state"] != "pending":
            raise HTTPException(409, "DECISION_FINAL")
        self.clock.now = datetime.now(timezone.utc)
        operator = entry["operator"]
        decision = operator.decide(approve=body.decision == "approve", authentication=operator.identity.approver_session)
        return {"state": self.approval_view(identifier, entry)["state"], "reason": decision.reason.value, **FLAGS}

    def refresh(self, identifier, revision):
        record = self.record(identifier, revision)
        replacement = MockSession(mock=True, scenario=record.scenario).inspect()
        with SQLiteInspectionHistory(self.directory / "history.sqlite") as history:
            saved = history.save(replacement)
        for key, entry in self.approvals.items():
            if entry["record_id"] == identifier and not entry["historical"]:
                entry["snapshot"] = self.approval_view(key, entry)
                entry["operator"].close()
                entry.update(historical=True, operator=None)
        self.records[identifier] = Record(identifier, record.scenario, record.title, record.lifecycle,
                                         replacement, str(uuid4()), now(), saved.record_id)

    def view(self):
        records = []
        for record in self.records.values():
            record.inspection.validate()
            view = record.inspection.result.to_dict()["presentation"]
            snapshot = {key: value for key, value in view["snapshot"].items() if key != "logs"}
            records.append({"id": record.identifier, "title": record.title, "lifecycle": record.lifecycle,
                "lifecycle_is_demo": True, "revision": record.revision, "scenario": record.scenario,
                "created_at": record.created_at, "history_id": record.history_id,
                "snapshot": snapshot, "report": view["diagnosis"]["report"],
                "context": view["collection_context"], "source": "mock", **FLAGS})
        return {"version": "infrapilot-ui/1-mock", "source": "mock", "real_available": False,
            "service": {"id": "MOCK-service", "name": "سرویس آزمایشی", "project": "mock-project"},
            "records": records, "approvals": [self.approval_view(key, value) for key, value in self.approvals.items()],
            "connection": {"state": "not_verified", "logs_window": "not_configured"}, **FLAGS}


def create_ui_app(*, mock=False, data_directory=None, origins=None, static_directory=None):
    if mock is not True or data_directory is None:
        raise ValueError("Explicit Mock UI configuration required.") from None
    directory = Path(data_directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Invalid UI data directory.") from None
    allowed = frozenset(origins or ("http://127.0.0.1:4173", "http://localhost:4173", "http://127.0.0.1:8787", "http://localhost:8787"))
    sessions, lock = {}, RLock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for session in sessions.values():
            session.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
            if request.headers.get("origin") not in allowed or request.headers.get("content-type", "").split(";")[0] != "application/json":
                return error_response("ORIGIN_DENIED", 403)
            length = request.headers.get("content-length", "")
            if not length.isascii() or not length.isdigit() or len(length) > 6 or int(length) > 1024:
                return error_response("INVALID_REQUEST", 413)
            if len(await request.body()) > 1024:
                return error_response("INVALID_REQUEST", 413)
        response = await call_next(request)
        response.headers.update(SAFE_HEADERS)
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        codes = {"NOT_FOUND", "STALE_REVISION", "DECISION_FINAL", "APPROVAL_UNAVAILABLE", "SESSION_REQUIRED", "CSRF_DENIED", "SESSION_LIMIT"}
        return error_response(error.detail if error.detail in codes else "INVALID_REQUEST", error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response("INVALID_REQUEST", 422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return error_response("UI_UNAVAILABLE", 503)

    def current(request, *, mutation=False):
        session = sessions.get(request.cookies.get("infrapilot_mock"))
        if session is None:
            raise HTTPException(401, "SESSION_REQUIRED")
        if mutation and not secrets.compare_digest(request.headers.get("x-ui-csrf", "").encode("utf-8"), session.csrf.encode("ascii")):
            raise HTTPException(403, "CSRF_DENIED")
        return session

    @app.post("/api/ui/session")
    def bootstrap(request: Request, body: EmptyInput):
        with lock:
            key = request.cookies.get("infrapilot_mock")
            if key not in sessions:
                if len(sessions) >= 8:
                    raise HTTPException(429, "SESSION_LIMIT")
                folder = directory / uuid4().hex
                folder.mkdir()
                session = UiSession(folder)
                key = secrets.token_urlsafe(32)
                sessions[key] = session
            response = JSONResponse({"csrf": sessions[key].csrf, "source": "mock"})
            response.set_cookie("infrapilot_mock", key, httponly=True, samesite="strict", max_age=3600)
            return response

    @app.get("/api/ui/state")
    def state(request: Request):
        with lock:
            return current(request).view()

    @app.post("/api/ui/reports/{identifier}/refresh")
    def refresh(identifier: str, request: Request, body: RevisionInput):
        with lock:
            current(request, mutation=True).refresh(identifier, body.revision)
            return {"status": "refreshed", **FLAGS}

    @app.post("/api/ui/reports/{identifier}/approval")
    def request_approval(identifier: str, request: Request, body: RevisionInput):
        with lock:
            return {"id": current(request, mutation=True).request_approval(identifier, body.revision), **FLAGS}

    @app.post("/api/ui/approvals/{identifier}/decision")
    def decide(identifier: str, request: Request, body: DecisionInput):
        with lock:
            return current(request, mutation=True).decide(identifier, body)

    @app.get("/api/ui/reports/{identifier}/export")
    def export(identifier: str, request: Request):
        with lock:
            record = current(request).record(identifier)
            raw = record.inspection.result.to_dict()["presentation"]
            report = raw["diagnosis"]["report"]
            return {"profile": "infrapilot-ui-export/1", "source": "mock", "historical": True,
                "report_id": identifier, "created_at": record.created_at,
                "counts": {name: len(report[name]) for name in ("evidence", "hypotheses", "actions", "limitations", "missing_information")},
                "capabilities": raw["collection_context"]["capabilities"], **FLAGS}

    if static_directory is not None:
        root = Path(static_directory).resolve()
        @app.get("/{path:path}")
        def frontend(path: str):
            target = (root / path).resolve()
            if path == "api" or path.startswith("api/") or not target.is_relative_to(root):
                raise HTTPException(404, "NOT_FOUND")
            file = target if target.is_file() else root / "index.html"
            if not file.is_file():
                raise HTTPException(404, "NOT_FOUND")
            return FileResponse(file)
    return app
