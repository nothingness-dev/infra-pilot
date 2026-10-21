# Liara provider adapter and authentication layer

Roham owns this isolated `provider/` package for InfraPilot. It uses **Python
3.10+ and the standard library only**. No installation, framework, credentials,
or network access is required to run its tests. Package markers are named
`__init__.py` (Python's import/discovery convention), rather than `init.py`.

The public API checks connection/authentication and lists projects. It does not
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

`ProviderConfig` is frozen. It accepts a plain string token and immediately
wraps it in `SecretStr`. A live token must be nonempty, printable ASCII without
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

`MockLiaraClient(config=None, *, failure_mode=None)` always forces mock mode on
a copied config, even when given a live config. It never constructs an HTTP
opener or opens a socket. Every result, including errors, has `is_mock=True`.
Fixtures are fresh on each call; caller mutations do not affect later calls.

Supported modes: `None` (normal), `"empty"`, `"timeout"`, `"unauthorized"` (401),
`"forbidden"` (403), `"rate_limit"` (429), `"not_found"` (404), `"unavailable"`
(503), or any integer HTTP error status from 400 through 599. Unknown modes
raise a safe `ValueError`. Empty means a valid account with zero projects,
and still produces a successful connection check.

## Result contracts for integration

All models live in `provider.models` and are also exported by `provider`.

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
and reads are limited to 4 MiB plus one byte for overflow detection. Empty 200,
non-finite JSON values and malformed project shapes are rejected. The internal
transport supports JSON payloads and URL-encoded query parameters for future
adapters; only `ping()` and `list_projects()` are public provider operations.

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
- Exact occurrences of the configured token in decoded success data, including
  nested values and dictionary keys, are redacted before results are returned.
- TLS verification uses urllib's default HTTPS behavior. Redirects are blocked,
  and Authorization is also registered as an unredirected header. No global
  urllib opener is installed or modified.
