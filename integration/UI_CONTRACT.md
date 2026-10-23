# Local UI bridge — `infrapilot-ui/1-mock`

This is a new **UI projection**, not a revision of `ServiceSnapshot`, collection
context or Approval wire contracts. The existing production-facing routes are
unchanged. The factory has no default ASGI app and requires `mock=True` plus an
existing local data directory. `integration.ui_server` binds only `127.0.0.1`.

## Source and capability inventory

| UI information | Existing producer | Projection and limitations |
| --- | --- | --- |
| Service identity | `MockSession.inspect()` / validated `CompletedInspection` | One synthetic `MOCK-service`; labels and IDs are separate. No hostname mapping. |
| Health, CPU/RAM, application HTTP and observation time | Retained `presentation.snapshot` | Preserve `unknown` / `null`. No series are available; charts explain the absence. |
| Diagnostic prose, evidence, hypotheses, actions | Existing Triage result inside `presentation.diagnosis.report` | Plain text; producer order and evidence IDs preserved. Current fixtures produce no hypotheses, so none are invented. No LLM. |
| Capability availability, HTTP errors, retryability, source timestamps | `presentation.collection_context` (`provider-collection-context/0.2-draft`) | Four ordered capabilities; partial failure retains valid observations. 403/404 do not imply unsupported API. |
| Log accounting | Existing context fixtures: `partial_failure`, `exported`, `withheld`, `empty` | Received/exported/withheld and null counts remain distinct. Snapshot log array is excluded. Diagnostic evidence may quote **synthetic** fixture log text; there is no raw Provider response endpoint. |
| Inspection history | `SQLiteInspectionHistory.save()` | Save sanitized summaries on initialization/refresh, not GET. Current full reports come from retained original objects, never reconstructed from history. Restart does not restore trusted sessions from SQLite. |
| Approval, expiry and audit | `OperatorApprovalExample`, actual Approval Gate and `SQLiteApprovalStore` | Separate operator-selected MOCK restart example, **not** a diagnosis-derived operation. Requester/approver handles stay on the server. Canonical grace period and policy category come from the existing review. |
| Incident lifecycle | UI catalog only | Four explicitly synthetic lifecycle labels over four inspections of the same service. These labels do not assert actual failures or repairs. Approval never closes an incident. |
| Real Liara, releases, metric series, production identity, execution | No configured UI backend path | REAL remains disabled. Deployment capability collection is visible, but release/deployment bodies are not part of this projection. No live request or executor is connected. |

All `authorization_consumed`, `execution_authorized`, `execution_performed`,
`remediation_verified` and `identity_verified` flags are false. Successful HTTP
responses or completed diagnosis are not health/freshness/identity verification.

## HTTP surface

All requests use the same origin. POST requires JSON, a permitted exact Origin,
and at most 1024 bytes. Mutation bodies reject extra properties and coerce no
types. Every protected endpoint requires the opaque HttpOnly session cookie.

| Method / route | Body | Result |
| --- | --- | --- |
| POST `/api/ui/session` | `{}` | `{source:"mock", csrf:...}` and HttpOnly SameSite=Strict cookie. Initializes four actual offline inspections and one pending separate demo request; repeat with same cookie is idempotent. |
| GET `/api/ui/state` | None | Version, source, one service, records, approvals, unverified connection, false execution flags. No collection, diagnosis or consuming authorization occurs here. |
| POST `/api/ui/reports/{id}/refresh` | `{revision}` | Reruns existing offline pipeline, saves history, generates a new revision and freezes old approvals as historical/non-actionable. |
| POST `/api/ui/reports/{id}/approval` | `{revision}` | Creates a separate mock approval through the actual gate/store; returns opaque public UI ID. |
| POST `/api/ui/approvals/{id}/decision` | `{revision, decision:"approve"\|"reject"}` | Calls actual gate with server-owned independent mock approver; returns stored state, safe reason and false flags. No authorize/consume/execute call. |
| GET `/api/ui/reports/{id}/export` | None | Strict allowlist: profile/source/historical/report ID/time, counts, capability statuses and false flags. No prose, log array, database, actor credentials or raw bodies. |

Records contain `id`, synthetic `title`/`lifecycle`, `lifecycle_is_demo`,
`revision`, fixture scenario, report creation time, history ID, validated
`snapshot` minus `logs`, actual `report` and `context`. Source timestamps are
separate from the UI report creation time.

Approvals expose a random UI ID, record/revision association, stored lifecycle,
creation/expiry time, canonical operation/category/grace period, historical flag,
decision availability and allowlisted audit event kind/reason/time. Internal
authentication handles and actor IDs are not projected. Historical entries retain
their recorded state; a historical pending entry is not a current pending count.

Known error envelopes contain only `error_code`. Missing session is 401, invalid
Origin/CSRF is 403, missing record is 404, stale revision or final decision is 409,
oversized request is 413, invalid shape is 422, session/resource limit is 429 and
unexpected backend failure is a fixed 503. No exception text or input value is
reflected. A gate expiration decision is a completed HTTP request with stored
`expired` state and `allowed` remaining false.

## Trust and lifetime

- Exact loopback Host allowlist; no permissive CORS. CLI permits its own local
  port plus Vite's fixed 4173 origin. No token upload, provider URL or actor field.
- CSRF lives in frontend module memory, never browser storage. Cookie is HttpOnly,
  SameSite=Strict and intentionally HTTP on loopback; this is not a public hosting
  authentication design. A 401 triggers one new bootstrap before retrying reads.
- Original inspections are validated before projection and mutations. Decisions
  match the retained report revision; another session cannot use its public IDs.
  A process lock serializes related reads and writes. Final UI decisions cannot
  be reversed. Gate and SQLite still enforce their own association/expiry rules.
- At most eight process-local sessions and 100 approvals per session. Cookie
  lifetime is one hour; no background session eviction/recovery is implemented.
  Restart starts new opaque sessions and leaves prior SQLite summaries/audit as
  local historical artifacts under `.tmp/ui-demo`, outside the static root.
- Browser/runtime JSON validation checks association, canonical capability order,
  log accounting, source/execution flags, ordering and date shapes. It does not
  create trust or recompute the digest of the omitted original snapshot logs;
  the backend validates the retained full objects.
- Static serving confines resolved paths to `apps/web/dist/client`; unknown API
  routes never fall back to HTML. Responses use no-store, nosniff, no-referrer,
  frame denial and a same-origin CSP. The Vite development shell uses Vite's own
  development headers; production-style loopback serving uses the bridge CSP.

No production identity/service ACL integration, real freshness, live Liara
access or infrastructure execution is claimed by this interface.
