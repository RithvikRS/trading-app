"""Dedicated cross-site callback; all remaining connector routes stay same-origin."""

import re
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, SecretStr
from starlette.responses import JSONResponse, RedirectResponse, Response

from trading_api.authentication import CookiePolicy
from trading_connectors.indmoney_models import PREFIX, ConnectorRejected, ConnectorUnavailable
from trading_connectors.indmoney_service import IndmoneyService

CALLBACK_COOKIE = "__Host-portfolio-indmoney"


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


def callback_values(
    request: Request, policy: CookiePolicy
) -> tuple[str, str, SecretStr | None, str | None]:
    try:
        headers = request.headers
        cookies = ";".join(headers.getlist("cookie"))
        raw = request.scope.get("query_string", b"")
        if (
            request.method != "GET"
            or str(request.base_url).rstrip("/") != policy.origin
            or not policy.secure
            or not 1 <= len(raw) <= 8192
            or any(
                len(headers.getlist(name)) > 1
                for name in ("host", "origin", "content-length", "sec-fetch-mode", "sec-fetch-dest")
            )
            or "authorization" in headers
            or "content-encoding" in headers
            or headers.get("content-length", "0") != "0"
            or "transfer-encoding" in headers
            or ("sec-fetch-mode" in headers and headers["sec-fetch-mode"] != "navigate")
            or ("sec-fetch-dest" in headers and headers["sec-fetch-dest"] != "document")
            or sum(part.strip().split("=", 1)[0] == CALLBACK_COOKIE for part in cookies.split(";"))
            != 1
        ):
            raise ValueError()
        query = raw.decode("ascii")
        if re.search(r"%(?![0-9A-Fa-f]{2})", query):
            raise ValueError()
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=6,
        )
        values = dict(pairs)
        if len(values) != len(pairs) or not set(values) <= {
            "state",
            "code",
            "iss",
            "error",
            "error_description",
            "error_uri",
        }:
            raise ValueError()
        state, binding = values.get("state", ""), request.cookies.get(CALLBACK_COOKIE, "")
        if any(re.fullmatch(r"[A-Za-z0-9_-]{43}", v, re.ASCII) is None for v in (state, binding)):
            raise ValueError()
        if ("code" in values) == ("error" in values) or any(
            not 1 <= len(v) <= 2048 or any(ord(c) < 32 or ord(c) > 126 for c in v)
            for v in values.values()
        ):
            raise ValueError()
        if "code" in values and ("error_description" in values or "error_uri" in values):
            raise ValueError()
        return (
            state,
            binding,
            SecretStr(values["code"]) if "code" in values else None,
            values.get("iss"),
        )
    except ValueError, UnicodeError:
        raise ConnectorRejected() from None


def routes(service: IndmoneyService, policy: CookiePolicy) -> APIRouter:
    if not policy.secure or policy.origin != "https://127.0.0.1:8443":
        raise ConnectorUnavailable()
    router = APIRouter(prefix=PREFIX)

    def inputs(request: Request) -> tuple[str, str, str, str]:
        return (
            request.cookies.get(policy.session, ""),
            request.headers.get("x-csrftoken", ""),
            request.headers.get("x-workspace-context", ""),
            request.state.request_id,
        )

    @router.get("")
    def status(request: Request) -> dict[str, str | bool | None]:
        return service.status(*inputs(request))

    @router.post("/authorize")
    def authorize(body: EmptyInput, request: Request) -> Response:
        url, binding = service.begin(*inputs(request))
        response = JSONResponse({"authorization_url": url})
        response.set_cookie(
            CALLBACK_COOKIE,
            binding,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=300,
        )
        return response

    @router.get("/callback")
    def callback(request: Request) -> Response:
        try:
            state, binding, code, issuer = callback_values(request, policy)
            service.store.receive(state, binding, code, issuer, request.state.request_id)
        except Exception:
            # Every callback leaves the credential-bearing URL through the same fixed redirect.
            # No query data or provider error text reaches the response or logs.
            pass
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(
            CALLBACK_COOKIE, secure=True, httponly=True, samesite="lax", path="/"
        )
        return response

    @router.post("/complete")
    def complete(body: EmptyInput, request: Request) -> dict[str, str]:
        service.complete(*inputs(request))
        return {"status": "authorized"}

    @router.post("/refresh")
    def refresh(body: EmptyInput, request: Request) -> dict[str, str]:
        service.complete(*inputs(request), refresh=True)
        return {"status": "authorized"}

    @router.post("/disconnect")
    def disconnect(body: EmptyInput, request: Request) -> dict[str, str]:
        return service.disconnect(*inputs(request))

    return router
