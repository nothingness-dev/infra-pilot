"""Extract observations and explicit symptom signals without diagnosing causes."""

from dataclasses import dataclass
from enum import Enum
import json
from math import isfinite
import re

from .schemas import Evidence, EvidenceKind, LogLevel, ServiceSnapshot, ServiceStatus


@dataclass(frozen=True)
class DiagnosisThresholds:
    """Heuristic thresholds, not provider limits or utilization guarantees."""

    high_cpu_percent: float = 85.0
    high_ram_mib: float = 1024.0
    slow_response_ms: float = 1000.0

    def __post_init__(self) -> None:
        for name in ("high_cpu_percent", "high_ram_mib", "slow_response_ms"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        if self.high_cpu_percent > 100:
            raise ValueError("high_cpu_percent must not exceed 100")


class Symptom(str, Enum):
    HTTP_SERVER_ERROR = "http_server_error"
    DATABASE_CONNECTION_FAILURE = "database_connection_failure"
    HIGH_CPU = "high_cpu"
    HIGH_RAM = "high_ram"
    SLOW_RESPONSE = "slow_response"
    OUT_OF_MEMORY = "out_of_memory"
    APPLICATION_ERROR = "application_error"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class SymptomSignal:
    symptom: Symptom
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedSymptoms:
    """Internal extraction result; not a replacement integration contract."""

    snapshot: ServiceSnapshot
    evidence: tuple[Evidence, ...]
    signals: tuple[SymptomSignal, ...]
    missing_information: tuple[str, ...]
    limitations: tuple[str, ...]

    def has(self, symptom: Symptom) -> bool:
        return any(signal.symptom == symptom for signal in self.signals)

    def supporting_ids(self, *symptoms: Symptom) -> tuple[str, ...]:
        selected = {
            identifier
            for signal in self.signals
            if signal.symptom in symptoms
            for identifier in signal.evidence_ids
        }
        return tuple(item.evidence_id for item in self.evidence if item.evidence_id in selected)


_DATABASE = re.compile(
    r"\b(?:database|postgres(?:ql)?|mysql|mariadb|mongodb|redis|sqlalchemy|psycopg[23]?|sqlite3)\b",
    re.IGNORECASE,
)
_CONNECTION_FAILURE = re.compile(
    r"\b(?:connection (?:refused|failed|failure|error|reset|timed out|timeout)"
    r"|could not connect|cannot connect|unable to connect|failed to connect"
    r"|connection pool (?:is )?exhausted|too many connections"
    r"|password authentication failed|econnrefused|etimedout|unavailable)\b",
    re.IGNORECASE,
)
_OOM = re.compile(
    r"\b(?:oomkilled|oom|out[- ]of[- ]memory|cannot allocate memory|memoryerror)\b",
    re.IGNORECASE,
)
_APPLICATION_ERROR = re.compile(
    r"\b(?:exception|traceback|internal server error|unhandled error)\b", re.IGNORECASE
)
_NEGATED_PREFIX = re.compile(r"\b(?:no|not|without)\s+(?:\w+\s+){0,3}$", re.IGNORECASE)
_NEGATED_SUFFIX = re.compile(r"^\s*(?:[:=]\s*)?(?:false|0|not detected)\b", re.IGNORECASE)


def _positive_match(pattern: re.Pattern[str], message: str) -> bool:
    """Avoid a few explicit negations; this is deliberately not a language parser."""
    return any(
        not _NEGATED_PREFIX.search(message[max(0, match.start() - 48):match.start()])
        and not _NEGATED_SUFFIX.search(message[match.end():])
        for match in pattern.finditer(message)
    )


def extract_symptoms(
    snapshot: ServiceSnapshot, *, thresholds: DiagnosisThresholds | None = None,
) -> ExtractedSymptoms:
    """Copy/revalidate input, retain real observations, and flag explicit signals."""
    if not isinstance(snapshot, ServiceSnapshot):
        raise TypeError("snapshot must be a ServiceSnapshot")
    snapshot = ServiceSnapshot.model_validate(snapshot.model_dump())
    thresholds = thresholds if thresholds is not None else DiagnosisThresholds()
    evidence: list[Evidence] = []
    signals: dict[Symptom, list[str]] = {}
    missing: list[str] = []
    limitations: list[str] = []

    def observe(identifier: str, kind: EvidenceKind, description: str) -> None:
        evidence.append(Evidence(evidence_id=identifier, kind=kind, description=description))

    def flag(symptom: Symptom, identifier: str) -> None:
        signals.setdefault(symptom, []).append(identifier)

    observe("service-status", EvidenceKind.STATUS, f"Reported service status: {snapshot.status.value}.")
    if snapshot.status == ServiceStatus.UNKNOWN:
        missing.append("Service health is unknown.")
    elif snapshot.status == ServiceStatus.UNHEALTHY:
        flag(Symptom.UNHEALTHY, "service-status")
    elif snapshot.status == ServiceStatus.DEGRADED:
        flag(Symptom.DEGRADED, "service-status")

    if snapshot.http_status is None:
        missing.append("HTTP status is unavailable.")
    else:
        observe("http-status", EvidenceKind.HTTP, f"Observed HTTP status: {snapshot.http_status}.")
        if snapshot.http_status >= 500:
            flag(Symptom.HTTP_SERVER_ERROR, "http-status")

    measurements = (
        ("cpu_usage_percent", "cpu-usage", "CPU usage", "%", thresholds.high_cpu_percent, Symptom.HIGH_CPU),
        ("ram_usage_mib", "ram-usage", "RAM usage", "MiB", thresholds.high_ram_mib, Symptom.HIGH_RAM),
        ("response_time_ms", "response-time", "Response time", "ms", thresholds.slow_response_ms, Symptom.SLOW_RESPONSE),
    )
    for field, identifier, label, unit, threshold, symptom in measurements:
        value = getattr(snapshot, field)
        if value is None:
            missing.append(f"{label} measurement is unavailable.")
        else:
            observe(identifier, EvidenceKind.METRIC, f"Observed {label.lower()}: {value:g} {unit}.")
            if value >= threshold:
                flag(symptom, identifier)

    if snapshot.logs is None:
        missing.append("Service logs are unavailable (not collected or not supplied).")
    elif not snapshot.logs:
        limitations.append("The collected log collection is empty; no application failure details are available.")
    else:
        limitations.append("Log window and completeness are unknown; supplied entries may be partial or historical.")
        blank_entries = False
        for index, entry in enumerate(snapshot.logs, start=1):
            if not entry.message.strip():
                blank_entries = True
                continue
            identifier = f"log-{index:04d}"
            # Quoting preserves whitespace through Evidence.description's trimming.
            message = json.dumps(entry.message, ensure_ascii=False)
            observe(identifier, EvidenceKind.LOG, f"Log entry {index} ({entry.level.value}): {message}")
            database_failure = bool(_DATABASE.search(entry.message)) and _positive_match(_CONNECTION_FAILURE, entry.message)
            oom = _positive_match(_OOM, entry.message)
            if database_failure:
                flag(Symptom.DATABASE_CONNECTION_FAILURE, identifier)
            if oom:
                flag(Symptom.OUT_OF_MEMORY, identifier)
            if not database_failure and not oom and (
                entry.level in (LogLevel.ERROR, LogLevel.CRITICAL)
                or _positive_match(_APPLICATION_ERROR, entry.message)
            ):
                flag(Symptom.APPLICATION_ERROR, identifier)
        if blank_entries:
            limitations.append("Some supplied log entries are blank and provide no diagnostic content.")

    if snapshot.timestamp is None:
        missing.append("Snapshot timestamp is unavailable; observation freshness cannot be assessed.")
    limitations.append("RAM usage is an absolute MiB value; memory limit and utilization are unavailable.")
    return ExtractedSymptoms(
        snapshot=snapshot,
        evidence=tuple(evidence),
        signals=tuple(SymptomSignal(symptom, tuple(ids)) for symptom, ids in signals.items()),
        missing_information=tuple(missing),
        limitations=tuple(limitations),
    )
