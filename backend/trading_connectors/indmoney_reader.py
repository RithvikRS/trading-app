"""Bounded, deterministic MCP holdings reads; no active provider adapter or import route."""

import asyncio
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx2 as httpx

from trading_api.finance import FinancialInstant
from trading_connectors.indmoney_discovery import RESOURCE
from trading_connectors.indmoney_models import TokenSecrets
from trading_connectors.portfolio_contracts import (
    MAX_RESPONSE_BYTES,
    MAX_ROWS,
    HoldingsContract,
    HoldingsPage,
    JsonNumber,
    PortfolioRead,
    PortfolioReadError,
    cursor_value,
    exact_document,
    identifier,
)

PROTOCOL = "2025-11-25"
HOLDINGS_TOOL = "networth_holdings"
MAX_PAGES = 10
MAX_CATALOG_PAGES = 4
MAX_TOTAL_BYTES = 2_097_152
READ_SECONDS = 20


class ReadGate:
    """Process-wide, non-queuing capacity and conservative provider backoff."""

    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(4)
        self._lock = threading.Lock()
        self._until = 0.0

    def acquire(self) -> None:
        self.check()
        if not self._slots.acquire(blocking=False):
            raise PortfolioReadError("capacity")

    def check(self) -> None:
        with self._lock:
            if time.monotonic() < self._until:
                raise PortfolioReadError("rate_limited")

    def defer(self, value: str | None) -> None:
        seconds = 60.0
        if value is not None and len(value) <= 64:
            try:
                if re.fullmatch(r"[0-9]{1,6}", value):
                    seconds = float(int(value))
                else:
                    seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except ValueError, TypeError, OverflowError:
                pass
        with self._lock:
            self._until = max(self._until, time.monotonic() + min(300, max(1, seconds)))

    def release(self) -> None:
        self._slots.release()


_GATE = ReadGate()


class _Events:
    """Incremental bounded SSE framing; server requests/instructions are never dispatched."""

    def __init__(self) -> None:
        self.line = bytearray()
        self.fields: list[str] = []
        self.skip_lf = False
        self.count = 0

    def feed(self, chunk: bytes) -> dict[str, Any] | None:
        for byte in chunk:
            if self.skip_lf and byte == 10:
                self.skip_lf = False
                continue
            self.skip_lf = byte == 13
            if byte not in (10, 13):
                self.line.append(byte)
                continue
            line = self.line.decode("utf-8")
            self.line.clear()
            if line:
                self.fields.append(line)
                continue
            self.count += 1
            if self.count > 16:
                raise PortfolioReadError("limits")
            data: list[str] = []
            seen: set[str] = set()
            for field in self.fields:
                if field.startswith(":"):
                    continue
                key, _, value = field.partition(":")
                value = value.removeprefix(" ")
                if key == "data":
                    data.append(value)
                else:
                    if key in seen or key not in {"id", "event", "retry"}:
                        raise PortfolioReadError("compatibility")
                    seen.add(key)
                    if (
                        key == "event"
                        and value != "message"
                        or key == "id"
                        and not re.fullmatch(r"[\x21-\x7e]{1,256}", value)
                        or key == "retry"
                        and not re.fullmatch(r"[0-9]{1,6}", value)
                    ):
                        raise PortfolioReadError("compatibility")
            self.fields.clear()
            text = "\n".join(data)
            if text:
                return exact_document(text.encode("utf-8"))
        return None


class _Connection:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: TokenSecrets,
        expires_at: datetime,
        validate_access: Callable[[], None],
        gate: ReadGate,
        *,
        allow_tool_calls: bool = False,
    ) -> None:
        self.client, self.tokens, self.expires_at = client, tokens, expires_at
        self.validate_access, self.gate = validate_access, gate
        self.session: str | None = None
        self.total = 0
        self.request_id = 0
        self.contract_revision = ""
        self.schema_digest = ""
        self.allow_tool_calls = allow_tool_calls

    def check(self) -> None:
        self.gate.check()
        if datetime.now(UTC) >= self.expires_at:
            raise PortfolioReadError("authorization")
        try:
            self.validate_access()
        except Exception:
            raise PortfolioReadError("authorization") from None

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.check()
        if method not in {"initialize", "notifications/initialized", "tools/list", "tools/call"}:
            raise PortfolioReadError("compatibility")
        if method == "tools/call" and (
            not self.allow_tool_calls or params is None or params.get("name") != HOLDINGS_TOOL
        ):
            raise PortfolioReadError("compatibility")
        notification = method == "notifications/initialized"
        self.request_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            message["id"] = self.request_id
        if params is not None:
            message["params"] = params
        body = json.dumps(message, allow_nan=False, separators=(",", ":")).encode()
        if len(body) > 8192:
            raise PortfolioReadError("limits")
        headers = {
            "Authorization": "Bearer " + self.tokens.access_token.get_secret_value(),
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        }
        if method != "initialize":
            headers["MCP-Protocol-Version"] = PROTOCOL
        if self.session is not None:
            headers["MCP-Session-Id"] = self.session
        # A shared connection can receive Set-Cookie; it is never credential forwarding policy.
        self.client.cookies.clear()
        async with self.client.stream("POST", RESOURCE, headers=headers, content=body) as response:
            if (
                len(response.headers.raw) > 64
                or sum(len(key) + len(value) for key, value in response.headers.raw) > 16_384
            ):
                raise PortfolioReadError("limits")
            for name in (
                "content-type",
                "content-length",
                "content-encoding",
                "mcp-session-id",
                "retry-after",
            ):
                if len(response.headers.get_list(name)) > 1:
                    raise PortfolioReadError("compatibility")
            if response.status_code in {401, 403, 404}:
                raise PortfolioReadError("authorization")
            if response.status_code in {429, 503}:
                self.gate.defer(response.headers.get("retry-after"))
                raise PortfolioReadError("rate_limited")
            if response.status_code != (202 if notification else 200):
                raise PortfolioReadError()
            if response.headers.get("content-encoding", "identity") != "identity":
                raise PortfolioReadError("compatibility")
            length = response.headers.get("content-length")
            if length is not None and (
                not re.fullmatch(r"[0-9]{1,6}", length) or int(length) > MAX_RESPONSE_BYTES
            ):
                raise PortfolioReadError("limits")
            session = response.headers.get("mcp-session-id")
            if session is not None:
                if not re.fullmatch(r"[\x21-\x7e]{1,256}", session):
                    raise PortfolioReadError("compatibility")
                if method == "initialize":
                    self.session = session
                elif session != self.session:
                    raise PortfolioReadError("compatibility")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if not notification and mime not in {"application/json", "text/event-stream"}:
                raise PortfolioReadError("compatibility")
            raw, count, events = bytearray(), 0, _Events()
            document = None
            async for chunk in response.aiter_raw():
                count += len(chunk)
                self.total += len(chunk)
                if count > MAX_RESPONSE_BYTES or self.total > MAX_TOTAL_BYTES:
                    raise PortfolioReadError("limits")
                if notification and chunk:
                    raise PortfolioReadError("compatibility")
                if mime == "text/event-stream":
                    document = events.feed(chunk)
                    if document is not None:
                        break  # Close once the response arrives; never wait for a permanent stream.
                else:
                    raw.extend(chunk)
            if mime != "text/event-stream" and length is not None and count != int(length):
                raise PortfolioReadError("compatibility")
        self.check()
        if notification:
            return {}
        if mime == "application/json":
            document = exact_document(bytes(raw))
        if (
            document is None
            or set(document) != {"jsonrpc", "id", "result"}
            or document["jsonrpc"] != "2.0"
            or type(document["id"]) is not JsonNumber
            or document["id"].source != str(self.request_id)
            or type(document["result"]) is not dict
        ):
            # Includes JSON-RPC errors, unsolicited requests and notifications. No body escapes.
            raise PortfolioReadError("compatibility")
        return document["result"]

    async def initialize(self) -> dict[str, Any]:
        result = await self.request(
            "initialize",
            dict(
                protocolVersion=PROTOCOL,
                capabilities={},
                clientInfo={"name": "Portfolio", "version": "0.1.0"},
            ),
        )
        if (
            not {"protocolVersion", "capabilities", "serverInfo"} <= result.keys()
            or result.keys() - {"protocolVersion", "capabilities", "serverInfo", "instructions"}
            or result["protocolVersion"] != PROTOCOL
            or type(result["capabilities"]) is not dict
            or type(result["capabilities"].get("tools")) is not dict
            or type(result["serverInfo"]) is not dict
            or type(result["serverInfo"].get("name")) is not str
            or type(result["serverInfo"].get("version")) is not str
        ):
            raise PortfolioReadError("compatibility")
        # Instructions, server URLs and other capabilities are inert, untrusted metadata.
        await self.request("notifications/initialized")
        return result

    async def catalog(
        self, validate_tool: Callable[[dict[str, Any]], None] | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Collect bounded metadata only; discovering a name never authorizes invocation."""
        cursor = None
        cursors: set[str] = set()
        names: set[str] = set()
        tools: list[dict[str, Any]] = []
        for _ in range(MAX_CATALOG_PAGES):
            result = await self.request("tools/list", {} if cursor is None else {"cursor": cursor})
            if (
                result.keys() - {"tools", "nextCursor"}
                or type(result.get("tools")) is not list
                or len(result["tools"]) > 64
            ):
                raise PortfolioReadError("compatibility")
            for tool in result["tools"]:
                if (
                    type(tool) is not dict
                    or type(tool.get("name")) is not str
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", tool["name"])
                    or tool["name"] in names
                ):
                    raise PortfolioReadError("compatibility")
                names.add(tool["name"])
                if validate_tool is not None:
                    validate_tool(tool)
                tools.append(tool)
            cursor = cursor_value(result.get("nextCursor"))
            if cursor is None:
                return tuple(tools)
            if cursor in cursors:
                raise PortfolioReadError("compatibility")
            cursors.add(cursor)
        raise PortfolioReadError("limits")

    async def verify_catalog(self, contract: HoldingsContract) -> None:
        expected_input = exact_document(contract.input_schema)
        expected_output = exact_document(contract.output_schema)
        if expected_input.get("type") != "object" or expected_output.get("type") != "object":
            raise PortfolioReadError("compatibility")
        self.contract_revision = identifier(contract.revision)
        self.schema_digest = hashlib.sha256(
            contract.input_schema + b"\0" + contract.output_schema
        ).hexdigest()
        found = False

        def validate_tool(tool: dict[str, Any]) -> None:
            nonlocal found
            if tool["name"] != HOLDINGS_TOOL:
                return
            if (
                tool.keys()
                - {"name", "title", "description", "inputSchema", "outputSchema", "annotations"}
                or tool.get("inputSchema") != expected_input
                or tool.get("outputSchema") != expected_output
                or type(tool.get("annotations")) is not dict
                or tool["annotations"].get("readOnlyHint") is not True
                or tool["annotations"].get("destructiveHint", False) is not False
            ):
                raise PortfolioReadError("compatibility")
            found = True

        await self.catalog(validate_tool)
        if not found:
            raise PortfolioReadError("compatibility")

    async def holdings(self, contract: HoldingsContract) -> PortfolioRead:
        pages: list[HoldingsPage] = []
        cursors: set[str] = set()
        keys: set[tuple[str, str, str | None, str | None, str | None]] = set()
        cursor = None
        count = 0
        for _ in range(MAX_PAGES):
            arguments = contract.arguments(cursor)
            if type(arguments) is not dict:
                raise PortfolioReadError("compatibility")
            result = await self.request(
                "tools/call", {"name": HOLDINGS_TOOL, "arguments": arguments}
            )
            if (
                result.keys() - {"content", "structuredContent", "isError"}
                or result.get("isError", False) is not False
                or type(result.get("structuredContent")) is not dict
                or type(result.get("content")) is not list
                or len(result["content"]) > 1
            ):
                raise PortfolioReadError("compatibility")
            # Text is a compatibility rendering, never a financial schema or executable content.
            for content in result["content"]:
                if (
                    type(content) is not dict
                    or set(content) != {"type", "text"}
                    or content["type"] != "text"
                    or type(content["text"]) is not str
                ):
                    raise PortfolioReadError("compatibility")
            page = contract.decode(result["structuredContent"])
            if type(page) is not HoldingsPage:
                raise PortfolioReadError("compatibility")
            if pages and (page.account, page.asset, page.observed_at) != (
                pages[0].account,
                pages[0].asset,
                pages[0].observed_at,
            ):
                raise PortfolioReadError("compatibility")
            if any(row.key in keys for row in page.holdings):
                raise PortfolioReadError("compatibility")
            if count + len(page.holdings) > MAX_ROWS:
                return self.finish(pages, "row_limit")
            count += len(page.holdings)
            keys.update(row.key for row in page.holdings)
            pages.append(page)
            cursor = page.next_cursor
            if cursor is None:
                return self.finish(pages, None if page.complete else "source_incomplete")
            if cursor in cursors:
                raise PortfolioReadError("compatibility")
            cursors.add(cursor)
        return self.finish(pages, "page_limit")

    def finish(
        self,
        pages: list[HoldingsPage],
        limitation: Literal["source_incomplete", "page_limit", "row_limit"] | None,
    ) -> PortfolioRead:
        self.check()
        return PortfolioRead(
            tuple(pages),
            FinancialInstant(datetime.now(UTC).isoformat()),
            "source_complete" if limitation is None else "incomplete",
            limitation,
            self.contract_revision,
            self.schema_digest,
        )


class IndmoneyPortfolioReader:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        gate: ReadGate = _GATE,
    ) -> None:
        self._transport, self._gate = transport, gate

    async def read(
        self,
        tokens: TokenSecrets,
        *,
        expires_at: datetime,
        validate_access: Callable[[], None],
        contract: HoldingsContract | None = None,
    ) -> PortfolioRead:
        # There is deliberately no production adapter until authenticated schemas are reviewed.
        # A token alone is not permission to guess arguments or financial/pagination semantics.
        if contract is None:
            raise PortfolioReadError("compatibility")
        self._gate.acquire()
        try:
            tokens = TokenSecrets.model_validate(tokens.model_dump(warnings=False))
            if type(expires_at) is not datetime or expires_at.utcoffset() is None:
                raise PortfolioReadError("authorization")
            async with asyncio.timeout(READ_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(3),
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                ) as client:
                    connection = _Connection(
                        client,
                        tokens,
                        expires_at,
                        validate_access,
                        self._gate,
                        allow_tool_calls=True,
                    )
                    await connection.initialize()
                    await connection.verify_catalog(contract)
                    return await connection.holdings(contract)
        except PortfolioReadError:
            raise
        except Exception:
            raise PortfolioReadError() from None
        finally:
            self._gate.release()
