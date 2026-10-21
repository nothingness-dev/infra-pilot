# Provisional Liara setup module — Stage 1

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
python -B -m unittest discover -s setup/tests -t . -v
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

## Integration proposals requiring agreement

`integration.py` accepts data-only `PreparationInputs`: `provider` and `triage`
each contain a `DependencyInput`. An available input must identify an external
output by a nonblank opaque `output_reference`; an unavailable input must give
a nonblank `reason`. An omitted input is unavailable. These constructors reject
malformed internal integration data with `ValueError`.

Roham owns the actual provider outputs, capability checks, snapshots, logs,
authentication, and adapters. Setayesh owns diagnosis and action-proposal
schemas and all authorization decisions. This module only carries references
to those future outputs; it does not fetch, parse, certify, or synthesize them.
The team must agree on reference resolution, freshness, request association,
and payload compatibility before real integration. Caller-supplied availability
and references are not trusted evidence of capability or authorization.

There are no callbacks, plugins, executors, or authorization inputs here. An
absent authorization mechanism can never grant permission. Output availability
will only affect preparation readiness. Execution dependencies remain explicit
and unavailable throughout Stage 1.

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
| `plan_prepared` | Complete brief and applicable external references were supplied. |

Validation errors take priority over missing fields, which take priority over
dependency checks. Valid complete briefs keep a structured candidate plan even
when dependencies block preparation. Invalid or incomplete briefs return no plan.
The provider output reference is needed for both operations; inspection also
needs a triage output reference. These are local preparation dependencies, not
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
new request/input set with the same caller-managed request ID. Previous results
and caller-owned mappings are not modified. No state means running or succeeded.

## Files and offline example

```text
setup/
  .gitignore
  __init__.py
  models.py
  integration.py
  validation.py
  workflow.py
  tests/
    __init__.py
    test_models.py
    test_integration.py
    test_validation.py
    test_workflow.py
  examples/
    __init__.py
    offline_demo.py
  README.md
```

The runnable example prints JSON for five clearly labeled mock scenarios:
complete setup, incomplete input, unsupported operation, unavailable provider,
and complete inspection. `mock:` references are invented labels, not real
provider snapshots, diagnoses, proposals, or approved actions. The mock service
kind is not a claim about supported Liara services. No credentials are used.

Python 3.14.8 was available during implementation; tests use `unittest` with no
installation, network access, or shared discovery configuration. The suite
covers both supported operations, malformed and incomplete input, unsupported
operations, explicit and absent dependencies, preparation-only execution flags,
JSON output, resubmission, and caller input preservation. A behavioral guard
raises on common socket, file, or process APIs during preparation. This is an
offline module test, not a substitute for future integration/security testing.
No provider API, diagnosis, authorization, UI, or deployment check is included.

## Branch ancestry and handoff

The inspected checkout and its configured `origin` had no commits or branches
with an existing implementation. No base commit or team-wide stack was assumed.
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
changed. There is no existing shared test/lint configuration to run. Nothing
has been pushed, merged, published, or deployed.

Before Stage 2 integration, agree with Roham and Setayesh on operation names,
local required fields, preparation-state/error semantics, dependency readiness,
and the opaque external reference format and its resolution, request binding,
freshness, and schema validation. The local rule requiring a provider reference
for setup and both references for inspection is also provisional. No
`DiagnosisReport`, `ActionProposal`, or authorization schema is defined here.

Stage 2 can use those agreements to connect Fatima's request collection and
preparation flow to teammate-owned outputs, then add the corresponding UI when
scheduled. Provider integration, diagnosis, approval policy, real operations,
and deployment remain outside this module's Stage 1 work. No shared-file change
is currently necessary or proposed; future shared-contract promotion requires
team agreement and the appropriate owner's change.
