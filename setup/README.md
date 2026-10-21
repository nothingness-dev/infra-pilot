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
from result objects. Dataclasses are frozen, with string-only request details;
runtime request validation will be handled by this module, separately from
Roham's future provider capability validation.

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
