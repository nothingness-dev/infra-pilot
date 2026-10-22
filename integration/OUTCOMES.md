# Evidence-based outcome evaluation

Profile **`infrapilot-evidence-outcome/1-mock`**, policy
**`controlled-observation-comparison/1`**. This is an offline, non-UI comparison
component, not an executor or a proof of recovery.

Pages 3 and 8 of the project responsibilities PDF require checking/reporting the
result of the InfraPilot journey. This milestone adds that evaluation boundary,
while preserving the explicit-limitation branch: approval does not establish
execution, and observations alone do not establish causality.

## Two independent questions

The output separates `observation_result` from `action.status`:

- Observations: `observed_improvement`, `no_material_observed_change`,
  `observed_deterioration`, `mixed_changes`, `insufficient_comparable_evidence`,
  `not_performed`, or `rejected_association`.
- Action status: `not_performed`, `unknown_unverified`, or `simulated`.

A pure comparison normally has action status `unknown_unverified`. A private
synthetic event may establish only `simulated`, never real execution. Passing the
actual retained `MockWorkflow` through `evaluate_unexecuted_workflow()` reports
action `not_performed` and `post_action_evaluation=not_performed`, including after
its Mock approval is granted. Serialized claims such as `executed=true` cannot
establish either an action or a trusted evidence reference.

Real execution, authorization consumption, causality and verified remediation
remain false in every result. A simulated event is an operator-selected fixture
annotation, not an execution receipt, an executor, or permission to restart.

## Evaluation policy

Only controlled canonical samples with the same explicit synthetic probe/workload
semantics can produce directional comparisons. They are distinct from Provider
fixtures; no richer measurements are inserted into a Provider export.

| Field | Comparison rule |
| --- | --- |
| Reported application health | Compare known `unhealthy > degraded > healthy` severity. `unknown` is not ordered. |
| Application HTTP status | Compare the actual Triage `HTTP_SERVER_ERROR` signal, present at >=500. Do not order all status codes or call 404 a successful response. |
| Application response time | Compare the actual Triage `SLOW_RESPONSE` signal using `DiagnosisThresholds.slow_response_ms` (default 1000 ms, inclusive). |
| CPU/RAM | Preserve known-unit values and numeric deltas as context only. They never determine the summary or prove recovery. |
| Logs, report prose, hypothesis counts/confidence | Never drive improvement/deterioration. Their absence, withholding or reduced detail cannot establish recovery. |

The existing symptom extractor supplies signal classification; there is no
second diagnosis engine. Setup's actual `prepare_diagnosis` and sanitization run
when retaining canonical samples. Comparing retained evidence does not rerun
diagnosis. CPU/RAM use `%`/`MiB` only in the explicitly defined canonical fixture
source, not as an interpretation of Liara summary arrays.

The summary is scoped to comparable primary health/server-error/latency
indicators. Both improving and worsening indicators produce `mixed_changes`.
Only improving directions produce `observed_improvement`; only worsening
directions produce `observed_deterioration`. Comparable unchanged indicators
produce `no_material_observed_change`. This means the same policy indicators,
not identical measurements, healthy status or a repaired service. For example,
1800 -> 1200 ms remains in the slow band; 200 -> 404 does not remove a server
error signal that was never present. Exact values remain in field-level rows.

If primary evidence coverage changes between samples, withhold the summary as
insufficient and retain all valid supporting field changes. Newly available
measurements are not compared against zero. If no primary indicator is
comparable, resources alone cannot produce an improvement. Missing indicators
on both sides limit the scope to the remaining comparable indicators and are
explicitly reported. Mixed changes and missing coverage are not silently reduced
to a success flag.

## Retained references, scope and time

`OutcomeEvaluator` owns an `EvidenceLedger`. Its `EvidenceRef` values are opaque
references to retained backend objects; their constructors are blocked and
foreign/unregistered references are rejected. JSON output cannot resume a session.

Provider capture retains the original `CompletedInspection`, `PreparedCollection`,
actual source binding, Setup presentation and context. Existing checks validate
the original snapshot/context digests against the independently configured
expected service/project/scope binding. A narrow extension in `integration/service.py`
exposes those retained typed objects and strengthens continuation validation; old
serialized results and commands are unchanged.

Canonical capture uses the existing `ServiceSnapshot`, sanitizer, Setup evidence
metadata and diagnosis binding. It never constructs a `PreparedCollection`.
`controlled-app-probe/1` and `/2` denote distinct backend-defined synthetic
probe/workload series with known units and source sample instants; cross-series
comparison is insufficient. These fixture declarations are not live measurement
verification or authenticated provider/account identity.

Every comparison revalidates the exact service, request fingerprint, source
class, backend scope and current retained payloads. Provider and canonical
sources cannot be silently mixed. Modified snapshots, context, reports, request
details or action bindings fail closed. Valid before-evidence survives an invalid
or unavailable after-reference. Output exposes safe summaries/digests and the
original Provider context, never private scope names, raw logs or diagnosis prose.

Controlled canonical timestamps have explicitly defined source-instant semantics.
References must first have been retained in distinct increasing backend sequence;
this ordering check alone establishes neither observation order nor freshness.
Source instants must also satisfy before < after <= the injected aware clock, with both samples
at most 60 seconds old. Exactly 60 seconds is accepted. A simulated event must
be strictly between them. Missing/equal/reversed/future/stale instants withhold
comparison with a specific limitation. Timezone-equivalent instants are equal.
The 60-second rule is fixture policy, not a production freshness default.

Provider's current Mock exports retain their original fixed collector times,
unknown source timestamps and undefined metric units/windows. Those times may be
identical. Starting two collection calls in sequence or advancing a local clock
does not turn them into ordered source observations. Such comparisons remain
insufficient; capability errors, null measurements, log dispositions/counts and
collection limitations are still retained. `source_freshness_verified=false`
never claims real source freshness, even when controlled fixture age checks pass.

The optional `SimulatedActionRef` binds the exact before-reference, request,
canonical operator-selected action and synthetic event instant. It cannot be
transferred to an identical-looking different reference or supplied as JSON.
No Approval gate is consumed or bypassed to execute anything; there is no
execution at all. These process-local references provide consistency, not
authentication, durable provenance, replay protection or a multi-worker store.

## Installation, CLI and exit codes

Use the existing environment; no dependencies were added:

```powershell
python -B -m venv .venv
.\.venv\Scripts\python.exe -B -m pip install -r requirements-mock.txt
.\.venv\Scripts\python.exe -B -m integration.outcome_demo --mock --scenario improvement
.\.venv\Scripts\python.exe -B -m integration.outcome_demo --mock --scenario approved_not_executed
$LASTEXITCODE  # 4: no action, so no post-action evaluation
```

Only explicit `--mock`, an allowlisted `--scenario` and static `--help` are
accepted. Arguments never contain credentials, arbitrary URLs, raw observations
or execution claims. Help and opt-in validation work without site packages.

| Exit | Meaning and scenarios |
| --- | --- |
| 0 | Comparison completed, including deterioration: `improvement`, `no_change`, `deterioration`, `mixed_changes`, `simulated_improvement` |
| 1 | Insufficient comparable evidence: `insufficient_evidence`, `coverage_loss`, `partial_collection`, `empty_logs`, `missing_logs`, `withheld_logs`, `partial_logs`, `semantics_mismatch`, `ambiguous_order`, `reversed_order`, `missing_timestamp`, `stale_samples`, `future_sample`, `simulation_order_mismatch` |
| 2 | Unexpected runtime/dependency/output failure; preserve independently valid before-data when available |
| 3 | Invalid arguments or rejected association: `service_mismatch`, `request_mismatch`, `action_mismatch`, `source_mismatch`, `scope_mismatch`, `tampered_snapshot`, `tampered_context`, `bad_after` |
| 4 | `approved_not_executed`: action-dependent evaluation not performed |
| 130 | Interrupted |

Exit 0 is successful computation, not a successful action, service health or
recovery. Missing Mock opt-in exits 3. Help exits 0 without constructing samples.

## Python API and output

```python
from datetime import timedelta
from integration.mock_approval import MockClock
from integration.outcome import OutcomeEvaluator
from integration.outcome_fixtures import synthetic_sample

clock = MockClock()
evaluator = OutcomeEvaluator(mock=True, clock=clock)
before = evaluator.evidence.retain_synthetic(synthetic_sample(timestamp=clock()))
clock.now += timedelta(seconds=10)
after = evaluator.evidence.retain_synthetic(synthetic_sample(
    timestamp=clock(), status="healthy", http_status=200, response_time_ms=300.0,
))
result = evaluator.compare(before, after)
assert result.to_dict()["observation_result"] == "observed_improvement"
assert result.to_dict()["action"]["status"] == "unknown_unverified"
assert result.to_dict()["remediation_verified"] is False
```

For a simulated sequence, advance the clock after before-capture, call
`record_simulated_action(before, mock=True)`, then advance again before after-
capture and pass `simulation=reference` to `compare`. This records only a fixture
event. For existing workflow results, pass the original typed session to
`evaluate_unexecuted_workflow(workflow)`, not its JSON. Configure `request` and
`binding` from independent trusted backend state if different from the defaults.

Capture methods raise fixed `OutcomeError` exceptions. `rejection(error,
before=reference)` creates a safe rejected result while retaining valid before
data; `failed(before=reference)` handles an unexpected later failure. Comparison
methods return immutable `OutcomeResult` objects with detached `to_dict()` and
`exit_code`. Summary copies cannot mutate retained payloads. Sessions are trusted,
single-process composition and are not thread-safe or a sandbox against Python
code in the same process.

The envelope includes profile/policy version, `evaluation_state`,
`observation_result`, `association_status`, comparison scope, policy thresholds,
safe before/after evidence summaries, field changes, limitations, errors and
independent action status. Execution/authorization/causality/remediation flags
remain false. `post_action_evaluation=simulated_only` means only that a
time-bracketed fixture event was evaluated; otherwise it remains `not_performed`.
Existing shared contracts keep their original Draft/proposal labels.

Generated CLI examples:
[simulated improvement](examples/outcome_simulated_improvement.json) and
[partial Provider collection](examples/outcome_partial_collection.json).
Both contain synthetic evidence only. They are actual outputs, not live captures.

## Verification and remaining work

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
python -B -m unittest discover -s provider/tests -t . -v
```

See [executed verification](OUTCOME_VERIFICATION.md). Previous verification
reports remain historical. The original Mock and workflow commands still run
their previous behavior; neither silently performs another collection/evaluation.

Real post-action evaluation still needs authenticated service/account identity,
trusted execution evidence, independently verified measurement/window semantics,
appropriate freshness policy, durable audit/association state and separately
authorized execution. No UI, server listener, token lookup, live API request,
real infrastructure operation, authorization consumption or deployment is enabled.
