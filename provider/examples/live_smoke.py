"""Read-only Liara access checks with an allowlisted, data-free JSON report.

Run from the repository root: python -B -m provider.examples.live_smoke
Configuration is environment-only. Importing this module has no side effects.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import sys
import time
from typing import Any

from provider import LiaraClient, ProviderConfig, ProviderResult, StructuredError
from provider.observability import _service_path


EXIT_SUCCESS = 0
EXIT_PARTIAL = 1
EXIT_FAILED = 2
EXIT_INVALID_CONFIGURATION = 3
EXIT_INTERRUPTED = 130

_CAPABILITIES = ("service", "deployment", "logs", "metrics", "releases")
_ERROR_CODES = frozenset({
    "AUTHENTICATION_ERROR", "RATE_LIMITED", "TIMEOUT", "API_UNAVAILABLE",
    "RESOURCE_NOT_FOUND", "NETWORK_ERROR", "INVALID_RESPONSE", "INVALID_REQUEST",
    "PROVIDER_ERROR", "PARTIAL_COLLECTION", "COLLECTION_FAILED",
})


@dataclass(frozen=True)
class _Settings:
    config: ProviderConfig
    project: str = field(repr=False)
    logs_since: str | None = field(repr=False)


def _settings(environment: Mapping[str, str]) -> _Settings:
    """Validate everything before constructing a client or making requests."""
    token = environment.get("LIARA_API_TOKEN")
    project = environment.get("LIARA_PROJECT_NAME")
    # Reuse the adapter's name validation and path encoding, without transport.
    _service_path(project)
    since = environment.get("LIARA_LOGS_SINCE")
    if since is not None:
        if not isinstance(since, str) or not since.strip():
            raise ValueError("Invalid log window setting.")
        since.encode("utf-8")
    options = {}
    if "LIARA_API_BASE_URL" in environment:
        options["base_url"] = environment["LIARA_API_BASE_URL"]
    if "LIARA_TIMEOUT_SECONDS" in environment:
        options["timeout"] = float(environment["LIARA_TIMEOUT_SECONDS"])
    return _Settings(ProviderConfig(api_key=token, **options), project, since)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary(result: ProviderResult) -> tuple[str, str | None, int | None]:
    """Never serialize provider data, error messages, or unrecognized codes."""
    if not isinstance(result, ProviderResult) or type(result.success) is not bool:
        return "failed", "INVALID_CLIENT_RESULT", None
    if result.is_mock is not False:
        return "failed", "MOCK_RESULT", None
    if result.success:
        if result.error is not None:
            return "failed", "INVALID_CLIENT_RESULT", None
        return ("unavailable" if result.data is None else "available"), None, None
    error = result.error
    if not isinstance(error, StructuredError):
        return "failed", "INVALID_CLIENT_RESULT", None
    status = error.http_status
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    code = error.code if type(error.code) is str and error.code in _ERROR_CODES else "PROVIDER_ERROR"
    state = {401: "authentication_failed", 403: "permission_denied", 404: "not_found"}.get(status, "failed")
    return state, code, status


def _report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = [check for check in checks if check["status"] != "skipped"]
    available = sum(check["status"] == "available" for check in attempted)
    if attempted and available == len(attempted):
        status, code = "complete", EXIT_SUCCESS
    elif available:
        status, code = "partial", EXIT_PARTIAL
    else:
        status, code = "failed", EXIT_FAILED
    return {"status": status, "exit_code": code, "checks": checks}


def _global_failure(status: str, code: int, error_code: str) -> dict[str, Any]:
    return {"status": status, "exit_code": code, "error_code": error_code, "checks": []}


def run_checks(client: LiaraClient, project: str, logs_since: str | None) -> dict[str, Any]:
    """Summarize five independent adapter calls; never probe application URLs.

    A successful access check describes this account/project at this instant,
    not general API support or application health. Skipped logs do not count
    as a failure. The adapter alone interprets response payloads.
    """
    checks = []
    calls = (
        lambda: client.get_service(project),
        lambda: client.get_deployment_status(project),
        lambda: client.get_logs(project, since=logs_since),
        lambda: client.get_metrics(project),
        lambda: client.list_releases(project),
    )
    for capability, call in zip(_CAPABILITIES, calls):
        if capability == "logs" and logs_since is None:
            checks.append({
                "capability": capability, "status": "skipped", "error_code": None,
                "http_status": None, "checked_at": _now(), "duration_ms": None,
            })
            continue
        started = time.perf_counter()
        try:
            state, error_code, http_status = _summary(call())
        except KeyboardInterrupt:
            # The CLI boundary produces a fixed report without a traceback.
            raise
        except Exception:
            # Unexpected client failures must neither leak diagnostics nor stop
            # the remaining checks. Ordinary provider failures are results.
            state, error_code, http_status = "failed", "UNEXPECTED_ERROR", None
        duration = max(0.0, (time.perf_counter() - started) * 1000)
        checks.append({
            "capability": capability, "status": state, "error_code": error_code,
            "http_status": http_status, "checked_at": _now(),
            "duration_ms": round(duration, 3),
        })
    return _report(checks)


def run_from_environment(environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Execute only with valid environment settings; no files or prompts."""
    try:
        settings = _settings(os.environ if environment is None else environment)
    except (ValueError, TypeError, OverflowError):
        return _global_failure("invalid_configuration", EXIT_INVALID_CONFIGURATION, "INVALID_CONFIGURATION")
    try:
        client = LiaraClient(settings.config)
    except Exception:
        return _global_failure("failed", EXIT_FAILED, "CLIENT_INITIALIZATION_FAILED")
    return run_checks(client, settings.project, settings.logs_since)


def main(argv: Sequence[str] | None = None) -> int:
    """Emit one JSON object to stdout and no raw exception diagnostics."""
    try:
        arguments = sys.argv[1:] if argv is None else argv
        if arguments:
            report = _global_failure("invalid_configuration", EXIT_INVALID_CONFIGURATION, "INVALID_CONFIGURATION")
        else:
            report = run_from_environment()
    except KeyboardInterrupt:
        report = _global_failure("interrupted", EXIT_INTERRUPTED, "INTERRUPTED")
    except Exception:
        report = _global_failure("failed", EXIT_FAILED, "UNEXPECTED_ERROR")
    try:
        print(json.dumps(report, allow_nan=False, sort_keys=True), flush=True)
    except OSError:
        # Force buffered failures into this boundary. Redirect the failed OS
        # descriptor to the null device so interpreter shutdown cannot retry a
        # buffered write and print a diagnostic (EINVAL on Windows, EPIPE on Unix).
        try:
            descriptor = sys.stdout.fileno()
            with open(os.devnull, "w") as sink:
                os.dup2(sink.fileno(), descriptor)
        except (AttributeError, OSError, ValueError):
            pass
        return EXIT_FAILED
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
