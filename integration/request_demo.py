"""Explicit offline request continuation CLI; help/opt-in need only stdlib."""

import argparse
import sys

from .mock_backend import write_report
from .history_errors import HistoryError
from .request_errors import RequestError, failure


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RequestError("INVALID_ARGUMENTS") from None


def _arguments(argv):
    parser = _Parser(prog="python -B -m integration.request_demo", allow_abbrev=False)
    parser.add_argument("--mock", action="store_true", help="Required offline opt-in")
    parser.add_argument("--database", required=True, help="Local request database; existing parent directory")
    parser.add_argument("command", choices=("create", "complete", "inspect", "show", "events", "history", "recover"))
    parser.add_argument("--request-id", help="Backend-generated opaque request ID")
    parser.add_argument("--key", help="Public non-secret 32 lowercase hex idempotency ID")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--target", action="store_true", help="Include configured MOCK-service fixture target")
    parser.add_argument("--goal", choices=("review", "review_again"), help="Controlled goal fixture; no free text")
    parser.add_argument("--scenario", default=None, help="Existing Mock scenario, inspect only")
    parser.add_argument("--history-database", help="Separate summary-history file, required for inspect/history")
    parser.add_argument("--limit", type=int, default=20, help="Event page size 1..100")
    parser.add_argument("--before-revision", type=int, help="Exclusive event pagination cursor")
    parser.add_argument("--revision", type=int, help="Historical summary's request revision")
    args = parser.parse_args(argv)
    if args.mock is not True:
        raise RequestError("MOCK_OPT_IN_REQUIRED")
    # Validation before heavy imports or storage initialization. Reject unused flags.
    from .request_policy import identifier, positive, SCENARIOS
    if args.command == "create":
        if args.request_id is not None or args.expected_revision is not None:
            raise RequestError("INVALID_ARGUMENTS")
    else:
        identifier(args.request_id)
    if args.command in ("create", "complete", "inspect", "recover"):
        identifier(args.key)
        if args.command != "create":
            positive(args.expected_revision)
    elif args.key is not None or args.expected_revision is not None:
        raise RequestError("INVALID_ARGUMENTS")
    if args.command not in ("create", "complete") and (args.target or args.goal is not None):
        raise RequestError("INVALID_ARGUMENTS")
    if args.command in ("inspect", "history"):
        if not args.history_database:
            raise RequestError("INVALID_ARGUMENTS")
    elif args.history_database is not None:
        raise RequestError("INVALID_ARGUMENTS")
    if args.scenario is not None and (args.command != "inspect" or args.scenario not in SCENARIOS):
        raise RequestError("INVALID_ARGUMENTS")
    if type(args.limit) is not int or not 1 <= args.limit <= 100 or (args.limit != 20 and args.command != "events"):
        raise RequestError("INVALID_ARGUMENTS")
    if args.before_revision is not None:
        positive(args.before_revision)
        if args.command != "events":
            raise RequestError("INVALID_ARGUMENTS")
    if args.revision is not None:
        positive(args.revision)
        if args.command != "history":
            raise RequestError("INVALID_ARGUMENTS")
    return args


def run(args):
    if getattr(args, "mock", False) is not True:
        raise RequestError("MOCK_OPT_IN_REQUIRED")
    from pathlib import Path
    from .history import SQLiteInspectionHistory
    from .request_policy import GOALS, TARGET
    from .request_store import SQLiteRequestStore
    from .requests import PersistentMockRequests

    if args.history_database is not None and Path(args.database).resolve() == Path(args.history_database).resolve():
        raise RequestError("INVALID_DATABASE")
    with SQLiteRequestStore(args.database, create=args.command == "create") as store:
        workflow = PersistentMockRequests(store, mock=True)
        if args.command in ("create", "complete"):
            brief = {}
            if args.target:
                brief["service_target"] = TARGET
            if args.goal is not None:
                brief["goal"] = GOALS[args.goal]
            result = (workflow.create(brief, idempotency_key=args.key) if args.command == "create" else
                      workflow.supply_information(args.request_id, brief, expected_revision=args.expected_revision, idempotency_key=args.key))
        elif args.command in ("inspect", "history"):
            with SQLiteInspectionHistory(args.history_database, create=args.command == "inspect") as history:
                result = (workflow.inspect(args.request_id, expected_revision=args.expected_revision, idempotency_key=args.key,
                                           history=history, scenario=args.scenario or "partial_failure") if args.command == "inspect" else
                          {**workflow.get(args.request_id), "historical_summary": workflow.historical_summary(args.request_id, history=history, revision=args.revision)})
        elif args.command == "events":
            result = {**workflow.get(args.request_id), "events": workflow.events(args.request_id, limit=args.limit, before_revision=args.before_revision)}
        elif args.command == "recover":
            result = workflow.recover(args.request_id, expected_revision=args.expected_revision, idempotency_key=args.key)
        else:
            result = workflow.get(args.request_id)
    return {**result, "status": "ok", "exit_code": 0}


def main(argv=None):
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
        report = run(args)
    except RequestError as error:
        invalid = {"INVALID_ARGUMENTS", "INVALID_REQUEST", "INVALID_LOOKUP", "NOT_FOUND", "MOCK_OPT_IN_REQUIRED", "INCOMPLETE_REQUEST"}
        conflicts = {"REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "RECOVERY_REQUIRED", "REINSPECTION_REQUIRED"}
        report = failure(error.code, 3 if error.code in invalid else 4 if error.code in conflicts else 2)
    except ImportError:
        report = failure("DEPENDENCIES_UNAVAILABLE", 2)
    except HistoryError:
        report = failure("HISTORY_FAILED", 2)
    except KeyboardInterrupt:
        report = failure("INTERRUPTED", 130)
    except Exception:
        report = failure("UNEXPECTED_ERROR", 2)
    try:
        return report["exit_code"] if write_report(report) else 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
