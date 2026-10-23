# Read-only Liara access verification

Record date: **2026-10-23**, Windows / Python **3.13.5**.
**Authenticated live verification was not performed.** This delivery completes
the independent investigation/tooling/tests and leaves an explicit operator step.

## Verified baseline and evidence

PR [#22](https://github.com/nothingness-dev/infra-pilot/pull/22) was actually
merged, with merge commit `28913499c008bc6da61d3f9c9f8edffebc48fd18` equal to
fetched `origin/main`. The starting worktree was clean. Branch
`feat/liara-live-readonly-verification` starts at that integrated main, so this is
not a stacked PR. Baseline: **895 tests, 770 subtests passed**.

The [capability investigation](../provider/CAPABILITIES.md#project-access-investigation-2026-10-23)
pins the official OpenAPI and CLI revisions. The documented response is an
object containing a `projects` array; the exact application identifier is
`project_id`, distinct from `_id`. Existing parsing already rejects a missing or
malformed array; no empty-list parser defect was reproduced. The official CLI
also explicitly sends `teamID` (empty for personal scope). That request-scope
detail is now optional configuration, uniformly applied to reads.

The earlier zero-project/404 results are historical user reports. **The root
cause remains unresolved.** Missing permission, account/token visibility,
account scope, host selection and a mistaken target identifier cannot be
distinguished without current authorized account evidence. A successful list
request proves neither ownership nor permission to inspect a particular service.
No region fallback, guessed identifier or undocumented endpoint was added.

## Current live record

Only documented process-environment setting presence was inspected; no values,
credential files, browser data or previously pasted credentials were used.
All eight documented settings, including optional `LIARA_TEAM_ID`, were absent.
The required four are token, project name, internal service alias and provider
namespace. Running the new command in that environment produced
`INVALID_CONFIGURATION`, JSON `exit_code=3`, `collection_outcome=not_performed`.
No client/network collection or history file was created.

| Check | This delivery's live outcome |
| --- | --- |
| Project list / exact target resolution | Not performed: required settings absent |
| Service details / deployment flags | Not performed |
| Logs | Not performed: credentials and explicit window absent |
| Metrics / release page | Not performed |
| Provider → Diagnosis → Setup / summary history | Not performed against Liara; exercised only with mocked HTTP |

There is no real captured fixture or sanitized successful live sample. No claim
is made about current account permissions, target visibility, application health,
CPU/RAM units or timestamps. Existing official API support documentation is
separate from these unperformed account checks.

## Secure operator procedure

Use the existing root `.venv` installation from [README](../README.md). No new
dependencies were added. From the repository root, set only process variables;
never enter a token as a literal command, command argument, Git file or chat
message. Do not dump environment/configuration in a recording terminal.

```powershell
$py = '.\.venv\Scripts\python.exe'
$env:LIARA_API_BASE_URL = 'https://api.liara.ir'
$env:LIARA_PROJECT_NAME = Read-Host 'Exact project_id shown by Liara'
$env:LIARA_SERVICE_ID = Read-Host 'Internal service alias'
$env:LIARA_PROVIDER_SCOPE = Read-Host 'Local namespace for this account and configuration'
Remove-Item -LiteralPath Env:LIARA_LOGS_SINCE -ErrorAction SilentlyContinue
Remove-Item -LiteralPath Env:LIARA_TEAM_ID -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path .tmp/liara-readonly -Force | Out-Null
$liaraSecureToken = Read-Host 'Existing Liara API token' -AsSecureString
$liaraTokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($liaraSecureToken)
try {
    $env:LIARA_API_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($liaraTokenPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($liaraTokenPointer)
    Remove-Variable liaraSecureToken, liaraTokenPointer
}
try {
    # Personal account: preserve an explicitly empty scope in this child process.
    & $py -B -c "import os,runpy; os.environ['LIARA_TEAM_ID']=''; runpy.run_module('integration.readonly_inspection', run_name='__main__')" --live-read-only --verify-access --history-database .tmp/liara-readonly/history.sqlite
    $verificationExit = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath Env:LIARA_API_TOKEN -ErrorAction SilentlyContinue
}
$verificationExit
```

The child setup above only preserves the existing environment variable contract;
it neither handles a secret argument nor adds another client/parser. It works
around older PowerShell versions removing an empty variable. Microsoft documents
[preserving empty environment values starting in PowerShell 7.5](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_environment_variables?view=powershell-7.5).
In 7.5+, `$env:LIARA_TEAM_ID = ''` followed by the ordinary module command can be
used instead. For an intentionally selected team, set `LIARA_TEAM_ID` to its
verified identifier and use the ordinary command below. Do not guess a team ID
or change scopes automatically after a failure. Unset leaves legacy requests
unchanged; it does not claim personal scope was selected.

```powershell
# After the same masked-token/environment setup, within its cleanup try/finally:
& $py -B -m integration.readonly_inspection --live-read-only --verify-access --history-database .tmp/liara-readonly/history.sqlite
```

The original command without `--verify-access` retains its original behavior.
History is optional: omit `--history-database` for no persistent artifact. A
provided path requires an existing parent directory; no raw response is stored.
Choose an isolated local path and retain its contents according to account policy.
The fixed-schema history archives the validated inspection, not the separate
list/release diagnostics. No existing database/schema is migrated.

Optional settings keep existing validation: positive finite
`LIARA_TIMEOUT_SECONDS` (10 seconds default) and an explicit nonblank
`LIARA_LOGS_SINCE` string if logs should be collected. The reviewed API does not
define its accepted time syntax/completeness precisely, so this tool forwards the
operator-selected window without inventing conversions. With no window, no logs
request occurs and log state is explicitly `not_collected`.
`LIARA_TEAM_ID` has a local maximum of 128 printable non-whitespace ASCII
characters; an empty value is permitted. Internal aliases retain the existing
`ServiceBinding` grammar. Use an independently selected namespace per account/
configuration; account selection and local aliases are not authenticated grants.

## Execution, safe output and exits

The existing CLI validates literal opt-in, all environment settings, an optional
history path and the exact API host before constructing a client. Verification
allows only HTTPS `api.liara.ir` or `api.iran.liara.ir`, root base paths and the
default/443 port. No alternate host is tried. Redirect refusal, response bounds,
TLS, timeout validation and sanitized errors remain in the existing transport.

One `list_projects()` call must resolve exactly one matching `project_id` before
any service collection. Missing identifiers, incompatible shapes or multiple
exact matches fail as invalid responses. Database IDs, names, substrings, case
folding and public URLs are not alternate identifiers. The same client then
collects details/metrics plus explicitly requested logs, derives deployment from
details, runs actual Diagnosis and Setup association once, and checks one existing
release page (`page=1,count=10`). Rendering/history do not collect or diagnose
again. Later capability failures preserve earlier valid evidence and safe errors.

The new profile is `infrapilot-live-readonly-verification/1`. JSON includes only:
known API hostname, scope category (`unspecified`, `personal`, `team`), local UTC
observation time, project counts/resolution state, safe errors/HTTP status/
retryability, local diagnostic durations, the existing data-free inspection
summary, release availability and optional opaque history record digest. It
exports no project/account names or IDs, team identifier, configuration, raw keys,
response bodies, environment entries, token, auth headers, logs or diagnosis prose.
Successful HTTP status remains null because the existing result does not expose
it. Local timing is not application latency or source freshness.

List outcomes distinguish `empty_project_list`, `target_not_listed`,
`invalid_response`, `authentication_failed` (401), `permission_denied` (403),
`not_found` (404), `rate_limited`, `timeout`, `network_error`, `api_unavailable`,
and `target_resolved`. Collection/release summaries retain existing availability
and safe error codes. Empty collected data differs from unavailable data; 403/404
do not imply global API non-support. Unknown CPU/RAM remain null, health unknown,
and live log text withheld, with received/exported/withheld counts retained.

Before the new profile is available, CLI configuration/dependency/interruption
errors use the existing `infrapilot-readonly-inspection/1` fixed error envelope.
Unknown exceptions never enter JSON or stderr. For example, this is an
**illustrative synthetic subset**, not a live result:

```json
{"verification_profile":"infrapilot-live-readonly-verification/1","status":"blocked","exit_code":2,"error_code":"NO_PROJECTS_VISIBLE","project_access":{"status":"empty_project_list","projects_count":0,"identifiable_projects":0,"target_resolved":false},"inspection":null,"releases":null}
```

| Exit | Meaning |
| --- | --- |
| 0 | Exact target resolved, composition completed, every attempted capability including releases available; requested history recorded |
| 1 | Composition completed with at least one available and one failed/unavailable attempted capability |
| 2 | List blocked/unresolved, all capabilities failed, or composition/dependency/history/output failure |
| 3 | Invalid/missing settings, opt-in or arguments; no client/network collection |
| 130 | Interrupted; no completed verification claim |

Skipped logs do not cause partial status. History failure exits 2 while retaining
valid earlier summaries; it never claims a successful archive. Interruption
the initial list completes may replace incomplete verification with the existing
safe interrupted envelope. Interruption during diagnosis, releases or history
retains earlier summaries, exits 130 and stops subsequent checks/storage. An
interrupted history operation never claims that persistence succeeded; inspect
the existing history separately before deciding whether to repeat a run.

If listing remains empty, verify in the intended account that the token can see
that exact service and that the selected scope/host are appropriate. If nonempty
but unmatched, check the exact project name locally. For 401 review credential
validity; for 403 review account permissions; for 404 review target visibility and
mapping. Do not infer the cause solely from these codes. Resolve account issues
through the operator's console/support access; do not weaken validation or guess
new endpoints. Share only the sanitized summary, scoped to that account/target/
time, and keep account-identifying context separately protected.

## Offline verification and remaining boundaries

Executed checks:

```powershell
python -B -m unittest discover -s provider/tests -t . -v
.\.venv\Scripts\python.exe -B -m unittest provider.tests.test_diagnostics integration.tests.test_live_verification -q
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
git diff --check
```

- Standalone Provider: **136 tests passed**, with only Python's standard library.
- Focused new modules: **36 tests passed**.
- Full configured suite: **931 tests and 827 subtests passed**, no skips,
  67.16 seconds. One existing Starlette/HTTPX deprecation warning remains; no
  dependencies were changed to silence it. No other Python/OS or CI run is claimed.

All 36 added tests are new; no previous test was weakened or removed. New tests
mock the existing urllib boundary and prohibit sockets, subprocess
infrastructure tools, Approval mutations and the production/Mock contextual
diagnosis entry points. They exercise actual Provider, pure Diagnosis, Setup and
SQLite summary persistence. Synthetic API responses include private canaries
that must not appear in stdout, stderr, logs, repr, exceptions or database bytes.
Separate `-S` child-process checks verify static help and safe missing-dependency
handling without installing another stack. These results are **offline evidence**.

Changed runtime files: `provider/models.py`, `environment.py`, `client.py`,
`diagnostics.py`, `examples/live_smoke.py`; `integration/readonly.py`,
`readonly_inspection.py`, `live_verification.py`. New tests:
`provider/tests/test_diagnostics.py`, `integration/tests/test_live_verification.py`.
Documentation: `provider/README.md`, `provider/CAPABILITIES.md`,
`integration/README.md`, `integration/READONLY_INSPECTION.md`, this record.
All 15 files stay in `provider/` and `integration/`. Setup/Triage, shared contracts,
production access control, root settings, dependencies and infrastructure are unchanged.

Operator-local API-token access is not production user identity, verified service
ACLs or trusted ownership onboarding. Existing `ProtectedMockRequests` remains
strictly Mock-only; no principal is promoted into real authentication. Historical
summaries cannot reconstruct current trusted evidence. Durable Approval/audit,
freshness/replay policy, reviewed executor/allowed actions and a separately
authorized infrastructure demo remain independent blockers. No operation is
approved, consumed, executed, deployed or verified as a repair by this milestone.
