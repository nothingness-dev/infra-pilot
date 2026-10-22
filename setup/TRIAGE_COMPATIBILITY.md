# Setup compatibility with published triage (internal proposal)

Actual source access was verified through this clone and authenticated GitHub CLI.
Reported handoff counts and file contents were not accepted as verification.
Setup remains at `setup/`. No incident UI, HTTP server, Diagnosis API, provider
adapter or infrastructure operation is added.

## Verified sources and ancestry

| Source | Actual full SHA |
| --- | --- |
| Current `main` / `origin/main` | `fa84670203d920cad6535208ddcc23e43bf024af` |
| Preserved Setup application boundary | `c5d037b657e7970a3d34c59ce1a28e4ce7b10463` |
| `feature/liara-triage-foundation` (PR #2) | `2b3ed5f9d0969b816c6a1b8d4e15e0c5778b7aa1` |
| `feature/liara-diagnosis-engine` (PR #3) | `ce19889a7c220f2d63e7036851f3178e389423c3` |
| Required `feature/liara-approval-policy` | `835e557b9d97f59522a88527117f759c9779f9d1` |
| Provider contracts inspected, `fix/provider-auth-and-response-handling` | `c9f829f5fa8eff8f2feac520aceeb6ac4bfc3878` |

No newer Diagnosis API branch was present in the fetched branch list. The active
triage package is `apps/liara/triage/src/infrapilot_triage`, not a hypothetical
shared API. Its `__init__` exports the actual engine, models and approval gate.
Provider paths were inspected read-only using Git; provider history is not needed
by this consumer and was not merged.

`feat/setup-triage-compatibility` starts at main and merges only the required
Approval head (which contains Diagnosis and foundation), producing integration
commit `8e3b49ee481d1b5a6825a049a1ed44de7365fbd5`. Main already contains Setup's
reported tip through merged PR #1. No source history is reset or rewritten.
The compatibility draft targets `feature/liara-approval-policy` so the review
diff contains Setup changes. `feat/setup-approval-workflow` will stack on this
completed compatibility branch. Teammate PRs are not merged or retargeted.

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

## Required producer / shared decisions

- Roham's actual provider supports `ping()` and `list_projects()` only. A projects
  result, successful connection, `ProviderStatus.timestamp` or `is_mock` is not
  service-health telemetry or an authorization principal. Example gap:
  `ProviderResult(success=True, data=[{"project_id": "svc-A"}])` cannot supply
  CPU, RAM, HTTP status or logs for a `ServiceSnapshot`. Publish a separately
  reviewed observability adapter, stable project/service mapping, units, source
  labels, sanitized logs and observation timestamps. Unavailable data must stay null.
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
  provider capabilities/execution are still absent. No shared application
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
or force-push was used. Main and open teammate PRs #2/#3 remain intact.

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
setup/.venv/Scripts/python.exe -m pip install "pydantic>=2,<3" "pytest>=8,<10"
$env:PYTHONPATH = (Resolve-Path apps/liara/triage/src).Path
setup/.venv/Scripts/python.exe -B -m unittest discover -s setup/tests -t .
Push-Location apps/liara/triage
try {
    ..\..\..\setup\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
} finally { Pop-Location }
```

Verified compatibility branch: 62 Setup tests and 238 triage tests passed on
Python 3.14.8, Pydantic 2.14.1 and pytest 9.1.1. No provider/live API test is claimed.
Fixtures clearly label all synthetic service evidence `mock`. There is no
repository-wide linter, shared manifest or root CI command in the inspected tree.
