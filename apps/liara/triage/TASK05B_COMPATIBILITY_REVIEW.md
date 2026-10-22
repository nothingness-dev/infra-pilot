# Task 05B compatibility review — internal DRAFT, audit first

This is a review artifact, not approval of a shared contract. The current six
schemas, diagnosis/approval logic, and HTTP routes are unchanged. No new context
schema, endpoint, trusted service resolver, or execution boundary is implemented.
The matrix was recorded before any conditional integration implementation.

## Exact sources

| Source | Status and inspected revision |
| --- | --- |
| Provider PR #10 | MERGED into main as `cc20096285a34ffd5e8c622612b8804953216b37`; head `16838ba0a3acd5b75f9481c381216bda4c7a15c1` |
| Setup PR #8 | OPEN; `feat/setup-triage-compatibility` at `a9d7482e0a1f67a396b5cd98609b217eeb13079f` |
| Setup PR #9 | OPEN; `feat/setup-approval-workflow` at `929574dcde9e95e60c5a5889b5257612589c5a2c`; includes PR #8 |
| Triage PR #11 | OPEN; `feature/liara-triage-qa-demo` at `d65f4b76ed44d32090a982c26af9b0a8a534d72d` |
| Triage API dependency, PR #6 | OPEN; `428237de83631035439afa4d78d9f68f863942b9` |

Provider/setup sources are inspected read-only from Git objects. Any test copies
are confined to ignored triage `.tmp` directories, pinned to the exact sources;
no teammate files or branches are changed. No live credentials or provider calls
are needed for the review. Current main contains provider but not the newer
Setup consumers; review uses the actual open topic revision, not assumed main.

## Compatibility matrix and ownership

| Concern | Classification | Exact interface / mismatch | Required owner action |
| --- | --- | --- | --- |
| Snapshot transport | Compatible | `provider/triage.py:TriageSnapshot.to_request()` -> `apps/liara/triage/src/infrapilot_triage/schemas.py:ServiceSnapshot` -> `api.py:POST /internal/triage/diagnose` | Keep existing snapshot JSON and nulls unchanged |
| Report consumption | Compatible with an adapter | `setup/diagnosis_api.py:consume_diagnosis_response(request, evidence, *, status_code, payload)` validates `DiagnosisReport` and calls `setup/triage.py:consume_diagnosis` | Trusted composition supplies actual response and exact request association; no frontend report trust |
| Unknown telemetry / withheld logs | Compatible | Provider sets health unknown; CPU/RAM/HTTP/latency/time null; nonempty logs withheld by default; `TriageHandoff.logs_exported/logs_withheld` retain counts | Provider owns reviewed log sanitizer and future verified unit/status mappings; no guessed values |
| Collection failures | Requires contract change at the contextual transport/presentation boundary | Provider `TriageHandoff.capabilities: CollectionSummary` stores availability/error_code/http_status/collected_at; full handoff is not `ServiceSnapshot`; neither `DiagnosisReport` nor Setup `SnapshotEvidence`/`DiagnosisPresentation` has collection context | Provider/Triage/Setup agree how one structured sidecar survives transport and presentation |
| Service/project identity | Blocked by missing dependency | `TriageAdapter.collect(name, *, service_id=...)` / `from_observations(..., service_id=...)` accept a caller-selected valid internal alias; no resolver verifies its relationship to `ServiceObservations.service_name` | Trusted composition/Provider owner supplies verified mapping; Triage/Setup require exact target correlation; do not infer names |
| Snapshot/context correlation | Requires contract change | Current `TriageHandoff` embeds snapshot, but has no versioned trusted mapping reference or snapshot digest; Setup binding covers only snapshot/report/association, not capability errors/counts | Agree versioned companion and correlation validation; a digest is not identity/authentication proof |
| Action/service/parameter policy binding | Compatible | `setup/approval_workflow.py:SetupApprovalWorkflow` delegates actual policy/gate; `policy.py:CanonicalAction` includes exact service/type/parameters/policy_version/fingerprint | Keep canonical action immutable and check exact target |
| Report/proposal binding at authorization consumption | Compatible with a required trusted adapter; currently blocked by missing dependency | Setup `BoundAction` includes request/report/proposal bindings and validates them for review/request/approve/reject. `authorization.py:ApprovalGate.authorize` accepts only intent, verified context, approval ID; it has no report/proposal/Setup binding parameter | Setup/Triage/composition agree a server consumption port that rechecks current workflow bindings immediately before gate authorization; current execution remains disabled |
| Identity / approval actor | Blocked by missing dependency for live use | `IdentityBoundary.authenticate/is_authorized` is a trusted port; gate binds requester, checks independent approver and current scoped permissions; Setup stores no authenticated session itself | Composition supplies real verifier, exact target ACLs and durable shared state; body IDs/roles cannot satisfy this |
| Versions | Requires explicit agreement for companion integration | Setup wrapper uses `setup-integration-v1`; gate fingerprints `triage-approval-v1`; API documents draft v0.1 but snapshot/report have no version field; provider sidecar has no version field | Keep these meanings separate; agree companion version and binding inputs, not a silent schema change |
| Execution | Compatible, disabled | Default HTTP approval routes return 503; Setup `execution_readiness()` always disables operations; no executor in triage | Do not enable operations while dependencies/bindings are unresolved |

The existing gate is intentionally an action authorization boundary. Its lack of
Setup-specific report/proposal fields is not a demonstrated bypass in the current
disabled system. A future caller that invokes the gate without Setup's current
binding validation would omit those workflow constraints. Do not advertise that
future consuming boundary as already integrated or implement it by inference.

## Confirmed exported interfaces and paths

- `provider/__init__.py` exports `MockLiaraClient`, `TriageAdapter`, `TriageHandoff`,
  `TriageSnapshot`, `TriageLog`, `CollectionSummary`, and `LogSanitizer`.
  `TriageAdapter.collect(name, *, service_id, logs_since=None, log_sanitizer=None)`
  returns `ProviderResult[TriageHandoff]`; `from_observations` projects an existing
  bundle. `TriageSnapshot.to_request()` is the diagnosis body;
  `TriageHandoff.to_dict()` is the separate collection sidecar.
- `apps/liara/triage/src/infrapilot_triage/__init__.py` exports `ServiceSnapshot`,
  `DiagnosisReport`, `ActionIntent`, `ActionPolicy`, `ApprovalGate`, `GateDecision`,
  and `diagnose`. `api.py:create_app` installs trusted dependencies only through
  Python composition. `approval_integration.py:ApprovalIntegration.evaluate`
  classifies; `.authorize` delegates to the existing gate, never execution.
- `setup/triage.py` exports `SnapshotEvidence`, `DiagnosisPresentation`,
  `prepare_diagnosis`, `consume_diagnosis`, and `validate_presentation`.
  `setup/diagnosis_api.py:consume_diagnosis_response` accepts the existing HTTP
  report. `setup/approval_workflow.py` defines `BoundAction`, `ActionReview`,
  `ApprovalUpdate`, and `SetupApprovalWorkflow.review_action/request_approval/approve/reject`.
  Setup deliberately does not consume authorizations.

Existing routes remain `GET /health`, `POST /internal/triage/diagnose`,
`POST /internal/triage/policy/evaluate`, `POST /internal/triage/authorize`, and
`GET /openapi.json`. There is no approval lifecycle/execution HTTP route.

## Optional context: compared options, none implemented

| Option | Consumer impact / risk | Assessment |
| --- | --- | --- |
| Existing `/diagnose` accepts snapshot OR `{snapshot, context}` envelope | Existing requests could remain valid with a union, but OpenAPI/request dispatch and response semantics change; Setup currently sends/validates bare canonical models | Do not silently widen the current endpoint or insert context into `DiagnosisReport` |
| Separate contextual internal endpoint | Leaves old endpoint stable, but creates a new transport, response schema, authentication/deployment and Setup adoption decisions | Defer until all consumers agree; no new endpoint in this audit |
| Trusted server keeps companion beside unchanged snapshot/report | Smallest transport impact; existing API works unchanged, but Setup must explicitly retain/validate/render the companion and current workflow binding must include it | Recommended discussion starting point, not an approved or implemented integration |

Any proposed companion should retain **one** `capabilities` collection with its
safe errors/status/times, provider limitations, collection start/end, and existing
`logs_exported`/`logs_withheld` counts. Do not introduce a second conflicting
`collection_errors` source, flatten failures into text only, or transport raw
provider errors/bodies. Distinguish withheld counts from guaranteed permanent
discard: provider currently reports withheld entries, not a retention policy.

Before adoption, agree an explicit version, internal service ID, trusted mapping
reference, and correlation to the exact sanitized snapshot (for example a canonical
digest within trusted orchestration). Retain provider source classification; a
hash or claimed `service_id` is not provenance verification or authorization.
Define how Setup's current report/proposal/request binding includes this context.

## Stop condition and implementation decision

The supplied Task 05B requires stopping if unresolved mismatches could cause
incorrect service identity, lost collection failures, or authorization bypass.
The missing structured companion consumer and trusted mapping/consumption ports
meet that condition for full semantic integration. Merely dropping the sidecar
would preserve syntax but lose permission/failure/log-loss information. Merely
using a caller-selected alias would not validate a provider project association.

Therefore only read-only compatibility/audit checks may continue; no conditional
production implementation, new context contract/endpoint, feature-branch commit,
push, or PR is authorized by the safe-path condition yet. This stop comes from
the user's Task 05B request, not an inferred AGENTS.md approval requirement.

## Verification record

All checks below ran against unchanged implementations, not replacement diagnosis
or policy functions. Provider/Setup source copies match the exact Git archive
bytes: 22 provider files at `16838ba0a3acd5b75f9481c381216bda4c7a15c1` and 33 Setup
files at `929574dcde9e95e60c5a5889b5257612589c5a2c`. SHA-256 verification manifests
are in ignored `.tmp/task05b_sources/manifest.json`. Import paths select those
copies and current triage source. Tests do not modify the source copies or the
original teammate paths. The explicit audit probes forbid external connections
and process execution; observation/session fixtures remain synthetic MOCK data.

| Suite | Runtime | Result |
| --- | --- | --- |
| Existing triage suite | Python 3.14.7 | 350 passed, 1 warning, 5.77s |
| Existing triage suite | Python 3.12.13 | 350 passed, 1 warning, 6.84s |
| Actual Provider tests (98), Provider compatibility QA (4), actual Setup tests (83), audit probes (17) | Python 3.14.7 | 202 passed, 1 warning, 4.55s |

The warning is the existing Starlette/HTTPX TestClient deprecation; no dependency
upgrade, suppression, or environment recreation was performed. Python 3.11 and
3.13 were not tested. All previous 350 triage cases, core source, serialized
examples, schemas, routes, and approval behavior are preserved unchanged.

Exact commands from the canonical triage module, after the ignored source-copy
preparation script `.tmp/task05b_export.py` (it verifies every copy and refuses
conflicting existing files):

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B .tmp/task05b_export.py
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.tmp\qa-py312\Scripts\python.exe -m pytest -p no:cacheprovider
$triagePreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = 'C:\git\shared\infra-pilot\apps\liara\triage\.tmp\task05b_sources\provider-16838ba;C:\git\shared\infra-pilot\apps\liara\triage\.tmp\task05b_sources\setup-929574d;C:\git\shared\infra-pilot\apps\liara\triage\src'
    .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider .tmp/test_task05b_audit.py .tmp/task05b_sources/provider-16838ba/provider/tests .tmp/task05b_sources/provider-16838ba/provider/qa .tmp/task05b_sources/setup-929574d/setup/tests
} finally { $env:PYTHONPATH = $triagePreviousPythonPath }
```

These are locally retained audit artifacts under `.tmp`, not a new committed
integration harness. No success claim is made for a missing contextual contract.
Passing probes deliberately verify both compatible behavior and the gaps:

1. Actual `MockLiaraClient` -> `TriageAdapter` -> existing HTTP diagnosis ->
   actual Setup `consume_diagnosis_response` succeeds for the bare snapshot;
   source stays MOCK and every proposal stays `not_executed`.
2. Provider 401/403/404 capability errors are correctly structured in the handoff,
   but those outcomes are absent from the report/Setup presentation. Provider 403
   and 404 cases produce identical snapshots, reports, and Setup binding hashes
   under the same reference/association, despite different collection failures.
3. Full sidecar and an unagreed `{snapshot, context}` envelope both yield 422 at
   the existing endpoint. Backward-compatible bare requests still succeed.
4. Nonempty default logs are withheld (count 1, exported 0, `logs=null`). Actual
   empty source logs produce `[]`; unavailable logs remain null. An explicit
   MOCK-only reviewed-log callback exports one line and withholds one synthetic
   credential line, preserving counts without forwarding that text. Setup's
   current presentation has no field for those loss counts/limitation codes.
5. Health and unverified CPU/RAM remain unknown/null; provider API errors never
   become application HTTP/latency evidence. No source timestamp is fabricated.
6. The provider accepts two syntactically valid internal aliases for the same
   mock project bundle, confirming trusted mapping is the caller's responsibility.
   Setup rejects a snapshot whose alias differs from its exact requested target;
   this equality check does not resolve project identity or verify provenance.
7. Actual Setup review/request/approve uses the real gate and retains the current
   report/proposal/action binding. Wrong-service or changed-parameter consumption
   is denied. A changed report causes Setup `stale_binding`; a separate direct
   call to the action gate can still consume the previously approved unchanged
   canonical action, since the gate has no report input. This proves the missing
   future consumption seam, not a current execution path or an infrastructure
   operation. The default sensitive HTTP route still returns 503.

Existing original tests cover additional invalid/incomplete data, unverified
identities, dependency outages, approval expiry/replay, and non-execution. The
new probes use actual module implementations; provider's checked-in JSON fixture
is separately validated by its four existing QA tests. No captured real Liara
response, real account authentication, or real infrastructure execution is used.

## Owner decisions and Incident UI readiness

Provider: define the trusted project-to-internal-service mapping input/verification
port; agree sidecar field meanings/version/correlation, log-sharing policy, and
future verified metric units. Keep errors structured under capabilities; preserve
unknown/nulls and counts. No credentials belong in the companion or shared model.

Setup: agree retention/rendering of the collection sidecar and bind it with the
current request/snapshot/report/proposal. Specify the trusted authorization
consumption boundary and how it revalidates current workflow bindings and caller
identity, including revocation and contract/policy versions, immediately before
the existing gate. No approval flag can replace those checks.

Triage/composition: after agreement, validate the proposed companion without
changing existing snapshot/report behavior, require a trusted mapping result,
and add wrong-service/correlation/stale-binding integration tests. Real verifier,
target ACLs, durable atomic approval/audit/workflow stores, and safe transport
remain missing live dependencies. No live Liara connectivity is claimed.

Incident UI can already consume the canonical report's evidence, ranked heuristic
hypotheses, limitations, missing information, source and non-executed proposals.
Setup can present its safe approval states while execution remains disabled.
The UI cannot yet claim complete collection-failure display, verified provider
identity, live measurements, or authorized remediation. No UI is built here.
