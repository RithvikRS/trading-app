import json
import logging
import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from trading_api.application import SECURITY_HEADERS, HTTPBoundary, create_app
from trading_api.config import Settings
from trading_api.logging import SafeFormatter

SECRET = "synthetic-sensitive-value"


@pytest.fixture
def app():
    return create_app(Settings(environment="test"))


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1") as value:
        yield value


def test_liveness_has_only_minimal_non_dependency_status(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "set-cookie" not in response.headers
    assert "server" not in response.headers
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    for key, value in SECURITY_HEADERS.items():
        assert response.headers[key] == value


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login",
        "/api/v1/holdings",
        "/api/v1/workspace",
        "/api/v1/preferences",
        "/api/v1/auth/test-login",
        "/health/ready",
    ],
)
def test_undelivered_routes_and_schema_are_unavailable(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "request_id": response.headers["x-request-id"]}
    assert response.headers["cache-control"] == "no-store"


def test_untrusted_host_is_denied_even_with_forwarded_host(client):
    response = client.get(
        "/api/v1/health/live", headers={"Host": "attacker.invalid", "X-Forwarded-Host": "localhost"}
    )
    assert response.status_code == 400
    assert "attacker" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"


def test_mutations_and_cors_are_not_enabled(client):
    response = client.post("/api/v1/health/live", json={"password": SECRET})
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert SECRET not in response.text
    preflight = client.options(
        "/api/v1/health/live",
        headers={"Origin": "https://attacker.invalid", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 405
    assert "access-control-allow-origin" not in preflight.headers


def test_paths_are_not_redirected_and_request_ids_are_server_generated(client):
    response = client.get("/api/v1/health/live/", follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers
    one = client.get("/api/v1/health/live", headers={"X-Request-ID": SECRET})
    two = client.get("/api/v1/health/live", headers={"X-Request-ID": one.headers["x-request-id"]})
    assert one.headers["x-request-id"] != SECRET
    assert two.headers["x-request-id"] != one.headers["x-request-id"]


def test_validation_and_exception_details_are_never_returned_or_logged(app, caplog):
    # Only this test registers fault routes; none are part of the deployed factory.
    api = app.app.app
    assert isinstance(api, FastAPI)

    class Input(BaseModel):
        count: int

    @api.post("/test-validation")
    async def validation(payload: Input):
        return payload

    @api.get("/test-failure")
    async def failure():
        raise RuntimeError(SECRET)

    @api.get("/test-http-failure")
    async def http_failure():
        raise HTTPException(400, detail=SECRET, headers={"X-Private": SECRET})

    with (
        caplog.at_level(logging.INFO, logger="trading_api"),
        TestClient(app, base_url="http://localhost", raise_server_exceptions=True) as client,
    ):
        invalid = client.post("/test-validation", json={"count": SECRET})
        error = client.get("/test-failure?token=" + SECRET, headers={"Authorization": SECRET})
        handled = client.get("/test-http-failure")

    assert [invalid.status_code, error.status_code, handled.status_code] == [422, 500, 400]
    for response in (invalid, error, handled):
        assert SECRET not in response.text
        assert "traceback" not in response.text.lower()
        assert "x-private" not in response.headers
        assert response.json()["request_id"] == response.headers["x-request-id"]
        for key, value in SECURITY_HEADERS.items():
            assert response.headers[key] == value
    assert "request_failed" in caplog.text
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_boundary_handles_errors_outside_the_framework():
    async def broken(scope, receive, send):
        raise RuntimeError(SECRET)

    client = TestClient(HTTPBoundary(broken), base_url="http://localhost")
    response = client.get("/")
    client.close()
    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert SECRET not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_interrupted_response_does_not_report_success_or_disclose_exception(caplog):
    async def chunks():
        yield b"partial"
        raise RuntimeError(SECRET)

    async def streaming(scope, receive, send):
        if scope["type"] == "http":
            await StreamingResponse(chunks())(scope, receive, send)

    with caplog.at_level(logging.INFO, logger="trading_api"):
        client = TestClient(HTTPBoundary(streaming))
        with pytest.raises(RuntimeError, match="Response interrupted") as failure:
            client.get("/")
        client.close()
    assert SECRET not in str(failure.value)
    assert "request_completed" not in caplog.text
    failed = [record for record in caplog.records if record.msg == "request_failed"]
    assert len(failed) == 1
    assert failed[0].status == 200  # Headers were sent; the failure did not send a second status.


def test_log_formatter_drops_raw_messages_arguments_exception_and_untrusted_fields():
    try:
        raise ValueError(SECRET)
    except ValueError:
        import sys

        record = logging.LogRecord(
            "uvicorn.error", logging.ERROR, SECRET, 1, "bad %s", (SECRET,), sys.exc_info()
        )
    record.request_id = SECRET
    record.status = SECRET
    record.stack_info = SECRET
    serialized = SafeFormatter().format(record)
    assert json.loads(serialized) == {"level": "ERROR", "event": "server_event"}
    assert SECRET not in serialized


def test_log_formatter_keeps_only_safe_correlation_and_status():
    record = logging.LogRecord("trading_api", logging.INFO, "", 0, "request_completed", (), None)
    record.request_id = "a" * 32
    record.status = 200
    assert json.loads(SafeFormatter().format(record)) == {
        "level": "INFO",
        "event": "request_completed",
        "request_id": "a" * 32,
        "status": 200,
    }
