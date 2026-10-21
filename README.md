# Trading app

A personal finance workspace for Indian and US investments, employee shares, and everyday banking. Security comes first, followed by financial accuracy, recoverability, and a clear interface.

## Current progress

The Overview and Investments prototype runs locally with fictional data. It includes responsive Indigo & Apricot light/dark themes, INR/USD display, amount masking, allocation, dated value history, expandable accounts, and activity. Investments adds 14 account-specific holdings with search, combined filters, sorting, reporting-currency prices/NAVs with labeled originals, portfolio weights, and separate source dates. Each holding opens a detail view with source information, selected sample activity, fund identity, and UBS ESPP lots where applicable. Screens handle loading, empty, partial/stale, and failed-load states.

Banking adds HDFC/SBI booked balance snapshots, 28 fictional transactions, combined activity filters, statement reconciliation, and an inspector for original transaction records. It distinguishes posted/pending entries, incomplete coverage, and original source evidence. The INR/USD control applies across summaries, charts, expanded accounts, prices/NAVs, holding activity, ESPP lots, banking rows, reconciliation, and inspection. Converted records use dated demo FX for display only; original source amounts remain labeled. Transfer review adds explainable candidates, explicit pair confirmation, dismissal/restore, unlink, undo, and reset. Decisions update effective classifications and the Overview excerpt while source records and balances remain unchanged; they stay in memory until reload. Category review adds supplied suggestions, individual and bulk corrections with previews, shared undo, and a classified-spending preview with verified refunds and unresolved coverage. Original categories remain visible in inspection. No financial account is connected. Budgets, cash-flow trends, backend services, authentication, imports, databases, and deployment remain planned.

## Run locally

Use Node.js 22.22.2 or newer in the Node 22 release line, with npm 12. From the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open [the local prototype](http://127.0.0.1:5173), [Investments](http://127.0.0.1:5173/#/investments), [Banking](http://127.0.0.1:5173/#/banking), or a [sample transaction](http://127.0.0.1:5173/#/banking/t08). The server binds to loopback only. Use **Explore the demo** at the bottom to switch fixture states. Theme, currency, and amount masking are saved locally; financial records and search/filter state are not stored in browser storage. Masking also hides units, quotes, purchase amounts, fees, bank activity values, and raw narration/reference in transaction inspection.

```sh
npm run check       # tests, TypeScript checks, and production build
npm run preview     # local production preview at http://127.0.0.1:4173
```

The FX rate is fixed and fictional. The history shows asset values, including cash-flow effects; it does not calculate investment returns. Amount masking provides visual privacy, not access control. Never put real records or credentials into the prototype.

## Direction

- Indian and US stocks, ETFs, and direct/regular mutual funds.
- UBS Accenture ESPP lots, dividends, and cash movements.
- HDFC/SBI transactions, categories, transfers, cash flow, and budgets.
- Supported automatic imports, statement fallbacks, and separate holdings/price freshness.
- Python API with local PostgreSQL for development and Supabase PostgreSQL for deployment.
- Likely Oracle Cloud AMD hosting; resource, swap protection, and recovery checks precede hosted use.
- Personal access first; multi-user access and trade execution are future extensions.

## Documentation

| Document | Purpose |
| --- | --- |
| [Product plan](docs/plan.md) | Scope and staged roadmap |
| [UI prototype plan](docs/ui-prototype-plan.md) | Visual direction, increments, acceptance criteria |
| [Prototype implementation](docs/ui-prototype.md) | Behavior, calculations, security boundaries, verification |
| [Architecture](docs/architecture.md) | Components, database decisions, financial data rules |
| [Security](docs/security.md) | Threat model, controls, release gates |
| [Integrations](docs/integrations.md) | Provider options and verification |
| [Operations](docs/operations.md) | Hosting, backups, recovery, incident handling |
| [Development](docs/development.md) | Local commands, validation, conventional commits |
| [Pull requests](docs/pull-requests.md) | Scope, evidence, merge policy |

Completed features use conventional commits on `dev`, with pull requests into `main`. Real statements, identifiers, credentials, and database dumps stay outside the repository. Planned protections are not claims of controls already deployed.

Licensed under [Apache License 2.0](LICENSE).
