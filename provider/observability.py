"""Read-only observations from documented Liara PaaS endpoints.

These local models intentionally preserve native status strings, timestamps,
metric values and unknown units. They do not infer application health.
"""

import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from .exceptions import InvalidRequestError, InvalidResponseError
from .models import (
    DeploymentStatus, DiskUsage, MetricSeries, MetricsSummary, Observation,
    ProviderResult, Release, ReleasePage, ServiceDetails, ServiceLog,
    ServiceObservations, StructuredError,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _service_path(name: str) -> str:
    if (
        not isinstance(name, str) or not name.strip() or name in (".", "..")
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise ValueError("Invalid service name.")
    return "/v1/projects/" + quote(name, safe="")


def _optional(data: dict, key: str, expected: type) -> Any:
    value = data.get(key)
    if value is not None and type(value) is not expected:
        raise ValueError("Unexpected provider field type.")
    return value


def _number(data: dict, key: str) -> int | float | None:
    value = data.get(key)
    if value is not None and (
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
    ):
        raise ValueError("Invalid provider count.")
    return value


def _series(data: dict, key: str) -> tuple[MetricSeries, ...] | None:
    items = _optional(data, key, list)
    if items is None:
        return None
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid metric series.")
        values = _optional(item, "value", list)
        if values is not None and any(
            type(value) not in (int, float, str)
            or (type(value) is float and not math.isfinite(value)) for value in values
        ):
            raise ValueError("Invalid metric values.")
        result.append(MetricSeries(_optional(item, "applet", str), None if values is None else tuple(values)))
    return tuple(result)


class ObservabilityMixin:
    """Public observation methods sharing LiaraClient's protected transport."""

    def _observe_request(self, name, suffix, parser, *, params=None) -> ProviderResult:
        try:
            endpoint = _service_path(name) + suffix
        except ValueError:
            return self._failure(InvalidRequestError())
        result = self._request("GET", endpoint, params=params)
        if not result.success or result.data is None:
            return result
        try:
            data = parser(result.data)
        except (ValueError, TypeError, OverflowError):
            return self._failure(InvalidResponseError())
        return ProviderResult(True, data, is_mock=self.config.is_mock)

    def get_service(self, name: str) -> ProviderResult[ServiceDetails]:
        """Read selected project fields; omit envs and other unrestricted data."""
        def parse(data):
            if not isinstance(data, dict) or "project" not in data:
                raise ValueError("Missing project envelope.")
            project = _optional(data, "project", dict)
            if project is None:
                return None
            reported_name = _optional(project, "project_id", str)
            if reported_name is not None and reported_name != self._redact(name):
                raise ValueError("Response belongs to a different service.")
            values = (
                _optional(project, "_id", str), _optional(project, "type", str),
                _optional(project, "status", str), _optional(project, "isDeployed", bool),
            )
            if all(value is None for value in values):
                return None
            return ServiceDetails(self._redact(name), *values)
        return self._observe_request(name, "", parse)

    def get_deployment_status(self, name: str) -> ProviderResult[DeploymentStatus]:
        """Return the native project deployment flag/status, not inferred health."""
        return self._deployment_from_service(self.get_service(name))

    def _deployment_from_service(self, result: ProviderResult) -> ProviderResult:
        if not result.success or result.data is None:
            return result
        service = result.data
        data = None
        if service.is_deployed is not None or service.native_status is not None:
            data = DeploymentStatus(service.service_name, service.is_deployed, service.native_status)
        return ProviderResult(True, data, is_mock=self.config.is_mock)

    def get_logs(self, name: str, *, since: str) -> ProviderResult[list[ServiceLog]]:
        """Pass an explicit timestamp string as the required opaque since query."""
        if not isinstance(since, str) or not since.strip():
            return self._failure(InvalidRequestError())
        def parse(data):
            if not isinstance(data, list):
                raise ValueError("Expected a log array.")
            logs = []
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("Invalid log entry.")
                logs.append(ServiceLog(
                    _optional(item, "message", str), _optional(item, "type", str),
                    _optional(item, "datetime", str),
                ))
            return logs
        return self._observe_request(name, "/logs", parse, params={"since": since})

    def get_metrics(self, name: str) -> ProviderResult[MetricsSummary]:
        """Read summary series with unknown units; never convert to CPU % or MiB."""
        def parse(data):
            if not isinstance(data, dict):
                raise ValueError("Expected metrics object.")
            cpu, memory = _series(data, "cpuUsage"), _series(data, "memoryUsage")
            disk_items = _optional(data, "disksUsage", list)
            disks = None
            if disk_items is not None:
                disks = []
                for item in disk_items:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid disk observation.")
                    disks.append(DiskUsage(*(
                        _optional(item, key, str) for key in ("name", "size", "usage", "reportedAt")
                    )))
                disks = tuple(disks)
            if cpu is None and memory is None and disks is None:
                return None
            return MetricsSummary(cpu, memory, disks)
        return self._observe_request(name, "/metrics/summary", parse)

    def list_releases(self, name: str, *, page: int = 1, count: int = 10) -> ProviderResult[ReleasePage]:
        """Read exactly one release page. Preserve opaque states; do not sort."""
        if type(page) is not int or page < 1 or type(count) is not int or count < 1:
            return self._failure(InvalidRequestError())
        def parse(data):
            if not isinstance(data, dict):
                raise ValueError("Expected release envelope.")
            items = _optional(data, "releases", list)
            releases = None
            if items is not None:
                releases = []
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid release.")
                    releases.append(Release(*(_optional(item, key, str) for key in (
                        "_id", "state", "createdAt", "finishedAt", "tag",
                    ))))
                releases = tuple(releases)
            total = _number(data, "total")
            current = _optional(data, "currentRelease", str)
            ready = _number(data, "readyReleasesCount")
            if releases is None and total is None and current is None and ready is None:
                return None
            return ReleasePage(releases, total, current, ready, page, count)
        return self._observe_request(name, "/releases", parse, params={"page": page, "count": count})

    def _observation(self, result: ProviderResult, collected_at: str) -> Observation:
        state = "available"
        if not result.success:
            status = result.error.http_status if result.error else None
            state = {
                401: "authentication_failed", 403: "permission_denied", 404: "not_found",
            }.get(status, "failed")
        elif result.data is None:
            state = "unavailable"
        return Observation(state, result.data, result.error, self.config.is_mock, collected_at)

    def collect_service_observations(
        self, name: str, *, logs_since: str | None = None, include_metrics: bool = True,
    ) -> ProviderResult[ServiceObservations]:
        """Collect up to three independent GETs, preserving each partial result.

        No releases are implicitly paged. Deployment data shares the service
        response. Logs are not requested unless since is explicitly supplied.
        """
        try:
            _service_path(name)
            if type(include_metrics) is not bool or (
                logs_since is not None and (not isinstance(logs_since, str) or not logs_since.strip())
            ):
                raise ValueError("Invalid collection options.")
        except ValueError:
            return self._failure(InvalidRequestError())
        started = _utc_now()
        service_result = self.get_service(name)
        service = self._observation(service_result, _utc_now())
        deployment = self._observation(self._deployment_from_service(service_result), service.collected_at)
        logs = Observation("not_collected", None, None, self.config.is_mock, None)
        if logs_since is not None:
            logs = self._observation(self.get_logs(name, since=logs_since), _utc_now())
        metrics = Observation("not_collected", None, None, self.config.is_mock, None)
        if include_metrics:
            metrics = self._observation(self.get_metrics(name), _utc_now())
        data = ServiceObservations(
            self._redact(name), started, _utc_now(), self.config.is_mock,
            service, deployment, logs, metrics, self._redact(logs_since),
        )
        requested = [item for item in (service, deployment, logs, metrics) if item.availability != "not_collected"]
        if all(item.availability == "available" for item in requested):
            return ProviderResult(True, data, is_mock=self.config.is_mock)
        partial = any(item.availability == "available" for item in requested)
        error = StructuredError(
            "PARTIAL_COLLECTION" if partial else "COLLECTION_FAILED",
            "Some requested observations are unavailable." if partial else "No requested observations are available.",
            None, any(item.error is not None and item.error.retryable for item in requested),
        )
        return ProviderResult(False, data, error, self.config.is_mock)
