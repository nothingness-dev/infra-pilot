"""Reproducible SYNTHETIC context fixtures; no account, environment or network."""

from dataclasses import replace

from provider import CollectionContextAdapter, MockLiaraClient, PreparedCollection, ServiceBinding, ServiceLog


MOCK_CONTEXT_SCENARIOS = (
    "exported", "empty", "unavailable", "not_collected", "withheld", "partial_logs", "partial_failure",
)


def mock_context_binding() -> ServiceBinding:
    return ServiceBinding("MOCK-service", "mock-project", "mock-account", True)


def build_mock_context(scenario: str = "partial_failure") -> PreparedCollection:
    if scenario not in MOCK_CONTEXT_SCENARIOS:
        raise ValueError("Unknown mock context scenario.")
    failures = {
        "empty": {"logs": "empty"}, "unavailable": {"logs": "missing"},
        "partial_failure": {"logs": 403, "metrics": 429},
    }.get(scenario)
    client = MockLiaraClient(failure_modes=failures)
    binding = mock_context_binding()
    bundle = client.collect_service_observations(
        binding.project_name, logs_since=None if scenario == "not_collected" else "mock-window",
    ).data
    # Controlled collector times are fixture data, not live evidence. Do not
    # change process clocks/globals: another caller may be collecting concurrently.
    stamp = "2026-10-22T00:00:00Z"
    times = {
        name: replace(getattr(bundle, name), collected_at=(
            None if getattr(bundle, name).collected_at is None else stamp
        )) for name in ("service", "deployment", "logs", "metrics")
    }
    bundle = replace(bundle, collection_started_at=stamp, collection_finished_at=stamp, **times)
    if scenario == "partial_logs":
        bundle = replace(bundle, logs=replace(bundle.logs, data=[
            ServiceLog("Synthetic application started", "mock-stdout", None),
            ServiceLog(None, None, None),
        ]))

    def reviewed_fixture(message: str) -> str | None:
        return message if message == "Synthetic application started" else None

    return CollectionContextAdapter(client, provider_scope=binding.provider_scope).from_observations(
        bundle, binding=binding, log_sanitizer=None if scenario == "withheld" else reviewed_fixture,
    )
