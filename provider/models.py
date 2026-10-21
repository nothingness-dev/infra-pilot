"""Provider-local contracts with safe credential representations."""

from dataclasses import dataclass, field
import math
from typing import Any, Generic, TypeVar
from urllib.parse import urlsplit


class SecretStr:
    """An opaque secret; disclosure requires an explicit get_secret_value call.

    Deliberately not a str subclass or dataclass: formatting and dataclass
    conversion of a containing config must not unwrap the underlying value.
    """

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if hasattr(self, "_SecretStr__value"):
            raise AttributeError("SecretStr is immutable.")
        if not isinstance(value, str):
            raise ValueError("The API key must be a string.")
        object.__setattr__(self, "_SecretStr__value", value)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("SecretStr is immutable.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SecretStr is immutable.")

    def get_secret_value(self) -> str:
        return self.__value

    def __str__(self) -> str:
        return "**********"

    def __repr__(self) -> str:
        return "SecretStr('**********')"

    def __copy__(self) -> "SecretStr":
        return self

    def __deepcopy__(self, memo: dict) -> "SecretStr":
        return self


@dataclass(frozen=True)
class ProviderConfig:
    """Validated configuration. Plain string API keys are wrapped on creation."""

    api_key: str | SecretStr
    base_url: str = field(default="https://api.iran.liara.ir", repr=False)
    timeout: float = 10.0
    is_mock: bool = False

    def __post_init__(self) -> None:
        if type(self.is_mock) is not bool:
            raise ValueError("is_mock must be a boolean.")
        secret = self.api_key if isinstance(self.api_key, SecretStr) else SecretStr(self.api_key)
        token = secret.get_secret_value()
        # Reject header injection, whitespace and values urllib cannot encode.
        if (not token and not self.is_mock) or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError("The API key must be a nonblank, printable ASCII token.")
        object.__setattr__(self, "api_key", secret)
        try:
            valid_timeout = (
                type(self.timeout) in (int, float)
                and math.isfinite(self.timeout) and self.timeout > 0
            )
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise ValueError("timeout must be a positive, finite number of seconds.")
        valid_url = False
        if isinstance(self.base_url, str):
            try:
                parts = urlsplit(self.base_url)
                valid_url = (
                    parts.scheme == "https" and bool(parts.hostname)
                    and parts.username is None and parts.password is None
                    and not parts.query and not parts.fragment
                    and "?" not in self.base_url and "#" not in self.base_url
                    and "\\" not in self.base_url
                    and all(33 <= ord(c) <= 126 for c in self.base_url)
                    and (parts.port is None or 0 < parts.port <= 65535)
                )
            except ValueError:
                pass
        if not valid_url:
            raise ValueError("base_url must be an HTTPS URL without credentials, query or fragment.")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    def to_dict(self) -> dict[str, Any]:
        """Return safe diagnostic configuration; never serialize the raw token."""
        token = self.api_key.get_secret_value()
        return {
            "api_key": str(self.api_key),
            "base_url": self.base_url.replace(token, "**********") if token else self.base_url,
            "timeout": self.timeout,
            "is_mock": self.is_mock,
        }


@dataclass(frozen=True)
class ProviderStatus:
    connected: bool
    latency_ms: float
    account_email: str | None
    is_mock: bool
    timestamp: str


@dataclass(frozen=True)
class StructuredError:
    code: str
    message: str
    http_status: int | None
    retryable: bool


T = TypeVar("T")


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    success: bool
    data: T | None = None
    error: StructuredError | None = None
    is_mock: bool = False
