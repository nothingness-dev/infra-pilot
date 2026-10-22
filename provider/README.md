# Liara provider adapter and authentication layer

Roham owns this isolated `provider/` package for InfraPilot. It uses **Python
3.10+ and the standard library only**. No installation, framework, credentials,
or network access is required to run its tests. Package markers are named
`__init__.py` (Python's import/discovery convention), rather than `init.py`.

The public API checks connection/authentication, lists projects, and collects
read-only service/deployment, log, metric and release observations. It does not
create or modify infrastructure. It has no dependency on Fatima's `setup/`, and
does not change that module's models or integration contracts.

## Run tests

From the repository root:

```powershell
python -B -m unittest discover -s provider/tests -t . -v
```

Live-client tests mock HTTP transport; redirect tests exercise urllib's real
redirect handler with a mocked HTTPS transport. Mock-client tests reject socket
access and opener construction. Tests cover credentials, all required status
codes, connection/read timeouts, malformed responses, secrets, and offline flows.
Regression tests also use the real `http.client.HTTPResponse` parser with an
in-memory socket to verify complete/truncated fixed-length and chunked bodies.

## Live client

```python
import os
from provider import LiaraClient, ProviderConfig

client = LiaraClient(ProviderConfig(
    api_key=os.environ["LIARA_API_TOKEN"],
    # Defaults: base_url="https://api.iran.liara.ir", timeout=10.0, is_mock=False
))

status = client.ping()
if status.success:
    print(status.data.connected, status.data.latency_ms)
else:
    print(status.error.code, status.error.message)

projects = client.list_projects()
if projects.success:
    for project in projects.data:
        print(project.get("project_id"))
```

`LiaraApiClient` is an alias for `LiaraClient`. Both methods send authenticated
`GET /v1/projects` requests, following the
[official Liara PaaS specification](https://github.com/liara-cloud/openapi/blob/main/spec/paas.yaml).
The required regional default above is preserved. The published specification
also lists `https://api.liara.ir`; callers can explicitly configure the HTTPS
base URL appropriate to their account/region. Redirects are returned as errors,
so configure the final service URL directly.

`ProviderConfig` and its `SecretStr` credential are immutable. The client's
`config` property is read-only; construct a new client to change credentials or
switch between live and mock mode. Configuration accepts a plain string token
and immediately wraps it in `SecretStr`. A live token must be nonempty, printable ASCII without
whitespace; pass the token alone, without a `Bearer ` prefix. The base URL must
use HTTPS, without embedded credentials, a query, or a fragment. The timeout
must be positive and finite. Invalid configuration raises a fixed-message
`ValueError` before network access.

## Offline mock

```python
from provider import LiaraClient, MockLiaraClient, ProviderConfig

mock = MockLiaraClient()  # No token required; two realistic example projects
assert mock.ping().data.connected
assert mock.list_projects().is_mock

# The flag also makes the regular client completely offline.
flagged = LiaraClient(ProviderConfig(api_key="", is_mock=True))
assert flagged.list_projects().is_mock

failure = MockLiaraClient(failure_mode="unauthorized").ping()
assert not failure.success
assert failure.error.http_status == 401
assert failure.data.connected is False
assert failure.is_mock and failure.data.is_mock

empty = MockLiaraClient(failure_mode="empty").list_projects()
assert empty.success and empty.data == []
```

`MockLiaraClient(config=None, *, failure_mode=None, failure_modes=None)` forces mock mode on
a copied config, even when given a live config. It never constructs an HTTP
opener or opens a socket. Every result, including errors, has `is_mock=True`.
Fixtures are fresh on each call; caller mutations do not affect later calls.

Supported modes: `None` (normal), `"empty"`, `"missing"`, `"invalid_response"`,
`"timeout"`, `"unauthorized"` (401),
`"forbidden"` (403), `"rate_limit"` (429), `"not_found"` (404), `"unavailable"`
(503), or any integer HTTP error status from 400 through 599. Unknown modes
raise a safe `ValueError`. Empty means a valid account with zero projects,
and still produces a successful connection check.

## Result contracts for integration

Core client models live in `provider.models` and are also exported by `provider`.

| Model | Fields / behavior |
| --- | --- |
| `ProviderConfig` | `api_key` (string input, stored as `SecretStr`), `base_url`, `timeout`, `is_mock` |
| `ProviderStatus` | `connected`, `latency_ms`, `account_email`, `is_mock`, `timestamp` |
| `StructuredError` | `code`, safe `message`, `http_status` or `None`, `retryable` |
| `ProviderResult[T]` | `success`, `data` or `None`, `error` or `None`, `is_mock` |

`list_projects()` returns `ProviderResult[list[dict[str, Any]]]`. It unwraps
Liara's `{"projects": [...]}` envelope; a top-level project list is also accepted.
Project objects retain the provider's fields. An empty list succeeds. Missing or
invalid project lists fail with `INVALID_RESPONSE`, rather than implying that
authentication worked. Listing failures have `data=None`.

`ping()` returns `ProviderResult[ProviderStatus]`. **Both successful and failed
pings include status data**; a failure has `connected=False` and an error.
Latency uses a monotonic clock and is measured in milliseconds. Timestamps use
ISO 8601 UTC with a `Z` suffix. `account_email=None` because the projects
endpoint does not establish account identity; no identity is fabricated.

For client-produced results, `success=True` means `error=None`. `is_mock` must
be carried through downstream flows so fixtures are distinguishable from live
observations. Connection success means access to the project-list endpoint;
it grants no authorization for infrastructure changes. These are provider-local
contracts; integration with `setup/` references still needs team agreement.

Dataclass results can be converted to detached JSON-compatible values:

```python
import json
from dataclasses import asdict
from provider import MockLiaraClient

result = MockLiaraClient().ping()
serialized = json.dumps(asdict(result))
```

## Errors and transport behavior

Public methods return structured failures for HTTP, connection and response
errors. Typed exceptions in `provider.exceptions` inherit from
`LiaraProviderException` and provide `to_error()`; they are used internally,
not raised for ordinary provider failures.

| Failure | Exception | Error code | Retryable |
| --- | --- | --- | --- |
| HTTP 401 / 403 | `AuthenticationError` | `AUTHENTICATION_ERROR` | No |
| HTTP 429 | `RateLimitError` | `RATE_LIMITED` | Yes |
| Socket/connection/read timeout, HTTP 408 | `TimeoutError` | `TIMEOUT` | Yes |
| HTTP 5xx, including 500/502/503/504 | `ApiUnavailableError` | `API_UNAVAILABLE` | Yes |
| HTTP 404 | `ResourceNotFoundError` | `RESOURCE_NOT_FOUND` | No |
| Other connection failures | `NetworkError` | `NETWORK_ERROR` | Yes |
| Invalid JSON, project shape, encoding, protocol or size | `InvalidResponseError` | `INVALID_RESPONSE` | No |
| Invalid internal request arguments | `InvalidRequestError` | `INVALID_REQUEST` | No |
| Other HTTP errors, including blocked redirects | `LiaraProviderException` | `PROVIDER_ERROR` | No |

HTTP failures retain the status code; transport failures have no HTTP status.
There are no automatic retries. `retryable` is a hint for a caller's bounded
retry policy, not a promise of success. The `timeout` applies to socket
operations rather than an overall wall-clock deadline. Responses are closed
and reads are limited to 4 MiB plus one byte for overflow detection. Oversized
declared lengths are rejected before reading; bodies shorter than their declared
`Content-Length` are rejected, and chunked framing takes precedence over that
header. Empty 200, non-finite JSON values (including exponent overflow such as
`1e999`) and malformed project shapes are rejected. `HEAD` succeeds without
reading or parsing a response body. The internal
transport supports JSON payloads and URL-encoded query parameters for future
adapters; all public provider operations are read-only.

## Secret handling

- Config and secret `str`/`repr` mask the token. `config.to_dict()` produces
  redacted, JSON-compatible diagnostic configuration. `asdict(config)` retains
  an opaque `SecretStr`; direct JSON serialization intentionally fails rather
  than exposing it. Use `config.to_dict()` for configuration serialization.
- The only explicit disclosure method is `config.api_key.get_secret_value()`;
  the adapter uses it to build `Authorization: Bearer <token>`. Do not log its
  return value or inspect/log raw request headers.
- The adapter emits no logs or console output. Exceptions retain fixed messages,
  discarding caller-supplied messages, remote error bodies and transport text.
  Their `args`, `str`, `repr`, and structured errors contain no raw diagnostics.
  Implicit exception context is suppressed so `logging.exception()` cannot
  render a previous transport error containing a token. Do not explicitly chain
  provider exceptions to raw transport errors with `raise ... from raw_error`.
- Exact occurrences of the configured token in decoded success data, including
  nested values and dictionary keys, are redacted before results are returned.
- TLS verification uses urllib's default HTTPS behavior. Redirects are blocked,
  and Authorization is also registered as an unredirected header. No global
  urllib opener is installed or modified.

## Service observations

See [CAPABILITIES.md](CAPABILITIES.md) for pinned official API evidence, access
limitations, native response schemas, and unverified units/time semantics.
All additions reuse the protected transport. Runtime dependencies remain zero.

| Public method | Local result data |
| --- | --- |
| `get_service(name)` | `ServiceDetails`: selected identifier/platform/native status/deployment fields |
| `get_deployment_status(name)` | `DeploymentStatus`: native deployment flag and status from project details |
| `get_logs(name, *, since)` | List of `ServiceLog`; required opaque nonblank timestamp string |
| `get_metrics(name)` | `MetricsSummary` of native series and disk strings; units remain `None` |
| `list_releases(name, *, page=1, count=10)` | One `ReleasePage`, retaining native states and order |
| `collect_service_observations(name, *, logs_since=None, include_metrics=True)` | `ServiceObservations` with per-component data, availability, error, origin and collector timestamps |

Every method returns `ProviderResult` with its existing `is_mock` flag. Retain
that flag when forwarding data. Null/sparse responses can yield
`success=True, data=None` for unavailable observations; malformed structures
yield `INVALID_RESPONSE`. Missing fields stay `None`, empty arrays stay empty,
and false/zero remain measured values. Native status strings are not mapped to
healthy/unhealthy. CPU/memory samples are not converted to percent/MiB. API
latency is not exported as an application response-time measurement.

Project `envs` and unrestricted metadata are excluded from selected detail and
release models. Returned `project_id`, when present, must match the request.
`ServiceLog` retains `message`, `native_type`, `native_datetime`; no severity or
timezone is guessed. These dataclasses are module-local and independent of the
team's unapproved `ServiceSnapshot` draft.

```python
import json
import os
from dataclasses import asdict
from provider import LiaraClient, MockLiaraClient, ProviderConfig

# For live calls, set LIARA_API_TOKEN and initialize with the same methods:
# live = LiaraClient(ProviderConfig(api_key=os.environ["LIARA_API_TOKEN"]))
mock = MockLiaraClient(failure_modes={"logs": 403})

result = mock.collect_service_observations(
    "example-api", logs_since="2026-01-01T00:00:00Z",
)
assert not result.success
assert result.error.code == "PARTIAL_COLLECTION"
assert result.data.service.availability == "available"
assert result.data.logs.availability == "permission_denied"
assert result.data.logs.error.http_status == 403
assert result.data.is_mock and result.is_mock
print(json.dumps(asdict(result), allow_nan=False))

# These each make a single read-only request when used with the live client:
# details = live.get_service("your-project-name")
# logs = live.get_logs("your-project-name", since="provider-supported-timestamp")
# releases = live.list_releases("your-project-name", page=1, count=10)
```

The collector always reads service details once and derives deployment from
that same response. It optionally makes one log request (only with explicit
`logs_since`) and one metrics request. At most three sequential GETs occur;
release pages are fetched separately and never implicitly paged. Optional flags
are validated before any request. A skipped component has `not_collected`, null
data/error/time. Every requested component gets its own UTC collection time,
availability and error. Source timestamps remain distinct from collection time.

An unsuccessful bundle **retains its valid data**. `PARTIAL_COLLECTION` means at
least one component is available but some requested data is unavailable/failed;
`COLLECTION_FAILED` means none is available. The bundle's `http_status` is `None`,
because multiple requests are involved; inspect the component errors. Bundle
`retryable` is true when any component error is retryable. Inspect individual
components when retrying instead of assuming every request needs repetition.

### Extended offline modes

`MockLiaraClient(..., failure_modes={...})` accepts copied capability overrides:
`projects`, `service`, `logs`, `metrics`, `releases`. The global `failure_mode`
remains the default; an explicit override of `None` restores normal success for
that capability. `get_deployment_status()` shares the `service` mode.

In addition to existing modes, `"missing"` returns null source data and
`"invalid_response"` returns a malformed source shape. `"empty"` supplies empty
collections/sparse details. All mock observations remain synthetic and labelled;
mock metric numbers imply no units, and mock log timestamps do not implement
server-side `since` filtering. Release page/count slicing is supported.

## Read-only live smoke test

From the repository root, run:

```powershell
python -B -m provider.examples.live_smoke
$LASTEXITCODE
```

This tool uses the existing `LiaraClient` methods for **one configured project**:
service details, deployment status, logs, summary metrics, and the first release
page (the adapter's default page/count). It does not list account projects,
probe application URLs, perform mutations, retry, or follow redirects. Service
and deployment checks are independent calls to the same details endpoint. At
most five GETs occur, or four when logs are skipped. Per-socket timeout and
response-size protections are inherited from the client.

### Environment-only configuration

| Variable | Requirement |
| --- | --- |
| `LIARA_API_TOKEN` | Required token, without `Bearer `; validated by `ProviderConfig` |
| `LIARA_PROJECT_NAME` | Required documented project name; uses the adapter's name/path validation |
| `LIARA_LOGS_SINCE` | Optional opaque timestamp string accepted by the provider; omit to skip logs. Explicit blank or non-UTF-8 text is invalid. No timestamp format/units are guessed. |
| `LIARA_API_BASE_URL` | Optional trusted HTTPS API base URL, validated by `ProviderConfig`; defaults to `https://api.iran.liara.ir`. This is not an application health-check URL. |
| `LIARA_TIMEOUT_SECONDS` | Optional positive finite number, validated by `ProviderConfig`; defaults to 10 seconds |

All configuration is validated before client construction or network access.
Explicit invalid optional values are rejected rather than silently replaced.
No command-line arguments are accepted or echoed. The tool reads no credential
files, does not prompt, and does not write reports/configuration to disk.

For a temporary PowerShell session, use a masked prompt so the token is not a
literal in command history. The example clears the token/project environment
variables it sets after execution:

```powershell
$liaraSmokeToken = Read-Host 'Liara API token' -AsSecureString
try {
    $env:LIARA_API_TOKEN = [System.Net.NetworkCredential]::new('', $liaraSmokeToken).Password
    $env:LIARA_PROJECT_NAME = Read-Host 'Liara project name'

    # Optional: set LIARA_LOGS_SINCE to a provider-supported timestamp to enable logs.
    # Without it, the log check is explicitly reported as skipped.

    python -B -m provider.examples.live_smoke
    $liaraSmokeExitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:LIARA_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:LIARA_PROJECT_NAME -ErrorAction SilentlyContinue
    $liaraSmokeToken.Dispose()
}
$liaraSmokeExitCode
```

### Report and exit codes

Stdout contains one JSON object; ordinary failures do not produce stderr or a
traceback. Only fixed capability/status names, allowlisted error codes,
validated HTTP error status codes, UTC check times and local check durations
are serialized. The tool never exports project names, tokens, auth headers,
raw response bodies, log contents, environment values, or error messages.
`duration_ms` measures execution of an API check, not application response time.

The following report is **synthetic**, illustrating one log permission failure;
it is not evidence of authenticated access:

```json
{
  "status": "partial",
  "exit_code": 1,
  "checks": [
    {"capability": "service", "status": "available", "error_code": null, "http_status": null, "checked_at": "2026-10-22T00:00:00Z", "duration_ms": 10.2},
    {"capability": "deployment", "status": "available", "error_code": null, "http_status": null, "checked_at": "2026-10-22T00:00:00Z", "duration_ms": 9.1},
    {"capability": "logs", "status": "permission_denied", "error_code": "AUTHENTICATION_ERROR", "http_status": 403, "checked_at": "2026-10-22T00:00:00Z", "duration_ms": 8.4},
    {"capability": "metrics", "status": "available", "error_code": null, "http_status": null, "checked_at": "2026-10-22T00:00:00Z", "duration_ms": 7.3},
    {"capability": "releases", "status": "available", "error_code": null, "http_status": null, "checked_at": "2026-10-22T00:00:00Z", "duration_ms": 8.8}
  ]
}
```

| Exit code | Meaning |
| --- | --- |
| `0` | Every attempted check returned available data; an intentionally skipped log check does not prevent success. |
| `1` | Partial result: at least one check is available and at least one attempted check failed or returned unavailable data. |
| `2` | No attempted check returned available data, or client initialization/output failed. |
| `3` | Missing/invalid environment configuration or unsupported command-line arguments; no network request is made. |
| `130` | Operator interrupted the run; a fixed interrupted report replaces the incomplete report. |

Per-check states are `available`, `authentication_failed` (401),
`permission_denied` (403), `not_found` (404), `unavailable`, `skipped`, and
`failed`. HTTP status is `null` for successful results because the existing
adapter does not expose successful transport status; the tool does not invent
a 200. Unavailable means `success=True, data=None`; an empty log list or a false
deployment flag is still available data. Skipped logs have null duration/error/
HTTP status, with a timestamp recording the skip decision.

Structured provider error codes are allowlisted. Unknown codes become
`PROVIDER_ERROR`; inconsistent client results become `INVALID_CLIENT_RESULT`;
unexpected per-check exceptions become `UNEXPECTED_ERROR` and later checks
continue. A mock-labelled result becomes `MOCK_RESULT` and cannot pass as live
evidence. Bootstrap failures have a fixed top-level error code and empty checks.
A closed output pipe returns code 2 without emitting an exception diagnostic.

Access results apply only to the configured account/project and the reported
check instants. A 403/404 does not establish that Liara lacks the capability;
available API data does not establish application health. This tool neither
interprets metric units nor updates the capability report automatically. Review
actual run evidence before documenting a live verification claim.

## Draft diagnosis handoff

`TriageAdapter`, `TriageHandoff` and `TriageSnapshot` now provide a provider-local
projection to the team's draft `ServiceSnapshot`, without importing triage or
adding framework dependencies. See [TRIAGE_HANDOFF.md](TRIAGE_HANDOFF.md) for the
pinned contract revision, field mapping, optional compatibility QA and live blockers.

```python
from provider import MockLiaraClient, TriageAdapter

result = TriageAdapter(MockLiaraClient()).collect(
    "mock-project", service_id="MOCK-service",
)
if result.data is not None:
    request = result.data.snapshot.to_request()  # Only this dict fits /diagnose.
    sidecar = result.data.to_dict()  # Preserve errors, availability and limits.
```

Provide a trusted opaque service binding explicitly; no project-to-internal-ID
mapping is assumed. Health remains `unknown`; unverified normalized metrics,
app HTTP/response time and source timestamp remain null. Nonempty logs require
a trusted application-specific sanitizer; they are withheld by default. Empty
collected logs remain `[]`, unavailable/withheld logs remain null. Partial
collection retains its handoff even when `result.success` is false.

Generate the reproducible, clearly **mock** JSON request offline:

```powershell
python -B -m provider.examples.triage_handoff
```

The adapter does not call triage, consume approval, or execute operations. Real
account/service access and a sanitized real sample remain pending environment
credentials; offline compatibility does not constitute live verification.

## Experimental collection context (Draft v0.2)

An opt-in provider-local proposal now pairs the unchanged snapshot with
`collection_context`. It preserves per-capability errors/retry hints, collector
times, limitations and log export counts. Trusted bindings select the exact
project/client scope; a retained `PreparedCollection` checks the entire submitted
snapshot/context against backend state. Digests are not authentication or approval.

See [COLLECTION_CONTEXT_DRAFT.md](COLLECTION_CONTEXT_DRAFT.md) for the proposed
fields, trust boundary, seven synthetic fixtures and executed Setup/Task 05A QA.
The existing endpoint still accepts only `ServiceSnapshot`; this new envelope
is not sent anywhere automatically and has no implemented HTTP consumer.

```powershell
python -B -m provider.examples.context_demo --mock
```

This explicit offline demo prints a synthetic partial-failure envelope and needs
no token. Previous snapshot/sidecar wire shapes remain unchanged. Shared Task 05B
adoption, endpoint decisions, real credentials and live verification remain pending.
