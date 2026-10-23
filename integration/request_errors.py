"""Dependency-free, fixed messages for the local Mock request interface."""

VERSION = "infrapilot-persistent-request/1"
CODES = frozenset({
    "INVALID_ARGUMENTS", "MOCK_OPT_IN_REQUIRED", "INVALID_REQUEST", "INVALID_LOOKUP",
    "NOT_FOUND", "REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "INCOMPLETE_REQUEST",
    "RECOVERY_REQUIRED", "REINSPECTION_REQUIRED", "EVIDENCE_MISMATCH", "STORE_CLOSED",
    "INVALID_DATABASE", "UNSUPPORTED_DATABASE", "RECORD_CORRUPTED", "STORAGE_FAILED",
    "STORAGE_BUSY", "COLLECTION_FAILED", "HISTORY_FAILED", "INTERRUPTED",
    "DEPENDENCIES_UNAVAILABLE", "UNEXPECTED_ERROR",
})


class RequestError(ValueError):
    def __init__(self, code="STORAGE_FAILED"):
        self.code = code if type(code) is str and code in CODES else "STORAGE_FAILED"
        super().__init__("Local Mock request operation failed: " + self.code)
        self.__suppress_context__ = True


def failure(code, exit_code):
    return {"request_profile": VERSION, "status": "failed", "error_code": RequestError(code).code,
            "exit_code": exit_code, "data_source": "mock", "authorization_consumed": False,
            "execution_authorized": False, "execution_performed": False, "remediation_verified": False}
