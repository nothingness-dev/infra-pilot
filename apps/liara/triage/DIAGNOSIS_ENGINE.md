# Deterministic diagnosis engine (Task 2)

Public entry point: `diagnose(snapshot: ServiceSnapshot, *, thresholds=None)`
returns the existing `DiagnosisReport`. It copies/revalidates the input, extracts
observations, evaluates fixed rules, ranks hypotheses, and creates recommendations.
It does not mutate input, read the clock, generate randomness, call providers,
execute processes, invoke an LLM, or perform infrastructure actions.

## Observations and missing data

Evidence IDs are stable for a given snapshot: `service-status`, `http-status`,
`cpu-usage`, `ram-usage`, `response-time`, and positional `log-0001`, etc.
All supplied measurements are recorded, including zero. Unavailable fields are
listed in `missing_information`; no substitute values are created.

`logs=None` means unavailable. `logs=[]` is an explicitly empty collection and
is disclosed as a limitation. Blank lines provide no evidence and are disclosed;
nonblank lines retain their original positions. Evidence descriptions quote log
messages as JSON strings so trailing whitespace survives the existing description
validation. This quoting is not redaction: adapter/UI sanitization remains needed
before handling sensitive logs or presenting reports outside a trusted context.

The contract cannot indicate a truncated log stream or a shared observation time
window. Supplied lines are therefore described as potentially partial/historical.
An absent snapshot timestamp is explicit; a provided timestamp is not treated as
proof that metrics and logs are contemporaneous.

## Rules and default thresholds

Threshold comparisons are inclusive. Configure finite positive values through
`DiagnosisThresholds`; CPU must be at most 100 percent. The active thresholds
are included in report limitations for reproducibility.

| Observation | Candidate and base heuristic confidence |
| --- | --- |
| Explicit OOM/out-of-memory/MemoryError log | `out_of_memory`: 0.92; 0.96 with high RAM |
| Database context plus connection failure log | `database_connection_failure`: 0.86; 0.89 with HTTP 5xx |
| CPU >= 85% | `cpu_saturation`: 0.66; 0.82 with response time >= 1000 ms |
| RAM >= 1024 MiB, without OOM logs | `high_memory_usage`: 0.62 |
| Error/critical log or explicit exception indicator, without a specific match on that line | `application_error`: 0.58 |
| Response time >= 1000 ms, without high CPU | `response_latency`: 0.50 |
| Unhealthy service state | `service_unhealthy`: 0.45 |
| Degraded service state | `service_degraded`: 0.40 |
| HTTP 500–599 | `http_server_error`: 0.35 |

Database detection requires both named database/library context and a recognized
connection error; a generic connection refusal alone is insufficient. OOM uses
explicit text, not an exit code such as 137 alone. A few direct negations such as
`No OOM` and `OOM: false` are excluded. Matching is a limited English pattern
heuristic, not a general natural-language or structured-log parser.

RAM's threshold is an absolute investigation threshold, not an allocation limit
or utilization percentage. Usage alone never produces an OOM hypothesis. High
CPU and latency occurring together suggest a relationship, not proven causality.
Other HTTP statuses remain observed evidence but have no HTTP-specific cause rule.

Healthy status together with failure indicators, or successful HTTP 2xx together
with log/health failures, adds explicit conflict limitations. A conflict subtracts
0.10 from each candidate score once; it does not discard any observed evidence.
This keeps specificity ahead of generic errors while lowering confidence. Scores
are **heuristics, not calibrated probabilities**, and do not sum to one.

Candidates sort by descending confidence, then ascending hypothesis identifier
to resolve ties. Every hypothesis has nonempty references to evidence in the
same report. Actions are deduplicated and sorted by identifier. The same snapshot
and thresholds produce the same serialized report. Missing measurements do not
contribute positive evidence or become zeros.

Healthy snapshots with incomplete observability can produce no hypotheses plus
a collection recommendation. They are never declared guaranteed problem-free.
Mock input always produces a mock report with a real-service limitation.

## Recommendations and approval metadata

Inspection recommendations cover application errors, database connectivity,
CPU/workload, memory, latency, health, and missing observations. Potential database,
memory, and resource configuration changes are only proposals for operator review,
have medium risk, and explicitly require approval. Provider support must be
verified before any future change is proposed for execution.

All actions retain `status="not_executed"`. Read-only investigation suggestions
have low risk and `requires_approval=False`; this grants no execution permission.
These are static per-recommendation labels, not a generalized Approval Policy.
There is no executor, provider operation registry, restart, scaling API, or secret
handling implementation here.

Task 3 adds a separate `ApprovalGate`; it never trusts these Agent recommendation
labels for authorization. See `APPROVAL_POLICY.md`. Diagnosis itself remains
unchanged and cannot grant approval or execute actions.

## Integration boundary and dependencies

The six Task 1 schemas, dependencies, and original 56 tests remain unchanged.
Adapter and UI integration continues to require team approval of the internal
draft contracts; they are not official Liara schemas. The adapter supplies
normalized status, correct units, source, logs, and timestamps. The UI should
display missing information, heuristic confidence, conflicts, mock labeling,
and approval flags without treating a recommendation as an executed operation.

Memory limits, log completeness/window metadata, richer evidence pointers, and
per-observation timestamps remain proposed future extensions in
`CONTRACT_PROPOSAL.md`; no new transport fields are added in Task 2.
