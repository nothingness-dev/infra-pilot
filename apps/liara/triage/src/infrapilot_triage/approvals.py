"""Immutable approval lifecycle records and structured, credential-free audits."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .identity import AuthenticatedActor
from .policy import ActionType, CanonicalAction


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class DecisionReason(str, Enum):
    PENDING = "approval_pending"
    APPROVED = "approval_approved"
    REJECTED = "approval_rejected"
    EXPIRED = "approval_expired"
    CONSUMED = "approval_consumed"
    AUTHORIZED = "authorized_not_executed"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_NOT_REQUIRED = "approval_not_required"
    INVALID_ACTION = "invalid_or_unknown_action"
    UNSUPPORTED_ACTION = "unsupported_action"
    UNAUTHENTICATED = "unauthenticated"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    NOT_AUTHORIZED = "not_authorized"
    AUTHORIZATION_UNAVAILABLE = "authorization_unavailable"
    POLICY_UNAVAILABLE = "policy_unavailable"
    STORAGE_UNAVAILABLE = "storage_or_audit_unavailable"
    CLOCK_UNAVAILABLE = "clock_unavailable"
    INVALID_EXPIRATION = "invalid_expiration"
    REQUEST_NOT_FOUND = "request_not_found"
    INVALID_STATE = "invalid_approval_state"
    ACTION_MISMATCH = "action_mismatch"
    REQUESTER_MISMATCH = "requester_mismatch"
    SELF_APPROVAL = "self_approval_denied"


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    action: CanonicalAction
    requested_by: AuthenticatedActor
    created_at: datetime
    expires_at: datetime
    state: ApprovalState = ApprovalState.PENDING
    approved_by: AuthenticatedActor | None = None
    rejected_by: AuthenticatedActor | None = None
    consumed_by: AuthenticatedActor | None = None


class AuditKind(str, Enum):
    REQUESTED = "approval_requested"
    GRANTED = "approval_granted"
    REJECTED = "approval_rejected"
    EXPIRED = "approval_expired"
    DENIED = "authorization_denied"
    CONSUMED = "authorization_consumed"


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    occurred_at: datetime
    kind: AuditKind
    reason: DecisionReason
    request_id: str | None = None
    service_id: str | None = None
    action_type: ActionType | None = None
    fingerprint: str | None = None
    actor_id: str | None = None


@dataclass(frozen=True)
class GateDecision:
    """Only authorize() can allow; approval transitions never imply execution."""

    allowed: bool
    reason: DecisionReason
    action: CanonicalAction | None = None
    request: ApprovalRequest | None = None
    authorization_id: str | None = None
    audit_recorded: bool = False
