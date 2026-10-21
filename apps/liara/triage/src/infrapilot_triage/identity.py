"""Trusted integration port; this module does not authenticate user-supplied IDs."""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol

from .policy import CanonicalAction


class Permission(str, Enum):
    REQUEST = "request_approval"
    APPROVE = "approve_action"
    EXECUTE = "authorize_action"


@dataclass(frozen=True)
class AuthenticatedActor:
    """Identity output from a trusted verifier, not proof supplied by the Agent."""

    subject: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}", self.subject):
            raise ValueError("A non-secret stable actor identifier is required")


class IdentityBoundary(Protocol):
    """Implement only in trusted composition code, never from Agent-provided data.

    authenticate must verify a session/credential, not merely accept an ID.
    is_authorized must check current account status and permissions for the exact
    service/action/permission, resolving the service against trusted target
    information, including for a previously authenticated approver.
    Exceptions, missing dependencies, and non-True responses fail closed.
    """

    def authenticate(self, authentication: object) -> AuthenticatedActor | None: ...

    def is_authorized(
        self, actor: AuthenticatedActor, action: CanonicalAction, permission: Permission,
    ) -> bool: ...
