# Integration QA handoff (Task 05A)

**Internal DRAFT v0.1, requiring team agreement; not official Liara API schemas.**
No shared contract was changed or approved by this QA task. Work is confined to
`apps/liara/triage/`; neither setup nor provider source was checked out, merged,
imported into the demo, or modified. Source inspection below is read-only Git
object inspection, not an executed cross-module integration test.

## Verified source revisions

| Source | Inspected revision |
| --- | --- |
| Task 04 API and all 313 regressions | `428237de83631035439afa4d78d9f68f863942b9` |
| Approval dependency, unmerged PR #4 | `835e557b9d97f59522a88527117f759c9779f9d1` |
| Provider in main, from merged PR #5 | `799c752a038a6a5ec1697411bbefb77161457e72` (main merge `0ef27606a2500df334a651a63f57a7ecc492a441`) |
| Setup compatibility / approval-workflow branch tip | `56df8f82d28a6784afc10c136cb80fc674addd84` |

Task 04 PR #6 targets the unmerged approval branch. The QA branch starts directly
at Task 04; no PR is merged or retargeted by QA. Branch names and documentation
on teammates' revisions may reflect earlier checkpoints; findings here use actual
source content at the revisions above.

## Actual imports and HTTP contracts

```python
from infrapilot_triage import (
    ServiceSnapshot, LogEntry, DiagnosisReport, ActionProposal, diagnose,
    ActionIntent, ActionPolicy, ApprovalGate, GateDecision,
    IdentityBoundary, Permission, InMemoryApprovalStore,
)
from infrapilot_triage.api import (
    app, create_app, TrustedAuthenticationResolver,
    get_approval_integration, get_trusted_authentication,
)
from infrapilot_triage.api_contracts import (
    HealthResponse, ErrorResponse, AuthorizationRequest, PolicyEvaluationResponse,
)
from infrapilot_triage.approval_integration import ApprovalIntegration
from infrapilot_triage.approval_store import ApprovalStore
from infrapilot_triage.demo import run_mock_demo  # Explicit offline mock=True only.
```

`diagnose(snapshot, *, thresholds=None) -> DiagnosisReport` remains pure and
deterministic. `ApprovalIntegration(*, policy=None, gate=None)` exposes
`evaluate(intent) -> PolicyEvaluationResponse` and
`authorize(intent, *, authentication=None, approval_request_id=None) -> GateDecision`.
The gate provides trusted Python `request_approval`, `approve`, `reject`, and
`authorize`, with the existing checks documented in `APPROVAL_POLICY.md`.

| HTTP route | Input | Output / status |
| --- | --- | --- |
| `GET /health` | none | 200 `HealthResponse`; process only |
| `POST /internal/triage/diagnose` | `ServiceSnapshot` | 200 `DiagnosisReport`, even for an observed service HTTP 500 |
| `POST /internal/triage/policy/evaluate` | `ActionIntent` | 200/403/503 `PolicyEvaluationResponse`; classification never grants permission |
| `POST /internal/triage/authorize` | `AuthorizationRequest` | 200/401/403/503 `GateDecision`; may consume an approved request, never executes |
| `GET /openapi.json` | none | Exact generated draft request/response schema definitions |

Approval routes default to 503 `ErrorResponse` without the trusted bridge/resolver.
Once installed, a missing verified context returns 401. Known policy/authorization
denials return 403. Identity/ACL/policy/clock/storage/audit outages deny with 503.
Input schema failures return 422; internal faults return safe 500. Early failures
use `ErrorResponse`; 401/503 approval responses can be either `ErrorResponse` or
`GateDecision`, as documented in OpenAPI. Unknown routes return 404, wrong methods
405. Errors do not echo inputs, exception text, or tracebacks. No approval mutation
or execution route exists. `API_INTEGRATION.md` specifies the full trust boundary.

All observations keep their existing units and null semantics: CPU 0..100 percent,
RAM MiB, response milliseconds; null is unavailable, zero is measured. `logs=null`
is unavailable, `logs=[]` collected-empty. Timestamps must be aware when supplied.
Source `mock`/`real` is a producer declaration, not proof of provenance or a trigger
for a provider request. A report cannot represent mixed real/mock inputs.

## Sanitized examples and demo

Paths below are relative to `C:\git\shared\infra-pilot\apps\liara\triage\`:

| Scenario | Request | Response |
| --- | --- | --- |
| Database / HTTP 500 | `examples/mock_db_http500.request.json` | `examples/mock_db_http500.response.json` |
| CPU / latency | `examples/mock_cpu_latency.request.json` | `examples/mock_cpu_latency.response.json` |
| Healthy / incomplete | `examples/mock_healthy_incomplete.request.json` | `examples/mock_healthy_incomplete.response.json` |
| Pending sensitive action | `examples/mock_sensitive_pending.request.json` | `examples/mock_sensitive_pending.response.json` |
| Authorization denial | `examples/mock_authorization_denied.request.json` | `examples/mock_authorization_denied.response.json` |

All were already serialized from actual models/engine/gate and remain unchanged.
The pending pair uses Python `request_approval`, not an HTTP route. The denial pair
uses a configured real gate without authentication; default HTTP instead returns
503 for absent integration. Do not confuse these two response contexts.

`python -m infrapilot_triage.demo --mock` reuses these requests and adds a private
in-process two-actor MOCK approval story. It opens no listener and performs no
provider request or execution. See `DEMO.md` for the reproducible five-minute
walkthrough, exact commands, statuses, and structured output fields.

## Fatima: setup compatibility findings

Inspected `setup/triage.py`, `setup/TRIAGE_COMPATIBILITY.md`, and the published
application boundary at the revision above. The actual optional consumer already
imports `ServiceSnapshot`, `DiagnosisReport`, and `diagnose` from this package.
`SnapshotEvidence(snapshot, association)` wraps the canonical snapshot with a
Setup `DependencyInput`. `prepare_diagnosis` validates target, metadata, source,
current request fingerprint, and canonical payloads, then calls Python diagnosis.
`submit_problem` / `supply_problem_information` return `DiagnosisWorkflow`.
`DiagnosisPresentation` preserves the report and binding with execution flags false.

This is compatible with the unchanged Python contracts by source inspection. No
Setup test execution or actual Setup-to-HTTP call was performed. The inspected
branch contains compatibility implementation, not an implemented approval UI or
trusted approver backend; its name alone does not establish approval support.

For future integration:

- Supply genuine associated observations, exact target identifiers, and complete
  brief metadata. Keep source mapping `mock -> mock`, `external -> real` explicit.
- Preserve Setup's `setup-integration-v1` wrapper; do not insert its request ID,
  revision, digest, or provenance fields into `ServiceSnapshot`/`DiagnosisReport`.
  Triage's v0.1 proposal label is not that wrapper version or a freshness proof.
- Python diagnosis is already usable with the installed package. An HTTP consumer
  is not implemented in the inspected Setup source. If proposed, POST the exact
  snapshot and validate `DiagnosisReport`, retaining Setup association outside it.
- Sanitize observations before establishing the association/digest. The HTTP API
  redacts recognizable credentials before diagnosis and declares that redaction;
  direct Python `diagnose` preserves logs. Do not assume byte-identical reports
  from unsanitized Python and HTTP inputs or ignore changes in a bound snapshot.
- Display evidence links, heuristic ranking, source, missing data, conflicts,
  approval labels, and `not_executed`; preparation readiness is not authorization.
- Supply reviewed mappings from recommendation to canonical `ActionIntent`,
  verified identity/ACLs and an explicit different approver, and bindings to the
  current Setup brief/report. Neither a digest, proposal flag nor UI approval is
  proof of authority. No mapping is implemented by this task.

## Roham: provider compatibility findings

Inspected `provider/models.py`, `provider/observability.py`,
`provider/CAPABILITIES.md`, and exports at the revision above. Unlike the earlier
Setup note that mentions only ping/projects, the current provider publishes
read-only `get_service`, `get_deployment_status`, `get_logs(..., since=...)`,
`get_metrics`, `list_releases`, and `collect_service_observations` methods.
This is an inspection of implementation and its capability report, not independent
verification of live Liara connectivity, account permissions, or endpoint behavior.

`ProviderResult[ServiceObservations]` is **not** `ServiceSnapshot`:

| Provider data | Gap / required agreed normalization |
| --- | --- |
| `service_name`, `provider_id` | Agree a stable exact triage/setup identifier; policy IDs are narrower than snapshot text IDs |
| Native status and `is_deployed` | Deployment/native state does not prove application health; preserve unknown without an agreed mapping |
| `MetricSeries.values`, null CPU/memory units | Sample layout, timestamps, and units are opaque; do not guess a last sample, percent, MiB, or clamp values |
| `ServiceLog.message/native_type/native_datetime` | Message may be null; level and aware timestamp mapping/sanitization need agreement; do not invent content |
| `Observation.availability`, errors, collection times | Preserve partial failures and observation context in a reviewed wrapper; snapshot has no fields for per-source errors, windows, or truncation |
| `success=false` with non-null partial data | Some observations may still be usable; success alone must not erase partial evidence or imply complete collection |
| Provider transport HTTP status / latency | These describe provider requests, not service application HTTP status or website response time; never populate those fields from transport errors/ping |
| `is_mock` | Require consistent source across accepted observations; `real` is still a declaration, not verified provenance |

A trusted, separately reviewed normalizer is still required. For fields without
verified units/semantics, use null/unknown; failed or skipped logs must not become
`[]`. Collection timestamps do not prove all observations share a time window.
No normalizer or provider call is implemented here. The illustrative partial
fixture in QA tests is synthetic snapshot input, not a second provider schema.

## QA coverage, reliability, and limitations

- All previous 313 tests are unchanged. New tests exercise actual FastAPI and
  engine/gate logic: database/500, CPU/latency, high RAM with/without OOM, healthy
  incomplete, missing logs/metrics, provider-like partial data, invalid envelopes,
  sensitive recommendations, source labels, evidence IDs, ranking, limitations,
  and non-execution.
- API security checks cover wrong service/operation/parameters, exact expiry,
  eight concurrent attempts across two API/gate instances sharing one store,
  identity/ACL outages, audit append and transaction-commit rollback, isolated
  defaults, unknown recommendation IDs, plus all original forged identity,
  missing dependency, unknown operation, replay, and safe-error tests.
- A reproduced HTTP regression showed escaped quotes could truncate credential
  redaction and expose the remaining suffix. The narrow redaction fix consumes
  escaped characters within quoted values. It changes no schema or core rule.
  Pattern redaction remains defense in depth, not complete secret detection.
- Demo tests verify explicit opt-in, actual reports, distinct MOCK approval,
  single consumption, replay denial, no provider connection/process execution,
  structured CLI output, and no changes to the default app's dependencies.
- Complete suite: **350 passed**, one warning on each of Python **3.14.7** and
  **3.12.13**, using Pydantic 2.14.1, FastAPI 0.159.1, Starlette 1.9.0, HTTPX 0.28.1,
  and pytest 9.1.1. Python 3.11 and 3.13 are not installed and were not tested.

Exact test commands from the canonical module:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.tmp\qa-py312\Scripts\python.exe -m pytest -p no:cacheprovider
```

The second command uses the fresh ignored module-local environment created from
the discovered Python 3.12.13 runtime. To reproduce with an installed 3.12:

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
py -3.12 -m venv .tmp\qa-py312
$triageOriginalTemp = $env:TEMP
$triageOriginalTmp = $env:TMP
try {
    $env:TEMP = (Resolve-Path .tmp).Path
    $env:TMP = $env:TEMP
    .\.tmp\qa-py312\Scripts\python.exe -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 dependency installation failed.' }
} finally {
    $env:TEMP = $triageOriginalTemp
    $env:TMP = $triageOriginalTmp
}
.\.tmp\qa-py312\Scripts\python.exe -m pytest -p no:cacheprovider
```

Warning inspection: installed `starlette/testclient.py` tries `httpx2` first, then
uses installed HTTPX and emits `StarletteDeprecationWarning`. The existing HTTPX
transport passes the full suite on both runtimes. No dependency upgrade, alternate
transport installation, version pin downgrade, or warning suppression was used.
Any transport migration should be validated against the declared FastAPI range
before changing dependencies; the warning remains documented and visible.

Before a real demo, the team must agree the normalization/association/version
contracts, provide sanitized genuine observations and real connectivity checks,
install verified identities/current target ACLs, build the independent approval
workflow, and supply durable atomic shared audit/storage. A separately reviewed
executor would be needed for any real remediation; authorization receipts cannot
be sent back later as bearer permission, and consuming a grant does not execute
anything. Network deployment additionally needs transport/access controls and
bounded workloads described in `API_INTEGRATION.md`. None of these prerequisites
is replaced by this MOCK QA demonstration.
