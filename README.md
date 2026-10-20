# Trading app

A personal finance application for tracking Indian and US investments, Accenture employee shares, and bank accounts in one place. Security is the highest priority, followed by financial accuracy, recoverability, and a clear, responsive interface.

## Project status

Step 1 planning documentation is complete. The PR standard and GitHub PR template were approved on 21 October 2026. Application implementation has not started. Each subsequent small step requires approval before work begins.

The agreed database setup is local PostgreSQL for development and Supabase PostgreSQL for deployment. The Python application will likely run on an Oracle Cloud AMD VM, with swap provisioned as a buffer after resource and storage checks.

## Planned coverage

- INDmoney Indian and US stocks, ETFs, and mutual funds.
- Regular mutual funds purchased through a financial advisor.
- Accenture employee stock purchase plan shares held with UBS.
- HDFC and SBI balances, transactions, spending categories, cash flow, and budgets.
- Automatic holdings imports where supported, plus independent price, NAV, and currency updates.
- Personal access first; multiple users and trade execution are future stages.

## Documentation

| Document | Purpose |
| --- | --- |
| [Product plan](docs/plan.md) | Scope, UI direction, staged roadmap, and next approval boundary |
| [Architecture](docs/architecture.md) | Components, database decisions, environments, and financial data rules |
| [Security](docs/security.md) | Threat model, required controls, and release gates |
| [Integrations](docs/integrations.md) | Provider options, access limitations, and verification requirements |
| [Operations](docs/operations.md) | Deployment, resource limits, backup, recovery, and incident handling |
| [Development workflow](docs/development.md) | Small approved changes, validation, documentation, and conventional commits |
| [Pull request standard](docs/pull-requests.md) | Scope, review evidence, security checks, approvals, and merge policy |

The controls and workflows in these documents are requirements for future implementation, not claims of protections already deployed. There are no application setup commands yet.

## Working agreement

For each approved feature: implement the agreed scope, run relevant checks, update documentation, create a conventional commit, push the feature branch, open or update its PR, report the outcome, and wait for approval of the next step. Use the [GitHub PR template](.github/pull_request_template.md) when preparing a pull request. Merging requires the owner's explicit approval; deployment requires separate approval. Real statements, personal identifiers, credentials, and database dumps must stay out of the repository.

Licensed under [Apache License 2.0](LICENSE).
