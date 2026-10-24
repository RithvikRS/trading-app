# Integration plan

Research baseline: 21 October 2026; INDmoney custom-client compatibility checked on 24 October 2026. Public documentation identifies possible interfaces; authenticated access, scopes, data coverage, and automation behavior still need verification against the owner's accounts. No provider connection has been established.

The implemented [connection-status walkthroughs](ui-prototype.md#connections-and-source-coverage-step-2e1) illustrate coverage and recovery using bundled fictional evidence. [Bank and investment samples](import-samples.md) provide fictional evidence inspection, reversible review decisions, and session-only completion receipts. They do not verify a provider API/export format, establish a connection, or change the research baseline below. Simulated permissions and attempts must remain labeled separately from actual capabilities.

## Provider coverage

| Provider or data | Initial approach | Verification before implementation |
| --- | --- | --- |
| INDmoney Indian stocks and ETFs | Prioritize the official read-only portfolio interface; retain INDstocks REST as a separately assessed option | Custom-client eligibility, ETF coverage, source IDs, history depth, scopes, limits and renewal |
| INDmoney US stocks and mutual funds | Evaluate the official read-only MCP connector; use statement imports where necessary | Custom-client access, unattended use, consent lifetime, holdings detail, historical transactions, and terms |
| Advisor mutual funds | Verify linked portfolio coverage first; detailed CAS for missing or incomplete evidence | Actual folios, direct/regular variants, demat versus non-demat coverage, supported periods, and opening balances |
| UBS Accenture ESPP | Statements and available transaction exports | Export formats, purchase dates, fractional units, discounts, basis, dividends, withholding, fees, and transfers |
| HDFC banking | Downloaded statements first; later evaluate automatic emailed statement ingestion | Representative format, account identifiers, transaction references, debit/credit signs, running balances, and delivery frequency |
| SBI banking | Downloaded statements first; later evaluate automatic emailed statement ingestion | The same checks as HDFC, implemented as a separate parser |
| HDFC credit cards | Separate [Step 9](credit-cards-plan.md), starting with one downloaded statement/export format | Card product/layout, billing account versus card identity, cycle/due fields, signs, references, refunds/EMIs, password behavior and actual history coverage; automatic access remains unverified |
| Mutual fund NAVs | AMFI downloads or another documented source | Stable scheme mapping, publication dates, history, permitted usage, and failure behavior |
| Indian/US prices and FX | Official broker data or a suitable documented provider | Instruments, delayed versus live prices, historical coverage, adjusted prices, license, limits, and cost |

## INDmoney and INDstocks

Prioritize the [official read-only portfolio route](indmoney-integration-plan.md) before selecting a mutual-fund statement format. [Compatibility checks](indmoney-compatibility.md) verified local application registration and an authorization handoff. Account access, actual coverage, permitted storage and successful renewal still require verification. Initial Stage 6 work now precedes the remaining Stage 5 file-parser work.

INDstocks documents equity holdings in a demat account and separate trading endpoints. Its FAQ describes 24-hour tokens and a TOTP-based unattended generation path. That path involves sensitive credentials and must not be enabled merely to eliminate a manual renewal step. Prefer a provider-enforced read-only route; a trading-capable token is not made read-only by hiding trade buttons. See [holdings documentation](https://api-docs.indstocks.com/portfolio_funds/) and [authentication FAQ](https://api-docs.indstocks.com/faq/).

INDmoney advertises a read-only MCP connector covering holdings and market data, including investments held in its US account. A dedicated local client registered successfully, but its account access is not yet verified. Complete the protected OAuth flow and confirm the direct backend use, retained data, renewal and transaction-history contract before enabling imports. Session expiry can require reauthorization. External UBS holdings need a separate source. See [INDmoney MCP](https://www.indmoney.com/mcp).

The published MCP tools do not establish a complete transaction ledger. INDstocks documents [order and trade books](https://api-docs.indstocks.com/normal_orders/) for the current trading day; per-order fills do not establish historical backfill coverage. Current holdings and average purchase prices cannot reconstruct a complete transaction ledger. Statements may still be required for historical lots, cash flows, fees, corporate actions, and reliable performance calculations. Tax reports may supplement evidence but are not assumed to contain all holdings or activity. See [INDmoney reports](https://www.indmoney.com/features/tax-centre).

## Mutual funds

AMFI describes consolidated statements through CAMS and KFintech and summary/detailed CAS through MFCentral. Request detailed history for the needed periods and reconcile the result against actual folios. Account linkage, holding form, and available statement periods can affect coverage. Preserve advisor regular plans as distinct from direct plans. See [AMFI CAS guidance](https://www.amfiindia.com/online-center/download-cas).

[Step 5A](amfi-nav-contracts.md) implements bounded parsing of the current eight-column AMFI text report and exact scheme/ISIN/variant matching. It performs no acquisition or persistence. Source dates and unsupported identity/variant fields remain explicit; actual statement compatibility follows the [investment flow plan](investment-flow-plan.md).

NAV refreshes update valuation, not units owned. Units and cash flows change only through validated transactions or explicitly sourced snapshots. AMFI publishes NAV resources; confirm the chosen endpoint and usage conditions before scheduling downloads. See [AMFI NAV resources](https://www.amfiindia.com/net-asset-value/).

## UBS and banking

UBS identifies One Source as its corporate stock-plan portal and provides stock-plan statement support. Direct automatic access for this account is unverified, so statement/export import is the baseline. An ESPP purchase cost and any tax basis supplied by UBS must remain separately identified. See [UBS support](https://www.ubs.com/us/en/wealth-management/contact-us.html).

SBI documents account-statement downloads; HDFC provides email-statement enrollment. Select parsers from representative sanitized exports before promising a format. If email ingestion is later implemented, prefer a dedicated mailbox or narrow authorization and process only identified statement sources. A label or message filter alone does not reduce an OAuth token's mailbox permissions. Delivery may be monthly, so email ingestion cannot promise daily bank balances. See [SBI statements](https://sbi.bank.in/web/faq-s/retail-internet-banking) and [HDFC email statements](https://v.hdfcbank.com/content/dam/hdfc-aem-microsites/common-pdfs/pdf/email_statements.pdf).

India's Account Aggregator framework has regulated participant requirements. A personal application is not assumed to qualify as a financial information user. Evaluate any eligible partner's terms, consent model, coverage, and cost before selecting that route. See [Sahamati FAQ](https://sahamati.org.in/faq/).

## HDFC credit cards

HDFC credit card planning was added on 24 October 2026. Its [mobile banking FAQ](https://www.hdfc.bank.in/need-help/mobile-banking-faqs) describes PDF/XLS/CSV statement downloads; actual exports, field coverage and custom-client/API entitlement have not been verified. Select and test one format before expanding. Monthly statements cannot establish live outstanding or pending authorizations. Card imports do not reuse bank-account sign/balance rules implicitly, collect issuer login credentials, or enable bill payments. See the [card plan](credit-cards-plan.md) for separate statement, payment and privacy boundaries.

## Connector acceptance

For each provider, document authorization type, actual scopes, account identity, allowed destinations, token storage, renewal, revocation, history depth, source identifiers, rate limits, and expected freshness. Confirm permitted programmatic use. Do not base the initial design on reverse-engineered private endpoints or unattended credential scraping.

Use sanitized fixtures and a small authorized read to verify assumptions during connector validation. Test expired authorization, revocation, timeout, rate limiting, malformed data, duplicate delivery, incomplete pages, pagination, and partial failure. Provider errors must not erase the last valid portfolio.

Expose connected account, permission summary, last successful holdings import, last price update, statement coverage period, and actionable errors. Financial data fetched recently can still describe an old statement period; display both dates.

Fallback order is a supported provider interface, a supported export/statement import, then explicit manual entry with provenance. Refresh cadence must reflect what the source can actually deliver.

## Bank sample review boundary

Step 2E.3 completes only bundled bank sample reviews. Row choices, suggested-choice previews, and receipts stay in memory and never receive files or credentials, invoke a provider, or insert financial records. The supplied account/provider identity is fixed; incompatible owner or account data cannot be repaired by choosing another bank. Source formats and actual import/connection permissions remain unverified. Step 2E.4 adds investment examples with the same isolation boundary. Generic snapshots, fund overlap, regular-plan funds, employee lots, and bounded activity examples do not verify INDmoney, consolidated-statement, advisor, or UBS export formats. Supplied openings and zero fees in i14 are fictional walkthrough evidence, not an inference about provider history. See [sample outcomes](import-samples.md#reversible-review-expectations-step-2e3).
