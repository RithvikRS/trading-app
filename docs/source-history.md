# Source-history coverage

Step 6E.1 adds source-history inspection to protected investment details. Open a selected snapshot and choose **Inspect source-history coverage**. The page reads the source's saved observations through the existing authenticated `POST /api/v1/finance/imports/observations/query` endpoint.

The view distinguishes holdings snapshots, partial activity, unknown coverage, and a source claim of complete activity. It shows supplied period boundaries and replacement lineage, including superseded evidence. A current version is neither a freshness guarantee nor proof of completeness. A source may cover multiple positions; its period is not automatically the selected holding's acquisition history.

No periods are merged, gaps filled, or overlapping reports added together. Entries retain stable identity ordering with 25-item pages, not an implied chronological order. Empty pages do not establish zero transactions. A source coverage claim does not establish completed ingestion, reconciliation, lifetime history, tax basis or usable returns; completion and reconciliation receipts are separate evidence.

## Security and validation

The existing owner/MFA/CSRF/workspace-context checks, 4 KiB request limit, 256 KiB response limit and no-store headers apply. Source IDs and cursors stay in POST bodies, never URLs. The browser validates exact source scope, bounded IDs, booleans, coverage kinds, real calendar dates, paired and ordered periods, and replacement identity. Wrong-source responses lock the workspace. Private data stays in memory and late responses cannot restore a locked or replaced workspace.

This increment adds no backend route, database write, provider call, schema migration or credential. Returning to positions reloads their current resolved evidence. Tests cover malformed dates/claims, unknown periods, scope mismatch, superseded history, pagination without old-page retention, and accessibility. Synthetic browser checks cover light/dark desktop/mobile layouts, keyboard opening, contrast, reflow, empty browser storage and sign-out clearing.

| Mode | Desktop | Mobile |
| --- | --- | --- |
| Light | [Image](images/source-history/history-1440-light.png) | [Image](images/source-history/history-390-light.png) |
| Dark | [Image](images/source-history/history-1440-dark.png) | [Image](images/source-history/history-390-dark.png) |

## Historical acquisition boundary

Public documentation rechecked on 25 October 2026: the [INDmoney tool guide](https://www.indmoney.com/mcp) describes holdings, portfolio summaries, SIP information and market data, but does not document a complete transaction-ledger contract. That omission does not prove no additional capability exists. The separate [INDstocks order/trade-book documentation](https://api-docs.indstocks.com/normal_orders/) describes current-day views and per-order fills; it does not establish full mutual-fund/US historical coverage.

Step 6E.2 [checks transaction-history APIs first](indmoney-history-api.md). The public specification assessment is complete; authenticated capability and history verification remain open. Select a detailed statement format only for verified API gaps. Check account/folio and instrument identity, source dates and timezone, stable occurrence references, exact units/currencies/signs, fees, cancellations, cash boundaries, pagination and retained history. Source holdings, price candles and SIP status cannot substitute for executed transactions.

No dedicated hosted authentication project, authorized INDmoney account or verified detailed statement layout is configured for this application. Production acquisition remains gated. Statement-format selection is deferred while API verification is pursued; credentials, personal statements and account identifiers do not belong in development conversations or Git. A subsequent adapter must use the existing isolated parser/transport, owned staging and reviewed completion boundaries, and keep unsupported or incomplete evidence explicit.
