# Instruments and fund identities: Step 4C

[Internal services](../backend/trading_db/instruments.py) and migration [0007_instruments](../backend/migrations/versions/0007_instruments.py) add owner-scoped securities, fund schemes/variants, exchange listings, provider security identifiers, mapping history and account position identities. These records describe identity only: no quantity, trade, balance, quote, import, provider download, HTTP route or frontend change is added.

## Security identity and listings

A canonical instrument has an opaque UUID, asset class (`equity`, `etf`, or `mutual_fund`), bounded display name and exact ISIN. Names never identify an instrument. The same name and ticker may describe different securities; neither causes a merge. ISIN uniqueness is scoped to the owner. An identical canonical definition is an idempotent create; a changed definition under the same ISIN conflicts. Canonical fields and listings are immutable in this increment. A correction to a provider mapping can select another existing canonical definition while retaining its earlier links; canonical reclassification itself requires a separately implemented correction contract, not a silent update.

ISIN validation checks exactly twelve uppercase ASCII characters and the modulus-10 check digit in Python and PostgreSQL. It does not prove that an identifier was issued, remains active, or describes the supplied name/asset class. Future ingestion must establish those facts from source evidence. A missing, malformed or conflicting identity stays unresolved; it cannot become an invented security. The ISIN prefix must not be used as the listing market: issuer domicile and trading venue can differ. [ANNA identifier structure](https://anna-web.org/identifiers/).

A listing belongs to one instrument and records venue, exact symbol, supplied series and native quote currency. Empty series means “not supplied”; no series is guessed. The initial venue/currency allowlist is:

| Venue | Market | Quote currency |
| --- | --- | --- |
| `XNSE` | National Stock Exchange of India | INR |
| `XBOM` | BSE | INR |
| `XNYS` | New York Stock Exchange | USD |
| `XNAS` | Nasdaq | USD |
| `ARCX` | NYSE Arca | USD |

These codes were checked against the public [ISO 10383 registration data](https://www.iso20022.org/market-identifier-codes) on 24 October 2026. The application does not download or refresh that registry. The allowlist is a project boundary, not an exhaustive exchange/segment catalog. NSE series can distinguish different trading arrangements, so supplied series are retained separately from the symbol. [NSE series definitions](https://www.nseindia.com/static/market-data/legend-of-series).

The same instrument may have several listings. Different instruments may have the same venue/symbol, including historical ticker reuse; a ticker lookup alone cannot select a security. Listings are not trade executions or proof of an exchange's current coverage. Quotes and explicit evidence selection arrive in 4E.

## Mutual funds and provider references

Fund schemes are opaque groupings with bounded names. Creating the same scheme label twice does not merge groups. A fund instrument requires an explicit scheme, `direct`/`regular` plan, `growth`/`idcw_payout`/`idcw_reinvestment` option and INR NAV currency. All six plan/option combinations remain distinguishable. Different ISINs remain separate even within one scheme/plan/option: distribution cadence or share classes may differ. Descriptive grouping is not a uniqueness rule. Equity and ETF records cannot carry fund-plan fields; Indian mutual fund variants do not use the exchange-listing table in this increment.

Direct and regular plans can share a portfolio while retaining separate NAVs; similarity is insufficient identity evidence. [AMFI direct-plan explanation](https://www.amfiindia.com/investor/knowledge-center-info?zoneName=DirectPlan). Published NAV rows distinguish growth/payout and reinvestment ISINs and contain different distribution cadences, so a code or plan/option label alone cannot silently collapse variants. [AMFI published NAV data](https://portal.amfiindia.com/spages/NAVAll.txt). Detailed cadence is not inferred by this schema; the exact ISIN identifies the supplied security.

Provider security identifiers use a finite namespace (`indmoney_india`, `indmoney_us`, `indmoney_funds`, `ubs`, `amfi_nav`) plus exact value and qualifier. An AMFI reference requires a numeric code and explicit distribution option; its mapping must agree with the target fund option. Other namespaces have an empty qualifier. Namespace/value/qualifier uniqueness is owner-scoped; case and leading zeros are preserved. These are normalized project contracts, not verified broker export specifications.

Every explicit link, correction or unlink appends a revision with its immediate predecessor. Expected revisions, composite foreign keys and transaction locks prevent stale writes, branching history, cross-owner links and a listing from another instrument. Provider/asset/currency compatibility is checked in PostgreSQL too. A repeated current mapping is a no-op; unlink cannot be the initial revision. Later financial evidence must retain the mapping revision it used.

Only public security identifiers belong in this table. Account numbers, folio references, usernames and provider credentials belong neither here nor in labels; private account references keep the [separate encrypted custody contract](accounts-source-mappings.md#private-references-and-keys). Instrument identifiers and their owner association are still private portfolio data, protected by RLS, restricted grants and encrypted recovery. They are not logged or exposed through URLs/browser storage.

## Account position identity

A position identity is the owner, canonical account, instrument and explicit holding form (`folio`, `demat`, or `custody`). It contains no units or value. UBS and INDmoney positions in the same security remain separate because their accounts differ. Several listings for one instrument do not create extra positions. A folio is represented by its canonical account, not copied into the position key as plaintext.

Bank accounts cannot have security positions. Indian brokerage positions use demat form; US brokerage equity/ETF positions use custody; UBS employee-share positions use equity/custody; fund accounts use fund/folio or fund/demat. Fund positions require INR among the account's declared native currencies. Unsupported combinations fail. Exact repeats return the existing position. Creating a new position and archiving its account share the same owner lock; archive retains existing positions and prevents new ones.

## Boundaries and persistence

The six added tables are `fund_schemes`, `instruments`, `instrument_listings`, `instrument_identifiers`, `instrument_mappings`, and `account_positions`. All use non-null owners, composite owner/parent references and forced active-owner row policies. Runtime receives SELECT and narrowly scoped INSERT columns; no UPDATE, DELETE, TRUNCATE or audit-timestamp assignment is granted. The authentication identity has no access. Database exceptions are sanitized and unknown/foreign reads are indistinguishable.

Services reuse trusted `WorkspaceTransaction` ownership and the account mutation lock/savepoint, supporting atomic work across account and instrument identities. They do not authenticate callers or accept payload owners. Pages default to 25 and cap at 100, with opaque UUID cursors or exclusive mapping-revision cursors. New records are capped at 1,000 per owner/table. Schema and reference strings have explicit length/character bounds. A transaction object cannot outlive its transaction, and failed operations cannot leak partial records or owner context into a pooled connection.

## Migration, recovery and verification

Apply the normal [local migration command](database-foundation.md#commands-and-lifecycle) to reach `0007_instruments`. Existing accounts, keys, mappings, authentication and preferences are preserved. No security catalog, financial position, provider credential or owner is seeded. Tests cover fresh creation, repeated migration, upgrade with existing accounts, injected migration failure, and disposable downgrade/re-upgrade.

Recovery format **3** includes all seventeen application tables: fifteen durable tables and two explicitly omitted session/admission tables. Fund schemes restore before variants, listings and identifiers before mappings, and accounts/instruments before positions. The separate-cluster test includes two owners, direct/regular variants, listings, mapping corrections, positions at active/archived accounts and rotated private account references. It compares exact durable rows, revisions, constraints, column/table grants and row policies and rejects pre-restore sessions. Identifier keys remain separate from the encrypted database object.

Formats 1 and 2 must be restored with their matching repository/schema, then migrated forward. No manifest is relabeled. The [bounded local recovery limits](local-packaging.md#encrypted-foundation-recovery) and hosted gaps still apply. Fixtures checkpoint the guarded disposable database before rebuilding schemas, allowing PostgreSQL to recycle WAL within the existing 256 MiB tmpfs; fsync, full-page writes, storage limits and migration/rollback assertions are retained.

Tests cover checksum errors, explicit fund variants, same-name/ticker collisions, provider qualifiers, wrong listing links, cross-owner references, archived/incompatible accounts, concurrent creation/correction, rollback, bounds and recovery. Public checksum examples and fabricated unassigned identifiers are test data, not a registry or personal portfolio. Actual check counts and CI results are recorded in the PR.

Next is [4D.1: source evidence and review staging](financial-data-plan.md#delivery-increments).
