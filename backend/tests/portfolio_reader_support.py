"""Fabricated contract for reader tests. This is NOT an observed INDmoney response schema."""

import json
import secrets
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
from pydantic import SecretStr

from trading_api.finance import FinancialValue, ReportedMarketValue
from trading_connectors.indmoney_models import TokenSecrets
from trading_connectors.indmoney_reader import (
    HOLDINGS_TOOL,
    PROTOCOL,
    IndmoneyPortfolioReader,
    ReadGate,
)
from trading_connectors.portfolio_contracts import (
    HoldingEvidence,
    HoldingsPage,
    PortfolioReadError,
    instant,
    source_decimal,
)


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


class SyntheticContract:
    revision = "synthetic-test-v1"
    input_schema = encode(
        {
            "type": "object",
            "properties": {"cursor": {"type": "string"}},
            "additionalProperties": False,
        }
    )
    # Only the local test decoder defines the nested format. No provider compatibility claim.
    output_schema = encode(
        {
            "type": "object",
            "properties": {"rows": {"type": "array"}},
            "required": ["account", "asset", "rows", "next_cursor", "complete", "observed_at"],
            "additionalProperties": False,
        }
    )

    def arguments(self, cursor):
        return {} if cursor is None else {"cursor": cursor}

    def decode(self, value):
        if set(value) != {"account", "asset", "rows", "next_cursor", "complete", "observed_at"}:
            raise PortfolioReadError("compatibility")
        if type(value["rows"]) is not list:
            raise PortfolioReadError("compatibility")
        holdings = []
        for row in value["rows"]:
            if type(row) is not dict or set(row) != {
                "instrument",
                "currency",
                "quantity",
                "price",
                "cost",
                "folio",
                "plan",
                "option",
                "observed_at",
                "priced_at",
            }:
                raise PortfolioReadError("compatibility")
            holdings.append(
                HoldingEvidence(
                    account=value["account"],
                    instrument=row["instrument"],
                    asset=value["asset"],
                    currency=row["currency"],
                    quantity=FinancialValue("position_quantity", source_decimal(row["quantity"])),
                    price=ReportedMarketValue(
                        "unit_price",
                        None if row["price"] is None else source_decimal(row["price"]),
                        currency=row["currency"],
                        missing_reason="not_supplied" if row["price"] is None else None,
                    ),
                    acquisition_cost=FinancialValue(
                        "monetary_evidence",
                        None if row["cost"] is None else source_decimal(row["cost"]),
                        currency=row["currency"],
                        meaning="acquisition_cost",
                        missing_reason="not_supplied" if row["cost"] is None else None,
                    ),
                    folio=row["folio"],
                    plan=row["plan"],
                    option=row["option"],
                    observed_at=instant(row["observed_at"]),
                    priced_at=instant(row["priced_at"]),
                )
            )
        return HoldingsPage(
            value["account"],
            value["asset"],
            tuple(holdings),
            value["next_cursor"],
            value["complete"],
            instant(value["observed_at"]),
        )


def row(**changes):
    return (
        dict(
            instrument="fixture-stock",
            currency="INR",
            quantity="12.000000000001",
            price="123.000000000001",
            cost=None,
            folio=None,
            plan=None,
            option=None,
            observed_at="2026-10-23T15:30:00+05:30",
            priced_at="2026-10-22T15:30:00+05:30",
        )
        | changes
    )


def page(**changes):
    return (
        dict(
            account="fixture-account",
            asset="indian_equity",
            rows=[row()],
            next_cursor=None,
            complete=True,
            observed_at="2026-10-23T15:30:00+05:30",
        )
        | changes
    )


def tokens():
    return TokenSecrets(
        access_token=SecretStr(secrets.token_urlsafe(32)),
        token_type="Bearer",
        scope="portfolio:read",
        expires_in=3600,
    )


def response(body, status=200, headers=None):
    return httpx.Response(
        status,
        headers=headers or {"content-type": "application/json"},
        stream=httpx.ByteStream(body),
    )


class Server:
    def __init__(self, pages=None, alter=None, *, sse=False, session=True):
        self.pages = pages if pages is not None else [page()]
        self.alter = alter
        self.sse, self.session = sse, session
        self.requests = []
        self.page_index = 0

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request, body))
        method = body["method"]
        headers = {"content-type": "text/event-stream" if self.sse else "application/json"}
        if method == "initialize":
            result = dict(
                protocolVersion=PROTOCOL,
                capabilities={"tools": {}},
                serverInfo={"name": "Synthetic test server", "version": "1"},
                instructions="Untrusted instructions to call an arbitrary URL are inert.",
            )
            if self.session:
                headers["mcp-session-id"] = "synthetic-session"
                headers["set-cookie"] = "fixture=must-not-forward; Path=/"
        elif method == "notifications/initialized":
            return response(b"", 202)
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": HOLDINGS_TOOL,
                        "inputSchema": json.loads(SyntheticContract.input_schema),
                        "outputSchema": json.loads(SyntheticContract.output_schema),
                        "annotations": {"readOnlyHint": True, "destructiveHint": False},
                    }
                ]
            }
        else:
            result = dict(
                content=[{"type": "text", "text": "Untrusted text is not interpreted."}],
                structuredContent=self.pages[self.page_index],
                isError=False,
            )
            self.page_index += 1
        message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if self.alter:
            override = self.alter(request, body, message, headers)
            if override is not None:
                return override
        raw = encode(message)
        if self.sse:
            raw = (
                b": keepalive\r\n\r\nid: first\r\ndata:\r\n\r\nevent: message\r\ndata: "
                + raw
                + b"\r\n\r\n"
            )
        return response(raw, headers=headers)


async def read(server, **kwargs):
    reader = IndmoneyPortfolioReader(transport=httpx.MockTransport(server), gate=ReadGate())
    return await reader.read(
        tokens(),
        **(
            {
                "contract": SyntheticContract(),
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
                "validate_access": lambda: None,
            }
            | kwargs
        ),
    )
