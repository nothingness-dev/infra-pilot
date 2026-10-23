# Request access verification

Date: **2026-10-23**, Windows / Python **3.13.5**, existing root environment.

## Verified baseline and change scope

Fetched main at `b99f36f498b3a09a94eeb69863e238f932c7ea37`. GitHub reported
PR #21 merged at that exact commit. The starting worktree was clean on
`feat/backend-request-persistence`; created `feat/backend-access-control` from
integrated main. The baseline was rerun: **847 tests and 770 subtests passed**.

All changes stay in `integration/`:

- `access_identity.py`: trusted resolver protocol, request permissions, existing
  Triage `AuthenticatedActor`, and explicit volatile Mock contexts/grants/clock.
- `access_store.py`: dedicated ownership schema v1 and request-storage association,
  idempotent registration, trusted CAS transfer and connection/error handling.
- `access.py`: authorization/ownership-enforcing facade around actual persistent
  requests, independently configured service binding and access-bound caches.
- `access_demo.py`: explicit offline scenarios, safe JSON and separate-process
  persistent-directory demonstration.
- `request_store.py`: optional trusted transaction checkpoints and a path-digest
  companion-storage reference. Existing SQL schema/application ID unchanged.
- `requests.py`: optional trusted checkpoints, including between actual collection
  and diagnosis; original pipeline, idempotency and retained-association logic reused.
- `request_errors.py`: fixed `ACCESS_DENIED` code; no raw exception diagnostics.
- `tests/test_access.py`, `tests/test_access_demo.py`: 48 new offline tests.
- `ACCESS.md`, this record, and links in `README.md`/`REQUESTS.md`.

No files outside `integration/` changed. No Provider, Setup, Triage, root config,
dependency, existing test or shared schema changed. New request-specific permissions
are necessary because existing Approval permissions apply to canonical action
approval/consumption, not request access. No parallel Approval policy/gate exists.
Existing demo commands retain their prior behavior. Production routes and
contextual diagnosis remain fail-closed.

## Executed checks

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
python -B -m unittest discover -s provider/tests -t . -v
.\.venv\Scripts\python.exe -B -m unittest integration.tests.test_access integration.tests.test_access_demo -q
git diff --check
```

- Full configured repository suite: **895 tests passed, 770 subtests passed**.
- Standalone Provider: **121 tests passed**.
- Focused new unittest modules: **48 tests passed**.
- No skips. One existing Starlette/HTTPX deprecation warning remains. No additional
  platform/Python version, CI result or dependency upgrade is claimed.

Actual-component spies verify Setup intake/completion and one real Mock Provider
collection/normalization and Triage diagnosis; the original prepared object and
Setup companion/report feed existing history persistence. Reads and valid receipt
replay do not collect or diagnose again. Partial logs 403/metrics 429, null telemetry,
unknown health and false execution flags survive the facade unchanged.

The new tests cover:

- Unconfigured resolver; missing/forged/foreign contexts; body roles/subject claims;
  malformed trusted resolver outputs; arbitrary resolver exceptions.
- Exact expiration, revoked handles/grants, permission changes, generation changes,
  missing service grants, invalid/backward clocks and refusal to revive a rejected
  context after clock recovery.
- All request permissions; inspection's additional history permission; cross-owner
  reads, events, completion, inspection, recovery, current evidence and history.
- Service/project/provider-scope/Mock-source isolation; expected binding selected
  independently from stored metadata; wrong request-database companion rejection.
- Owner/binding-scoped keys, key/content conflicts, revoked cached receipts, changed
  grant/ownership generations and non-destructive denial of another owner's guesses.
- Revocation during actual collection (before diagnosis), actual diagnosis, request
  write-before-commit, ownership registration and after summary save-before-link.
  Access-store failure after collection stays pending and is not relabeled as a
  Provider collection failure.
- Ownership transfer during collection/history reads; old creation replay cannot
  overwrite the new owner; transfer-away-and-back invalidates old retained evidence.
- Registration failure leaves an inaccessible request; same-key retry registers the
  original ID without another intake; lock timeout/rollback and duplicate concurrent
  creation/registration; exactly one stale-revision transfer writer succeeds.
- Close/reopen, interrupted-attempt recovery and missing retained references after
  restart; ownership JSON cannot mint a context or add approval privileges; mismatched
  historical-summary links and oversized records are rejected.
- Foreign request/history databases, future versions, corruption, unexpected schema
  objects, closed handles and invalid timeout settings; Windows cleanup after failure.
- Secret canaries in rejected contexts/briefs, stdout/stderr, JSON, exceptions/repr/logs
  and raw SQLite bytes. No tokens, session handles, raw synthetic log text, Authorization,
  private fixture account/project, environment or client credential configuration persist.
- Reentrant facade calls cannot clear an active outer checkpoint; all CLI scenarios,
  argument/claim rejection, literal opt-in, dependency failures, interruption and
  closed/broken output.

In-process tests guard sockets, live opener construction, subprocess tools and
ApprovalGate mutations/consumption. Child composition tests also disable network
and Approval entry points before running the real CLI. Temporary SQLite connections
are explicitly closed. Standard-library-only `-S` tests verify help/opt-in and safe
dependency failure before any database is created.

## Separate processes and manual walkthrough

Independent Python processes create/complete/inspect a protected request and then
reopen the same three databases. The second process rejects a reconstructed
context, resolves a fresh server-installed fixture context, reads the same request
ID/revision, and reports reinspection required with no retained evidence.

The PowerShell walkthrough in `ACCESS.md` was also executed using independent
native Python invocations and ignored `.tmp/access-walkthrough` files. Proof summary:

```json
{
  "owner_status": "allowed",
  "request_revision": 5,
  "restart_status": "fresh_context_resolved",
  "fresh_context_required": true,
  "reinspection_required": true,
  "retained_after_restart": false,
  "denied_status": "denied",
  "denied_exit": 4,
  "metrics_status": 429,
  "execution_performed": false
}
```

## Trust and remaining limitations

This provides a reusable protected backend boundary demonstrated with explicit
Mock identity, not verified real users. Production still needs a real credential
verifier/identity-provider adapter, verified service/account grants and ownership
onboarding, durable Approval/audit, live Liara access and an executor. No session,
identity, approval, execution or remediation authority is restored from JSON.

Request creation/ownership registration/history linking have no cross-file atomicity.
Unowned requests stay inaccessible; same authorized creation retry is the explicit
registration recovery. Revocation can leave a pending attempt or orphan historical
summary. Fresh access, explicit lifecycle recovery and reinspection apply.

Local metadata and installed resolvers are trusted backend dependencies. Checksums
are not signatures; arbitrary file rewriting or backend code access can bypass
this facade. The tests do not claim tamper-proof ACL storage, constant-time lookups,
encrypted SQLite, multi-host linearizability, or production authentication.

No live credentials were looked up/used, no live Liara call was made, and prior
live service visibility remains unresolved. No UI, privileged HTTP route,
infrastructure mutation, deployment, merge or force-push was performed.
