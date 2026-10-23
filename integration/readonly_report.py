"""Data-free CLI vocabulary; no backend/framework imports or input reflection."""

PROFILE = "infrapilot-readonly-inspection/1"
CODES = frozenset({
    "INVALID_ARGUMENTS", "LIVE_OPT_IN_REQUIRED", "INVALID_CONFIGURATION",
    "DEPENDENCIES_UNAVAILABLE", "COLLECTION_FAILED", "CONTEXT_REJECTED",
    "DIAGNOSIS_FAILED", "ASSOCIATION_FAILED", "EVIDENCE_MODIFIED",
    "UNEXPECTED_ERROR", "INTERRUPTED",
})
LIMITATIONS = frozenset({
    "HEALTH_STATUS_UNVERIFIED", "APPLICATION_HTTP_NOT_MEASURED", "CPU_RAM_UNITS_UNVERIFIED",
    "SOURCE_TIMESTAMPS_UNVERIFIED", "LOG_WINDOW_COMPLETENESS_UNVERIFIED",
    "DEPLOYMENT_RELEASE_FIELDS_NOT_IN_DRAFT", "LOG_TEXT_WITHHELD",
    "LOG_EXPORT_INCOMPLETE", "LOG_TIME_AND_LEVEL_UNVERIFIED",
})


class ReadOnlyError(ValueError):
    def __init__(self, code="UNEXPECTED_ERROR"):
        self.code = code if type(code) is str and code in CODES else "UNEXPECTED_ERROR"
        super().__init__("Read-only inspection could not proceed: " + self.code)
        self.__suppress_context__ = True


def empty_summary(*, code=2, error="UNEXPECTED_ERROR", stage="initialization"):
    stage = stage if type(stage) is str and stage in {
        "initialization", "configuration", "collection", "context", "diagnosis",
        "association", "complete", "validation", "interrupted",
    } else "initialization"
    code = code if type(code) is int and code in {0, 1, 2, 3, 130} else 2
    return {
        "integration_profile": PROFILE, "data_source": "real", "stage": stage,
        "status": "failed", "collection_outcome": "not_performed", "exit_code": code,
        "error_code": error if type(error) is str and error in CODES else "UNEXPECTED_ERROR",
        "capabilities": [], "logs": None,
        "diagnosis": {"available": False, "associated": False, "counts": None},
        "limitations": [], "production_readiness": "unresolved",
        "identity_verified": False, "freshness_evaluated": False,
        "authorization_consumed": False, "execution_authorized": False,
        "execution_performed": False, "remediation_verified": False,
        "post_action_evaluation": "not_performed",
    }
