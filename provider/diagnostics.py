"""Data-free access diagnostics over the existing client; no extra transport."""

from datetime import datetime, timezone
import time

from .models import ProviderResult, StructuredError
from .observability import _service_path

SAFE_ERROR_CODES = frozenset({
    "AUTHENTICATION_ERROR", "RATE_LIMITED", "TIMEOUT", "API_UNAVAILABLE",
    "RESOURCE_NOT_FOUND", "NETWORK_ERROR", "INVALID_RESPONSE", "INVALID_REQUEST",
    "PROVIDER_ERROR", "PARTIAL_COLLECTION", "COLLECTION_FAILED",
})


def summarize_result(result):
    """Project no data/messages; shared with the existing smoke report."""
    state, code, status, retryable = "failed", "INVALID_CLIENT_RESULT", None, None
    if isinstance(result, ProviderResult) and type(result.success) is bool:
        if result.is_mock is not False:
            code = "MOCK_RESULT"
        elif result.success:
            if result.error is None:
                state, code = ("unavailable" if result.data is None else "available"), None
        elif isinstance(result.error, StructuredError):
            error = result.error
            status = error.http_status if type(error.http_status) is int and 100 <= error.http_status <= 599 else None
            code = error.code if type(error.code) is str and error.code in SAFE_ERROR_CODES else "PROVIDER_ERROR"
            state = {401: "authentication_failed", 403: "permission_denied", 404: "not_found"}.get(status, "failed")
            retryable = error.retryable if type(error.retryable) is bool else None
    return {"status": state, "error_code": code, "http_status": status, "retryable": retryable}


def check_project_access(client, project):
    """One list call, exact project_id resolution; no IDs or raw fields exported.

    A successful listing/match is not authenticated ownership, an ACL decision
    or evidence that every capability is permitted. No target is guessed.
    """
    from .client import LiaraClient
    report = {"status": "failed", "error_code": "INVALID_REQUEST", "http_status": None,
              "retryable": None, "projects_count": None, "identifiable_projects": None,
              "target_resolved": False, "checked_at": datetime.now(timezone.utc).isoformat(),
              "duration_ms": None}
    started = time.perf_counter()
    try:
        try:
            _service_path(project)
        except ValueError:
            report.update(status="invalid_configuration", error_code="INVALID_REQUEST")
            return report
        if not isinstance(client, LiaraClient) or client.config.is_mock is not False:
            report["error_code"] = "MOCK_RESULT"
            return report
        result = client.list_projects()
        report.update(summarize_result(result))
        if report["status"] != "available":
            report["status"] = {"INVALID_RESPONSE": "invalid_response", "RATE_LIMITED": "rate_limited",
                                "TIMEOUT": "timeout", "NETWORK_ERROR": "network_error",
                                "API_UNAVAILABLE": "api_unavailable"}.get(report["error_code"], report["status"])
        else:
            # list_projects already parses the documented envelope. Resolve its
            # normalized objects, never reparse or default an absent list to [].
            projects = result.data
            if type(projects) is not list or any(type(item) is not dict for item in projects):
                raise ValueError()
            report["projects_count"] = len(projects)
            names = [item.get("project_id") for item in projects]
            report["identifiable_projects"] = sum(type(name) is str and bool(name.strip()) for name in names)
            if report["identifiable_projects"] != len(projects) or names.count(project) > 1:
                raise ValueError()
            if not projects:
                report.update(status="empty_project_list", error_code="NO_PROJECTS_VISIBLE")
            elif project not in names:
                report.update(status="target_not_listed", error_code="TARGET_NOT_LISTED")
            else:
                report.update(status="target_resolved", target_resolved=True)
    except KeyboardInterrupt:
        raise
    except (ValueError, TypeError):
        report.update(status="invalid_response", error_code="INVALID_RESPONSE")
    except Exception:
        report.update(status="failed", error_code="UNEXPECTED_ERROR")
    finally:
        report["duration_ms"] = round(max(0.0, time.perf_counter() - started) * 1000, 3)
    return report
