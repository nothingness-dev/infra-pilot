# Inspection history verification

Date: **2026-10-23**, Windows / Python **3.13.5**, existing root environment.

## Baseline and scope

`git fetch origin` verified merged main at
`b073f94` (merge of read-only inspection PR #19). The prior feature head's tree
matched that main before changes. New branch:
`feat/backend-inspection-history`. The starting worktree was clean; unrelated
Desktop diagnostic/service files remain outside this change.

This milestone is persistent **summary history**, not a resumable request store,
raw evidence archive, durable approval backend, audit attestation or production
identity integration. Existing shared schemas and trust boundaries are unchanged.

## Executed checks

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
python -B -m unittest discover -s provider/tests -t . -v
.\.venv\Scripts\python.exe -B -m unittest integration.tests.test_history -q
```

- Full configured suite: **792 tests passed**, **770 subtests passed**, no skips.
- Provider standalone: **121 tests passed**.
- New history module under unittest: **27 tests passed**.
- One existing Starlette/HTTPX deprecation warning remains. No dependency was
  upgraded to silence it, and no other OS/Python version or CI run is claimed.

The 27 new tests verify actual Mock/HTTP-mocked read-only producer objects,
normalization, Diagnosis and Setup association before projection. They cover:

- Close/reopen and a separate-process record/list round trip; duplicate retries
  retain the original record and storage time.
- All seven existing Mock collection/log states, original partial 403/429 errors,
  retryability, null telemetry and unknown health.
- Real-source HTTP-mocked inspection without relabeling; preservation of valid
  collected evidence after diagnosis failure.
- Modified request/report/binding rejection, exact full-brief filtering, and
  service/project/scope/real-mock partition isolation.
- Refusal of JSON/historical records as trusted inspections; historical-only
  status and false provenance/freshness/authorization/execution/remediation flags.
- Bounded newest-first pagination, invalid lookup inputs, SQL-injection-shaped
  identifiers, detached return values and closed-store behavior.
- Corrupt/oversized/nonfinite payload rejection without silently dropping rows,
  unsupported/newer/foreign databases without overwriting their data.
- Write rollback and retry, bounded SQLite lock failure and recovery, concurrent
  writers through separate connections, and duplicate-write serialization.
- Raw-byte scans of Mock and HTTP-mocked real databases for token, request goal,
  log text, project/scope/service/raw request identifiers and secret canaries.
- Safe exceptions/repr/logging/stdout/stderr, invalid CLI arguments, dependency
  failure, interruption, output-pipe failure, and dependency-free opt-in/help.
- Listing calls no collector/engine; composition tests guard sockets, subprocesses,
  live opener construction and Approval gate mutations/consumption. The separate
  CLI process tests run only the explicit offline Mock profile.

The development record/list command and the generated example were also run
against local SQLite files. `integration/examples/history_partial_failure.json`
is explicitly labeled `offline_mock_history_not_live_evidence` and contains no
database file or live account evidence. SQLite artifacts are under ignored `.tmp`
or test-managed temporary directories and are not staged.

## Live verification boundary

No new authenticated Liara request or application probe was made for this task.
The user previously reported successful API project-list access but zero visible
projects on both documented hosts. The target service was therefore not resolved
by those reported diagnostics; authenticated service observability remains
unverified. This independent offline feature does not resolve or bypass that
account/access issue, claim a healthy service or enable mutations.

## Changed files and limits

- `integration/history.py`: versioned allowlisted payload, actual retained-object
  projection, SQLite schema/transactions/idempotency/scoped reads.
- `integration/history_errors.py`: fixed dependency-free diagnostics.
- `integration/history_demo.py`: explicit offline record/list CLI.
- `integration/tests/test_history.py`: 27 behavior/privacy/storage/CLI tests.
- `integration/HISTORY.md`, this record, and the generated example: usage,
  architecture, privacy, consistency guarantees and honest limitations.
- Root `README.md` and `integration/README.md`: entry links and current test count.

No Provider/Setup/Triage source, shared schema, package manifest, constraints,
existing command or approval/execution behavior changed. A local SQLite file
requires operator-controlled filesystem permissions and is not encrypted. Hashes
are correlation/consistency aids, not authentication, anonymity, freshness or
tamper-proof evidence. Loaded records never reconstruct original producer
references, resume a brief or revive an approval. Full request/evidence/report
retention, production identities/ACLs and durable approval/audit storage remain
separate work. No merge, force-push, deployment or infrastructure mutation occurs.
