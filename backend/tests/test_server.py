import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2 as httpx
import pytest

from trading_api import __main__ as entry

ROOT = Path(__file__).resolve().parents[1]


def clean_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("TRADING_API_")
    }


@pytest.mark.parametrize(
    "settings,args",
    [
        ({"TRADING_API_ENVIRONMENT": "production"}, []),
        ({"TRADING_API_PORT": "synthetic-secret"}, []),
        ({"TRADING_API_AUTH_BYPASS": "synthetic-secret"}, []),
        ({}, ["--host", "synthetic-secret"]),
    ],
)
def test_invalid_startup_exits_without_traceback_or_values(settings, args):
    result = subprocess.run(
        [sys.executable, "-m", "trading_api", *args],
        cwd=ROOT,
        env=clean_environment() | settings,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"level": "ERROR", "event": "configuration_invalid"}


def test_entrypoint_does_not_enable_network_debug_or_proxy_overrides(monkeypatch):
    captured = {}
    monkeypatch.setattr(entry, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["trading_api"])
    monkeypatch.setenv("UVICORN_HOST", "0.0.0.0")
    monkeypatch.setenv("UVICORN_RELOAD", "true")
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    assert entry.main() == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["workers"] == 1
    assert captured["reload"] is False
    assert captured["proxy_headers"] is False
    assert captured["forwarded_allow_ips"] == ""
    assert captured["server_header"] is False
    assert captured["access_log"] is False
    assert captured["log_config"] is None


def test_real_server_liveness_and_log_privacy():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "trading_api"],
        cwd=ROOT,
        env=clean_environment()
        | {"TRADING_API_PORT": str(port), "TRADING_API_ENVIRONMENT": "test"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10
        ) as client:
            # Cold Python imports on Windows can exceed 15 seconds. This is a
            # bounded readiness wait, not a startup-performance assertion.
            deadline = time.monotonic() + 60
            while True:
                try:
                    response = client.get("/api/v1/health/live?secret=synthetic-private-query")
                    break
                except httpx.ConnectError, httpx.ConnectTimeout:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        pytest.fail("Local API did not start.")
                    time.sleep(0.05)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            assert "server" not in response.headers
            assert response.headers["cache-control"] == "no-store"
            missing = client.get(
                "/synthetic-private-path", headers={"Authorization": "synthetic-private-header"}
            )
            assert missing.status_code == 404
            denied = client.get("/api/v1/health/live", headers={"Host": "attacker.invalid"})
            assert denied.status_code == 400
        # Also exercise protocol-level errors that bypass the application middleware.
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(b"synthetic-private-invalid-http\r\n\r\n")
            assert b"400" in connection.recv(1024)
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
    assert stdout == ""
    assert "synthetic-private" not in stderr
    events = [json.loads(line) for line in stderr.splitlines()]
    assert any(event["event"] == "server_starting" for event in events)
    assert any(event["event"] == "request_completed" for event in events)
    assert all(set(event) <= {"level", "event", "request_id", "status"} for event in events)
