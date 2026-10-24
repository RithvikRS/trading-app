"""Same-origin, bounded JSON browser endpoints with framework CSRF protection."""

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette_csrf.middleware import CSRFMiddleware

from trading_auth.browser import BrowserAuth


@dataclass(frozen=True)
class CookiePolicy:
    origin: str
    secure: bool = False

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        target = urlsplit(self.origin)
        if (
            not target.hostname
            or target.path
            or target.query
            or target.fragment
            or target.username
            or target.password
            or (self.secure and target.scheme != "https")
            or (not self.secure and (target.scheme != "http" or target.hostname != "127.0.0.1"))
        ):
            raise ValueError("Invalid browser origin.")

    @property
    def session(self) -> str:
        return "__Host-portfolio-session" if self.secure else "trading_dev_session"

    @property
    def csrf(self) -> str:
        return "__Host-portfolio-csrf" if self.secure else "trading_dev_csrf"

    def set(self, response: Response, value: str) -> None:
        # Session cookie, never a persistent remember-me cookie. Server TTL is authoritative.
        response.set_cookie(
            self.session, value, httponly=True, secure=self.secure, samesite="strict", path="/"
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(
            self.session, httponly=True, secure=self.secure, samesite="strict", path="/"
        )


class SafeCSRF(CSRFMiddleware):
    def _get_error_response(self, request: Request) -> Response:
        from trading_api.application import error_response

        return error_response(403, request.state.request_id)


def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Ambiguous JSON object.")
        values[key] = value
    return values


def reject_nonfinite(value: str) -> None:
    raise ValueError("Invalid JSON constant.")


def finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Invalid JSON number.")
    return result


def validate_financial_json(body: bytearray) -> None:
    document = json.loads(
        body.decode("utf-8"),
        object_pairs_hook=unique_fields,
        parse_constant=reject_nonfinite,
        parse_float=finite_float,
    )
    pending = [(document, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 16:
            raise ValueError("JSON nesting is too deep.")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)


class BrowserBoundary:
    def __init__(self, app: ASGIApp, policy: CookiePolicy, secret: str) -> None:
        self.policy = policy
        self.app = SafeCSRF(
            app,
            secret=secret,
            cookie_name=policy.csrf,
            cookie_secure=policy.secure,
            cookie_samesite="strict",
            safe_methods={"GET", "HEAD", "OPTIONS"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from trading_api.application import error_response

        request = Request(scope)
        financial = request.url.path == "/api/v1/finance" or request.url.path.startswith(
            "/api/v1/finance/"
        )
        if not (
            request.url.path.startswith("/api/v1/auth/")
            or request.url.path == "/api/v1/preferences"
            or request.url.path.startswith("/api/v1/preferences/")
            or financial
        ):
            await self.app(scope, receive, send)
            return
        headers = request.headers
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        invalid = (
            str(request.base_url).rstrip("/") != self.policy.origin
            or bool(scope.get("query_string"))
            or headers.get("sec-fetch-site") in {"cross-site", "same-site"}
            or "authorization" in headers
            or (unsafe and headers.get("origin") != self.policy.origin)
            or ("origin" in headers and headers["origin"] != self.policy.origin)
        )
        for name in ("origin", "host", "content-type", "x-csrftoken", "content-length"):
            invalid = invalid or len(headers.getlist(name)) > 1
        # Reject ambiguous duplicate auth cookies instead of accepting the last one.
        cookies = ";".join(headers.getlist("cookie"))
        for name in (self.policy.session, self.policy.csrf):
            invalid = (
                invalid
                or sum(part.strip().split("=", 1)[0] == name for part in cookies.split(";")) > 1
            )
        if invalid:
            await error_response(403, request.state.request_id)(scope, receive, send)
            return
        if unsafe:
            if (
                headers.get("content-type", "").lower() != "application/json"
                or "content-encoding" in headers
            ):
                await error_response(415, request.state.request_id)(scope, receive, send)
                return
            try:
                body = bytearray()
                async with asyncio.timeout(5):
                    while True:
                        message = await receive()
                        if message["type"] != "http.request":
                            raise ValueError("Incomplete body")
                        body.extend(message.get("body", b""))
                        if len(body) > 4096:
                            await error_response(413, request.state.request_id)(
                                scope, receive, send
                            )
                            return
                        if not message.get("more_body", False):
                            break
                if financial:
                    validate_financial_json(body)
            except TimeoutError, ValueError, RecursionError:
                await error_response(400, request.state.request_id)(scope, receive, send)
                return

            async def buffered() -> Message:
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, buffered, send)
        else:
            await self.app(scope, receive, send)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Login(Input):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)


class Email(Input):
    email: str = Field(min_length=3, max_length=254)


class Recovery(Email):
    code: SecretStr = Field(min_length=6, max_length=10)


class Code(Input):
    code: SecretStr = Field(min_length=6, max_length=6)


class MFA(Code):
    factor_id: Annotated[UUID, Field(strict=False)]


class Password(Input):
    password: SecretStr = Field(min_length=16, max_length=128)


class Factor(Input):
    factor_id: Annotated[UUID, Field(strict=False)]


def routes(service: BrowserAuth, policy: CookiePolicy) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth")

    def context(request: Request) -> tuple[str, str, str]:
        return (
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.state.request_id,
        )

    @router.get("/bootstrap")
    def bootstrap() -> dict[str, str | bool]:
        return {"status": "ready", "recovery_email_enabled": service.recovery_email}

    @router.post("/login")
    def login(body: Login, request: Request) -> Response:
        old, csrf, correlation = context(request)
        if old:
            service.logout(old, csrf, correlation)
        cookie, content = service.start(body.email, body.password, csrf, correlation)
        response = JSONResponse(content)
        policy.set(response, cookie)
        return response

    @router.post("/mfa/verify")
    def mfa(body: MFA, request: Request) -> Response:
        old, csrf, correlation = context(request)
        cookie, content = service.mfa(old, body.factor_id, body.code, csrf, correlation)
        response = JSONResponse(content)
        policy.set(response, cookie)
        return response

    @router.get("/session")
    def session(request: Request) -> dict[str, object]:
        return service.session(*context(request))

    @router.post("/session/activity")
    def activity(body: Input, request: Request) -> dict[str, object]:
        return service.session(*context(request), activity=True)

    @router.post("/logout")
    def logout(body: Input, request: Request) -> Response:
        response = JSONResponse(service.logout(*context(request)))
        policy.clear(response)
        return response

    @router.post("/revoke-all")
    def revoke_all(body: Input, request: Request) -> Response:
        response = JSONResponse(service.logout(*context(request), all_sessions=True))
        policy.clear(response)
        return response

    @router.post("/recovery/request", status_code=202)
    def recovery_request(body: Email, request: Request) -> dict[str, str]:
        service.recovery_request(body.email, request.state.request_id)
        return {"status": "recovery_requested"}

    @router.post("/recovery/verify")
    def recovery_verify(body: Recovery, request: Request) -> Response:
        old, csrf, correlation = context(request)
        if old:
            service.logout(old, csrf, correlation)
        cookie, content = service.start(body.email, body.code, csrf, correlation, recovery=True)
        response = JSONResponse(content)
        policy.set(response, cookie)
        return response

    @router.post("/recovery/password")
    def password(body: Password, request: Request) -> Response:
        old, csrf, correlation = context(request)
        service.password(old, body.password, csrf, correlation)
        response = JSONResponse({"status": "sign_in_required"})
        policy.clear(response)
        return response

    @router.post("/mfa/backup")
    def backup(body: Input, request: Request) -> Response:
        cookie, content = service.backup(*context(request))
        response = JSONResponse(content)
        policy.set(response, cookie)
        return response

    @router.post("/mfa/backup/verify")
    def backup_verify(body: Code, request: Request) -> Response:
        old, csrf, correlation = context(request)
        service.backup_verify(old, body.code, csrf, correlation)
        response = JSONResponse({"status": "sign_in_required"})
        policy.clear(response)
        return response

    @router.post("/mfa/remove")
    def remove(body: Factor, request: Request) -> Response:
        old, csrf, correlation = context(request)
        service.remove(old, body.factor_id, csrf, correlation)
        response = JSONResponse({"status": "sign_in_required"})
        policy.clear(response)
        return response

    return router
