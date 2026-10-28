# AMFI market source positions

Step 5F.2 extends the internal [market evidence contract](market-evidence.md) so an explicitly versioned AMFI NAV observation retains its original position in a [bounded report](amfi-nav-contracts.md). Original data occurrences are distinct from the number of observations stored for an owner.

## Versioned position contract

The default remains version 1. Every existing valid namespace keeps its integer occurrence range of 1 through 1,000. Explicit version 2 is valid only for `kind=nav` and `namespace=amfi_nav_report`, with an original occurrence of 1 through 25,000. Manual, exchange-quote and FX evidence cannot use version 2, even at an occurrence below 1,001. Application versions and occurrences reject booleans, floating-point values and numeric strings.

The source identity remains owner, namespace, digest algorithm, digest, occurrence, normalizer and normalizer version. Contract version is part of the immutable payload, not a new identity dimension. Reusing a source identity with a different contract version conflicts in either direction; exact replay returns the original observation. A different source digest may identify a separate observation. Source decimal spelling, dates, target identity, missing values and nonpositive-value semantics remain intact.

A reported position of 25,000 can describe one retained observation. Market service and database admission remain capped at 1,000 observations and 1,000 selection revisions per owner. Recovery remains bounded at 1,000 rows per retained table and 4,000,000 plaintext bytes. This increment does not authorize retaining an entire report or increase any admission, traversal or archive budget.

## Migration and recovery

Forward migration `0025_market_nav_occurrence` follows `0024_bank_account_setup`. It replaces only the occurrence/version checks with the explicit versioned domain. Existing source identity, target/value constraints, ownership policies, column privileges, immutable observations, serialized writes and selection history remain in force.

Every retained version 2 observation prevents downgrade to the preceding schema. This includes low occurrences, unselected observations, superseded observations and observations whose selection was cleared, for every owner. The disposable migration runner locks the tables and makes records visible to the schema owner within its transaction before checking the guard. A failure rolls back the migration and restores forced owner policies. Legacy-only evidence can downgrade and upgrade without rewriting its history.

Older applications that accept only contract version 1 cannot read version 2, including low-occurrence observations. Use the matching application and schema; after version 2 admission, compatibility changes require a forward migration. Do not delete, renumber or rewrite evidence to force application rollback.

[Encrypted recovery](local-packaging.md#encrypted-foundation-recovery) advances to format 21 with the same 51 application tables: 47 retained durable tables and four omitted live session/admission/connector tables. The decoder applies the shared exact-type/domain guard to every market observation before reference checks, destination validation, engine construction or SQL insertion. This prevents PostgreSQL from silently accepting a JSON string or boolean as an integer source position. The narrow guard validates kind, namespace, version and occurrence; existing schema checks still validate other fields and relationships inside the atomic restore transaction.

Format 20 and earlier archives require their matching repository/schema before a tested forward upgrade. Current restore checks the exact format, schema, migration digest and application compatibility. Encryption keys, identifier keys and hosted identity recovery remain separate from the archive.

## Remaining source boundary

This capacity extension operates on already-owned synthetic or saved evidence. It adds no provider request, report adapter, source registration, API route, automatic selection, valuation or acquisition job. It establishes no ongoing AMFI source-use entitlement.

The current market schema does not retain every parsed report field: file-line position, original date spelling, both identifier roles, source plan/option labels and the chosen mapping revision remain outside it. A separate adapter must settle that immutable provenance and revalidate owned mappings before claiming complete report-to-target lineage. Identifier normalization, retention volume, freshness policy, application activation and valuation remain separate work.

## Verification

Focused synthetic checks cover legacy defaults, all source/version boundaries, inclusive limits, primitive rejection, exact values and preservation of a selected report occurrence above 1,000. Encrypted archive cases verify rejection before restore infrastructure is reached. PostgreSQL checks cover actual constraint names, runtime and administrator writes, cross-version replay conflicts, unchanged owner quotas, interrupted migration rollback, legacy round trips, retained-history downgrade refusal and separate-cluster encrypted recovery.

The focused run passed 306 Python cases and strict typing. All 13 new PostgreSQL cases passed in 36.30 seconds; a combined 59-case affected set, including those 13 plus existing market, protected read, bank setup recovery and complete encrypted recovery checks, passed in 146.19 seconds. The initial database run passed 12 cases and failed while committing synthetic recovery setup; the fixture now commits the original selection before its later correction, preserving the existing production selection rules. The cleared-choice assertion uses the existing unselected resolution state. Owned containers, networks and test credential contexts were removed. Final lint and format checks and projected documentation links are recorded alongside these focused results; integrated repository verification remains separate. No live report, private statement or hosted provider is used.
