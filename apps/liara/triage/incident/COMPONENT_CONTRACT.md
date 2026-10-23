# Incident component contract — internal proposal

Status: **blocked on the shared frontend foundation**. This is a framework-neutral
component proposal, not an implemented UI, public API, approved shared contract,
or official Liara schema. See [READINESS.md](READINESS.md) for inspected revisions,
missing dependencies and validation results. No browser application, package,
route, dependency, design token or privileged transport is introduced here.

## Ownership and composition

The future `IncidentPanel` is a presentation feature owned by Triage. The parent
Setup/application workflow owns navigation, selected service, data fetching,
session/authentication, request revisions, server association, policy/approval
operations, retry scheduling and authoritative state. A browser component cannot
create backend trust by adding a `trusted` flag to props.

`apps/liara/triage/incident/` holds this proposal only. The implementation/import
path must be agreed with the shell owner after the actual frontend workspace,
framework and module resolution are published. Do not assume React, Next, Vite,
Tailwind, or create a separate app to fill that gap. No teammate source is copied.

## Proposed props and callbacks

The following notation describes readonly data, not executable TypeScript or a
new wire schema. `Wire<T>` means the **JSON serialization** of the named existing
Python contract, not its Python instance or a separately maintained UI model.
The eventual shell must define validated frontend types from those contracts.

```text
IncidentPanelProps {
  locale: "fa-IR"
  direction: "rtl"
  incidentKey: string
  revision: string
  serviceLabel: string | null
  resource:
    | { state: "loading" }
    | { state: "empty", reason: "no_service" | "no_report" }
    | { state: "invalid_data", code: "invalid_payload" | "association_mismatch" }
    | { state: "error", code: "network_unavailable" | "diagnosis_unavailable" }
    | { state: "ready", data: IncidentData }
  actionWorkflow: readonly ActionWorkflowEntry[]
  refresh: { enabled: boolean, disabledReason: string | null }
  onRefreshRequested?: (event: { incidentKey, revision }) => void
  onReviewRequested?: (event: { incidentKey, revision, proposalId }) => void
  onEvidenceSelected?: (event: { incidentKey, revision, evidenceId }) => void
}

IncidentData {
  report: Wire<DiagnosisReport>
  snapshot: Wire<ServiceSnapshot> | null
  context:
    | { kind: "absent" }
    | { kind: "unavailable", code: "invalid_context" | "context_not_available" }
    | { kind: "mock_preview", value: Wire<DraftContextualDiagnosisResponse> }
    | { kind: "setup_companion", value: Wire<CollectionCompanion.to_dict()> }
}

ActionWorkflowEntry {
  proposalId: string
  association: { incidentKey: string, revision: string }
  review: Wire<ActionReview.to_dict()> | null
  decision:
    | { kind: "unavailable" }
    | { kind: "setup_update", value: Wire<ApprovalUpdate.to_dict()> }
    | { kind: "authorization_result", value: Wire<GateDecision> }
  reviewControl: {
    state: "hidden" | "disabled" | "enabled" | "busy"
    disabledReason: string | null
  }
}
```

`incidentKey` and `revision` are opaque parent-controlled presentation identity,
not new fields on DiagnosisReport and not credentials. They prevent accidental
cross-selection rendering; the backend still verifies actual associations. The
parent must use a new revision when request, snapshot, report, context or action
association changes, discard late responses, and clear prior approval entries.
These revision and callback conventions require shell/Setup agreement.

`serviceLabel` is an optional display name from the current parent selection.
Always retain `report.service_id` beside it; never infer identity from a project
name. `snapshot=null` means no associated snapshot was supplied. A report alone
has **no health/status or observation timestamp**, so the panel must show status
as unavailable rather than infer it from summary, evidence text or hypotheses.

`actionWorkflow=[]` means no trusted workflow update was supplied. It does not
mean approval is unnecessary. Entries must refer to actions in this exact report.
Their Setup request/diagnosis/proposal/canonical-action associations are validated
by the parent/backend before delivery; the component must not construct ActionIntent
from proposal IDs, risk levels, titles or descriptions.

Each proposal has at most one workflow entry. `decision` contains the latest
parent-validated result, never simultaneous stale lifecycle and authorization
objects. The parent must associate a bare GateDecision with this exact proposal,
canonical action, policy version and current approval request before exposing it.
Within a result, approval state comes from request.state when present; outcome
comes from allowed/reason. An unavailable decision never invents a lifecycle.

Callbacks only signal navigation/review/refresh intent. They return no approval
or authorization result and receive no actor, role, token, canonical parameters
or browser-provided report. A click may display `busy` only after a parent prop
update; it cannot optimistically display approved, authorized or executed. Review
opens the parent-owned review flow. Approve/reject controls and their mutations
remain in that flow; this feature exposes no approve/reject/execute callback.

Missing callback, missing valid workflow association, unavailable backend or no
review capability means review is disabled/hidden with an explicit reason. An
enabled control is only a UX capability, never backend permission. The component
does not fetch any endpoint, call `/internal/triage/authorize`, poll authorization,
persist approval in browser storage, or accept URL/query/local-storage approval.

## Existing contracts and exact extraction paths

| Input | Source and serialized shape | Parent adaptation |
| --- | --- | --- |
| Existing diagnosis | `src/infrapilot_triage/api.py:create_app`, `POST /internal/triage/diagnose`: bare ServiceSnapshot -> bare DiagnosisReport | Keep response unchanged in `data.report`; retain only its associated sanitized request snapshot |
| Snapshot/report | `schemas.py:ServiceSnapshot`, `DiagnosisReport` | Validate enums, finite ranges, unique IDs, descending hypothesis confidence and existing evidence links; do not silently repair malformed payloads |
| Setup diagnosis | PR #13 `setup/triage.py:DiagnosisPresentation.to_dict()` | Extract `.report`, `.snapshot`; retain request_id/request_fingerprint/binding in parent state, not as proof supplied by the browser |
| Setup workflow | `setup/triage.py:DiagnosisWorkflow.to_dict()` | `.diagnosis` is a presentation or null; `evidence_required`, incomplete input and blocked states must not fabricate a report |
| Context preview | `collection_context.py:DraftContextualDiagnosisResponse` | `.diagnosis_report` must equal `data.report`; retain `.collection_context`, limitations and false trust/execution flags; visibly MOCK-only |
| Setup context | PR #13 `setup/collection_context.py:CollectionCompanion.to_dict()` | `.diagnosis.report` / `.snapshot` / `.collection_context` must match selected data; `production_readiness=unresolved`; this is an offline proposal, not a browser trust object |
| Policy review | PR #13 `setup/approval_workflow.py:ActionReview.to_dict()` | Keep `.policy_decision`, `.binding`, `.approval_reason`, and `.execution` distinct from approval and authorization |
| Approval update | Same file, `ApprovalUpdate.to_dict()` | Read `.gate_decision.request.state`, `.gate_decision.reason`, `.binding` and execution blockers; top-level `.state` is a decision reason, not ApprovalState |
| Consuming authorization | `approvals.py:GateDecision` | Parent may supply an existing trusted backend result for display; this is not a review/polling operation and must not be invoked by the component |

Wire details matter: canonical `GateDecision.action` has `parameters_json`, while
Setup's `_action()` serializer uses `parameters`. Do not blindly cast these shapes
to each other. Setup transition updates intentionally have `allowed=false` and
`authorization_id=null` even when request.state is `approved`.

The contextual HTTP endpoint is absent; do not fetch the proposed
`/internal/triage/diagnose-contextual`. Current privileged routes are unavailable
by default, and request/approve/reject HTTP endpoints do not exist. No response
transport, browser authentication or new shared wrapper is approved here.

## Layout and Persian RTL behavior

Use the shared shell's future font, spacing, surfaces, borders, focus, responsive
breakpoints and semantic status/risk tokens. Their concrete names and values do
not exist in the inspected repository. Do not introduce global CSS, colors or
fonts while waiting. Once published, prefer a scoped feature stylesheet and
logical properties such as padding-inline/margin-block.

Reading order, with matching DOM and keyboard order:

1. Header `گزارش رخداد`: optional service label, persistent identifier, last
   observed status, source badge, optional observation time and parent refresh.
2. Diagnosis summary and a persistent `هیچ اقدامی اجرا نشده است` notice.
3. Ranked hypotheses, each linking to exact supporting evidence in an evidence
   section. Preserve producer order, including ties; confidence is an
   `امتیاز اطمینان (ابتکاری)`, not a calibrated probability or proof of cause.
4. Recommended action cards: exact title/description, advisory risk badge,
   proposal approval hint, separate parent policy/approval/authorization display,
   and an optional parent review entry point.
5. Missing observations and all diagnostic limitations.
6. When context exists, collection capabilities/errors, log accounting and
   context limitations, without replacing the report's original limitations.

Every heading/control/system state uses Persian. Existing summary, hypothesis,
evidence and action text is shown verbatim as escaped plain text with `dir=auto`;
do not invent Persian diagnostic translations or alter evidence meaning. Put
service IDs, hashes, HTTP codes and technical values in isolated LTR spans (`bdi`
or equivalent). Never render provider/log text as HTML/Markdown or generate links
from it. Avoid exposing actor subjects, raw canonical parameters or opaque
authorization/reference IDs in normal presentation.

Status copy: healthy `سالم`, degraded `افت عملکرد`, unhealthy `ناسالم`, unknown
`نامشخص`; absent snapshot `وضعیت در دسترس نیست`. Label this as
`آخرین وضعیت مشاهده‌شده`, not current/live health. A null timestamp means
`زمان مشاهده در دسترس نیست`; collection time is not observation freshness.
`/health` reports process availability only and must not populate service health.

Source labels must always contain literal `MOCK` or `REAL`, not color alone:
`MOCK · داده آزمایشی` / `REAL · داده واقعی گزارش‌شده`. REAL is a source claim,
not verified identity/freshness. Current contextual proposals additionally show
`منشأ و تازگی داده تأیید نشده است`. An approved MOCK result remains visibly MOCK.

Use semantic lists/headings, labelled buttons, visible keyboard focus, sufficient
contrast through shared tokens, and textual risk/status labels. Layout stacks on
small screens without clipping identifiers or hiding limitations. Loading changes
use an appropriate polite live region; errors are announced without repeatedly
interrupting assistive technology. Evidence navigation must work by keyboard.

## Telemetry and structured context rendering

- Preserve null versus zero. Null CPU/RAM/latency/HTTP renders `در دسترس نیست`;
  actual zero renders zero with `%`, `MiB` or `ms`. No charts/defaults use null as
  zero. Never convert absolute MiB into utilization without a verified limit.
- `snapshot.logs=null` means unavailable/not supplied, not empty. An explicit
  empty array means zero entries returned, not a complete time window or proof
  of no errors. Partial/withheld context takes precedence over an empty claim.
- Capabilities, in their original order, are the single source of structured
  failures. Derive displayed errors from `error_code != null`; never trust a
  separately supplied `collection_errors` list as authoritative. Keep capability,
  availability, safe error_code, provider HTTP status and nullable retryable
  separately visible. `retryable=null` is unknown, not false.
- Show simultaneous failures separately, e.g. logs 403 `permission_denied` and
  metrics 429 `failed`; 404 `not_found` is not unsupported. Label these as Provider
  collection HTTP outcomes, never application HTTP/status or restart outcomes.
- Log accounting uses the actual fields `state`, `received`, `exported`,
  `withheld`. Received null means unknown. Explain partial/exported/withheld/
  empty/unavailable/not_collected/collection_failed states without collapsing
  them. Known received must equal exported + withheld; list length must match
  exported when supplied. Withheld nonempty data is not successfully empty.
- `withheld` means text not exported. Provider has no `discarded` count or
  permanent-loss assertion; show permanent discard/loss as `نامشخص`, never
  relabel withheld as permanently lost. Do not fabricate a retention guarantee.
- Preserve contract/source/correlation context in parent state. IDs/hashes are
  consistency aids, not identity proof. Context from another snapshot/service,
  source mismatch, unexpected version, changed sanitization or accounting mismatch
  must produce invalid-data/unavailable context, never a success display.
- A valid legacy report may still render if context independently fails validation;
  the parent passes `context.kind=unavailable` with a safe code, shows an explicit
  context-unavailable warning and disables related review. If
  report/selected-service or report/snapshot association fails, show no report.

## Approval, authorization and non-execution

Render approval lifecycle and authorization outcome separately. Neither report
`requires_approval=false` nor low risk bypasses trusted policy. If no policy is
available, say `سیاست تأیید بررسی نشده است`. Recommendations always remain
`not_executed` / `اجرا نشده`; an unexpected execution status is invalid data.

| Trusted serialized input | Persian display | Authorization/execution implication |
| --- | --- | --- |
| No update / unavailable dependencies | `وضعیت تأیید در دسترس نیست` | No authorization inferred; review unavailable unless parent enables its review flow |
| request.state `pending` | `در انتظار تأیید` | No approval granted |
| request.state `approved` | `تأیید شده` | Lifecycle approval only; still not authorization or execution |
| request.state `rejected` | `رد شده` | No approval; show any denial reason separately |
| request.state `expired` | `منقضی شده` | Cannot reuse; await fresh parent response |
| request.state `consumed` | `مجوز یک‌بار مصرف استفاده شده` | No replay; does not mean action executed |
| GateDecision `allowed=false` with a denial reason | `مجوز صادر نشد` | Preserve current approval state independently; pending/expired are their own lifecycle displays |
| GateDecision `allowed=true`, reason `authorized_not_executed` | `مجوز صادر شده؛ اجرا نشده` | No execution-success badge, service mutation, or optimistic health update |
| HTTP 503 safe error / missing integration | `امکان بررسی مجوز در دسترس نیست` | Distinguish unavailable service from rejected approval |

Display only parent/backend validated updates for the current revision. Known
`DecisionReason` values come from `approvals.py`; unknown combinations/values
are invalid data. A local clock may flag a potentially stale expiry and disable
review while requesting refresh; it must not fabricate a server lifecycle change.
The parent must establish the read-only status refresh transport: Setup currently
provides no browser endpoint or independent approval polling method. Never poll
the consuming authorization route as a substitute.

Keep `execution_disabled` and any supplied execution blockers visible even after
approval. No restart, redeploy, execute or retry-operation control belongs here.
No state may say remediation succeeded or change service status after a click,
approval, audit_recorded flag, authorization ID or consumed request.

## Resource states and validation boundary

| State | Required behavior |
| --- | --- |
| loading | Skeleton/`در حال دریافت گزارش…`; no fabricated metric/action values or stale review controls |
| empty/no_service | `سرویسی انتخاب نشده است`; parent selection remains outside this feature |
| empty/no_report | `گزارش تشخیصی موجود نیست`; empty hypotheses/actions alone do not make a valid report empty |
| ready with no hypotheses | Render summary, evidence, missing information and limitations; say `فرضیه‌ای با شواهد کافی موجود نیست` |
| invalid_data | `داده‌های گزارش معتبر یا مرتبط نیستند`; safe fixed message, no raw payload/validator details |
| error | Safe Persian explanation, optional parent refresh; no raw exception, credential, trace or provider body |

The parent validates actual wire schemas and backend association before passing
`ready`. The eventual feature adapter still validates at runtime because static
frontend types do not validate JSON. Unknown states must fail visibly and disable
review. The UI adds no trust to accepted data and must not send rendered payloads
back as trusted evidence. Server sanitization is required before display; browser
escaping is not a credential-redaction strategy. Do not log incident payloads or
persist them in local/session storage or analytics.

During refresh this initial contract hides stale data/controls; a future stale
view needs an explicit shell agreement. Parent cancellation/revision checks must
discard out-of-order success, error and approval results after a service change.

## Acceptance before implementation

The shell owner must approve the actual import path, generated/validated wire
types, props/revision convention, review slot/callback, CSS/token mapping,
Persian typography, router mounting and existing test/build commands. Setup must
supply the current parent association and read-only update transport. Triage must
review the final feature implementation against the scenario checklist in
[READINESS.md](READINESS.md). These decisions do not authorize backend changes.
