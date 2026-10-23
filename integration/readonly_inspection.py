"""python -B -m integration.readonly_inspection --live-read-only

No arguments contain settings; importing/help/invalid opt-in constructs nothing.
"""

import sys
import argparse

from .mock_backend import write_report
from .readonly_report import ReadOnlyError, empty_summary


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ReadOnlyError("INVALID_ARGUMENTS") from None


def main(argv=None):
    verifying = False
    try:
        args = sys.argv[1:] if argv is None else list(argv)
        if args == ["--help"]:
            print("Usage: python -B -m integration.readonly_inspection --live-read-only\n"
                  "       add --verify-access [--history-database PATH] for exact project-list verification.\n"
                  "Settings: process environment only. No infrastructure changes.")
            return 0
        parser = _Parser(add_help=False, allow_abbrev=False)
        parser.add_argument("--live-read-only", action="store_true")
        parser.add_argument("--verify-access", action="store_true")
        parser.add_argument("--history-database")
        names = [arg.split("=", 1)[0] for arg in args]
        if any(names.count(option) > 1 for option in
               ("--live-read-only", "--verify-access", "--history-database")):
            raise ReadOnlyError("INVALID_ARGUMENTS")
        parsed = parser.parse_args(args)
        if not parsed.live_read_only:
            raise ReadOnlyError("LIVE_OPT_IN_REQUIRED")
        if parsed.history_database is not None and not parsed.verify_access:
            raise ReadOnlyError("INVALID_ARGUMENTS")
        verifying = parsed.verify_access
        if verifying:
            from .live_verification import run_verification
            report = run_verification(live_read_only=True, history_database=parsed.history_database)
        else:
            from .readonly import run_readonly_inspection
            report = run_readonly_inspection(live_read_only=True).summary()
    except ReadOnlyError as error:
        report = empty_summary(code=3, error=error.code, stage="configuration")
    except ImportError:
        report = empty_summary(error="DEPENDENCIES_UNAVAILABLE")
    except KeyboardInterrupt:
        report = empty_summary(code=130, error="INTERRUPTED", stage="interrupted")
    except Exception:
        report = empty_summary(error="UNEXPECTED_ERROR")
    try:
        return report["exit_code"] if write_report(report) else 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
