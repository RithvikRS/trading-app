# Product plan

Planning baseline: 21 October 2026.

Steps 2A, 2B.1, and 2B.2, covering the responsive Overview, searchable holdings list, and holding detail pages, are merged into `main`. Banking activity/inspection, transfer matching, and category corrections through Step 2C.3 are also merged into `main`. See the [implementation notes](ui-prototype.md) for current behavior and verification. [Step 2D.1](budgets-prototype-plan.md#step-2d1-monthly-category-budgets) adds monthly category budgets. Cash-flow trends (2D.2) are implemented. Recurring-expense review (2D.3) completes Step 2D, now merged into `main`. [Step 2E.1](imports-prototype-plan.md#step-2e1-connections-and-source-coverage) implements connection status and source coverage using isolated local walkthroughs. [Step 2E.2](import-samples.md) implements the bank sample catalog, read-only previews, and source row inspection. Step 2E.3 adds reversible bank review choices and sample completion receipts, with exact source/combined reconciliation and isolated undo/reset. Step 2E.4 adds investment statement walkthroughs for Indian/US snapshots, fund overlap, regular-plan funds, and UBS employee shares. All review decisions remain isolated from financial records. Step 2 is merged into `main`. [Step 3A](api-foundation.md) implements the local Python API scaffold. [Supabase Auth on Free with FastAPI](authentication-options.md) is selected; authentication itself remains Step 3E. [Step 3B](verification.md) adds shared local checks and CI. Step 3C is next.

Build a personal finance application that provides a trustworthy view of investments and banking activity with as little manual maintenance as supported integrations allow. Security takes priority over convenience, cost optimization, and delivery speed. Financial accuracy and recoverability are part of that requirement.

## Scope

| Area | Initial coverage |
| --- | --- |
| Investments | Indian and US stocks and ETFs purchased through INDmoney |
| Mutual funds | INDmoney purchases and regular funds purchased through an advisor, with direct and regular plans distinguished |
| Employee shares | Accenture ESPP holdings, purchase lots, dividends, fees, and sales from UBS |
| Banking | HDFC and SBI balances, transactions, income, spending categories, recurring payments, transfers, and budgets |
| Reporting | INR reporting view with original INR and USD amounts, allocation, cash flow, and returns when history is complete |
| Updates | Supported automatic imports, statement imports as a fallback, scheduled valuations, and visible freshness |

The first version serves one owner. Every account and financial record will still have an ownership boundary so future multi-user access does not require guessing who owns existing data.

Trade execution, public registration, multi-user onboarding, tax filing, and investment recommendations are outside the first version. Preserve source information useful for later reporting without describing portfolio calculations as tax calculations. Credit cards, loans, and other account products can extend banking coverage after the first HDFC and SBI formats are confirmed.

## Success criteria

- The owner can inspect investments and bank activity together and trace each imported value to its source.
- Holdings and transactions reconcile to representative statements; overlaps do not inflate balances.
- Bank transfers and investment funding do not inflate income or spending.
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
| 4 | Portfolio foundation | Accounts, instruments, transaction history, snapshots, and reviewed import batches with deduplication |
| 5 | First complete investment flow | One detailed mutual fund CAS format, reconciliation, NAV updates, and a working portfolio view |
| 6 | INDmoney integration | Verify official authorization and permissions, then add supported Indian and US data one capability at a time |
| 7 | UBS integration | Verify available statements, import ESPP lots, and reconcile shares and cash |
| 8 | Banking and budgets | HDFC import, SBI import, transfer matching, categorization, recurring items, and budgets as separate features |
| 9 | Automation and analytics | Durable schedules, retries, renewal handling, valuation history, and tested return calculations |
| 10 | Hosted deployment | Supabase hardening, Oracle configuration, access protection, resource checks, backup restoration, and security acceptance |

Authentication and security foundations can progress alongside the synthetic UI. No live credentials or real statements may be connected to an unprotected prototype. Each later feature inherits the security requirements rather than deferring them to Stage 10.

## Future extensions

Multiple users require enrollment, recovery, authorization, database policy, background-job, and storage isolation reviews. Trade execution requires a distinct execution boundary, narrowly scoped credentials where available, explicit order confirmation, duplicate-order protection, order limits, reconciliation, and an emergency disable control. Tracking must continue to work when execution is disabled.

## Decisions still to make

- App name; the visual direction is Indigo & Apricot in light and dark modes. [Authentication/framework selection](authentication-options.md) is settled; recovery, SMTP, session integration, and key custody remain to be designed before Step 3E.
- Private access method, domain, Oracle region, Supabase region, and available storage.
- Actual provider exports, history depth, consent scopes, and supported unattended renewal.
- Refresh cadence and any market-data budget; daily valuations are the starting proposal.
- Backup destination, retention, recovery targets, and statement retention preferences.

The current prototype covers Overview, investment holdings/details, bank activity/inspection, transfer matching, and category corrections. Monthly category budgets, reconciled cash-flow trends, and recurring-expense review are implemented. The [import and connection walkthroughs](imports-prototype-plan.md) now include bank and investment samples with isolated review outcomes. Provider access, real data, databases, and deployment remain outside the prototype scope.
