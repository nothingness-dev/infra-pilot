"""Fail-closed approval gate. Decisions authorize canonical intents, never execute."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

from .approval_store import ApprovalStore, ApprovalTransaction
from .approvals import ApprovalRequest, ApprovalState, AuditEvent, AuditKind, DecisionReason, GateDecision
from .identity import AuthenticatedActor, IdentityBoundary, Permission
from .policy import ActionCategory, ActionIntent, ActionPolicy, CanonicalAction, PolicyDecision


class _Refusal(Exception):
    def __init__(self, reason: DecisionReason) -> None:
        self.reason = reason


@dataclass
class _Context:
    now: datetime
    action: CanonicalAction | None = None
    actor: AuthenticatedActor | None = None
    request_id: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalGate:
    """Trusted server component; never construct its dependencies from Agent input.

    No default identity, policy, or store is installed. The trusted composition
    root must supply all three. Every operation requires working atomic audit
    storage; unavailable dependencies return denied decisions.
    """

    def __init__(
        self, *, identity: IdentityBoundary | None = None,
        policy: ActionPolicy | None = None, store: ApprovalStore | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._identity = identity
        self._policy = policy
        self._store = store
        self._clock = clock

    def _now(self) -> datetime:
        try:
            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Aware timestamp required")
            return now.astimezone(timezone.utc)
        except Exception:
            raise _Refusal(DecisionReason.CLOCK_UNAVAILABLE) from None

    def _classify(self, intent: ActionIntent) -> PolicyDecision:
        if self._policy is None:
            raise _Refusal(DecisionReason.POLICY_UNAVAILABLE)
        try:
            decision = self._policy.classify(intent)
            if (
                not isinstance(decision, PolicyDecision)
                or type(decision.allowed) is not bool
                or type(decision.requires_approval) is not bool
                or not isinstance(decision.category, ActionCategory)
            ):
                raise ValueError("Missing trusted decision")
            if decision.allowed and (
                not isinstance(decision.action, CanonicalAction)
                or decision.category == ActionCategory.DENIED
                or (decision.category == ActionCategory.SENSITIVE and not decision.requires_approval)
            ):
                raise ValueError("Incomplete trusted classification")
            if decision.allowed:
                # Independently check the built-in canonical allowlist. A broken
                # policy response cannot relabel restart as read-only. Installed
                # policy may deny additional operations, but cannot widen it.
                canonical = ActionPolicy.classify(self._policy, intent)
                if (
                    canonical.allowed is not True or decision.action != canonical.action
                    or decision.category != canonical.category
                    or decision.requires_approval != canonical.requires_approval
                ):
                    raise ValueError("Inconsistent trusted classification")
        except Exception:
            raise _Refusal(DecisionReason.POLICY_UNAVAILABLE) from None
        if not decision.allowed or decision.action is None:
            reasons = {
                "unsupported_action": DecisionReason.UNSUPPORTED_ACTION,
                "policy_unavailable": DecisionReason.POLICY_UNAVAILABLE,
            }
            reason = reasons.get(decision.reason, DecisionReason.INVALID_ACTION)
            raise _Refusal(reason)
        return decision

    def _actor(self, authentication: object | None, context: _Context) -> AuthenticatedActor:
        if authentication is None:
            raise _Refusal(DecisionReason.UNAUTHENTICATED)
        if self._identity is None:
            raise _Refusal(DecisionReason.IDENTITY_UNAVAILABLE)
        try:
            actor = self._identity.authenticate(authentication)
        except Exception:
            raise _Refusal(DecisionReason.IDENTITY_UNAVAILABLE) from None
        if not isinstance(actor, AuthenticatedActor):
            raise _Refusal(DecisionReason.UNAUTHENTICATED)
        context.actor = actor
        return actor

    def _permission(self, actor: AuthenticatedActor, action: CanonicalAction, permission: Permission) -> None:
        if self._identity is None:
            raise _Refusal(DecisionReason.IDENTITY_UNAVAILABLE)
        try:
            authorized = self._identity.is_authorized(actor, action, permission)
        except Exception:
            raise _Refusal(DecisionReason.AUTHORIZATION_UNAVAILABLE) from None
        if authorized is not True:
            raise _Refusal(DecisionReason.NOT_AUTHORIZED)

    @staticmethod
    def _event(context: _Context, kind: AuditKind, reason: DecisionReason) -> AuditEvent:
        action = context.action
        return AuditEvent(
            event_id=str(uuid4()), occurred_at=context.now, kind=kind, reason=reason,
            request_id=context.request_id,
            service_id=action.service_id if action else None,
            action_type=action.action_type if action else None,
            fingerprint=action.fingerprint if action else None,
            actor_id=context.actor.subject if context.actor else None,
        )

    def _run(self, operation: Callable[[ApprovalTransaction, _Context], GateDecision]) -> GateDecision:
        if self._store is None:
            return GateDecision(False, DecisionReason.STORAGE_UNAVAILABLE)
        try:
            with self._store.transaction() as transaction:
                context = _Context(self._now())
                try:
                    return operation(transaction, context)
                except _Refusal as refusal:
                    transaction.record(self._event(context, AuditKind.DENIED, refusal.reason))
                    return GateDecision(False, refusal.reason, audit_recorded=True)
        except _Refusal as refusal:
            return GateDecision(False, refusal.reason)
        except Exception:
            # No exception or credential text enters audit/results. A transaction
            # failure rolls back transitions and audit together, or denies safely
            # if a future backend's commit outcome is ambiguous.
            return GateDecision(False, DecisionReason.STORAGE_UNAVAILABLE)

    @staticmethod
    def _identifier(value: str | None, context: _Context) -> str:
        try:
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("Invalid request identifier")
        except (ValueError, AttributeError):
            raise _Refusal(DecisionReason.REQUEST_NOT_FOUND) from None
        context.request_id = value
        return value

    def _load(self, value: str | None, transaction: ApprovalTransaction, context: _Context) -> ApprovalRequest:
        identifier = self._identifier(value, context)
        request = transaction.get(identifier)
        if request is None:
            raise _Refusal(DecisionReason.REQUEST_NOT_FOUND)
        return request

    def _expire(
        self, request: ApprovalRequest, transaction: ApprovalTransaction, context: _Context,
    ) -> ApprovalRequest:
        context.now = self._now()
        if context.now < request.created_at:
            raise _Refusal(DecisionReason.CLOCK_UNAVAILABLE)
        if request.state in (ApprovalState.PENDING, ApprovalState.APPROVED) and context.now >= request.expires_at:
            request = replace(request, state=ApprovalState.EXPIRED)
            transaction.put(request)
            transaction.record(self._event(context, AuditKind.EXPIRED, DecisionReason.EXPIRED))
        return request

    @staticmethod
    def _state_refusal(request: ApprovalRequest) -> None:
        reasons = {
            ApprovalState.PENDING: DecisionReason.APPROVAL_REQUIRED,
            ApprovalState.REJECTED: DecisionReason.REJECTED,
            ApprovalState.EXPIRED: DecisionReason.EXPIRED,
            ApprovalState.CONSUMED: DecisionReason.CONSUMED,
        }
        raise _Refusal(reasons.get(request.state, DecisionReason.INVALID_STATE))

    @staticmethod
    def _intent(action: CanonicalAction) -> ActionIntent:
        return ActionIntent(
            service_id=action.service_id, action_type=action.action_type.value,
            parameters=action.parameters,
        )

    def request_approval(
        self, intent: ActionIntent, *, authentication: object | None = None,
        ttl: timedelta = timedelta(minutes=5),
    ) -> GateDecision:
        def operation(transaction: ApprovalTransaction, context: _Context) -> GateDecision:
            decision = self._classify(intent)
            action = decision.action
            assert action is not None
            actor = self._actor(authentication, context)
            self._permission(actor, action, Permission.REQUEST)
            # Only audited after a trusted authorization check recognizes the
            # target; arbitrary caller input must not become trusted audit text.
            context.action = action
            if not decision.requires_approval:
                raise _Refusal(DecisionReason.APPROVAL_NOT_REQUIRED)
            if not isinstance(ttl, timedelta) or not timedelta(0) < ttl <= timedelta(minutes=15):
                raise _Refusal(DecisionReason.INVALID_EXPIRATION)
            context.now = self._now()
            request = ApprovalRequest(
                request_id=str(uuid4()), action=action, requested_by=actor,
                created_at=context.now, expires_at=context.now + ttl,
            )
            if transaction.get(request.request_id) is not None:
                raise _Refusal(DecisionReason.STORAGE_UNAVAILABLE)
            context.request_id = request.request_id
            transaction.put(request)
            transaction.record(self._event(context, AuditKind.REQUESTED, DecisionReason.PENDING))
            return GateDecision(False, DecisionReason.PENDING, action, request, audit_recorded=True)
        return self._run(operation)

    def approve(self, request_id: str, *, authentication: object | None = None) -> GateDecision:
        return self._decide(request_id, authentication, approve=True)

    def reject(self, request_id: str, *, authentication: object | None = None) -> GateDecision:
        """Reject pending requests or revoke an approved, unconsumed request."""
        return self._decide(request_id, authentication, approve=False)

    def _decide(self, request_id: str, authentication: object | None, *, approve: bool) -> GateDecision:
        def operation(transaction: ApprovalTransaction, context: _Context) -> GateDecision:
            actor = self._actor(authentication, context)
            request = self._load(request_id, transaction, context)
            context.action = request.action
            decision = self._classify(self._intent(request.action))
            if decision.action != request.action or not decision.requires_approval:
                raise _Refusal(DecisionReason.ACTION_MISMATCH)
            self._permission(actor, request.action, Permission.APPROVE)
            if actor.subject == request.requested_by.subject:
                raise _Refusal(DecisionReason.SELF_APPROVAL)
            request = self._expire(request, transaction, context)
            valid_states = (ApprovalState.PENDING,) if approve else (ApprovalState.PENDING, ApprovalState.APPROVED)
            if request.state not in valid_states:
                self._state_refusal(request)
            if approve:
                request = replace(request, state=ApprovalState.APPROVED, approved_by=actor)
                kind, reason = AuditKind.GRANTED, DecisionReason.APPROVED
            else:
                request = replace(request, state=ApprovalState.REJECTED, rejected_by=actor)
                kind, reason = AuditKind.REJECTED, DecisionReason.REJECTED
            transaction.put(request)
            transaction.record(self._event(context, kind, reason))
            return GateDecision(False, reason, request.action, request, audit_recorded=True)
        return self._run(operation)

    def authorize(
        self, intent: ActionIntent, *, authentication: object | None = None,
        approval_request_id: str | None = None,
    ) -> GateDecision:
        """Re-evaluate policy and atomically consume approval, without execution."""
        def operation(transaction: ApprovalTransaction, context: _Context) -> GateDecision:
            decision = self._classify(intent)
            action = decision.action
            assert action is not None
            actor = self._actor(authentication, context)
            self._permission(actor, action, Permission.EXECUTE)
            context.action = action
            request: ApprovalRequest | None = None
            if decision.requires_approval:
                if approval_request_id is None:
                    raise _Refusal(DecisionReason.APPROVAL_REQUIRED)
                request = self._load(approval_request_id, transaction, context)
                if request.action != action:
                    raise _Refusal(DecisionReason.ACTION_MISMATCH)
                if request.requested_by.subject != actor.subject:
                    raise _Refusal(DecisionReason.REQUESTER_MISMATCH)
                request = self._expire(request, transaction, context)
                if request.state != ApprovalState.APPROVED:
                    self._state_refusal(request)
                if request.approved_by is None or request.approved_by.subject == actor.subject:
                    raise _Refusal(DecisionReason.INVALID_STATE)
                self._permission(request.approved_by, action, Permission.APPROVE)
                # Recheck trusted policy and time after external identity/ACL calls.
                current = self._classify(self._intent(action))
                if current.action != action or not current.requires_approval:
                    raise _Refusal(DecisionReason.ACTION_MISMATCH)
                request = self._expire(request, transaction, context)
                if request.state != ApprovalState.APPROVED:
                    self._state_refusal(request)
                request = replace(request, state=ApprovalState.CONSUMED, consumed_by=actor)
                transaction.put(request)
            elif approval_request_id is not None:
                raise _Refusal(DecisionReason.APPROVAL_NOT_REQUIRED)
            else:
                context.now = self._now()
            transaction.record(self._event(context, AuditKind.CONSUMED, DecisionReason.AUTHORIZED))
            return GateDecision(
                True, DecisionReason.AUTHORIZED, action, request,
                authorization_id=str(uuid4()), audit_recorded=True,
            )
        return self._run(operation)
