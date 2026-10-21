# Stage 2 coordination proposal

This is an isolated **module-local proposal**, not an approved shared contract.
No approved contracts or documented team agreement were found in the inspected
checkout or either advertised remote branch. No actual teammate output has been
verified against this interface. Provider and diagnosis payloads stay opaque.

## Result metadata

The existing `DependencyInput(available, output_reference, reason)` gains optional
`metadata: ResultMetadata`. Existing constructor checks remain in place. New
metadata checks return `StructuredError` values via `validate_dependency_input`.

| Metadata field | Local rule |
| --- | --- |
| `contract_version` | Exactly `setup-integration-v1`; unknown versions are rejected. |
| `request_id` | Exact current request identifier. |
| `operation` | Exact current request operation. |
| `request_fingerprint` | `request_fingerprint(request)` for the entire complete brief. |
| `source` | `provider` or `triage`, matching the supplied dependency slot. |
| `state` | `ready`, `pending`, `failed`, or `unavailable`. |
| `provenance` | `mock` or `external`; neither establishes authenticity. |

All metadata fields must be nonblank strings. `available` must agree with the
state: only `ready` may be available. Nonready results carry a reason instead of
an output reference. A legacy unavailable input is still a blocking signal;
legacy available inputs lack association and cannot establish readiness.

Ready references use the **provisional** grammar
`(mock|external):[A-Za-z0-9][A-Za-z0-9._-]*`, matched in full. The prefix must
match `provenance`. These are opaque identifiers, not URLs, paths, API formats,
or values to resolve automatically. `external` only means caller-declared
non-mock origin; no compatibility with real outputs has been established.

The fingerprint is `sha256:` plus the lowercase SHA-256 digest of an ASCII
JSON encoding of `{contract_version, request_id, operation, details}`, using
sorted object keys, `ensure_ascii=True`, and separators `(',', ':')`. The
contract version is the constant above; details are the complete validated
collected information, with exact string values. Key order is irrelevant;
changes to identity, operation, target, goal, or optional choices invalidate old
associations. This deliberately conservative rule avoids stale result reuse.

## Trust and freshness limits

These checks establish structural compatibility and exact request association
only. Callers can reproduce a fingerprint or assert a source/provenance. Nothing
here verifies payload contents, producer identity, authenticity, or permission.
No raw logs, diagnoses, or action proposals are interpreted or generated.

Freshness rules remain undecided. No expiry, timestamp validation, clock, or
production freshness default is implemented. Even a structurally ready reference
may be stale; do not interpret preparation readiness as production usability.
The team must specify freshness requirements and an explicit externally supplied
policy before freshness checks are added; those checks will need a controlled
clock in tests. Execution and authorization remain absent.

## Workflow outcomes and compatibility

`prepare_request` validates applicable dependency envelopes before declaring
`plan_prepared`. `pending`, `failed`, missing, and unavailable inputs all use the
existing `blocked` preparation state, with distinct structured error codes.
Malformed or mismatched metadata, unknown versions/states, and unusable references
also block. Invalid references are omitted from the returned candidate plan.
The serialized dependencies expose recognized `reported_state`, `provenance`,
and `contract_version`; invalid values are not copied into the output.

The local briefs, states, precedence of request validation, candidate-plan
behavior, lack of persistence, and permanent execution/authorization flags are
reused from Stage 1. Setup still needs only a provider result; inspection needs
both provider and triage results. No result is fetched or interpreted.

**Intentional safety change:** the legacy constructor remains callable, but a
bare `available=True`/reference pair is now blocked with
`dependency_metadata_required`. It must be accompanied by the associated versioned
metadata to become preparation-ready. Legacy unavailable inputs remain blocked
with their supplied reason. Original Stage 1 behavior tests are retained, with
ready fixtures upgraded to include the new metadata. Passing these fixtures
demonstrates local structural compatibility only, not real teammate integration.

## Completing missing information

Stage 1 already revalidated explicitly resubmitted requests. Its concrete gap
was the lack of an incremental merge operation that preserves established
identity and gives the caller the resulting request for further completion.
`completion.complete_request(request, additional_information, inputs=None)`
fills that gap, using the existing validator and workflow rather than a second
state machine. It returns `RequestCompletion(request, preparation)`.

`additional_information` patches detail fields only. The original ID and
operation are retained; attempts to pass envelope fields as details are rejected
by existing validation. Unknown or wrongly typed detail values remain errors.
The helper can replace incorrect known detail values and returns remaining
missing information. Invalid non-mapping additions return a structured error;
if the original has no usable identity/operation/details mapping, the returned
request is `None` and ordinary preparation explains the original problem.

Use the returned `.request` for another completion and `.preparation.to_dict()`
for the structured preparation outcome. Valid string-valued details are copied,
and caller inputs are not modified. No state or dependency results are cached.
Any supplied results are checked against the entire merged brief. Changing a
target, goal, service kind, or optional choice invalidates old associations;
identical updates keep them compatible. The helper cannot grant permission or
perform an operation. Newly associated results must come from the caller; the
module never silently rebinds old metadata to an edited request.

## Decisions and blockers before real integration

| Owner | Decisions or evidence needed |
| --- | --- |
| Roham | Actual provider result/reference format and version; producer identity; snapshot/capability output association; readiness/failure semantics; freshness requirements and reference resolution. |
| Setayesh | Actual triage result/reference format and version; diagnosis/proposal request and target association; readiness/failure semantics and freshness; a separate interface for teammate-owned authorization validation in a later stage. |
| Both teammates and Fatima | Operation/identity fields, preparation-state semantics, required dependency slots, provenance labels, binding canonicalization or an agreed alternative, and which request edits invalidate which results. |

No approved contracts, validated real output fixtures, authenticity mechanism,
reference resolver, or agreed freshness policy are available in this checkout.
These block claims of real integration or production compatibility. The local
fingerprint and reference grammar may need replacement after team agreement;
they have not been published into `contracts/` or `shared/`.

No protected-file change is necessary for this stage. If the team later chooses
shared contracts, their owner must publish them and Fatima's module can consume
them read-only. The next backend step is obtaining the agreed schemas and
sanitized fixtures, then verifying a small offline translation path. It does not
require a provider adapter, diagnosis logic, approval policy, or execution path
inside this module.
