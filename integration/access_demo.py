"""Explicit offline access demonstration. Help/opt-in require only stdlib."""

import argparse
import sys

from .mock_backend import write_report
from .history_errors import HistoryError
from .request_errors import RequestError

VERSION = "infrapilot-request-access/1-mock"
SCENARIOS = ("owner_allowed", "other_owner_denied", "missing_context", "missing_permission",
             "service_scope_mismatch", "expired_context", "revoked_access",
             "restart_requires_fresh_context", "idempotency_does_not_bypass_access")


def _report(*, scenario=None, status="failed", error=None, code=2, **extra):
    return {"access_profile": VERSION, "data_source": "mock", "scenario": scenario, "status": status,
            "error_code": error, "exit_code": code, "authorization_consumed": False,
            "execution_authorized": False, "execution_performed": False, "remediation_verified": False, **extra}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RequestError("INVALID_ARGUMENTS") from None


def _arguments(argv):
    parser = _Parser(prog="python -B -m integration.access_demo", allow_abbrev=False)
    parser.add_argument("--mock", action="store_true", help="Required offline opt-in")
    parser.add_argument("--scenario", default="owner_allowed", help="Documented allowlisted Mock scenario")
    parser.add_argument("--directory", help="Existing private local directory; default temporary storage")
    parser.add_argument("--request-id", help="Non-secret prior ID, restart scenario only")
    args = parser.parse_args(argv)
    if args.mock is not True:
        raise RequestError("MOCK_OPT_IN_REQUIRED")
    if args.scenario not in SCENARIOS:
        raise RequestError("INVALID_ARGUMENTS")
    if args.scenario == "restart_requires_fresh_context":
        from .request_policy import identifier
        identifier(args.request_id)
        if args.directory is None:
            raise RequestError("INVALID_ARGUMENTS")
    elif args.request_id is not None:
        raise RequestError("INVALID_ARGUMENTS")
    return args


def run_demo(*, mock=False, scenario="owner_allowed", directory=None, request_id=None):
    if mock is not True:
        raise RequestError("MOCK_OPT_IN_REQUIRED")
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise RequestError("INVALID_ARGUMENTS")
    # Import before creating any files. No credential/environment lookup.
    from contextlib import ExitStack
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from uuid import uuid4
    from .access import ProtectedMockRequests
    from .access_identity import AccessContext, MockRequestIdentity, RequestPermission
    from .access_store import SQLiteOwnershipStore
    from .history import SQLiteInspectionHistory
    from .request_policy import GOALS, TARGET, identifier
    from .request_store import SQLiteRequestStore
    from provider.examples.context_fixtures import mock_context_binding

    restarting = scenario == "restart_requires_fresh_context"
    if restarting:
        identifier(request_id)
        if directory is None:
            raise RequestError("INVALID_ARGUMENTS")
    elif request_id is not None:
        raise RequestError("INVALID_ARGUMENTS")
    now = [datetime.now(timezone.utc)]
    with ExitStack() as stack:
        root = Path(stack.enter_context(TemporaryDirectory())) if directory is None else Path(directory)
        if not root.is_dir():
            raise RequestError("INVALID_DATABASE")
        store = stack.enter_context(SQLiteRequestStore(root / "access-requests.sqlite", create=not restarting))
        owners = stack.enter_context(SQLiteOwnershipStore(root / "access-owners.sqlite", request_store=store, create=not restarting))
        identity = MockRequestIdentity(mock=True, clock=lambda: now[0])
        backend = ProtectedMockRequests(store, owners, identity=identity, mock=True)
        owner = identity.issue()
        if restarting:
            # A new process cannot recover an old opaque handle from persisted JSON.
            try:
                backend.get(object.__new__(AccessContext), request_id)
            except RequestError as error:
                if error.code != "ACCESS_DENIED":
                    raise
            else:
                raise RequestError("UNEXPECTED_ERROR")
            result = backend.get(owner, request_id)
            return _report(scenario=scenario, status="fresh_context_resolved", code=0,
                           request_id=request_id, request_revision=result["request"]["revision"],
                           fresh_context_required=True, reinspection_required=result["reinspection_required"],
                           retained_evidence_available=result["retained_evidence_available"])
        creation_key = uuid4().hex
        created = backend.create(owner, {"service_target": TARGET}, idempotency_key=creation_key)
        request_id = created["request"]["request_id"]
        if scenario == "owner_allowed":
            backend.supply_information(owner, request_id, {"goal": GOALS["review"]}, expected_revision=1, idempotency_key=uuid4().hex)
            history = stack.enter_context(SQLiteInspectionHistory(root / "access-history.sqlite"))
            result = backend.inspect(owner, request_id, expected_revision=2, idempotency_key=uuid4().hex, history=history)
            return _report(scenario=scenario, status="allowed", code=0, request_id=request_id,
                           request_revision=result["request"]["revision"],
                           retained_evidence_available=result["retained_evidence_available"],
                           historical_summary=backend.historical_summary(owner, request_id, history=history))
        context = owner
        if scenario == "other_owner_denied":
            context = identity.issue("other")
        elif scenario == "missing_context":
            context = None
        elif scenario == "missing_permission":
            identity.configure("owner", permissions=frozenset({RequestPermission.CREATE}))
            context = identity.issue()
        elif scenario == "service_scope_mismatch":
            identity.configure("owner", bindings=(replace(mock_context_binding(), provider_scope="other"),))
            context = identity.issue()
        elif scenario == "expired_context":
            now[0] += timedelta(seconds=301)
        else:
            identity.revoke(owner)
        try:
            if scenario == "idempotency_does_not_bypass_access":
                backend.create(context, {"service_target": TARGET}, idempotency_key=creation_key)
            else:
                backend.get(context, request_id)
        except RequestError as error:
            if error.code == "ACCESS_DENIED":
                return _report(scenario=scenario, status="denied", error="ACCESS_DENIED", code=4)
            raise
        raise RequestError("UNEXPECTED_ERROR")


def main(argv=None):
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
        report = run_demo(mock=args.mock, scenario=args.scenario, directory=args.directory, request_id=args.request_id)
    except RequestError as error:
        code = 4 if error.code == "ACCESS_DENIED" else 3 if error.code in ("INVALID_ARGUMENTS", "INVALID_LOOKUP", "MOCK_OPT_IN_REQUIRED") else 2
        report = _report(error=error.code, code=code)
    except ImportError:
        report = _report(error="DEPENDENCIES_UNAVAILABLE")
    except HistoryError:
        report = _report(error="HISTORY_FAILED")
    except KeyboardInterrupt:
        report = _report(error="INTERRUPTED", code=130)
    except Exception:
        report = _report(error="UNEXPECTED_ERROR")
    try:
        return report["exit_code"] if write_report(report) else 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
