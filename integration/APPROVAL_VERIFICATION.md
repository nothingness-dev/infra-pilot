# Durable Approval/Audit verification

Date: **2026-10-23**, Windows / Python **3.13.5**, existing root `.venv`.

## Baseline and scope

PR [#23](https://github.com/nothingness-dev/infra-pilot/pull/23) was verified merged
at `c999177f7c3cc8519aadd00ee531248d6c46f23d`, equal to fetched `origin/main`.
The starting worktree was clean on `feat/liara-live-readonly-verification`.
Created **`feat/durable-approval-audit`** from that integrated main. Baseline rerun:
**931 tests, 827 subtests passed**. Before push, main advanced through merged PR
[#24](https://github.com/nothingness-dev/infra-pilot/pull/24) to
`5aa34dfd63440dd4e9777cd5c7bcf3a96a1d4799`, adding only two Incident documents.
The unpublished feature branch was rebased cleanly onto that latest main; no
merge or force-push was performed. Comparing pre/post-rebase trees confirmed only
those two documents were added, with runtime and tests byte-for-byte unchanged.
**The final PR base is integrated main at `5aa34df`.** No stacked dependency exists.

This task explicitly authorizes whole-project backend ownership and the named
repository path. The older Triage AGENTS task/owner/canonical-path restrictions
do not prevent the narrowly requested core changes here. Its security/default
denial, shared-schema preservation and no-merge instructions remain respected.

Runtime changes:

- `apps/liara/triage/src/infrapilot_triage/approval_store.py`: additive retry
  receipt and optional transaction extension; atomic memory-store receipt commit.
  The original transaction protocol remains unchanged for existing ports.
- `apps/liara/triage/src/infrapilot_triage/authorization.py`: optional keyed
  operations on the same gate, current-context checks before replay, no reissued
  consumed grant, preserved clock-unavailable handling across store backends.
- `integration/approval_store.py`: strict, independently scoped SQLite store,
  existing canonical-action validation, transactional state/Audit/receipt writes,
  bounded decoding, lifecycle consistency, pagination and safe failure cleanup.
- `integration/mock_approval.py`: existing operator example selects storage from
  original validated evidence plus a backend retention nonce; Mock identity and
  execution restrictions unchanged.
- `integration/workflow.py`: optional trusted factory and deterministic ownership/
  cleanup; changed briefs invalidate the old store and retained Approval example.
- `integration/workflow_demo.py`: optional `--approval-database` on the existing
  entry point, exporting only a summary in persistent mode.

Tests: `integration/tests/test_approval_store.py`,
`integration/tests/test_durable_approval_workflow.py`.
Documentation: `integration/APPROVAL_PERSISTENCE.md`, this record,
`integration/README.md`, `integration/WORKFLOW.md`,
`apps/liara/triage/APPROVAL_POLICY.md`.

All **13 files** stay in integration and the existing Triage Approval module.
Provider, Setup, shared schemas, root settings, dependencies, existing database
schemas and previous tests are unchanged. There is no new policy engine, public
authorization endpoint, principal issuer, UI or executor.

## Executed verification

```powershell
python -B -m unittest discover -s provider/tests -t . -v
.\.venv\Scripts\python.exe -B -m unittest integration.tests.test_approval_store integration.tests.test_durable_approval_workflow -q
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
git diff --check
```

- Full configured suite: **979 tests and 827 subtests passed**, no skips, 88.00
  seconds. One existing Starlette/HTTPX deprecation warning remains.
- Standalone Provider: **136 tests passed**, using the standard library only.
- Focused new modules: **48 tests passed** (35 storage/gate, 13 workflow/process).
- `git diff --check`: passed. No previous test was modified or removed.

The full run preceded the final documentation-only rebase; its runtime/test
content is identical on the final base. The 48 focused tests were rerun after
rebasing. No execution or extra verification is inferred from document changes.

No dependency upgrades or additional OS/Python/CI verification are claimed.

The tests use actual temporary SQLite files and the actual Triage policy/gate.
Socket/API construction and infrastructure subprocesses are forbidden in the
in-process fixtures. Separate child-process tests run only the existing offline
workflow command and stdlib-only dependency-failure bootstrap.

Demonstrated behavior:

- Pending/approved/rejected/expired records and audits survive close/reopen.
  Decoded actor subjects do not authenticate: old opaque handles, claimed actors,
  JSON roles and missing identity fail. Newly installed fixture sessions are
  required; current actor/service/action/approver permissions remain checked.
- Canonical action, parameters, requester, policy version, TTL and independently
  selected associations cannot be substituted. Identical fixture contents in a
  fresh process cannot restore an old current-workflow association; its fresh
  backend retention nonce prevents that accidental reuse.
- Valid keyed retries produce no duplicate transition/audit. Keys cannot switch
  operations, requests, actors or associations. Expiration is never extended;
  denied/revoked permissions are not bypassed. A consumed receipt after restart
  returns false/no authorization UUID, not another grant.
- Independent-connection races use barriers, not sleeps. Exactly one consumption
  or competing approval wins. Revocation versus consumption produces one terminal
  winner while preserving the original policy's legitimate approved revocation.
- Real SQLite triggers inject state-write and audit failures; state/receipt/Audit
  changes roll back. An unaudited direct transition cannot commit. Failure before
  commit rolls back; simulated commit-success/result-loss denies and a keyed retry
  never reissues authorization. Failed rollback discards the uncertain connection.
- Foreign schemas/application IDs, changed scope, corrupted canonical action,
  oversized persisted data, invalid clocks/configuration, nested transactions,
  closed stores and retained transaction handles fail safely. Audit pagination is
  bounded and malformed payloads are rejected.
- Synthetic credential/proposal/log canaries do not appear in stdout, stderr,
  log capture, errors, repr or approved persisted fields. Tokens, session handles,
  full provider observations/reports and unrestricted text are not stored. Allowed
  non-secret subject/service/action references remain necessary internal records.
- Spies observe one actual Mock collection, Diagnosis and Approval request through
  the existing workflow. Persistent and default in-memory modes use the same gate.
  The workflow cannot call `authorize`; no synthetic fixture grant is consumed by
  that workflow or CLI. Direct gate tests consume only synthetic domain records.
- Two separate workflow processes reopen the same SQLite file: two new requests
  and four audits persist, each with fresh current associations and Mock contexts.
  CLI summaries contain no record IDs, subjects, parameters, paths or full payloads.
  Missing dependencies/opt-in and invalid scenarios create no database.

## Live and production limits

**No live API, real authentication, live authorization consumption, infrastructure
operation, deployment or repair occurred.** No Liara token, environment secret or
private credential file was needed or searched. Previously pasted tokens were not
used. The read-only Liara blocker and its existing verification record remain
unchanged; this milestone makes no new provider capability/access claim.

SQLite is backend-controlled local storage, not a tamper-proof audit system.
Digests do not authenticate file contents. Historical records cannot restore a
current evidence object, trusted identity or executable receipt. Production IdP/
service ACL/account onboarding, protected audit retention/backup and quotas,
trusted distributed time/freshness/replay policy, live evidence association,
reviewed operations and an executor remain separate work. Coarse write locking
requires bounded identity checks and is not a distributed scaling claim.

See [interfaces, schema, safe run commands and recovery semantics](APPROVAL_PERSISTENCE.md).
