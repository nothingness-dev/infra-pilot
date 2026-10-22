# InfraPilot: executable offline Mock backend workflows

This repository assembles the existing Provider, Triage and Setup into
one **explicitly Mock** Python flow. The actual Provider collector/normalizer,
Triage diagnosis engine and Setup companion/presentation execute in-process.
It needs no Liara account, token, external API, listener or infrastructure tool.

The [request-to-approval workflow](integration/WORKFLOW.md) adds request intake,
information completion, preparation, actual evidence/diagnosis, action review,
and a separate explicit Mock approval example. It has no UI or executor.

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

## Connected request and approval journey

Use the same environment; no new dependencies or credentials are required:

```powershell
.\.venv\Scripts\python.exe -B -m integration.workflow_demo --mock --scenario complete_information
.\.venv\Scripts\python.exe -B -m integration.workflow_demo --mock --scenario approved_not_executed
$LASTEXITCODE  # 4: approved in Mock, infrastructure execution remains blocked
```

The first command completes missing information, collects actual Mock evidence,
diagnoses once and reviews an observational recommendation (exit 0). The second
also exercises a separate operator-selected Mock approval. It does not invent a
restart recommendation, consume authorization, or claim that the service was
repaired. The existing `integration.mock_backend` command is unchanged.

See [all 19 scenarios, safe output, Python API and exits](integration/WORKFLOW.md),
including partial collection, missing data, unmapped actions, rejection,
expiration and missing identity/permissions.

## Evidence-based outcome comparison

The [outcome evaluator](integration/OUTCOMES.md) compares retained before/after
observations separately from action performance. It reports improvement,
deterioration, mixed changes, unchanged policy indicators, insufficient evidence
or rejected associations. It does not establish execution or causality.

```powershell
.\.venv\Scripts\python.exe -B -m integration.outcome_demo --mock --scenario improvement
.\.venv\Scripts\python.exe -B -m integration.outcome_demo --mock --scenario approved_not_executed
$LASTEXITCODE  # 4: approval does not establish that an action occurred
```

Directional examples use explicitly controlled canonical observations with known
fixture units. Provider's unknown telemetry and original collection context are
preserved; its fixed timestamps are not turned into a chronological post-action
sequence. All execution, causality and verified-remediation flags remain false.
The two older commands retain their original behavior.

## Tests

Run the assembled checkout, without temporary source copies:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
```

The merged Mock integration baseline passed **661 tests**, with one existing Starlette/HTTPX TestClient
deprecation warning, no skipped tests. This includes 119 Provider tests, 99 Setup
tests, 416 Triage tests, nine Provider cross-module QA tests and 18 new integration
tests. Its integration tests also run the real CLI for every supported scenario.
Installation and all 661 tests were also verified in a fresh tracked-source
archive with a separate new virtual environment, without Git objects or QA
scratch copies. Installed imports and the Mock flow also worked outside that
checkout directory. See [verification evidence](integration/VERIFICATION.md).

The request-to-approval continuation added 30 behavioral/CLI tests. That
suite passed **691 tests**; see the separately recorded
[workflow verification](integration/WORKFLOW_VERIFICATION.md).

The outcome milestone adds 39 tests. The current suite passed **730 tests**;
see [outcome verification](integration/OUTCOME_VERIFICATION.md).

Provider remains usable and testable with the standard library alone:

```powershell
python -B -m unittest discover -s provider/tests -t . -v
```

The same 119 Provider tests also passed with `python -B -S`, excluding site
packages. Optional historical QA commands and their separate results are in the
[integration guide](integration/README.md#verification).

## Scope and next steps

The executable profiles are `infrapilot-mock-backend/1`,
`infrapilot-request-approval/1-mock`, and the opt-in
`infrapilot-evidence-outcome/1-mock`. Existing shared
schemas and the Provider/Triage/Setup contextual proposals keep their original
Draft/proposal labels. No contextual HTTP route or production trust backend is
enabled. Both existing diagnosis and approval behavior are preserved.

Remaining backend work includes separately reviewed real read-only collection,
trusted service/account identity and ACLs, durable current
associations/approval/audit storage, and freshness/replay policies. A future
infrastructure executor is a separate task. CPU/RAM units, application health and
log-window semantics remain unverified; missing telemetry stays null/unknown.

See [architecture and trust boundaries](integration/README.md),
[exact selected source revisions](integration/SOURCE_REVISIONS.json), and
[the Incident UI proposal](https://github.com/nothingness-dev/infra-pilot/pull/15).
None of these profiles implements that UI or performs infrastructure execution.
