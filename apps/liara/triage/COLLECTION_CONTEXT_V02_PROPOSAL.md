# Provider collection context compatibility — INTERNAL DRAFT v0.2

**Not an approved shared contract, official Liara schema, or implemented contextual
HTTP route.** This task implements local consistency models/tests and an explicit
MOCK preview only. No source from Provider/Setup is merged, edited, or installed
as a runtime dependency. Existing shared schemas, diagnosis/approval behavior,
default dependencies and `/internal/triage/diagnose` remain unchanged.

## Verified sources and scope

- Provider PR #12 is **OPEN, unmerged**, head
  `66655e6f21b70717948122bc521b72f54b9d91a8`, base `main`.
  Inspected `provider/collection_context.py`, `provider/triage.py`,
  `provider/COLLECTION_CONTEXT_DRAFT.md`, seven original JSON fixtures,
  `provider/tests/test_collection_context.py`, and `provider/qa/`.
- Triage base: Task 05A / PR #11, **OPEN**, head
  `d65f4b76ed44d32090a982c26af9b0a8a534d72d`; its API dependency remains PR #6.
  Current main at inspection: `cc20096285a34ffd5e8c622612b8804953216b37`.
- Setup PR #13 is **OPEN**, head `7e559255a72134473aac75c1de0c42b21864b061`,
  based on approval workflow `929574dcde9e95e60c5a5889b5257612589c5a2c`.
  Inspected `setup/collection_context.py`, `setup/COLLECTION_CONTEXT_COMPATIBILITY.md`,
  `setup/TRIAGE_COMPATIBILITY.md`, `setup/APPROVAL_WORKFLOW.md`, existing report
  consumer and approval bindings. This newer companion proposal updates the
  implementation-status findings of the earlier audit; it does not approve them.

The historical `TASK05B_COMPATIBILITY_REVIEW.md` is preserved byte-for-byte,
SHA-256 `497a7d0e2377c5743b2e42ce455b6cc94366f50c3f192671c7239b3f8240cf7b`.
No claim in that report about its earlier revisions is rewritten as current.

## Detailed compatibility matrix

Provider paths below refer to the PR #12 pin; Setup paths refer to PR #13. Triage
paths are under `apps/liara/triage/src/infrapilot_triage/` unless stated otherwise.

| # / concern | Exact source symbol and current behavior | Expected integration behavior | Severity / impact / responsible owner |
| --- | --- | --- | --- |
| 1 Service identity | `provider/collection_context.py:ServiceBinding` contains service_id/project_name/provider_scope/is_mock; `CollectionContextAdapter` checks selected scope/project/source against its client/bundle | Backend independently resolves a retained mapping for the authenticated current request; never derives internal ID from project name or submitted hash | Critical production dependency; Provider/composition supplies real verified mapping, Setup/Triage enforce it |
| 2 Snapshot structure | `provider/triage.py:TriageSnapshot.to_request()` emits existing nullable fields; `schemas.py:ServiceSnapshot` validates them | Keep existing schema and old endpoint body unchanged | Compatible, no breaking impact; Provider/Triage |
| 3 Context version | Provider `COLLECTION_CONTEXT_VERSION` is `provider-collection-context/0.2-draft`; local `ProviderCollectionContext` accepts exactly that value | Reject unknown versions; negotiate future revisions rather than guessing | High contract decision, strict local proposal; all owners |
| 4 Capability status | Provider `_context` emits four ordered capabilities service/deployment/logs/metrics, nine controlled availability states | Preserve order/status and unknown/unavailable/skipped distinctions | Compatible structural check; Provider/Triage |
| 5 Structured errors | Provider `CollectionSummary` has error_code/http_status/retryable beside availability; old unversioned handoff omits retryable | `capabilities` remains the authoritative error source; only derive views, never a second mutable error store | High loss risk if dropped; Triage/Setup |
| 6 HTTP status | Provider status is read/transport outcome, not application probe; snapshot.http_status remains null | Keep 403 permission_denied and 404 not_found distinct; never infer unsupported/healthy/unhealthy from either | Compatible; Provider/Triage/Setup |
| 7 Times | Provider collector times are aware strings or null; `_context` bounds known per-capability instants | Preserve original strings, nulls and ordering; do not claim source freshness/log window | Compatible; future freshness policy still unresolved; all owners |
| 8 Missing telemetry | Provider snapshot CPU/RAM/application HTTP/latency/source time remain null and health unknown | This pinned-context parser rejects contradictory measured fields; old ServiceSnapshot behavior stays unchanged | Compatible, stricter new local boundary only; Provider verifies units before future version |
| 9 Empty/unavailable logs | Provider state empty means actual []; unavailable/not_collected/failure means null | Preserve distinctions; never turn missing/withheld data into successful empty collection | High correctness; Provider/Triage/Setup |
| 10 Withheld counts | Provider log_export is state/received/exported/withheld; no discarded field or permanent retention claim exists | Validate sum/count/list consistency; show withheld exactly, do not rename it to guaranteed permanent discard | Compatible; Provider must agree any distinct discard/retention semantics |
| 11 Source labels | Provider binding/client/observations enforce mock/source consistency; public context and snapshot contain data_source | Require equal snapshot/context source; no mock/real mixed bundle; labels alone remain unverified claims | High trust limit; all owners; MOCK preview rejects real |
| 12 Partial failure | Provider returns valid data even when collection success=false; context retains individual safe failures | Preserve usable snapshot AND full context, including simultaneous log 403 and metric 429 | Compatible in MOCK/local models; route response/persistence still proposed; Triage/Setup |
| 13 Correlation | `PreparedCollection.verify_request` compares complete envelope and independently selected expected ServiceBinding; snapshot_digest alone misses context swaps | Retain original producer object in backend state, compare full envelope, resolve lookup refs safely; never recreate a reference from submitted data | Critical production dependency; structural hashes are not trust; composition/Provider/Setup |
| 14 Diagnosis serialization | `engine.diagnose` returns unchanged DiagnosisReport; local preview retains original collection_context beside it | Preserve report verbatim and context fields/limit codes independently; do not flatten failures into report text | Safe local proposal, contextual HTTP response unapproved; Triage |
| 15 Setup/approval correlation | `setup/collection_context.py:CollectionCompanion` binds complete envelope/current request/diagnosis; `SetupApprovalWorkflow` separately binds request/report/proposal/canonical action; gate binds action/version/actors | Agree how current companion enters the approval/consumption binding and recheck immediately before gate authorization | Critical open integration decision; Setup/Triage/composition; execution remains disabled |

No critical decision is silently resolved by this implementation. The safe portion
is structural validation and MOCK-only compatibility output. A shape-valid request
can still contain forged service IDs or recomputed hashes; production diagnosis
with context therefore fails closed.

## Actual local Python interfaces

Module: `infrapilot_triage.collection_context` (no root package export changes).

- Models: `CapabilityContext`, `LogExportContext`, `ProviderCollectionContext`,
  `ProviderContextEnvelope`, `ContextCorrelation`, `DraftContextualDiagnosisRequest`,
  `DraftContextualDiagnosisResponse`.
- `validate_provider_context(payload)` validates the exact two-field Provider
  envelope. `validate_contextual_request(payload)` validates the proposed
  three-field request below. Neither verifies a mapping, source authenticity,
  reference retention, authorization, or freshness.
- `canonical_context_json` / `context_digest` use Provider's documented sorted,
  compact, ASCII-escaped, finite JSON encoding, bounded to 4 MiB. Digests are
  consistency aids; they are not signatures or bearer credentials.
- `diagnose_contextual_request(payload)` **always raises** safe
  `ContextCompatibilityError(code="untrusted_service_mapping")`. No caller flag,
  supplied PreparedCollection, body mapping or header enables production here.
- `preview_mock_contextual_diagnosis(payload, *, mock=False)` requires literal
  `mock=True` and MOCK source, calls the real existing engine, and returns context
  plus actual report with all trust/authorization/execution flags false. Its only
  allowed nonempty log text is Provider's synthetic fixture-policy message,
  `Synthetic application started`; arbitrary claimed-exported text is rejected.
- Compatibility failures use fixed safe codes through the validation functions;
  raw Pydantic messages, submitted errors, tokens, payloads and traces are not
  logged or echoed. Direct model validators are not HTTP error handlers. No
  contextual route is registered, and future transport must keep errors sanitized.

The local models are proposed consumer validators, not copies declared as a new
authoritative shared schema. They enforce the pinned producer's unknown telemetry,
log accounting, controlled error/limitation fields, and original timestamp strings.
Future Provider fields/limit codes/semantics require review before accepting them.

## Proposed separate endpoint — NOT IMPLEMENTED

Proposed path: `POST /internal/triage/diagnose-contextual`.
It currently returns **404**. The old `/internal/triage/diagnose` still accepts only
the bare ServiceSnapshot, including all previously supported observations. Sending
the contextual envelope to the old endpoint still returns 422.

The three-field proposed request is:

- `snapshot`: the unchanged existing snapshot.
- `collection_context`: original Provider PR #12 fields, unchanged.
- `correlation`: service_id, service_binding_ref, collection_ref, snapshot_digest,
  collection_context_digest. These are **untrusted lookup/consistency claims**,
  not credentials, project/account identity, or proof of retained association.

The **exact complete JSON**, with real calculated digests and no placeholders:

- [Draft MOCK request](examples/context_v02/mock_partial_failure.request.json)
- [Actual MOCK preview / proposed response example](examples/context_v02/mock_partial_failure.response.json)

The request embeds the exact partial_failure Provider fixture plus explicitly
MOCK lookup claims. The response was generated by the real engine and local
preview, not handcrafted. It contains `contract_version=triage-contextual-diagnosis/0.2-draft`,
`integration_status=mock_preview_only`, `diagnosis_report`, original structured
`collection_context`, correlation, explicit unresolved-integration limitations,
and false trust/provenance/authorization/execution flags. It is **not** an actual
HTTP 200 response. Success semantics for a trusted live route are still a team
decision; this MOCK-only response model must not be relabeled as production-ready.

Response preservation strategy:

1. Keep `DiagnosisReport` and its original limitations/actions unchanged.
2. Retain the original collection_context values, including limitation codes,
   collector timestamp spelling, counts, source and four capability records.
3. `ProviderCollectionContext.collection_errors` is a derived immutable view
   filtering capabilities where error_code is not null. It is not serialized as
   another stored field. Setup PR #13 independently derives its display view.
4. Public context digest covers the entire context, so changed collection
   outcomes are detectable against a retained value even when snapshots match.
   An attacker can recompute it; full retained-reference comparison is mandatory.
5. Sanitize at the producer before digesting/binding; if the existing sanitizer
   would change log messages, the local envelope is rejected rather than silently
   rehashing another payload. No regex guarantees removal of arbitrary secrets.

Required checks before implementing the proposed HTTP route:

- Authenticate the caller and authorize the current request/service scope before
  resolving correlation refs. Do not let an arbitrary lookup ID select another
  user's collection. Independently resolve ServiceBinding from trusted backend
  configuration, including account scope/project/internal-service relationship.
- Retrieve the original backend-retained PreparedCollection; never deserialize
  it from JSON or build a reference from the submitted envelope. Compare the full
  Provider envelope via `verify_request` and the independently selected binding.
- Agree durable association/retention, replay/freshness, multi-worker lookup,
  sanitizer revision, error status conventions, size/depth limits, protected
  transport and shared application registration. None is supplied here.
- Define how Setup companion/request/report/proposal/canonical-action versions
  bind at any future authorization consumption. Context diagnosis grants nothing.

Until then, the separate path stays absent and the Python production entry denies.
Existing sensitive approval HTTP routes remain unavailable by default. No approval
request/grant/reject endpoint, real authentication, service mutation or execution
is added.

## Fixture provenance and actual implementation QA

`tests/fixtures/provider_context_v02/` contains exact original PR #12 fixture
bytes: empty, exported, not_collected, partial_failure, partial_logs, unavailable,
withheld. `SOURCE.json` records each path/hash and the full revision. They are
synthetic sanitized fixtures, not captured Liara responses. Do not replace them
with invented payloads; malformed-input tests explicitly mutate copies.

`tests/test_collection_context.py` uses only those fixture files and triage.
`qa/test_collection_context_implementations.py` separately imports exact pinned
Provider and Setup code. It verifies 403 **and 404** from actual Provider mock
collection (404 is not present in the seven JSON files), retained-reference
rejection, original fixture reproducibility, and actual Setup companion retention.
MOCK mappings come only from Provider's explicit fixture helper and never stand
in for a real identity resolver.

Standard offline regressions, from the canonical module:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.tmp\qa-py312\Scripts\python.exe -m pytest -p no:cacheprovider
```

Optional actual-source QA (the preparation reads local fetched Git objects only,
refuses conflicting files/symlinks/path escapes, and confines exact source copies
to ignored `.tmp/collection_context_sources`; hashes are rechecked by tests):

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B qa/prepare_collection_context_sources.py
$triagePreviousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = 'C:\git\shared\infra-pilot\apps\liara\triage\.tmp\collection_context_sources\provider-66655e6;C:\git\shared\infra-pilot\apps\liara\triage\.tmp\collection_context_sources\setup-7e55925;C:\git\shared\infra-pilot\apps\liara\triage\src'
    .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider qa/test_collection_context_implementations.py
    .\.tmp\qa-py312\Scripts\python.exe -B -m pytest -p no:cacheprovider qa/test_collection_context_implementations.py
} finally { $env:PYTHONPATH = $triagePreviousPath }
```

Regenerate the exact proposal examples offline with explicit MOCK opt-in:

```powershell
.\.venv\Scripts\python.exe -B qa/generate_collection_context_examples.py --mock
```

The generator verifies its source fixture and refuses replacing changed examples
without review. It makes no provider/network request, installs no identity, and
does not create a trusted mapping. Current known warning: Starlette's HTTPX
TestClient transport deprecation, retained without upgrades or suppression.
Python 3.11/3.13 are unavailable and remain untested.

Verified results before publication:

| Check | Result |
| --- | --- |
| Standard triage suite, Python 3.14.7 | 416 passed, 1 warning |
| Standard triage suite, Python 3.12.13 | 416 passed, 1 warning |
| Actual pinned Provider/Setup compatibility checks, Python 3.14.7 | 23 passed, 1 warning |
| Actual pinned Provider/Setup compatibility checks, Python 3.12.13 | 23 passed, 1 warning |
| Actual Provider/Setup suites plus those 23 checks, Python 3.14.7 | 250 passed, 1 warning |

The standard 416 tests comprise all 350 unchanged regressions and 66 new local
fixture/proposal checks. The 250-test combined run used this command with the
same pinned PYTHONPATH as above:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider qa/test_collection_context_implementations.py .tmp/collection_context_sources/provider-66655e6/provider/tests .tmp/collection_context_sources/provider-66655e6/provider/qa .tmp/collection_context_sources/setup-7e55925/setup/tests
```

Module-local `.gitattributes` preserves LF only for the new fixture/example JSON
and unchanged historical audit, so Windows checkout retains their verified bytes.
No existing source/test line-ending policy or root configuration is changed.

## Remaining decisions and owner actions

Provider: keep PR #12 explicitly experimental; agree context version/field/limit
code evolution, withheld versus permanently discarded semantics, sanitizer policy
revision, and genuine verified account/project/internal-ID resolution. Unit/status
verification is still required before exporting real CPU/RAM or application HTTP
telemetry; collector HTTP status/latency must remain separate.

Setup: review the proposed response adapter and correlation-ref ownership. Keep
the complete context in its companion and current request/diagnosis binding, retain
capabilities as authoritative errors, and agree how companion freshness/version
changes affect approval review and future consuming authorization. Never reuse a
hash, JSON companion, UI approval flag or stale report as authority.

Triage/composition: require explicit team approval and technically available trust
dependencies before implementing a contextual route. Real authentication/ACLs,
durable shared reference/approval/audit stores, sanitized live telemetry and
controlled live connectivity verification remain absent. No real infrastructure
execution is part of this task; no live Liara connectivity is claimed.

Incident UI readiness: original evidence/ranking/report rendering and MOCK
collection-failure/count displays can be prototyped from these exact examples.
The new Setup companion can retain structured context in offline proposal tests.
Do not label source claims as verified, show withheld logs as empty/successful,
or imply approval/remediation/live-health success. No Incident UI is implemented.
