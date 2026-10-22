"""Fixed integration errors; raw component diagnostics never cross the CLI."""


_MESSAGES = {
    "MOCK_OPT_IN_REQUIRED": "Explicit mock mode is required.",
    "INVALID_ARGUMENTS": "Unsupported command arguments.",
    "INVALID_SCENARIO": "Select a supported mock scenario.",
    "UNKNOWN_MOCK_SERVICE": "Select a configured mock service.",
    "CONTEXT_REJECTED": "The retained collection or submitted context is inconsistent.",
    "SETUP_ASSOCIATION_FAILED": "Setup could not associate the current evidence and diagnosis.",
    "DIAGNOSIS_FAILED": "The mock diagnosis could not be completed.",
    "DEPENDENCIES_UNAVAILABLE": "Install the documented mock environment first.",
    "UNEXPECTED_ERROR": "The mock integration could not complete.",
    "INTERRUPTED": "The mock integration was interrupted.",
}


class MockIntegrationError(Exception):
    def __init__(self, code="UNEXPECTED_ERROR"):
        self.code = code if type(code) is str and code in _MESSAGES else "UNEXPECTED_ERROR"
        super().__init__(_MESSAGES[self.code])
        self.__suppress_context__ = True


def failure(code: str) -> dict:
    error = MockIntegrationError(code)
    return {
        "mode": "mock", "status": "failed", "error_code": error.code,
        "authorization_consumed": False, "execution_authorized": False, "execution_performed": False,
    }
