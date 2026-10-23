"""Operator-local live verification; no production login/ACL or application probe."""

from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.parse import urlsplit

from provider import LiaraClient
from provider.diagnostics import check_project_access, summarize_result
from .history import SQLiteInspectionHistory
from .history_errors import HistoryError
from .readonly import inspect_with_client
from .readonly_config import read_inspection_settings
from .readonly_report import ReadOnlyError

PROFILE = "infrapilot-live-readonly-verification/1"


def empty_report(*, error=None, code=2):
    return {"verification_profile": PROFILE, "status": "failed", "exit_code": code,
            "error_code": error, "observed_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "real", "api_host": None, "account_scope": None,
            "project_access": None, "inspection": None, "releases": None,
            "history": {"status": "not_requested", "record_id": None},
            "identity_verified": False, "freshness_evaluated": False,
            "authorization_consumed": False, "execution_authorized": False,
            "execution_performed": False, "remediation_verified": False}


def run_verification(*, live_read_only=False, environment=None, history_database=None):
    if live_read_only is not True:
        raise ReadOnlyError("LIVE_OPT_IN_REQUIRED")
    if environment is None:
        import os
        environment = os.environ
    settings = read_inspection_settings(environment)
    # No automatic host fallback or credential forwarding to arbitrary origins.
    parts = urlsplit(settings.live.config.base_url)
    if (parts.hostname not in ("api.liara.ir", "api.iran.liara.ir") or parts.path
            or parts.port not in (None, 443)):
        raise ReadOnlyError("INVALID_CONFIGURATION")
    if history_database is not None:
        try:
            location = Path(history_database)
            if (location.is_symlink() or not location.parent.is_dir()
                    or settings.live.config.api_key.get_secret_value() in str(location)):
                raise ValueError()
        except Exception:
            raise ReadOnlyError("INVALID_CONFIGURATION") from None
    report = empty_report()
    scope = settings.live.config.team_id
    report.update(api_host=parts.hostname, account_scope="unspecified" if scope is None else "personal" if scope == "" else "team")
    if history_database is not None:
        report["history"]["status"] = "not_collected"
    client = LiaraClient(settings.live.config)
    report["project_access"] = check_project_access(client, settings.live.project)
    if not report["project_access"]["target_resolved"]:
        report.update(status="blocked", error_code=report["project_access"]["error_code"])
        return report
    # Same client, independently selected original binding and existing pipeline.
    inspection = inspect_with_client(client, settings)
    report["inspection"] = inspection.summary()
    if report["inspection"]["exit_code"] == 130:
        report.update(error_code="INTERRUPTED", exit_code=130)
        return report
    started = time.perf_counter()
    interrupted = False
    try:
        report["releases"] = summarize_result(client.list_releases(settings.live.project))
    except KeyboardInterrupt:
        interrupted = True
        report["releases"] = {"status": "interrupted", "error_code": "INTERRUPTED", "http_status": None, "retryable": None}
    except Exception:
        report["releases"] = {"status": "failed", "error_code": "UNEXPECTED_ERROR", "http_status": None, "retryable": None}
    report["releases"]["duration_ms"] = round(max(0.0, time.perf_counter() - started) * 1000, 3)
    if interrupted:
        report.update(error_code="INTERRUPTED", exit_code=130)
        return report
    if history_database is not None:
        try:
            with SQLiteInspectionHistory(history_database) as history:
                saved = history.save(inspection)
                if history.get(saved.record_id, expected_binding=settings.binding) != saved:
                    raise HistoryError("RECORD_CORRUPTED")
                report["history"] = {"status": "recorded", "record_id": saved.record_id}
        except KeyboardInterrupt:
            report["history"]["status"] = "interrupted"
            report.update(error_code="INTERRUPTED", exit_code=130)
            return report
        except Exception:
            report["history"]["status"] = "failed"
            report["error_code"] = "HISTORY_FAILED"
            return report  # Preserve valid earlier summaries; never claim persisted.
    detail = report["inspection"]
    if detail["stage"] != "complete" or detail["error_code"] is not None:
        report["error_code"] = detail["error_code"]
        return report
    attempted = [item["availability"] for item in detail["capabilities"] if item["availability"] != "not_collected"]
    attempted.append(report["releases"]["status"])
    available = sum(state == "available" for state in attempted)
    if available == len(attempted):
        report.update(status="complete", exit_code=0)
    elif available:
        report.update(status="partial", exit_code=1)
    else:
        report.update(status="failed", exit_code=2)
    return report
