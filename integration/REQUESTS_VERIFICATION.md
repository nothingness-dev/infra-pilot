# Persistent request verification

Date: **2026-10-23**, Windows, Python **3.13.5**, existing root environment.

## Verified baseline and scope

Fetched main at `4ce3018a02967638e601fbcd7ec3e7df86e7133c`; GitHub reported
PR #20 **MERGED** at that exact commit. The starting worktree was clean on
`feat/backend-inspection-history`. Created a new branch from integrated main:
`feat/backend-request-persistence`. The only other open PR at inspection was #15
(Incident UI proposal); it and its branches were untouched.

The baseline suite was rerun before implementation: **792 tests and 770 subtests
passed**. No assumption that earlier feature branches were merged was needed.
The project PDF's request/evidence/diagnosis flow is supported here through the
explicit offline Mock continuation; UI, live deployment and operations are excluded.

All changes are in `integration/`:

- `request_errors.py`: dependency-free fixed diagnostics/profile.
- `request_policy.py`: finite persisted Mock vocabulary, actual Setup intake,
  completion and full-brief fingerprint; existing Provider scenario choices.
- `request_store.py`: dedicated schema v1, atomic revisions/events/receipts,
  strict reads, CAS/idempotency, rollback, locking and ownership.
- `requests.py`: original-object Mock continuation and recoverable summary handoff.
- `request_demo.py`: explicit offline CLI and safe JSON/exits.
- `tests/test_requests.py`, `tests/test_request_demo.py`: 55 new offline tests.
- `REQUESTS.md`, this record, `README.md`, `HISTORY.md`: usage and scope links.

No Provider, Setup, Triage, shared schema, existing test, root configuration,
dependency, endpoint, approval policy or UI file was changed. No new runtime
dependency or duplicate transport/parser/collector/diagnosis/sanitizer was added.
The existing inspection-history application ID/schema remains unchanged.

## Executed checks

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
python -B -m unittest discover -s provider/tests -t . -v
.\.venv\Scripts\python.exe -B -m unittest integration.tests.test_requests integration.tests.test_request_demo -q
git diff --check
```

- Full configured suite: **847 tests passed, 770 subtests passed**, no skips.
- Provider standalone unittest suite: **121 tests passed**.
- New focused unittest modules: **55 tests passed**.
- One pre-existing Starlette/HTTPX deprecation warning remains; dependencies were
  not changed to suppress it. No other platform/Python version/CI run is claimed.

The tests exercise actual Setup intake/completion/fingerprints, actual Mock
collection, normalization, original prepared objects, Triage engine and Setup
companion/report association, then existing SQLite summary persistence. Spies
verify one collection/diagnosis for the transition and none on history reads or
successful idempotent replay. All seven existing Provider scenarios are covered.

Coverage includes invalid completion with prior revision intact; exact full-brief,
source, service/project/scope/request/evidence mismatch; changed-brief invalidation;
no-op updates; current revision checks; restart reinspection; old receipt replay;
two concurrent writers accepting exactly one stale-revision update; concurrent
same-key creation; bounded busy timeout/retry; atomic event/receipt rollback;
interruption before/after collection; generated-ID collision; corrupt/missing
pending receipts; foreign/newer/history/corrupt/modified-schema databases;
oversized/noncanonical records; pagination and invalid inputs; cross-request and
binding isolation; forged completed/approved JSON; and outcome-reference rejection.

Cross-database tests inject a history failure, missing/wrong readback, failure
before the pending-history commit, and failure after the history commit but before
the link. Same-instance retries reuse original objects and deduplicate the same
summary. New instances cannot reconstruct or auto-link abandoned evidence.

Secret canaries cover rejected goal/target/nested config/header fields, arbitrary
exceptions, repr/logging/stdout/stderr, mutated Pydantic warning paths, JSON and
raw database bytes. Raw synthetic log text, private fixture project/scope and
Authorization fields are absent from the stored artifacts under the declared
finite vocabulary policy. This does not claim universal secret recognition in
arbitrary free text or in a credential disguised as a valid public UUID key.

In-process tests guard sockets, live opener construction, subprocess tools and
Approval mutation/consumption. Composition child processes disable socket/opener
and Approval entry points before executing the CLI. Temporary SQLite connections
are explicitly closed for Windows cleanup. Dependency-free `-S` tests cover help,
invalid opt-in and safe dependency failure before database creation. CLI checks
also cover fixed error JSON, conflicts, interrupts and closed/broken output.

## Demonstrated process boundaries

The test suite starts independent Python processes for:

1. Create an incomplete request, then exit.
2. Complete the accepted brief through Setup, then exit.
3. Run the actual partial-failure Mock pipeline and store/link its summary, then exit.
4. Reopen history/events: same request fingerprint/history ID, no retained evidence,
   explicit reinspection requirement and all execution flags false.

A separate test forcibly exits a child with `os._exit(97)` immediately after its
durable `inspecting` transition. The next process reads the pending stage, rejects
automatic resume, explicitly recovers with CAS, then performs a fresh inspection.
This is process death, not a claimed machine-power-loss durability experiment.

The PowerShell walkthrough in `REQUESTS.md` was also executed with separate native
Python invocations and ignored local SQLite files. Observed proof summary:

```json
{
  "created_state": "needs_information",
  "completion_revision": 2,
  "inspection_revision": 5,
  "history_link_matches": true,
  "event_page_count": 2,
  "retained_after_restart": false,
  "reinspection_required": true,
  "logs_status": 403,
  "metrics_status": 429,
  "execution_performed": false
}
```

## Limits retained

This is local, finite-vocabulary Mock request persistence. Historical checksums
are not signatures; filesystem control can forge historical displays, never
original process-retained producer objects or authority. No stored JSON restores
identity, ACLs, approval, authorization, execution, source freshness or verified
health. CPU/RAM and other unverified normalized telemetry remain null.

There is no cross-file atomicity, encryption, migration, backup/retention service,
multi-host job scheduler, durable approval/audit backend or production intake.
Pending attempts after restart require explicit recovery and fresh inspection;
an orphan summary can remain historical. Real Liara credentials were neither
looked up nor used, and no live service/account access was attempted. Prior live
target visibility remains unresolved. No merge, force-push, deployment, UI or
infrastructure change was performed.
