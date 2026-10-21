"""Typed failures whose messages never incorporate untrusted diagnostics."""

from .models import StructuredError


class LiaraProviderException(Exception):
    """Only fixed messages are retained, even if a caller passes a raw error.

    Remote bodies, URLs, headers and transport exception text may contain
    credentials. Discarding those messages also protects Exception.args/repr.
    Public client methods convert these exceptions to StructuredError values.
    """

    code = "PROVIDER_ERROR"
    default_message = "The provider request failed."
    default_http_status = None
    retryable = False

    def __init__(self, message: str | None = None, *, http_status: int | None = None) -> None:
        status = self.default_http_status if http_status is None else http_status
        self.http_status = status if type(status) is int and 100 <= status <= 599 else None
        super().__init__(self.default_message)

    def to_error(self) -> StructuredError:
        return StructuredError(self.code, self.default_message, self.http_status, self.retryable)


class AuthenticationError(LiaraProviderException):
    code = "AUTHENTICATION_ERROR"
    default_message = "The provider rejected the credentials or access permissions."
    default_http_status = 401


class RateLimitError(LiaraProviderException):
    code = "RATE_LIMITED"
    default_message = "The provider rate limit was reached."
    default_http_status = 429
    retryable = True


class TimeoutError(LiaraProviderException):
    code = "TIMEOUT"
    default_message = "The provider request timed out."
    retryable = True


class ApiUnavailableError(LiaraProviderException):
    code = "API_UNAVAILABLE"
    default_message = "The provider API is temporarily unavailable."
    retryable = True


class ResourceNotFoundError(LiaraProviderException):
    code = "RESOURCE_NOT_FOUND"
    default_message = "The requested provider resource was not found."
    default_http_status = 404


class NetworkError(LiaraProviderException):
    code = "NETWORK_ERROR"
    default_message = "A network connection to the provider could not be completed."
    retryable = True


class InvalidResponseError(LiaraProviderException):
    code = "INVALID_RESPONSE"
    default_message = "The provider returned an invalid or oversized response."


class InvalidRequestError(LiaraProviderException):
    code = "INVALID_REQUEST"
    default_message = "The provider request parameters are invalid."
