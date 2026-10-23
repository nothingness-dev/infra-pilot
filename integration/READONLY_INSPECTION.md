# Local read-only Liara inspection

Profile: `infrapilot-readonly-inspection/1`. This explicitly opted-in Python
composition connects the existing real Provider client to the existing pure
Diagnosis engine and Setup presentation. It installs no HTTP route, listener,
identity backend, approval mutation, executor or UI.

The implementation is verified offline with mocked HTTP. **An authenticated live
inspection has not been performed in this delivery.** `data_source=real` describes
the selected adapter path; it is not independently authenticated provenance or
proof that a checked-in example contacted Liara.

The additive [live access verification mode](LIVE_VERIFICATION.md) first checks
the documented project list, requires an exact target match, reuses this same
composition once, checks one release page and optionally archives the original
typed result in existing allowlisted summary history. Authenticated live access
remains unverified; the linked record distinguishes offline checks from live work.

## Run safely

Use the existing root environment from [README](../README.md). No dependencies
were added. Provider and its environment helper remain standard-library-only;
the composed path uses the already installed Triage/Pydantic stack.

Required process environment settings:

| Setting | Meaning |
| --- | --- |
| `LIARA_API_TOKEN` | Existing operator-supplied token; never a CLI argument |
| `LIARA_PROJECT_NAME` | Exact Liara project name for the existing adapter |
| `LIARA_SERVICE_ID` | Explicit internal service alias; not inferred from project or database ID |
| `LIARA_PROVIDER_SCOPE` | Explicit opaque local namespace for this client configuration |
| `LIARA_LOGS_SINCE` | Optional opaque API window string; absent means no log request |
| `LIARA_API_BASE_URL` | Optional existing HTTPS API base; Provider validation is unchanged |
| `LIARA_TIMEOUT_SECONDS` | Optional positive finite timeout; default 10 seconds per request |
| `LIARA_TEAM_ID` | Optional account selection: unset preserves prior requests; empty selects personal scope; nonempty selects a team |

Service/scope aliases use the existing `ServiceBinding` grammar: 1–128 ASCII
characters, beginning with an alphanumeric character and then alphanumerics or
`_.:-`. Existing Provider project-name validation/encoding is reused. No alias,
project or scope may contain the configured token. Log-window semantics are not
guessed or converted. This local configuration establishes **association only**;
it does not prove account ownership, authenticated caller identity, target ACLs,
freshness, token scope or a production authorization decision.

PowerShell: enter an existing key with a masked prompt, not a literal in shell
history. The non-secret placeholders below are examples, not configured services.
Do not run this in a terminal session that records secrets or environment dumps.

```powershell
$env:LIARA_PROJECT_NAME = Read-Host 'Liara project name'
$env:LIARA_SERVICE_ID = Read-Host 'Internal service alias'
$env:LIARA_PROVIDER_SCOPE = Read-Host 'Local provider namespace'
# Leave LIARA_LOGS_SINCE unset to skip log collection.
# Set it explicitly only when an operator has selected a log window.
$liaraSecureToken = Read-Host 'Existing Liara API token' -AsSecureString
$liaraTokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($liaraSecureToken)
try {
    $env:LIARA_API_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($liaraTokenPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($liaraTokenPointer)
    Remove-Variable liaraSecureToken, liaraTokenPointer
}
try {
    .\.venv\Scripts\python.exe -B -m integration.readonly_inspection --live-read-only
    $inspectionExit = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath Env:LIARA_API_TOKEN -ErrorAction SilentlyContinue
}
$inspectionExit
```

The literal `--live-read-only` opt-in is required. Optional `--verify-access`
adds exact listing verification and a release check; `--history-database PATH`
is allowed only with that mode and takes a local summary-storage path.
See its [separate output/exit documentation](LIVE_VERIFICATION.md).
Duplicate flags are rejected. `--help` is static and
constructs nothing. Tokens, URLs, aliases, requests and identity claims cannot be
passed as arguments. Missing/invalid settings fail before client construction or
network access. Importing the module never collects data. Existing Mock, workflow
and outcome commands remain explicitly offline and cannot switch into this path.

## Composition and retained evidence

```text
explicit opt-in
  -> public Provider read_live_settings + local ServiceBinding validation
  -> independently selected expected binding
  -> existing LiaraClient / CollectionContextAdapter.collect
  -> original retained PreparedCollection
  -> exact envelope/binding verification + Triage validate_provider_context
  -> Setup preserve_collection_context
  -> actual engine.diagnose once on an independent canonical snapshot copy
  -> Setup consume_diagnosis / attach_collection_diagnosis
  -> shared pure validate_retained_inspection
  -> typed ReadOnlyInspection -> allowlisted summary only
```

The collector performs at most three existing documented GETs: project details,
optional logs and resource summary. Deployment flags share the details response.
There is no duplicate transport, parser or collection implementation, no retries,
and no application URL probe. Existing TLS behavior, redirect refusal, timeouts,
4 MiB response limits and secret redaction remain in Provider. Release pagination
is not part of the snapshot collector; the existing separate
`provider.examples.live_smoke` command still checks releases independently.
This task adds no endpoints or new API-support claims; the pinned official
evidence and unresolved permissions/units in [CAPABILITIES](../provider/CAPABILITIES.md)
remain applicable.

`integration.composition.validate_retained_inspection` is the only shared pure
composition helper added. The old Mock retained-result validator uses it too;
Mock construction, preview and outputs remain separate. Real observations never
enter the Mock-only contextual preview. The production contextual diagnosis entry
remains fail-closed, and the existing outcome evaluator stays Mock-only.

Trusted Python use:

```python
from integration.readonly import run_readonly_inspection

inspection = run_readonly_inspection(live_read_only=True)  # reads process env
safe_summary = inspection.summary()
if inspection.presentation is not None:
    inspection.validate()  # recheck retained producer/request/report associations
    report = inspection.presentation.report  # trusted backend use, never CLI dump
```

`ReadOnlyInspection` retains the request, independently selected binding, original
`PreparedCollection`, preserved Setup companion and actual Diagnosis presentation
as each becomes available. `inspect_prepared(request, prepared,
expected_binding=...)` is a network-free continuation for trusted Python code.
Its optional submitted envelope must equal the full original producer export;
recomputed digests do not replace that reference. Never deserialize these internal
objects or select the expected binding from submitted context.

Later context/diagnosis/association failures return fixed safe codes and retain
earlier valid objects. A diagnosis interruption also retains already collected
evidence and returns 130. Interruption before collection completes has no complete
producer reference to return. Serialization revalidates mutable nested evidence,
request and report. Modified evidence produces a data-free validation failure.
This process-local consistency mechanism is not a signature, durable registry,
freshness/replay policy or defense against privileged Python code replacing all
private state.

## Meaning of partial and missing data

Authoritative per-capability context, errors, HTTP status, retryability, collection
instants and limitations remain intact through Setup. Partial collection still
runs Diagnosis on the valid canonical snapshot; total collection failure may
also yield an explicitly incomplete diagnosis, with exit 2. A report being
available does not establish useful telemetry or a healthy service.

Live text is always withheld by the existing Provider default policy. This path
accepts no log-sanitizer callback and rejects an exported/partially exported live
snapshot rather than sanitizing again and recomputing its digest. Source entries
with missing messages count as withheld too. Existing separately tested Mock and
Provider sanitizer scenarios remain available for reviewed synthetic data.

| Log state | Snapshot logs | Counts/meaning |
| --- | --- | --- |
| `not_collected` | `null` | No window supplied; no request; received unknown |
| `unavailable` | `null` | Successful API response supplied no log data |
| `empty` | `[]` | Actually collected an empty array; received zero |
| `withheld` | `null` | Collected entries; exported zero, withheld count retained |
| `collection_failed` | `null` | API/response failure; capability error retained |

HTTP 401 (`authentication_failed`), 403 (`permission_denied`) and 404 (`not_found`)
remain distinct. 429, timeout, server and malformed-response errors preserve
their safe codes/retryability. Neither 403 nor 404 establishes global non-support.
Skipped logs do not make otherwise complete collection partial; unavailable or
failed attempted capabilities do.

Canonical health stays `unknown`; CPU/RAM, application HTTP/latency and source
timestamp remain `null`. Native deployment flags are not health evidence. API
call success/latency is not application health/response time. Resource units,
sampling and log-window completeness are unverified. Context remains Draft v0.2;
shared models and contracts were not silently revised.

## CLI summary and exits

Stdout contains one JSON object, with no raw report, snapshot, API response,
message, service/account/project/scope identifier, window, auth header or arbitrary
exception text. It includes only profile/source, stages/outcomes, allowlisted
capability/error/status/retryability fields, log counts, aggregate diagnosis
counts, fixed limitation codes and explicit readiness/false execution indicators.
Internal data must not be exported by dumping dataclasses or presentation objects.

| Exit | Meaning |
| --- | --- |
| 0 | Local pipeline completed; every attempted capability available |
| 1 | Pipeline completed with partial/missing attempted collection |
| 2 | No attempted capability available, or runtime/dependency/association/output failure |
| 3 | Missing opt-in, invalid arguments or invalid configuration; zero requests |
| 130 | Interrupted |

Exit 0 does not mean healthy, repaired, authorized or production ready. No approval
or authorization is consumed; execution, remediation verification and post-action
evaluation remain disabled. Output-pipe failure exits 2 without dumping diagnostics.

The [generated summary examples](examples/readonly_mocked_transport.json) are
explicitly labeled **offline mocked transport**, not live evidence. Their nested
`data_source=real` exercises the actual live-client composition against synthetic
urllib responses. They contain no captured account data. See
[verification](READONLY_VERIFICATION.md) for executed checks and live status.

Before production use, trusted identities/target ACLs, validated account mapping,
durable associations/approval/audit state, freshness/replay rules and independently
reviewed operations remain separate work. Nothing here grants permission for a
mutation or claims deployment readiness.
