# Protected local Mock request access

Profile: `infrapilot-request-access/1-mock`. `ProtectedMockRequests` adds a trusted
identity-resolution port, operation/service permissions and persistent request
ownership around the existing finite [request lifecycle](REQUESTS.md).

**This is an offline Mock composition, not production authentication.** No login,
JWT verifier, identity provider, public HTTP route, executor or infrastructure
operation is installed. A facade with no identity resolver denies all access.
Existing production contextual/privileged entry points remain fail-closed.

## Trusted boundary

The composition root installs a `RequestIdentityBoundary` whose `resolve(context)`
must verify a server context and current permissions on every call. It returns
`ResolvedAccess`: the existing Triage `AuthenticatedActor`, a positive grant
generation, a strict set of `RequestPermission` values and full `ServiceBinding`
grants. Its owner reference is a stable **non-secret, 32 lowercase hex** identifier.
An actual identity-provider adapter must map verified subjects to these references.
No production adapter exists in this delivery.

`ResolvedAccess` is a resolver output, not an accepted caller context or signed
credential. Body actor IDs, roles, JSON, digests, source labels, database rows and
`AuthenticatedActor` objects supplied as contexts establish nothing by themselves.
The installed resolver is trusted code: a resolver that blindly accepts claims
would violate this boundary. Structural validation cannot authenticate its inputs.

`MockRequestIdentity(mock=True)` is a trusted fixture issuer for two distinct
principals, `owner` and `other`. Both have service permissions initially; only the
registered owner can access a particular request. It recognizes retained opaque
`AccessContext` handle identity in its own registry. Handles are neither tokens
nor strings, have a safe repr, and are not persisted or exported. A new registry
cannot recognize an old handle or a reconstructed object of the same type.

The injected aware UTC clock controls expiration (default lifetime 300 seconds,
allowed 1..3600). It uses current UTC when not injected, with no fixed fixture
date. Invalid clocks fail closed. A context observed expired, revoked, or moving
backward relative to its last successful check is invalidated; clock recovery
does not resurrect it. Changing fixture permissions/bindings advances a grant
generation and invalidates existing contexts, even if permissions are restored.
The identity issuer is volatile fixture configuration, not durable session storage.

The existing Triage `Permission` enum describes Approval operations and is not
repurposed. No ApprovalGate call or authorization consumption occurs here.

## Protected operations

| Facade operation | Required permission |
| --- | --- |
| `create` | `CREATE` for configured service; registers ownership before returning |
| `get`, `events` | `READ` and exact request ownership |
| `supply_information` | `COMPLETE` and exact request ownership |
| `inspect` | `INSPECT` **and `HISTORY`**, because its response includes the linked summary |
| `historical_summary` | `HISTORY` and exact request ownership |
| `current_inspection` | `INSPECT` and exact request ownership; backend-only original objects |
| `recover` | `RECOVER` and exact request ownership |

A mutation permission permits returning its own receipt/request snapshot. It
does not grant arbitrary request/history reads. Owner access also requires a
current grant for the exact configured service. There is no administrator bypass,
role-string interpretation, delegated user access or public ownership-transfer API.

The full service/project/provider-scope/Mock-source binding is selected from
trusted backend configuration, never from an envelope or SQLite. This executable
profile supports only Provider's existing `MOCK-service` binding and finite brief
vocabulary. Supplying another expected binding is denied rather than widening the
collector. Registration stores a versioned binding reference, not raw account or
project identifiers. Matching aliases with different scopes/sources do not match.

Checks run before lower-level request reads, mutation/idempotency handling and
returning cached results. Unknown, invalid, unowned and other-owner request IDs
return the same fixed `ACCESS_DENIED`; the facade discloses no request contents
or IDs in denied CLI results. This is not a constant-time existence oracle guarantee.
Storage outages retain safe storage errors; invalid ownership metadata denies access.

Access is revalidated inside request transactions before receipt replay and before
commit, after collection before diagnosis, before history save/link, and before
the facade returns. Grant/owner versions and the complete permission/binding set
must still match the initial resolution. A change during a transition denies it;
request/event/receipt writes still in a transaction roll back together.

Cached original inspections are associated with principal, grant generation and
ownership revision. Changed access invalidates them even if ownership or grants
later return. Unauthorized guesses do not discard the actual owner's cache.
Current evidence still requires the existing exact request revision/fingerprint,
original prepared object and actual Setup companion/report checks.

Checks are point-in-time backend checks, not locks held across future caller use
or distributed transactions with an external identity provider. `current_inspection`
is only for trusted Python consumers; recheck through the facade before later use.
Do not export its raw objects as public responses.

## Persistence, registration failure and restart

`SQLiteOwnershipStore` uses a dedicated file with application ID `0x49504131`,
`user_version=1`, and profile `infrapilot-request-ownership/1`:

- `metadata`: a request-storage association digest.
- `owners`: request ID, canonical ownership JSON and checksum. The JSON contains
  version, request ID, owner reference, full binding reference and ownership revision.

The companion is bound to the request database's canonical local path digest.
This prevents accidentally using one ownership database with another request
store. It is not a cryptographic file identity or authentication credential.
Moving/restoring a database to another path needs an explicit operator storage
decision; there is no automatic rebinding/migration utility. Do not delete the
companion and assume old ownership can safely be inferred.

Existing request/history application IDs and schema v1 definitions are unchanged.
No automatic migration, ownership adoption of legacy bare requests or rewrite of
existing request databases occurs. Unregistered old requests are inaccessible
through the new facade. Existing lower-level commands remain available to trusted
local operators and retain their prior behavior.

Creation first checks current service/CREATE permission and calls actual request
creation, then idempotently registers ownership and checks access again before
returning. There is **no distributed transaction** between request and ownership
files. If registration fails, the request may already exist, but its ID is not
returned and no protected read/update/inspection is allowed without ownership.
Retry the same public key, same brief and same authorized principal/binding:
the existing request receipt returns the same ID and registration is retried.
It does not create a duplicate or rerun Setup intake. A conflicting owner is never
overwritten by registration or replay.

Public mutation keys are namespaced by principal and complete binding before
calling the unchanged request idempotency machinery. They are non-secret UUID
hex identifiers, not bearer credentials. Session/grant changes do not manufacture
new request IDs for the same legitimate creation retry; **fresh access checks
always precede replay**. A receipt cannot cross owners or service scopes, authorize
a revoked context, or recreate current evidence. Key/content/command/revision
conflicts retain existing behavior.

Ownership transfer is a separate trusted storage control, `owners.transfer`, used
for fixture/admin testing; it requires an expected ownership revision and advances
it atomically. It is not exposed by the facade or CLI as a user capability.
Transfer intentionally changes who may read the request's historical records;
it never transfers a process-retained identity, evidence capability or approval.

After restart, ownership survives; contexts, grant configuration and original
producer references do not. Trusted startup must install grants/resolver and
resolve a fresh context. Stored JSON cannot mint one. Prior inspections remain
historical and require reinspection for current retained references. Interrupted
attempts retain the existing explicit CAS recovery requirement.

If access is lost during collection/diagnosis, no current protected result is
returned or linked. If history was already saved before revocation or a link
failure, an orphan historical summary may remain. It confers no current access or
trust. Recovery/fresh collection must follow the existing lifecycle; this facade
does not guess a link from persisted digests or revive cached permissions.

Ownership reads are exact indexed lookups; canonical JSON is bounded to 1024
ASCII bytes. Schema definitions, version, unexpected objects and quick integrity
checks are verified. Corrupt/foreign/unsupported files are refused without
overwriting. Lock timeouts are finite (`0 < timeout <= 30`, default 5 seconds).
One store/facade instance per thread, explicit context-manager cleanup, no
reentrant calls. No locks span collection or diagnosis. There is no multi-host
storage, durable authorization audit, backup/retention service or scheduler.

## Privacy and local trust limits

No real credentials are read, no live call occurs and no raw log/API body,
environment, client configuration, session handle, roles or report prose is
persisted/exported by this profile. Request fields retain the existing finite
vocabulary. Identity references/keys must be non-secret; format validation cannot
detect a credential deliberately disguised as an allowed identifier.

All stores require an operator-controlled local directory and appropriate OS
permissions. SQLite is not encrypted. Checksums detect ordinary inconsistency,
not malicious file rewriting. Ownership metadata is trusted backend storage:
an attacker with arbitrary file/code control can change policy metadata or bypass
the facade. It cannot be advertised as a tamper-proof ACL database. Tests for
forged JSON verify that extra identity/approval fields and reconstructed contexts
grant nothing; they do not claim resistance to an attacker rewriting trusted code
or all valid metadata and checksums.

`PersistentMockRequests`, storage controls and older demos remain trusted
lower-level Python APIs. **Always route untrusted callers through the facade.**
This delivery creates no security sandbox around arbitrary backend Python code.
All execution/consumption/remediation flags remain false.

## Python example

```python
from integration.access import ProtectedMockRequests
from integration.access_identity import MockRequestIdentity
from integration.access_store import SQLiteOwnershipStore
from integration.request_store import SQLiteRequestStore
from uuid import uuid4

with SQLiteRequestStore('.tmp/access-requests.sqlite') as requests:
    with SQLiteOwnershipStore('.tmp/access-owners.sqlite', request_store=requests) as owners:
        identity = MockRequestIdentity(mock=True)  # trusted fixture composition only
        context = identity.issue('owner')
        backend = ProtectedMockRequests(requests, owners, identity=identity, mock=True)
        receipt = backend.create(context, {'service_target': 'MOCK-service'},
                                 idempotency_key=uuid4().hex)
        view = backend.get(context, receipt['request']['request_id'])
```

## Safe PowerShell demonstration

Use the existing root environment; no additional dependencies:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -B -m integration.access_demo --mock --scenario owner_allowed
$LASTEXITCODE  # 0
& $py -B -m integration.access_demo --mock --scenario other_owner_denied
$LASTEXITCODE  # 4: expected denial, not a successful cross-owner lookup
```

Default storage is temporary and explicitly closed/deleted. To demonstrate actual
separate-process restart with persistent files in an ignored directory:

```powershell
New-Item -ItemType Directory -Path .tmp/access-walkthrough -Force | Out-Null
$first = & $py -B -m integration.access_demo --mock --scenario owner_allowed --directory .tmp/access-walkthrough | ConvertFrom-Json
& $py -B -m integration.access_demo --mock --scenario restart_requires_fresh_context --directory .tmp/access-walkthrough --request-id $first.request_id
$LASTEXITCODE  # 0: forged context denied, fresh fixture context resolved; evidence still historical
```

Only `--mock`, allowlisted `--scenario`, optional local `--directory` and the
non-secret restart `--request-id` are accepted. No token, password, role, actor,
goal or URL arguments exist. Restart requires an existing directory/request ID.
Other scenarios: `missing_context`, `missing_permission`, `service_scope_mismatch`,
`expired_context`, `revoked_access`, `idempotency_does_not_bypass_access`.

Example denied JSON:

```json
{"access_profile":"infrapilot-request-access/1-mock","data_source":"mock","scenario":"other_owner_denied","status":"denied","error_code":"ACCESS_DENIED","exit_code":4,"authorization_consumed":false,"execution_authorized":false,"execution_performed":false,"remediation_verified":false}
```

Allowed output includes only a public request ID/revision and existing validated
summary, with partial 403/429 states, null CPU/RAM and unknown health preserved.
Denied output includes no request ID or data. Restart output reports
`fresh_context_required: true`, `reinspection_required: true`, and
`retained_evidence_available: false` for a prior completed inspection.

| Exit | Meaning |
| --- | --- |
| 0 | Demonstration succeeded; no application-health/execution claim |
| 4 | Access denied, including expected negative scenarios |
| 3 | Invalid arguments, absent literal Mock opt-in or invalid restart ID |
| 2 | Dependency, storage, history, evidence, conflict or unexpected runtime failure |
| 130 | Interrupted |

Help/invalid opt-in require only stdlib. Missing composition dependencies fail
before storage creation. Errors are fixed JSON without rejected values/tracebacks;
broken/interrupted output may prevent a JSON report.

Remaining production blockers: verified identity-provider integration, trusted
account/service grants and ownership onboarding, durable approval/audit storage,
reviewed live Liara access, production freshness/replay policy and an executor.
No UI, deployment, real infrastructure mutation or new privileged route is included.
See [executed verification](ACCESS_VERIFICATION.md).
