"""Draft contracts and deterministic diagnostics for InfraPilot."""

from .schemas import (
    ActionProposal,
    DataSource,
    DiagnosticHypothesis,
    DiagnosisReport,
    Evidence,
    EvidenceKind,
    LogEntry,
    LogLevel,
    RiskLevel,
    ServiceSnapshot,
    ServiceStatus,
)
from .engine import diagnose
from .symptoms import DiagnosisThresholds
from .policy import ActionCategory, ActionIntent, ActionPolicy, ActionType, CanonicalAction, PolicyDecision
from .identity import AuthenticatedActor, IdentityBoundary, Permission
from .approvals import ApprovalRequest, ApprovalState, AuditEvent, AuditKind, DecisionReason, GateDecision
from .approval_store import InMemoryApprovalStore
from .authorization import ApprovalGate

__all__ = [
    "ActionProposal",
    "ActionCategory",
    "ActionIntent",
    "ActionPolicy",
    "ActionType",
    "ApprovalGate",
    "ApprovalRequest",
    "ApprovalState",
    "AuditEvent",
    "AuditKind",
    "AuthenticatedActor",
    "CanonicalAction",
    "DataSource",
    "DiagnosticHypothesis",
    "DiagnosisReport",
    "DiagnosisThresholds",
    "DecisionReason",
    "Evidence",
    "EvidenceKind",
    "LogEntry",
    "LogLevel",
    "GateDecision",
    "IdentityBoundary",
    "InMemoryApprovalStore",
    "Permission",
    "PolicyDecision",
    "RiskLevel",
    "ServiceSnapshot",
    "ServiceStatus",
    "diagnose",
]
