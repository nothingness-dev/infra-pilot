"""Environment-only read settings shared by explicit live entry points.

Validation performs no I/O. This module and Provider remain standard-library-only.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from .models import ProviderConfig
from .observability import _service_path


@dataclass(frozen=True)
class LiveSettings:
    config: ProviderConfig
    project: str = field(repr=False)
    logs_since: str | None = field(repr=False)


def read_live_settings(environment: Mapping[str, str]) -> LiveSettings:
    """Validate all existing smoke settings before constructing a transport."""
    try:
        return _read_live_settings(environment)
    except Exception:
        raise ValueError("Invalid live provider settings.") from None


def _read_live_settings(environment):
    project = environment.get("LIARA_PROJECT_NAME")
    _service_path(project)
    since = environment.get("LIARA_LOGS_SINCE")
    if since is not None:
        if not isinstance(since, str) or not since.strip():
            raise ValueError("Invalid log window setting.") from None
        try:
            since.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid log window setting.") from None
    options = {}
    if "LIARA_API_BASE_URL" in environment:
        options["base_url"] = environment["LIARA_API_BASE_URL"]
    if "LIARA_TIMEOUT_SECONDS" in environment:
        try:
            options["timeout"] = float(environment["LIARA_TIMEOUT_SECONDS"])
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid timeout setting.") from None
    return LiveSettings(ProviderConfig(api_key=environment.get("LIARA_API_TOKEN"), **options), project, since)
