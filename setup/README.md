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
