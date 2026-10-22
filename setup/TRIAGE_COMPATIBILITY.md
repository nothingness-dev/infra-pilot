# Setup compatibility with published triage (internal proposal)

Actual source access was verified through this clone and authenticated GitHub CLI.
Reported handoff counts and file contents were not accepted as verification.
Setup remains at `setup/`. No incident UI, HTTP server, Diagnosis API, provider
adapter or infrastructure operation is added.

## Verified sources and ancestry

| Source | Actual full SHA |
| --- | --- |
| Current `main` / `origin/main` | `0ef27606a2500df334a651a63f57a7ecc492a441` |
| Preserved Setup application boundary | `c5d037b657e7970a3d34c59ce1a28e4ce7b10463` |
| `feature/liara-triage-foundation` (PR #2) | `2b3ed5f9d0969b816c6a1b8d4e15e0c5778b7aa1` |
| `feature/liara-diagnosis-engine` (PR #3) | `ce19889a7c220f2d63e7036851f3178e389423c3` |
| Required `feature/liara-approval-policy` | `835e557b9d97f59522a88527117f759c9779f9d1` |
| Newer `feature/liara-triage-api` | `428237de83631035439afa4d78d9f68f863942b9` |
| Published provider, `feat/liara-service-observability` (merged into main) | `799c752a038a6a5ec1697411bbefb77161457e72` |

The resumed fetch found the published Diagnosis API branch. The active package is
`apps/liara/triage/src/infrapilot_triage`; its original exports, engine, schemas and
policy are unchanged by that API history. The API is internal draft v0.1;
snapshot/report still have no schema version, request ID or report timestamp.
`/health` measures process availability only. Default privileged routes return
503; no HTTP request/approve/reject routes exist. Setup does not call the consuming
`/authorize` route for review or polling.

`feat/setup-triage-compatibility` starts at original main
`fa84670203d920cad6535208ddcc23e43bf024af` and merges the required
Approval head (which contains Diagnosis and foundation), producing integration
commit `8e3b49ee481d1b5a6825a049a1ed44de7365fbd5`. Main already contains Setup's
reported tip through merged PR #1. No source history is reset or rewritten.
On resumption it merges current main's published provider history in
`0be6213e2c7ee282b9dec99bf98eb07335cf06e3`, then the actual API branch in
`7aa8f666245b97a353a1681aa9d4f8c6ac12160b`. These integrations are into our topic
only, without editing producer code. The compatibility draft targets
`feature/liara-triage-api`; its description distinguishes inherited already-merged
provider history from Setup-owned changes. `feat/setup-approval-workflow` stacks
on the completed compatibility tip. Teammate PRs are not merged or retargeted.

## Exact compatibility mapping

| Concern | Existing Setup | Actual producer | Consumer behavior |
| --- | --- | --- | --- |
| Problem input | `OperationRequest(request_id, operation, details)`; details are strings | `diagnose(ServiceSnapshot)`; no natural-language problem argument | Reuse `submit_request` / `supply_information` for intake; `goal` remains user intent, never fabricated telemetry or a new parser |
| Operation | `setup_service`, `inspect_service` | Diagnosis needs observations of an existing service | Only complete `inspect_service` briefs enter this adapter; service creation cannot be diagnosed from a guessed target |
| Target | Exact `details.service_target`, arbitrary nonblank string | Snapshot/report `service_id` uses stripped nonempty text; policy IDs are narrower ASCII, max 128 | Exact equality after canonical validation; no fuzzy lookup, whitespace normalization or guessed mapping |
| Payload | Opaque `DependencyInput.output_reference` | Actual `ServiceSnapshot`, `DiagnosisReport` | `SnapshotEvidence` adds the imported snapshot beside the existing associated reference; no canonical model copies |
| Request association | `ResultMetadata.request_id`, operation and full-brief fingerprint | No workflow request ID, revision or report ID on snapshot/report | Keep association in the Setup wrapper; recheck all fields against the current full brief |
| Version | Exactly `setup-integration-v1` | Snapshot/report have no schema version; package metadata says `0.1.0` | Retain the Setup wrapper version and record tested source SHAs here; do not inject new fields into canonical payloads |
| Provenance | `mock` / `external`; reference prefix must match | `data_source=mock` / `real` | Explicit `mock -> mock`, `external -> real`; labels are assertions, not verified producer identity |
| Time | No freshness timestamp or TTL | Optional aware snapshot/log timestamp; report has no generated timestamp | Preserve original aware timestamps and nulls; no invented report time or freshness guarantee |
| Missing evidence | Old dependency unavailable/pending/failure | Null measurements, `logs=None` vs `logs=[]`, explicit missing information/limitations | Preserve distinctions, zero measurements, ranked hypotheses, evidence links and every limitation |
| Diagnosis actions | No action payload in original Setup | Advisory `ActionProposal(action_id, title, description, risk_level, requires_approval, status)` | Preserve complete proposals; ID/title/flags are not canonical runnable operations or authorization |
| State | `received`, `needs_information`, `blocked`, `plan_prepared`; dependency states `ready/pending/failed/unavailable` | Report is presentation data; proposals only allow `not_executed` | New wrapper uses `evidence_required` / `diagnosis_presented`; original preparation state is retained separately |
| Approval | Old Setup has no authorization inputs | `ActionIntent`, `PolicyDecision`, `ApprovalRequest`, `GateDecision` | Consume separately on the next branch; never reinterpret preparation readiness or proposal labels as approval |

`prepare_diagnosis(request, evidence)` reuses the actual engine. `SnapshotEvidence`
is an internal object with an imported `ServiceSnapshot` and existing
`DependencyInput`. The association must identify the provider slot, current full
brief, supported version, ready state and declared source. A bare available flag
is insufficient. No payload/reference resolution or geocoding is performed.

The returned `DiagnosisPresentation` retains the complete snapshot and report,
with a digest binding reference, metadata, full request fingerprint and canonical
serialized payloads. Mutable canonical models are revalidated at every boundary;
changed evidence/report/request cannot reuse a retained binding. Digests are
not signatures and JSON presentations are not accepted as trusted backend objects.

`submit_problem(payload, *, evidence=None)` and `supply_problem_information(...)`
reuse the existing application functions and return a typed `DiagnosisWorkflow`;
call `.to_dict()` for detached JSON. Invalid or incomplete input never diagnoses.
No evidence yields `evidence_required`, not synthetic observations. Complete,
matched evidence yields `diagnosis_presented`, including incomplete-evidence
reports. The original reference-only preparation can remain `blocked` inside
`preparation`; no fake provider/triage references are manufactured to promote it.
Every outcome retains `execution_performed=false`, `execution_authorized=false`.

`consume_diagnosis(request, evidence, report)` binds an actual producer report
from trusted backend orchestration without recreating it.
`setup.diagnosis_api.consume_diagnosis_response(..., status_code=..., payload=...)`
validates a decoded successful response from the existing
`POST /internal/triage/diagnose`; failed/unusable responses remain errors with
constant safe messages. No server, HTTP client, retry or alternative API is added.
The original snapshot is copied and sanitized using triage's actual
`sanitize_snapshot` before presentation, so raw logs are not redisplayed beside
the API's redacted report. The original input remains unchanged. This sanitizer
is defense in depth, not a general secret detector. Frontend-returned reports
are not accepted as trusted backend evidence or approval credentials.

## Required producer / shared decisions

- Roham's provider now implements read-only details/deployment, logs, metrics,
  releases and partial collection. Source and `provider/CAPABILITIES.md` were
  inspected; no live access was verified. `ServiceObservations` is not a canonical
  snapshot: native status `mock-running` is not normalized health; CPU
  `values=("0.25",)` with `cpu_unit=None` cannot become `cpu_usage_percent`, and
  memory with unknown units cannot become MiB. Native log type/time is not agreed
  severity/aware source time. Collector times are not source freshness. Application
  HTTP health/response latency is not collected. An actual mock partial bundle
  with permission-denied logs is tested and refused as a canonical snapshot.
  Roham must propose explicit identifier/health/unit/log-time normalization and
  availability/window semantics; unresolved fields stay null rather than guessed.
- Agree how a trusted composition layer associates an actual snapshot/reference
  to a Setup brief. The Setup fingerprint is a local association, not a producer
  signature, freshness proof, cross-service identity resolver or shared contract.
- Setayesh's proposals such as `review_resource_configuration` are not policy
  operation IDs. A reviewed backend mapping must explicitly choose a canonical
  `ActionIntent` and its parameters; no generic restart/resource change is inferred.
  Triage's `policy_version="triage-approval-v1"` and 64-character action fingerprint
  bind service, operation and canonical parameters, not Setup request/report/proposal.
  Setup must retain those additional bindings around the gate without changing it.
- Agree on freshness windows, report/schema versioning, log completeness and
  sanitized transport before production use. Snapshot `timestamp=None` is valid;
  it cannot be upgraded to current/live evidence.
- Real authentication/ACLs, durable approval/audit storage, shared API routing and
  provider operation capability validation/execution are still absent. No shared application
  registration or competing Diagnosis API is implemented here.

## Git preparation and remaining remote rename

Fetch/prune/tags and clean tracked main's `pull --ff-only` completed. Four owned
local refs were renamed non-overwriting at exactly the same SHAs:

| Old name | New name | Unchanged SHA |
| --- | --- | --- |
| `feat/liara-fatima-setup-foundation` | `feat/liara-setup-foundation` | `9c6e7229e126f203369c901638a6d06e8aa5b370` |
| `feat/liara-fatima-setup-request-flow` | `feat/liara-setup-request-flow` | `f30e3f0d65ad95d2c606dd1e3117cb1b81c097b0` |
| `feat/liara-fatima-setup-integration` | `feat/liara-setup-integration` | `c6cb653c9f3a254df32db1868d9dd69752d57446` |
| `feat/liara-fatima-setup-application-boundary` | `feat/liara-setup-application-boundary` | `c5d037b657e7970a3d34c59ce1a28e4ce7b10463` |

The last three remote refs were renamed using GitHub's native mechanism after
checking protection and open PR heads/bases. Their new upstreams and SHAs match.
No open PR used those refs; PR #1 was already merged. No manual remote ref deletion
or force-push was used. Main and open teammate PRs #2/#3/#4 remain intact.

**Pending:** remote `feat/liara-fatima-setup-foundation` at
`9c6e7229e126f203369c901638a6d06e8aa5b370` is still GitHub's default branch.
Authenticated access is WRITE, not admin. Its local topic-only name deliberately
still tracks the old remote ref. An owner/admin must coordinate any native rename
to `feat/liara-setup-foundation`; there are no open PR heads/bases to migrate for
that ref. No default branch change was made. Main exists and no common-base
creation decision remains. See [GitHub branch-renaming rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/renaming-a-branch).

## Reproducible environment and checks

Original Setup baseline was independently verified: 53 unittest tests passed
with Python 3.14.8, plus its thirteen-scenario offline example. Legacy intake
and preparation still import with the standard library only. The new optional
consumer requires the actual triage package's Pydantic dependency.

A fresh ignored `setup/.venv` keeps all new environment files inside ownership.
Its Pydantic/pytest constraints match triage's `pyproject.toml` / `requirements.txt`;
`PYTHONPATH` selects the actual source package without an editable install that
would generate files in teammate paths. No shared dependency file was changed.

```powershell
python -m venv setup/.venv
setup/.venv/Scripts/python.exe -m pip install "pydantic>=2,<3" "pytest>=8,<10" "fastapi>=0.115,<1" "uvicorn>=0.30,<1" "httpx>=0.27,<1"
$env:PYTHONPATH = (Resolve-Path apps/liara/triage/src).Path
setup/.venv/Scripts/python.exe -B -m unittest discover -s setup/tests -t .
Push-Location apps/liara/triage
try {
    ..\..\..\setup\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
} finally { Pop-Location }
```

The initial checkpoint was independently rerun: 62 Setup / 238 triage tests passed.
After integrating the newer API: **69 Setup / 313 triage tests pass** on Python
3.14.8, Pydantic 2.14.1, pytest 9.1.1, FastAPI 0.159.1, Starlette 1.9.0,
HTTPX 0.28.1 and Uvicorn 0.54.0. The documented Starlette HTTPX TestClient
deprecation warning remains. API tests are in-process; no live provider/API test
is claimed.
Fixtures clearly label all synthetic service evidence `mock`. There is no
repository-wide linter, shared manifest or root CI command in the inspected tree.
The producer guide's `C:\git\shared` path belongs to its workstation. The user
explicitly authorized this verified clone at `C:\Users\FATIMA\GitHub\infra-pilot`;
the same documented dependency/source contracts are tested here, keeping generated
environment artifacts inside ignored `setup/.venv`.
