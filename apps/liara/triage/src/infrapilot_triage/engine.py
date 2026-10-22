"""Build a draft DiagnosisReport from one snapshot, without side effects."""

from .rules import conflicting_indicators, evaluate_rules
from .schemas import ActionProposal, DataSource, DiagnosisReport, RiskLevel, ServiceSnapshot, ServiceStatus
from .symptoms import DiagnosisThresholds, extract_symptoms


# Static recommendation metadata, not an Approval Policy or an execution registry.
_RECOMMENDATIONS: dict[str, tuple[str, str, RiskLevel, bool]] = {
    "collect_observability": (
        "Collect missing observations",
        "Ask the observability adapter for available missing metrics, health details, and relevant logs; do not invent unavailable values.",
        RiskLevel.LOW, False,
    ),
    "inspect_application_errors": (
        "Review application errors",
        "Review existing application logs and error context around the failing request without exposing credentials.",
        RiskLevel.LOW, False,
    ),
    "inspect_cpu_load": (
        "Inspect CPU load",
        "Review available CPU history and workload profiling before attributing latency to CPU saturation.",
        RiskLevel.LOW, False,
    ),
    "inspect_database_connectivity": (
        "Review database connection evidence",
        "Review supplied connection errors and database availability observations; distinguish connectivity, authentication, and pool failures.",
        RiskLevel.LOW, False,
    ),
    "inspect_latency": (
        "Inspect response latency",
        "Review available request timings and dependency observations to locate the source of latency.",
        RiskLevel.LOW, False,
    ),
    "inspect_memory_usage": (
        "Inspect memory usage and limits",
        "Review available memory history, allocation limits, and OOM events before concluding that memory capacity is insufficient.",
        RiskLevel.LOW, False,
    ),
    "inspect_service_health": (
        "Review service health details",
        "Review supplied health-check details and recent service events to investigate the reported unhealthy or degraded state.",
        RiskLevel.LOW, False,
    ),
    "review_database_configuration": (
        "Review a possible database configuration change",
        "If connection evidence supports a configuration change, have the operator review credentials, endpoints, and connection limits before any approved change. No change is performed.",
        RiskLevel.MEDIUM, True,
    ),
    "review_memory_configuration": (
        "Review a possible memory configuration change",
        "If profiling confirms memory pressure, review possible configuration changes with the service owner and verify provider support before requesting approval. No change is performed.",
        RiskLevel.MEDIUM, True,
    ),
    "review_resource_configuration": (
        "Review a possible resource configuration change",
        "If workload evidence confirms saturation, review configuration options and provider support with the operator before any approved change. No change is performed.",
        RiskLevel.MEDIUM, True,
    ),
}


def diagnose(
    snapshot: ServiceSnapshot, *, thresholds: DiagnosisThresholds | None = None,
) -> DiagnosisReport:
    """Return evidence-backed heuristics; never call providers or execute actions."""
    thresholds = thresholds if thresholds is not None else DiagnosisThresholds()
    observations = extract_symptoms(snapshot, thresholds=thresholds)
    snapshot = observations.snapshot
    findings = evaluate_rules(observations)
    hypotheses = sorted(
        (finding.hypothesis for finding in findings),
        key=lambda hypothesis: (-hypothesis.confidence, hypothesis.hypothesis_id),
    )
    action_ids = {identifier for finding in findings for identifier in finding.action_ids}
    if observations.missing_information or snapshot.logs == []:
        action_ids.add("collect_observability")
    actions: list[ActionProposal] = []
    for identifier in sorted(action_ids):
        title, description, risk, approval = _RECOMMENDATIONS[identifier]
        actions.append(ActionProposal(
            action_id=identifier, title=title, description=description,
            risk_level=risk, requires_approval=approval,
        ))
    limitations = [
        "Confidence scores are deterministic heuristics, not calibrated probabilities.",
        "This report uses one supplied snapshot; it does not establish causality or verify data provenance.",
        f"Configured heuristic thresholds: CPU >= {thresholds.high_cpu_percent:g} %, "
        f"RAM >= {thresholds.high_ram_mib:g} MiB, response time >= {thresholds.slow_response_ms:g} ms.",
        *observations.limitations,
        *conflicting_indicators(observations),
    ]
    if snapshot.data_source == DataSource.MOCK:
        limitations.append("Mock observations cannot establish the state of a real service.")
    if hypotheses:
        summary = f"Top hypothesis: {hypotheses[0].explanation}"
    elif snapshot.status == ServiceStatus.HEALTHY:
        summary = "No failure indicators were found in the supplied observations; incomplete observability may hide problems."
    else:
        summary = "Insufficient failure evidence to identify a cause from the supplied observations."
    return DiagnosisReport(
        service_id=snapshot.service_id, summary=summary, data_source=snapshot.data_source,
        evidence=list(observations.evidence), hypotheses=hypotheses, actions=actions,
        missing_information=list(observations.missing_information), limitations=limitations,
    )
