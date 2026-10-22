"""EXPERIMENTAL provider-local Draft v0.2; no shared endpoint is implemented.

The retained PreparedCollection is a trusted backend comparison reference, NOT
an authorization token. Digests/source labels alone do not authenticate input.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import re

from .client import LiaraClient
from .exceptions import CollectionContextError
from .models import ProviderResult, ServiceObservations
from .observability import _service_path
from .triage import LogSanitizer, TriageAdapter, TriageHandoff


COLLECTION_CONTEXT_VERSION = "provider-collection-context/0.2-draft"
MAX_COLLECTION_CONTEXT_BYTES = 4 * 1024 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def _identifier(value: str) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _canonical(value: dict) -> bytes:
    """Bounded, deterministic, finite JSON. Never echo an invalid input."""
    if type(value) is not dict:
        raise CollectionContextError() from None
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    size = 0
    chunks = []
    try:
        for chunk in encoder.iterencode(value):
            size += len(chunk)
            if size > MAX_COLLECTION_CONTEXT_BYTES:
                raise CollectionContextError()
            chunks.append(chunk)
        return "".join(chunks).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise CollectionContextError() from None


@dataclass(frozen=True)
class ServiceBinding:
    """Operator-supplied exact mapping, not frontend claims or account proof.

    provider_scope is an opaque local namespace selecting a trusted client/account
    configuration. No token, credential object or application URL belongs here.
    """

    service_id: str = field(repr=False)
    project_name: str = field(repr=False)
    provider_scope: str = field(repr=False)
    is_mock: bool

    def __post_init__(self) -> None:
        try:
            if not _identifier(self.service_id) or not _identifier(self.provider_scope) or type(self.is_mock) is not bool:
                raise ValueError()
            _service_path(self.project_name)
        except (TypeError, ValueError):
            raise CollectionContextError() from None


@dataclass(frozen=True, init=False)
class PreparedCollection:
    """Retain internally until consuming a submitted context; never deserialize it.

    verify_request compares the complete snapshot AND context to this retained
    reference and the independently selected trusted binding. It does not check
    identity, ACLs, storage integrity, retention/freshness, or grant execution.
    """

    _binding: ServiceBinding = field(repr=False)
    _canonical_request: bytes = field(repr=False)

    def __new__(cls):
        raise CollectionContextError() from None

    def to_request(self) -> dict:
        """Detached proposed envelope; not accepted by the current diagnosis API."""
        return json.loads(self._canonical_request)

    def verify_request(self, request: dict, *, expected_binding: ServiceBinding) -> dict:
        """Fail closed on changes, including recomputed hashes, extra fields or origin."""
        if not isinstance(expected_binding, ServiceBinding) or expected_binding != self._binding:
            raise CollectionContextError() from None
        if _canonical(request) != self._canonical_request:
            raise CollectionContextError() from None
        return self.to_request()


def _context(handoff: TriageHandoff) -> dict:
    snapshot = handoff.snapshot.to_request()
    capability = next(item for item in handoff.capabilities if item.capability == "logs")
    received = None
    if capability.availability == "available":
        received = handoff.logs_exported + handoff.logs_withheld
        state = "empty" if received == 0 else (
            "withheld" if handoff.logs_exported == 0 else (
                "partial" if handoff.logs_withheld else "exported"
            )
        )
    else:
        state = {
            "not_collected": "not_collected", "unavailable": "unavailable",
            "unverified": "unverified", "unsupported": "unsupported",
        }.get(capability.availability, "collection_failed")
    context = {
        "contract_version": COLLECTION_CONTEXT_VERSION,
        "service_id": snapshot["service_id"],
        "data_source": snapshot["data_source"],
        "snapshot_digest": "sha256:" + hashlib.sha256(_canonical(snapshot)).hexdigest(),
        "collection_started_at": handoff.collection_started_at,
        "collection_finished_at": handoff.collection_finished_at,
        "capabilities": [asdict(item) for item in handoff.capabilities],
        "log_export": {
            "state": state, "received": received,
            "exported": handoff.logs_exported, "withheld": handoff.logs_withheld,
        },
        "limitations": list(handoff.limitations),
    }
    # These are collector instants, not source freshness or log-window claims.
    start, finish = handoff.collection_started_at, handoff.collection_finished_at
    if start is not None and finish is not None:
        lower, upper = datetime.fromisoformat(start), datetime.fromisoformat(finish)
        if lower > upper or any(
            item.collected_at is not None
            and not lower <= datetime.fromisoformat(item.collected_at) <= upper
            for item in handoff.capabilities
        ):
            raise CollectionContextError() from None
    return {"snapshot": snapshot, "collection_context": context}


class CollectionContextAdapter:
    """Opt-in draft producer using an existing read-only collector and normalizer.

    The operator supplies the binding and client scope from trusted server
    configuration. No registry, authentication backend, API route or transport to
    triage is installed. Use mock data until the team approves this proposal.
    """

    def __init__(self, client: LiaraClient, *, provider_scope: str) -> None:
        self._client = client
        self._adapter = TriageAdapter(client)
        token = client.config.api_key.get_secret_value()
        if not _identifier(provider_scope) or (token and token in provider_scope):
            raise CollectionContextError() from None
        self._scope = provider_scope

    def _validate_binding(self, binding: ServiceBinding, log_sanitizer: LogSanitizer | None) -> None:
        token = self._client.config.api_key.get_secret_value()
        if (
            not isinstance(binding, ServiceBinding)
            or binding.provider_scope != self._scope
            or binding.is_mock != self._client.config.is_mock
            or (token and any(token in value for value in (
                binding.service_id, binding.project_name, binding.provider_scope,
            )))
        ):
            raise CollectionContextError() from None
        self._adapter._validate_options(binding.service_id, log_sanitizer)

    def from_observations(
        self, observations: ServiceObservations, *, binding: ServiceBinding,
        log_sanitizer: LogSanitizer | None = None,
    ) -> PreparedCollection:
        """Bind a trusted bundle before exporting; no credentials or raw metadata."""
        self._validate_binding(binding, log_sanitizer)
        if not isinstance(observations, ServiceObservations) or observations.service_name != binding.project_name:
            raise CollectionContextError() from None
        try:
            handoff = self._adapter.from_observations(
                observations, service_id=binding.service_id, log_sanitizer=log_sanitizer,
            )
        except ValueError:
            raise CollectionContextError() from None
        result = object.__new__(PreparedCollection)
        object.__setattr__(result, "_binding", binding)
        object.__setattr__(result, "_canonical_request", _canonical(_context(handoff)))
        return result

    def collect(
        self, binding: ServiceBinding, *, logs_since: str | None = None,
        log_sanitizer: LogSanitizer | None = None,
    ) -> ProviderResult[PreparedCollection]:
        """At most three existing GETs. Keep valid partial data; never retry/submit."""
        self._validate_binding(binding, log_sanitizer)
        result = self._client.collect_service_observations(binding.project_name, logs_since=logs_since)
        if result.data is None:
            return result
        try:
            if result.is_mock is not self._client.config.is_mock:
                raise CollectionContextError()
            data = self.from_observations(result.data, binding=binding, log_sanitizer=log_sanitizer)
        except CollectionContextError as error:
            return ProviderResult(False, None, error.to_error(), self._client.config.is_mock)
        return ProviderResult(result.success, data, result.error, result.is_mock)
