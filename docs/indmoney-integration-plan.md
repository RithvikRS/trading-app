# INDmoney portfolio integration

Prioritize official, provider-enforced read-only access for the first connected investment flow. Validate the INDmoney interface before selecting a mutual-fund statement format. Keep completed financial persistence, NAV contracts, parser transport and account-directory work; statement parsing remains a fallback for missing history and separate providers.

Research checked on 24 October 2026. [Step 6A.2](indmoney-compatibility.md) verified custom-client registration and the authorization handoff. Account access, transaction history and successful token renewal remain unverified; no financial connection is enabled.

Step 6A.1 implements the standalone [public discovery validator](../backend/trading_connectors/indmoney_discovery.py). It is not imported by the API or included in its container. It has no registration, authorization, token, financial-tool or database operation. The later connection steps below remain planned. The separate 6A.2 investigation created one local application registration with encrypted local credential custody, without authorizing a financial account.

## Evidence and limits

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| [Official portfolio interface](https://www.indmoney.com/mcp) | Free customer access, read-only holdings across mutual funds, Indian stocks and INDmoney US holdings; OAuth consent. | Standalone application eligibility, complete history, account-specific coverage, retention permissions or reliable unattended renewal. External US accounts are excluded. |
| [Protected resource metadata](https://mcp.indmoney.com/.well-known/oauth-protected-resource/mcp) | The advertised resource is `https://mcp.indmoney.com/mcp`, issuer `https://mcp.indmoney.com/`, scope `portfolio:read`, bearer tokens in headers. | A granted scope, authenticated account identity or successful data retrieval. |
| [Authorization server metadata](https://mcp.indmoney.com/.well-known/oauth-authorization-server) | Advertises authorization code and refresh grants, S256 PKCE, confidential-client authentication, registration and revocation endpoints. | Registration eligibility, token lifetime, refresh rotation/reuse behavior, redirect rules or scheduled-use entitlement. |
| [INDstocks holdings](https://api-docs.indstocks.com/portfolio_funds/) and [FAQ](https://api-docs.indstocks.com/faq/) | Separate REST integration for Indian demat equities; free API access and 24-hour tokens. | Mutual-fund/US coverage or provider-enforced read-only credentials. Trading capability makes this a separate security decision. |

The 6A.1 public check sent credential-free GET requests to the portfolio endpoint and its two discovery documents. The endpoint returned HTTP 401 with its metadata location; both documents returned JSON. No client was registered, account authorized, token issued or financial tool called. Discovery describes advertised capabilities and can change; it is not an authenticated acceptance test.

The authorization document also advertises `market:read`. Request only `portfolio:read` for the first holdings integration. Any later market access is a separate capability with its own purpose, source permissions and acceptance. Registration and endpoint metadata are untrusted until validated against fixed provider policy.

## Delivery sequence

Retain existing step numbers and move initial Stage 6 feasibility ahead of the remaining Stage 5 statement work. Each increment uses the existing conventional commit and `dev` to `main` PR workflow.

| Step | Deliverable | Acceptance |
| --- | --- | --- |
| 6A.1 | Public discovery validation; implemented | Fixed HTTPS issuer/resource/endpoints, bounded strict JSON, exact required capabilities, no redirects, credentials, arbitrary URLs or provider login. Tests reject destination substitution, malformed/oversized responses and unsupported security capabilities. |
| 6A.2 | [Compatibility findings](indmoney-compatibility.md); public portion complete | Registration and handoff verified; source-history, successful renewal, protocol/schema and account checks remain open until the protected authorization flow exists. |
| 6B | Owned authorization and encrypted credential custody | MFA/session-bound initiation; single-use state and PKCE; fixed callback and issuer/resource validation; encrypted credentials bound to owner, connection and provider; renewal/revocation races, recovery and audit tests. |
| 6C | Bounded portfolio reader | Fixed read-only calls through a deterministic Python client, strict exact-value validation, complete pagination or explicit incomplete coverage, source timestamps and sanitized errors. Failed reads preserve prior evidence. |
| 6D | Reviewed snapshots and connected investment views | Explicit account/instrument/source mappings, overlap review, atomic snapshot completion and receipts, visible coverage/freshness in the protected UI. Repeated imports do not multiply holdings. |
| 6E | Historical coverage and statement fallback | Add activity only when an independently verified source contract supplies it. Choose a statement format for gaps; retain folio/plan, native cash, fee and lot evidence without fabrication. |
| 6F | Connection acceptance and recovery | Authorized owner-side smoke test, expiry/revocation and partial-failure behavior, two-owner isolation, encrypted restore, browser privacy and resource measurements. Record hosted and account-specific evidence separately. |

Stage 10 remains responsible for durable schedules. A refresh grant may support renewal, but does not by itself implement a scheduler or guarantee unattended access. Stage 5 file intake/adapter work resumes for verified gaps; UBS, banking and credit cards retain their separate stages.

## Implemented discovery boundary

`validate_metadata` accepts only the two bounded public JSON documents. Duplicate keys, non-UTF-8 input, unexpected fields, numeric/non-finite values, incompatible types and substituted destinations fail with a fixed error. Endpoint strings are compared exactly. This deliberately narrow provider contract requires review when metadata changes; it is not a general OAuth discovery library. Refresh and registration advertisements may be absent and are reported as absent, never assumed.

`discover` makes two sequential GET requests to fixed metadata URLs with verified TLS, no redirects or ambient proxy credentials, no cookie forwarding, no compressed responses and no retries. Each document is limited to 16 KiB; an asynchronous 10-second deadline covers the whole attempt, with shorter transport timeouts and cancellation propagation. A failed second document cannot produce partial success. One connection is allowed per attempt; application-wide admission remains part of a future enabled connector. Responses remain in memory and return only three capability flags.

The 94 focused tests use synthetic HTTP responses and cover destination changes, broad scopes, missing PKCE, duplicate/malformed JSON, transport errors, response bounds, timeout cleanup and cancellation. A separate public-network check of this implementation on 24 October returned refresh and registration advertised, response-issuer support not advertised. These flags describe metadata only. CI does not call INDmoney.

## Authentication and custody

Use the application's Python backend as the OAuth client. The browser navigates to the provider's own sign-in and consent screen. Provider MPINs, passwords, OTPs and TOTP seeds never enter application forms or storage. Financial accounts connect only through the application. The planned path is provider to application backend to owned storage and protected UI.

Follow the [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) for the negotiated protocol version. Client registration is distinct from user authorization. The observed metadata advertises dynamic registration; its presence alone does not establish an eligible client. The 6A.2 registration check succeeded for the local callback. Complete the protected callback, real token exchange and account-specific acceptance before enabling an import.

Initiation must require current MFA, signed CSRF, exact same-origin controls and checked workspace context. Bind a short-lived, single-use attempt to the owner, current session, expected issuer, resource, callback, requested scopes and PKCE verifier. An OAuth callback is a dedicated cross-site response boundary; it cannot weaken existing financial routes. Reject duplicate parameters, mismatched state/issuer, expired or replayed attempts, replacement sessions and unexpected granted permissions. Prevent callback codes and error details from entering access logs, analytics, browser history beyond the redirect, or referrers.

Store access/refresh tokens and any client secret only in encrypted server custody, with purpose/owner/connection-bound encryption and keys held separately from the database. Do not reuse Supabase tokens or session encryption purposes for a financial provider. Exclude secrets from repr, exception output, audit payloads, URLs, browser persistence and source control. Forward migrations, forced ownership policies, least privileges, recovery-format coverage and key rotation tests accompany any new durable state.

Serialize renewal per connection and compare connection revision before publishing refreshed credentials or fetched data. Disconnect and owner/session revocation must defeat in-flight reconnect, token-refresh and import races. Separate local access removal from confirmed provider revocation; an unavailable revocation endpoint must not leave the local connection usable. Reconnect is explicit and cannot silently change account identity. Provider tokens and financial data are never supplied to CI or code-review tools.

## Data and execution boundary

Use a fixed allowlist of structured read capabilities. A deterministic client can speak the protocol without a language model. Do not dynamically execute returned instructions, arbitrary tool names, code, URLs or provider-suggested credential flows. Require reviewed schemas and reject incompatible changes. No trading client, order endpoint or stored trading credential belongs to this connection.

Fix and validate HTTPS destinations; disallow arbitrary redirects, ambient proxies/credentials and user-supplied endpoints. Verify certificates. Bound response bytes, pages, nesting, concurrency, time and retries. Never perform provider I/O while holding a financial database lock. Apply rate-limit backoff without exposing provider response bodies or accumulating an unbounded retry queue.

Preserve decimal tokens exactly before conversion into existing financial contracts; do not round through binary floats. Validate identifiers, units, currencies, timestamps and pagination before normalization. Treat supplied totals, invested amounts, returns and valuations as source claims with provenance, not recomputed accounting facts. Unknown cost basis remains unknown. Incomplete pagination cannot clear absent holdings or produce a complete-account snapshot.

Resolve account/folio and instrument identity explicitly. A fund's direct/regular plan and growth/distribution option remain distinct; names and similar amounts do not establish identity. Linked external holdings can overlap direct-source statements. Choose source evidence explicitly and preserve the alternatives rather than adding both positions together. Reject unsupported instruments or currencies visibly; never discard them while labeling the import complete.

A current holding cannot establish its purchases, fees, dividends, cash movements, realized gains or tax lots. Do not derive a transaction ledger from daily snapshot differences. Keep provider observation time, import time and price time separate. A fresh fetch with an old or unknown observation date remains old or undated evidence. UBS ESPP requires its own source. Advisor funds require verified linkage and folio/variant detail or a statement fallback; bank/card summaries cannot substitute for detailed account activity.

## Readiness and user experience

Until authenticated acceptance, expose the route as unconfigured rather than connected. Later screens should show the connected account, actual read permissions, scope of coverage, last successful holdings refresh, price date, renewal need and disconnect outcome. Preserve prior valid data on failure with an explicit stale state. Native amounts remain inspectable when reporting-currency conversion is unavailable.

Local tests use fabricated provider responses; public discovery checks contain no account data. Account acceptance happens through the application in the owner's environment after custody and callback protections are verified. It must confirm source identity, precision, multiple funds/markets, empty versus incomplete results, revoked access, refresh behavior and provider-side disconnection. Compatibility, terms and actual account access remain unresolved until supported by evidence; no credentials or personal statements are needed in development conversations.
