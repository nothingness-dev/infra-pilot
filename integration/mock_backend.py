"""Safe CLI: python -B -m integration.mock_backend --mock --scenario partial_failure."""

import argparse
import json
import os
import sys

from .errors import MockIntegrationError, failure


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse diagnostics otherwise echo unrecognized arguments/values.
        raise MockIntegrationError("INVALID_ARGUMENTS") from None


def _arguments(argv):
    parser = _Parser(prog="python -B -m integration.mock_backend", allow_abbrev=False)
    parser.add_argument("--mock", action="store_true", help="Required explicit offline opt-in")
    parser.add_argument("--scenario", default="partial_failure", help="One documented mock collection scenario")
    parser.add_argument("--service", default="MOCK-service", help="Configured mock service alias")
    args = parser.parse_args(argv)
    if not args.mock:
        raise MockIntegrationError("MOCK_OPT_IN_REQUIRED") from None
    return args


def main(argv=None) -> int:
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
    except MockIntegrationError as error:
        report, code = failure(error.code), 3
    except KeyboardInterrupt:
        report, code = failure("INTERRUPTED"), 130
    else:
        try:
            # Lazy import: opt-in/errors/help need no Triage/framework dependency.
            from .service import run_mock_backend
            result = run_mock_backend(mock=True, scenario=args.scenario, service_id=args.service)
            report, code = result.to_dict(), result.exit_code
        except ImportError:
            report, code = failure("DEPENDENCIES_UNAVAILABLE"), 2
        except MockIntegrationError as error:
            report = failure(error.code)
            code = 3 if error.code in ("INVALID_SCENARIO", "UNKNOWN_MOCK_SERVICE") else 2
        except KeyboardInterrupt:
            report, code = failure("INTERRUPTED"), 130
        except Exception:
            report, code = failure("UNEXPECTED_ERROR"), 2
    try:
        print(json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True), flush=True)
    except OSError:
        # Prevent buffered shutdown diagnostics after a closed OS output pipe.
        try:
            with open(os.devnull, "w") as sink:
                os.dup2(sink.fileno(), sys.stdout.fileno())
        except (AttributeError, OSError, ValueError):
            pass
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
