# Setup / Diagnosis / Approval integration handoff

This stage completes the existing Setup workflow at `setup/`. It consumes actual
published producer implementations, preserves the previous intake/completion
functions and does not implement a Diagnosis engine/API, policy rules, incident
UI, provider adapter, authenticator or executor.

Later opt-in continuation: [COLLECTION_CONTEXT_COMPATIBILITY.md](COLLECTION_CONTEXT_COMPATIBILITY.md)
preserves Provider's draft context beside evidence/Diagnosis on a topic stacked
over PR #9. That document records its newer exact producer pins and checks;
the source history and results below remain this approval stage's checkpoint.
The new context consumer uses only this workflow's disabled-readiness view and
does not request/approve/reject/consume an authorization or enable execution.

## Actual source history and dependencies

Verified through the selected local clone and authenticated origin access:
`C:\Users\FATIMA\GitHub\infra-pilot`,
`https://github.com/nothingness-dev/infra-pilot.git`.

| Source | Full SHA |
| --- | --- |
| Main integrated/tested by compatibility | `0ef27606a2500df334a651a63f57a7ecc492a441` |
| Final refreshed tracked main | `9f244f93445cf59600db96e16a61980df87284ec` |
| Preserved Setup application boundary | `c5d037b657e7970a3d34c59ce1a28e4ce7b10463` |
| Diagnosis, `feature/liara-diagnosis-engine` | `ce19889a7c220f2d63e7036851f3178e389423c3` |
| Approval, `feature/liara-approval-policy` | `835e557b9d97f59522a88527117f759c9779f9d1` |
| Newer Diagnosis API, `feature/liara-triage-api` | `428237de83631035439afa4d78d9f68f863942b9` |
| Provider observability, merged in main | `799c752a038a6a5ec1697411bbefb77161457e72` |
| Completed `feat/setup-triage-compatibility` dependency | `a9d7482e0a1f67a396b5cd98609b217eeb13079f` |
| Approval behavior commit on `feat/setup-approval-workflow` | `62a1c740862f9aa7d1d00b941e4dc747956ed9dd` |

The compatibility branch retains its previously published commits `8e3b49e`
(merge of the required Approval history) and `56df8f8` (canonical Diagnosis
consumer). New published provider history from main is integrated only into
that topic by `0be6213`, and API history by `7aa8f66`. Commit `a9d7482` adds API
response consumption. The approval branch, previously at `56df8f8`, fast-forwards
to that compatibility tip and adds the lifecycle consumer plus this demo/handoff.
There is no reset, rebase, force-push, teammate branch rewrite or PR merge.

Draft PR dependency: compatibility -> `feature/liara-triage-api`; approval ->
`feat/setup-triage-compatibility`. The compatibility PR also inherits the provider
history already merged into main; those files are identical to main checkpoint
`0ef2760`, not Setup edits. Final main adds the teammate's live-smoke runner in
PR #7, with unchanged provider contracts/client/observability. Its unrelated
history is not merged into our topics and its opt-in runner is not executed.
Triage files are identical to the actual API source branch.
Only new Setup-owned files/documentation are edited or explicitly staged.
The existing teammate stack is API PR #6 -> Approval PR #4 -> Diagnosis PR #3 ->
foundation PR #2 -> main. None of those PR heads/bases are changed by this task.

The initial empty-history messages are obsolete: main exists, has the original
Setup through merged PR #1, and was updated with fetch/prune/tags and tracked
`pull --ff-only`. No main/common-base creation is required. Prior non-overwriting
local personal-name removals preserved all four exact SHAs; see
[TRIAGE_COMPATIBILITY.md](TRIAGE_COMPATIBILITY.md). Three remote renames are done.
The remaining old remote default `feat/liara-fatima-setup-foundation` at
`9c6e7229e126f203369c901638a6d06e8aa5b370` needs an owner/admin's native rename
to `feat/liara-setup-foundation`; authenticated access is WRITE. The local clean
topic name still tracks that unchanged remote. No open PR head/base uses it.
Do not delete the published ref or change the default to hide this pending item.

## Supported flow and exact compatibility

`setup.application.submit_request()` and `supply_information()` remain intact.
`setup.triage.submit_problem()` and `supply_problem_information()` reuse them:
complete valid problem -> supplied associated ServiceSnapshot -> actual Diagnosis
engine -> structured presentation. Missing evidence yields `evidence_required`;
incomplete observations still produce the actual report's missing-information
and limitations. No synthetic evidence is inserted by the implementation.

Alternatively, server orchestration calls the already published
`POST /internal/triage/diagnose` and passes its response to
`setup.diagnosis_api.consume_diagnosis_response(request, evidence,
status_code=..., payload=...)`. The consumer validates the actual DiagnosisReport
and preserves every evidence item/link, ranking, hypothesis, action, limitation
and source. It does not reconstruct a report or make another HTTP API. Failed
status/body/model/target/source checks yield safe SetupIntegrationError records.
The API's actual sanitizer is reused for the retained snapshot so presentation
does not redisplay raw logs beside a redacted report. Core direct-engine callers
must independently supply sanitized observations. No log sanitizer proves that
arbitrary application secrets are absent.

The detailed snapshot/report/provisional-envelope mapping is in
[TRIAGE_COMPATIBILITY.md](TRIAGE_COMPATIBILITY.md). Important approval differences:

| Concern | Producer's actual contract | Setup association / behavior |
| --- | --- | --- |
| Proposal vs operation | ActionProposal ID/title/risk/approval flag is advisory; status only `not_executed` | A reviewed backend mapping must explicitly supply ActionIntent; no automatic ID-to-restart/configuration dispatch |
| Target | Canonical service ID is exact ASCII, max 128, narrower than snapshot text | Must equal report/snapshot/current request target; incompatible producer IDs need a reviewed resolver, not trimming or fuzzy matching |
| Parameters | Policy canonicalizes defaults and validates its own allowlist | Reuse actual ActionPolicy through ApprovalIntegration.evaluate; no duplicate policy or provider capability assertion |
| Version / hash | CanonicalAction has policy_version `triage-approval-v1`, SHA-256 fingerprint over service/type/canonical parameters | Retain canonical action unchanged and add full Setup brief fingerprint plus Diagnosis binding and proposal ID |
| Approval request identity | ApprovalRequest.request_id is a UUID for approval, not the Setup workflow ID | Keep both IDs separately; server registry binds approval ID to exact request, Diagnosis, proposal, canonical action/version |
| Actor | requested_by / approved_by / rejected_by are AuthenticatedActor outputs of an installed IdentityBoundary | Pass opaque verified server authentication context into the real gate; never accept subject/role/boolean fields as identity |
| Time | Aware UTC created_at/expires_at; default producer TTL 5 minutes; exact deadline expires | Preserve timestamps; producer gate checks expiry/clock, not a frontend timer. Snapshot/report timestamps have different semantics |
| Approval lifecycle | pending, approved, rejected, expired, consumed | Present actual gate reason/state; Setup never invokes authorize or consumes an approval |
| Permission vs execution | Transition decisions have allowed=False; authorize can return `authorized_not_executed` | Setup does not call authorize; all outcomes retain execution_authorized=False and execution_performed=False |

Bindings are integrity/association hashes, not signatures, access control or
bearer tokens. Mutable canonical reports/intents are revalidated before use;
changed request, snapshot, report, proposal, parameters, target or policy version
cannot reuse a prior binding. Backend objects and registry remain inside trusted
server composition; presentation JSON is never accepted as a binding credential.

## Approval interface and actual states

`SetupApprovalWorkflow(gate=actual_gate, policy=actual_policy)` is installed only
by trusted server code. Its default gate lacks identity/store and fails closed.
`review_action(request, presentation, proposal_id, intent=reviewed_intent)` uses
the producer's informational bridge. It returns ActionReview with
`state=policy_decision_returned`, unchanged PolicyDecision and
`approval_reason=approval_required` or `approval_not_required` for allowed
classifications. Classification's allowed=True means only policy classification,
not current target permission or execution authorization.

`request_approval(binding, request=..., presentation=..., authentication=...)`,
`approve(binding, approval_request_id, ...)` and `reject(...)` delegate to the
actual gate. `ApprovalUpdate.state` is exactly its DecisionReason.value:

- `approval_pending`, `approval_approved`, `approval_rejected`, `approval_expired`.
- `unauthenticated`, `identity_unavailable`, `not_authorized`,
  `policy_unavailable`, `storage_or_audit_unavailable`, `self_approval_denied`,
  and other producer reasons when those prerequisites fail.
- Missing/unknown/restart-lost Setup approval association raises a structured
  `request_not_found`; changed bound action/proposal/request raises
  `action_mismatch`, `stale_binding` or the precise Diagnosis association error.
  Malformed producer transition decisions fail as `invalid_gate_decision`.

On SetupIntegrationError, trusted transport code may serialize
`dataclasses.asdict(error.error)` as an error object and render execution disabled;
it must not reinterpret an error or missing binding as permission. Gate errors
preserve audit_recorded=False when the producer cannot record the denial. No
authentication context, raw exception or submitted arbitrary value is serialized.

An approved request may be rejected before consumption, as supported by the actual
gate. Rejection/expiry remain terminal. This stage never calls the consuming
authorization route, creates an executor, or reports deployment/restart success.
`execution_readiness()` always says execution_disabled with concrete missing
authentication/ACL, durable storage, capability-validation and executor blockers.

The real gate's InMemoryApprovalStore and Setup's approval-to-workflow dictionary
are volatile and local to one process. A restarted workflow refuses old IDs even
if a separately retained approval store still has them. Neither layer is a
production durable/distributed approval system. There is no persistent request
repository, approval polling API or real authentication backend in Setup.

## Main shell and incident component proposal

This is a proposed composition contract for team agreement, not a frontend
implementation or shared application registration. Setup's main shell owns
problem intake/completion, navigation, selected request, loading/errors, passing
backend presentation to the incident component and showing the global execution
blockers. The triage owner keeps the incident component: evidence/hypothesis
presentation, limitations, mock labels and proposal/approval controls. No incident
UI files or competing page/component are added here.

Suggested incident-component props, passed from the shell:

| Prop | Value / constraint |
| --- | --- |
| requestId, requestFingerprint, diagnosisBinding | Association identifiers for display/stale-response handling; never authorization tokens |
| report, snapshot, source | Entire validated report and sanitized nullable snapshot; mock/real declaration visible; provenance_verified remains false |
| missingInformation, limitations | Preserve full producer text, uncertainty/conflicts and heuristic confidence wording |
| selectedProposalId, actionReview | Selected advisory proposal and backend-reviewed canonical action/parameters/version; policy classification clearly distinguished from permission |
| approval | Latest actual gate reason, UUID, lifecycle state, expiry and audit status from the backend |
| busy, errors, execution | Controlled request state, safe structured errors and always-disabled execution with blockers |

Suggested asynchronous callbacks (proposals only; no new routes):

```text
onReviewAction({requestId, diagnosisBinding, proposalId, reviewedMappingReference})
onRequestApproval({requestId, diagnosisBinding, proposalId})
onApproveAction({requestId, approvalRequestId})
onRejectAction({requestId, approvalRequestId})
onRefreshDiagnosis({requestId})
```

The shell calls its future trusted backend for each event and replaces controlled
props from the returned view. Backend reloads its own request/presentation/binding,
verifies current session/target ACL and resolves the reviewed operation mapping;
it never trusts returned JSON, user/role fields, a client fingerprint or an
`approved:true` value. Approve/reject are distinct authenticated commands by an
independent authorized actor. No onExecute callback is supplied. Do not poll
`/internal/triage/authorize`, since that route consumes authorization.

## Concrete producer/shared requests and remaining dependencies

- Roham: publish an agreed ServiceObservations -> ServiceSnapshot normalization
  boundary or propose explicit shared extensions. Native `cpuUsage.value=["0.25"]`
  with unknown units is not 0.25% or 25%; native memory is not established MiB.
  Native running/deployed is not healthy. Preserve per-component errors, including
  partial success and permission-denied logs, collector vs source time, null vs
  empty logs, sanitization and window/completeness metadata. No fabricated source
  measurement or live-access claim fills these gaps.
- Setayesh: agree proposal-to-canonical-operation mapping and policy versioning.
  `review_resource_configuration` does not itself mean `change_resources` or
  specify CPU values. The demo's explicit CPU mapping is synthetic only. Agree
  report/schema revisions and trusted service identity resolution. Existing API
  has no approval lifecycle HTTP routes; propose their owner/session/CSRF/error
  contract before wiring the callbacks. Do not use authorize as an approval API.
- Composition owners: supply real credential/session verification, active account
  and exact target ACLs, independent approvers, durable transactional approval/audit
  and workflow-binding storage, request retention, freshness/access policy, safe
  HTTP client settings and shared application registration. This stage changes
  none of those components. The existing default app's privileged routes remain
  disabled; real operation capabilities/parameter semantics and a separately
  reviewed executor remain required. Policy approval alone executes nothing.

## Reproduce checks and offline example

Use the Setup-owned ignored environment described in TRIAGE_COMPATIBILITY.md;
it installs the actual producer dependency ranges without editing shared manifests
or generating an editable install in producer paths. On Windows/Python 3.14.8:

```powershell
$env:PYTHONPATH = (Resolve-Path apps/liara/triage/src).Path
setup/.venv/Scripts/python.exe -B -m unittest discover -s setup/tests -t . -v
Push-Location apps/liara/triage
try {
    ..\..\..\setup\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
} finally { Pop-Location }
setup/.venv/Scripts/python.exe -B -m setup.examples.approval_demo
python -B -m setup.examples.offline_demo
git diff --check
git diff --exit-code origin/feature/liara-triage-api -- apps/liara/triage
git diff --exit-code 0ef27606a2500df334a651a63f57a7ecc492a441 -- provider
```

Actual final results: **83 Setup tests, 313 triage tests passed**. The 53 original
Setup cases remain unchanged; the prior compatibility added 9, the API consumer
adds 7, and approval adds 14. All actual producer tests run, including the original
238 core cases and 75 API cases. The API tests use FastAPI TestClient in-process;
the approval tests use the actual policy/gate/store with an explicitly test-only
opaque-session identity boundary and deterministic UTC clock. They do not mock
authorization decisions or authenticate real users. The only warning is the
documented Starlette HTTPX TestClient deprecation. Versions are recorded in the
compatibility document. No authenticated live Liara call or browser/UI check is
claimed; no incident UI exists in the inspected tree to verify here.

The new demo reports MOCK diagnosis -> approval_required -> pending -> approved
(not executed) -> rejected/revoked, plus default unconfigured refusal. Identity
and CPU parameters are synthetic fixtures; real_operations_performed is false.
The original thirteen-scenario offline preparation example is preserved.

## پیام هماهنگی

ستایش: Setup گزارش کامل Diagnosis و پاسخ API موجود را با حفظ evidence، رتبه‌بندی،
محدودیت و provenance مصرف می‌کند. Approval از policy/gate واقعی گرفته می‌شود و به
درخواست، هدف، گزارش، proposal، پارامتر و نسخه متصل است. برای incident component،
props و callbackهای پیشنهادی بالا را بررسی کن؛ پیاده‌سازی UI یا API دیگری اضافه نشد.

رهام: observability جدید خوانده و fixture واقعی‌اش بررسی شد، اما status بومی، واحد
متریک و زمان/نوع log هنوز نگاشت توافق‌شده به ServiceSnapshot ندارند. این فیلدها را
حدس نزده‌ام. main shell فقط intake و هماهنگی backend/incident را نگه می‌دارد؛
احراز هویت واقعی، ذخیره‌سازی پایدار، API چرخهٔ approval و اجرای واقعی هنوز وابستگی
مرحلهٔ بعد هستند. تأیید policy هیچ عملیاتی روی Liara اجرا نمی‌کند.
