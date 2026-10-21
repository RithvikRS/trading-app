# Integration plan

Research baseline: 21 October 2026. Public documentation identifies possible interfaces; authenticated access, scopes, data coverage, and automation behavior still need verification against the owner's accounts. No provider connection has been established.

The implemented [connection-status walkthroughs](ui-prototype.md#connections-and-source-coverage-step-2e1) illustrate coverage and recovery using bundled fictional evidence. [Bank sample previews](import-samples.md) also provide read-only fictional evidence inspection; decisions, completion, and investment samples remain planned. They do not verify a provider API/export format, establish a connection, or change the research baseline below. Simulated permissions and attempts must remain labeled separately from actual capabilities.

## Provider coverage

| Provider or data | Initial approach | Verification before implementation |
| --- | --- | --- |
| INDmoney Indian stocks and ETFs | Evaluate official INDstocks holdings and market-data endpoints | Account eligibility, ETF coverage, trade-history depth, source IDs, token scopes, rate limits, and renewal |
| INDmoney US stocks and mutual funds | Evaluate the official read-only MCP connector; use statement imports where necessary | Custom-client access, unattended use, consent lifetime, holdings detail, historical transactions, and terms |
| Advisor mutual funds | Detailed CAMS/KFintech/MFCentral consolidated account statement | Actual folios, direct/regular variants, demat versus non-demat coverage, supported periods, and opening balances |
| UBS Accenture ESPP | Statements and available transaction exports | Export formats, purchase dates, fractional units, discounts, basis, dividends, withholding, fees, and transfers |
| HDFC banking | Downloaded statements first; later evaluate automatic emailed statement ingestion | Representative format, account identifiers, transaction references, debit/credit signs, running balances, and delivery frequency |
| SBI banking | Downloaded statements first; later evaluate automatic emailed statement ingestion | The same checks as HDFC, implemented as a separate parser |
| Mutual fund NAVs | AMFI downloads or another documented source | Stable scheme mapping, publication dates, history, permitted usage, and failure behavior |
| Indian/US prices and FX | Official broker data or a suitable documented provider | Instruments, delayed versus live prices, historical coverage, adjusted prices, license, limits, and cost |

## INDmoney and INDstocks

INDstocks documents equity holdings in a demat account and separate trading endpoints. Its FAQ describes 24-hour tokens and a TOTP-based unattended generation path. That path involves sensitive credentials and must not be enabled merely to eliminate a manual renewal step. Prefer a provider-enforced read-only route; a trading-capable token is not made read-only by hiding trade buttons. See [holdings documentation](https://api-docs.indstocks.com/portfolio_funds/) and [authentication FAQ](https://api-docs.indstocks.com/faq/).

INDmoney advertises a read-only MCP connector covering holdings and market data, including investments held in its US account. This is a candidate data interface. Verify whether a deterministic backend client is supported and permitted, and whether refresh, scheduled access, and complete transaction history are available. Session expiry can require reauthorization. External UBS holdings need a separate source. See [INDmoney MCP](https://www.indmoney.com/mcp).

Current holdings and average purchase prices cannot reconstruct a complete transaction ledger. Statements may still be required for historical lots, cash flows, fees, corporate actions, and reliable performance calculations. Tax reports may supplement evidence but are not assumed to contain all holdings or activity. See [INDmoney reports](https://www.indmoney.com/features/tax-centre).

## Mutual funds

AMFI describes consolidated statements through CAMS and KFintech and summary/detailed CAS through MFCentral. Request detailed history for the needed periods and reconcile the result against actual folios. Account linkage, holding form, and available statement periods can affect coverage. Preserve advisor regular plans as distinct from direct plans. See [AMFI CAS guidance](https://www.amfiindia.com/online-center/download-cas).

NAV refreshes update valuation, not units owned. Units and cash flows change only through validated transactions or explicitly sourced snapshots. AMFI publishes NAV resources; confirm the chosen endpoint and usage conditions before scheduling downloads. See [AMFI NAV resources](https://www.amfiindia.com/net-asset-value/).

## UBS and banking

UBS identifies One Source as its corporate stock-plan portal and provides stock-plan statement support. Direct automatic access for this account is unverified, so statement/export import is the baseline. An ESPP purchase cost and any tax basis supplied by UBS must remain separately identified. See [UBS support](https://www.ubs.com/us/en/wealth-management/contact-us.html).

SBI documents account-statement downloads; HDFC provides email-statement enrollment. Select parsers from representative sanitized exports before promising a format. If email ingestion is later implemented, prefer a dedicated mailbox or narrow authorization and process only identified statement sources. A label or message filter alone does not reduce an OAuth token's mailbox permissions. Delivery may be monthly, so email ingestion cannot promise daily bank balances. See [SBI statements](https://sbi.bank.in/web/faq-s/retail-internet-banking) and [HDFC email statements](https://v.hdfcbank.com/content/dam/hdfc-aem-microsites/common-pdfs/pdf/email_statements.pdf).

India's Account Aggregator framework has regulated participant requirements. A personal application is not assumed to qualify as a financial information user. Evaluate any eligible partner's terms, consent model, coverage, and cost before selecting that route. See [Sahamati FAQ](https://sahamati.org.in/faq/).

## Connector acceptance

For each provider, document authorization type, actual scopes, account identity, allowed destinations, token storage, renewal, revocation, history depth, source identifiers, rate limits, and expected freshness. Confirm permitted programmatic use. Do not base the initial design on reverse-engineered private endpoints or unattended credential scraping.

Use sanitized fixtures and a small authorized read to verify assumptions during connector validation. Test expired authorization, revocation, timeout, rate limiting, malformed data, duplicate delivery, incomplete pages, pagination, and partial failure. Provider errors must not erase the last valid portfolio.

Expose connected account, permission summary, last successful holdings import, last price update, statement coverage period, and actionable errors. Financial data fetched recently can still describe an old statement period; display both dates.

Fallback order is a supported provider interface, a supported export/statement import, then explicit manual entry with provenance. Refresh cadence must reflect what the source can actually deliver.
