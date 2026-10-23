"""Application factory and the outer HTTP error/header boundary."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from trading_api.authentication import BrowserBoundary, CookiePolicy, routes
from trading_api.config import Settings, load_settings
from trading_auth.browser import BrowserAuth
from trading_auth.models import (
    AuthenticationDenied,
    AuthenticationLimited,
    AuthenticationUnavailable,
)

logger = logging.getLogger("trading_api")
ERROR_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    422: "invalid_request",
    401: "authentication_required",
    403: "request_rejected",
    413: "request_too_large",
    415: "unsupported_content_type",
    429: "try_later",
    503: "authentication_unavailable",
}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def error_response(status: int, request_id: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": ERROR_CODES.get(
                status, "internal_error" if status >= 500 else "request_rejected"
            ),
            "request_id": request_id,
        },
        status_code=status,
    )


class HTTPBoundary:
    """Wrap even framework error responses; never pass exception details to logs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = False
        completed = False
        status = 500

        async def safe_send(message: Message) -> None:
            nonlocal started, completed, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers[key] = value
                headers["X-Request-ID"] = request_id
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True

        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            logger.error("request_failed", extra={"request_id": request_id, "status": status})
            if not started:
                await error_response(500, request_id)(scope, receive, safe_send)
            elif not completed:
                # A partial response cannot be replaced: terminate it without disclosing the cause.
                raise RuntimeError("Response interrupted.") from None
            # Starlette re-raises handled server errors after sending the safe response.
            return

        logger.info("request_completed", extra={"request_id": request_id, "status": status})


def create_app(
    settings: Settings | None = None, *, browser: BrowserAuth | None = None
) -> HTTPBoundary:
    config = load_settings() if settings is None else settings
    # Revalidate injected settings as well as process configuration at startup.
    Settings.model_validate(config.model_dump())
    if config.auth_enabled and browser is None:
        from trading_auth.local import local_browser

        browser = local_browser()
    policy = CookiePolicy(f"http://127.0.0.1:{config.port}")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if browser is not None:
                browser.close()

    api = FastAPI(
        debug=False,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    if browser is not None:
        api.include_router(routes(browser, policy))

    @api.exception_handler(AuthenticationDenied)
    @api.exception_handler(AuthenticationUnavailable)
    async def auth_error(request: Request, exc: Exception) -> JSONResponse:
        status = (
            429
            if isinstance(exc, AuthenticationLimited)
            else 401
            if isinstance(exc, AuthenticationDenied)
            else 503
        )
        response = error_response(status, request.state.request_id)
        if status != 429:
            policy.clear(response)
        if status == 429:
            response.headers["Retry-After"] = "5"
        return response

    @api.get("/api/v1/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @api.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        response = error_response(exc.status_code, request.state.request_id)
        if exc.status_code == 405 and exc.headers and "Allow" in exc.headers:
            response.headers["Allow"] = exc.headers["Allow"]
        return response

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, request.state.request_id)

    @api.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> JSONResponse:
        return error_response(500, request.state.request_id)

    app: ASGIApp = api
    if browser is not None:
        app = BrowserBoundary(app, policy, browser.vault.csrf_secret)
    return HTTPBoundary(
        TrustedHostMiddleware(
            app,
            allowed_hosts=["127.0.0.1", "localhost"],
            www_redirect=False,
        )
    )
