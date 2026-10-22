"""Provider-local projection to the team's INTERNAL DRAFT ServiceSnapshot.

No triage/framework imports, HTTP forwarding, diagnosis or authorization. Native
observations remain with the collector; only reviewed fields cross this boundary.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from typing import Literal

from .client import LiaraClient
from .models import Observation, ProviderResult, ServiceLog, ServiceObservations


LogSanitizer = Callable[[str], str | None]
_AVAILABILITY = frozenset({
    "available", "unavailable", "not_collected", "permission_denied",
    "authentication_failed", "not_found", "failed", "unsupported", "unverified",
})
_ERROR_CODES = frozenset({
    "AUTHENTICATION_ERROR", "RATE_LIMITED", "TIMEOUT", "API_UNAVAILABLE",
    "RESOURCE_NOT_FOUND", "NETWORK_ERROR", "INVALID_RESPONSE", "INVALID_REQUEST",
    "PROVIDER_ERROR", "PARTIAL_COLLECTION", "COLLECTION_FAILED",
})


@dataclass(frozen=True)
class TriageLog:
    message: str = field(repr=False)
    level: Literal["unknown"] = "unknown"
    timestamp: None = None


@dataclass(frozen=True)
class TriageSnapshot:
    """Projection of draft v0.1, not a replacement shared schema."""

    service_id: str = field(repr=False)
    data_source: Literal["real", "mock"]
    logs: tuple[TriageLog, ...] | None = field(repr=False)
    status: Literal["unknown"] = field(default="unknown", init=False)
    http_status: None = field(default=None, init=False)
    cpu_usage_percent: None = field(default=None, init=False)
    ram_usage_mib: None = field(default=None, init=False)
    response_time_ms: None = field(default=None, init=False)
    timestamp: None = field(default=None, init=False)

    def to_request(self) -> dict:
        """Detached JSON values with nulls retained and no sidecar fields."""
        result = asdict(self)
        result["logs"] = None if self.logs is None else [asdict(log) for log in self.logs]
        return result


@dataclass(frozen=True)
class CollectionSummary:
    capability: str
    availability: str
    error_code: str | None
    http_status: int | None
    collected_at: str | None


@dataclass(frozen=True)
class TriageHandoff:
    snapshot: TriageSnapshot
    capabilities: tuple[CollectionSummary, ...]
    collection_started_at: str | None
    collection_finished_at: str | None
    logs_exported: int
    logs_withheld: int
    limitations: tuple[str, ...]

    def to_dict(self) -> dict:
        """Provider sidecar; send ONLY snapshot.to_request() to /diagnose."""
        return {
            "snapshot": self.snapshot.to_request(),
            "capabilities": [asdict(item) for item in self.capabilities],
            "collection_started_at": self.collection_started_at,
            "collection_finished_at": self.collection_finished_at,
            "logs_exported": self.logs_exported,
            "logs_withheld": self.logs_withheld,
            "limitations": list(self.limitations),
        }


class TriageAdapter:
    """Read-only draft bridge over an existing LiaraClient, including its mock.

    Nonempty logs are withheld unless trusted integration code supplies an
    application-specific sanitizer. Its return value must be reviewed text or
    None (withhold entry). Exceptions/invalid returns withhold that entry safely.
    Pattern matching alone cannot guarantee removal of arbitrary app secrets.
    """

    def __init__(self, client: LiaraClient) -> None:
        self._client = client

    def _validate_options(self, service_id: str, log_sanitizer: LogSanitizer | None) -> None:
        token = self._client.config.api_key.get_secret_value()
        if (
            not isinstance(service_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", service_id) is None
            or (token and token in service_id)
            or (log_sanitizer is not None and not callable(log_sanitizer))
        ):
            raise ValueError("Invalid triage handoff options.") from None

    def _safe_time(self, value: str | None) -> str | None:
        token = self._client.config.api_key.get_secret_value()
        if not isinstance(value, str) or (token and token in value):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed.isoformat()
        except ValueError:
            pass
        return None

    def _summary(self, name: str, observation: Observation) -> CollectionSummary:
        error = observation.error
        code = None
        status = None
        if error is not None:
            code = error.code if type(error.code) is str and error.code in _ERROR_CODES else "PROVIDER_ERROR"
            if type(error.http_status) is int and 100 <= error.http_status <= 599:
                status = error.http_status
        return CollectionSummary(name, observation.availability, code, status,
                                 self._safe_time(observation.collected_at))

    def from_observations(
        self, observations: ServiceObservations, *, service_id: str,
        log_sanitizer: LogSanitizer | None = None,
    ) -> TriageHandoff:
        """Project an existing bundle, keeping availability in a separate sidecar.

        Mixed/live-as-mock origins are rejected. The explicit opaque service ID
        must come from trusted service binding; never infer it from an API name.
        No source time, metric conversion or native health mapping is invented.
        """
        self._validate_options(service_id, log_sanitizer)
        if not isinstance(observations, ServiceObservations):
            raise ValueError("Invalid provider observations.") from None
        items = (observations.service, observations.deployment, observations.logs, observations.metrics)
        origin = self._client.config.is_mock
        if type(observations.is_mock) is not bool or observations.is_mock != origin or any(
            not isinstance(item, Observation) or type(item.is_mock) is not bool
            or item.is_mock != origin or item.availability not in _AVAILABILITY
            or (item.availability == "available" and (item.data is None or item.error is not None))
            or (item.availability != "available" and item.data is not None)
            for item in items
        ):
            raise ValueError("Inconsistent provider observations.") from None

        limitations = [
            "HEALTH_STATUS_UNVERIFIED", "APPLICATION_HTTP_NOT_MEASURED",
            "CPU_RAM_UNITS_UNVERIFIED", "SOURCE_TIMESTAMPS_UNVERIFIED",
            "LOG_WINDOW_COMPLETENESS_UNVERIFIED", "DEPLOYMENT_RELEASE_FIELDS_NOT_IN_DRAFT",
        ]
        source_logs = observations.logs.data
        logs = None
        withheld = 0
        if source_logs is not None:
            if not isinstance(source_logs, list) or any(not isinstance(log, ServiceLog) for log in source_logs):
                raise ValueError("Invalid provider log observations.") from None
            exported = []
            token = self._client.config.api_key.get_secret_value()
            for log in source_logs:
                text = None
                if log_sanitizer is not None and isinstance(log.message, str):
                    try:
                        # Defense in depth before AND after the trusted callback.
                        message = log.message.replace(token, "[REDACTED]") if token else log.message
                        text = log_sanitizer(message)
                        if not isinstance(text, str):
                            text = None
                        else:
                            text = text.replace(token, "[REDACTED]") if token else text
                            text.encode("utf-8")
                    except Exception:
                        text = None
                if text is None:
                    withheld += 1
                else:
                    exported.append(TriageLog(text))
            # Only an actually empty collection is exported as [].
            if exported or not source_logs:
                logs = tuple(exported)
            if withheld:
                limitations.append("LOG_TEXT_WITHHELD" if log_sanitizer is None else "LOG_EXPORT_INCOMPLETE")
            if exported:
                limitations.append("LOG_TIME_AND_LEVEL_UNVERIFIED")
        snapshot = TriageSnapshot(service_id, "mock" if origin else "real", logs)
        summaries = tuple(self._summary(name, item) for name, item in zip(
            ("service", "deployment", "logs", "metrics"), items,
        ))
        return TriageHandoff(
            snapshot, summaries, self._safe_time(observations.collection_started_at),
            self._safe_time(observations.collection_finished_at), len(logs or ()), withheld,
            tuple(limitations),
        )

    def collect(
        self, name: str, *, service_id: str, logs_since: str | None = None,
        log_sanitizer: LogSanitizer | None = None,
    ) -> ProviderResult[TriageHandoff]:
        """Reuse the collector's up to three GETs and preserve partial results.

        success/error describe collection, not health or evidence completeness.
        Invalid integration options raise a fixed ValueError before network I/O.
        """
        self._validate_options(service_id, log_sanitizer)
        result = self._client.collect_service_observations(name, logs_since=logs_since)
        data = None if result.data is None else self.from_observations(
            result.data, service_id=service_id, log_sanitizer=log_sanitizer,
        )
        return ProviderResult(result.success, data, result.error, result.is_mock)
