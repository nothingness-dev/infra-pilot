# Liara PaaS observation capabilities

Reviewed on **2026-10-23** (original implementation: 2026-10-22). This is a documentation-backed implementation report,
not proof of access to a live account. No live credential/service was supplied
for this task; no authenticated live requests were performed.

## Primary sources and verification boundary

The official [Liara PaaS OpenAPI specification at the reviewed revision](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml)
is the source for the paths, request parameters and response fields below.
The reviewed upstream HEAD was `338325a42cd28d12dcee10c088840d2098504a8b`.
Links below are pinned so the evidence can be rechecked independently of later
upstream changes. Mock payloads are synthetic fixtures shaped by this schema;
they are not captured live responses.

The spec declares `https://api.liara.ir` as its server. The task's existing
`https://api.iran.liara.ir` configuration default is preserved, but equivalence
of the regional and published servers was not live-verified. Configure the
final HTTPS service URL explicitly if needed; redirects remain blocked.

## Documented read operations

| Capability / method | GET path and query | Documented response / local projection | Evidence |
| --- | --- | --- | --- |
| Project list / `list_projects()` | `/v1/projects` | `projects` array; existing list wrapper preserved | [Endpoint](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L45-L64) |
| Project details / `get_service(name)` | `/v1/projects/{name}` | `project` object; select `_id`, `type`, `status`, `isDeployed`. If returned, `project_id` must match the requested name. `envs` and extra fields are omitted. | [Endpoint](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L91-L117), [schema](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1621-L1690) |
| Deployment flag / `get_deployment_status(name)` | Same details endpoint; no invented deployment endpoint | Native `isDeployed` boolean and `status` string. Neither means healthy, current build progress, or a successful recent rollout. | [Fields](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1621-L1690) |
| Logs / `get_logs(name, since=...)` | `/v1/projects/{name}/logs?since=...`; `since` is a required string | Top-level array of objects with string `message`, `type`, `datetime`. Native strings are preserved. | [Endpoint](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L957-L992), [schema](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1723-L1733) |
| Resource summary / `get_metrics(name)` | `/v1/projects/{name}/metrics/summary` | Optional `cpuUsage`/`memoryUsage` arrays, whose records contain `applet` and `value` arrays of number/string values; optional `disksUsage` string fields | [Endpoint and schema](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1133-L1203) |
| Release history / `list_releases(name, page=1, count=10)` | `/v1/projects/{name}/releases?page=...&count=...`; both query parameters are required in the spec | Optional `releases`, `total`, `currentRelease`, `readyReleasesCount`; selected release `_id`, `state`, `createdAt`, `finishedAt`, `tag`. Preserve source ordering. No inferred latest/current state join. | [Endpoint](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1089-L1132), [schema](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1842-L1926) |

Every operation above is **documented and implemented, live access unverified**.
All new public methods use GET; none change infrastructure. `name` is the
documented project name, not an assumed interchangeable database `_id`.

## Authentication and permissions

[Security schemes](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L2031-L2039)
declare Authorization-header authentication and HTTP Bearer JWT. The operations
describe access to projects owned by the caller and document 401/404 errors.
The reviewed specification does not enumerate per-operation token scope names,
team-role rules, or a least-privilege role matrix. Those details are **unverified**;
no permission or ownership is inferred from a schema or successful mock call.
The existing transport defensively handles 403, 429 and 5xx as well.

## Missing information and availability semantics

These are different dimensions; do not collapse them into an unsupported flag:

| State | Meaning / evidence |
| --- | --- |
| Documented support | The official spec describes the endpoint. It does not prove this account can use it. |
| Unsupported | Requires affirmative evidence that a capability is not supported. **No requested capability is conclusively classified unsupported in this review.** |
| Unverified | No live access test, undefined units/semantics, or a capability not researched in this task. Unimplemented does not mean unsupported. |
| `authentication_failed` | This collection received HTTP 401. |
| `permission_denied` | This collection received HTTP 403. The result alone does not identify which permission is missing. |
| `not_found` | This collection received HTTP 404; do not treat this as evidence that the endpoint is globally unsupported. |
| `unavailable` | A successful response supplied null or no recognized observation fields. This is an explicit local tolerance for absent data, not a claim that the spec guarantees null responses. |
| `not_collected` | A caller skipped this optional observation; no request was made. |
| `failed` | Transport, rate-limit, server or response-validation failure; the typed error is retained. |
| `available` | Valid data was collected, including a measured false/zero or an empty collection. This does not imply application health. |

`Observation.availability` reserves `unsupported` and `unverified` for future
evidence/policies. The collector currently never emits them from an HTTP error.

The schema's observation fields generally lack `required` declarations. Local
models retain missing/null fields as `None`; known fields with incompatible
types cause `INVALID_RESPONSE`. Unknown fields are excluded, not silently
promoted to observations. A malformed endpoint response is rejected atomically;
other successfully collected endpoints remain available in a partial bundle.

## Units, timestamps and collection limits

- CPU, RAM and disk units are **not specified by the reviewed summary schema**.
  Metric tuple positions, sample timestamps, aggregation windows and multicore
  scaling are also unspecified. Preserve native numbers/strings and ordering;
  `cpu_unit`, `memory_unit`, `disk_unit` remain `None`. No percent/MiB conversion,
  numeric-string coercion, clamping or synthetic zero is performed.
- Logs `since` is documented only as a timestamp string. The adapter requires
  an explicit nonblank string, URL-encodes it and forwards it without assuming
  accepted epoch units, formats, timezone, inclusivity or ordering. Limits,
  pagination, retention, streaming completeness and truncation are unverified.
  The mock returns canned logs; it does not emulate server-side time filtering.
- Native log/release/disk timestamp strings are preserved, not parsed into
  asserted timezone-aware observations. Collector timestamps are separately
  generated UTC instants indicating when a request finished, not source freshness.
- Release history reads one requested page; it does not fetch all pages or
  guess which entry is current. Local page/count inputs must be positive integers.
- Transport retains the existing per-socket timeout, 4 MiB response limit,
  complete-body checks, redirect blocking, and exact configured-token redaction.
  No retries occur. Log/release collection never silently truncates oversized
  responses: it returns `INVALID_RESPONSE` instead.
- API availability, API request latency and deployment flags are not application
  availability, application response time or diagnosis. No application health
  probing or host-controlled URL fetching is implemented.
- Other observed app secrets inside arbitrary log text cannot be identified
  reliably by this adapter; callers must apply their log-display/access policy.
  The configured API token is always redacted from these results, and project
  environment variables and unrestricted project/release metadata are excluded.

## Integration boundary

Models in `provider/models.py` and `collect_service_observations()` are local to
this module. The setup coordination envelope was inspected for context; the
triage `ServiceSnapshot` draft now has an optional provider-local projection
described below. Neither shared contract is finalized, imported or modified.
No permissions backend, execution adapter, app server or deployment infrastructure
is supplied by provider.

## Live-smoke tooling follow-up (2026-10-22)

`python -B -m provider.examples.live_smoke` now provides environment-configured,
read-only checks using the existing adapter. Its report excludes payloads,
project/account names, credentials and raw error messages. See the module README
for configuration, summary fields and exit codes.

At implementation verification, **both `LIARA_API_TOKEN` and
`LIARA_PROJECT_NAME` were absent from the execution environment**. No
authenticated live smoke run was performed. Automated tests use mocked clients
or mocked HTTP transport; they do not change any capability's live-verification
status in this document.

When a real run is later reviewed, retain its time, account/project context
outside committed credential data, API base URL and per-check outcomes. Record
the conclusion only for that context/time; do not infer account-independent
support or permissions from a successful call, and do not infer unsupported
API capabilities from 403, 404, missing data or skipped logs. Metric units and
other schema uncertainties above remain unverified.

## Draft diagnosis compatibility follow-up (2026-10-22)

The official upstream HEAD was rechecked and remains
`338325a42cd28d12dcee10c088840d2098504a8b`; no new metric-unit or health semantics
were established. Provider now has a local `TriageAdapter` projection and a
synthetic draft request. [TRIAGE_HANDOFF.md](TRIAGE_HANDOFF.md) records the exact
triage revision, conservative field mapping, per-capability sidecar, log-sharing
policy and offline schema/ASGI QA. No shared contract is finalized by this work.

Neither `LIARA_API_TOKEN` nor `LIARA_PROJECT_NAME` was present. No authenticated
request, account/key creation or test-service provisioning was performed and no
real captured fixture is supplied. All previous live-access and unit/semantic
uncertainties remain unchanged. Official documentation describes token creation
through the console, but short-lived key options and permission scopes were not
verified in a logged-in account. Mock and in-process diagnosis tests do not
establish any account's Liara permissions or service health.

## Collection-context preparation follow-up (2026-10-22)

An experimental provider-local Draft v0.2 envelope and synthetic fixtures now
preserve collection metadata beside the unchanged snapshot. Executed offline QA
uses actual Task 05A and Setup code; see
[COLLECTION_CONTEXT_DRAFT.md](COLLECTION_CONTEXT_DRAFT.md). No new Liara endpoint,
unit interpretation or live support conclusion is introduced. Current coordination
keeps testing Mock, and no authenticated live request was made. Service health,
metric units, permissions and source-window uncertainties remain as above.

## Project access investigation (2026-10-23)

Official upstream revisions were checked again: OpenAPI remains
`338325a42cd28d12dcee10c088840d2098504a8b`; CLI master was
`14ec35f79d703a09a5e3abbb22ba59239cdde80d`. These are documentation/source
observations, not authenticated API results.

- The [Projects schema](https://github.com/liara-cloud/openapi/blob/338325a42cd28d12dcee10c088840d2098504a8b/spec/paas.yaml#L1689-L1720)
  distinguishes database `_id` from project name `project_id`. The official
  [list command](https://github.com/liara-cloud/cli/blob/14ec35f79d703a09a5e3abbb22ba59239cdde80d/src/commands/app/list.ts#L18-L28)
  reads the `projects` envelope and displays `project_id`. The existing adapter
  already validates that envelope and rejects an absent/malformed array rather
  than substituting `[]`; no such parser bug was reproduced. Its legacy bare-list
  tolerance is preserved, without claiming that shape is officially documented.
- The official [CLI request setup](https://github.com/liara-cloud/cli/blob/14ec35f79d703a09a5e3abbb22ba59239cdde80d/src/base.ts#L269-L311)
  explicitly supplies a `teamID` query parameter: empty for personal scope, a
  selected identifier for a team. This detail is evidenced by official client
  source; it is not a permission guarantee or a requirement stated in the reviewed
  PaaS OpenAPI operation. Optional `ProviderConfig(team_id=...)` /
  `LIARA_TEAM_ID` now forwards this scope consistently on existing read requests.
  Unset preserves prior behavior; empty explicitly selects personal scope.
  Identifiers are URL-encoded, omitted from config repr/safe config export and
  never printed by diagnostics. The printable-ASCII/128-character bound is a
  local input policy, not a verified Liara identifier-format specification.
- The [CLI host constants](https://github.com/liara-cloud/cli/blob/14ec35f79d703a09a5e3abbb22ba59239cdde80d/src/constants.ts#L9-L14)
  currently map its Iran/Germany REST choices to `api.liara.ir`. This corroborates
  the OpenAPI server; it does not establish account-region equivalence with the
  legacy adapter default `api.iran.liara.ir`. No automatic fallback was added.
  The focused verification command permits only these two exact API hosts,
  HTTPS root paths and the default/443 port. Other existing Provider callers
  retain their validated configurable transport behavior.

The public [developer overview](https://developers.liara.ir/) and its
[documentation index](https://developers.liara.ir/llms.txt) were accessible;
individual indexed Markdown endpoint pages were not retrievable in this review.
The pinned official specification and CLI source above supplied the substantive
endpoint, shape and query evidence. Scope names, accepted account roles, metric
units and actual account visibility remain unverified.

The historical user-reported zero-project lists and subsequent 404s do not
establish a root cause. Current process settings contain neither token nor
target/binding configuration. **No authenticated live list, exact target
resolution, service, deployment, logs, metrics, releases or end-to-end inspection
was performed.** No account, region, permission or API-support conclusion follows.
Explicit scope support is a documented diagnostic option, not a proven fix for
the earlier result. See [operator procedure and verification record](../integration/LIVE_VERIFICATION.md).
