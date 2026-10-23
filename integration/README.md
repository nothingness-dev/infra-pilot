# Mock backend integration profile

[Persistent local Mock requests](REQUESTS.md) add versioned accepted briefs,
information completion, lifecycle events and safe continuation across separate
processes. This uses a dedicated SQLite database; prior evidence remains
historical after restart and cannot restore approvals or trusted references.

[Persistent inspection history](HISTORY.md) adds opt-in local SQLite storage for
validated summaries, with an offline record/list demo. Historical records do not
restore current producer references, identity, approvals or execution authority.

The separate [local read-only Liara inspection](READONLY_INSPECTION.md) now
connects the real adapter to Diagnosis/Setup behind explicit opt-in and validated
environment configuration. Its CLI exports a data-free summary. Live account
verification has not been performed; existing Mock profiles below stay offline.

Latest non-UI continuation: [outcome evaluation](OUTCOMES.md) compares retained
observations independently of action-performance claims. The original Mock and
request/approval commands keep their existing behavior.

Current non-UI continuation: [request-to-approval workflow](WORKFLOW.md), using
the same installed environment and original component implementations. The
baseline was merged through PR #16; its original source-selection record below
remains intact as historical provenance.

Profile: **`infrapilot-mock-backend/1`**, offline only. The shared contextual
contracts remain proposals; this profile chooses a concrete, reversible Mock
composition without claiming a production transport or finalized shared API.

## Source selection

Integration branch: `integration/mock-backend`, created from Provider PR #12 at
`66655e6f21b70717948122bc521b72f54b9d91a8`, which already contains main through
`cc20096285a34ffd5e8c622612b8804953216b37` (merged PR #10).

| Component | Original selected head | Integration handling |
| --- | --- | --- |
| Provider / #12 | `66655e6f21b70717948122bc521b72f54b9d91a8` | Retained existing ancestry and all Provider files unchanged |
| Triage / #14 | `51d268d94757b5cc3d2f01bf04709aa71ee248b6` | Replayed its 26 non-merge commits with `cherry-pick -x`, including all Task 1–05B dependencies |
| Setup / #13 | `7e559255a72134473aac75c1de0c42b21864b061` | Replayed seven Setup commits, preserving its complete module tree |
| Incident UI / #15 | `c9f8f4035d9f1cded65e9dfd342170afa5020aa9` | Read for consumer expectations; not included or implemented |

[SOURCE_REVISIONS.json](SOURCE_REVISIONS.json) records every replayed original and
integration commit. Setup's historical import/merge commits were deliberately
excluded: their triage dependencies were already replayed and their older
Provider/API trees would not represent the selected current versions. No Git
merge, PR merge, original-branch rewrite or force-push was performed. The
integration PR targets main and contains its required pending implementations;
it does not assume PRs #8/#9/#11/#12/#13/#14 are merged.

The sole change inside an assembled component is
`apps/liara/triage/qa/prepare_collection_context_sources.py`: its historical
personal absolute-path guard now checks the actual checkout root/layout. It
retains pinned source hashes and all archive/path safety checks. Runtime source,
shared models, engine, gate, endpoints, dependency declarations, fixtures and
existing tests are otherwise preserved. Historical module ownership/path/task
notes remain historical; this integration was explicitly authorized across all
modules in the user's current checkout, without migrating other workspaces.

## Executed architecture

```text
explicit --mock + allowlisted scenario/service
  -> backend-owned ServiceBinding
  -> existing Provider build_mock_context fixture producer
     -> actual MockLiaraClient.collect_service_observations
     -> actual CollectionContextAdapter and TriageAdapter
     -> original retained PreparedCollection
  -> full-envelope verification against independently selected expected binding
  -> actual Triage validate_provider_context
  -> actual Setup preserve_collection_context
  -> actual Triage preview_mock_contextual_diagnosis(mock=True)
     -> actual engine.diagnose exactly once
  -> actual Setup consume_diagnosis
  -> actual Setup attach_collection_diagnosis / CollectionCompanion.to_dict
  -> detached MockResult -> JSON stdout
```

All runtime imports are ordinary imports from the assembled packages. No test
implementation, Git subprocess, sys.path modification, temporary checkout or
historical source archive participates in this flow. The Provider's public
example fixture producer is deliberately reused for its seven synthetic
observation scenarios; it really invokes the collector/normalizer and does not
load precomputed diagnosis output. Its fixed collector instants are synthetic
fixture data. No fixture time or source label is presented as live evidence.

The selected Python path avoids inventing an HTTP response/status or running a
second diagnosis to demonstrate another interface. No listener or API client is
created. The production `diagnose_contextual_request` remains fail-closed and is
never called. The existing `/internal/triage/diagnose` endpoint remains unchanged.

## Public integration entry points

After installing the documented environment:

```python
from integration.service import run_mock_backend

result = run_mock_backend(mock=True, scenario="partial_failure")
view = result.to_dict()  # Detached JSON values, not an authorization receipt.
assert result.exit_code == 1
assert view["presentation"]["state"] == "diagnosis_associated"
assert view["execution_performed"] is False
```

`MockSession(mock=True, ...)` is an internal, process-local staging object used
when an envelope must be compared before finishing. Its `collection_request()`
returns a detached copy; `finish(submitted_envelope)` compares it to the original
retained Provider reference. It never builds a reference from submitted fields.
The service alias must select the backend fixture registry; expected project,
account scope and source cannot be overridden by the envelope. These checks do
not authenticate a real account or authorize a caller. Session internals are
trusted Python state, not a sandbox against code running inside the process.

Setup receives a real `OperationRequest`, `SnapshotEvidence` and existing
`ResultMetadata` with an exact request fingerprint. Metadata `ready` means a
canonical input is supplied to Setup, not successful collection of every field.
Changes to the brief, evidence, source or generated report fail association.
The companion is serialized only after its current bindings revalidate.

Result copies and `MockResult` cannot mutate retained evidence. Repeating a
session's finish operation performs another Mock diagnosis; it grants nothing
and makes no replay-prevention claim. Fixed fixture refs are not external lookup
credentials or globally unique production collection IDs. No persistent registry,
multi-worker store, TTL, authenticated session or freshness proof is supplied.

## Output contract and preserved facts

The CLI emits a single JSON object with:

- `integration_profile`, `mode`, `scenario`, and collection-oriented `status`.
- `triage_preview`: the existing preview's version, Mock-only integration status,
  correlation claims, limitations and false trust/authorization/execution flags.
- `presentation`: the actual Setup `CollectionCompanion.to_dict()` output,
  including the exact snapshot/context, associated original Diagnosis report,
  request/source bindings, derived display and existing readiness blockers.
- `production_readiness=unresolved` and false authorization-consumed,
  execution-authorized and execution-performed flags.

The original report and context are checked against the actual Triage preview
before output. Their complete data lives in the Setup serialization rather than
in a parallel integration-owned diagnostic model. Upstream Setup also retains
its existing nested evidence snapshot; that established format is not rewritten.
Capability records remain authoritative. Setup's `display.collection_errors`
is its existing deterministic derived view, not a second mutable error store.

The preview's limitations are preserved verbatim, including descriptions of its
own unimplemented trust boundary. The composition adds local retained-object
comparison, not authenticated mapping/provenance, and does not relabel those
flags true. No existing report limitations are replaced or silently enriched.

Logs keep received/exported/withheld counts and distinct not-collected,
unavailable, failure, collected-empty, withheld, partial and exported states.
Withheld is not permanent discard. Actual empty arrays remain arrays; missing or
withheld logs remain null. API errors/retry hints stay collection metadata and
never become application HTTP/latency or unsupported-capability conclusions.

The reviewed Mock policy exports only `Synthetic application started`; all other
nonempty/unreviewed text is withheld by Provider before digesting. Missing log
messages also count as withheld. Setup and Triage then reject any sanitizer
change to the bound snapshot. This is a deliberately narrow fixture policy,
not a generic live-log secret detector or a production policy receipt.

Snapshot health remains `unknown`; CPU/RAM, app HTTP/response time and source
timestamp remain null. A collection/component/CLI success is not app health.
No real token/environment file is read. Configured-token redaction and existing
transport timeouts, 4 MiB limits and redirect blocking are unchanged in Provider.

## Run and exit semantics

From the repository root after the [root setup](../README.md#setup-and-run):

```powershell
.\.venv\Scripts\python.exe -B -m integration.mock_backend --mock --scenario partial_failure
```

| Exit | Meaning |
| --- | --- |
| 0 | Mock pipeline completed and every attempted collection component was available; intentionally skipped logs and policy withholding are described separately |
| 1 | Mock pipeline completed with retained diagnosis/context, but at least one attempted component failed or supplied unavailable data |
| 2 | Dependency, association, validation, unexpected integration or output failure; no successful payload is reported |
| 3 | Missing explicit Mock opt-in or invalid CLI/scenario/service; no collection |
| 130 | Operator interruption handled safely |

`--help` is a static exit-0 action. The CLI accepts no credentials or live mode.
Errors use fixed allowlisted codes, no input echo or raw exception text. Broken
output pipes exit 2 without buffered shutdown diagnostics. The partial-failure
example's exit 1 is expected and is not a test-suite failure.

The [complete example](examples/partial_failure.json) was generated by the actual
integrated flow. It is reproducible for the current fixed Mock scenarios and
includes simultaneous log 403/metric 429, null metrics and the actual report.
It is not a captured or sanitized real Liara response.

## Verification

Main assembled checkout, Python 3.13.5 on Windows, with pinned Pydantic 2.14.1,
FastAPI 0.159.1, Starlette 1.9.0, HTTPX 0.28.1 and pytest 9.1.1:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
```

**661 passed**, no skips, one pre-existing TestClient HTTPX deprecation warning.
This includes Provider 119, Setup 99, Triage 416, Provider cross-module QA 9, and
new integration/CLI 18. Tests prove actual component calls, a single diagnosis,
all seven scenarios/real CLI runs, partial metadata preservation, mismatched
service/project/scope/source/request/report rejection, recomputed-digest and
identical-snapshot context tampering rejection, policy-before-association,
detached output, safe canaries/errors and no network/environment-loader,
subprocess or approval activity during the runtime flow. Provider additionally
passed all 119 tests with `python -B -S`, excluding site packages.

The existing Setup historical QA runner also passed its pinned Provider 119,
Setup 99, Provider QA 9 and Task 05A 350 checks. It intentionally tests historical
producer sources, not the new runtime checkout. Run from repository root:

```powershell
.\.venv\Scripts\python.exe -B setup/qa/run_collection_context_checks.py --suite all
```

The existing 23 pinned Provider/Setup implementation checks also passed after
making source preparation portable. They require the original Git objects
(a normal fetch of dependency branches, not an archive/shallow single-branch
checkout). Unlike the runtime, this optional historical QA intentionally uses
verified ignored source copies and an isolated PYTHONPATH:

```powershell
$qaPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$qaLocation = Get-Location
$qaPreviousPath = $env:PYTHONPATH
try {
    Set-Location -LiteralPath .\apps\liara\triage
    & $qaPython -B qa/prepare_collection_context_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Source preparation failed.' }
    $qaModule = (Get-Location).Path
    $env:PYTHONPATH = "$qaModule\.tmp\collection_context_sources\provider-66655e6;$qaModule\.tmp\collection_context_sources\setup-7e55925;$qaModule\src"
    & $qaPython -B -m pytest -p no:cacheprovider -q qa/test_collection_context_implementations.py
} finally {
    Set-Location -LiteralPath $qaLocation.Path
    $env:PYTHONPATH = $qaPreviousPath
}
```

The historical Setup combined runner retains its existing anyio assertion-rewrite
warning as well as the visible TestClient warning; warnings are not suppressed
and dependencies were not upgraded to silence them. Historical task documents
retain their original runtime reports. This integration does not claim its own
Python 3.11/3.12/3.14 or Linux test run.

## Remaining work

The connected non-UI request/approval journey is now available through
`python -B -m integration.workflow_demo --mock`. It retains existing component
contracts, uses explicit isolated Mock approval composition, and leaves
authorization consumption and execution disabled. See [WORKFLOW.md](WORKFLOW.md).
The Incident
contract in PR #15 remains a proposal; no shell, browser components, rendering
or frontend build is part of this backend delivery.

Real read-only Liara collection requires separately supplied secure account and
service configuration and reviewed evidence. Production context diagnosis needs
authenticated service/account/ACL resolution, protected transport and an agreed
endpoint/response contract. Current-request reference retention, durable
association/approval/audit stores, freshness/replay policy, sanitizer ownership
and review receipts must be designed for their real trust boundary. A future
executor needs separate implementation and authorization review. No sensitive
operation, real Approval, restart/redeploy or deployment is enabled by this profile.
