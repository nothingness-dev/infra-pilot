# Diagnosis API and integration boundary (Task 4)

**INTERNAL DRAFT v0.1; team approval required before integration. Not official
Liara endpoints or schemas.** FastAPI app version: `0.1.0`. No version header,
schema negotiation, provider connection, authentication backend, or execution
capability is introduced. The six Task 1 schemas and Task 2/3 core are unchanged.

## Routes and schemas

| Method and route | Request | Successful response | Semantics |
| --- | --- | --- | --- |
| `GET /health` | none | 200 `HealthResponse` | `status=ok`, `component=triage_api`, `scope=process_only`; no provider check |
| `POST /internal/triage/diagnose` | existing `ServiceSnapshot` JSON | 200 existing `DiagnosisReport` | Actual deterministic engine; input HTTP 500 is an observation, not an API failure |
| `POST /internal/triage/policy/evaluate` | existing `ActionIntent` JSON | 200 `PolicyEvaluationResponse` | Classification only; `authorization_granted` is always false |
| `POST /internal/triage/authorize` | `AuthorizationRequest` JSON | 200 existing `GateDecision` | Calls the real gate; may atomically consume an approved request, never executes |
| `GET /openapi.json` | none | 200 OpenAPI document | Exact request/response field definitions; internal draft |

Swagger/ReDoc UIs are disabled. There are **no HTTP approval request, grant,
rejection, or execution routes**. Wrong routes/methods return structured 404/405.

`AuthorizationRequest` contains required `intent: ActionIntent` and optional
`approval_request_id: str | null` (maximum 128 characters). It rejects extras.
`ActionIntent` has `service_id`, `action_type`, `parameters`, and optional untrusted
`proposal`, with the existing canonical allowlist in `APPROVAL_POLICY.md`.
`PolicyEvaluationResponse` contains `policy: PolicyDecision` plus literal false
`authorization_granted`. `PolicyDecision.allowed` means the canonical operation
was classified, **not** that the caller has target permission or approval.

`GateDecision` uses the unchanged Task 3 dataclass serialization: `allowed`,
enum `reason`, nullable `action`, nullable `request`, nullable `authorization_id`,
and `audit_recorded`. The nested canonical action includes `parameters_json`
(a JSON-encoded string), `policy_version`, and `fingerprint`; no new action shape
is invented. `authorized_not_executed` is a permission decision only. Successful
authorization consumes a sensitive approval even though this module executes
nothing. Do not use this route for previews, polling, or automatic retries.

Invalid JSON/model input returns 422:

```json
{"error":{"code":"validation_error","message":"Request does not match the required schema."}}
```

Error envelopes contain only `error.code` and safe constant `error.message`.
They omit submitted values, validation locations/context, validator text, exception
messages, and tracebacks. Unexpected internal failures return 500 `internal_error`.
The JSON-only middleware buffers responses, catches failures before server error
logging, and marks responses `Cache-Control: no-store`. Streaming, background
responses, and large unbounded workloads are outside this MVP.

## Trusted approval wiring and failure behavior

The exported default `api.app` has **no** approval bridge or authentication
resolver installed. Both approval HTTP routes return 503
`approval_integration_unavailable`. Installing only a bridge still returns 503
`authentication_unavailable`. A configured verifier returning no authenticated
context yields 401 `authentication_required`. Resolver exceptions yield a safe
503. Supplying `Authorization`, `X-User-ID`, `X-Roles`, or body identity fields
cannot install dependencies. Unexpected body fields are rejected.

Only trusted server composition may construct an app with these dependencies:

```python
from fastapi import FastAPI
from infrapilot_triage.api import create_app, TrustedAuthenticationResolver
from infrapilot_triage.approval_integration import ApprovalIntegration
from infrapilot_triage.approval_store import ApprovalStore
from infrapilot_triage.authorization import ApprovalGate
from infrapilot_triage.identity import IdentityBoundary
from infrapilot_triage.policy import ActionPolicy

def build_trusted_app(
    identity: IdentityBoundary,
    store: ApprovalStore,
    resolver: TrustedAuthenticationResolver,
) -> FastAPI:
    # Call only after supplying genuine verifier, scoped ACLs, and atomic audit
    # storage. No production implementations are supplied by this module.
    policy = ActionPolicy()
    gate = ApprovalGate(identity=identity, policy=policy, store=store)
    return create_app(
        approval_integration=ApprovalIntegration(policy=policy, gate=gate),
        authentication_resolver=resolver,
    )
```

`TrustedAuthenticationResolver` is a synchronous `Callable[[Request], object | None]`.
It must verify a credential or resolve verified server middleware/session context;
it must never transform an arbitrary claimed user/role header into identity. Its
output is an opaque authentication context understood by the installed
`IdentityBoundary`. The gate authenticates that context again and checks current
scoped target/action permission. Server composition and dependencies are trusted
code, not a sandbox against malicious code already in the process.

Policy evaluation is informational under the configured trusted resolver. It does
not touch approval storage or audit, check a target ACL, or issue permission. Actual
authorization always delegates to `ApprovalGate.authorize`; it cannot fall back to
evaluation if the gate is missing or fails. Unknown/unsupported operations and
normal denials return 403. Unauthenticated gate decisions return 401. Missing or
failed identity, ACL, policy, clock, storage, or audit dependencies return 503 with
`allowed=false`. Gate denials retain its safe structured enum reason. Depending
on failure stage, 401/503 can contain `ErrorResponse` or `GateDecision`; OpenAPI
documents these unions. No raw error is echoed.

Requesting, explicitly granting, and rejecting approvals remain trusted Python
calls on `ApprovalGate`, protected by its existing permission checks. No UI body
or client identity claim can call them through this app. Approvals require a
different authorized actor, exact canonical bindings, valid expiration, and atomic
audit. Unknown operations, forged risk labels, expired approvals, changed actions,
and replay remain denied. Returned decisions are not bearer execution tokens.

## Python interfaces

- `infrapilot_triage.api`: `app`,
  `create_app(*, approval_integration=None, authentication_resolver=None)`,
  `TrustedAuthenticationResolver`, `get_approval_integration(request)`, and
  `get_trusted_authentication(request)`. Dependencies may be replaced only by
  trusted server/test composition; no client mechanism exists to do so.
- `infrapilot_triage.approval_integration.ApprovalIntegration`:
  constructor `(*, policy=None, gate=None)`;
  `evaluate(intent: ActionIntent) -> PolicyEvaluationResponse`;
  `authorize(intent, *, authentication=None, approval_request_id=None) -> GateDecision`.
  Missing dependencies and dependency exceptions deny safely. No mutation methods.
- `infrapilot_triage.api_contracts`: `HealthResponse`, `ErrorCode`, `ErrorDetail`,
  `ErrorResponse`, `AuthorizationRequest`, and `PolicyEvaluationResponse`.
- `infrapilot_triage.redaction`: `redact_log_message(message) -> str` and
  `sanitize_snapshot(snapshot) -> tuple[ServiceSnapshot, bool]`. HTTP-only input
  sanitization; direct core diagnosis semantics are unchanged.
- `infrapilot_triage.example_payloads.build_mock_examples(*, mock: bool)` returns
  the five real serialized MOCK pairs only with explicit `mock=True`. Its CLI
  `main()` requires `--mock` and writes only the module's `examples` directory.
- Existing package exports remain intact: `diagnose`, shared models, thresholds,
  `ActionIntent`, `ActionPolicy`, and `ApprovalGate`. See previous task guides.

## Data handling and local operation

See `README.md` for exact PowerShell install, loopback launch, diagnosis request,
and full pytest commands. Runtime: Pydantic v2, FastAPI, Uvicorn. Testing: pytest
and HTTPX. No new service, database, frontend, LLM, or orchestration dependency.

Send the existing snapshot JSON retaining nulls: CPU percent 0..100, RAM MiB,
response milliseconds, aware timestamp if known; `logs=null` unavailable versus
`logs=[]` collected but empty. Unknown metrics remain null; zero remains measured.
The response preserves source labels, stable evidence references, deterministic
ranking, missing information, limitations, and `not_executed` proposals.

Before diagnosis, HTTP copies the snapshot and redacts recognizable credential
patterns in log messages (authorization values, common credential assignments,
URL user/password, common token formats, PEM private keys). Redaction is disclosed
in report limitations and evidence positions remain stable. It may remove useful
context; it is **not a general secret detector**. Trusted producers must sanitize
all input, including IDs and custom log formats, before transport. Core Python
`diagnose` intentionally still accepts/preserves supplied logs unchanged.

Diagnosis/health/OpenAPI have no authentication in this loopback MVP. Do not expose
this process publicly or send unsanitized production observations. Sensitive
routes stay unavailable until explicitly configured; there is no runtime mock
login, demo identity header, bypass flag, or mock HTTP authentication mode. Offline
examples in `examples/` use explicit MOCK-only generation. No fixture is evidence
of a real service's health. Real/mock is a caller declaration, not attestation.

Before network deployment, owners must supply reviewed authentication, trusted
target resolution/ACLs, TLS, network/access controls, request/log size limits,
timeouts, rate limiting, safe telemetry/retention, and any applicable browser
credential/CSRF controls. This app buffers JSON and supplies no streaming or log
volume controls. In-memory approval storage is single-process, volatile, and
unbounded; do not use it to coordinate production workers. No capability or
exactly-once execution guarantee is implied.

## Owner handoff and remaining integration decisions

Provider owner:

- Confirm service identifier/status mappings and supported observations. Convert
  actual units; do not clamp multicore CPU or invent missing metrics/logs.
- Provide source classification, aware timestamps, sanitized ordered logs, and
  agreed collection/error semantics. Window/truncation/freshness metadata and
  memory allocation limits remain unimplemented proposals.
- Independently confirm real provider operation support, account scope, quotas,
  and parameter semantics. Canonical local policy names are not a Liara SDK.

Setup/workflow owner:

- POST a provider-normalized `ServiceSnapshot` to diagnosis and validate the
  unchanged `DiagnosisReport`; display evidence, uncertainty/conflicts, null
  availability, mock labels, approval metadata, and `not_executed` status.
- Handle generic errors without requiring echoed field values. Distinguish API
  failure from a successfully diagnosed HTTP 500 observation.
- Propose reviewed mappings from recommendations to `ActionIntent`; recommendation
  IDs are not automatically executable. Supply real verified session/credential
  handling, current target-specific ACLs, and an explicit independent approver
  workflow before wiring approval calls. No UI-only approval is sufficient.
- Agree on the draft version/envelopes and deployment boundary with the team.

A real Liara end-to-end demo remains blocked on these agreements, actual provider
normalization/connectivity, trusted identity/ACL installation, durable atomic
approval/audit storage, approved workflow integration, and a separately reviewed
server executor. Any future executor must re-enforce the gate immediately before
dispatch and use only its returned canonical operation/parameters. This task does
not build that executor or modify either owner's code.

Implementation references: [FastAPI error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/),
[FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), and
[Starlette middleware](https://www.starlette.io/middleware/).
