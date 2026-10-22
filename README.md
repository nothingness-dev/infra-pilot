# InfraPilot: executable offline Mock backend

This integration branch assembles the existing Provider, Triage and Setup into
one **explicitly Mock** Python flow. The actual Provider collector/normalizer,
Triage diagnosis engine and Setup companion/presentation execute in-process.
It needs no Liara account, token, external API, listener or infrastructure tool.

## Setup and run

Use Python **3.11+** from the repository root. This delivery was tested on
Windows with Python **3.13.5**. Create an isolated environment and install the two
local packages plus their existing QA dependencies:

```powershell
python -B -m venv .venv
.\.venv\Scripts\python.exe -B -m pip install -r requirements-mock.txt
.\.venv\Scripts\python.exe -B -m integration.mock_backend --mock --scenario partial_failure
$LASTEXITCODE
```

The example deliberately simulates logs HTTP 403 and metrics HTTP 429. It emits
one JSON object and exits **1**, meaning the pipeline produced a diagnosis and
retained partial collection data. It is not a failed installation. To run a
collection with all attempted components available, use `--scenario exported`
(exit 0). See the [actual generated partial output](integration/examples/partial_failure.json).

With the virtual environment active, the equivalent single command is:

```powershell
python -B -m integration.mock_backend --mock --scenario partial_failure
```

On other platforms use the environment's `bin/python` instead of
`Scripts/python.exe`; no non-Windows runtime verification is claimed here.
`constraints-mock.txt` pins the existing reviewed component environment rather
than upgrading producer dependency ranges. Install commands may download Python
packages; the installed backend execution itself is fully offline.

## Available scenarios

The only configured service alias is `MOCK-service`; it can be selected with
`--service MOCK-service`. Project/scope bindings come from backend-owned fixture
configuration, not submitted JSON.

| Scenario | Log outcome | Exit |
| --- | --- | --- |
| `exported` | One reviewed synthetic message | 0 |
| `empty` | Actually collected empty array | 0 |
| `unavailable` | Successful collection supplied no log data | 1 |
| `not_collected` | Logs deliberately skipped | 0 |
| `withheld` | Nonempty source; all messages withheld | 0 |
| `partial_logs` | One exported message and one withheld entry | 0 |
| `partial_failure` | Logs denied (403), metrics rate-limited (429) | 1 |

Exit 0 means every attempted collection component was available and the Mock
pipeline completed. It does not mean complete log export, application health,
production readiness or authorization. Withholding is recorded independently.
Exit 1 preserves the usable result when an attempted component is missing/failed.
Exit 2 means integration/dependency/output failure; exit 3 means missing Mock
opt-in, invalid arguments/scenario/service; exit 130 means interruption.
`--help` prints static help and exits 0 without running the backend. Invalid
arguments are not echoed. Ordinary errors produce fixed JSON codes and no raw
exception diagnostics.

## Tests

Run the assembled checkout, without temporary source copies:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
```

Verified result: **661 passed**, one existing Starlette/HTTPX TestClient
deprecation warning, no skipped tests. This includes 119 Provider tests, 99 Setup
tests, 416 Triage tests, nine Provider cross-module QA tests and 18 new integration
tests. The integration tests also run the real CLI for every supported scenario.
Installation and all 661 tests were also verified in a fresh tracked-source
archive with a separate new virtual environment, without Git objects or QA
scratch copies. Installed imports and the Mock flow also worked outside that
checkout directory. See [verification evidence](integration/VERIFICATION.md).

Provider remains usable and testable with the standard library alone:

```powershell
python -B -m unittest discover -s provider/tests -t . -v
```

The same 119 Provider tests also passed with `python -B -S`, excluding site
packages. Optional historical QA commands and their separate results are in the
[integration guide](integration/README.md#verification).

## Scope and next steps

The current executable profile is `infrapilot-mock-backend/1`. Existing shared
schemas and the Provider/Triage/Setup contextual proposals keep their original
Draft/proposal labels. No contextual HTTP route or production trust backend is
enabled. Both existing diagnosis and approval behavior are preserved.

Next work is a UI over this verified Mock output, then separately reviewed real
read-only collection, trusted service/account identity and ACLs, durable current
associations/approval/audit storage, and freshness/replay policies. A future
infrastructure executor is a separate task. CPU/RAM units, application health and
log-window semantics remain unverified; missing telemetry stays null/unknown.

See [architecture and trust boundaries](integration/README.md),
[exact selected source revisions](integration/SOURCE_REVISIONS.json), and
[the Incident UI proposal](https://github.com/nothingness-dev/infra-pilot/pull/15).
This branch does not implement that UI or merge any open PR.
