import asyncio
import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import httpx2 as httpx
import pytest

from tests.portfolio_reader_support import (
    Server,
    SyntheticContract,
    encode,
    page,
    read,
    response,
    row,
    tokens,
)
from trading_api.finance import FinancialInstant, FinancialValue
from trading_connectors import indmoney_reader as reader_module
from trading_connectors.indmoney_discovery import RESOURCE
from trading_connectors.indmoney_reader import (
    HOLDINGS_TOOL,
    IndmoneyPortfolioReader,
    ReadGate,
)
from trading_connectors.portfolio_contracts import (
    MAX_RESPONSE_BYTES,
    JsonNumber,
    PortfolioReadError,
    exact_document,
    source_decimal,
)


@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("session", [False, True])
def test_fixed_read_only_lifecycle_and_private_exact_evidence(sse, session):
    server = Server(sse=sse, session=session)
    result = asyncio.run(read(server))
    assert result.coverage == "source_complete" and result.limitation is None
    assert result.import_ready is False
    assert result.contract_revision == "synthetic-test-v1" and len(result.schema_digest) == 64
    holding = result.pages[0].holdings[0]
    assert holding.quantity.source == "12.000000000001"
    assert holding.price.value == Decimal("123.000000000001")
    assert holding.acquisition_cost.value is None
    assert holding.acquisition_cost.missing_reason == "not_supplied"
    assert holding.priced_at.value < holding.observed_at.value < result.fetched_at.value
    assert "fixture" not in repr(result) + repr(result.pages) + repr(holding)
    assert [body["method"] for _, body in server.requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    for index, (request, _body) in enumerate(server.requests):
        assert str(request.url) == RESOURCE and request.method == "POST"
        assert "cookie" not in request.headers and "referer" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["authorization"].startswith("Bearer ")
        assert request.headers["accept"] == "application/json, text/event-stream"
        assert ("mcp-protocol-version" in request.headers) == (index > 0)
        assert ("mcp-session-id" in request.headers) == (session and index > 0)
    assert server.requests[0][1]["params"]["capabilities"] == {}
    assert server.requests[-1][1]["params"] == {"name": HOLDINGS_TOOL, "arguments": {}}


def test_default_reader_is_disabled_before_network_or_credential_access():
    server = Server()
    with pytest.raises(PortfolioReadError) as error:
        asyncio.run(read(server, contract=None))
    assert error.value.reason == "compatibility" and server.requests == []


def test_json_numeric_lexemes_preserve_large_values_negative_zero_and_precision():
    document = exact_document(b'{"q":123456789012345678.123456789012,"zero":-0.000,"e":1.00e-2}')
    assert document["q"].source == "123456789012345678.123456789012"
    assert document["zero"].source == "-0.000"
    assert document["e"].source == "1.00e-2"
    assert "123" not in repr(document["q"])
    with localcontext() as context:
        context.prec = 2
        value = FinancialValue("position_quantity", source_decimal(document["q"]))
        assert value.value == Decimal("123456789012345678.123456789012")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"\xff",
        b"\xef\xbb\xbf{}",
        b"{} suffix",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":"\\ud800"}',
        b'{"x":"\\u0000"}',
        b'{"x":' + b"1" * 65 + b"}",
        b" " * (MAX_RESPONSE_BYTES + 1),
        b'{"x":' + b"[" * 17 + b"]" * 17 + b"}",
        encode({str(n): n for n in range(129)}),
        encode({"x": [None] * 2001}),
        encode({"x": "x" * 65537}),
        encode({"x": [["x"] * 2000] * 11}),
    ],
    ids=lambda raw: f"bounded-payload-{len(raw)}",
)
def test_strict_bounded_json_rejects_untrusted_shapes(raw):
    with pytest.raises(PortfolioReadError, match="^Portfolio read did not complete.$"):
        exact_document(raw)


@pytest.mark.parametrize("value", [True, 1, 1.25, Decimal("1.25"), None, [], {}])
def test_numeric_boundary_never_coerces_python_numbers(value):
    with pytest.raises(PortfolioReadError):
        source_decimal(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", "-1"),
        ("quantity", "1e2"),
        ("quantity", "+1"),
        ("quantity", "1.1234567890123"),
        ("quantity", "1000000000000000000"),
        ("quantity", True),
        ("quantity", None),
        ("price", "0.1234567890123"),
        ("cost", "1.123456789"),
        ("currency", "EUR"),
        ("currency", "USD"),
        ("instrument", ""),
        ("instrument", "private\nidentifier"),
        ("observed_at", "2026-10-24"),
        ("priced_at", "2026-10-24T00:00:00"),
        ("priced_at", "2026-10-24T00:00:00-00:00"),
        ("folio", "unexpected"),
    ],
)
def test_invalid_financial_row_fails_entire_read(field, value):
    server = Server([page(rows=[row(), row(instrument="second") | {field: value}])])
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))


@pytest.mark.parametrize("price,cost", [(None, None), ("0", "0.0000"), ("-1.00", None)])
def test_missing_and_unusable_source_claims_do_not_become_usable_zero(price, cost):
    result = asyncio.run(read(Server([page(rows=[row(price=price, cost=cost)])])))
    holding = result.pages[0].holdings[0]
    assert holding.price.source == price and not holding.price.usable
    assert holding.acquisition_cost.source == cost
    assert holding.acquisition_cost.missing_reason == ("not_supplied" if cost is None else None)


def test_all_reviewed_asset_types_and_fund_variants_remain_distinct():
    fund_rows = [
        row(folio="folio-1", plan=plan, option=option)
        for plan in ("direct", "regular")
        for option in ("growth", "distribution")
    ]
    result = asyncio.run(read(Server([page(asset="mutual_fund", rows=fund_rows)])))
    assert len({item.key for item in result.pages[0].holdings}) == 4
    result = asyncio.run(read(Server([page(asset="us_equity", rows=[row(currency="USD")])])))
    assert result.pages[0].holdings[0].currency == "USD"


@pytest.mark.parametrize(
    "change",
    [
        {"asset": "bond"},
        {"asset": "mutual_fund"},
        {"account": ""},
        {"complete": "true"},
        {"observed_at": "2026-10-24"},
        {"rows": [row(), row()]},
        {"unknown": "private"},
        {"next_cursor": "next", "complete": True},
        {"next_cursor": "bad\ncursor", "complete": False},
    ],
)
def test_invalid_scope_or_completeness_is_not_silently_dropped(change):
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(Server([page(**change)])))


@pytest.mark.parametrize("complete", [True, False])
def test_empty_source_is_only_complete_on_explicit_coverage(complete):
    result = asyncio.run(read(Server([page(rows=[], complete=complete, observed_at=None)])))
    assert result.coverage == ("source_complete" if complete else "incomplete")
    assert result.pages[0].observed_at is None
    assert result.import_ready is False


def test_cursor_pagination_is_opaque_and_preserves_source_time():
    server = Server(
        [
            page(next_cursor="https://untrusted.invalid/path", complete=False),
            page(rows=[row(instrument="second")]),
        ]
    )
    result = asyncio.run(read(server))
    assert len(result.pages) == 2 and result.coverage == "source_complete"
    assert server.requests[-1][1]["params"]["arguments"] == {
        "cursor": "https://untrusted.invalid/path"
    }
    assert all(str(request.url) == RESOURCE for request, _ in server.requests)


@pytest.mark.parametrize(
    "change",
    [
        {"account": "other"},
        {"asset": "us_equity", "rows": [row(currency="USD")]},
        {"observed_at": "2026-10-24T00:00:00Z"},
        {"observed_at": None},
        {"rows": [row()]},
        {"next_cursor": "loop", "complete": False},
    ],
)
def test_inconsistent_pages_reject_whole_result_without_replacing_prior_evidence(change):
    previous = asyncio.run(read(Server()))
    server = Server(
        [
            page(next_cursor="loop", complete=False),
            page(rows=[row(instrument="second")], **change)
            if "rows" not in change
            else page(**change),
        ]
    )
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))
    assert previous.pages[0].holdings[0].instrument == "fixture-stock"
    assert previous.coverage == "source_complete"


def test_page_limit_returns_explicit_incomplete_evidence_without_an_extra_call():
    pages = [
        page(rows=[row(instrument=f"item-{n}")], next_cursor=f"cursor-{n}", complete=False)
        for n in range(11)
    ]
    server = Server(pages)
    result = asyncio.run(read(server))
    assert result.coverage == "incomplete" and result.limitation == "page_limit"
    assert len(result.pages) == server.page_index == 10


def test_cumulative_row_limit_preserves_only_accepted_pages(monkeypatch):
    monkeypatch.setattr(reader_module, "MAX_ROWS", 2)
    server = Server(
        [
            page(
                rows=[row(instrument="a"), row(instrument="b")], next_cursor="two", complete=False
            ),
            page(rows=[row(instrument="c")]),
        ]
    )
    result = asyncio.run(read(server))
    assert result.coverage == "incomplete" and result.limitation == "row_limit"
    assert len(result.pages) == 1 and len(result.pages[0].holdings) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(protocolVersion="unreviewed"),
        lambda result: result.update(capabilities={}),
        lambda result: result.update(serverInfo={}),
        lambda result: result.update(unknown="private"),
    ],
)
def test_initialization_mismatch_prevents_catalog_and_tool_calls(mutate):
    def alter(request, body, message, headers):
        if body["method"] == "initialize":
            mutate(message["result"])

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda tool: tool.update(name="place_order"),
        lambda tool: tool.update(inputSchema={}),
        lambda tool: tool.update(outputSchema={}),
        lambda tool: tool.pop("outputSchema"),
        lambda tool: tool.update(annotations={"readOnlyHint": False}),
        lambda tool: tool.update(annotations={"readOnlyHint": True, "destructiveHint": True}),
        lambda tool: tool.update(execution={"taskSupport": "required"}),
        lambda tool: tool.update(inputSchema={"$ref": "https://untrusted.invalid/schema"}),
    ],
)
def test_tool_schema_and_capability_drift_prevents_execution(mutate):
    def alter(request, body, message, headers):
        if body["method"] == "tools/list":
            mutate(message["result"]["tools"][0])

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))
    assert server.page_index == 0


@pytest.mark.parametrize("mode", ["cycle", "limit", "duplicate", "malformed"])
def test_catalog_must_finish_without_duplicate_names_or_cursors(mode):
    counter = 0

    def alter(request, body, message, headers):
        nonlocal counter
        if body["method"] != "tools/list":
            return
        counter += 1
        if mode == "duplicate":
            message["result"]["tools"] *= 2
        elif mode == "malformed":
            message["result"]["tools"] = {}
        else:
            message["result"] = {
                "tools": [],
                "nextCursor": "cycle" if mode == "cycle" else str(counter),
            }

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))
    assert server.page_index == 0 and counter <= 4


def test_complete_catalog_checked_even_when_first_page_contains_allowed_tool():
    counter = 0

    def alter(request, body, message, headers):
        nonlocal counter
        if body["method"] == "tools/list":
            counter += 1
            if counter == 1:
                message["result"]["nextCursor"] = "second"
            else:
                assert body["params"] == {"cursor": "second"}
                message["result"]["tools"] = [{"name": "place_order", "description": "Never call"}]

    server = Server(alter=alter)
    result = asyncio.run(read(server))
    assert result.coverage == "source_complete" and counter == 2
    assert [
        body["params"]["name"] for _, body in server.requests if body["method"] == "tools/call"
    ] == [HOLDINGS_TOOL]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(id=True),
        lambda m: m.update(id="1"),
        lambda m: m.update(id=500),
        lambda m: m.update(jsonrpc="1.0"),
        lambda m: m.update(error={"message": "private"}),
        lambda m: m.update(method="sampling/createMessage"),
        lambda m: m.pop("result"),
    ],
)
def test_unsolicited_protocol_messages_and_errors_never_dispatch(mutate):
    def alter(request, body, message, headers):
        mutate(message)

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError) as error:
        asyncio.run(read(server))
    assert "private" not in str(error.value) and len(server.requests) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(isError=True),
        lambda r: r.update(isError=0),
        lambda r: r.pop("structuredContent"),
        lambda r: r.update(structuredContent=[]),
        lambda r: r.update(content=[{"type": "resource_link", "uri": "https://untrusted.invalid"}]),
        lambda r: r.update(content=[{"type": "image", "data": "private"}]),
        lambda r: r.update(content=[{"type": "text", "text": "bad"}] * 2),
        lambda r: r.update(unknown=True),
    ],
)
def test_only_reviewed_structured_result_is_decoded(mutate):
    def alter(request, body, message, headers):
        if body["method"] == "tools/call":
            mutate(message["result"])

    with pytest.raises(PortfolioReadError):
        asyncio.run(read(Server(alter=alter)))


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404, 500])
def test_status_failure_never_follows_redirects_retries_or_echoes_provider_body(status):
    def alter(*args):
        return response(
            b"private provider message", status, {"location": "https://untrusted.invalid"}
        )

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError) as error:
        asyncio.run(read(server))
    assert str(error.value) == "Portfolio read did not complete."
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/html"},
        {"content-type": "application/json", "content-encoding": "gzip"},
        {"content-length": "9999999"},
        {"content-length": "-1"},
        {"content-length": "1.0"},
        {"mcp-session-id": "bad\r\nsession"},
        {"mcp-session-id": "s" * 257},
    ],
)
def test_unsupported_http_metadata_fails(headers):
    def alter(request, body, message, original):
        return response(encode(message), headers={"content-type": "application/json"} | headers)

    with pytest.raises(PortfolioReadError):
        asyncio.run(read(Server(alter=alter)))


@pytest.mark.parametrize(
    "header",
    ["content-type", "content-encoding", "content-length", "mcp-session-id", "retry-after"],
)
def test_duplicate_security_relevant_headers_fail(header):
    def alter(request, body, message, original):
        return response(
            encode(message),
            headers=[("content-type", "application/json"), (header, "one"), (header, "two")],
        )

    with pytest.raises(PortfolioReadError):
        asyncio.run(read(Server(alter=alter)))


def test_session_substitution_is_rejected_before_holdings():
    def alter(request, body, message, headers):
        if body["method"] == "tools/list":
            headers["mcp-session-id"] = "replacement"

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))
    assert server.page_index == 0


@pytest.mark.parametrize("expires", [datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC)])
def test_naive_or_expired_token_never_reaches_provider(expires):
    server = Server()
    with pytest.raises(PortfolioReadError) as error:
        asyncio.run(read(server, expires_at=expires))
    assert error.value.reason == "authorization" and not server.requests


@pytest.mark.parametrize("phase", ["initialize", "tools/list", "tools/call"])
def test_revocation_during_response_discards_data_and_stops_calls(phase):
    revoked = False

    def validate():
        if revoked:
            raise RuntimeError("private session data")

    def alter(request, body, message, headers):
        nonlocal revoked
        if body["method"] == phase:
            revoked = True

    server = Server(alter=alter)
    with pytest.raises(PortfolioReadError) as error:
        asyncio.run(read(server, validate_access=validate))
    assert error.value.reason == "authorization"
    assert server.requests[-1][1]["method"] == phase


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("retry", ["2", "999999", "0", "invalid", "Wed, 21 Oct 2015 07:28:00 GMT"])
def test_provider_backoff_is_bounded_and_has_no_automatic_retry(monkeypatch, status, retry):
    now = 1000.0
    monkeypatch.setattr(reader_module.time, "monotonic", lambda: now)
    gate = ReadGate()
    server = Server(alter=lambda *args: response(b"private", status, {"retry-after": retry}))
    reader = IndmoneyPortfolioReader(transport=httpx.MockTransport(server), gate=gate)

    async def attempt():
        return await reader.read(
            tokens(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            validate_access=lambda: None,
            contract=SyntheticContract(),
        )

    for _ in range(2):
        with pytest.raises(PortfolioReadError) as error:
            asyncio.run(attempt())
        assert error.value.reason == "rate_limited"
    assert len(server.requests) == 1
    assert 1 <= gate._until - now <= 300
    now += 301
    gate.check()


def test_capacity_is_non_queuing_and_released_after_failure():
    gate = ReadGate()
    for _ in range(4):
        gate.acquire()
    with pytest.raises(PortfolioReadError) as error:
        gate.acquire()
    assert error.value.reason == "capacity"
    for _ in range(4):
        gate.release()
    gate.acquire()
    gate.release()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, wait=False):
        self.chunks, self.wait, self.closed = chunks, wait, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.wait:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_sse_split_at_every_byte_and_open_stream_closes_at_response(ending):
    streams = []

    def alter(request, body, message, headers):
        raw = b": comment" + ending * 2 + b"data: " + encode(message) + ending * 2
        stream = Chunks([bytes([byte]) for byte in raw], wait=True)
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    result = asyncio.run(read(Server(alter=alter)))
    assert result.coverage == "source_complete" and all(stream.closed for stream in streams)


@pytest.mark.parametrize(
    "raw",
    [
        b"event: endpoint\ndata: https://untrusted.invalid\n\n",
        b"data: {}\n",
        b"data: {}\n\n",
        b"id: first\nid: second\ndata: {}\n\n",
        b"retry: -1\ndata: {}\n\n",
        b": comment\n\n" * 17,
        b"data: \xff\n\n",
        b"unknown: value\ndata: {}\n\n",
        b"data: [1]\n\n",
    ],
)
def test_malformed_or_unbounded_sse_never_becomes_success(raw):
    server = Server(
        alter=lambda *args: response(raw, headers={"content-type": "text/event-stream"})
    )
    with pytest.raises(PortfolioReadError):
        asyncio.run(read(server))


@pytest.mark.parametrize("mode", ["response", "aggregate", "length", "notification"])
def test_transport_bounds_are_enforced_before_parsing(monkeypatch, mode):
    if mode == "aggregate":
        monkeypatch.setattr(reader_module, "MAX_TOTAL_BYTES", 20)

    def alter(request, body, message, headers):
        if mode == "response":
            return response(b"x" * (MAX_RESPONSE_BYTES + 1))
        if mode == "length":
            return response(
                encode(message), headers={"content-type": "application/json", "content-length": "1"}
            )

    server = Server(alter=alter)

    def handle(request):
        if (
            mode == "notification"
            and json.loads(request.content)["method"] == "notifications/initialized"
        ):
            return response(b"not empty", 202)
        return server(request)

    with pytest.raises(PortfolioReadError):
        asyncio.run(read(handle))


@pytest.mark.parametrize("cancel", [False, True])
def test_deadline_and_cancellation_close_stream_and_release_capacity(monkeypatch, cancel):
    monkeypatch.setattr(reader_module, "READ_SECONDS", 0.02)
    stream = Chunks([], wait=True)
    gate = ReadGate()

    async def scenario():
        reader = IndmoneyPortfolioReader(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=stream
                )
            ),
            gate=gate,
        )
        task = asyncio.create_task(
            reader.read(
                tokens(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                validate_access=lambda: None,
                contract=SyntheticContract(),
            )
        )
        if cancel:
            await asyncio.sleep(0)
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else PortfolioReadError):
            await task

    asyncio.run(scenario())
    assert stream.closed
    for _ in range(4):
        gate.acquire()
    for _ in range(4):
        gate.release()


def test_transport_exception_is_sanitized():
    private = secrets.token_hex(16)

    def fail(request):
        raise httpx.ConnectError(private)

    with pytest.raises(PortfolioReadError) as error:
        asyncio.run(read(fail))
    assert private not in str(error.value)


def test_source_number_tokens_are_validated_without_float_rounding():
    def alter(request, body, message, headers):
        if body["method"] == "tools/call":
            raw = encode(message).replace(b'"12.000000000001"', b"123456789012345678.123456789012")
            return response(raw)

    result = asyncio.run(read(Server(alter=alter)))
    quantity = result.pages[0].holdings[0].quantity
    assert quantity.source == "123456789012345678.123456789012"


def test_page_boundary_requires_owned_scope_and_valid_value_objects():
    result = asyncio.run(read(Server()))
    holding = result.pages[0].holdings[0]
    for changes in (
        {"account": "different"},
        {"asset": "us_equity"},
        {"holdings": list(result.pages[0].holdings)},
    ):
        with pytest.raises(PortfolioReadError):
            replace(result.pages[0], **changes)
    for changes in (
        {"quantity": FinancialValue("cash", "1", currency="INR")},
        {"observed_at": "2026-10-24"},
        {"price": holding.quantity},
    ):
        with pytest.raises(PortfolioReadError):
            replace(holding, **changes)
    assert type(result.fetched_at) is FinancialInstant
    assert exact_document(b'{"n":0}')["n"] == JsonNumber("0")
