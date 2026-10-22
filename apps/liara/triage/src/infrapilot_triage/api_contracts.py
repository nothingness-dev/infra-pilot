"""INTERNAL DRAFT v0.1 HTTP envelopes; existing core contracts are unchanged."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .policy import ActionIntent, PolicyDecision


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    component: Literal["triage_api"] = "triage_api"
    scope: Literal["process_only"] = "process_only"


class ErrorCode(str, Enum):
    VALIDATION = "validation_error"
    INTERNAL = "internal_error"
    AUTHENTICATION_UNAVAILABLE = "authentication_unavailable"
    AUTHENTICATION_REQUIRED = "authentication_required"
    APPROVAL_UNAVAILABLE = "approval_integration_unavailable"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    HTTP = "http_error"


class ErrorDetail(ApiModel):
    code: ErrorCode
    message: str


class ErrorResponse(ApiModel):
    error: ErrorDetail


class AuthorizationRequest(ApiModel):
    intent: ActionIntent
    approval_request_id: StrictStr | None = Field(default=None, max_length=128)


class PolicyEvaluationResponse(ApiModel):
    policy: PolicyDecision
    authorization_granted: Literal[False] = False
