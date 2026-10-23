import asyncio
import secrets

import pytest
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from trading_api.application import HTTPBoundary
from trading_api.authentication import BrowserBoundary, CookiePolicy

ORIGIN = "http://127.0.0.1:8000"
PATH = "/api/v1/auth/login"


@pytest.fixture
def boundary():
    called = []

    async def endpoint(scope, receive, send):
        called.append(scope["path"])
        await JSONResponse({"status": "ok"})(scope, receive, send)

    app = HTTPBoundary(BrowserBoundary(endpoint, CookiePolicy(ORIGIN), secrets.token_hex(32)))
    client = TestClient(app, base_url=ORIGIN)
    client.get("/api/v1/auth/bootstrap")
    called.clear()
    yield client, called
    client.close()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "TRACE"])
def test_every_unsafe_method_requires_csrf_even_without_session(boundary, method):
    client, called = boundary
    response = client.request(method, PATH, json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 403 and not called
    assert response.json()["error"] == "request_rejected"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "origin", [None, "null", "https://attacker.invalid", "http://localhost:8000", ORIGIN + "/"]
)
def test_csrf_token_alone_never_bypasses_exact_origin(boundary, origin):
    client, called = boundary
    headers = {"X-CSRFToken": client.cookies["trading_dev_csrf"]}
    if origin is not None:
        headers["Origin"] = origin
    assert client.post(PATH, json={}, headers=headers).status_code == 403
    assert not called


@pytest.mark.parametrize(
    "change",
    [
        "csrf_tamper",
        "bearer",
        "same_site",
        "cross_site",
        "query",
        "duplicate_origin",
        "duplicate_cookie",
    ],
)
def test_ambiguous_or_cross_site_authentication_never_reaches_service(boundary, change):
    client, called = boundary
    headers = [("Origin", ORIGIN), ("X-CSRFToken", client.cookies["trading_dev_csrf"])]
    path = PATH
    if change == "csrf_tamper":
        headers[1] = ("X-CSRFToken", "tampered")
    elif change == "bearer":
        headers.append(("Authorization", "Bearer synthetic"))
    elif change in {"same_site", "cross_site"}:
        headers.append(("Sec-Fetch-Site", change.replace("_", "-")))
    elif change == "query":
        path += "?token=synthetic"
    elif change == "duplicate_origin":
        headers.append(("Origin", ORIGIN))
    elif change == "duplicate_cookie":
        headers.append(("Cookie", "trading_dev_session=one; trading_dev_session=two"))
    assert client.post(path, json={}, headers=headers).status_code == 403
    assert not called


def test_signed_csrf_and_origin_allow_json_and_reject_forms_and_large_bodies(boundary):
    client, called = boundary
    headers = {"Origin": ORIGIN, "X-CSRFToken": client.cookies["trading_dev_csrf"]}
    assert client.post(PATH, json={}, headers=headers).status_code == 200
    called.clear()
    assert client.post(PATH, data={"field": "value"}, headers=headers).status_code == 415
    assert client.post(PATH, json={"field": "x" * 5000}, headers=headers).status_code == 413
    assert (
        client.post(PATH, json={}, headers={**headers, "Content-Encoding": "gzip"}).status_code
        == 415
    )
    assert not called


def test_chunked_body_is_bounded_without_trusting_content_length():
    calls = []

    async def endpoint(scope, receive, send):
        calls.append(True)

    app = HTTPBoundary(BrowserBoundary(endpoint, CookiePolicy(ORIGIN), secrets.token_hex(32)))

    async def run():
        chunks = iter([b"a" * 3000, b"b" * 2000])
        messages = []

        async def receive():
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            messages.append(message)

        await app(
            dict(
                type="http",
                asgi={"version": "3.0"},
                method="POST",
                path=PATH,
                scheme="http",
                server=("127.0.0.1", 8000),
                query_string=b"",
                headers=[
                    (b"host", b"127.0.0.1:8000"),
                    (b"origin", ORIGIN.encode()),
                    (b"content-type", b"application/json"),
                ],
            ),
            receive,
            send,
        )
        assert messages[0]["status"] == 413

    asyncio.run(run())
    assert not calls


def test_hosted_cookie_contract_and_loopback_relaxation_are_distinct():
    policy = CookiePolicy("https://portfolio.example.invalid", secure=True)
    response = Response()
    policy.set(response, "synthetic")
    header = response.headers["set-cookie"]
    assert header.startswith("__Host-portfolio-session=")
    assert all(value in header for value in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"))
    assert "Domain=" not in header and "Max-Age=" not in header
    response = Response()
    policy.clear(response)
    assert "Max-Age=0" in response.headers["set-cookie"]
    with pytest.raises(ValueError):
        CookiePolicy("http://example.invalid")
    with pytest.raises(ValueError):
        CookiePolicy(ORIGIN, secure=True)
