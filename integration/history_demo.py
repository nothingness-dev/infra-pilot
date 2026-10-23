"""Explicit offline history demo; no credential or live-client construction."""

import argparse
import sys

from .history_errors import HistoryError, VERSION, failure
from .mock_backend import write_report


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise HistoryError("INVALID_ARGUMENTS") from None


def _arguments(argv):
    parser = _Parser(prog="python -B -m integration.history_demo", allow_abbrev=False)
    parser.add_argument("--mock", action="store_true", help="Required offline opt-in")
    parser.add_argument("--database", required=True, help="Explicit local SQLite file; keep outside Git")
    parser.add_argument("--scenario", default="partial_failure", help="Existing Mock collection scenario")
    parser.add_argument("--list", action="store_true", help="Read existing history without collecting or diagnosing")
    args = parser.parse_args(argv)
    if not args.mock:
        raise HistoryError("MOCK_OPT_IN_REQUIRED") from None
    return args


def run_demo(*, database, scenario="partial_failure", list_only=False):
    from provider.examples.context_fixtures import MOCK_CONTEXT_SCENARIOS, mock_context_binding
    from .history import SQLiteInspectionHistory
    from .service import MockSession

    if type(scenario) is not str or scenario not in MOCK_CONTEXT_SCENARIOS or type(list_only) is not bool:
        raise HistoryError("INVALID_ARGUMENTS") from None
    binding = mock_context_binding()
    with SQLiteInspectionHistory(database, create=not list_only) as history:
        saved = None if list_only else history.save(MockSession(mock=True, scenario=scenario).inspect())
    # A new connection deliberately proves persistence beyond a session object.
    with SQLiteInspectionHistory(database, create=False) as reopened:
        records = reopened.list_for(expected_binding=binding)
        if saved is not None and reopened.get(saved.record_id, expected_binding=binding) != saved:
            raise HistoryError("RECORD_CORRUPTED") from None
    return {"history_profile": VERSION, "status": "history_read" if list_only else "recorded",
            "exit_code": 0, "data_source": "mock", "history_only": True,
            "saved_record_id": saved.record_id if saved is not None else None,
            "returned_count": len(records), "records": [record.to_dict() for record in records],
            "authorization_consumed": False, "execution_authorized": False, "execution_performed": False}


def main(argv=None):
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
    except HistoryError as error:
        report = failure(error.code, 3)
    except KeyboardInterrupt:
        report = failure("INTERRUPTED", 130)
    else:
        try:
            report = run_demo(database=args.database, scenario=args.scenario, list_only=args.list)
        except ImportError:
            report = failure("DEPENDENCIES_UNAVAILABLE", 2)
        except HistoryError as error:
            report = failure(error.code, 3 if error.code == "INVALID_ARGUMENTS" else 2)
        except KeyboardInterrupt:
            report = failure("INTERRUPTED", 130)
        except Exception:
            report = failure("UNEXPECTED_ERROR", 2)
    return report["exit_code"] if write_report(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
