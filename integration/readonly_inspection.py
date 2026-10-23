"""python -B -m integration.readonly_inspection --live-read-only

No arguments contain settings; importing/help/invalid opt-in constructs nothing.
"""

import sys

from .mock_backend import write_report
from .readonly_report import ReadOnlyError, empty_summary


def main(argv=None):
    try:
        args = sys.argv[1:] if argv is None else list(argv)
        if args == ["--help"]:
            print("Usage: python -B -m integration.readonly_inspection --live-read-only\n"
                  "Settings: process environment only. No infrastructure changes.")
            return 0
        if args != ["--live-read-only"]:
            raise ReadOnlyError("LIVE_OPT_IN_REQUIRED" if not args else "INVALID_ARGUMENTS")
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
    return report["exit_code"] if write_report(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
