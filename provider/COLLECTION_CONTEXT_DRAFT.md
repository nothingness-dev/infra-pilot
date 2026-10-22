# Provider collection context — INTERNAL DRAFT v0.2

This is an **experimental provider-local proposal**, not an approved shared
contract, official Liara schema, implemented HTTP route, or authorization API.
The existing `ServiceSnapshot`, `TriageHandoff.to_dict()` wire shape, and
`POST /internal/triage/diagnose` remain unchanged. Task 05B still owns decisions
about accepting this context and returning a context-aware diagnosis response.
Nothing here installs an endpoint or changes Setup/Triage source.

## Current independently completed work

- Explicit trusted service/project/scope/source bindings, checked before reads.
- Additive `CollectionContextAdapter` over the existing read-only collector and
  normalizer, retaining partial failures with valid data.
- A separate versioned snapshot/context envelope and seven synthetic fixtures.
- Full-envelope comparison against a retained backend reference, including
  context changes when the snapshot and its digest have not changed.
- Distinct log export outcomes and exact received/exported/withheld counts.
- Per-capability retry hints in v0.2 only; original v0.1 JSON remains unchanged.
- Executed compatibility QA against Task 05A and the published Setup consumer,
  using their actual code in an isolated environment. No live access occurred.

## Proposed envelope

```json
{
  "snapshot": {"...": "existing ServiceSnapshot fields only"},
  "collection_context": {
    "contract_version": "provider-collection-context/0.2-draft",
    "service_id": "MOCK-service",
    "data_source": "mock",
    "snapshot_digest": "sha256:<64 lowercase hex characters>",
    "collection_started_at": "2026-10-22T00:00:00+00:00",
    "collection_finished_at": "2026-10-22T00:00:00+00:00",
    "capabilities": [],
    "log_export": {"state": "not_collected", "received": null, "exported": 0, "withheld": 0},
    "limitations": []
  }
}
```

The abbreviated JSON above is explanatory; use the complete checked-in
[fixtures](examples/fixtures/context_v02/) for actual proposed inputs. Each
generated context currently contains exactly four capability records in order:
`service`, `deployment`, `logs`, `metrics`. Releases remain available separately
through `list_releases`; no release/health field is invented in the snapshot.

| Context field | Proposed meaning |
| --- | --- |
| `contract_version` | Exact provider proposal identifier; distinct from the unchanged triage API version and Setup's `setup-integration-v1` |
| `service_id`, `data_source` | Same internal alias/source as snapshot; validated against trusted binding/client/bundle |
| `snapshot_digest` | SHA-256 of canonical exported snapshot after log policy; consistency aid, **not authenticity, freshness or permission** |
| Collection times | Aware collector instants or null; not source measurement times or proof of a shared observation window |
| `capabilities` | Primary source of per-component availability/error/time information; no parallel stored `collection_errors` array |
| `log_export` | Export disposition, source entries received if known, entries exported and entries withheld |
| `limitations` | Existing fixed provider limitation codes; kept structured for a future context-aware consumer |

Each capability record has `capability`, `availability`, `error_code`,
`http_status`, `collected_at`, `retryable`. Availability preserves `available`,
`unavailable`, `not_collected`, `authentication_failed`, `permission_denied`,
`not_found`, `failed`; `unsupported`/`unverified` remain reserved for evidence
outside ordinary HTTP-error inference. Unknown error codes become
`PROVIDER_ERROR`; raw messages/bodies are excluded. `http_status` is a validated
HTTP error status or null; no successful status or app HTTP result is invented.
`retryable` is the provider's validated boolean hint when an error exists,
otherwise null. It neither triggers a retry nor promises success.

A consumer can derive a `collection_errors` view from capability records whose
`error_code` is non-null. Do not reinterpret unavailable/skipped observations as
errors or duplicate independently mutable error records. No context metadata is
silently appended to today's `DiagnosisReport`; existing consumers have no such
fields. Task 05B must agree how its response retains these structured facts.

## Service association and backend trust boundary

```python
from provider import CollectionContextAdapter, MockLiaraClient, ServiceBinding

# This mapping comes from trusted backend configuration, never a frontend body.
binding = ServiceBinding(
    service_id="MOCK-service", project_name="mock-project",
    provider_scope="mock-account", is_mock=True,
)
producer = CollectionContextAdapter(MockLiaraClient(), provider_scope="mock-account")
result = producer.collect(binding)  # Logs skipped; up to two existing GETs offline.
if result.data is not None:
    retained = result.data  # PreparedCollection: retain internally with the request.
    envelope = retained.to_request()
    # Later, expected_binding must be independently resolved from trusted state.
    checked = retained.verify_request(envelope, expected_binding=binding)
    snapshot_for_existing_endpoint = checked["snapshot"]
```

`ServiceBinding` holds an exact internal service ID, project name, opaque local
provider/account scope and mock flag. Scope selects a trusted client configuration;
it is **not** verified Liara account identity. Credentials and application URLs
are not mapping fields. The scope/project are not exported in the context, and
all binding identifiers are hidden from repr. Internal service/scope identifiers
use the existing 1-128-character ASCII alias policy. The configured API token
cannot appear in any binding field. The adapter rejects another scope/source
before invoking the collector and checks selected project/detail/deployment
names before invoking a log policy. No automatic registry or persistent mapping
is created; production orchestration must store and resolve this mapping safely.

`PreparedCollection` is created only through the producer, immutable and returned
as detached JSON copies. The backend must retain the original object alongside
its own request association. `verify_request()` compares the full proposed
envelope to that reference, as well as the independently selected binding. It
rejects altered service/source/version/logs, extra fields, changed capabilities,
limitations/counts/times, swapped metadata and a changed snapshot with a freshly
recomputed digest. Different projects/scopes are rejected even when exported
snapshots happen to be identical. A reference constructed from frontend data or
selected by an unchecked client ID is not trusted.

This helper does **not** authenticate a caller, verify target ACLs, sign a
payload, prevent replay, evaluate freshness or authorize anything. A legitimate
unchanged envelope can be verified repeatedly. Retention, expiry, durable
association storage, multi-worker access, identity and transport belong to the
trusted backend integration. `PreparedCollection` is not a bearer credential or
an approval receipt and must not be deserialized from an HTTP request. Recreating
a reference from submitted data and comparing it to itself provides no security.

Canonicalization uses `json` with sorted keys, compact separators,
`ensure_ascii=True`, `allow_nan=False`, then ASCII bytes. Snapshot digests use
that same encoding. Envelope construction/verification is limited to 4 MiB of
canonical JSON; unsupported/circular/non-finite/oversized values fail with fixed
`CollectionContextError` / `INVALID_COLLECTION_CONTEXT`. A future HTTP boundary
still needs its own body/depth limits and JSON decoding policy. Known collector
times must be ordered and enclose known per-capability collection instants;
unknown/invalid times stay null. No source freshness is inferred from that check.

Invalid bindings/options fail before reads. Ordinary read errors retain the
collector's structured result; if data is partially/fully unavailable, a context
can still be returned. Failure to build a valid bounded context returns a fixed
`INVALID_COLLECTION_CONTEXT` result without exporting malformed data. Callers
can still use the original collector for native observations. Collection success
does not establish complete normalized data, application health or authorization.

## Logs and unavailable data

| `log_export.state` | Snapshot logs / counts |
| --- | --- |
| `not_collected` | null; received unknown; no log request |
| `unavailable` | null; successful collection supplied no log data; received unknown |
| `collection_failed` | null; capability retains auth/permission/not-found/transport/etc. failure; received unknown |
| `empty` | []; actual source list contained zero entries |
| `withheld` | null; nonempty source received, all entries withheld |
| `partial` | Some reviewed messages exported, others withheld; both counts retained |
| `exported` | All received entries exported through the trusted policy |

The source count is unknown (`received=null`) when no source array was obtained.
`exported=0` / `withheld=0` in that case count actual local export/withholding,
not a claim of zero source log entries. No source entry is silently truncated or
replaced by a placeholder. Reserved unsupported/unverified capability states also
remain distinct. Retention/completeness/window semantics are still unverified.

Nonempty text is withheld by default. A trusted application-specific sanitizer
can return reviewed text or null; missing messages, policy rejection, exceptions,
invalid return types and invalid UTF-8 withhold an entry and retain valid others.
The configured API token is removed before/after the callback. Exact-token
redaction and recognizable-pattern sanitizers cannot guarantee removal of every
application secret. The callback is trusted code, not sandboxed code.

Build associations/digests **after** sanitization. Task 05A fixed escaped quotes
in password redaction. QA runs that actual sanitizer before binding, then the
current HTTP diagnosis and Setup consumer, confirming the retained snapshot is
unchanged and the synthetic secret suffix does not reappear. Use the same
reviewed sanitizer revision on producer/consumer; arbitrary unreviewed log text
must not be exported just because a downstream API also has a sanitizer.

CPU/RAM remain null, health unknown, and app HTTP/response time/source timestamp
null. Collector latency is never an app measurement. Per-component errors remain
distinct from unavailable data and are not converted to unsupported capability.

## Reproducible offline demo and fixtures

```powershell
python -B -m provider.examples.context_demo --mock
```

This prints the complete **mock partial-failure** proposal: valid service data,
logs denied with 403 and metrics rate-limited with 429. No arguments other than
`--mock` are accepted; missing/invalid opt-in exits 3 with a fixed JSON error
without echoing arguments. Successful fixture generation exits 0, including
synthetic collection failures; this is a demo exit, not a live-smoke status.
No credential/environment files, account, API network, listener or approval
operation is used. Fixture collection times are explicitly synthetic.

Seven checked-in [fixtures](examples/fixtures/context_v02/) cover `exported`,
`empty`, `unavailable`, `not_collected`, `withheld`, `partial_logs`,
`partial_failure`. They are generated by `provider.examples.context_fixtures`
and compared with the generator in stdlib tests. They are candidates for shared
Task 05B fixtures, not approved shared test artifacts or captured live responses.

## Verified compatibility and commands (2026-10-22)

| Component | Immutable reviewed/tested revision |
| --- | --- |
| Provider baseline from merged PR #10 | `16838ba0a3acd5b75f9481c381216bda4c7a15c1` (main merge `cc20096285a34ffd5e8c622612b8804953216b37`) |
| Task 05A / PR #11 | `d65f4b76ed44d32090a982c26af9b0a8a534d72d` |
| Setup approval/compatibility / PR #9 (contains PR #8 changes) | `929574dcde9e95e60c5a5889b5257612589c5a2c` |

These source trees were read and copied using Git archives into ignored
`provider/.tmp/context-qa/`. No shared files or teammate branches were modified,
installed into the provider runtime, merged or pushed. Optional QA imports the
actual archived implementations, not copies of their contracts in provider.

Default provider/root checks remain standard-library only:

```powershell
python -B -m unittest discover -s provider/tests -t . -v
python -B -m unittest discover -v
```

For optional cross-module QA, use an isolated environment with the reviewed
triage module's declared QA dependencies installed. Prepare a scratch checkout
containing the pinned Setup and triage directories, and run from that checkout
so Python does not accidentally import the older Setup package from main:

```powershell
# Replace paths with your provider repository, scratch checkout and QA environment.
$providerRepo = 'C:\path\to\infra-pilot'
$reviewedQa = 'C:\path\to\reviewed-qa'
$qaPython = 'C:\path\to\qa-venv\Scripts\python.exe'
$qaPreviousPath = $env:PYTHONPATH
$qaPreviousLocation = Get-Location
try {
    $env:PYTHONPATH = "$reviewedQa;$reviewedQa\apps\liara\triage\src;$providerRepo"
    Set-Location -LiteralPath $reviewedQa
    & $qaPython -B -m unittest discover -s "$providerRepo\provider\qa" -v
    & $qaPython -B -m pytest -p no:cacheprovider -q apps/liara/triage/tests
    & $qaPython -B -m unittest discover -s setup/tests -t . -v
} finally {
    Set-Location -LiteralPath $qaPreviousLocation.Path
    $env:PYTHONPATH = $qaPreviousPath
}
```

Provider-local unit/fixture tests, optional QA and upstream regression results
are recorded in the PR. Verification used Python 3.13.5, Pydantic 2.14.1,
FastAPI 0.159.1, Starlette 1.9.0, HTTPX 0.28.1 and pytest 9.1.1. One existing
upstream TestClient HTTPX deprecation warning remains visible. This task does not
claim Python 3.12/3.14 runs; those are the teammate's separately reported runs.

The nine optional QA tests exercise all seven proposed fixtures through the
existing provider snapshot -> actual diagnosis API -> actual Setup consumer,
safe sanitizer-before-binding, target/source/brief/report mismatches, old schema
round-tripping, and rejection of the proposed envelope by the current endpoint
(422). Context is retained alongside that flow, not consumed by today's engine.
No sensitive approval route is called and execution flags remain false.

## Remaining team decisions and external blockers

- Task 05B's context-aware endpoint/input/response contracts and how structured
  collection errors/limitations affect diagnosis without losing metadata.
- Agreement on version string, fields/count semantics/canonicalization, stable
  service registry ownership, log policy and shared fixture adoption with Setup.
- Backend identity/ACL/transport, trusted reference retention, persistence and
  freshness/replay requirements; this local comparison helper replaces none.
- Real account/service configuration and reviewed read-only live evidence. Token
  and project variables were absent; latest coordination keeps tests Mock. No
  account, token, test service, infrastructure execution or live sample was made.
- Verified metric units, application-health measurements and log-window semantics.

All independently implemented pieces remain opt-in provider-local code pending
review. No incompatible API, executor, deployment or real approval integration
was enabled.
