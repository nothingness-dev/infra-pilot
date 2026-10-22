# Provider to diagnosis handoff (INTERNAL DRAFT v0.1)

Reviewed on 2026-10-22 against triage commit
[`428237de83631035439afa4d78d9f68f863942b9`](https://github.com/nothingness-dev/infra-pilot/tree/428237de83631035439afa4d78d9f68f863942b9/apps/liara/triage).
PRs #5 and #7 containing the provider and live-smoke tooling are merged into
`main`. Triage PR #6 remains open, based on the approval-policy branch; its
dependency branches were not merged or modified for this task.

Sources for this **proposed**, provider-local compatibility layer:
[CONTRACT_PROPOSAL.md](https://github.com/nothingness-dev/infra-pilot/blob/428237de83631035439afa4d78d9f68f863942b9/apps/liara/triage/CONTRACT_PROPOSAL.md),
[API_INTEGRATION.md](https://github.com/nothingness-dev/infra-pilot/blob/428237de83631035439afa4d78d9f68f863942b9/apps/liara/triage/API_INTEGRATION.md),
and [schemas.py](https://github.com/nothingness-dev/infra-pilot/blob/428237de83631035439afa4d78d9f68f863942b9/apps/liara/triage/src/infrapilot_triage/schemas.py).
No shared schema has been approved, copied into teammates' modules, or changed.

## Readiness and live blockers

Offline structural and in-process HTTP compatibility is verified for the pinned
triage revision. **Authenticated Liara access and end-to-end live integration
remain unverified.** The execution environment contains neither
`LIARA_API_TOKEN` nor `LIARA_PROJECT_NAME`; no account login, token issuance,
test-service provisioning, deployment, or authenticated Liara request occurred.
There is no real response capture to share. The supplied JSON is explicitly mock.

An account owner still needs to select a disposable test service and make its
token/project available in the local environment using the masked PowerShell
instructions in [README.md](README.md#environment-only-configuration). Do not send
keys in chat, command arguments, committed files or PRs. No account credentials
or unrelated private files were searched. The official
[authentication introduction](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/index.mdx)
directs account owners to the Liara console for tokens. Expiration choices and
read-only permission scopes were not confirmed from that official source or a
logged-in console; this work does not claim to issue a short-lived/scoped key.

Run the existing summary-only tool first:

```powershell
python -B -m provider.examples.live_smoke
```

Logs require an explicit `LIARA_LOGS_SINCE`; otherwise they are skipped. Preserve
the run time, selected account/service context and per-capability outcomes in
controlled local evidence. A successful result applies only to that context.
It does not verify app health, resolve metric units, or grant action permission.
Review and sanitize any later real fixture before sharing it; never capture raw
logs, environment variables or unrestricted API bodies in Git.

## Interfaces

| Interface | Purpose |
| --- | --- |
| `LiaraClient`, alias `LiaraApiClient` | Existing authenticated, bounded, redirect-blocked read transport |
| `ServiceDetails`, `DeploymentStatus`, `ServiceLog`, `MetricsSummary`, `ReleasePage` | Native selected observations; see the README method table |
| `ProviderResult[ServiceObservations]` | Collector result retaining per-component availability/errors and mock/live origin even after partial failure |
| `TriageAdapter(client).collect(name, *, service_id, logs_since=None, log_sanitizer=None)` | Reuses the existing collector's at most three GETs; returns `ProviderResult[TriageHandoff]` |
| `TriageAdapter(client).from_observations(bundle, *, service_id, log_sanitizer=None)` | Pure projection of an already collected bundle; performs no requests |
| `TriageSnapshot.to_request()` | Detached JSON-compatible dict matching only the draft `ServiceSnapshot` fields, with nulls retained |
| `TriageHandoff.to_dict()` | Provider sidecar containing the snapshot, per-capability availability/safe error codes/HTTP error statuses, collector times, log-export counts and fixed limitation codes |

All interfaces above are exported by `provider`. `TriageSnapshot`, `TriageLog`
and `CollectionSummary` are local dataclasses, not Pydantic models or a new
shared contract. Runtime dependencies remain standard library only. Importing
provider starts no server, constructs no client and makes no request.

`service_id` must be supplied by trusted integration code after binding the
internal identifier to the selected Liara project. It is not inferred from a
project name/provider ID. This adapter accepts an opaque ASCII identifier of
1-128 characters: letters/digits first, then letters/digits/`_ . : -`. Invalid
options raise fixed-message `ValueError` before collection; configured tokens
are forbidden in the identifier. Mixed mock/live observation bundles and bundles
whose origin disagrees with the client are rejected, never relabelled.

`collect().success` and `error` retain the collector's meaning. They describe
collection, not diagnosis quality, health, or completeness of normalized fields.
An unsuccessful partial/total collection can still contain a handoff. Inspect
`result.data` and the sidecar instead of discarding valid observations. There
are no retries or automatic HTTP submissions to triage.

## Field mapping and limits

| Draft field | Mapping and reason |
| --- | --- |
| `service_id` | Explicit trusted internal alias; no automatic cross-module identity claim |
| `data_source` | `mock` for mock client/bundle, otherwise `real`; origin is checked on every component |
| `status` | Always `unknown`: native project status and `isDeployed` are not documented app-health measurements |
| `http_status` | `null`: the provider API HTTP status is not an app HTTP probe |
| `response_time_ms` | `null`: API/collection duration is not application response time |
| `cpu_usage_percent`, `ram_usage_mib` | `null`: summary metric units, tuple positions, scaling and sampling semantics remain unverified; no coercion, clamping or guessed conversion |
| `timestamp` | `null`: no snapshot source-measurement time is established. Known collector times remain in the sidecar only. |
| `logs` | `null` if unavailable/skipped/withheld; `[]` only if the collected source array was actually empty. Reviewed exportable messages become entries. |
| Log `level`, `timestamp` | `unknown`, `null`: native stream type/time semantics are not treated as verified severity or aware measurement times |

Native metrics, project/deployment fields and release history remain available
through the existing provider methods. The draft has no fields for releases or
deployment flags; the snapshot does not smuggle them into logs/status. Releases
are collected separately via `list_releases()`, one explicit page at a time.
The draft also lacks log-window, completeness, per-observation availability and
error fields. Keep `TriageHandoff` beside the diagnosis response in the trusted
workflow so 401, 403, 404, missing data and skips remain distinguishable. Send
**only** `handoff.snapshot.to_request()` to `POST /internal/triage/diagnose`;
sending the full sidecar is invalid (`extra=forbid`). The current endpoint cannot
incorporate sidecar limitations into its report automatically. Team agreement is
needed before changing that contract or claiming semantic integration is complete.

The sidecar contains only allowlisted error codes, validated HTTP error status,
fixed limitation codes and validated aware collector times; no raw error message,
project name, native status, metric tuple, `since`, environment data or API body.
403/404 remain permission/not-found outcomes, not API-unsupported conclusions.

## Log-sharing boundary

Nonempty log text is withheld by default, even if collection succeeded. Regexes
cannot establish that arbitrary application logs contain no secrets. Trusted
server code can supply an application-specific `LogSanitizer`: `str -> str | None`.
It must return reviewed sanitized text or `None` to withhold an entry. The adapter
redacts its configured API token before and after that callback; it never stores
or prints callback exception text. An exception, non-string return, invalid UTF-8
text or missing message withholds that entry while retaining other valid exports.

`logs_exported`, `logs_withheld` and `LOG_TEXT_WITHHELD` /
`LOG_EXPORT_INCOMPLETE` record this loss. A nonempty source whose entries were all
withheld becomes `logs=null`, not `[]`. Whitespace and empty messages returned by
a trusted sanitizer are preserved. No invented placeholder log is inserted.
Log messages are hidden from dataclass repr. The callback is trusted application
code, not a security sandbox or a guarantee against secrets unknown to provider.

## Offline sample and usage

[examples/mock_triage_snapshot.json](examples/mock_triage_snapshot.json) is a
reproducible **synthetic** request, not a sanitized real capture. Generate it:

```powershell
python -B -m provider.examples.triage_handoff
```

```python
from provider import MockLiaraClient, TriageAdapter

result = TriageAdapter(MockLiaraClient(failure_modes={"metrics": 403})).collect(
    "mock-project", service_id="MOCK-service",
    # No log window/policy: logs stay uncollected and null.
)
if result.data is not None:
    request_body = result.data.snapshot.to_request()
    sidecar = result.data.to_dict()  # Preserve for missing-information display.
    # Trusted coordinator may send request_body to the internal diagnose endpoint.
    # This adapter itself does not submit it or invoke authorization/execution.
```

For a live client, construct `LiaraClient(ProviderConfig(api_key=...))` using the
existing environment configuration and supply a trusted service binding. The
adapter uses identical methods for live/mock. Avoid printing a live body/sidecar
until its identifiers and approved log policy have been reviewed for sharing.

## Reproducible compatibility QA

Default provider tests remain offline and require no third-party packages:

```powershell
python -B -m unittest discover -s provider/tests -t . -v
python -B -m unittest discover -v
```

Optional `provider/qa/` tests are intentionally outside default discovery. They
use the teammate's actual dependencies and source, not a reimplementation of
its validators. In an isolated environment with that reviewed triage revision
and its declared QA dependencies installed, set its source path and run:

```powershell
$triageQaPreviousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = 'C:\path\to\reviewed-checkout\apps\liara\triage\src'
    C:\path\to\qa-venv\Scripts\python.exe -B -m unittest discover -s provider/qa -v
} finally {
    $env:PYTHONPATH = $triageQaPreviousPath
}
```

Run from the provider repository root. No FastAPI, Pydantic, HTTPX or pytest
dependency is added to the provider runtime. The QA source for this task was a
Git archive of the pinned triage revision in ignored `provider/.tmp/`, with an
isolated Python 3.13.5 environment. Its complete original suite passed **313**
tests. The four provider compatibility QA tests passed schema round-tripping,
full-sidecar rejection, successful in-process `/diagnose`, and partial-failure
payloads. ASGI requests use `TestClient`, not a real HTTP deployment or Liara.
QA used Pydantic 2.14.1, FastAPI 0.159.1, Starlette 1.9.0, HTTPX 0.28.1,
pytest 9.1.1; upstream TestClient emits one HTTPX deprecation warning.

Provider tests: **98 passed**. Root provider/setup regression suite: **151 passed**.
The provider-local unit tests cover provenance rejection, invalid binding before
I/O, null/empty distinctions, partial HTTP/transport failures, log export policy,
callback failure, safe output/repr, and absence of network access in the fixture.
These are offline checks, not live capability evidence or team approval.

No restart/redeploy/resource mutation, approval consumption, executor or trusted
identity backend is introduced. The next integration step is team agreement on
identity, log-sharing and sidecar handling, then a controlled read-only live run
once account/service configuration is present.
