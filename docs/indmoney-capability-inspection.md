# INDmoney capability inspection

The internal [capability inspector](../backend/trading_connectors/indmoney_capabilities.py) prepares the next authenticated check in the [history API assessment](indmoney-history-api.md). It initializes the fixed INDmoney MCP resource and collects tool metadata without invoking a financial tool. This increment uses synthetic responses only; it does not verify a live history capability, source retention, account coverage or provider permissions.

There is no application route, command-line entry point, scheduler, credential lookup, registration, database write, production adapter or dependency change. The existing portfolio reader remains disabled without a locally reviewed contract. The inspector cannot enable it, install an adapter or broaden its tool allowlist.

## Transport and authorization boundary

The inspector reuses the [portfolio reader's](indmoney-reader.md) transport, lifecycle validation, exact JSON parser, complete catalog pagination, process-wide capacity limit and cooldown. Each attempt uses only `initialize`, `notifications/initialized` and `tools/list` at `https://mcp.indmoney.com/mcp`. Its connection rejects `tools/call` before a request is sent, including names advertised as read-only. The separate portfolio reader still permits only its fixed `networth_holdings` call after pinned schema validation.

The caller supplies private server-held token material, an absolute aware expiry and an access validator. Access and expiry are checked before and after every request and again before returning evidence. Capacity is immediate rather than queued. Cancellation propagates, closes the client/stream and releases the slot. Provider or protocol failures return the existing fixed `PortfolioReadError` message without remote text.

Bearer tokens are sent only in the Authorization header to the fixed resource. Verified TLS, disabled ambient proxies/redirects/retries, cleared cookies, identity encoding and private session-ID validation follow the existing reader. The inspector advertises no callback capabilities. It does not dispatch server requests, follow links, resolve schema references or execute descriptions, instructions or newly advertised capabilities.

The shared bounds remain 20 seconds for the attempt, 3 seconds per transport operation, four active attempts per process, 8 KiB requests, 256 KiB responses and 2 MiB total received bytes. A catalog has at most four pages with 64 tools per page. Duplicate tool names, repeated cursors, malformed metadata and unfinished pagination reject the entire result. JSON depth, node, string and numeric-token limits and SSE framing limits remain unchanged. A catalog cursor is opaque request data; even a URL-shaped cursor never changes the destination.

## Private evidence contract

Successful inspection returns a `CapabilityInspection` containing immutable initialization bytes, a tuple of immutable `ToolMetadata` descriptors, receipt time and an evidence digest. Numeric schema tokens preserve their original spelling and precision. The digest identifies the retained metadata bytes; it does not attest provider behavior or schema suitability. Receipt time is not the date of any financial activity.

Descriptors require a valid unique name and an object-valued input schema. Optional output schemas and annotations must be objects; optional titles and descriptions must be strings. Unknown metadata and external schema references are retained as inert data for later local inspection. Read-only/destructive annotations are provider claims, not authorization. Schemas are not evaluated or declared compatible merely because they can be retained.

All descriptor names, descriptions, schemas and initialization metadata remain private, including default object representations. Metadata can contain identifiers or sensitive examples despite being distinct from transaction records. The result is memory-only and is not exported, logged, rendered, sent to a browser or written to disk by this engine. A future review surface must preserve that boundary and explicitly select any non-sensitive evidence to retain.

The inspector and portfolio reader revalidate credential models with serializer warnings suppressed. Malformed copied or constructed token values fail before provider requests and cannot escape through warning text, logs, stdout/stderr or the fixed public exception.

`catalog_complete = true` means the bounded advertised catalog reached its terminal page. An empty catalog says nothing about actual transaction availability, and an advertised history tool says nothing about verified retention or completeness. Every result reports `history_verified = false` and `import_ready = false`. No transactions, snapshots, holdings, account mappings or coverage intervals are created.

## Remaining live verification

Actual inspection still requires configured local HTTPS, application authentication and owner-side provider sign-in through the existing [authorization boundary](indmoney-authorization.md). A future service must bind access validation to the original owner, browser session, registration and connection revision. This engine does not establish that service binding or a durable admission limit.

Before a history adapter is written, review observed schemas and provider terms, prove account and market boundaries, retained date ranges, pagination and completeness, stable occurrence IDs, exact values, date semantics, fees and corrections. Any financial sample call needs its own fixed-name/schema contract and bounded reviewed arguments. Listing a capability never authorizes such a call. The absence of a history name from a catalog also does not prove that no separately supported API exists.

## Verification

[Synthetic capability tests](../backend/tests/test_indmoney_capabilities.py) cover JSON/SSE initialization, private immutable metadata, fixed destinations, inert hostile descriptions/links/schemas, exact numeric tokens, empty and paginated catalogs, duplicate/invalid/oversized catalogs, method allowlists, expiry/revocation, protocol/session failures, shared cooldown and timeout/cancellation cleanup. Malformed token-field regressions cover both engines and assert no diagnostic leakage or provider request. The existing [portfolio-reader tests](../backend/tests/test_indmoney_reader.py) remain regression coverage for its pinned schemas, exact holdings and transport bounds.

From `backend/`, run `python -m pytest tests/test_indmoney_capabilities.py tests/test_indmoney_reader.py`, then the normal lint/type checks and [verification groups](verification.md). Synthetic success demonstrates bounded inspection behavior only. No live account request, owner authorization, token renewal, registration or historical import was performed for this increment.
