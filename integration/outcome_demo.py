"""Safe explicit offline outcome CLI; no API token or arbitrary JSON input."""

import sys

from .errors import MockIntegrationError
from .mock_backend import _Parser, write_report


def _arguments(argv):
    parser = _Parser(prog="python -B -m integration.outcome_demo", allow_abbrev=False)
    parser.add_argument("--mock", action="store_true", help="Required explicit offline opt-in")
    parser.add_argument("--scenario", default="approved_not_executed", help="Documented Mock outcome scenario")
    args = parser.parse_args(argv)
    if args.mock is not True:
        raise MockIntegrationError("MOCK_OPT_IN_REQUIRED") from None
    return args


def _failure(code):
    allowed = ("MOCK_OPT_IN_REQUIRED", "INVALID_ARGUMENTS", "INVALID_SCENARIO", "DEPENDENCIES_UNAVAILABLE",
               "UNEXPECTED_ERROR", "INTERRUPTED")
    code = code if type(code) is str and code in allowed else "UNEXPECTED_ERROR"
    return {"contract_version": "infrapilot-evidence-outcome/1-mock", "mode": "mock",
            "evaluation_state": "failed", "error_code": code, "post_action_evaluation": "not_performed",
            "authorization_consumed": False, "execution_authorized": False, "execution_performed": False,
            "remediation_verified": False, "causality_established": False}


def main(argv=None):
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
    except MockIntegrationError as error:
        report, code = _failure(error.code), 3
    except KeyboardInterrupt:
        report, code = _failure("INTERRUPTED"), 130
    else:
        try:
            from .outcome_evidence import OutcomeError
            from .outcome_fixtures import run_outcome_demo
        except ImportError:
            report, code = _failure("DEPENDENCIES_UNAVAILABLE"), 2
        except KeyboardInterrupt:
            report, code = _failure("INTERRUPTED"), 130
        except Exception:
            report, code = _failure("UNEXPECTED_ERROR"), 2
        else:
            try:
                result = run_outcome_demo(mock=True, scenario=args.scenario)
                report, code = result.to_dict(), result.exit_code
            except OutcomeError as error:
                report, code = _failure(error.code), 3 if error.code == "INVALID_SCENARIO" else 2
            except KeyboardInterrupt:
                report, code = _failure("INTERRUPTED"), 130
            except Exception:
                report, code = _failure("UNEXPECTED_ERROR"), 2
    return code if write_report(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
