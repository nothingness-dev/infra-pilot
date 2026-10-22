"""Explicit backend-owned outcome scenarios. No inferred Liara measurements."""

from dataclasses import replace
from datetime import timedelta

from infrapilot_triage.schemas import ServiceSnapshot
from provider.examples.context_fixtures import mock_context_binding
from setup.models import OperationRequest

from .mock_approval import MockClock
from .outcome import OutcomeEvaluator
from .outcome_evidence import OutcomeError
from .service import MockSession
from .workflow import MOCK_GOAL, MockWorkflow


SCENARIOS = (
    "approved_not_executed", "improvement", "no_change", "deterioration", "mixed_changes",
    "insufficient_evidence", "coverage_loss", "partial_collection", "empty_logs", "missing_logs",
    "withheld_logs", "partial_logs", "service_mismatch", "request_mismatch", "action_mismatch",
    "source_mismatch", "scope_mismatch", "semantics_mismatch", "ambiguous_order", "reversed_order",
    "missing_timestamp", "stale_samples", "future_sample", "tampered_snapshot", "tampered_context",
    "bad_after", "simulated_improvement", "simulation_order_mismatch",
)


def synthetic_sample(*, timestamp, status="unhealthy", http_status=500, response_time_ms=1800.0,
                     cpu_usage_percent=90.0, ram_usage_mib=1200.0, logs=None, **changes):
    """Known-unit canonical app observations, NOT Provider exports or captures.

    Timestamp is a controlled source sample instant, measurements come from
    one synthetic probe/workload definition. No raw API unit is interpreted.
    """
    return ServiceSnapshot(service_id="MOCK-service", data_source="mock", status=status,
                           http_status=http_status, response_time_ms=response_time_ms,
                           cpu_usage_percent=cpu_usage_percent, ram_usage_mib=ram_usage_mib,
                           logs=logs, timestamp=timestamp, **changes)


def run_outcome_demo(*, mock=False, scenario="approved_not_executed"):
    if mock is not True:
        raise OutcomeError("MOCK_OPT_IN_REQUIRED") from None
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise OutcomeError("INVALID_SCENARIO") from None
    clock = MockClock()
    evaluator = OutcomeEvaluator(mock=True, clock=clock)
    before = None
    try:
        if scenario == "approved_not_executed":
            workflow = MockWorkflow(mock=True)
            workflow.submit({"request_id": "MOCK-workflow-request", "operation": "inspect_service",
                             "details": {"service_target": "MOCK-service", "goal": MOCK_GOAL}})
            workflow.inspect()
            workflow.review_action()
            workflow.operator_example("approved_not_executed")
            return evaluator.evaluate_unexecuted_workflow(workflow)
        provider_scenario = {
            "partial_collection": "partial_failure", "empty_logs": "empty", "missing_logs": "unavailable",
            "withheld_logs": "withheld", "partial_logs": "partial_logs", "tampered_context": "exported",
        }.get(scenario)
        if provider_scenario:
            first = MockSession(mock=True, scenario="exported", request=evaluator.evidence.request).inspect()
            before = evaluator.evidence.retain_provider(first)
            second = MockSession(mock=True, scenario=provider_scenario, request=evaluator.evidence.request).inspect()
            after = evaluator.evidence.retain_provider(second)
            if scenario == "tampered_context":
                evaluator.evidence._entries[after].context["log_export"]["withheld"] += 1
            return evaluator.compare(before, after)

        start = clock.now
        baseline = synthetic_sample(timestamp=start)
        if scenario == "insufficient_evidence":
            baseline = synthetic_sample(timestamp=start, status="unknown", http_status=None, response_time_ms=None)
        before = evaluator.evidence.retain_synthetic(baseline)
        simulation = None
        if scenario in ("simulated_improvement", "simulation_order_mismatch", "action_mismatch"):
            clock.now += timedelta(seconds=5)
            simulation = evaluator.record_simulated_action(before, mock=True)
            if scenario == "action_mismatch":
                other = evaluator.evidence.retain_synthetic(baseline)
                return evaluator.compare(other, before, simulation=simulation)
        clock.now = start + timedelta(seconds=10)
        sample = synthetic_sample(timestamp=clock.now)
        if scenario in ("improvement", "simulated_improvement", "simulation_order_mismatch"):
            sample = synthetic_sample(timestamp=clock.now, status="healthy", http_status=200, response_time_ms=300.0,
                                      cpu_usage_percent=20.0, ram_usage_mib=800.0)
        elif scenario == "deterioration":
            # A new evaluator reference is needed for a genuinely different
            # before sample. No bound Provider export is modified.
            before = evaluator.evidence.retain_synthetic(synthetic_sample(
                timestamp=start, status="healthy", http_status=200, response_time_ms=300.0,
            ))
        elif scenario == "mixed_changes":
            sample = synthetic_sample(timestamp=clock.now, status="healthy", response_time_ms=2200.0)
            before = evaluator.evidence.retain_synthetic(synthetic_sample(timestamp=start, response_time_ms=300.0))
        elif scenario == "insufficient_evidence":
            sample = synthetic_sample(timestamp=clock.now, status="unknown", http_status=None, response_time_ms=None)
        elif scenario == "coverage_loss":
            sample = synthetic_sample(timestamp=clock.now, status="healthy", http_status=None, response_time_ms=None)
        elif scenario == "service_mismatch":
            sample.service_id = "MOCK-other-service"
        elif scenario == "source_mismatch":
            sample.data_source = "real"
        elif scenario == "ambiguous_order":
            sample.timestamp = start
        elif scenario == "reversed_order":
            sample.timestamp = start - timedelta(seconds=1)
        elif scenario == "missing_timestamp":
            sample.timestamp = None
        elif scenario == "future_sample":
            sample.timestamp = clock.now + timedelta(seconds=1)
        elif scenario == "bad_after":
            return evaluator.compare(before, {"executed": True})
        if scenario == "simulation_order_mismatch":
            sample.timestamp = start + timedelta(seconds=2)
        capture_options = {}
        if scenario == "request_mismatch":
            capture_options["request"] = OperationRequest("MOCK-other-request", "inspect_service", {
                "service_target": "MOCK-service", "goal": MOCK_GOAL,
            })
        elif scenario == "scope_mismatch":
            capture_options["binding"] = replace(mock_context_binding(), provider_scope="MOCK-other-scope")
        elif scenario == "semantics_mismatch":
            capture_options["semantics"] = "controlled-app-probe/2"
        after = evaluator.evidence.retain_synthetic(sample, **capture_options)
        if scenario == "tampered_snapshot":
            evaluator.evidence._entries[after].presentation.evidence.snapshot.response_time_ms = 1.0
        if scenario == "stale_samples":
            clock.now += timedelta(seconds=61)
        return evaluator.compare(before, after, simulation=simulation)
    except OutcomeError as error:
        return evaluator.rejection(error, before=before)
    except Exception:
        return evaluator.failed(before=before)
