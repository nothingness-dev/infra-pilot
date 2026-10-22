"""Thin offline CLI: python -B -m integration.workflow_demo --mock."""

import sys

from .errors import MockIntegrationError
from .mock_backend import _Parser, write_report


def _arguments(argv):
    parser = _Parser(prog="python -B -m integration.workflow_demo", allow_abbrev=False)
    parser.add_argument("--mock", action="store_true", help="Required explicit offline opt-in")
    parser.add_argument("--scenario", default="complete", help="One documented Mock workflow scenario")
    args = parser.parse_args(argv)
    if not args.mock:
        raise MockIntegrationError("MOCK_OPT_IN_REQUIRED") from None
    return args


def _failure(code):
    # Keep invalid options/help independent of the optional Triage dependencies.
    return {"contract_version": "infrapilot-request-approval/1-mock", "mode": "mock", "state": "failed",
            "error_code": MockIntegrationError(code).code,
            "authorization_consumed": False, "execution_authorized": False, "execution_performed": False}


def main(argv=None):
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
    except MockIntegrationError as error:
        report, code = _failure(error.code), 3
    except KeyboardInterrupt:
        report, code = _failure("INTERRUPTED"), 130
    else:
        try:
            from .workflow import run_mock_workflow
            result = run_mock_workflow(mock=True, scenario=args.scenario)
            report, code = result.to_dict(), result.exit_code
        except ImportError:
            report, code = _failure("DEPENDENCIES_UNAVAILABLE"), 2
        except MockIntegrationError as error:
            report = _failure(error.code)
            code = 3 if error.code == "INVALID_SCENARIO" else 2
        except KeyboardInterrupt:
            report, code = _failure("INTERRUPTED"), 130
        except Exception:
            report, code = _failure("UNEXPECTED_ERROR"), 2
    return code if write_report(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
