# Executed outcome verification - 2026-10-23

Base: `origin/main` at `733a4ffac2d996f1767335a277337ffbec8823b3`.
GitHub confirmed PR #17 merged; its request-to-approval workflow and PR #16's
original integrated backend are present. The working tree was clean before
creating `feat/backend-outcome-evaluation`. Only Incident UI documentation PR #15
remained open. No merge, branch rewrite or force-push was performed.

Implementation: `28b3a3e`. Tests: `12d6baf`. Later delivery changes add
documentation and generated output; shared component code is unchanged.

## Environment and actual checks

Windows, Python **3.13.5**, existing isolated root `.venv`. Dependency profile
remains Pydantic 2.14.1, FastAPI 0.159.1, Starlette 1.9.0, HTTPX 0.28.1 and pytest
9.1.1. No dependency declaration or constraint changed. `pip check` reported no
broken requirements.

| Executed command | Result |
| --- | --- |
| `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q` before changes | 691 passed, 628 passing subtests, one existing TestClient warning |
| `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q` on final runtime/tests | **730 passed**, 683 passing subtests, one existing TestClient warning |
| `python -B -m unittest discover -s provider/tests -t . -v` using base Python | **119 passed** |
| Targeted new test file during implementation | 37 passed at that stage; two additional retention/failure tests are included in the final full suite |

The final total is the unchanged 691-test baseline plus **39 new tests**. It
includes all existing configured Provider, Setup, Triage, cross-module QA and
integration tests. Component/targeted checks overlap; do not add them to 730.
Existing tests and warning settings were not weakened or changed. Optional
historical pinned-source QA tools were not rerun; their historical reports
remain unchanged. No other Python version/platform run is claimed.

## Actual CLI coverage

All **28** scenarios were launched in real CLI subprocesses with parseable JSON,
empty stderr and false real execution/authorization/causality/remediation flags.

| Exit | Scenarios |
| --- | --- |
| 0 | improvement, no_change, deterioration, mixed_changes, simulated_improvement |
| 1 | insufficient_evidence, coverage_loss, partial_collection, empty_logs, missing_logs, withheld_logs, partial_logs, semantics_mismatch, ambiguous_order, reversed_order, missing_timestamp, stale_samples, future_sample, simulation_order_mismatch |
| 3 | service_mismatch, request_mismatch, action_mismatch, source_mismatch, scope_mismatch, tampered_snapshot, tampered_context, bad_after |
| 4 | approved_not_executed |

The actual CLI generated [simulated improvement](examples/outcome_simulated_improvement.json)
(exit 0) and [partial collection](examples/outcome_partial_collection.json)
(exit 1). These contain synthetic evidence only. Exit 0 also applies to observed
deterioration: it means computation completed, not that a service recovered.

Separate checks covered missing opt-in, unknown/abbreviated arguments, sensitive
canaries, static help, absent site packages, unexpected import/runtime exceptions,
interruption, and a closed output pipe. No raw diagnostic/canary was printed.

A fresh subprocess ran the installed editable package outside repository cwd and
verified no test modules were imported. No source-copy/sys.path bootstrapping,
new environment installation or production deployment is claimed.

## Policy and integrity evidence

- Known health transitions, unknown status, server-error classes and exact
  latency threshold crossings were checked independently of scenario names.
  Actual existing symptom extraction supplied HTTP/latency classifications.
- Mixed supporting directions remained visible. Resource reductions alone
  could not establish improvement. Missing/new primary measurements withheld the
  summary without becoming zero. Fewer logs/hypotheses did not imply recovery.
- Canonical fixtures invoked the actual existing sanitizer and Setup diagnosis
  path. Their declared units/source instants remained separate from Provider
  fixtures. No bound Provider export was enriched with invented telemetry.
- Existing Provider context, null metrics, unknown health, logs 403, metrics 429,
  retryability, limitations and distinct log disposition/count states survived.
  Fixed collector times and advancing a local clock did not establish ordered
  source observations or verified metric units.
- Service, source class, independent scope, request, retained snapshot/context,
  diagnosis and action associations were rechecked. JSON claims, forged/foreign
  references and changed payloads failed closed. Valid before summaries survived
  invalid after data and an unexpected second collection failure.
- Distinct increasing retention order, source-time ordering, missing/equal/
  reversed/future times, timezone-equivalent instants, exact 60-second freshness
  boundary and strict simulated-event bracketing were checked. These are
  controlled fixture checks, not production provenance/freshness assurances.
- Simulated references could not transfer to another identical-looking before
  reference or changed canonical action. The original typed approved workflow
  still reported no action and no post-action evaluation; its serialized JSON
  could not establish execution. A changed workflow action binding was rejected.
- All scenarios ran with sockets, urllib opener construction, subprocesses,
  environment/live configuration loading, production contextual diagnosis and
  `ApprovalGate.authorize` blocked. Pure simulated comparison also worked with
  approval request/grant methods blocked; a synthetic event is not an executor.
- Unrecognized and recognizable sensitive log canaries never reached outcome
  output. Rejected fields, Pydantic warning paths, exception context, mutable
  error-code injection, repr, stderr and safe logs were checked. Summary/result
  copies did not mutate retained evidence.

Changes are inside `integration/`, except the root README. The narrow existing
`CompletedInspection` extension retains the original typed producer reference
and source binding, allowing independent expected-scope verification. Provider,
Setup, Triage, shared schemas/endpoints and dependency files are unchanged.

No UI, listener, live credentials/API request, infrastructure operation, real
authorization consumption, execution receipt, causal recovery proof or deployment
was introduced. Actual authenticated post-action evaluation remains future work.
