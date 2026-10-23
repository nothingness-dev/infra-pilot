"""Trusted request-access port and explicit process-local Mock implementation.

Approval permissions intentionally remain in Triage's separate ApprovalGate.
This module reuses its identity output; it does not verify credentials or JWTs.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from infrapilot_triage.identity import AuthenticatedActor
from provider import ServiceBinding
from provider.examples.context_fixtures import mock_context_binding
from .request_errors import RequestError
from .request_policy import digest, identifier, positive

VERSION = "infrapilot-request-access/1-mock"


class RequestPermission(str, Enum):
    CREATE = "create_request"
    READ = "read_request"
    COMPLETE = "complete_request"
    INSPECT = "inspect_request"
    HISTORY = "read_history"
    RECOVER = "recover_request"


def binding_reference(binding):
    try:
        if type(binding) is not ServiceBinding:
            raise ValueError()
        return digest({"access_binding_v1": asdict(ServiceBinding(**asdict(binding)))})
    except Exception:
        raise RequestError("ACCESS_DENIED") from None


@dataclass(frozen=True, repr=False)
class ResolvedAccess:
    """Output of installed trusted resolver, never an accepted caller context."""

    actor: AuthenticatedActor
    generation: int
    permissions: frozenset[RequestPermission]
    bindings: tuple[ServiceBinding, ...]

    def __repr__(self):
        return "ResolvedAccess(origin='trusted_resolver', authority='request_access_only')"


class RequestIdentityBoundary(Protocol):
    def resolve(self, context: object) -> ResolvedAccess | None:
        """Verify a server context and current permissions; return None on denial."""
        ...


def validate_resolution(value):
    try:
        if type(value) is not ResolvedAccess or type(value.actor) is not AuthenticatedActor:
            raise ValueError()
        identifier(value.actor.subject)  # Non-secret opaque owner reference only.
        positive(value.generation)
        if (type(value.permissions) is not frozenset or any(type(p) is not RequestPermission for p in value.permissions)
                or type(value.bindings) is not tuple or len(value.bindings) > 100):
            raise ValueError()
        for binding in value.bindings:
            binding_reference(binding)
        return value
    except Exception:
        raise RequestError("ACCESS_DENIED") from None


class AccessContext:
    __slots__ = ()

    def __new__(cls):
        raise RequestError("ACCESS_DENIED") from None

    def __repr__(self):
        return "AccessContext(mode='mock', contents='opaque')"


@dataclass(frozen=True, repr=False)
class _Session:
    principal: str
    generation: int
    issued_at: datetime
    expires_at: datetime
    last_seen: datetime


class MockRequestIdentity:
    """Trusted fixture issuer; not a login endpoint or production verifier.

    Only retained handle identity is recognized. Grants/contexts are volatile;
    permissions changes invalidate previously issued handles via generation.
    """

    def __init__(self, *, mock=False, clock=None):
        if mock is not True:
            raise RequestError("MOCK_OPT_IN_REQUIRED")
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._sessions = {}
        self._actors = {"owner": AuthenticatedActor("1" * 32), "other": AuthenticatedActor("2" * 32)}
        self._grants = {name: ResolvedAccess(actor, 1, frozenset(RequestPermission), (mock_context_binding(),))
                        for name, actor in self._actors.items()}

    def __repr__(self):
        return "MockRequestIdentity(mode='mock', sessions='volatile')"

    def _now(self):
        try:
            value = self._clock()
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError()
            return value.astimezone(timezone.utc)
        except Exception:
            raise RequestError("ACCESS_DENIED") from None

    def issue(self, principal="owner", *, lifetime_seconds=300):
        if (type(principal) is not str or principal not in self._actors or type(lifetime_seconds) is not int
                or not 1 <= lifetime_seconds <= 3600):
            raise RequestError("INVALID_ARGUMENTS")
        now = self._now()
        try:
            expires = now + timedelta(seconds=lifetime_seconds)
        except Exception:
            raise RequestError("INVALID_ARGUMENTS") from None
        context = object.__new__(AccessContext)
        self._sessions[context] = _Session(principal, self._grants[principal].generation, now, expires, now)
        return context

    def resolve(self, context):
        try:
            if type(context) is not AccessContext or context not in self._sessions:
                return None
            session = self._sessions[context]
            grant = validate_resolution(self._grants[session.principal])
            now = self._now()
            if (session.generation != grant.generation or not session.last_seen <= now < session.expires_at
                    or grant.actor != self._actors[session.principal]):
                self._sessions.pop(context, None)
                return None
            self._sessions[context] = replace(session, last_seen=now)
            return grant
        except Exception:
            if type(context) is AccessContext:
                self._sessions.pop(context, None)
            return None

    def revoke(self, context):
        if type(context) is AccessContext:
            self._sessions.pop(context, None)

    def configure(self, principal, *, permissions=None, bindings=None):
        """Trusted fixture control, never exposed through JSON or CLI identity flags."""
        if type(principal) is not str or principal not in self._grants:
            raise RequestError("INVALID_ARGUMENTS")
        old = self._grants[principal]
        new = validate_resolution(ResolvedAccess(old.actor, old.generation + 1,
                                  old.permissions if permissions is None else permissions,
                                  old.bindings if bindings is None else bindings))
        self._grants[principal] = new
