"""Synthetic transport evidence only; no live report, credentials or customer records."""

import asyncio
import hashlib
import traceback
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx2 as httpx
import pytest

from tests.test_amfi import report, row
from trading_api.amfi import parse_report
from trading_connectors import amfi_reader as reader
from trading_connectors.amfi_reader import NavReadError, read_current_nav


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks=(), *, wait=None, error=None):
        self.chunks = chunks
        self.wait = wait
        self.error = error
        self.reads = 0
        self.closed = False
        self.started = asyncio.Event()

    async def __aiter__(self):
        self.started.set()
        if self.wait is not None:
            await self.wait.wait()
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self):
        self.closed = True


class Server:
    def __init__(self, data=None, *, status=200, headers=None, body=None):
        data = report(row()) if data is None else data
        self.body = body or Body([data])
        self.headers = (
            headers
            if headers is not None
            else {"content-type": "text/plain", "content-length": str(len(data))}
        )
        self.status = status
        self.requests = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, headers=self.headers, stream=self.body)


def run(server):
    return asyncio.run(read_current_nav(transport=server.transport))


@pytest.fixture(autouse=True)
def separate_gate(monkeypatch):
    monkeypatch.setattr(reader, "_GATE", reader._ReadGate())


def test_fixed_destination_preserves_complete_exact_report_evidence():
    data = report(
        row(),
        row(code="900002", first="ZZ0000000024", nav="-0.0000"),
        row(code="900003", first="ZZ0000000032", nav="-"),
        newline="\r\n",
        prefix="\ufeff",
    )
    server = Server(data, body=Body([data[:17], data[17:155], data[155:]]))
    result = run(server)
    expected = parse_report(data)
    assert result == expected
    assert result.digest == hashlib.sha256(data).hexdigest()
    assert result.byte_count == len(data)
    assert [item.occurrence for item in result.rows] == [1, 2, 3]
    assert result.rows[0].nav_source == "12.340000000001"
    assert result.rows[0].date_source == "23-Oct-2026"
    assert result.rows[1].nav_source == "-0.0000"
    assert result.rows[2].reported().missing_reason == "not_supplied"
    assert "Synthetic" not in repr(result)
    assert len(server.requests) == 1 and server.body.closed
    request = server.requests[0]
    assert request.method == "GET" and str(request.url) == reader.REPORT_URL
    assert not request.url.query and not request.content
    assert request.headers["accept"] == "text/plain"
    assert request.headers["accept-encoding"] == "identity"
    for name in ("authorization", "proxy-authorization", "cookie", "referer"):
        assert name not in request.headers


def test_client_controls_are_fixed_and_no_ambient_environment_or_cookie_is_reused(monkeypatch):
    original = httpx.AsyncClient
    options = []

    def capture(**kwargs):
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(reader.httpx, "AsyncClient", capture)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(name, "https://invalid.example/private-canary")
    first = Server(headers={"content-type": "text/plain", "set-cookie": "private=canary"})
    second = Server()
    run(first)
    run(second)
    assert len(options) == 2
    for option in options:
        assert option["verify"] is True and option["trust_env"] is False
        assert option["follow_redirects"] is False
        assert option["timeout"].read == option["timeout"].connect == 3
        assert option["timeout"].write == option["timeout"].pool == 3
        assert option["limits"].max_connections == 1
        assert option["limits"].max_keepalive_connections == 0
    assert "cookie" not in second.requests[0].headers


@pytest.mark.parametrize(
    "media",
    ["text/plain", "TEXT/PLAIN", "text/plain; charset=utf-8", "text/plain; charset=US-ASCII"],
)
def test_verified_plain_text_metadata_variations(media):
    assert run(Server(headers={"content-type": media})).rows


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"content-type": "application/json"},
        {"content-type": "text/html"},
        {"content-type": "text/plain; charset=utf-16"},
        {"content-type": "text/plain\n; charset=utf-8"},
        {"content-type": "text/plain;\r\ncharset=utf-8"},
        {"content-type": "text/plain; charset=utf-8; unexpected=x"},
        {"content-type": "text/plain" + " " * 129},
        {"content-type": "text/plain", "content-encoding": "gzip"},
        {"content-type": "text/plain", "content-encoding": "br"},
        {"content-type": "text/plain", "content-range": "bytes 0-99/100"},
        {"content-type": "text/plain", "transfer-encoding": "gzip, chunked"},
        {"content-type": "text/plain", "transfer-encoding": "chunked", "content-length": "1"},
        {"content-type": "text/plain", "content-length": "-1"},
        {"content-type": "text/plain", "content-length": "1.0"},
        {"content-type": "text/plain", "content-length": "1, 1"},
        {"content-type": "text/plain", "content-length": "12345678"},
        [("content-type", "text/plain"), ("content-type", "text/plain")],
        [("content-type", "text/plain"), ("content-length", "1"), ("content-length", "1")],
        [
            ("content-type", "text/plain"),
            ("content-encoding", "identity"),
            ("content-encoding", "identity"),
        ],
        [
            ("content-type", "text/plain"),
            ("transfer-encoding", "chunked"),
            ("transfer-encoding", "chunked"),
        ],
    ],
)
def test_ambiguous_or_unsupported_response_metadata_fails_before_body(headers):
    server = Server(headers=headers)
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "unsupported"
    assert server.body.reads == 0 and server.body.closed


def test_chunked_response_without_length_remains_fully_bounded():
    result = run(Server(headers={"content-type": "text/plain", "transfer-encoding": "chunked"}))
    assert result.rows[0].nav_source == "12.340000000001"


@pytest.mark.parametrize("status", [201, 204, 206, 301, 302, 303, 307, 308, 400, 401, 404, 500])
def test_non_success_and_redirects_never_follow_or_read_error_bodies(status):
    server = Server(status=status, headers={"location": "http://127.0.0.1/private-canary"})
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "unavailable"
    assert len(server.requests) == 1 and server.body.reads == 0 and server.body.closed


def test_oversized_declared_body_fails_before_streaming():
    server = Server(
        headers={"content-type": "text/plain", "content-length": str(reader.MAX_BYTES + 1)}
    )
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "limits" and server.body.reads == 0 and server.body.closed


def test_stream_cap_applies_without_declared_length():
    server = Server(body=Body([b"x" * 65536] * 65), headers={"content-type": "text/plain"})
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "limits" and server.body.closed


def test_exact_stream_cap_is_inclusive(monkeypatch):
    data = report(row())
    monkeypatch.setattr(reader, "MAX_BYTES", len(data))
    assert run(Server(data)).byte_count == len(data)
    with pytest.raises(NavReadError) as error:
        run(Server(data + b"\n", headers={"content-type": "text/plain"}))
    assert error.value.reason == "limits"


@pytest.mark.parametrize("difference", [-1, 1])
def test_declared_length_must_match_complete_body(difference):
    data = report(row())
    server = Server(
        data, headers={"content-type": "text/plain", "content-length": str(len(data) + difference)}
    )
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "unsupported" and server.body.closed


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<html>private-provider-canary</html>",
        report(row(), row(nav="not-a-value")),
        report(row()).replace(b";Plan;Option;", b";"),
    ],
)
def test_parser_rejects_entire_unsupported_report_without_partial_result_or_payload(data):
    server = Server(data)
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "unsupported"
    assert str(error.value) == "Public NAV read did not complete."
    assert "private-provider-canary" not in "".join(traceback.format_exception(error.value))
    assert server.body.closed


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ReadError("private-provider-canary"),
        OSError("private-provider-canary"),
        RuntimeError("private-provider-canary"),
    ],
)
def test_transport_failure_is_safe_and_releases_capacity(exception):
    server = Server(body=Body(error=exception))
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "unavailable"
    assert "private-provider-canary" not in "".join(traceback.format_exception(error.value))
    assert server.body.closed
    assert run(Server()).rows


def test_transport_timeout_is_safe_and_releases_capacity():
    transport_error = httpx.ReadTimeout("private-provider-canary")
    with pytest.raises(NavReadError) as error:
        run(Server(body=Body(error=transport_error)))
    assert error.value.reason == "limits"
    assert "private-provider-canary" not in "".join(traceback.format_exception(error.value))
    assert run(Server()).rows


def test_total_deadline_bounds_a_stalled_stream_and_closes_it(monkeypatch):
    monkeypatch.setattr(reader, "READ_SECONDS", 0.02)

    async def scenario():
        server = Server(body=Body(wait=asyncio.Event()))
        with pytest.raises(NavReadError) as error:
            await asyncio.wait_for(read_current_nav(transport=server.transport), 2)
        assert error.value.reason == "limits" and server.body.closed
        return await read_current_nav(transport=Server().transport)

    assert asyncio.run(scenario()).rows


def test_capacity_rejects_without_queuing_and_cancellation_releases_slot():
    async def scenario():
        blocked = Server(body=Body(wait=asyncio.Event()))
        pending = asyncio.create_task(read_current_nav(transport=blocked.transport))
        await blocked.body.started.wait()
        rejected = Server()
        with pytest.raises(NavReadError) as error:
            await read_current_nav(transport=rejected.transport)
        assert error.value.reason == "capacity" and rejected.requests == []
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert blocked.body.closed
        return await read_current_nav(transport=Server().transport)

    assert asyncio.run(scenario()).rows


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "retry,delay",
    [
        (None, 60),
        ("bad-private-canary", 60),
        ("9" * 65, 60),
        ("0", 1),
        ("2", 2),
        ("99999999", 3600),
    ],
)
def test_rate_limits_use_bounded_monotonic_backoff_without_retry(monkeypatch, status, retry, delay):
    clock = [100.0]
    monkeypatch.setattr(reader, "_GATE", reader._ReadGate(lambda: clock[0]))
    headers = {} if retry is None else {"retry-after": retry}
    limited = Server(status=status, headers=headers)
    with pytest.raises(NavReadError) as error:
        run(limited)
    assert error.value.reason == "rate_limited"
    assert limited.body.reads == 0 and limited.body.closed and len(limited.requests) == 1
    clock[0] += delay - 0.01
    blocked = Server()
    with pytest.raises(NavReadError) as error:
        run(blocked)
    assert error.value.reason == "rate_limited" and blocked.requests == []
    clock[0] += 0.01
    assert run(Server()).rows


def test_duplicate_retry_after_is_conservative_and_http_date_is_bounded(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(reader, "_GATE", reader._ReadGate(lambda: clock[0]))
    limited = Server(status=429, headers=[("retry-after", "1"), ("retry-after", "2")])
    with pytest.raises(NavReadError):
        run(limited)
    clock[0] = 159
    with pytest.raises(NavReadError):
        run(Server())
    clock[0] = 160
    assert run(Server()).rows
    now = datetime.now(UTC)
    assert 1 <= reader._retry_seconds(format_datetime(now + timedelta(seconds=30))) <= 30
    assert reader._retry_seconds(format_datetime(now - timedelta(days=1))) == 1
    assert reader._retry_seconds(format_datetime(now + timedelta(days=30))) == 3600
    assert reader._retry_seconds("26 Oct 2026 10:30:00") == 60


@pytest.mark.parametrize("status", [200, 503])
@pytest.mark.parametrize("limit", ["count", "bytes"])
def test_aggregate_header_limits_fail_before_body(status, limit):
    headers = [("content-type", "text/plain")]
    if limit == "count":
        headers += [(f"x-synthetic-{index}", "x") for index in range(64)]
    else:
        headers += [("x-synthetic", "x" * 16384)]
    server = Server(status=status, headers=headers)
    with pytest.raises(NavReadError) as error:
        run(server)
    assert error.value.reason == "limits" and server.body.reads == 0 and server.body.closed


def test_aggregate_header_limits_are_inclusive():
    headers = [("content-type", "text/plain")]
    headers += [(f"x-synthetic-{index}", "x") for index in range(63)]
    assert run(Server(headers=headers)).rows
    base = len("content-type") + len("text/plain") + len("x-synthetic")
    headers = [("content-type", "text/plain"), ("x-synthetic", "x" * (16384 - base))]
    assert run(Server(headers=headers)).rows
