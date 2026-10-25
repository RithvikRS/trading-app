"""Private, bounded MCP catalog inspection; metadata never grants permission to call tools."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx2 as httpx

from trading_api.finance import FinancialInstant
from trading_connectors.indmoney_models import TokenSecrets
from trading_connectors.indmoney_reader import _GATE, PROTOCOL, READ_SECONDS, ReadGate, _Connection
from trading_connectors.portfolio_contracts import JsonNumber, PortfolioReadError


def _document(value: dict[str, Any]) -> bytes:
    """Copy already bounded JSON to immutable bytes without converting numeric lexemes."""

    def encode(node: Any) -> str:
        if type(node) is JsonNumber:
            return node.source
        if type(node) is dict:
            return (
                "{" + ",".join(encode(key) + ":" + encode(item) for key, item in node.items()) + "}"
            )
        if type(node) is list:
            return "[" + ",".join(encode(item) for item in node) + "]"
        return json.dumps(node, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    return encode(value).encode("utf-8")


@dataclass(frozen=True, slots=True, repr=False)
class ToolMetadata:
    """Untrusted descriptor, including inert schemas/descriptions, for private local review."""

    name: str
    document: bytes

    def __repr__(self) -> str:
        return "ToolMetadata(<private>)"


@dataclass(frozen=True, slots=True, repr=False)
class CapabilityInspection:
    initialization: bytes
    tools: tuple[ToolMetadata, ...]
    fetched_at: FinancialInstant
    evidence_digest: str

    def __repr__(self) -> str:
        return "CapabilityInspection(<private>)"

    @property
    def protocol(self) -> str:
        return PROTOCOL

    @property
    def catalog_complete(self) -> Literal[True]:
        return True

    @property
    def history_verified(self) -> Literal[False]:
        return False

    @property
    def import_ready(self) -> Literal[False]:
        return False


def _validate_tool(tool: dict[str, Any]) -> None:
    # A schema is retained as inert data, never evaluated or resolved. Optional output schemas,
    # annotations and unknown metadata stay available for review, not runtime authorization.
    if (
        type(tool.get("inputSchema")) is not dict
        or "outputSchema" in tool
        and type(tool["outputSchema"]) is not dict
        or "annotations" in tool
        and type(tool["annotations"]) is not dict
        or any(key in tool and type(tool[key]) is not str for key in ("description", "title"))
    ):
        raise PortfolioReadError("compatibility")


class IndmoneyCapabilityInspector:
    """Internal engine only: no route, credential lookup, registration, writes or financial call."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        gate: ReadGate = _GATE,
    ) -> None:
        self._transport, self._gate = transport, gate

    async def inspect(
        self,
        tokens: TokenSecrets,
        *,
        expires_at: datetime,
        validate_access: Callable[[], None],
    ) -> CapabilityInspection:
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
                        allow_tool_calls=False,
                    )
                    initialization = _document(await connection.initialize())
                    catalog = await connection.catalog(_validate_tool)
                    tools = tuple(ToolMetadata(tool["name"], _document(tool)) for tool in catalog)
                    digest = hashlib.sha256(initialization)
                    for tool in tools:
                        digest.update(b"\0" + tool.document)
                    connection.check()
                    return CapabilityInspection(
                        initialization,
                        tools,
                        FinancialInstant(datetime.now(UTC).isoformat()),
                        digest.hexdigest(),
                    )
        except PortfolioReadError:
            raise
        except Exception:
            raise PortfolioReadError() from None
        finally:
            self._gate.release()
