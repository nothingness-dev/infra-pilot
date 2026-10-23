# Durable Approval and transactional Audit

This backend implementation supplies `SQLiteApprovalStore` for the **existing**
Triage `ApprovalGate` protocol. The gate still owns policy, identity/permission
checks, independent canonicalization, separation of requester/approver, expiry,
revocation and consumption. No parallel approval engine or execution path exists.
The default store/identity/policy remain unconfigured and fail closed; existing
in-memory composition and default CLI output keep their prior behavior.

## Existing workflow integration

The backend-owned `approval_store_factory` option on `MockWorkflow` and
`run_mock_workflow` creates a store only when the existing operator-selected
Approval example is reached. `OperatorApprovalExample` supplies independently
derived scope and current-inspection associations to that factory and verifies
the returned concrete store against them. It uses the original gate directly.

Only an original, validated `CompletedInspection` with a Mock binding may select
this workflow's associations. Scope hashes the exact configured `ServiceBinding`;
the association hashes scope, existing request fingerprint, diagnosis/companion
bindings and a fresh backend-only UUID retention nonce. Neither the nonce nor
those constituent fingerprints are stored separately. A new example, even with
identical synthetic payloads, gets a different association. Hash equality alone
does not authenticate an original object or restore a session.

After restart, old requests/decisions/audits remain durable historical records.
The Mock workflow cannot reconstruct its original current evidence, review or
opaque sessions from SQLite. A new workflow collects/reviews anew and requests a
new approval. No resume-from-row method or JSON trust-restoration path was added.

Lower-level trusted backend code can reopen a store with independently established
scope/association references. Every gate call still needs a newly trusted
authentication context and current permissions. Production composition must also
re-establish its actual evidence/request/account associations; a database digest
must never be used as proof that those preconditions hold. There is no production
identity implementation or real-service Approval wiring in this delivery.

## Run the existing offline command

Use the existing root environment. No new dependencies or credentials are needed:

```powershell
New-Item -ItemType Directory -Path .tmp/approval-demo -Force | Out-Null
.\.venv\Scripts\python.exe -B -m integration.workflow_demo --mock --scenario approved_not_executed --approval-database .tmp/approval-demo/approval.sqlite
$LASTEXITCODE  # 4: recorded Mock approval; execution remains blocked
```

The parent directory must exist. The path is an explicitly selected local file,
never a credential argument. Omitting `--approval-database` retains the existing
volatile store and output. Without `--mock`, parsing fails before creating files.
Scenarios that do not reach Approval create no database and report
`storage_recorded=false`. Invalid scenarios/dependency failures also create none.

Persistent mode prints a data-free summary, for example this **synthetic offline**
output, not a live authorization or infrastructure result:

```json
{"contract_version":"infrapilot-request-approval/1-mock","mode":"mock","state":"approved_not_executed","error_code":null,"storage":"local_sqlite","storage_recorded":true,"exit_code":4,"approval_state":"approved","audit_count":2,"authorization_consumed":false,"execution_authorized":false,"execution_performed":false}
```

Output contains no database path, subject/service/request IDs, parameters, raw
logs, free-form reports or full workflow payload. `audit_count` covers the current
association, not all historical records in the file. A denied request can persist
an audit without creating an Approval request; `approval_state` is then null.

Run the same command again in a separate process to exercise restart. It records
a **new** synthetic inspection and decision; it does not reuse the old approval.
Both sets of records remain stored. The regression tests verify two processes,
two durable Approval requests and four audit events, with execution disabled.

Existing exits remain: 0 for a completed informational workflow, 4 for the blocked
Approval journey, 3 for invalid arguments/opt-in/scenario, 2 for runtime/storage/
dependency failure, 130 for interruption. `approved` is never an execution claim.

Trusted Python injection:

```python
from integration.approval_store import SQLiteApprovalStore
from integration.workflow import run_mock_workflow

def factory(*, scope_ref, association_ref):
    return SQLiteApprovalStore(
        ".tmp/approval-demo/approval.sqlite",
        scope_ref=scope_ref, association_ref=association_ref,
    )

result = run_mock_workflow(
    mock=True, scenario="approved_not_executed", approval_store_factory=factory,
)
# The runner closes its owned connection before returning.
# Never dump internal records for production/user-facing output.
```

For reusable sessions, use `with MockWorkflow(..., approval_store_factory=factory)`
or call `close()` explicitly. Changing the accepted brief closes the previous
store and invalidates current review/Approval objects. A factory is trusted Python
configuration, never a value selected from an HTTP body. Existing
`ProtectedMockRequests`, default HTTP approval restrictions and real/Mock identity
boundaries are unchanged.

## Store interface and schema

`SQLiteApprovalStore(path, *, scope_ref, association_ref, create=True, timeout=5.0)`
requires two existing-format SHA-256 references selected by trusted composition.
They are read-only properties. `create=False` requires an existing file; timeout
must be finite, positive and at most 30 seconds. Symlink leaf paths and missing
parents are rejected. Connections support explicit context management/close.

Application ID **0x49504141**, schema version **1**, separate from request,
ownership and inspection-history databases. New empty files are initialized
transactionally. Existing files must match the exact schema, scope metadata and
SQLite integrity check. Foreign versions, schemas, extra objects and other
application IDs are rejected without migration or adoption. There is no automatic
upgrade or database discovery.

| Table | Persisted information |
| --- | --- |
| `metadata` | Schema identity is held in SQLite pragmas; one configured account/service scope digest |
| `approvals` | Approval UUID, association digest, canonical action and fingerprint, bounded non-secret subject references, UTC creation/expiry, existing state and decision subject references |
| `audits` | Ordered sequence, event UUID, association/request references, UTC time, existing enum kind/reason, optional non-secret actor/service/action/fingerprint references |
| `receipts` | SHA-256 of the retry UUID, association digest, operation, request UUID, actor reference, canonical action fingerprint and requested TTL for creation |

Stable subject references in `ApprovalRequest` use the existing
`AuthenticatedActor` value type for compatibility. Decoding them restores only
historical subject labels, **not an authenticated caller, credentials, permissions
or a privileged principal**. Caller authentication always goes through the newly
installed identity boundary; the historical approver's permission is rechecked
at consumption. Use non-secret opaque identifiers, not session tokens.

Canonical parameters use the existing narrow action schemas; credentials,
arbitrary config maps, raw commands and unknown fields are not accepted. Storage
does not persist proposal labels/text, requests/reports, observations/logs, provider
environment values, auth headers, API keys, session handles, roles or executable
authorization receipts. The original authorization UUID returned on first
consumption is not persisted or reissued.

Payloads are canonical, allowlisted and capped at **8 KiB per row**, including
bounded reads before JSON decoding. Digests detect accidental inconsistencies;
they are not signatures or protection against an attacker who controls the file.
The local file contains necessary non-secret identifiers and permitted action
parameters in plaintext and needs backend-controlled filesystem access.

`get(id)` returns an administrative snapshot, never permission to execute. Expiry
remains lazy: only gate access advances it. `read_events(after_sequence=0,
limit=100)` returns `(sequence, AuditEvent)` pairs, at most 1000 per page. Use the
returned sequence as the next cursor. The compatibility `events` snapshot fails
if over 1000 events exist rather than silently truncating. Reads are scoped to
the independently selected association; mismatched associations fail closed.
There is no interface to update/delete audit events or edit terminal decisions.

## Atomicity, concurrency and failures

`BEGIN IMMEDIATE` holds a SQLite write transaction across the existing gate call,
including trusted identity checks. Per-instance locking refuses nested use and
detaches transaction handles on exit. Separate connections serialize transitions;
stale updates cannot revive consumed, rejected or expired state. Existing allowed
revocation (`approved` → `rejected`) is preserved, rather than redefining policy.

Each state transition requires its matching structured Audit event before commit.
Receipt writes participate in the same transaction and must match an actual
transition. State, Audit and retry association commit or roll back together.
Audit insertion, record write or pre-commit failure cannot leave a successful
transition committed. An unsuccessful rollback discards/closes the uncertain
connection; later calls cannot reuse it. No automatic transaction retry occurs.

A commit may succeed before the caller loses its result. Such an ambiguous error
returns a denied/storage-unavailable decision. Do not automatically execute or
repeat an infrastructure operation. An explicit retry with the original key and
fresh trusted context can inspect the durable lifecycle safely, but never regain
a consumed authorization. This is **not exactly-once infrastructure execution**.

Gate/store errors use fixed messages without SQL, paths, rejected values or raw
exception text. When no valid clock timestamp exists, the gate denies with
`clock_unavailable` and cannot promise an audit. Storage/audit outages return
`storage_or_audit_unavailable`; external incident reporting remains separate.

## Optional retry contract

The existing gate's `request_approval`, `approve`, `reject` and sensitive
`authorize` methods accept optional keyword-only `idempotency_key`. It must be a
canonical UUID4 chosen as a non-secret operation nonce. Omitting it preserves
previous behavior, including audited denial of repeated non-idempotent calls.
Ports used without keys need only the previous `get/put/record` transaction
methods; keyed calls additionally require `receipt/remember`.

Keys bind operation, actor, canonical action/fingerprint, request association and
creation TTL. A key cannot switch actors, operations, requests, parameters, policy
versions or associations. UUID values are hashed before persistence. Valid retries
recheck current authentication, permissions, policy and time before inspecting
their receipt. They append no duplicate transitions/Audits. A new lazy expiration
is a real new transition and receives its own audit.

Creation retries return the existing request's **current** state and never extend
its expiry. Approve/reject retries cannot revive a later terminal state. A
consumption retry returns `allowed=false`, `approval_consumed`, no authorization
UUID and the existing record; it **never returns an executable grant again**.
For a valid replay, `audit_recorded=true` refers to the original committed
transition's audit, not an additional audit of the retry attempt.
Changed/revoked identity or permissions deny even a previously valid retry.
Read-only/low-risk authorization keeps its original audited behavior and does not
accept a retry key because no Approval request is consumed.

The in-memory store supports the additive receipt methods too. Existing shared
schemas, HTTP inputs and authorization response types are unchanged. No retry
key or role field was added to a public endpoint.

## Remaining limits

This is local SQLite durability on a backend-controlled filesystem, not a
tamper-proof audit ledger, distributed authorization service or production IdP.
Trusted UTC time is still required. Nondecreasing per-request audit timestamps
reject observed clock regression, but distributed skew, freshness and replay
policy are not solved. Identity/ACL checks run under a coarse write lock and must
be bounded; high-contention scaling and network-filesystem locking are not claimed.

Protected audit retention/backup, storage quotas, corruption recovery, real
identity/account/service onboarding, independently re-established live evidence,
reviewed action support and an executor remain separate work. No automated purge
or revocation of historical audit records is provided. No Liara call, live
authorization consumption, infrastructure operation or deployment occurred.
Domain-consumption tests use synthetic trusted fixtures only.

See [executed verification and file inventory](APPROVAL_VERIFICATION.md).
