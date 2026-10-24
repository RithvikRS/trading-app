# Product plan

Planning baseline: 21 October 2026.

Steps 2A, 2B.1, and 2B.2, covering the responsive Overview, searchable holdings list, and holding detail pages, are merged into `main`. Banking activity/inspection, transfer matching, and category corrections through Step 2C.3 are also merged into `main`. See the [implementation notes](ui-prototype.md) for current behavior and verification. [Step 2D.1](budgets-prototype-plan.md#step-2d1-monthly-category-budgets) adds monthly category budgets. Cash-flow trends (2D.2) are implemented. Recurring-expense review (2D.3) completes Step 2D, now merged into `main`. [Step 2E.1](imports-prototype-plan.md#step-2e1-connections-and-source-coverage) implements connection status and source coverage using isolated local walkthroughs. [Step 2E.2](import-samples.md) implements the bank sample catalog, read-only previews, and source row inspection. Step 2E.3 adds reversible bank review choices and sample completion receipts, with exact source/combined reconciliation and isolated undo/reset. Step 2E.4 adds investment statement walkthroughs for Indian/US snapshots, fund overlap, regular-plan funds, and UBS employee shares. All review decisions remain isolated from financial records. Step 2 is merged into `main`. [Step 3A](api-foundation.md) implements the local Python API scaffold. [Supabase Auth on Free with FastAPI](authentication-options.md) is selected; its internal integration is described below. [Step 3B](verification.md) adds shared local checks and CI. [Step 3C](database-foundation.md) implements local PostgreSQL, isolated database checks, restricted roles, and a transactional migration baseline. [Step 3D](ownership-isolation.md) adds owner/identity mapping, forced row-level security, and isolated non-financial preference transactions. [Step 3E.1](authentication-foundation.md) adds server-side Supabase password/TOTP verification and restricted enrollment, tested locally without a hosted project. [Step 3E.2](browser-sessions.md) implements browser sessions, recovery, revocation, and security events using local tests. [Step 3F.1](protected-workspace.md) adds a separate protected frontend shell with authentication/recovery and empty-workspace states. [Step 3F.2](display-preferences.md) implements authenticated display preference persistence with versioned saves and explicit conflict review. [Step 3G](local-packaging.md) implements the local HTTPS package, resource measurements, and encrypted synthetic recovery. [Supabase readiness](supabase-readiness.md) records hosted compatibility work and unperformed checks. [Step 4](financial-data-plan.md) covers exact financial contracts, accounts/instruments, provenance, events/lots, snapshots, reviewed persistence, and protected reads. [Step 4A](financial-values.md) implements the pure Python value/date contracts and bounded arithmetic; [4B accounts and source mappings](accounts-source-mappings.md) adds financial account persistence, protected reference custody and recovery. [Step 4C](instrument-identities.md) adds securities, fund variants, listings, provider mappings and account position identities. [Step 4D.1](import-staging.md) adds immutable source observations, normalized candidates and revisioned review without financial posting. [Step 4D.2](financial-events.md) records source-linked events and posted/pending native movements. [Step 4D.3](lot-evidence-corrections.md) adds lot scopes and immutable event/lot correction histories. [Step 4E.1](snapshot-evidence.md) adds sourced position/cash snapshots, exact observation precision and explicit selection history. [Step 4E.2](market-evidence.md) adds quote/NAV and directed FX observations with explicit selection. [Step 4F.1](event-evidence.md) adds protected provider transaction identities and exact evidence reuse. [Step 4F.2](reconciliation-contracts.md) adds exact reconciliation contracts. [Step 4F.3.1](statement-boundaries.md) adds explicit statement boundaries and cash date basis. [Step 4F.3.2a](completion-preflight.md) adds strict completion manifests and serialized owner-state guards. [Step 4F.3.2b](completion-receipts.md) adds atomic limited-coverage completion and immutable receipts. [Step 4F.3.2c](reconciled-completion.md) adds full source-period reconciliation and immutable compared inputs. [Step 4G.1](financial-reads.md) adds protected identity queries. [Step 4G.2a](event-lot-reads.md) adds dated event/lot evidence and history. [Step 4G.2b](snapshot-market-reads.md) adds snapshot/market evidence and selection reads; [Step 4G.3a](import-review-reads.md) adds import/review inspection. [Step 4G.3b](completion-receipt-reads.md) completes receipt/comparison inspection and synthetic persistence acceptance. Step 4 is implemented; [Stage 5](investment-flow-plan.md) provides the first complete investment import flow; [5A](amfi-nav-contracts.md) implements public NAV evidence parsing and exact matching.

Build a personal finance application that provides a trustworthy view of investments, banking activity and credit cards with as little manual maintenance as supported integrations allow. Security takes priority over convenience, cost optimization, and delivery speed. Financial accuracy and recoverability are part of that requirement.

## Scope

| Area | Initial coverage |
| --- | --- |
| Investments | Indian and US stocks and ETFs purchased through INDmoney |
| Mutual funds | INDmoney purchases and regular funds purchased through an advisor, with direct and regular plans distinguished |
| Employee shares | Accenture ESPP holdings, purchase lots, dividends, fees, and sales from UBS |
| Banking | HDFC and SBI balances, transactions, income, spending categories, recurring payments, transfers, and budgets |
| Credit cards | HDFC first: statement imports, billing cycles, dues, liability/activity views, payment matching and spending; a separate Step 9 |
| Reporting | INR reporting view with original INR and USD amounts, allocation, cash flow, and returns when history is complete |
| Updates | Supported automatic imports, statement imports as a fallback, scheduled valuations, and visible freshness |

The first version serves one owner. Every account and financial record will still have an ownership boundary so future multi-user access does not require guessing who owns existing data.

Trade execution, public registration, multi-user onboarding, tax filing, and investment recommendations are outside the first version. Preserve source information useful for later reporting without describing portfolio calculations as tax calculations. [HDFC credit cards](credit-cards-plan.md) have a dedicated stage after banking and budgets; loans and other account products remain future extensions.

## Success criteria

- The owner can inspect investments and bank activity together and trace each imported value to its source.
- Holdings and transactions reconcile to representative statements; overlaps do not inflate balances.
- Bank transfers and investment funding do not inflate income or spending.
- Credit card purchases and bill payments do not double-count spending; statement dues, current outstanding and available credit remain distinct, dated values.
- Importing the same data twice leaves totals unchanged, while legitimate identical transactions remain distinct.
- Failed imports preserve the last valid state and explain what needs attention.
- Price freshness and holdings freshness are shown separately; stale or missing values are never presented as current zeros.
- Access controls, protected secrets, and a successful restore exercise are required before hosted use with real data.

## Interface direction

Use clear typography, consistent spacing, compact readable tables, and charts that support specific decisions. Provide light and dark themes, an INR/USD display choice, masked balances, and layouts for desktop and mobile. Daily overview and statement review should be efficient with both keyboard and touch.

| Screen | Main purpose |
| --- | --- |
| Overview | Tracked assets, cash, allocation, performance where available, and data freshness |
| Investments | Searchable holdings with account, asset class, currency, fund plan, and transaction detail |
| Banking | Account balances, searchable activity, transfer matching, and category corrections |
| Credit Cards | HDFC card accounts, statement history, dues, activity, import review and bank-payment matching; planned Step 9 |
| Budgets | Monthly category budgets, actual spending, recurring commitments, and cash-flow trends |
| Activity | Transactions, import batches, reconciliations, and corrections |
| Connections | Provider permissions, last successful sync, failures, renewal needs, and disconnect controls |

Label totals as tracked assets unless liabilities and account coverage support a net-worth claim. Show the effect of deposits and withdrawals separately from investment performance.

Review a clickable prototype with synthetic data before connecting personal accounts. Acceptance covers useful visual hierarchy, responsive layouts, accessible contrast, visible keyboard focus, chart alternatives, and loading, empty, error, and stale-data states. Import review must explain proposed additions, duplicates, conflicts, and rejected rows before confirmation.

## Roadmap

Deliver each stage through small features with concrete acceptance criteria. The integration feasibility review precedes production connector work and can change the order of imports.

| Stage | Deliverable | Acceptance boundary |
| --- | --- | --- |
| 1 | Planning documentation | Scope, architecture, security, integrations, operations, and workflow recorded in a conventional commit |
| 2 | UI prototype | [Overview first](ui-prototype-plan.md), followed by holdings, bank activity, budgets, and import/connection walkthroughs; synthetic data and reviewed interaction states |
| 3 | [Secure application foundation](foundation-plan.md) | Python API, security checks, local PostgreSQL, migrations, ownership/RLS, MFA and revocable sessions, protected frontend, and local recovery/deployment readiness in small increments |
| 4 | [Financial data model and persistence](financial-data-plan.md) | Exact values, owned accounts/instruments, source evidence, events/lots, snapshots, atomic review completion/deduplication, protected read models and continuous recovery coverage; synthetic data first |
| 5 | [First complete investment flow](investment-flow-plan.md) | [5A public NAV contracts](amfi-nav-contracts.md), [5B.1 parser transport](parser-transport.md) and [5E.1 protected account directory](connected-accounts.md) implemented; prioritize Stage 6 acquisition, then reviewed completion and connected investments; verified statements cover source gaps |
| 6 | [INDmoney integration](indmoney-integration-plan.md) | 6A.1 discovery and [6B authorization/custody](indmoney-authorization.md) implemented; [6A.2](indmoney-compatibility.md) live account/history/renewal checks remain open. Next: bounded portfolio reader, reviewed snapshots, mappings and explicit history gaps |
| 7 | UBS integration | Verify available statements, import ESPP lots, and reconcile shares and cash |
| 8 | Banking and budgets | HDFC import, SBI import, transfer matching, categorization, recurring items, and budgets as separate features |
| 9 | [Credit cards](credit-cards-plan.md) | HDFC first: dedicated prototype, liability/statement persistence, one verified import format, reviewed completion, bank-payment matching and spending integration |
| 10 | Automation and analytics | Durable schedules, retries, renewal handling, valuation history, and tested return calculations; card acquisition only where supported access is verified |
| 11 | Hosted deployment | Supabase hardening, Oracle configuration, access protection, resource checks, backup restoration, and security acceptance |

Authentication and security foundations can progress alongside the synthetic UI. No live credentials or real statements may be connected to an unprotected prototype. Each later feature inherits the security requirements rather than deferring them to Stage 11.

## Future extensions

Multiple users require enrollment, recovery, authorization, database policy, background-job, and storage isolation reviews. Trade execution requires a distinct execution boundary, narrowly scoped credentials where available, explicit order confirmation, duplicate-order protection, order limits, reconciliation, and an emergency disable control. Tracking must continue to work when execution is disabled.

## Decisions still to make

- App name; the visual direction is Indigo & Apricot in light and dark modes. [Authentication/framework selection](authentication-options.md) and local session/recovery behavior are implemented; hosted provider/SMTP evidence and production key custody remain outstanding.
- Private access method, domain, Oracle region, Supabase region, and available storage.
- Actual provider exports, history depth, consent scopes, and supported unattended renewal.
- HDFC card product/export layout, account versus add-on/replacement mapping, and statement/payment coverage for the first credit card parser.
- Refresh cadence and any market-data budget; daily valuations are the starting proposal.
- Backup destination, retention, recovery targets, and statement retention preferences.

The current prototype covers Overview, investment holdings/details, bank activity/inspection, transfer matching, and category corrections. Monthly category budgets, reconciled cash-flow trends, and recurring-expense review are implemented. The [import and connection walkthroughs](imports-prototype-plan.md) now include bank and investment samples with isolated review outcomes. Provider access, real data, databases, and deployment remain outside the prototype scope.
