# Liara Setup preparation and triage workflow

Current continuation: [TRIAGE_COMPATIBILITY.md](TRIAGE_COMPATIBILITY.md) documents
the actual published Diagnosis integration, source SHAs and remaining producer
gaps. [APPROVAL_WORKFLOW.md](APPROVAL_WORKFLOW.md) completes the backend-only
approval handoff, source ancestry, exact verification and proposed shell/incident
props/callbacks. `setup.triage` consumes canonical Diagnosis models;
`setup.diagnosis_api` validates the existing API's responses;
`setup.approval_workflow` delegates review/request/approve/reject to the actual
policy/gate. All execution indicators remain false, and there is no executor.
The optional consumers/tests use triage's documented dependencies in ignored
`setup/.venv`; legacy intake and preparation remain standard-library only.
Setup stays here and existing application functions are preserved.

## Historical Stages 1–3

The descriptions below record the original reference-only foundation, not current
claims that teammate code or these optional consumers are absent. For full current
tests/environment and the new offline approval example, use APPROVAL_WORKFLOW.md.

Fatima owns this isolated, framework-independent Python 3 module. Its models
are **local proposals awaiting team agreement**, not approved shared contracts
or a repository-wide stack decision. It uses only the Python standard library.

The module describes request preparation. It has no provider adapter, network
client, diagnosis implementation, authorization policy, executor, HTTP endpoint,
database, UI, or deployment configuration. A prepared plan cannot authorize an
operation. All results explicitly report that execution and authorization have
not occurred. State names describe preparation only.

`setup/__init__.py` is the Python package marker (rather than `init.py`).
No installation or dependency manifest is needed. Run from the repository root:

```powershell
setup/.venv/Scripts/python.exe -B -m unittest discover -s setup/tests -t . -v
python -B -m setup.examples.offline_demo
```

`models.py` defines local request, missing-information, plan, dependency, error,
and preparation-state proposals. JSON representations detach collected values
from result objects. Dataclasses are frozen, with string-only request details.
`validation.validate_request()` checks local inputs separately from Roham's
future provider capability validation.

## Provisional request briefs

| Operation | Required details | Optional details |
| --- | --- | --- |
| `setup_service` | `service_name`, `service_kind`, `goal` | `plan`, `region`, `budget` |
| `inspect_service` | `service_target`, `goal` | none |

Each `OperationRequest` also requires a nonblank string `request_id` and an
exact supported `operation`. Required details are a local planning convention,
not a claim about Liara's API requirements or supported service types. A complete
brief is sufficient for local workflow preparation, never for deployment.

Detail values must be strings. Blank required strings produce structured missing
information. Wrong types, blank optional values, and unknown detail names produce
structured errors; unknown operations produce `unsupported_operation`. Unknown
operations are not mapped to setup or guessed from natural language. Values are
preserved verbatim, including nonblank whitespace. No target, plan, region,
budget, cost, or provider-specific parameter is inferred. Optional choices may
remain absent: determining applicable provider requirements and requesting any
remaining operational choices is deferred to the future provider handoff.

## Application boundary (Stage 3)

`setup.application` is a small, module-local **provisional Python interface** for
a future transport layer. It is usable now without teammate modules. It is not
an approved shared contract, an HTTP API, a server, or a repository entry point.

```python
import json
from setup.application import submit_request, supply_information

first = submit_request({
    "request_id": "example-1", "operation": "inspect_service", "details": {},
})
assert first["state"] == "needs_information"

current = supply_information(first["request"], {
    "service_target": "example-service", "goal": "Prepare an inspection",
})
assert current["state"] == "blocked"  # Provider and triage outputs are absent.
assert current["plan"] is not None     # Candidate preparation plan is available.
assert current["execution_performed"] is False
assert current["execution_authorized"] is False
print(json.dumps(current, allow_nan=False))
```

| Function | Inputs | Result |
| --- | --- | --- |
| `submit_request(payload, *, dependency_inputs=None)` | A decoded JSON request object. | Current preparation state, missing information, errors, and candidate plan. |
| `supply_information(request_payload, additional_information, *, dependency_inputs=None)` | A retained request snapshot and additional detail fields. | Revalidated outcome with the same ID and operation. |

Public request objects allow only `request_id`, `operation`, and `details`.
Required/optional detail names and string validation are the existing rules
above. Raw JSON text must be decoded by the caller first. Additional information
is a detail object; it cannot set envelope fields or change the request identity
or operation. Unknown fields, including dependency, approval, authorization, and
execution claims, are rejected. Nothing interprets request text as commands.

Both functions reuse `PreparationResult.to_dict()` and add one field, `request`,
for stateless continuation. It contains a detached JSON request snapshot with
valid ID, supported operation, and accepted nonblank detail strings. Missing
details remain absent; strings are preserved verbatim. The snapshot is `None`
when no usable request exists, such as an unidentified, unsupported, or invalid
request. Invalid non-object additions can retain the previous valid snapshot;
invalid detail changes return no snapshot. Keep the last accepted request when
correcting an error. Every outcome explicitly reports both execution and
authorization as false, including preparation-ready results.

Pass `response["request"]` into completion or resubmit it to reevaluate the
current outcome. The interface stores no requests or dependency results. The
caller retains/retrieves the original accepted request; preserving identity
within that request is not an authentication or ownership guarantee.

Malformed object shapes return structured errors. Unknown envelope keys take
priority, return `unknown_field`, and suppress the plan. Domain errors such as
`invalid_field` and `unsupported_operation`, and existing missing-information
records, keep their established conventions. Rejected arbitrary input values
are not echoed into snapshots, so results serialize with standard `json.dumps`,
including `allow_nan=False`. Invalid input is handled explicitly; programming
exceptions are not broadly caught or hidden.

`dependency_inputs` is a separate keyword-only, typed `PreparationInputs` value
for internal orchestration, never a public payload field. A future HTTP layer
must obtain it separately from user request information. The existing domain
association/version/state/provenance checks still apply, and results are checked
again after any detail update. This input cannot grant authorization. Missing
teammate implementations return the existing blocked outcome with unavailable
dependencies; no output, readiness, trust, permission, or execution is fabricated.

## Integration proposals requiring agreement

`integration.py` accepts data-only `PreparationInputs`: `provider` and `triage`
each contain a `DependencyInput`. An available input must identify an external
output by an opaque `output_reference` and provide associated `ResultMetadata`;
an unavailable input must give a nonblank `reason`. An omitted input is
unavailable. Existing constructors still reject malformed core fields with
`ValueError`; metadata, association, state, and reference-format failures become
structured workflow errors. See [INTEGRATION.md](INTEGRATION.md) for the complete
provisional grammar and the intentional change to legacy available inputs.

Roham owns the actual provider outputs, capability checks, snapshots, logs,
authentication, and adapters. Setayesh owns diagnosis and action-proposal
schemas and all authorization decisions. This module only carries references
to those future outputs; it does not fetch, parse, certify, or synthesize their
payloads. It validates coordination metadata only.
The team must agree on reference resolution, freshness, request association,
and payload compatibility before real integration. Caller-supplied availability
and references are not trusted evidence of capability or authorization.

There are no callbacks, plugins, executors, or authorization inputs here. An
absent authorization mechanism can never grant permission. Output availability
will only affect preparation readiness. Execution dependencies remain explicit
and unavailable throughout all preparation stages. Freshness and authenticity
are not evaluated; no real teammate compatibility has been established.

## Preparation behavior

Call `workflow.prepare_request(request, inputs=None)` to receive a
`PreparationResult`. Its `to_dict()` output contains collected information,
missing fields, structured errors, a candidate plan when applicable, and explicit
`execution_performed: false` and `execution_authorized: false` indicators.

Each invocation records `received` first in `state_history`, followed by:

| State | Meaning |
| --- | --- |
| `needs_information` | Required local brief fields are missing; no plan yet. |
| `blocked` | Invalid/unsupported input, or an unavailable preparation dependency. |
| `plan_prepared` | Complete brief and structurally compatible, associated external references were supplied. |

Validation errors take priority over missing fields, which take priority over
dependency checks. Valid complete briefs keep a structured candidate plan even
when dependencies block preparation. Invalid or incomplete briefs return no plan.
The provider output reference is needed for both operations; inspection also
needs a triage output reference. Each ready result must pass the local version,
request, full-brief fingerprint, producer, state, and provenance checks.
These are local preparation dependencies, not
assertions about how Liara or triage must work. Missing inputs never produce
synthetic snapshots or diagnoses. Setup does not require or use triage results.

Even `plan_prepared` lists unavailable **execution** dependencies: provider
capability/requirement validation, authorization validation, and an executor.
Those do not block the preparation state; they prevent any interpretation that
the plan is ready to execute. The module cannot accept approval or execute steps.
Steps are descriptions, not executable tasks, and make no API-capability claims.
Applicable service requirements, exact plan/region choices, and costs remain
unresolved until the provider module and user supply them.

No state is persisted. To resolve missing information or dependencies, submit a
new request/input set with the same caller-managed request ID, or use
`completion.complete_request(request, additional_information, inputs=None)`.
The completion helper returns the updated `.request` and `.preparation`, keeping
identity and operation fixed and rechecking any supplied dependency metadata.
Previous results and caller-owned mappings are not modified. No state means
running or succeeded.

## Files and offline example

```text
setup/
  .gitignore
  __init__.py
  models.py
  integration.py
  completion.py
  application.py
  validation.py
  workflow.py
  tests/
    __init__.py
    fixtures.py
    test_models.py
    test_integration.py
    test_validation.py
    test_workflow.py
    test_result_association.py
    test_integrated_workflow.py
    test_completion.py
    test_application.py
  examples/
    __init__.py
    offline_demo.py
  README.md
  INTEGRATION.md
```

The existing runnable example retains ten clearly labeled mock domain scenarios:
complete setup, incomplete input, unsupported operation, unavailable provider,
complete inspection, pending triage, failed provider, missing triage, incremental
request completion, and a changed target rejecting old results. `mock:` references
are invented labels, not real provider snapshots, diagnoses, proposals, or
approved actions. The mock service
kind is not a claim about supported Liara services. No credentials are used.
Three application scenarios also demonstrate submission with missing information,
completion while teammate modules are absent, and rejection of a public
authorization claim. These boundary calls use no teammate fixtures. All thirteen
scenarios are printed by the same command; there is no second demo.

Python 3.14.8 was available during implementation; tests use `unittest` with no
installation, network access, or shared discovery configuration. The suite
covers both supported operations, malformed and incomplete input, unsupported
operations, explicit and absent dependencies, preparation-only execution flags,
JSON output, resubmission, and caller input preservation. A behavioral guard
raises on common socket, file, or process APIs during preparation. This is an
offline module test, not a substitute for future integration/security testing.
Stage 1's verified baseline was 25 passing tests. Stage 2 had 42 passing tests,
retaining all original behavior tests with request-bound ready fixtures. Stage 3
retains those tests and adds 11 focused application-boundary tests (53 total).
The demo
explicitly labels its contracts provisional, its data mocked, and real teammate
compatibility and freshness unverified. No provider API, diagnosis, authorization,
UI, or deployment check is included.

## Branch ancestry and handoff

At the start of Stage 1, the inspected checkout and its configured `origin` had
no commits or branches with an existing implementation. No base commit or
team-wide stack was assumed.
The provisional Python/unittest configuration applies only to this module.

1. `feat/liara-fatima-setup-foundation` was created while history was empty,
   before the root commit `6671839` (models and scoped module foundation).
   Its second commit/tip is `9c6e722` (data-only integration inputs).
   This branch has **no base commit**; no commit was created on `main`.
2. `feat/liara-fatima-setup-request-flow` was created at `9c6e722`, the latest
   foundation commit. Validation, preparation behavior, tests, and the example
   build on that foundation. It includes the foundation history and must be
   reviewed as a dependent branch, not an independent changeset.

Inspect the exact local commits with:

```powershell
git log --reverse --oneline feat/liara-fatima-setup-request-flow
git diff feat/liara-fatima-setup-foundation...feat/liara-fatima-setup-request-flow -- setup/
```

All Stage 1 files are within `setup/`. No protected files, shared contracts,
manifests, root configuration, teammate modules, or shared CI were needed or
changed. There is no existing shared test/lint configuration to run. The two
Stage 1 branches were subsequently pushed at the user's request. Stage 2 remains
local; no merge, publication, or deployment is part of this work.

Before real teammate integration, agree with Roham and Setayesh on operation names,
local required fields, preparation-state/error semantics, dependency readiness,
and the opaque external reference format and its resolution, request binding,
freshness, and schema validation. The local rule requiring a provider reference
for setup and both references for inspection is also provisional. No
`DiagnosisReport`, `ActionProposal`, or authorization schema is defined here.

Stage 2 prepares the isolated coordination path using provisional fixtures; it
does not implement real teammate integration. Provider integration, diagnosis,
approval policy, real operations, UI, and deployment remain outside these stages.
No shared-file change is currently necessary or proposed; future shared-contract promotion requires
team agreement and the appropriate owner's change.

## Stage 2 verified base and local checks

`feat/liara-fatima-setup-integration` starts at verified Stage 1 request-flow tip
`f30e3f0d65ad95d2c606dd1e3117cb1b81c097b0`. The initial worktree was clean, with
one worktree and only the two advertised Stage 1 remote branches. No applicable
`AGENTS.md`, root README, approved contracts, or team decisions were present.
All Stage 2 implementation, tests, fixtures, demo edits, and documentation remain
under `setup/`; no shared configuration or dependency installation was needed.

Run the two commands at the top of this document from the repository root.
Review whitespace, file scope, and the complete Stage 2 changes with:

```powershell
git diff --check f30e3f0d65ad95d2c606dd1e3117cb1b81c097b0 HEAD
git diff --name-only f30e3f0d65ad95d2c606dd1e3117cb1b81c097b0 HEAD
git diff f30e3f0d65ad95d2c606dd1e3117cb1b81c097b0 HEAD
git log --reverse --oneline f30e3f0d65ad95d2c606dd1e3117cb1b81c097b0..HEAD
```

Stage 2 identified future compatibility work requiring an agreed coordination
envelope and sanitized teammate outputs. Stage 3 instead delivers the independent
application boundary while those outputs remain unavailable. See
[INTEGRATION.md](INTEGRATION.md) for the unresolved integration decisions. Real
calls, diagnosis, approval decisions, execution, UI, and deployment remain outside
this preparation work.

## Stage 3 application-boundary handoff

The verified base is Stage 2 tip
`c6cb653c9f3a254df32db1868d9dd69752d57446`, with a clean worktree, 42 passing
tests and 10 working demo scenarios. Inspection found no existing application
payload interface. The topic branch is
`feat/liara-fatima-setup-application-boundary`; all commits remain local.

This stage changes only `setup/application.py`, `setup/tests/test_application.py`,
`setup/examples/offline_demo.py`, and this README. Models, validation, completion,
workflow preparation, dependency association, and existing tests are reused
without changes. No shared configuration, dependencies, or teammate files were
needed. Verify the final stage diff and local commits with:

```powershell
git diff --check c6cb653 HEAD
git diff --name-only c6cb653 HEAD
git diff c6cb653 HEAD
git log --reverse --oneline c6cb653..HEAD
```

The independent backend work is complete through request intake, validation,
missing-information collection, preparation coordination, and this JSON boundary.
Actual provider/triage output consumption, real reference resolution and
freshness/authenticity validation require teammate implementations and agreed
contracts. Roham retains provider/API/snapshot responsibilities; Setayesh retains
diagnosis, proposals, and authorization policy. Their current absence does not
block using or reviewing this interface. Real operations, UI, storage, HTTP,
and deployment have not been added, and no next stage is started here.
