"""Liara HTTP client using only Python's standard library."""

import errno
import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

from .exceptions import (
    ApiUnavailableError, AuthenticationError, InvalidRequestError,
    InvalidResponseError, LiaraProviderException, NetworkError, RateLimitError,
    ResourceNotFoundError, TimeoutError,
)
from .models import ProviderConfig, ProviderResult, ProviderStatus


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib otherwise forwards Authorization on redirects, even off-origin.
        return None


def _http_exception(status: int) -> LiaraProviderException:
    exception_type = LiaraProviderException
    if status in (401, 403):
        exception_type = AuthenticationError
    elif status == 429:
        exception_type = RateLimitError
    elif status == 404:
        exception_type = ResourceNotFoundError
    elif 500 <= status <= 599:
        exception_type = ApiUnavailableError
    elif status == 408:
        exception_type = TimeoutError
    return exception_type(http_status=status)


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-finite JSON numbers are not supported.")


class LiaraClient:
    """Read-only public adapter. Network failures are results, never raw errors."""

    MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    def __init__(self, config: ProviderConfig) -> None:
        if not isinstance(config, ProviderConfig):
            raise ValueError("config must be a ProviderConfig.")
        self.config = config
        if config.is_mock:
            raise ValueError("Mock transport is not available in this adapter stage.")
        # Do not change urllib's process-global opener.
        self._opener = urllib.request.build_opener(_NoRedirects())

    def ping(self) -> ProviderResult[ProviderStatus]:
        """Check project access and report UTC time and monotonic latency.

        The projects endpoint does not supply account identity, so email is None.
        A failed ping still includes a disconnected status alongside its error.
        """
        started = time.perf_counter()
        projects = self.list_projects()
        status = ProviderStatus(
            connected=projects.success,
            latency_ms=max(0.0, (time.perf_counter() - started) * 1000),
            account_email=None,
            is_mock=self.config.is_mock,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        return ProviderResult(projects.success, status, projects.error, self.config.is_mock)

    def list_projects(self) -> ProviderResult[list[dict[str, Any]]]:
        """Normalize Liara's {projects: [...]} envelope to a list of objects."""
        result = self._request("GET", "/v1/projects")
        if not result.success:
            return result
        projects = result.data.get("projects") if isinstance(result.data, dict) else result.data
        if not isinstance(projects, list) or any(not isinstance(p, dict) for p in projects):
            return self._failure(InvalidResponseError())
        return ProviderResult(True, projects, is_mock=self.config.is_mock)

    def _failure(self, error: LiaraProviderException) -> ProviderResult:
        return ProviderResult(False, error=error.to_error(), is_mock=self.config.is_mock)

    def _redact(self, value: Any) -> Any:
        """Remove an echoed API key even from decoded nested response values/keys."""
        token = self.config.api_key.get_secret_value()
        if isinstance(value, str):
            return value.replace(token, "**********") if token else value
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value

    def _request(
        self, method: str, endpoint: str,
        params: Mapping[str, Any] | None = None, payload: Any = None,
    ) -> ProviderResult:
        """Send JSON to a relative endpoint; never log headers or raw errors.

        Requests stay on the configured HTTPS base URL; no redirects or retries.
        timeout applies to socket operations, not a total wall-clock deadline.
        """
        try:
            if not isinstance(method, str) or method.upper() not in {
                "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
            }:
                return self._failure(InvalidRequestError())
            if not isinstance(endpoint, str):
                return self._failure(InvalidRequestError())
            parts = urlsplit(endpoint)
            if (
                not endpoint.startswith("/") or endpoint.startswith("//")
                or parts.scheme or parts.netloc or "?" in endpoint or "#" in endpoint
                or "\\" in endpoint or any(not 33 <= ord(c) <= 126 for c in endpoint)
                or (params is not None and not isinstance(params, Mapping))
            ):
                return self._failure(InvalidRequestError())
            query = urlencode(params, doseq=True) if params else ""
            body = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
            request = urllib.request.Request(
                self.config.base_url + endpoint + ("?" + query if query else ""),
                data=body, method=method.upper(),
                headers={"Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})},
            )
            # An unredirected header provides additional protection if the opener changes.
            request.add_unredirected_header(
                "Authorization", "Bearer " + self.config.api_key.get_secret_value(),
            )
        except (TypeError, ValueError, RecursionError):
            return self._failure(InvalidRequestError())
        try:
            with self._opener.open(request, timeout=self.config.timeout) as response:
                status = response.status
                if not 200 <= status < 300:
                    return self._failure(_http_exception(status))
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
                if len(raw) > self.MAX_RESPONSE_BYTES:
                    return self._failure(InvalidResponseError())
                if not raw and status in (204, 205):
                    return ProviderResult(True, is_mock=False)
                data = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
                return ProviderResult(True, self._redact(data), is_mock=False)
        except urllib.error.HTTPError as error:
            # Deliberately do not read the remote error body or stringify the error.
            try:
                error.close()
            except OSError:
                pass
            return self._failure(_http_exception(error.code))
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, socket.timeout) or (
                isinstance(reason, OSError) and reason.errno == errno.ETIMEDOUT
            ):
                return self._failure(TimeoutError())
            return self._failure(NetworkError())
        except socket.timeout:
            return self._failure(TimeoutError())
        except OSError as error:
            return self._failure(TimeoutError() if error.errno == errno.ETIMEDOUT else NetworkError())
        except OverflowError:
            return self._failure(InvalidRequestError())
        except (http.client.HTTPException, ValueError, RecursionError):
            return self._failure(InvalidResponseError())


# Both names appear in the task and are supported as the same public API.
LiaraApiClient = LiaraClient
