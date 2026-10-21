"""Deterministic diagnostic heuristics; no provider calls or approval evaluation."""

from dataclasses import dataclass

from .schemas import DiagnosticHypothesis, ServiceStatus
from .symptoms import ExtractedSymptoms, Symptom


@dataclass(frozen=True)
class RuleFinding:
    hypothesis: DiagnosticHypothesis
    action_ids: tuple[str, ...]


def conflicting_indicators(observations: ExtractedSymptoms) -> tuple[str, ...]:
    snapshot = observations.snapshot
    failures = (
        Symptom.DATABASE_CONNECTION_FAILURE, Symptom.OUT_OF_MEMORY,
        Symptom.APPLICATION_ERROR, Symptom.HTTP_SERVER_ERROR,
    )
    conflicts: list[str] = []
    if snapshot.status == ServiceStatus.HEALTHY and any(observations.has(s) for s in failures):
        conflicts.append(
            "Reported healthy state conflicts with failure indicators; observations may cover different times."
        )
    http_success = snapshot.http_status is not None and 200 <= snapshot.http_status < 300
    if http_success and any(observations.has(s) for s in (*failures, Symptom.UNHEALTHY, Symptom.DEGRADED)):
        conflicts.append(
            "A successful HTTP response coexists with failure indicators; endpoint scope or observation time may differ."
        )
    return tuple(conflicts)


def evaluate_rules(observations: ExtractedSymptoms) -> tuple[RuleFinding, ...]:
    """Return candidates in rule order; the report builder performs final ranking."""
    findings: list[RuleFinding] = []
    penalty = 0.1 if conflicting_indicators(observations) else 0.0

    def add(
        identifier: str, explanation: str, confidence: float,
        symptoms: tuple[Symptom, ...], actions: tuple[str, ...],
    ) -> None:
        evidence_ids = observations.supporting_ids(*symptoms)
        if not evidence_ids:
            return
        findings.append(RuleFinding(
            hypothesis=DiagnosticHypothesis(
                hypothesis_id=identifier,
                explanation=explanation,
                confidence=round(max(0.0, confidence - penalty), 2),
                evidence_ids=list(evidence_ids),
            ),
            action_ids=actions,
        ))

    if observations.has(Symptom.OUT_OF_MEMORY):
        add(
            "out_of_memory",
            "Supplied logs report an out-of-memory condition; memory exhaustion may have affected the service.",
            0.96 if observations.has(Symptom.HIGH_RAM) else 0.92,
            (Symptom.OUT_OF_MEMORY, Symptom.HIGH_RAM),
            ("inspect_memory_usage", "review_memory_configuration"),
        )
    if observations.has(Symptom.DATABASE_CONNECTION_FAILURE):
        add(
            "database_connection_failure",
            "Supplied logs report database connection failures that may explain application errors.",
            0.89 if observations.has(Symptom.HTTP_SERVER_ERROR) else 0.86,
            (Symptom.DATABASE_CONNECTION_FAILURE, Symptom.HTTP_SERVER_ERROR),
            ("inspect_database_connectivity", "review_database_configuration"),
        )
    if observations.has(Symptom.HIGH_CPU):
        slow = observations.has(Symptom.SLOW_RESPONSE)
        add(
            "cpu_saturation",
            "Elevated CPU usage may contribute to the observed slow response."
            if slow else "CPU usage exceeds the configured threshold; its effect on service latency is unconfirmed.",
            0.82 if slow else 0.66,
            (Symptom.HIGH_CPU, Symptom.SLOW_RESPONSE),
            ("inspect_cpu_load", "review_resource_configuration"),
        )
    if observations.has(Symptom.HIGH_RAM) and not observations.has(Symptom.OUT_OF_MEMORY):
        add(
            "high_memory_usage",
            "RAM usage exceeds the configured absolute threshold; capacity pressure cannot be confirmed without a memory limit.",
            0.62,
            (Symptom.HIGH_RAM,),
            ("inspect_memory_usage", "review_memory_configuration"),
        )
    if observations.has(Symptom.SLOW_RESPONSE) and not observations.has(Symptom.HIGH_CPU):
        add(
            "response_latency",
            "Response time exceeds the configured threshold; the cause is not established by this observation.",
            0.50,
            (Symptom.SLOW_RESPONSE,),
            ("inspect_latency",),
        )
    if observations.has(Symptom.APPLICATION_ERROR):
        add(
            "application_error",
            "Supplied logs contain application error indicators; a specific underlying cause remains unconfirmed.",
            0.58,
            (Symptom.APPLICATION_ERROR,),
            ("inspect_application_errors",),
        )
    if observations.has(Symptom.UNHEALTHY):
        add(
            "service_unhealthy", "The service reports unhealthy state; the underlying cause remains unconfirmed.",
            0.45, (Symptom.UNHEALTHY,), ("inspect_service_health",),
        )
    if observations.has(Symptom.DEGRADED):
        add(
            "service_degraded", "The service reports degraded state; the underlying cause remains unconfirmed.",
            0.40, (Symptom.DEGRADED,), ("inspect_service_health",),
        )
    if observations.has(Symptom.HTTP_SERVER_ERROR):
        add(
            "http_server_error", "An HTTP server error was observed; HTTP status alone does not identify its cause.",
            0.35, (Symptom.HTTP_SERVER_ERROR,), ("inspect_application_errors",),
        )
    return tuple(findings)
