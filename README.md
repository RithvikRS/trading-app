# Trading app

A personal finance workspace for Indian and US investments, employee shares, and everyday banking. Security comes first, followed by financial accuracy, recoverability, and a clear interface.

## Current progress

The Overview and Investments prototype runs locally with fictional data. It includes responsive Indigo & Apricot light/dark themes, INR/USD display, amount masking, allocation, dated value history, expandable accounts, and activity. Investments adds 14 account-specific holdings with search, combined filters, sorting, reporting-currency prices/NAVs with labeled originals, portfolio weights, and separate source dates. Each holding opens a detail view with source information, selected sample activity, fund identity, and UBS ESPP lots where applicable. Screens handle loading, empty, partial/stale, and failed-load states.

Banking adds HDFC/SBI booked balance snapshots, 58 fictional transactions across August to October (28 in the default October view), combined activity filters, statement reconciliation, and an inspector for original transaction records. It distinguishes posted/pending entries, incomplete coverage, and original source evidence. The INR/USD control applies across summaries, charts, expanded accounts, prices/NAVs, holding activity, ESPP lots, banking rows, reconciliation, and inspection. Converted records use dated demo FX for display only; original source amounts remain labeled. Transfer review adds explainable candidates, explicit pair confirmation, dismissal/restore, unlink, undo, and reset. Decisions update effective classifications and the Overview excerpt while source records and balances remain unchanged; they stay in memory until reload. Category review adds supplied suggestions, individual and bulk corrections with previews, shared undo, and a classified-spending preview with verified refunds and unresolved coverage. Original categories remain visible in inspection. No financial account is connected. A separate local API scaffold now provides liveness and safe configuration. A separate local PostgreSQL service and migration baseline are implemented. The separate backend now supports opt-in authentication and browser sessions. Production imports, connected financial views, and deployment remain planned.

Budgets adds October category limits, exact INR editing, separate undo/reset, and actual-spending breakdowns linked to the same source records and category decisions. Missing classifications or activity make remaining amounts provisional. The workspace supports both themes, INR/USD, and amount masking, including edit fields and progress bars. Limits and decisions remain in memory until reload. Cash flow adds three months of reconciled statement history, account filters, selectable monthly/daily charts with tables, matching-day comparisons, source inspection, and a bridge from classified activity to bank movement. October is month-to-date; missing coverage and unresolved classifications stay explicit. Recurring review adds seven supplied monthly patterns with source evidence, confirm/dismiss/restore, independent undo/reset, and expected commitments for the rest of October. Fixed amounts and variable ranges stay separate; missing or changed evidence retains the decision and requires review. Expected expenses never change actual spending or balances.

Connections adds six source inspectors with separate financial, statement, quote/NAV, and FX dates. Two local connector walkthroughs demonstrate successful, missing, partial, failed, rate-limited, expired, and revoked scenarios; four statement examples have no simulated authorization. Attempts and receipts never change financial records or other review decisions. Sample imports adds seven HDFC/SBI examples with source coverage, whole-batch counts, posted/pending totals, and read-only row inspection. Original and normalized fields, duplicate/overlap evidence, conflicting versions, and invalid values remain distinct. No records are imported or saved.

Investment samples distinguish positions, activity, cash, and remaining lots. Same-folio source preferences retain one snapshot; regular/direct funds and Accenture positions at different accounts remain separate. Missing fees, acquisition history, and tax basis stay unknown. Completion records only a scoped sample receipt, and bank/investment reviews share undo/reset without changing portfolio totals.

## Run locally

Use Node.js 22.22.2 or newer in the Node 22 release line, with npm 12. From the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open [the local prototype](http://127.0.0.1:5173), [Investments](http://127.0.0.1:5173/#/investments), [Banking](http://127.0.0.1:5173/#/banking), [Budgets](http://127.0.0.1:5173/#/budgets), [Connections](http://127.0.0.1:5173/#/connections), a [bank sample preview](http://127.0.0.1:5173/#/connections/imports/i01), an [investment sample](http://127.0.0.1:5173/#/connections/imports/i10), or a [sample transaction](http://127.0.0.1:5173/#/banking/t08). The server binds to loopback only. Use **Explore the demo** at the bottom to switch fixture states. Theme, currency, and amount masking are saved locally; financial records and search/filter state are not stored in browser storage. Masking also hides units, quotes, purchase amounts, fees, bank activity values, and raw narration/reference in transaction inspection. Import masking also removes source descriptions, all original source fields, matching financial evidence, and search text.

```sh
npm run check       # tests, TypeScript checks, and production build
npm run preview     # local production preview at http://127.0.0.1:4173
```

The FX rate is fixed and fictional. The history shows asset values, including cash-flow effects; it does not calculate investment returns. Amount masking provides visual privacy, not access control. Never put real records or credentials into the prototype.

## Direction

[Step 3A](docs/api-foundation.md) implements the local FastAPI scaffold with locked Python dependencies, loopback-only startup, validated configuration, and sanitized errors/logs. [Supabase Auth on Free](docs/authentication-options.md) is selected for password and TOTP verification. Follow the [Python setup commands](docs/development.md#local-python-api) to run `GET /api/v1/health/live`; the fictional prototype remains independent. [Step 3B](docs/verification.md) adds shared local checks and CI for Python, the frontend, and repository security. [Step 3C](docs/database-foundation.md) adds local PostgreSQL, separate disposable database tests, restricted roles, and transactional migrations. [Step 3D](docs/ownership-isolation.md) adds internal owner mapping, forced row-level security, and isolated preference transactions with connection cleanup. [Step 3E.1](docs/authentication-foundation.md) implements the server-side Supabase password/TOTP adapter and restricted enrollment with local tests. No Supabase project is configured and no hosted authentication check has run. [Step 3E.2](docs/browser-sessions.md) adds encrypted server sessions, browser CSRF/origin controls, durable admission, revocation, recovery, and sanitized security events. Authentication remains opt-in. [Step 3F.1](docs/protected-workspace.md) adds a separate protected frontend with sign-in, MFA, restricted recovery, session controls, and an empty workspace. It runs through the API at the same origin and never loads fictional balances. [Step 3F.2](docs/display-preferences.md) persists account display preferences with owner-scoped validation, conflict review, and session-aware saves. [Step 3G](docs/local-packaging.md) adds the restricted local HTTPS package, resource measurements, encrypted synthetic recovery, and a [Supabase readiness checklist](docs/supabase-readiness.md). Hosted integration remains future work. [Step 4](docs/financial-data-plan.md) covers the financial model and persistence in small increments. [Step 4A](docs/financial-values.md) implements exact value/date contracts and bounded arithmetic with synthetic tests; [Step 4B](docs/accounts-source-mappings.md) adds owned accounts, protected source references, versioned mappings and expanded recovery. [Step 4C](docs/instrument-identities.md) adds instrument/fund/listing identities, provider mappings and account positions. [Step 4D.1](docs/import-staging.md) adds immutable source evidence, exact staged rows and revisioned review decisions. [Step 4D.2](docs/financial-events.md) adds exact source-linked events and distinct posted/pending native movements. [Step 4D.3](docs/lot-evidence-corrections.md) adds sourced lot observations and retained correction, cancellation and reinstatement history. [Step 4E.1](docs/snapshot-evidence.md) adds dated snapshots, retained precision and explicit source selection. [Step 4E.2](docs/market-evidence.md) adds exact quote/NAV and directed FX observations, corrections and explicit selection. [Step 4F.1](docs/event-evidence.md) adds protected transaction references and exact corroborating evidence links. [Step 4F.2](docs/reconciliation-contracts.md) adds exact source/combined-state reconciliation contracts. Connected views remain planned. [Step 4F.3.1](docs/statement-boundaries.md) retains explicit statement boundaries and cash date basis. [Step 4F.3.2a](docs/completion-preflight.md) adds strict completion manifests and serialized owner-state guards. [Step 4F.3.2b](docs/completion-receipts.md) atomically completes partial/unknown/snapshot evidence with immutable receipts and exact retries. [Step 4F.3.2c](docs/reconciled-completion.md) adds full source-period reconciliation with immutable comparison inputs. [Step 4G.1](docs/financial-reads.md) adds authenticated account/source/instrument/position identity reads with bounded JSON pagination. [Step 4G.2a](docs/event-lot-reads.md) adds exact event/lot evidence and retained correction history. [Step 4G.2b](docs/snapshot-market-reads.md) adds dated snapshot/market observations, listings and selection history/resolution. [Step 4G.3a](docs/import-review-reads.md) adds source, normalized row and review inspection. [Step 4G.3b](docs/completion-receipt-reads.md) completes protected receipt/comparison reads and synthetic persistence acceptance; the protected frontend remains empty until Stage 5.

[Step 2D](docs/budgets-prototype-plan.md) provides monthly category budgets, historical cash-flow analysis, and recurring-expense review (2D.1–2D.3). [Step 2E.1](docs/imports-prototype-plan.md#step-2e1-connections-and-source-coverage) provides source coverage and connection-status walkthroughs. [Step 2E.2](docs/import-samples.md) provides bank sample previews and row inspection. Step 2E.3 adds reversible bank review decisions, independent reconciliation, and sample-only completion receipts. Step 2E.4 adds seven investment examples with typed snapshots, activity, cash, and lots; bounded fund-source preferences; independent position/cash checks; and the same reversible review history.

- Indian and US stocks, ETFs, and direct/regular mutual funds.
- UBS Accenture ESPP lots, dividends, and cash movements.
- HDFC/SBI transactions, categories, transfers, cash flow, and budgets.
- [HDFC credit cards in Step 9](docs/credit-cards-plan.md): a dedicated section, statement imports, dues, activity and payment matching; planned separately from Step 4.
- Supported automatic imports, statement fallbacks, and separate holdings/price freshness.
- Python API with local PostgreSQL for development and Supabase PostgreSQL for deployment.
- Likely Oracle Cloud AMD hosting; resource, swap protection, and recovery checks precede hosted use.
- Personal access first; multi-user access and trade execution are future extensions.

## Documentation

| Document | Purpose |
| --- | --- |
| [Product plan](docs/plan.md) | Scope and staged roadmap |
| [UI prototype plan](docs/ui-prototype-plan.md) | Visual direction, increments, acceptance criteria |
| [Budgets and cash-flow plan](docs/budgets-prototype-plan.md) | Step 2D increments, financial rules, security, and acceptance criteria |
| [Import and connection prototype plan](docs/imports-prototype-plan.md) | Step 2E increments, review rules, sample boundaries, and verification |
| [Bank import samples](docs/import-samples.md) | Fixed comparison baselines, expected row dispositions, native amounts, and source arithmetic |
| [Prototype implementation](docs/ui-prototype.md) | Behavior, calculations, security boundaries, verification |
| [Browser sessions and recovery](docs/browser-sessions.md) | Session limits, HTTP contract, key custody, recovery procedures, and evidence gaps |
| [Protected financial reads](docs/financial-reads.md) | Authenticated identity queries, response fields, pagination and failure boundaries |
| [Architecture](docs/architecture.md) | Components, database decisions, financial data rules |
| [Verification](docs/verification.md) | Shared local/CI commands, tool integrity, secret scanning, and workflow boundaries |
| [Authentication foundation](docs/authentication-foundation.md) | Supabase password/TOTP verification, restricted enrollment, and local/provider test boundaries |
| [Ownership isolation](docs/ownership-isolation.md) | Owner mapping, row policies, transaction scope, and connection cleanup |
| [Database foundation](docs/database-foundation.md) | Local PostgreSQL commands, roles, migration safety, and recovery boundaries |
| [API scaffold](docs/api-foundation.md) | Implemented local HTTP/configuration/logging boundary and limits |
| [Local packaging](docs/local-packaging.md) | Restricted HTTPS package, resource evidence, and encrypted synthetic recovery |
| [Supabase readiness](docs/supabase-readiness.md) | Hosted compatibility work and evidence checklist |
| [Financial data plan](docs/financial-data-plan.md) | Step 4 increments, identity/precision contracts, provenance, atomic persistence, isolation and recovery |
| [Lot evidence and corrections](docs/lot-evidence-corrections.md) | Implemented Step 4D.3 separate acquisition/remaining observations and immutable correction histories |
| [Snapshot evidence and selection](docs/snapshot-evidence.md) | Implemented Step 4E.1 dated position/cash evidence, source conflicts and retained selection history |
| [Financial events](docs/financial-events.md) | Implemented Step 4D.2 source-linked events, native movements, explicit posting state and recovery |
| [Import staging](docs/import-staging.md) | Implemented Step 4D.1 immutable evidence, exact normalized rows and versioned review |
| [Instrument identities](docs/instrument-identities.md) | Implemented Step 4C securities, fund variants, listings, provider mappings and account position identities |
| [Accounts and source mappings](docs/accounts-source-mappings.md) | Implemented Step 4B account identity, reference key custody, mapping history and recovery |
| [Exact financial values](docs/financial-values.md) | Implemented Step 4A decimal, currency, missing-value, arithmetic and date contracts |
| [Credit cards plan](docs/credit-cards-plan.md) | Step 9 HDFC scope, statement imports, liabilities/dues, payment matching, spending and security |
| [Foundation plan](docs/foundation-plan.md) | Step 3 increments, ownership/session contracts, and verification |
| [Authentication options](docs/authentication-options.md) | Supabase Auth, Django/allauth, and Auth0 tradeoffs |
| [Security](docs/security.md) | Threat model, controls, release gates |
| [Integrations](docs/integrations.md) | Provider options and verification |
| [Operations](docs/operations.md) | Hosting, backups, recovery, incident handling |
| [Development](docs/development.md) | Local commands, validation, conventional commits |
| [Pull requests](docs/pull-requests.md) | Scope, evidence, merge policy |

Completed features use conventional commits on `dev`, with pull requests into `main`. Real statements, identifiers, credentials, and database dumps stay outside the repository. Planned protections are not claims of controls already deployed.

Licensed under [Apache License 2.0](LICENSE).
