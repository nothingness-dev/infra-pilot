"""Module-local INTERNAL DRAFT HTTP API. No executor, login, or provider calls."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import engine
from .api_contracts import (
    AuthorizationRequest, ErrorCode, ErrorDetail, ErrorResponse, HealthResponse, PolicyEvaluationResponse,
)
from .approval_integration import ApprovalIntegration
from .approvals import DecisionReason, GateDecision
from .policy import ActionIntent
from .redaction import sanitize_snapshot
from .schemas import DiagnosisReport, ServiceSnapshot


# A trusted resolver verifies credentials/middleware context. It must not accept
# X-User, roles, body actor IDs, or other unverified claims as identity.
TrustedAuthenticationResolver = Callable[[Request], object | None]

_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION: "Request does not match the required schema.",
    ErrorCode.INTERNAL: "The triage API could not process the request.",
    ErrorCode.AUTHENTICATION_UNAVAILABLE: "Trusted authentication is not configured or is unavailable.",
    ErrorCode.AUTHENTICATION_REQUIRED: "Verified authentication is required.",
    ErrorCode.APPROVAL_UNAVAILABLE: "The trusted approval integration is not configured.",
    ErrorCode.NOT_FOUND: "Route not found.",
    ErrorCode.METHOD_NOT_ALLOWED: "Method not allowed.",
    ErrorCode.HTTP: "The HTTP request could not be processed.",
}


def _error_response(status: int, code: ErrorCode) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=_MESSAGES[code]))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


class _ApiFailure(Exception):
    def __init__(self, status: int, code: ErrorCode) -> None:
        self.status = status
        self.code = code


class _SafeJsonResponses:
    """Buffer this non-streaming JSON API so failures cannot leak partial output.

    Catch before ServerErrorMiddleware can re-raise raw exception text to a server
    logger. No request bodies, credentials, exception strings, or tracebacks log.
    Streaming/background-response APIs are deliberately outside this application.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []

        async def collect(message: Message) -> None:
            messages.append(message)

        try:
            await self.app(scope, receive, collect)
        except Exception:
            await _error_response(500, ErrorCode.INTERNAL)(scope, receive, send)
            return
        for message in messages:
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", []) if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)


def get_approval_integration(request: Request) -> ApprovalIntegration:
    integration = request.app.state.approval_integration
    if not isinstance(integration, ApprovalIntegration):
        raise _ApiFailure(503, ErrorCode.APPROVAL_UNAVAILABLE)
    return integration


def get_trusted_authentication(request: Request) -> object:
    resolver = request.app.state.authentication_resolver
    if resolver is None:
        raise _ApiFailure(503, ErrorCode.AUTHENTICATION_UNAVAILABLE)
    try:
        context = resolver(request)
    except Exception:
        raise _ApiFailure(503, ErrorCode.AUTHENTICATION_UNAVAILABLE) from None
    if context is None:
        raise _ApiFailure(401, ErrorCode.AUTHENTICATION_REQUIRED)
    return context


_UNAVAILABLE_REASONS = {
    DecisionReason.IDENTITY_UNAVAILABLE, DecisionReason.AUTHORIZATION_UNAVAILABLE,
    DecisionReason.POLICY_UNAVAILABLE, DecisionReason.STORAGE_UNAVAILABLE, DecisionReason.CLOCK_UNAVAILABLE,
}


def create_app(
    *, approval_integration: ApprovalIntegration | None = None,
    authentication_resolver: TrustedAuthenticationResolver | None = None,
) -> FastAPI:
    """Build an isolated app; privileged HTTP checks are disabled by default."""
    application = FastAPI(
        title="InfraPilot internal triage API", version="0.1.0", debug=False,
        description="INTERNAL DRAFT v0.1. Not official Liara endpoints. No infrastructure execution.",
        docs_url=None, redoc_url=None,
    )
    application.state.approval_integration = approval_integration
    application.state.authentication_resolver = authentication_resolver
    application.add_middleware(_SafeJsonResponses)

    @application.exception_handler(_ApiFailure)
    async def failure_handler(_request: Request, error: _ApiFailure) -> JSONResponse:
        return _error_response(error.status, error.code)

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, _error: RequestValidationError) -> JSONResponse:
        # Omit input, locations, exception context, and validator messages: each
        # may contain untrusted credentials. OpenAPI supplies field definitions.
        return _error_response(422, ErrorCode.VALIDATION)

    @application.exception_handler(ResponseValidationError)
    async def response_handler(_request: Request, _error: ResponseValidationError) -> JSONResponse:
        return _error_response(500, ErrorCode.INTERNAL)

    @application.exception_handler(HTTPException)
    async def http_handler(_request: Request, error: HTTPException) -> JSONResponse:
        code = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.METHOD_NOT_ALLOWED}.get(error.status_code, ErrorCode.HTTP)
        return _error_response(error.status_code, code)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @application.post(
        "/internal/triage/diagnose", response_model=DiagnosisReport,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def diagnose_snapshot(snapshot: ServiceSnapshot) -> DiagnosisReport:
        sanitized, redacted = sanitize_snapshot(snapshot)
        report = engine.diagnose(sanitized)
        if redacted:
            report.limitations.append("The API redacted recognizable credential values from supplied logs before diagnosis.")
        return report

    @application.post(
        "/internal/triage/policy/evaluate", response_model=PolicyEvaluationResponse,
        responses={
            401: {"model": ErrorResponse}, 403: {"model": PolicyEvaluationResponse},
            422: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
            503: {"model": PolicyEvaluationResponse | ErrorResponse},
        },
    )
    def evaluate_policy(
        intent: ActionIntent, response: Response,
        integration: Annotated[ApprovalIntegration, Depends(get_approval_integration)],
        _authentication: Annotated[object, Depends(get_trusted_authentication)],
    ) -> PolicyEvaluationResponse:
        result = integration.evaluate(intent)
        if not result.policy.allowed:
            response.status_code = 503 if result.policy.reason == "policy_unavailable" else 403
        return result

    @application.post(
        "/internal/triage/authorize", response_model=GateDecision,
        responses={
            401: {"model": GateDecision | ErrorResponse}, 403: {"model": GateDecision},
            422: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
            503: {"model": GateDecision | ErrorResponse},
        },
    )
    def authorize_action(
        body: AuthorizationRequest, response: Response,
        integration: Annotated[ApprovalIntegration, Depends(get_approval_integration)],
        authentication: Annotated[object, Depends(get_trusted_authentication)],
    ) -> GateDecision:
        result = integration.authorize(
            body.intent, authentication=authentication, approval_request_id=body.approval_request_id,
        )
        if not result.allowed:
            if result.reason in _UNAVAILABLE_REASONS:
                response.status_code = 503
            else:
                response.status_code = 401 if result.reason == DecisionReason.UNAUTHENTICATED else 403
        return result

    return application


app = create_app()
