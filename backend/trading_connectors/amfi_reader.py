"""Internal bounded AMFI current-report reader; no application activation or persistence."""

import asyncio
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx2 as httpx

from trading_api.amfi import MAX_BYTES, NavReport, NavUnavailable, parse_report

REPORT_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
READ_SECONDS = 20
_IO_SECONDS = 3
_CHUNK_BYTES = 65_536
_MAX_HEADERS = 64
_MAX_HEADER_BYTES = 16_384
_DEFAULT_BACKOFF = 60
_MAX_BACKOFF = 3600

type ReadFailure = Literal["capacity", "rate_limited", "limits", "unsupported", "unavailable"]


class NavReadError(ValueError):
    def __init__(self, reason: ReadFailure = "unavailable") -> None:
        self.reason = reason
        super().__init__("Public NAV read did not complete.")


def _retry_seconds(value: str | None) -> float:
    if value is None or len(value) > 64:
        return _DEFAULT_BACKOFF
    try:
        if re.fullmatch(r"[0-9]{1,8}", value, re.ASCII):
            seconds = float(int(value))
        else:
            parsed = parsedate_to_datetime(value)
            if parsed.utcoffset() is None:
                return _DEFAULT_BACKOFF
            seconds = (parsed - datetime.now(UTC)).total_seconds()
        return min(_MAX_BACKOFF, max(1, seconds))
    except ValueError, TypeError, OverflowError:
        return _DEFAULT_BACKOFF


class _ReadGate:
    """One non-queued attempt per process, with bounded provider-directed backoff."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._busy = False
        self._until = 0.0

    def acquire(self) -> None:
        with self._lock:
            if self._busy:
                raise NavReadError("capacity")
            if self._clock() < self._until:
                raise NavReadError("rate_limited")
            self._busy = True

    def defer(self, value: str | None) -> None:
        seconds = _retry_seconds(value)
        with self._lock:
            self._until = max(self._until, self._clock() + seconds)

    def release(self) -> None:
        with self._lock:
            self._busy = False


_GATE = _ReadGate()


def _response_length(response: httpx.Response) -> int | None:
    for name in ("content-type", "content-length", "content-encoding", "transfer-encoding"):
        if len(response.headers.get_list(name)) > 1:
            raise NavReadError("unsupported")
    media_type = response.headers.get("content-type", "")
    if (
        len(media_type) > 128
        or re.fullmatch(
            r"text/plain(?:[ \t]*;[ \t]*charset=(?:utf-8|us-ascii))?",
            media_type,
            re.IGNORECASE | re.ASCII,
        )
        is None
    ):
        raise NavReadError("unsupported")
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise NavReadError("unsupported")
    if "content-range" in response.headers:
        raise NavReadError("unsupported")
    transfer = response.headers.get("transfer-encoding")
    length = response.headers.get("content-length")
    if transfer is not None and (transfer.lower() != "chunked" or length is not None):
        raise NavReadError("unsupported")
    if length is None:
        return None
    if re.fullmatch(r"[0-9]{1,7}", length, re.ASCII) is None:
        raise NavReadError("unsupported")
    if int(length) > MAX_BYTES:
        raise NavReadError("limits")
    return int(length)


async def read_current_nav(*, transport: httpx.AsyncBaseTransport | None = None) -> NavReport:
    """Explicit internal read; callers must separately establish permitted source use.

    This function is not connected to application routes, configuration or jobs. It returns
    source evidence, never a selected price or freshness/portfolio conclusion. The transport
    override is for trusted internal tests, not an application-supplied destination/client.
    """
    gate = _GATE
    gate.acquire()
    raw = bytearray()
    try:
        async with asyncio.timeout(READ_SECONDS):
            async with httpx.AsyncClient(
                transport=transport,
                verify=True,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(_IO_SECONDS),
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                headers={
                    "Accept": "text/plain",
                    "Accept-Encoding": "identity",
                    "User-Agent": "trading-app-nav-reader/1",
                },
            ) as client:
                async with client.stream("GET", REPORT_URL) as response:
                    headers = response.headers.raw
                    if (
                        len(headers) > _MAX_HEADERS
                        or sum(len(name) + len(value) for name, value in headers)
                        > _MAX_HEADER_BYTES
                    ):
                        raise NavReadError("limits")
                    if response.status_code in {429, 503}:
                        retry = response.headers.get_list("retry-after")
                        gate.defer(retry[0] if len(retry) == 1 else None)
                        raise NavReadError("rate_limited")
                    if response.status_code != 200:
                        raise NavReadError()
                    length = _response_length(response)
                    async for chunk in response.aiter_raw(chunk_size=_CHUNK_BYTES):
                        if len(raw) + len(chunk) > MAX_BYTES:
                            raise NavReadError("limits")
                        raw.extend(chunk)
                    if length is not None and len(raw) != length:
                        raise NavReadError("unsupported")
        try:
            return parse_report(bytes(raw))
        except NavUnavailable:
            raise NavReadError("unsupported") from None
    except NavReadError:
        raise
    except TimeoutError, httpx.TimeoutException:
        raise NavReadError("limits") from None
    except Exception:
        raise NavReadError() from None
    finally:
        raw.clear()
        gate.release()
