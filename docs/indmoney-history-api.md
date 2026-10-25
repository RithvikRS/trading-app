# INDmoney transaction-history API assessment

Step 6E.2 investigates API acquisition before choosing a statement format. Public sources checked on 25 October 2026 do not yet establish a supported historical ledger for the required Indian-stock, US-stock/ETF and mutual-fund accounts. This is a documentation finding, not proof that an authenticated or separately supported capability is unavailable. Historical ingestion remains disabled.

## Published capabilities

| Source | Finding | Effect on history acquisition |
| --- | --- | --- |
| [INDmoney portfolio tool reference](https://www.indmoney.com/mcp) | Its 14 advertised capabilities cover portfolio snapshots/holdings, SIP information and market data. No account transaction-history tool or backfill contract is documented. | Indian, US and mutual-fund holdings access does not establish their purchase/redemption, dividend, fee or cash history. |
| [INDstocks order/trade books](https://api-docs.indstocks.com/normal_orders/) | Both books describe the current trading day. The trade book takes a segment, with no documented date range or continuation parameter. | Potential same-day Indian-market fills; insufficient for historical backfill. Missed days cannot be reconstructed by polling later. |
| [Per-order fills](https://api-docs.indstocks.com/normal_orders/#get-trades) | Requires an existing order ID and segment; retention is unspecified. | A known-order lookup does not enumerate older orders or prove complete account history. |
| [Historical Data API](https://api-docs.indstocks.com/historicalData/) | Instrument price/volume candles, including expired derivatives. | Its date ranges describe market data, not the owner's transactions. |
| [Portfolio API](https://api-docs.indstocks.com/portfolio_funds/) and [funds API](https://api-docs.indstocks.com/Users/) | Current holdings, open positions and available/utilized funds. | These summaries cannot substitute for an activity ledger. |

The published [OpenAPI specification](https://api-docs.indstocks.com/openapi-spec.yaml) contains 27 paths and 28 HTTP operations. Inspection found no documented US-stock or mutual-fund account-activity endpoint, nor a dated transaction/statement/ledger backfill operation. The [full reference](https://api-docs.indstocks.com/llms-full.txt) was also searched for historical activity. A generic description of trade history does not override an endpoint's current-day restriction.

There is a documentation inconsistency: the [overview](https://api-docs.indstocks.com/api-overview/) lists `/trades/{order_id}`, while the detailed order guide and OpenAPI specify `GET /order/trades` with a JSON body. Verify the supported route and retention before implementing a client; neither spelling establishes historical coverage.

The [observation record](evidence/indmoney-history-api-2026-10-25.json) identifies the downloaded public specification by hash and size. This assessment used public documentation only. It made no authenticated API calls, registrations or token requests, and did not access the existing encrypted research registration. It does not claim that any endpoint was exercised successfully against an account.

## Next verification

Keep API acquisition first and statements as a fallback for verified gaps. The next capability check needs the existing [protected authorization flow](indmoney-authorization.md), configured local HTTPS and application authentication, and owner-side provider sign-in. No Supabase project or INDmoney account authorization is currently configured. Credentials and financial payloads stay in the application backend and its protected custody.

The internal [capability inspector](indmoney-capability-inspection.md) now implements bounded initialization and complete tool-catalog collection through server-held credentials. Its connection rejects every financial tool call. Names, descriptions, instructions and schemas remain immutable private evidence; links and schema references are inert. This engine has synthetic verification only and no application route or credential-loading command. Actual authenticated inspection, provider protocol/schema compatibility and any transaction-history capability remain unverified. Every result reports `history_verified = false` and `import_ready = false`; neither an advertised name nor a complete catalog establishes retained activity or source completeness.

For any history capability, verify markets/account boundaries, earliest retained dates, pagination and completeness, stable occurrence IDs, exact amounts/units/currencies, execution versus settlement dates, fees, cash movements and corrections. Compare a bounded owner-side sample with the provider's records before enabling staging. A partial result remains partial; snapshots and SIP status never become inferred trades.

The separate INDstocks trading token is not a substitute for the portfolio read scope. Read endpoints and static-IP restrictions do not establish narrowly scoped credentials. Resolve missing history or retention details through provider documentation/clarification or authenticated evidence before enabling an adapter. Only confirmed gaps proceed to a detailed statement-format investigation.
