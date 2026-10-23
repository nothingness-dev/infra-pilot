# Offline request-to-approval workflow

Profile: **`infrapilot-request-approval/1-mock`**. This non-UI continuation of
the merged Mock backend connects the existing implementations. It is not
production authorization or an infrastructure executor.

## Project acceptance scenario and reused interfaces

The responsibilities PDF, page 3, describes receiving a problem, collecting
evidence, diagnosis, proposals, approval and result checking. Page 8 explicitly
allows a permitted action **or an announced limitation**, followed by an outcome.
This milestone follows the limitation branch through an offline CLI.

| Stage | Actual implementation |
| --- | --- |
| Intake and information completion | `setup.application.submit_request`, `supply_information`, existing validation/completion |
| Initial candidate plan | Existing Setup preparation, blocked on genuinely absent dependency references |
| Evidence and diagnosis | Existing `MockSession`, Provider collector/normalizers/retained `PreparedCollection`, Setup companion, Triage Mock contextual preview and actual engine |
| Final preparation | Existing Setup with references only to actual retained Provider/Diagnosis outputs |
| Recommendation review | `SetupApprovalWorkflow.review_action` and existing Triage policy |
| Separate operator approval example | Actual `ApprovalIntegration`, `ApprovalGate`, `InMemoryApprovalStore` with isolated opaque Mock identities |
| Final outcome | Accurate execution blockers; post-action evaluation not performed |

No Provider, Setup or Triage code, shared schema, endpoint, dependency or policy
table changed. Existing runtime edits are confined to `integration/`: an optional
complete-request input and retained `CompletedInspection` continuation in
`MockSession`, plus a shared safe stdout writer. The original `finish()` result,
`integration.mock_backend` CLI, profile and exits remain intact.

## Install and run in PowerShell

From repository root, with Python 3.11+:

```powershell
python -B -m venv .venv
.\.venv\Scripts\python.exe -B -m pip install -r requirements-mock.txt
.\.venv\Scripts\python.exe -B -m integration.workflow_demo --mock --scenario complete_information
$LASTEXITCODE
```

An existing Mock backend environment needs no additional packages. Installation
may download dependencies; the installed workflow opens no listener, makes no
network calls, starts no subprocess and reads no live credentials/configuration.

```powershell
.\.venv\Scripts\python.exe -B -m integration.workflow_demo --mock --scenario approved_not_executed
$LASTEXITCODE  # 4: Mock approval, execution remains blocked
```

Only `--mock`, `--scenario` and static `--help` are accepted. No credentials,
free-text goals, arbitrary URLs or authorization claims belong in arguments.
Opt-in validation and help work without optional Triage dependencies.

## Scenarios and exit codes

| Scenario | Outcome | Exit |
| --- | --- | --- |
| `complete` | Complete brief, actual inspection and observational policy review; nothing executed | 0 |
| `complete_information` | Missing details, controlled completion, then actual inspection/review | 0 |
| `needs_information` | Stop before collection or approval | 4 |
| `invalid_completion` | Reject an approval claim in additional information | 3 |
| `changed_target` | Reject a target outside backend Mock configuration | 3 |
| `partial_failure` | Preserve logs 403 and metrics 429 alongside diagnosis/review | 1 |
| `empty` | Preserve collected empty logs | 0 |
| `unavailable` | Preserve missing logs as unavailable | 1 |
| `not_collected` | Explicitly skip logs | 0 |
| `withheld` | Source logs exist; export policy withholds them | 0 |
| `partial_logs` | One exported message, one withheld entry | 0 |
| `unmapped_action` | No reviewed operation mapping | 4 |
| `policy_denied` | Separate operator-selected destructive example denied by local policy | 4 |
| `approval_pending` | Separate operator-selected Mock restart awaits approval | 4 |
| `approved_not_executed` | Distinct authorized Mock approver approves; execution remains disabled | 4 |
| `approval_rejected` | Mock approver rejects | 4 |
| `approval_expired` | Actual gate expires the request at its exact deadline | 4 |
| `unauthenticated` | No authenticated requester; no approval request created | 4 |
| `permission_denied` | Missing Mock request permission; no approval request created | 4 |

Exit **0** means non-executing inspection/review completed with attempted
collection available, not healthy/repaired/authorized. Skipped collection and
log withholding remain explicit. Exit **1** preserves partial collection.
Exit **2** is a component/association/dependency/output failure. Exit **3** means
invalid input/options or missing Mock opt-in. Exit **4** is an expected wait,
denial or blocked action, including approval without execution. Exit **130** is
interruption. Static help exits 0 without constructing the workflow.

An approval block after partial collection exits 4, while `collection_status`
and original capability errors still report the partial data. Runtime failures
take precedence over those outcomes. No exit means successful remediation.

## Reusable Python interface

```python
from integration.workflow import MOCK_GOAL, MockWorkflow

session = MockWorkflow(mock=True, collection_scenario="partial_failure")
missing = session.submit({
    "request_id": "MOCK-workflow-request",
    "operation": "inspect_service", "details": {},
})
assert missing.to_dict()["state"] == "needs_information"
completed = session.supply_information({
    "service_target": "MOCK-service", "goal": MOCK_GOAL,
})
inspection = session.inspect()
review = session.review_action()
approved = session.operator_example("approved_not_executed")
assert approved.exit_code == 4
assert approved.to_dict()["collection_status"] == "partial"
assert approved.to_dict()["execution_performed"] is False
```

The fixture profile accepts the exact ID/operation above, `MOCK-service`, and
either `MOCK_GOAL` or `Review this synthetic service again`. Required details can
initially be absent. It deliberately rejects arbitrary text without echo, even
if structurally valid. Shared Setup validation remains general and unchanged.
This is not a production intake API or service registry.

Methods return immutable `WorkflowResult` objects with `exit_code` and detached
`to_dict()`. `run_mock_workflow(mock=True, scenario=...)` composes these methods
for the CLI. Repeated inspection reads reuse the current diagnosis. Information
changes invalidate local collection/review/approval references and require fresh
inspection. Failed stages cannot continue as success; resubmit or complete a
brief to reset. Sessions are single-process, non-concurrent and non-durable.
JSON cannot reconstruct them or grant approval. Discarding local references
does not claim durable revocation of separately retained internal objects.

## Mapping and Approval boundaries

The sole reviewed recommendation mapping is `collect_observability` to
`refresh_observations` with no parameters. The actual report must contain that
proposal. The existing policy classifies it as a low-risk observational
operation. Review neither grants permission nor performs more collection.
Other IDs, prose and advisory risk flags cannot dispatch operations.

The controlled unknown-telemetry fixtures do not justify sensitive remediation.
The sensitive example therefore does not invent a restart recommendation or
rewrite the report. Instead an operator explicitly selects a separate Mock
restart with a 30-second grace period. Its output says `not_diagnosis_derived`
and provider support `unverified`. It uses the existing Triage gate directly;
using Setup's proposal-binding adapter here would falsely attach that operation
to a diagnosis proposal. The denied example similarly chooses deletion
explicitly; its `unsupported_action` is local policy, not a Liara capability claim.

Before each transition, retained inspection objects revalidate through existing
Setup/Provider checks. The integration compares the request fingerprint,
diagnosis binding, companion binding and canonical action to their original
retained values. No trusted reference or expected binding comes from output JSON.
Changed requests, targets, evidence, reports, parameters and policy fail closed.

Each operator example creates its own gate/store and opaque requester/approver
sessions. Permissions apply only to its exact canonical action. The requester
can request, the distinct approver can approve, and neither can execute. The
actual gate performs audit, denial and expiration handling. Original decisions,
including `allowed=false`, `authorization_id=null` and audit indicators, remain
unchanged. Approval is not authorization consumption or execution.

`MockClock` is an injectable aware synthetic clock, not observation freshness or
current wall-clock time. The expiry fixture advances it to the actual gate-created
deadline. An alternate installed clock's owner controls its progression. Each
CLI scenario is independent. Gate-generated UUIDs vary between runs, so complete
approval output is structurally reproducible, not byte-for-byte identical.

## Output and partial failures

The workflow-owned envelope adds `contract_version`, `mode`, `state`, `stage`,
`collection_scenario`, `collection_status`, `error_code`, and `stages`. It includes
existing execution blockers, false authorization/execution indicators,
`post_action_evaluation=not_performed` and `remediation_verified=false`.
Shared contracts retain their Draft/proposal versions.

`stages` contains actual serialized intake/completion/preparation, collection,
original integrated inspection, review and optional operator transitions/current
approval/audits. Completed stages are historical valid-at-completion snapshots.
A diagnosis failure retains valid collection. A later approval failure retains
inspection/review and any previously recorded pending state, without claiming
current approval or success. Errors report the failed stage and fixed safe code.

Capability errors remain authoritative. Unknown measurements stay null/unknown;
empty, unavailable, skipped, withheld, partial and failed logs stay distinct.
Collector fixture timestamps remain explicitly synthetic. Rejected field names,
values and arbitrary exceptions are not echoed. Only controlled brief text and
the existing exact-message Mock log export policy reach output. This is not a
general secret detector or a policy for sharing live logs.

[Full generated approval output](examples/workflow_approved_not_executed.json)
comes from the actual CLI, contains only synthetic data and reports execution
blocked. A shortened illustration of its top-level fields is:

```json
{
  "contract_version": "infrapilot-request-approval/1-mock",
  "mode": "mock",
  "state": "approved_not_executed",
  "stage": "approval",
  "collection_status": "complete",
  "authorization_consumed": false,
  "execution_authorized": false,
  "execution_performed": false,
  "post_action_evaluation": "not_performed",
  "remediation_verified": false,
  "production_readiness": "unresolved"
}
```

## Verification and remaining work

Optional [durable Approval/Audit](APPROVAL_PERSISTENCE.md) now uses the same gate
through a backend-owned store factory. The existing CLI accepts
`--approval-database PATH`; this mode exports a summary, keeps Mock opt-in and
never consumes authorization. Fresh workflows cannot reconstruct original
evidence/sessions from persisted decisions.

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
python -B -m unittest discover -s provider/tests -t . -v
```

See [executed workflow verification](WORKFLOW_VERIFICATION.md).

Remaining work: real read-only account/service verification, production identity
and target ACLs, production association/recovery and protected audit retention, freshness/replay and
live-log sharing policies, reviewed provider action capabilities, separately
authorized execution, and actual before/after evaluation. Online deployment,
frontend and video delivery are outside this change. No real API call, operation,
authorization consumption, merge, force-push or deployment was performed.
