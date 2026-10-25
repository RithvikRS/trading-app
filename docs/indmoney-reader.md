# Bounded INDmoney portfolio reader

Step 6C implements the internal [reader engine](../backend/trading_connectors/indmoney_reader.py) and [exact evidence contracts](../backend/trading_connectors/portfolio_contracts.py). It has no application route, persistence, scheduler or live adapter. Existing authorization controls continue to report financial access disabled. A call without a reviewed adapter fails before credential use or network access.

The engine is implemented and tested; live provider compatibility is still open. The [official guide](https://www.indmoney.com/mcp), rechecked on 24 October 2026, names `networth_holdings` and describes position information, but does not supply its machine schemas or pagination contract. The earlier [unauthenticated probe](indmoney-compatibility.md) returned HTTP 401. No authenticated schemas, account records or permission grants were obtained for this increment. Fabricated test schemas must never become a production adapter merely because tests pass.

## Read boundary

Each attempt opens a verified-TLS client against exactly `https://mcp.indmoney.com/mcp`. It initializes the supported MCP `2025-11-25` version, sends the initialized notification, finishes a bounded tool catalog and invokes only `networth_holdings`. This restricted client follows the official [lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) and [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) contracts. That protocol version has not been negotiated with INDmoney.

The client advertises no callback capabilities. Server instructions, descriptions and URLs are inert. It never dispatches server requests, follows resource links, invokes other tools or discovers new destinations. Tool annotations must claim read-only behavior, but annotations alone cannot authorize a call: the fixed name and locally reviewed input/output schemas must match. Missing schemas, changed fields, conflicting annotations and incomplete catalogs stop before holdings are called. No trading interface is used.

An adapter is trusted application code with a revision, pinned schema bytes, fixed argument construction and a strict decoder. It cannot be supplied through a browser request, environment variable, remote schema or plugin registry. The engine compares observed schemas with reviewed local documents; it never evaluates schema code or resolves references. The decoder must validate the actual financial payload and reject unsupported fields or rows. Only a fabricated adapter exists, under `backend/tests/`.

Bearer credentials travel only in the Authorization header. Refresh tokens and client secrets are never sent to the resource. Redirects, ambient proxies, cookies, compression and automatic retries are disabled. A bounded session ID is accepted only at initialization and remains private to that attempt. Substitution, expiry and authentication errors abort the read. There is no automatic session restart, legacy transport fallback, stream resumption or renewal.

JSON and incremental SSE responses are supported. A response must have the matching integer request ID and a single successful JSON-RPC result. Errors, unsolicited messages, unsupported content, text-only results and malformed frames fail with a fixed message. Structured output is authoritative; compatibility text is never parsed as financial data. The stream closes when its result arrives. This narrow client may reject otherwise valid MCP features; unsupported behavior requires a reviewed compatibility change.

## Resource bounds

| Boundary | Limit |
| --- | --- |
| Whole read, including all pages | 20 seconds; transport operations have a 3-second timeout |
| Active reads per process | 4; immediate rejection when full, no waiting queue |
| Request body | 8 KiB |
| Response headers | 64 fields and 16 KiB of names/values |
| One response / whole attempt | 256 KiB / 2 MiB |
| Tool catalog | 4 pages, 64 entries per page; duplicate names/cursors rejected |
| Holdings scope | 10 pages and 2,000 accepted rows |
| JSON | 16 nesting levels, 20,000 nodes, 128 members per object, 2,000 items per array, 64 KiB per string, 64 characters per numeric token |
| SSE | 16 frames per response, within the same byte/time bounds |
| Rate response | HTTP 429/503 establishes process-wide cooldown; valid Retry-After is clamped to 1–300 seconds, otherwise 60 seconds |

Cooldown blocks attempts without sleeping or retrying. These are process-local safeguards, not durable per-owner admission or a distributed scheduler. Future route integration must add owned admission and operation-revision guards. Cancellation propagates, closes the client/stream and releases capacity.

## Exact evidence and coverage

JSON numeric tokens retain their original text, including trailing zeros, negative zero and exponent spelling. Financial values never pass through a binary float. Conversion into the existing [financial contracts](financial-values.md) requires supported plain decimal notation; unsupported exponents, precision, magnitudes or currencies fail instead of being rounded or repaired.

The internal evidence shape supports Indian/US equity and mutual-fund positions with explicit private account/instrument keys, native INR/USD values, nonnegative units, reported prices and known or explicitly missing acquisition cost. An invested-value field must not map to acquisition cost without verified semantics. Missing values stay missing; reported zero/negative prices remain unusable evidence. Fund folio, direct/regular plan and growth/distribution option remain distinct. Source keys are not application mappings or proof of owner identity.

Each read covers one adapter-defined account and asset scope. Pages must agree on scope and source observation time; duplicate holding identities or cycling cursors abort the attempt. Row observation and price timestamps remain independent. Unknown source dates stay unknown. `fetched_at` records receipt time and cannot make old evidence fresh. Results retain the adapter revision and pinned-schema digest for subsequent provenance.

`source_complete` requires a terminal page with an explicit complete-coverage claim. An absent cursor or empty list alone is insufficient. A source-incomplete terminal page, page cap or cumulative row cap returns `incomplete`, its reason and only accepted pages. This never authorizes clearing absent holdings. Malformed data, transport failure, changed scope, access loss and timeouts raise without returning earlier pages. The reader has no database writes and cannot alter prior financial evidence.

Every result has `import_ready = false`. Complete pagination describes only the requested source scope; it does not establish all-account coverage, application identity mappings, overlap resolution, tax basis, transaction history or reconciliation. Those belong to [Step 6D and later](indmoney-integration-plan.md). No transaction, dividend, fee or lot is inferred from a position.

## Integration and remaining acceptance

The internal `read` method takes a private token bundle, absolute expiry and synchronous access validator. It checks that validator and expiry before and after each request and before returning evidence. A future service must bind the validator to the original owner, browser session, client registration and connection revision, using short database checks without locks during provider I/O. Final persistence must recheck the same state atomically. The access-loss tests do not claim a new database read lease or publication route.

Live enablement requires locally configured owner sign-in, verified protocol/schemas, native precision and timestamps, account/folio/variant semantics, complete pagination and permitted application use/retention. Implement a versioned adapter from that evidence, with tests for supported and rejected variants. Reuse the existing local registration; do not register clients during tests or expose credentials or personal payloads in conversations, CI or logs.

Step 6C introduced no migration or dependency change: its schema head was `0018_indmoney_authorization` and its recovery format was 14, with connector credentials omitted. Later schema/format changes are recorded in the [current recovery runbook](local-packaging.md#encrypted-foundation-recovery). No live request, account authorization, registration, credential transfer or financial import was performed for Step 6C. Provider contract acceptance precedes reviewed snapshot integration; this engine does not remove that dependency.

## Verification

[Reader tests](../backend/tests/test_indmoney_reader.py) cover JSON/SSE lifecycle, fixed destinations/calls, schema drift, exact numeric tokens, unknown basis, currency and fund identity rejection, empty versus incomplete coverage, pagination, response/header/aggregate limits, rate backoff, expiry, access loss, cancellation, timeout cleanup and private representations. The fabricated adapter is explicitly labeled in [test support](../backend/tests/portfolio_reader_support.py).

Run the focused test from `backend/` with the pinned environment: `python -m pytest tests/test_indmoney_reader.py`. The normal [five verification groups](verification.md) include these tests. No frontend behavior changes, so existing UI screenshots are not new reader evidence. Synthetic success demonstrates the engine contract, not live INDmoney compatibility.
