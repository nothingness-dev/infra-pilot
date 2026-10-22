"""Defense-in-depth redaction of recognizable credentials at the HTTP boundary.

This is not a general secret detector. Trusted callers must sanitize input logs
before sending them. Core diagnosis contracts and algorithms are not changed.
"""

import re

from .schemas import LogEntry, ServiceSnapshot


_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----"
)
_AUTHORIZATION = re.compile(
    r'''(?i)(["']?\bauthorization["']?\s*[:=]\s*["']?)(?:bearer|basic)\s+[^\s,;"']+'''
)
_ASSIGNMENT = re.compile(
    r'''(?i)(["']?\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\b["']?\s*[:=]\s*)'''
    r'''(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)'''
)
_URL_CREDENTIALS = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b"
)


def redact_log_message(message: str) -> str:
    message = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", message)
    message = _AUTHORIZATION.sub(r"\1[REDACTED]", message)
    message = _ASSIGNMENT.sub(r"\1[REDACTED]", message)
    message = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", message)
    return _TOKEN.sub("[REDACTED]", message)


def sanitize_snapshot(snapshot: ServiceSnapshot) -> tuple[ServiceSnapshot, bool]:
    """Copy only log messages; preserve telemetry, positions, source, and timestamps."""
    snapshot = ServiceSnapshot.model_validate(snapshot.model_dump())
    if snapshot.logs is None:
        return snapshot, False
    changed = False
    logs: list[LogEntry] = []
    for entry in snapshot.logs:
        message = redact_log_message(entry.message)
        changed = changed or message != entry.message
        logs.append(LogEntry(message=message, level=entry.level, timestamp=entry.timestamp))
    return snapshot.model_copy(update={"logs": logs}), changed
