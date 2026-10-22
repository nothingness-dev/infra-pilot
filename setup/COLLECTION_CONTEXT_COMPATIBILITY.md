# Setup collection_context compatibility — proposal, execution disabled

## Reviewed sources and compatibility verdict

Provider PR #12 head/prefix `66655e6` resolves exactly to
`66655e6f21b70717948122bc521b72f54b9d91a8`. The reviewed contract identifier is
`provider-collection-context/0.2-draft`, an internal proposal, not an approved
shared contract or live integration. Read its actual COLLECTION_CONTEXT_DRAFT.md,
collection_context.py, seven context_v02 fixtures and provider/qa tests.

Setup base: `929574dcde9e95e60c5a5889b5257612589c5a2c` (draft PR #9), containing
PR #8 at `a9d7482e0a1f67a396b5cd98609b217eeb13079f`. The topic
`feat/setup-collection-context` depends on PR #9 and does not merge producer
history. Main was fetched at `cc20096285a34ffd5e8c622612b8804953216b37`; PRs #8/#9
remain open drafts. No state in another repository was changed.

Triage QA reference: PR #11 at `d65f4b76ed44d32090a982c26af9b0a8a534d72d`.
Its escaped-quote redaction fix is used by Provider's own QA. Setup's older
published API ancestry lacks that fix; it is not silently patched here.

Verified verdict: all seven synthetic producer envelopes are preserved
alongside existing Setup evidence/Diagnosis with a separate backend-owned
association, provided the actual sanitizer leaves the producer-digested export
unchanged. The envelope cannot be sent to the current Diagnosis endpoint (422);
only its unchanged snapshot is an endpoint input. Production approval, source
authenticity, freshness and shared-contract agreement remain unresolved.
The new boundary accepts only the reviewed `provider-collection-context/0.2-draft`
identifier; installing a newer producer does not silently expand compatibility.
The implementation and its 16 new tests are in
`2ad4d36f14d7ab418b83b3636c69a69f77b867d2`.

## Field and semantics mapping assessed before implementation

| Concern | Actual Provider fields/semantics | Existing / proposed Setup boundary |
| --- | --- | --- |
| Request identity | No Setup request ID, operation or brief fingerprint | Existing SnapshotEvidence.association must come from backend orchestration and pass the full current request fingerprint checks. The new companion adds a Setup association; it does not pretend Provider supplied it. |
| Service identity | Exported service_id and private ServiceBinding(service_id, project_name, provider_scope, is_mock) | Require the actual retained PreparedCollection and independently resolved backend ServiceBinding. Exact snapshot/brief/service/source matching; no frontend registry selection. Project/scope are not UI props. |
| Snapshot | No snapshot UUID. snapshot_digest is SHA-256 of canonical exported snapshot, after the trusted log policy | Check that digest on the exact displayed snapshot. Retain existing DiagnosisPresentation.binding semantics unchanged; a new companion digest has a separate domain and includes the context. |
| Source / mode | data_source is mock or real; binding has is_mock | Match existing Setup mock/external provenance to snapshot mock/real. A real label is only a source claim, not authenticated live evidence or readiness. |
| Time | Nullable aware collection_started_at / collection_finished_at and per-capability collected_at | Preserve exactly as collector instants. snapshot.timestamp remains source measurement time (often null). No fabricated time, freshness TTL or shared observation window. |
| Outcomes | Ordered service/deployment/logs/metrics capability records: availability, error_code, http_status, collected_at, retryable | Preserve records; derive display errors from them. Partial failures retain surviving snapshot/context evidence. Retry hints never trigger a call. |
| Log disposition | log_export state and received/exported/withheld counts | Empty [] is distinct from unavailable, skipped, denied/failed and deliberately withheld null logs. Preserve partial exported messages and withheld counts. Reserved/unknown outcomes must remain distinguishable. |
| Sanitization | Trusted app-specific log callback; configured token removed before/after callback; nonempty text withheld by default. No exported sanitizer/policy revision or redaction receipt | Reuse Triage sanitize_snapshot before a new association. If it changes the digest-covered representation, block rather than recompute/relabel Provider's hash. Pattern redaction is not a general secret detector or a replacement team policy. |

The companion structure, digest, lifecycle and Incident UI interface below are
Setup proposals. No fields are added to ServiceSnapshot or DiagnosisReport.

## Companion structure and trusted entry points

`setup.collection_context` is an opt-in consumer with normal producer package
imports. It does not become part of the standard-library-only intake path. Server
composition must install the reviewed Provider and Triage implementations;
the pending branches are not merged into this topic. Importing the consumer with
the older Provider ancestry fails explicitly rather than selecting test code.

`preserve_collection_context(request, evidence, prepared=..., expected_binding=...)`
requires the actual backend-retained `PreparedCollection`, a separately resolved
`ServiceBinding`, and the existing internally associated `SnapshotEvidence`.
It checks the current complete `inspect_service` brief through `_snapshot`, the
producer's exact private binding (including project/scope), full exported
snapshot equality, source label, digest and sanitization boundary. A client
envelope, recomputed hash or frontend metadata is not a substitute for those
server objects. Missing producer reference/binding returns `unresolved` with
`producer_reference_required`; incompatible evidence returns `blocked` with a
fixed structured error and no companion payload. These checks establish an
internal association, not authenticated provenance.

On success, retain the returned `CollectionCompanion` in backend state. Its
proposed `to_dict()` view contains:

| Proposed Setup field | Meaning |
| --- | --- |
| contract_version / state | `setup-collection-companion/1-proposal`; `context_preserved` or `diagnosis_associated` |
| request_id / request_fingerprint | Existing complete Setup brief identity, not a producer identifier |
| source_evidence | Existing output reference and ResultMetadata association, never private Provider project/scope |
| snapshot / collection_context | Detached, exact policy-reviewed producer export and context; nulls and limitations retained |
| companion_binding | Separate Setup digest over its version, request fingerprint, full evidence association, exact Provider envelope and optional existing Diagnosis binding |
| diagnosis | Optional full existing DiagnosisPresentation, with its original binding/report unchanged |
| display | Derived source claim, log disposition/counts/availability, per-component errors, false provenance/freshness flags and null sanitizer-policy revision |
| production_readiness / execution | `unresolved`; existing `execution_readiness()` blockers. Authorization consumed, execution authorized and execution performed are all false |

The companion retains the producer object/private binding and immutable canonical
envelope bytes internally. It copies the request/evidence snapshot, detaches
serialized JSON, and revalidates mutable canonical models before every use or
serialization. The dataclass constructor and JSON reconstruction are rejected.
This is a Python composition boundary, not a security sandbox against hostile
code inside the server process.

Use `consume_collection_diagnosis_response(request, companion, status_code=...,
payload=...)` after the existing trusted transport obtains a response to the
**snapshot-only** Diagnosis call. It reuses `consume_diagnosis_response` and the
existing presentation validation; it neither sends HTTP nor reconstructs the
report. Alternatively, `attach_collection_diagnosis` accepts an already retained
DiagnosisPresentation. Exact snapshot and source-evidence associations must agree.
Attaching the Diagnosis produces a new companion binding; the Provider snapshot
digest and existing Diagnosis binding keep their original meanings.

No new Approval workflow is created. The consumer calls only its existing
readiness view. It does not invoke request/approve/reject/authorize, consume an
authorization or dispatch an action. Existing historical approval interfaces
in APPROVAL_WORKFLOW.md remain outside this new context boundary.

## Sanitization ordering and limits

The producer's documented order is observations -> trusted app-specific log
review/withholding (configured token removal around the callback) -> normalized
export -> `snapshot_digest` -> retained PreparedCollection. Setup then runs the
actual Triage `sanitize_snapshot` **before** creating its own companion digest.
The pinned QA Triage contains the escaped-quote credential fix from PR #11.

If the sanitizer changes the snapshot, Setup returns
`blocked/sanitization_order_conflict`: no companion binding, snapshot, context or
Diagnosis payload is returned. It does not display sanitized text beside a
Provider hash of different text, nor overwrite that hash. The producer must
apply the agreed reviewed policy and create a new export/reference after review;
the consumer cannot repair producer integrity metadata. Existing Snapshot and
Diagnosis digest algorithms are unchanged.

No sanitizer revision or review receipt exists in v0.2. The proposed display
field is therefore null. The tests use only synthetic token/password canaries,
including an escaped quote, and check payloads, repr, stdout/stderr and logging.
They also check that a late secret-bearing mutation blocks output. Triage pattern
redaction cannot detect arbitrary application secrets; a trusted app-specific
policy and its ownership/revision remain required. This compatibility result
does not certify arbitrary live logs as safe, and adds no replacement team policy.

## Association lifecycle and invalidation

1. Trusted orchestration selects its current request, authorized service mapping,
   retained producer reference and existing evidence association independently
   of frontend fields; this boundary checks consistency only.
2. Preserve context alongside evidence before requesting a Diagnosis. Serialize
   only the outcome view; retain the actual companion server-side.
3. Send the exact snapshot through existing transport, then attach the validated
   actual response. Replace the current companion with this new association.
4. On a new brief or collection, discard the selected old companion and
   Diagnosis. Resolve backend references again and build a fresh association.
   A failed replacement must show blocked/unresolved, not the prior payload.

Changed request ID, operation or full details, target/source, Provider private
binding, snapshot, context, source-evidence reference/metadata, report or existing
Diagnosis binding prevents reuse when checked against the current request.
Mutation of retained snapshot/report/context also prevents serialization. JSON
edits cannot mutate the retained object or establish a new association. A new
contract version is blocked until reviewed.

The helper has no global current-request/collection registry, durable storage,
expiry clock or replay policy. `to_dict()` validates the retained association; it
cannot discover that an external backend has selected a newer request/collection
or revoked an ACL. Future composition must resolve the **current** retained
objects on each command and invalidate old handles after replacement, restart,
retention expiry, access loss or policy change. Do not deserialize yesterday's
view into a valid companion. A matching hash or collector timestamp alone cannot
establish currentness; no invented TTL fills this gap.

## Proposed Incident props, callbacks and display states

Reviewed the existing Setup shell/incident proposal in APPROVAL_WORKFLOW.md and
Triage's CONTRACT_PROPOSAL.md/README. There is no approved frontend shell or
context-aware endpoint in the inspected agreements. The following extends the
existing proposal only; no frontend component, route or shared schema is added.

| Proposed controlled prop | Constraint |
| --- | --- |
| collectionState / errors | `context_preserved`, `diagnosis_associated`, `blocked` or `unresolved` and safe fixed errors; clear previous context on invalidation |
| companionBinding | Association/stale-response hint only; backend looks up its retained current companion, never trusts the client's hash |
| collectionContext / collectionDisplay | Full exact context, nullable collector times, capability availability/errors/retry hints, log disposition and original counts; preserve producer limitations |
| snapshot / report / diagnosisBinding | Reuse existing full validated Diagnosis view; null unknowns and existing report uncertainty remain visible |
| execution / busy | Existing disabled-execution blockers plus controlled loading; a real source label does not enable actions |

Suggested events, **proposals without new HTTP routes**:

```text
onRefreshCollection({requestId})
onRefreshDiagnosis({requestId, companionBinding})
```

The shell resolves its selected request and replaces controlled props from the
future trusted backend. That backend must reload the current request/service/
evidence/companion and check session/target access independently. It must not
accept the client-provided snapshot/context, roles or hashes as provenance.
Existing review/approval callback proposals are unchanged and remain separately
blocked by their prerequisites. There is no execute callback or authorize polling.

Display source `mock` conspicuously; `real` means a source claim, with provenance
unverified and freshness unevaluated. Preserve successful components during
`partial_failure` and show denied logs separately from failed/rate-limited
metrics. `collection_state=no_component_error_reported` does not mean complete,
fresh or authorized. Log states remain:

| Producer state | Proposed display state |
| --- | --- |
| empty | collected_empty; genuinely zero received/exported/withheld entries |
| unavailable | data_unavailable, not empty |
| not_collected | not_collected, not empty |
| collection_failed | collection_failed plus exact capability availability (including permission_denied/authentication_failed) |
| withheld | deliberately_withheld; retain withheld count, never reconstruct text |
| partial | partially_exported; retain surviving reviewed text and withheld count |
| exported | exported; no claim about source completeness/window |
| unsupported / unverified | unsupported / unverified, retaining null logs |
| future unknown | unknown in defensive display mapping; a new producer contract is blocked pending review |

## Required producer/team decisions

- Provider/Triage: agree the context contract and context-aware Task 05B API
  input/ownership. Existing endpoint rejects the envelope with 422; snapshot-only
  Diagnosis cannot reason about omitted-vs-denied context. Setup preserves that
  context alongside its unchanged report rather than changing diagnostic results.
- Provider/Triage: agree app-specific sanitization ownership, revision/receipt,
  shared sensitive fixture cases and export-before-digest ordering. PR #11's
  pending redaction fix is required for this verified escaped-quote case; this
  topic does not update Triage ancestry or claim broader redaction coverage.
- Composition owners: define the trusted request/service/collection registry,
  current-reference replacement, retention/replay/invalidation policy, durable
  storage, session authentication and exact target ACL checks. Backend-owned
  objects are prerequisites, not frontend-submittable credentials.
- Provider: agree measurement units, source timestamps/log windows/completeness
  and any freshness policy. Unknown CPU/RAM/health/time remain unknown. Collector
  timestamps and retry hints do not supply these missing semantics.
- Incident owner: review the controlled props/state wording/callback proposals
  and stale-response replacement behavior with the shell owner before UI wiring.
  No real approval, authorization consumption or executor is part of this work.

## Reproducible synthetic QA

Use the existing Setup-owned Python environment and producer dependency ranges;
no editable producer install, root config or teammate source changes are needed.

```powershell
# From this topic's repository root; fetch pinned Git objects first if needed.
C:/Users/FATIMA/GitHub/infra-pilot/setup/.venv/Scripts/python.exe -B setup/qa/run_collection_context_checks.py --suite all
```

The QA-only runner reads pinned Git objects into ignored `setup/.tmp/` and
preloads the actual Provider/Triage packages before discovering this Setup tree.
It refuses to overwrite different scratch content. Production code must use
normal package imports, never these paths. `--suite setup`, `provider`,
`provider-qa` or `triage` can select individual checks. The original fixtures are
read without editing them. These are fixture/contract checks, not real API,
authentication, authorization or infrastructure integration.

Final verification on Windows, Python 3.14.8 / Pydantic 2.14.1 / FastAPI 0.159.1 /
HTTPX 0.28.1 / pytest 9.1.1:

| Command | Actual result |
| --- | --- |
| `C:/Users/FATIMA/GitHub/infra-pilot/setup/.venv/Scripts/python.exe -B setup/qa/run_collection_context_checks.py --suite all` | Setup **99**, Provider **119**, Provider QA **9**, Triage **350** tests passed |
| `$env:PYTHONPATH = (Resolve-Path 'apps/liara/triage/src').Path; & 'C:/Users/FATIMA/GitHub/infra-pilot/setup/.venv/Scripts/python.exe' -B -m unittest discover -s setup/tests -t . -v` | Older topic ancestry: **83 passed**, pending-Provider test module explicitly skipped (84 discovered) |
| `git diff --check` | Passed |
| `git diff --exit-code 929574dcde9e95e60c5a5889b5257612589c5a2c -- provider apps` | No producer/Triage edits |

Setup adds 16 tests over its 83-test baseline. All seven source fixtures are read
from the pinned producer tree and checked against its actual factory; none are
copied into a substitute fixture contract or edited. Cases cover preservation,
partial/denied/withheld/empty semantics, independent bindings, mismatches,
forged frontend metadata, mutation, redaction ordering/no sensitive output,
reserved/unknown states, new-version refusal and unchanged Diagnosis/Approval
behavior. Network/approval/authorization calls are forbidden in the new boundary
test. The Provider QA and new API cases use FastAPI TestClient in-process, not a
running real API or Liara service. The real-mode label test constructs only
synthetic observations/configuration with socket connections forbidden.

Observed warnings: existing Starlette HTTPX TestClient deprecation and pytest's
already-imported-anyio assertion-rewrite warning in the combined runner. Tests
pass; no dependency manifests are changed to suppress them. No standalone lint
or typecheck configuration is defined for Setup. No UI was implemented or
visually verified in this backend-only task.

## پیام تحویل به رهام و ستایش

رهام: هر هفت fixture واقعی PR #12 روی SHA ثبت‌شده با Setup سازگارند. context
کنار snapshot و Diagnosis نگه داشته می‌شود و معنی digest قبلی تغییر نکرده است.
اگر sanitizer خروجی پوشش‌داده‌شده با digest را عوض کند، نتیجه blocked است؛ باید
سیاست پالایش در مرز producer اعمال و خروجی تازه ساخته شود. نسخه/رسید این سیاست،
ذخیرهٔ مرجع معتبر، ابطال و تازگی هنوز نیازمند توافق‌اند. این نتیجه فقط سازگاری
fixture/قرارداد است و تأیید اتصال واقعی یا آمادگی production نیست.

ستایش: گزارش و binding فعلی Diagnosis بدون تغییر مصرف می‌شوند؛ context وارد
ServiceSnapshot یا DiagnosisReport نشده است. props و callbackهای Incident بالا
فقط پیشنهادند. لطفاً نمایش empty، unavailable، withheld، partial و access-denied
و قرارداد API آگاه از context را بررسی کن. اجرای عملیات و مصرف authorization
غیرفعال مانده‌اند؛ هیچ approval واقعی یا UI جدیدی پیاده نشده است. این PR روی
PR #9 قرار دارد و هیچ شاخهٔ هم‌تیمی merge یا بازنویسی نشده است.
