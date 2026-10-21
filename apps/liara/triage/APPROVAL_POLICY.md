# Approval Policy and authorization gate (Task 3)

**Internal DRAFT integration interfaces. Team approval is required before final
setup/provider integration. These are not official Liara API schemas.** All six
Task 1 models, the Task 2 engine, their dependencies, and their 130 tests remain
unchanged. This module implements decisions, not infrastructure execution.

## Trust boundary

`ApprovalGate` is constructed only by trusted server code with an `ActionPolicy`,
an `IdentityBoundary`, atomic `ApprovalStore`, and trusted aware UTC clock.
Defaults do not install an identity verifier, policy, or store and always deny.
None of these dependencies may be chosen, supplied, or replaced by Agent input.

`IdentityBoundary.authenticate(authentication)` must verify a real credential or
trusted session and return `AuthenticatedActor`, never simply trust an ID,
`verified=true`, Agent output, or an Actor object supplied by the caller. This
repository supplies only the Protocol, not an authenticator. Test-only identity
fixtures use opaque preinstalled session handles; they are not production login.

`is_authorized(actor, canonical_action, permission)` must resolve the exact target
against trusted service information and check the actor's current active-account
status and scoped permission. Permission is separately required for requesting
approval, approving a target operation, and obtaining execution authorization.
Stored approver permissions are checked again at consumption, including account
revocation. Missing, exception-producing, malformed, or non-True identity/ACL
responses deny. There is no anonymous read-only authorization.

The threat model treats Agent input, proposal text/labels, parameters, request IDs,
and claimed identities as untrusted. Trusted Python composition code, store
transactions, identity verifier, clock, and policy code remain within the server
trust boundary. This is not a sandbox against arbitrary code already running
inside that process or an attacker controlling those trusted dependencies.

## Independent canonical classification

`ActionIntent` contains `service_id`, `action_type`, `parameters`, and optional
Task 1 `proposal` display metadata. Proposal risk, title, description, action ID,
and `requires_approval` never determine policy or the execution payload.

| Category | Canonical operation | Valid parameters |
| --- | --- | --- |
| Read-only inspection | `inspect_service`, `inspect_metrics` | none |
| Read-only inspection | `inspect_logs` | integer `limit`, 1–1000, default 100 |
| Low risk | `refresh_observations` | none |
| Sensitive, approval required | `restart_service` | integer `grace_period_seconds`, 0–300, default 30 |
| Sensitive, approval required | `redeploy_service` | immutable `artifact_digest`: `sha256:` plus 64 lowercase hexadecimal digits |
| Sensitive, approval required | `change_resources` | one or both positive integer `cpu_millicores`, `ram_mib`, maximum 1,000,000 each |
| Sensitive, approval required | `modify_production_config` | `log_level` (`info`, `warning`, `error`) and/or integer `request_timeout_seconds` (1–300) |
| Denied | `delete_service`, `execute_command`, all unknown operations | never approved |

These are deliberately narrow local policy parameter schemas, **not Liara
endpoints, capabilities, quotas, resource limits, or promises of provider support**.
Configuration maps, commands, credentials, unknown keys, wrong units/types, numeric
strings, and booleans in integer fields are rejected. A future provider adapter
must independently verify actual capabilities, quotas, and operation semantics.

Identifiers are exact and case-sensitive: 1–128 ASCII characters, starting with
an alphanumeric character, then alphanumerics or `.`, `_`, `:`, `-`. Whitespace
is rejected rather than normalized. This narrower proposed gate identifier
constraint needs integration review; Task 1 `service_id` fields are unchanged.

Defaults are explicit in the canonical payload; omitted optional null resource/
configuration fields are removed. For example `{}` and a restart grace period
of 30 describe the same approved action. Reordered parameter keys are equivalent.
The SHA-256 fingerprint covers policy version, exact service, canonical operation,
and sorted canonical validated parameters. It excludes proposal labels. Canonical
parameters are stored as immutable JSON and returned as fresh decoded copies.
The gate checks allowed classifications against the built-in canonical allowlist;
additional installed policy may deny more, but may not silently widen that list.
Change the policy version whenever rules or canonical semantics change; changed
versions invalidate existing approval bindings.

## Approval lifecycle

```text
pending -> approved -> consumed
   |           |
   +-> rejected <+  (authorized rejection may revoke an unconsumed grant)
   |           |
   +-> expired <+
```

Requests bind a UUID4 request ID, canonical action/fingerprint, verified requester,
verified approving actor when granted, creation/expiration timestamps, and state.
The default TTL is five minutes; valid requested TTLs are greater than zero and
at most fifteen minutes. The exact deadline is expired (`now >= expires_at`).
Expiration is checked lazily on gate access; an administrative store snapshot
may still contain its previous state until accessed by the gate. Never authorize
from `store.get`, a frontend state label, or an `ApprovalRequest` snapshot.

`request_approval(intent, authentication=..., ttl=...)` creates only `pending`.
`approve(request_id, authentication=...)` requires an explicit call under an
authorized approver identity. Requester and approver must be different actors,
even when the requester also holds an approval role. No grant is inferred from
an Agent response. `reject` requires the same approval permission and can reject
pending requests or revoke an approved request before consumption.

These transitions return `GateDecision.allowed=False`: approval alone is not
execution authorization. Rejected, expired, and consumed states are terminal;
reapproval or replay cannot reactivate them. Actor/target permissions and policy
are checked at each relevant transition. Changed policy requires a fresh request.

## Independent authorization boundary

`authorize(intent, authentication=..., approval_request_id=...)` is callable by a
future trusted execution adapter. It:

1. Revalidates the intent and independently re-evaluates canonical policy.
2. Authenticates the caller and checks current permission for that service/action.
3. For sensitive operations, loads the exact approved request; checks canonical
   service/type/parameters/version/fingerprint equality and requester identity;
   validates state and expiration; and checks the approver's current authorization.
4. Rechecks policy and expiration after external identity/ACL calls.
5. Atomically changes `approved` to `consumed` with its structured audit event.
6. Returns an authorization decision with a unique decision ID and canonical
   payload. The reason is `authorized_not_executed`; no operation has occurred.

Only the original verified requester can consume a grant. Delegated execution or
impersonation is not implemented; future service-account delegation requires a
separately reviewed trusted identity design, not a caller-supplied user ID.

Read-only and low-risk actions need current authentication, target permission,
policy, clock, and working audit storage but no approval request. Passing an
approval ID to an operation that does not require one is rejected.

The future server execution adapter must enforce this gate **immediately before
actual execution**, then dispatch only `decision.action.action_type` and
`decision.action.parameters` for `decision.action.service_id`. It must never
dispatch an Agent proposal's action ID or use different parameters after checking
the gate. Frontend approval alone cannot authorize execution. Returned decisions
are in-process receipts, not signed bearer tokens or reusable execution permits;
never accept them from a caller or cache them to authorize a later operation.

Consumption does not prove execution. If execution later fails, the approval
remains consumed; retries require a fresh approval. This task does not provide
an executor, execution idempotency, real success reporting, or an execution log.
`ActionProposal.status` stays `not_executed` throughout this module.

## Atomic store and audits

`InMemoryApprovalStore` holds a process-local lock across each entire transaction,
including final checks. Copy-on-write commit publishes lifecycle changes and
audit events together; exceptions roll back both. Separate gate instances sharing
the store coordinate consumption. Nested transactions are refused so reentrant
callbacks cannot double-consume. Retained transaction handles cannot mutate a
committed state after the lock is released. Transaction mutation is a trusted
server port and must never be exposed to Agents or frontend clients.

Structured `AuditEvent` kinds cover `approval_requested`, `approval_granted`,
`approval_rejected`, `approval_expired`, `authorization_denied`, and
`authorization_consumed`. Each has a UUID, aware timestamp, enum reason, and safe
optional request/actor/target/action/fingerprint references. Parameter values,
authentication contexts, credentials, proposal text, and exception messages are
never recorded. Unrecognized/unpermitted target IDs are omitted from denied
audit payloads so arbitrary input cannot be echoed as a trusted service ID.

An audit failure prevents authorization and rolls back consumption. If clock or
storage is unavailable, the gate denies with `audit_recorded=False`; no durable
audit can be promised during an outage. A production caller must route this to a
separate trusted incident channel without logging credentials. No such production
monitoring integration is implemented here.

## Production limitations and proposed integration

- In-memory storage is **not safe for distributed production execution**. Multiple
  workers/processes do not share it; approvals and audits disappear on restart.
  Restart fails closed for previous request IDs. State/audit retention is unbounded,
  and copying history has a performance cost. No production durability is claimed.
- Production requires durable transactional storage, atomic compare-and-set or
  locking across all executors, protected audit retention, bounded data lifecycle,
  and controlled transaction access. Ambiguous commit failures deny and must not
  trigger automatic operation retries. This is not an exactly-once executor.
- Authentication, active-account checks, target resolution, scoped ACLs, credential
  verification, and trusted dependency installation must be supplied by the future
  server integration. Tests use preverified fixture identities, not a real IdP.
- The UTC clock must be trusted and reliable. Missing/naive values and rollback
  before request creation deny; comprehensive distributed clock-skew handling is
  not supplied. External identity/ACL calls occur under the MVP lock and need
  bounded timeouts/availability controls in a production implementation.
- Setup should map reviewed workflow input to the new draft `ActionIntent` and
  present explicit approval decisions. Provider execution should enforce this
  gate at the server boundary. Neither teammate's module is changed here, and
  current diagnosis recommendations do not automatically become runnable actions.
- Existing shared models are unchanged. `ActionIntent`, `ApprovalRequest`,
  `GateDecision`, `IdentityBoundary`, and transactional store interfaces require
  team review before adoption. There is no API, frontend, real login, Liara call,
  provider executor, restart, deployment, resource change, or PR merge in Task 3.

## Verification

Run the full module pytest command in `README.md`. Tests exercise canonical
classification, lifecycle transitions, valid and missing approvals, rejection,
deadline expiry, replay, cross-service/operation reuse, parameter substitution,
forged safety labels/identities, actor transfer, self-approval, authorization
revocation, policy changes/malformed responses, failures of trusted dependencies,
audit secrecy/rollback, reentrancy, 16 concurrent consumers across two gates, and
all original 130 contract/diagnosis regressions. Authorization decisions themselves
are not mocked; tests supply the trusted identity port and inject dependency
outages to exercise the real gate.
