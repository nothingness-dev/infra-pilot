"""Safe, dependency-free history boundary diagnostics."""

VERSION = "infrapilot-inspection-history/1"
CODES = frozenset({
    "INVALID_DATABASE", "UNSUPPORTED_DATABASE", "STORAGE_FAILED", "STORE_CLOSED",
    "INVALID_INSPECTION", "RECORD_CORRUPTED", "INVALID_LOOKUP", "INVALID_ARGUMENTS",
    "MOCK_OPT_IN_REQUIRED", "DEPENDENCIES_UNAVAILABLE", "INTERRUPTED", "UNEXPECTED_ERROR",
})


class HistoryError(ValueError):
    def __init__(self, code="STORAGE_FAILED"):
        self.code = code if type(code) is str and code in CODES else "STORAGE_FAILED"
        super().__init__("Inspection history could not proceed: " + self.code)
        self.__suppress_context__ = True


def failure(code, exit_code):
    return {"history_profile": VERSION, "status": "failed", "exit_code": exit_code,
            "error_code": code if type(code) is str and code in CODES else "UNEXPECTED_ERROR",
            "history_only": True, "authorization_consumed": False,
            "execution_authorized": False, "execution_performed": False}
