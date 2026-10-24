"""Financial reads inherit the browser boundary, with strict JSON query envelopes."""

import asyncio
import secrets

import pytest

from tests.test_browser_boundary import ORIGIN
from tests.test_browser_boundary import boundary as boundary
from trading_api.application import HTTPBoundary
from trading_api.authentication import BrowserBoundary, CookiePolicy

PATHS = [
    f"/api/v1/finance/{name}/query" for name in ("accounts", "sources", "instruments", "positions")
]


@pytest.mark.parametrize("path", [*PATHS, "/api/v1/finance", "/api/v1/finance/unknown"])
@pytest.mark.parametrize(
    "attack",
    ["csrf", "origin", "query", "bearer", "same-site", "duplicate-cookie", "duplicate-header"],
)
def test_financial_family_never_bypasses_browser_rules(boundary, path, attack):
    client, called = boundary
    headers = [("Origin", ORIGIN), ("X-CSRFToken", client.cookies["trading_dev_csrf"])]
    if attack == "csrf":
        headers.pop()
    elif attack == "origin":
        headers[0] = ("Origin", "https://untrusted.invalid")
    elif attack == "query":
        path += "?account_id=synthetic"
    elif attack == "bearer":
        headers.append(("Authorization", "Bearer synthetic"))
    elif attack == "same-site":
        headers.append(("Sec-Fetch-Site", "same-site"))
    elif attack == "duplicate-cookie":
        headers.append(("Cookie", "trading_dev_session=one; trading_dev_session=two"))
    elif attack == "duplicate-header":
        headers.append(("Content-Type", "application/json"))
        headers.append(("Content-Type", "application/json"))
    response = client.post(path, headers=headers, json={})
    assert response.status_code == 403 and not called


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "body",
    [
        b'{"limit":1,"limit":2}',
        b'{"limit":NaN}',
        b'{"limit":Infinity}',
        b'{"limit":-Infinity}',
        b'{"limit":1e999}',
        b'{"nested":{"a":1,"a":2}}',
        b"\xff{}",
        b"{",
        b"[" * 1500 + b"]" * 1500,
    ],
    ids=[
        "duplicate",
        "nan",
        "infinity",
        "negative-infinity",
        "overflow",
        "nested-duplicate",
        "utf8",
        "malformed",
        "depth",
    ],
)
def test_ambiguous_malformed_nonfinite_and_deep_json_never_reaches_handlers(boundary, path, body):
    client, called = boundary
    response = client.post(
        path,
        content=body,
        headers={
            "Origin": ORIGIN,
            "X-CSRFToken": client.cookies["trading_dev_csrf"],
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400 and not called
    assert set(response.json()) == {"error", "request_id"}


@pytest.mark.parametrize("path", PATHS)
def test_financial_json_is_bounded_and_not_compressed_or_form_encoded(boundary, path):
    client, called = boundary
    headers = {"Origin": ORIGIN, "X-CSRFToken": client.cookies["trading_dev_csrf"]}
    assert client.post(path, json={}, headers=headers).status_code == 200
    called.clear()
    assert client.post(path, data={"limit": 1}, headers=headers).status_code == 415
    assert (
        client.post(path, json={}, headers={**headers, "Content-Encoding": "gzip"}).status_code
        == 415
    )
    assert (
        client.post(
            path, content=b" " * 4097, headers={**headers, "Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert not called


@pytest.mark.parametrize(
    "failure,expected", [("chunked", 413), ("incomplete", 400), ("deadline", 400)]
)
def test_body_stream_limit_and_deadline_apply_before_json_or_sql(failure, expected, monkeypatch):
    called = []

    async def endpoint(scope, receive, send):
        called.append(True)

    app = HTTPBoundary(BrowserBoundary(endpoint, CookiePolicy(ORIGIN), secrets.token_hex(32)))
    original = asyncio.timeout
    if failure == "deadline":
        monkeypatch.setattr(asyncio, "timeout", lambda seconds: original(0.001))

    async def run():
        messages = []
        chunks = iter([b" " * 3000, b" " * 2000])

        async def receive():
            if failure == "deadline":
                await asyncio.sleep(0.05)
            if failure == "incomplete":
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            messages.append(message)

        await app(
            dict(
                type="http",
                asgi={"version": "3.0"},
                method="POST",
                path=PATHS[0],
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
        assert messages[0]["status"] == expected

    asyncio.run(run())
    assert not called
