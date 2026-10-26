# Trading app

A personal finance workspace for Indian and US investments, employee shares, and everyday banking. Security comes first, followed by financial accuracy, recoverability, and a clear interface.

## Current progress

The Overview and Investments prototype runs locally with fictional data. It includes responsive Indigo & Apricot light/dark themes, INR/USD display, amount masking, allocation, dated value history, expandable accounts, and activity. Investments adds 14 account-specific holdings with search, combined filters, sorting, reporting-currency prices/NAVs with labeled originals, portfolio weights, and separate source dates. Each holding opens a detail view with source information, selected sample activity, fund identity, and UBS ESPP lots where applicable. Screens handle loading, empty, partial/stale, and failed-load states.

Banking adds HDFC/SBI booked balance snapshots, 58 fictional transactions across August to October (28 in the default October view), combined activity filters, statement reconciliation, and an inspector for original transaction records. It distinguishes posted/pending entries, incomplete coverage, and original source evidence. The INR/USD control applies across summaries, charts, expanded accounts, prices/NAVs, holding activity, ESPP lots, banking rows, reconciliation, and inspection. Converted records use dated demo FX for display only; original source amounts remain labeled. Transfer review adds explainable candidates, explicit pair confirmation, dismissal/restore, unlink, undo, and reset. Decisions update effective classifications and the Overview excerpt while source records and balances remain unchanged; they stay in memory until reload. Category review adds supplied suggestions, individual and bulk corrections with previews, shared undo, and a classified-spending preview with verified refunds and unresolved coverage. Original categories remain visible in inspection. No financial account is connected. A separate local API scaffold now provides liveness and safe configuration. A separate local PostgreSQL service and migration baseline are implemented. The separate backend now supports opt-in authentication and browser sessions. Live provider acquisition, production statement imports, connected banking views, current portfolio valuation and deployment remain planned; protected investment holdings/details and source-history inspection use saved evidence.

Budgets adds October category limits, exact INR editing, separate undo/reset, and actual-spending breakdowns linked to the same source records and category decisions. Missing classifications or activity make remaining amounts provisional. The workspace supports both themes, INR/USD, and amount masking, including edit fields and progress bars. Limits and decisions remain in memory until reload. Cash flow adds three months of reconciled statement history, account filters, selectable monthly/daily charts with tables, matching-day comparisons, source inspection, and a bridge from classified activity to bank movement. October is month-to-date; missing coverage and unresolved classifications stay explicit. Recurring review adds seven supplied monthly patterns with source evidence, confirm/dismiss/restore, independent undo/reset, and expected commitments for the rest of October. Fixed amounts and variable ranges stay separate; missing or changed evidence retains the decision and requires review. Expected expenses never change actual spending or balances.

Connections adds six source inspectors with separate financial, statement, quote/NAV, and FX dates. Two local connector walkthroughs demonstrate successful, missing, partial, failed, rate-limited, expired, and revoked scenarios; four statement examples have no simulated authorization. Attempts and receipts never change financial records or other review decisions. Sample imports adds seven HDFC/SBI examples with source coverage, whole-batch counts, posted/pending totals, and read-only row inspection. Original and normalized fields, duplicate/overlap evidence, conflicting versions, and invalid values remain distinct. No records are imported or saved.

Investment samples distinguish positions, activity, cash, and remaining lots. Same-folio source preferences retain one snapshot; regular/direct funds and Accenture positions at different accounts remain separate. Missing fees, acquisition history, and tax basis stay unknown. Completion records only a scoped sample receipt, and bank/investment reviews share undo/reset without changing portfolio totals.

[Step 5A](docs/amfi-nav-contracts.md) begins the [connected investment flow](docs/investment-flow-plan.md) with bounded public NAV parsing and exact fund matching. Missing, stale, ambiguous or unsupported evidence cannot supply a usable valuation. [Step 5B.1](docs/parser-transport.md) adds bounded worker transport contracts. The [INDmoney integration plan](docs/indmoney-integration-plan.md) prioritizes official read-only acquisition before further statement parsing; Step 6A.1 implements bounded public discovery validation; [6A.2](docs/indmoney-compatibility.md) verified local client registration and the authorization handoff. Account access, history coverage and successful token renewal remain unverified. The worker and statement intake remain later increments; Step 6D below connects saved snapshot evidence to investment screens. [Step 5E.1](docs/connected-accounts.md) connects the protected Accounts page to saved account identities, with bounded pagination, explicit unavailable states and sign-in-bound requests. It shows no balances or provider connection claims.

[Step 6B](docs/indmoney-authorization.md) adds opt-in INDmoney authorization controls, a browser-bound callback, encrypted credential custody, explicit renewal and local-first disconnect. It requires separately configured local HTTPS and MFA. Tests and screenshots use synthetic responses; no live account has been authorized, and financial imports remain disabled.

[Step 6C](docs/indmoney-reader.md) implements a bounded read-only portfolio engine with exact values, strict protocol/schema checks, explicit incomplete coverage and cancellation/access-loss handling. It is tested with a fabricated contract. Live reads remain disabled until authenticated INDmoney schemas and coverage semantics are verified; no production adapter or import route is enabled.

[Step 6D](docs/reviewed-snapshots.md) adds protected investment holdings/details and review of saved snapshots. Explicit mappings and row decisions lead to a rollback-only preview, atomic completion and an immutable receipt. Source quantities/prices retain their native currency and exact precision; incomplete coverage and unavailable values remain visible. Live acquisition and current portfolio valuation remain separate capabilities.

[Step 6E.1](docs/source-history.md) adds source-history coverage inspection from investment details. Reported periods, partial/snapshot-only coverage and superseded evidence are visible without implying completed imports, lifetime history or tax basis. A verified activity contract or detailed statement layout is still required for historical ingestion.

[Step 6E.2](docs/indmoney-capability-inspection.md) adds an internal bounded capability inspector for the [API-first history investigation](docs/indmoney-history-api.md). It collects private protocol and tool metadata without invoking financial tools or enabling imports. Synthetic tests verify the inspection boundary; authenticated INDmoney schemas, history availability, retention and successful renewal remain unverified. No application inspection route or production adapter is enabled.

[Step 7B.1](docs/lot-inspection.md) adds protected inspection of saved lot identities, acquisition/remaining observations and correction history. Exact native quantities and amounts, missing values and source coverage remain distinct. Bounded pages, masking and session-bound reads preserve the existing protected workspace boundary. No live UBS access, inferred disposal allocation, tax calculation or return is added.

[Step 7B.2](docs/account-activity-inspection.md) adds protected account-wide activity, retained event revisions and source-coverage inspection from investment details. Other positions and account-level cash remain visible. Bounded UUID pages are not chronological or lifetime history. Posted/pending, active/cancelled and current/historical states remain distinct; exact native values and independently supplied dates are preserved. Source claims do not establish reconciled completion. No provider acquisition, financial write or calculated balance is added.

[Step 7B.3](docs/saved-receipt-inspection.md) adds protected inspection of saved batch completion receipts and historical row effects from event revisions and lot observations. Whole-batch records, links, corrections and exclusions remain distinct. Exact batch, coverage, receipt and originating-row bindings plus bounded traversal checks verify the retained evidence without acquiring data or performing a financial write. A historical receipt does not establish current balances, tax basis or complete account history.

[Step 7B.4.1](docs/frozen-comparison-inspection.md) adds whole-receipt native comparison scopes and exact source/combined equations. Frozen periods, date bases, native currencies or units and decimal spelling remain distinct. Bounded count-only traversal and exact scaled-integer checks reject mismatched scopes, incomplete pages and inconsistent equations. Balanced at completion is historical evidence, not a current balance or complete account history. Acquisition and activity completion remain separate work.

[Step 7B.4.2](docs/frozen-input-inspection.md) adds the retained opening, activity and closing inputs for each source/combined comparison side. Six explicit selections preserve original native values, dates, posting states and lineage revisions. Bounded 25-row traversal checks saved counts without retaining prior private rows. This is historical evidence inspection; it performs no financial write or live provider acquisition.

[Step 8A.1](docs/protected-bank-activity.md) opens saved HDFC/SBI bank accounts directly from protected Banking. Account activity and revision history preserve exact native amounts, independent posting/cancellation states and source dates. Compact cards and expandable source details keep the view readable; masking and strict account/currency/history binding remain enforced. This increment adds saved-data inspection; bank acquisition, statement parsing, balances, transfer matching, categorization and budgets remain separate work.

[Step 8A.2](docs/bank-record-provenance.md) opens source records and saved import-completion effects from the selected bank event revision. Source records remain source-wide, while receipt effects retain every row in the whole batch. Exact origin binding, historical return floors and fresh-directory recovery protect navigation. Bank comparison/input inspection, acquisition and the complete protected import flow remain separate work.

[Step 9A](docs/credit-cards-prototype.md) adds a synthetic Credit Cards screen with one fictional HDFC billing account, shared primary/add-on activity, statement history, searchable activity and source inspection. Statement dues and separately dated outstanding remain distinct; missing values and payment status stay unknown. Both themes, INR/USD display and amount masking are supported. Financial records and selections are not persisted, and no real HDFC export format, upload or protected card screen is supported.

[Step 9B.1](docs/credit-card-values.md) adds pure Python contracts for INR statements, separately dated current evidence, explicit entry roles and exact liability reconciliation. Missing values remain distinct from zero, and matching arithmetic does not prove coverage or payment. This increment introduces no database schema, API, UI, import support or persistence.

[Step 9B.2](docs/credit-account-identity.md) adds a separate owned HDFC/INR billing-account registry with internal identities, safe nicknames and revision-checked archival. Forced owner isolation, bounded reads/writes and encrypted recovery cover the registry. It stores no financial values, card digits, issuer references or source mappings and exposes no API or screen. Archival does not establish issuer closure or payment.

[Step 9B.3](docs/credit-source-mappings.md) adds owned application source handles and append-only billing-account mapping history. Explicit links, corrections and unlinks retain their revisions; current resolution requires an active target. Forced owner isolation, bounded runtime writes and encrypted recovery cover both tables. Handles contain no issuer reference or card digits and do not establish HDFC identity, import compatibility, deduplication or payment status. No API, screen or financial evidence is added.

[Step 9B.4](docs/credit-statement-evidence.md) adds internal, immutable statement checkpoint observations bound to an owned credit source, exact mapping revision and billing account. Exact INR opening/closing liability, total due, minimum due and independent dates retain missing values and original decimal spelling. Corrections and explicitly identified retries preserve history; complete parent/child pairs and encrypted recovery retain the evidence. These unselected reported checkpoints establish neither provider authenticity nor current liability, transaction coverage or payment status. No acquisition, liability movement, public route or screen is added.

[Step 9B.5](docs/credit-current-evidence.md) adds separately dated, immutable current credit reports with independent outstanding, unbilled, credit-limit and available-credit values. Exact INR spelling, missing reasons and original source-local instants are retained through corrections and explicit retries. Typed reciprocal links preserve statement/current separation under the shared observation namespace and quota, including encrypted restore. These unselected source reports do not establish freshness, chosen liability, payment status or available cash. No entries, acquisition, public route or screen is added.

[Step 9B.6.1](docs/credit-entry-evidence.md) adds immutable credit entry interpretations with explicit roles/treatment, independent transaction/posting dates, billed INR and optional original INR/USD evidence. Absent original cash, explicitly missing cash and zero remain distinct. Corrections, explicit retries and encrypted restore preserve exact values and source/mapping/account history under the shared three-kind namespace and quota. Unsupported corrections remain retained and listable. No statement allocation, financial movement, withdrawal, payment inference, import or connected screen is added.

[Step 9B.7.1](docs/credit-identity-reads.md) adds four protected read-only JSON routes for owned billing identities, opaque source handles and retained mapping revisions. Never-mapped, unlinked and archived-target states remain explicit; current account lifecycle is distinct from historical target binding. Bounded pages and private response validation retain the existing active MFA/session boundary. These four routes expose metadata only.

[Step 9B.7.2](docs/credit-evidence-reads.md) adds three protected typed reads for unselected statement, current-report and entry evidence. Bounded queries, retained history and exact-revision inspection bind account/kind/root and frozen mapping provenance. Original native decimal and source-local instant spelling, independent dates, and absent/missing/zero distinctions remain explicit. Newest stored interpretations do not establish selected liability, freshness, coverage or payment status. No financial mutation, provider acquisition or connected card screen is added.

## Run locally

Use Node.js 22.22.2 or newer in the Node 22 release line, with npm 12. From the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open [the local prototype](http://127.0.0.1:5173), [Investments](http://127.0.0.1:5173/#/investments), [Banking](http://127.0.0.1:5173/#/banking), [Budgets](http://127.0.0.1:5173/#/budgets), [Credit Cards](http://127.0.0.1:5173/#/credit-cards), [Connections](http://127.0.0.1:5173/#/connections), a [bank sample preview](http://127.0.0.1:5173/#/connections/imports/i01), an [investment sample](http://127.0.0.1:5173/#/connections/imports/i10), or a [sample transaction](http://127.0.0.1:5173/#/banking/t08). The server binds to loopback only. Use **Explore the demo** at the bottom to switch fixture states. Theme, currency, and amount masking are saved locally; financial records and search/filter state are not stored in browser storage. Masking also hides units, quotes, purchase amounts, fees, bank activity values, and raw narration/reference in transaction inspection. Import masking also removes source descriptions, all original source fields, matching financial evidence, and search text.

```sh
npm run check       # tests, TypeScript checks, and production build
npm run preview     # local production preview at http://127.0.0.1:4173
```

The FX rate is fixed and fictional. The history shows asset values, including cash-flow effects; it does not calculate investment returns. Amount masking provides visual privacy, not access control. Never put real records or credentials into the prototype.

## Direction

[Step 3A](docs/api-foundation.md) implements the local FastAPI scaffold with locked Python dependencies, loopback-only startup, validated configuration, and sanitized errors/logs. [Supabase Auth on Free](docs/authentication-options.md) is selected for password and TOTP verification. Follow the [Python setup commands](docs/development.md#local-python-api) to run `GET /api/v1/health/live`; the fictional prototype remains independent. [Step 3B](docs/verification.md) adds shared local checks and CI for Python, the frontend, and repository security. [Step 3C](docs/database-foundation.md) adds local PostgreSQL, separate disposable database tests, restricted roles, and transactional migrations. [Step 3D](docs/ownership-isolation.md) adds internal owner mapping, forced row-level security, and isolated preference transactions with connection cleanup. [Step 3E.1](docs/authentication-foundation.md) implements the server-side Supabase password/TOTP adapter and restricted enrollment with local tests. No Supabase project is configured and no hosted authentication check has run. [Step 3E.2](docs/browser-sessions.md) adds encrypted server sessions, browser CSRF/origin controls, durable admission, revocation, recovery, and sanitized security events. Authentication remains opt-in. [Step 3F.1](docs/protected-workspace.md) adds a separate protected frontend with sign-in, MFA, restricted recovery, session controls, and an empty workspace. It runs through the API at the same origin and never loads fictional balances. [Step 3F.2](docs/display-preferences.md) persists account display preferences with owner-scoped validation, conflict review, and session-aware saves. [Step 3G](docs/local-packaging.md) adds the restricted local HTTPS package, resource measurements, encrypted synthetic recovery, and a [Supabase readiness checklist](docs/supabase-readiness.md). Hosted integration remains future work. [Step 4](docs/financial-data-plan.md) covers the financial model and persistence in small increments. [Step 4A](docs/financial-values.md) implements exact value/date contracts and bounded arithmetic with synthetic tests; [Step 4B](docs/accounts-source-mappings.md) adds owned accounts, protected source references, versioned mappings and expanded recovery. [Step 4C](docs/instrument-identities.md) adds instrument/fund/listing identities, provider mappings and account positions. [Step 4D.1](docs/import-staging.md) adds immutable source evidence, exact staged rows and revisioned review decisions. [Step 4D.2](docs/financial-events.md) adds exact source-linked events and distinct posted/pending native movements. [Step 4D.3](docs/lot-evidence-corrections.md) adds sourced lot observations and retained correction, cancellation and reinstatement history. [Step 4E.1](docs/snapshot-evidence.md) adds dated snapshots, retained precision and explicit source selection. [Step 4E.2](docs/market-evidence.md) adds exact quote/NAV and directed FX observations, corrections and explicit selection. [Step 4F.1](docs/event-evidence.md) adds protected transaction references and exact corroborating evidence links. [Step 4F.2](docs/reconciliation-contracts.md) adds exact source/combined-state reconciliation contracts. Current portfolio valuation and activity completion screens remain planned. [Step 4F.3.1](docs/statement-boundaries.md) retains explicit statement boundaries and cash date basis. [Step 4F.3.2a](docs/completion-preflight.md) adds strict completion manifests and serialized owner-state guards. [Step 4F.3.2b](docs/completion-receipts.md) atomically completes partial/unknown/snapshot evidence with immutable receipts and exact retries. [Step 4F.3.2c](docs/reconciled-completion.md) adds full source-period reconciliation with immutable comparison inputs. [Step 4G.1](docs/financial-reads.md) adds authenticated account/source/instrument/position identity reads with bounded JSON pagination. [Step 4G.2a](docs/event-lot-reads.md) adds exact event/lot evidence and retained correction history. [Step 4G.2b](docs/snapshot-market-reads.md) adds dated snapshot/market observations, listings and selection history/resolution. [Step 4G.3a](docs/import-review-reads.md) adds source, normalized row and review inspection. [Step 4G.3b](docs/completion-receipt-reads.md) completes protected receipt/comparison reads and synthetic persistence acceptance; Stage 5 begins connecting the protected frontend to these reads.

[Step 2D](docs/budgets-prototype-plan.md) provides monthly category budgets, historical cash-flow analysis, and recurring-expense review (2D.1–2D.3). [Step 2E.1](docs/imports-prototype-plan.md#step-2e1-connections-and-source-coverage) provides source coverage and connection-status walkthroughs. [Step 2E.2](docs/import-samples.md) provides bank sample previews and row inspection. Step 2E.3 adds reversible bank review decisions, independent reconciliation, and sample-only completion receipts. Step 2E.4 adds seven investment examples with typed snapshots, activity, cash, and lots; bounded fund-source preferences; independent position/cash checks; and the same reversible review history.

- Indian and US stocks, ETFs, and direct/regular mutual funds.
- UBS Accenture ESPP lots, dividends, and cash movements.
- HDFC/SBI transactions, categories, transfers, cash flow, and budgets.
- [HDFC credit cards in Step 9](docs/credit-cards-plan.md): the synthetic section, durable unselected evidence and protected identity/evidence reads are implemented; verified statement imports, connected card views and payment matching remain planned.
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
| [Protected lot inspection](docs/lot-inspection.md) | Saved lot identities, native evidence, source coverage and retained correction history |
| [Protected account activity](docs/account-activity-inspection.md) | Account-wide event pages, native evidence, retained revisions and source-coverage claims |
| [Saved completion inspection](docs/saved-receipt-inspection.md) | Historical batch receipts and whole-batch record/link/correction/exclusion effects |
| [Frozen native comparisons](docs/frozen-comparison-inspection.md) | Whole-receipt native scopes, exact source/combined equations and historical boundaries |
| [Frozen comparison inputs](docs/frozen-input-inspection.md) | Six source/combined input selections, exact native evidence and retained historical lineage |
| [Protected bank activity](docs/protected-bank-activity.md) | Saved HDFC/SBI account selection, exact native activity and revision history |
| [Bank record provenance](docs/bank-record-provenance.md) | Source-wide observations, exact clicked origins and whole-batch historical import effects |
| [Snapshot evidence and selection](docs/snapshot-evidence.md) | Implemented Step 4E.1 dated position/cash evidence, source conflicts and retained selection history |
| [Financial events](docs/financial-events.md) | Implemented Step 4D.2 source-linked events, native movements, explicit posting state and recovery |
| [Import staging](docs/import-staging.md) | Implemented Step 4D.1 immutable evidence, exact normalized rows and versioned review |
| [Instrument identities](docs/instrument-identities.md) | Implemented Step 4C securities, fund variants, listings, provider mappings and account position identities |
| [Accounts and source mappings](docs/accounts-source-mappings.md) | Implemented Step 4B account identity, reference key custody, mapping history and recovery |
| [Exact financial values](docs/financial-values.md) | Implemented Step 4A decimal, currency, missing-value, arithmetic and date contracts |
| [Credit cards plan](docs/credit-cards-plan.md) | Step 9 HDFC scope, statement imports, liabilities/dues, payment matching, spending and security |
| [Credit-card prototype](docs/credit-cards-prototype.md) | Synthetic statement/activity walkthrough, masking, financial distinctions and verification |
| [Credit-card value contracts](docs/credit-card-values.md) | Exact statement/current values, explicit liability roles and bounded reconciliation |
| [Credit billing-account identity](docs/credit-account-identity.md) | Owned HDFC/INR identities, safe nicknames, archival, isolation and recovery |
| [Credit source mappings](docs/credit-source-mappings.md) | Opaque owned source handles, immutable mapping history, active resolution and recovery |
| [Credit statement evidence](docs/credit-statement-evidence.md) | Immutable unselected INR checkpoints, frozen mapping provenance, explicit retries and recovery |
| [Current credit evidence](docs/credit-current-evidence.md) | Independently dated unselected INR reports, original source-local instants, typed history and recovery |
| [Credit entry evidence](docs/credit-entry-evidence.md) | Immutable roles/treatment, billed and original native values, independent dates and retained correction history |
| [Protected credit identity reads](docs/credit-identity-reads.md) | Four bounded billing/source/mapping metadata reads, observed lifecycle, strict private responses and session isolation |
| [Protected credit evidence reads](docs/credit-evidence-reads.md) | Typed native statement/current/entry reads, exact retained revisions, frozen provenance and private bounded responses |
| [Foundation plan](docs/foundation-plan.md) | Step 3 increments, ownership/session contracts, and verification |
| [Authentication options](docs/authentication-options.md) | Supabase Auth, Django/allauth, and Auth0 tradeoffs |
| [Security](docs/security.md) | Threat model, controls, release gates |
| [Private model diagnostics](docs/private-model-diagnostics.md) | Scoped warning privacy at internal validation boundaries and regression evidence |
| [Integrations](docs/integrations.md) | Provider options and verification |
| [INDmoney integration](docs/indmoney-integration-plan.md) | Read-only portfolio route, public discovery evidence, authorization design, coverage and statement fallbacks |
| [INDmoney compatibility](docs/indmoney-compatibility.md) | Observed custom-client registration/handoff, history limitations, renewal findings and remaining account tests |
| [INDmoney history APIs](docs/indmoney-history-api.md) | API-first historical acquisition assessment, current-day trade limits and remaining authenticated capability checks |
| [INDmoney capability inspection](docs/indmoney-capability-inspection.md) | Bounded private catalog inspection without financial calls; authenticated history verification remains open |
| [UBS integration plan](docs/ubs-integration-plan.md) | Step 7A public API/OFX and document candidates, ESPP evidence boundaries and incremental delivery |
| [INDmoney reader](docs/indmoney-reader.md) | Bounded read-only engine, exact evidence, incomplete coverage and the live schema compatibility gate |
| [Operations](docs/operations.md) | Hosting, backups, recovery, incident handling |
| [Development](docs/development.md) | Local commands, validation, conventional commits |
| [Pull requests](docs/pull-requests.md) | Scope, evidence, merge policy |

Completed features use conventional commits on `dev`, with pull requests into `main`. Real statements, identifiers, credentials, and database dumps stay outside the repository. Planned protections are not claims of controls already deployed.

Licensed under [Apache License 2.0](LICENSE).

[Step 5E.0](docs/workspace-context.md) binds workspace requests to their checked sign-in. A changed cookie in another tab cannot silently redirect preference saves or financial reads into a replacement session; stale views clear and require a session recheck.
