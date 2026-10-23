# Persistent local Mock requests

Profile: `infrapilot-persistent-request/1`. This backend persists **controlled
Mock `inspect_service` briefs**, their revisions, lifecycle events and mutation
receipts. Separate processes can complete the same accepted brief and run the
actual existing Provider → Diagnosis → Setup pipeline. There is no UI, listener,
credential lookup, application probe, approval operation or infrastructure tool.

This follows the request/evidence/diagnosis portion of the responsibilities PDF
(pages 3 and 8). It does not claim the live deployment, action or remediation
parts of that acceptance scenario. The existing six demo commands and shared
contracts remain unchanged. This internal version is not a new production API.

## Supported interface and privacy decision

`integration.requests.PersistentMockRequests(store, mock=True)` exposes `create`,
`supply_information`, `get`, `events`, `inspect`, `recover`, `historical_summary`
and process-local `current_inspection`. `SQLiteRequestStore` owns one SQLite
connection; the caller closes it, preferably with a context manager. Use one
store/workflow instance per thread. Mutations require a non-secret idempotency
key; existing-request mutations require an expected revision.

Request text persistence is deliberately narrower than the ordinary Setup
interface. The entire accepted vocabulary is:

| Detail | Accepted exact value |
| --- | --- |
| `service_target` | `MOCK-service` |
| `goal` | `Review this synthetic service collection` |
| alternative `goal` | `Review this synthetic service again` |

Either detail may be omitted while collecting information. This version cannot
remove an accepted detail, change targets, store unrestricted prose or accept
other operations. Unknown keys, nested values, credential/configuration fields,
extra whitespace, URLs and arbitrary strings are rejected with fixed errors.
Accepted strings are preserved exactly. No secret detector or silent sanitization
is involved. This is **not unrestricted production intake**.

The backend generates request IDs as UUID hex strings. Keys and lookup IDs must
be 32 lowercase hex characters; generate keys with a UUID utility. They must be
public identifiers, never secrets. Format validation cannot detect an arbitrary
credential disguised as a valid identifier. IDs, keys, digests, source labels and
rows confer no identity, ACL, freshness, approval or execution authority.

The dedicated request database contains accepted fixture text, IDs, revisions,
fingerprints, selected Mock scenarios, stage/error codes, timestamps and summary
references. It stores no client configuration, raw responses, environment,
unreviewed logs, diagnosis prose, evidence objects or credentials. Existing
summary history retains its narrower allowlist; it still contains no brief text.
Fixed diagnostics never echo rejected values, SQL, paths or arbitrary exceptions.

Store both files in an operator-controlled directory with appropriate filesystem
permissions, outside Git (the example uses ignored `.tmp/`). SQLite is **not
encrypted** and this module does not install ACLs, an encrypted vault, retention,
backup or secure-erasure services. Checksums detect ordinary inconsistency, not
malicious rewriting by someone who controls the file and can recompute hashes.

## Revisions and lifecycle

Every accepted transition advances `revision`. `brief_revision` advances only
when accepted detail content changes. Creation starts both at 1. Each event
contains the exact accepted state/brief for its revision, plus a local UTC storage
time. That time is not an observation timestamp or evidence-freshness assertion.

Actual `setup.application.submit_request` and `supply_information` accept the
brief; existing Setup validation determines missing information. The wrapper's
`ready_for_inspection` means the brief is complete, **not** that Setup's candidate
plan has all its dependencies or that any execution is permitted.

Complete briefs use the full existing `setup.integration.request_fingerprint`,
including identity, operation and exact detail strings. Incomplete briefs have
`fingerprint: null`: existing Setup intentionally cannot fingerprint them. Their
full canonical revision/event checksums are not substituted for a Setup fingerprint.

| State | Meaning |
| --- | --- |
| `needs_information` | Accepted incomplete brief; no collection |
| `ready_for_inspection` | Complete brief; no current inspection association |
| `inspecting` | Durable attempt committed before invoking actual Mock pipeline |
| `awaiting_history` | Original objects exist in the initiating instance; summary/link handoff pending |
| `inspection_recorded` | Summary was saved/read back and a revision-bound link committed; observations may still be partial |
| `inspection_failed` | Pipeline raised an error; fixed `COLLECTION_FAILED`, no invented summary |

An inspection advances the transition revision three times: started, history
pending, recorded. It leaves `brief_revision` unchanged. A changed brief clears
current history/inspection associations and process-local dependencies. Earlier
events and their history links remain readable with `historical_summary(revision=...)`.
A no-op completion records a transition without changing the brief or evidence
association; no-op completion during a pending attempt is refused until recovery.

All request/event/receipt writes for one transition are in one `BEGIN IMMEDIATE`
transaction. A stale expected revision returns `REVISION_CONFLICT` and changes
nothing. A key retry with the same command/content/expected revision returns its
original receipt; changing any of those inputs yields `IDEMPOTENCY_CONFLICT`.
Keys are unique across operations and requests within one database. The response's
`is_current_revision` distinguishes an old receipt from the current request.
Replaying a receipt never reruns collection/diagnosis or invalidates newer evidence.
Failed validation/conflicts/rolled-back writes do not reserve a key.

## Restart and cross-database handoff

Use separate files for request storage and [inspection-summary history](HISTORY.md).
There is **no distributed transaction** between them:

1. Commit `inspecting` and its pending receipt in the request database.
2. Invoke existing `MockSession(request=...)` once. It reuses the real Mock
   collector/normalizers, original `PreparedCollection`, existing Triage engine
   and Setup companion/report association; no copied parser or diagnosis exists.
3. Retain those original objects in this backend instance; commit `awaiting_history`.
4. Use existing `SQLiteInspectionHistory.save`, read back the record with the
   independently selected expected binding, and verify its exact request fingerprint,
   request-ID digest and Mock source.
5. CAS the request revision/attempt to `inspection_recorded` and store the history ID.

No database lock is held across collection, diagnosis or a history write. A history
failure returns `HISTORY_FAILED`, leaves the stage pending and never claims a link.
The initiating instance can retry the **same key and original expected revision**;
it reuses retained objects and content-idempotent history save, without another
collection/diagnosis. If history committed but the link failed, retry deduplicates
the same summary. A competing brief change prevents the old attempt attaching to
the new revision; an already-written summary may remain an unlinked historical record.

After process exit, or when using a different workflow instance, no retained
objects are restored. A previously recorded result has `reinspection_required:
true`. Reading a brief, events or summary neither collects nor diagnoses.
`current_inspection` requires the exact current transition revision and original
process-retained objects; it rechecks the full brief, brief revision, Mock source,
independently configured full `ServiceBinding`, original prepared envelope and
actual Setup companion/report association. Revalidate again before any later use;
this is not a lock held across future operations or an execution capability.

If a process dies during `inspecting`/`awaiting_history`, the next process reports
`recovery_required: true`. An explicit CAS/idempotent `recover` transition abandons
the pending attempt, records `INTERRUPTED`, and returns to `ready_for_inspection`.
It does not resurrect objects, link an orphan by guessing, or collect automatically.
Start a fresh inspection with a new key and the recovered revision. A changed
brief also supersedes its old pending attempt; replay of that superseded operation
returns a revision conflict. A terminal pipeline failure can be retried as a new
inspection using its current revision and a new key.

Persisted JSON never constructs a `PreparedCollection`, `CollectionCompanion`,
`CompletedInspection`, `EvidenceRef`, identity or approval. The existing Mock-only
outcome evaluator rejects these historical dictionaries as retained observations.
All consumed/authorized/executed/remediation flags on this new path remain false.
The production contextual endpoint and original Approval behavior stay fail-closed.

## Offline PowerShell walkthrough: each command is a separate process

Use the existing root environment installed via `requirements-mock.txt`; this
milestone adds no dependencies. From the repository root:

```powershell
$py = '.\.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path .tmp -Force | Out-Null
$db = '.tmp/request-workflows.sqlite'
$history = '.tmp/request-summaries.sqlite'

$created = & $py -B -m integration.request_demo --mock --database $db create --target --key ([guid]::NewGuid().ToString('N')) | ConvertFrom-Json
$id = $created.request.request_id
$created.request.state  # needs_information
$created.missing_information  # details.goal

$completed = & $py -B -m integration.request_demo --mock --database $db complete --request-id $id --expected-revision 1 --goal review --key ([guid]::NewGuid().ToString('N')) | ConvertFrom-Json
$completed.request.revision  # 2

$inspected = & $py -B -m integration.request_demo --mock --database $db inspect --request-id $id --expected-revision 2 --key ([guid]::NewGuid().ToString('N')) --history-database $history --scenario partial_failure | ConvertFrom-Json
$inspected.request.revision  # 5
$inspected.historical_summary.summary.capabilities

& $py -B -m integration.request_demo --mock --database $db show --request-id $id
& $py -B -m integration.request_demo --mock --database $db events --request-id $id --limit 2
& $py -B -m integration.request_demo --mock --database $db events --request-id $id --limit 2 --before-revision 4
& $py -B -m integration.request_demo --mock --database $db history --request-id $id --history-database $history --revision 5
$LASTEXITCODE
```

`show` after the inspection process exits reports historical status and requires
reinspection for retained references. The `history` command shows the existing
summary only. Example **output excerpt**, entirely synthetic (not live evidence):

```json
{
  "status": "ok",
  "exit_code": 0,
  "data_source": "mock",
  "historical_status": true,
  "retained_evidence_available": false,
  "reinspection_required": true,
  "recovery_required": false,
  "authorization_consumed": false,
  "execution_authorized": false,
  "execution_performed": false,
  "remediation_verified": false
}
```

The actual summary distinguishes logs `permission_denied`/403 and metrics
`failed` with error code `RATE_LIMITED`/429 in `partial_failure`, preserves retryability and limitations,
and keeps CPU/RAM/application latency/source timestamps null and health unknown.
It exports no log text. No missing value becomes zero or a healthy observation.

For a genuinely interrupted attempt, read its **current** revision first, then:

```powershell
& $py -B -m integration.request_demo --mock --database $db recover --request-id $id --expected-revision $pendingRevision --key ([guid]::NewGuid().ToString('N'))
# Use the returned revision and a new key for a fresh inspect command.
```

Do not run recovery against an ordinary completed request. `--goal` accepts only
`review`/`review_again`; `--target` includes the fixed fixture alias. Inspection
scenarios reuse Provider's seven existing choices: `exported`, `empty`,
`unavailable`, `not_collected`, `withheld`, `partial_logs`, `partial_failure`.
No token, URL, free-form goal or identity option exists. Static `--help` and invalid
opt-in work without installed composition dependencies; valid commands fail safely
before creating a database if those dependencies are unavailable.

| Exit | Meaning |
| --- | --- |
| 0 | Command/receipt/read succeeded; partial observations remain visible in summary, not application health |
| 2 | Storage, dependency, history, evidence or unexpected runtime failure; broken output may have no JSON |
| 3 | Invalid arguments/brief/lookup, absent Mock opt-in or incomplete brief for inspection |
| 4 | Revision/idempotency conflict or explicit recovery/reinspection required |
| 130 | Interrupted; output interruption may prevent a JSON report |

Ordinary errors are fixed JSON, no traceback or raw exception. Keep command keys
to safely retry a mutation. Do not generate a new key as a substitute for resolving
an unknown pending attempt. There is no automatic retry loop or background worker.

## Schema and operational limits

Request store application ID `0x49505231`, SQLite `user_version=1`:

- `requests`: current request ID/revision, canonical state JSON and checksum.
- `events`: immutable `(request_id, revision)` primary key, event kind/time,
  complete canonical state JSON and checksum.
- `receipts`: key, command digest, pending flag, result state JSON and checksum.

History's application ID `0x49504831` and schema v1 are unchanged. Supplying a
history database as a request database is rejected. Schema identifiers, exact
table definitions, unexpected triggers/views and SQLite quick integrity checks
are verified on open. Foreign/newer/unrelated/corrupt files are not migrated or
overwritten. There is no schema migration utility. `create=False` refuses missing
files; even reads use a read/write connection for schema verification.

State JSON is capped at 4096 ASCII bytes; reads validate shape, controlled values,
canonical form, checksums, full-brief fingerprint and latest event consistency.
Events are newest-first by revision with default 20, maximum 100, and an exclusive
`before_revision` cursor. SQL uses parameters for values; fixed schema identifiers
are backend constants. The composite event primary key supports pagination.
SQLite locks wait at most the configured timeout (default 5 seconds, finite
`0 < timeout <= 30`); failures roll back the complete transition. Parent directories
are not created implicitly. Constructors close connections on failure/interruption.

This is single-host local SQLite with no shared multi-host database, authenticated
tenant isolation, signed/tamper-evident audit, durable approvals or job scheduler.
Schema quick-check work and disk use grow with database size; records are not
automatically pruned. Back up both files consistently as historical data; copying
them never restores trust. Production identity/target ACLs, approval/audit storage,
live account/service access verification and an executor remain separate blockers.
No live credential or service access was attempted for this milestone.

See [executed verification](REQUESTS_VERIFICATION.md).
