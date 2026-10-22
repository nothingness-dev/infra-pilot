# Executed workflow verification - 2026-10-23

Base: `origin/main` at `e5d3ffdf747c7cb438aba5d1d8a818f59ccb5a6c`, the merged
PR #16. GitHub also confirmed PR #12 merged; only Incident UI documentation
PR #15 remained open. The working tree was clean before creating
`feat/backend-request-approval-workflow`. No existing branches were rewritten.

Runtime implementation: `81998b0`. New tests: `28aac3f`.
The remaining delivery changes are documentation and actual generated Mock output.

## Environment and checks

Executed on Windows, Python **3.13.5**, using the existing isolated root `.venv`.
Installed versions: Pydantic 2.14.1, FastAPI 0.159.1, Starlette 1.9.0,
HTTPX 0.28.1 and pytest 9.1.1. No package or dependency constraint was changed.
`python -m pip check` reported no broken requirements.

| Command | Actual result |
| --- | --- |
| `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q` before changes | 661 passed, 573 passing subtests, one existing TestClient warning |
| `.\.venv\Scripts\python.exe -B -m unittest integration.tests.test_backend -v` | All 18 original integration tests passed |
| `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q integration/tests` | 48 passed, 85 passing subtests |
| `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q` after implementation | **691 passed**, 628 passing subtests, one existing TestClient warning |
| `python -B -m unittest discover -s provider/tests -t . -v` | **119 passed** using base Python |

The 691 total is the unchanged 661-test baseline plus 30 new workflow tests.
Component/targeted runs overlap with that total; do not add them together.
Existing Setup and Triage tests are included in the configured full suite. The
original optional pinned-source historical QA tools were not rerun for this
integration-only continuation; their prior reports remain historical evidence.
No tests were weakened, skipped, or changed to suppress the existing warning.

## Actual command scenarios

The new test suite launched the real CLI in a separate process for every
documented scenario, parsed its JSON, checked empty stderr, and verified its
non-execution indicators:

| Exit | Executed scenarios |
| --- | --- |
| 0 | complete, complete_information, empty, not_collected, withheld, partial_logs |
| 1 | partial_failure, unavailable |
| 3 | invalid_completion, changed_target |
| 4 | needs_information, unmapped_action, policy_denied, approval_pending, approved_not_executed, approval_rejected, approval_expired, unauthenticated, permission_denied |

Separate CLI checks exercised missing opt-in, unrecognized/abbreviated arguments,
sensitive canaries, static help, missing site packages, unexpected exceptions,
interruption and broken/closed output streams. Invalid input did not echo its
values. Missing dependencies returned a safe code 2 rather than a traceback.

The actual `approved_not_executed` CLI generated
[`examples/workflow_approved_not_executed.json`](examples/workflow_approved_not_executed.json).
It exited 4, had empty stderr, retained actual engine/policy/gate output and
reported all execution/authorization-consumption indicators false. The stored
approval is approved with no consumer, not an executed operation. UUIDs identify
that isolated synthetic run and change on future runs.

Using the installed editable environment, the actual `complete_information`
command also ran with its working directory outside the repository. It returned
exit 0, valid JSON, empty stderr and `policy_reviewed_not_executed`, demonstrating
normal package imports rather than a repository-CWD path workaround. No fresh
environment or alternative Python/platform run is claimed for this milestone.

## Behavioral and failure evidence

- Spies confirmed actual Setup intake/completion, Mock Provider collection,
  Triage diagnosis, Setup consumption and policy review. A completed information
  journey collected and diagnosed exactly once. Repeated inspection reads did
  not repeat diagnosis.
- Incomplete/rejected briefs did not collect or request approval. Controlled
  information completion preserved identity. Out-of-profile text, claims and
  target changes were rejected without echoing rejected field names or values.
- The final plan used actual retained output associations. Request fingerprint,
  diagnosis binding, collection companion and canonical action remained linked.
  Changed request/target/snapshot/context/report/action and foreign inspection
  objects were rejected before approval transitions.
- Actual gate/store records covered pending, approved, rejected, exact-boundary
  expiration, missing/foreign identities, permission denial/revocation and invalid
  clocks. Independent stores/sessions prevented cross-run identity reuse. A
  repeated operator example did not create another request or grant. Neither
  Mock identity was granted execution permission.
- Logs 403 and metrics 429 remained separate errors. Missing logs were not empty;
  withheld and partial export counts remained correct. CPU/RAM/application
  response measurements stayed null, and service health stayed unknown.
- Injected collection, diagnosis, final preparation, review and approval failures
  retained valid prior stages. A failed diagnosis retained collected evidence;
  an approval failure retained the prior pending state. Failed stages could not
  resume as successful inspection without resubmission/completion.
- Runtime checks blocked sockets, urllib opener construction, subprocesses, live
  configuration loading, environment lookups, production contextual diagnosis and
  `ApprovalGate.authorize`. All 19 scenarios still produced their expected
  non-executing outcomes. A fresh-process check found no runtime imports from
  test modules or other demonstration harnesses.
- A raw log containing an Authorization canary was withheld by the existing
  Provider export policy before binding. Workflow JSON, repr, stdout, stderr and
  captured logs contained no canary. Injected raw component exception text and
  rejected input canaries did not cross the workflow/CLI boundary.

No UI, server listener, live credentials, live API call, real authentication,
infrastructure operation, authorization consumption, deployment, merge or
force-push was exercised. PDF acceptance follows the explicit-limitation branch;
real execution and before/after outcome evaluation remain unimplemented here.
