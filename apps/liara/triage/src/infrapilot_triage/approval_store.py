"""Atomic process-local approval/audit storage for one-process MVPs only."""

from contextlib import contextmanager
from threading import RLock, local
from typing import ContextManager, Iterator, Protocol

from .approvals import ApprovalRequest, AuditEvent


class StoreUnavailable(RuntimeError):
    pass


class ApprovalTransaction(Protocol):
    def get(self, request_id: str) -> ApprovalRequest | None: ...
    def put(self, request: ApprovalRequest) -> None: ...
    def record(self, event: AuditEvent) -> None: ...


class ApprovalStore(Protocol):
    def transaction(self) -> ContextManager[ApprovalTransaction]: ...


class _MemoryTransaction:
    def __init__(self, requests: dict[str, ApprovalRequest], events: list[AuditEvent]) -> None:
        self.requests = requests
        self.events = events

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self.requests.get(request_id)

    def put(self, request: ApprovalRequest) -> None:
        self.requests[request.request_id] = request

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class InMemoryApprovalStore:
    """Lock and copy-on-write commit keep state and audit events atomic.

    Transactions are a trusted server port, not an Agent-facing mutation API.
    This store cannot coordinate multiple processes and loses data on restart.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._thread = local()
        self._requests: dict[str, ApprovalRequest] = {}
        self._events: list[AuditEvent] = []

    @contextmanager
    def transaction(self) -> Iterator[ApprovalTransaction]:
        with self._lock:
            if getattr(self._thread, "active", False):
                raise StoreUnavailable("Nested approval transactions are unsupported")
            self._thread.active = True
            try:
                transaction = _MemoryTransaction(dict(self._requests), list(self._events))
                yield transaction
                # Prepare both copies before commit and detach retained handles.
                self._requests, self._events = dict(transaction.requests), list(transaction.events)
            finally:
                self._thread.active = False

    def get(self, request_id: str) -> ApprovalRequest | None:
        """Immutable administrative snapshot; reads do not advance expiration."""
        with self._lock:
            return self._requests.get(request_id)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)
