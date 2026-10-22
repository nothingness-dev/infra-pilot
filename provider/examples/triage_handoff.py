"""Print a synthetic draft ServiceSnapshot, offline and without credentials."""

import json

from provider import MockLiaraClient, TriageAdapter, TriageHandoff


def mock_handoff() -> TriageHandoff:
    # Exact allowlist reviewed for this synthetic fixture, NOT a real-log policy.
    def reviewed_fixture(message: str) -> str | None:
        return message if message == "Synthetic application started" else None

    result = TriageAdapter(MockLiaraClient()).collect(
        "mock-project", service_id="MOCK-service",
        logs_since="2026-01-01T00:00:00Z", log_sanitizer=reviewed_fixture,
    )
    return result.data


if __name__ == "__main__":
    print(json.dumps(mock_handoff().snapshot.to_request(), indent=2, allow_nan=False))
