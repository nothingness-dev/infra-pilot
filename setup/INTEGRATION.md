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
