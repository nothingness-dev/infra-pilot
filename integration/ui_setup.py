"""Durable Mock setup proposals. No provider writes, secrets, or executable grants."""

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from infrapilot_triage import ActionIntent, ActionPolicy
from setup.models import OperationRequest
from setup.workflow import prepare_request


class SetupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(pattern=r"^[0-9a-f-]{36}$")
    service_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    platform: Literal["nodejs", "python", "docker", "go", "php", "static"]
    plan: Literal["starter-256mb", "standard-1gb", "pro-2gb"]
    custom_domain: str = Field(default="", max_length=253)
    environment_keys: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("idempotency_key")
    @classmethod
    def uuid4_key(cls, value):
        if str(UUID(value)) != value or UUID(value).version != 4:
            raise ValueError("Invalid request key")
        return value

    @field_validator("custom_domain")
    @classmethod
    def domain(cls, value):
        if value and (len(value.split(".")) < 2 or any(
            re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) is None
            for label in value.split(".")
        )):
            raise ValueError("Invalid domain")
        return value.lower()

    @field_validator("environment_keys")
    @classmethod
    def keys(cls, value):
        if len(set(value)) != len(value) or any(re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", key) is None for key in value):
            raise ValueError("Invalid environment keys")
        return sorted(value)


class SetupPlans:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise HTTPException(503, "UI_UNAVAILABLE")
        connection = self._connect()
        connection.close()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS setup_plans (id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)")
        except BaseException:
            connection.close()
            raise
        return connection

    @staticmethod
    def _decode(identifier, fingerprint, payload):
        """Validate retained records before returning anything to a browser."""
        try:
            if not isinstance(payload, str) or len(payload.encode("utf-8")) > 8192:
                raise ValueError()
            value = json.loads(payload)
            allowed = {"id", "source", "operation", "state", "limitation", "created_at", "brief",
                       "environment_values", "execution_authorized", "execution_performed", "preparation"}
            if (type(value) is not dict or set(value) != allowed or value["id"] != identifier
                    or re.fullmatch(r"SETUP-[0-9a-f]{32}", identifier) is None
                    or value["source"] != "mock" or value["operation"] != "setup_service"
                    or value["state"] != "blocked" or value["limitation"] != "setup_operation_not_supported_by_gate"
                    or value["environment_values"] != "not_collected"
                    or value["execution_authorized"] is not False or value["execution_performed"] is not False
                    or datetime.fromisoformat(value["created_at"]).utcoffset() is None):
                raise ValueError()
            brief = SetupInput(idempotency_key=str(uuid4()), **value["brief"]).model_dump(exclude={"idempotency_key"})
            if brief != value["brief"] or hashlib.sha256(json.dumps(brief, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != fingerprint:
                raise ValueError()
            if value["preparation"] != _prepare(brief, identifier):
                raise ValueError()
            return value
        except Exception:
            raise HTTPException(503, "UI_UNAVAILABLE") from None

    def create(self, body, created_at):
        brief = body.model_dump(exclude={"idempotency_key"})
        encoded = json.dumps(brief, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        # Ask the real policy, and preserve its unsupported-operation limitation.
        policy = ActionPolicy().classify(ActionIntent(service_id=body.service_id, action_type="setup_service"))
        if policy.allowed:
            raise HTTPException(503, "SETUP_POLICY_CHANGED")  # Requires a reviewed gate integration.
        connection = self._connect()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute("SELECT fingerprint,CASE WHEN length(CAST(payload AS BLOB))<=8192 THEN payload END,id FROM setup_plans WHERE key=?", (body.idempotency_key,)).fetchone()
                if existing:
                    if existing[0] != fingerprint:
                        raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
                    return self._decode(existing[2], existing[0], existing[1])
                if connection.execute("SELECT count(*) FROM setup_plans").fetchone()[0] >= 100:
                    raise HTTPException(429, "SESSION_LIMIT")
                value = {"id": "SETUP-" + uuid4().hex, "source": "mock", "operation": "setup_service",
                         "state": "blocked", "limitation": "setup_operation_not_supported_by_gate",
                         "created_at": created_at, "brief": brief, "environment_values": "not_collected",
                         "execution_authorized": False, "execution_performed": False}
                value["preparation"] = _prepare(brief, value["id"])
                connection.execute("INSERT INTO setup_plans VALUES(?,?,?,?)",
                                   (value["id"], body.idempotency_key, fingerprint, json.dumps(value)))
                return value
        finally:
            connection.close()

    def list(self):
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT id,fingerprint,CASE WHEN length(CAST(payload AS BLOB))<=8192 THEN payload END FROM setup_plans ORDER BY rowid LIMIT 101").fetchall()
            if len(rows) > 100:
                raise HTTPException(503, "UI_UNAVAILABLE")
            return [self._decode(*row) for row in rows]
        finally:
            connection.close()


def _prepare(brief, identifier):
    """Use Setup's existing offline planner; never infer external dependencies."""
    result = prepare_request(OperationRequest(identifier, "setup_service", {
        "service_name": brief["service_id"], "service_kind": brief["platform"],
        "goal": "Prepare an offline Mock setup proposal for review.", "plan": brief["plan"],
    }))
    if result.plan is None or result.execution_authorized is not False or result.execution_performed is not False:
        raise HTTPException(503, "SETUP_POLICY_CHANGED")
    return {"state": result.state.value,
            "step_keys": [step.key for step in result.plan.proposed_steps],
            "missing_dependencies": [dependency.key for dependency in result.plan.dependencies if not dependency.available]}
