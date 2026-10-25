# First complete investment flow

Stage 5 provides reviewed investment evidence and connected portfolio views. Initial acquisition now prioritizes the [official INDmoney integration](indmoney-integration-plan.md); verify its custom-client access and actual coverage before selecting a statement format. The detailed CAS path below remains a fallback for missing history or unsupported folios. Direct and regular plans, growth and distribution options, and separate folios remain distinct.

This plan follows the [financial persistence foundation](financial-data-plan.md). Its internal services and protected reads are implemented. [Step 6D](reviewed-snapshots.md) adds browser review/completion for saved snapshot evidence and connected investment list/detail views. [Step 6E.1](source-history.md) adds saved-source coverage inspection, and [Step 7B.1](lot-inspection.md) adds protected lot observations and retained correction history. File intake, actual CAS compatibility, live portfolio acquisition, activity completion screens and NAV/FX valuation remain outstanding. The protected [account directory](connected-accounts.md) reads saved identities independently of those source-specific capabilities. The synthetic prototype remains separate.

## Source evidence and unresolved compatibility

Research checked on 24 October 2026:

| Source | Established evidence | Remaining boundary |
| --- | --- | --- |
| Detailed mutual-fund CAS | [AMFI](https://www.amfiindia.com/investor/become-mf-distributor?zoneName=consolidatedAcct) describes RTA/depository coverage and detailed statement access. The [myCAMS guide](https://newmycams.camsonline.com/myCAMSUserGuide) documents statement requests. | No representative detailed CAS fixture has been verified for this application. Select a concrete provider/layout and verify its identity, dates, signs, transaction references, unit balances and amount meanings before claiming support. |
| AMFI latest NAV text | The [download page](https://www.amfiindia.com/net-asset-value/nav-download) links the [current report](https://portal.amfiindia.com/spages/NAVAll.txt), with eight semicolon-separated columns including explicit Plan and Option. | Layout, values, identifiers and observation dates still require strict validation. A successful download does not establish fresh prices or fund ownership. Historical access and scheduled-use conditions need separate verification. |

The observed NAV report includes category/AMC headings, incomplete variant fields and observations from earlier dates. Preserve each row's date and both identifier roles. Never infer a plan from its name, use a download timestamp as a price date, or associate funds by name similarity. Report changes must produce a visible failure instead of shifting column meanings.

AMFI's [terms](https://www.amfiindia.com/terms-of-use) allow personal non-commercial access but restrict significant electronic storage and broader reuse. The public download link alone does not resolve ongoing acquisition, retained price history or later multi-user redistribution. Verify the intended use or select a source with suitable permissions before enabling acquisition. Format research and a pure parser do not establish that entitlement; retain only research counts/digests after the one-off check.

CAS compatibility requires a reproducible, irreversibly sanitized representative fixture or equivalent independently verifiable format evidence. Fabricated documents test hostile-input handling and financial edge cases; they cannot establish provider compatibility. Personal statements, passwords and extracted identity text stay outside Git, CI, external processing services and diagnostic output.

## Delivery sequence

Initial Stage 6 discovery and compatibility work now precedes further file-parser implementation. Completed 5A, 5B.1, 5E.0 and 5E.1 remain in use; step numbers are retained. An API snapshot can supply only the evidence it actually contains. The statement sequence below resumes when a verified source gap requires it.

Each increment has its own conventional commit and `dev` to `main` PR, documentation, review and final-revision checks. Complete independent work while source-specific evidence is unavailable. The 5E.0 sign-in binding precedes financial screens and does not require a source adapter. Do not enable an unverified source adapter to make the interface appear complete.

| Step | Deliverable | Acceptance |
| --- | --- | --- |
| 5A | Public NAV report contracts and exact identifier matching | Pure, bounded parsing of the observed current format; exact decimal/date preservation; explicit missing/ambiguous/unsupported outcomes; separate payout/growth and reinvestment ISIN roles; no network, database writes or automatic identity creation. |
| 5B | Isolated document intake; [5B.1 transport contracts](parser-transport.md) implemented | A fixed, non-root, network-disabled parser boundary with no database/provider/session secrets; strict file, time, memory, concurrency and output limits; authenticated bounded intake and cancellation; temporary plaintext/password cleanup. |
| 5C | One verified detailed CAS adapter | Original row order and reported balances preserved; explicit provider/layout version, folio and fund evidence; unsupported transaction types retained as blocked; verified known examples and hostile documents. |
| 5D | Owned staging and reviewed completion | Server-derived ownership, explicit account/folio/instrument mappings, revision checks, overlap/conflict review, immutable completion and source-specific reconciliation. Missing cash checkpoints cannot be replaced with invented balances. |
| 5E | Connected import and investment screens; [5E.0 sign-in context](workspace-context.md) and [5E.1 account directory](connected-accounts.md) implemented | Protected upload/review/receipt workflow and holdings/detail pages, Indigo & Apricot in both themes, accessible keyboard/mobile interactions, exact amounts and visible coverage/freshness. Lock/revocation discards private state and pending requests. |
| 5F | NAV acquisition and valuation | An allowlisted bounded public-data fetch, persisted exact source evidence and explicit source choice, safe retries and dated valuation for mapped fund positions. No holdings changes from a NAV update. |
| 5G | End-to-end acceptance and recovery | Synthetic statement-to-portfolio checks, repeat/overlap/conflict imports, two-owner denial, encrypted restore, resource measurements, failure recovery and documented source/hosted limitations. |

Step 5B.1 implements only bounded transport contracts. Worker provisioning, native parser isolation and authenticated intake remain separate increments; no file route or supported PDF adapter is enabled. Split a step when necessary to keep a schema change, isolation boundary or interface change independently reviewable. INDmoney acquisition now follows the separate integration plan ahead of file parsing. Banking, UBS, cards, unattended schedules and returns remain separate capabilities.

## File and parser boundary

Accept only the selected format with explicit size and content validation. A `.pdf` name or MIME header is insufficient. Reject archive/macro/conversion paths, unsafe attachments, unsupported encryption, page-count overflow and ambiguous layouts. Do not fetch links embedded in statements.

Run parsing in a separately provisioned Linux worker with network access disabled, a read-only root, bounded temporary memory, dropped capabilities, no privilege escalation, separate process namespace, no core dumps or container swap, and CPU/memory/PID limits. The API must never receive a Docker socket, privileged container-creation rights or a general-purpose process execution interface. A dedicated local Unix socket is a candidate transport; verify filesystem permissions, peer access, bounded framing, restart/replacement, cancellation and Windows development through Linux containers before selecting it.

Keep the worker credential-free and treat its output as untrusted. Validate structure, counts, exact values and identity evidence again in the API before persistence. Reject surplus output and partial results. No file/provider I/O occurs under a financial database lock. A lost request, timeout or parser crash cannot complete an import.

Default to no retained original statement. Process one bounded attempt in temporary memory, discard plaintext and password references after success or failure, and retain only minimized evidence needed for review and reconciliation. Memory cleanup is not a guarantee of physical erasure; real-data use additionally requires protected host storage/swap and crash handling. Any later original-retention feature needs encrypted private custody, authorization, an explicit retention period and recovery/deletion behavior.

The ordinary 4 KiB JSON financial boundary remains strict; only [snapshot completion manifests](reviewed-snapshots.md) have larger exact-path limits. A file route needs its own narrowly defined streaming boundary with exact host/origin, active MFA, bound CSRF, duplicate-header rejection, request-size/deadline/concurrency enforcement and no body logging. Do not increase every financial endpoint's limit or put passwords in URLs, headers used by access logs, browser persistence or durable job payloads.

## Financial normalization and reconciliation

Preserve source text only where it is necessary and safe. Normalize exact source amounts without floats, hidden rounding or fabricated zero fees. Record original transaction order, source occurrence, date meaning, reported unit balance, period, and explicit missing values. A third-party parser's inferred transaction type, enriched ISIN or recomputed running balance is derived information and cannot silently replace source evidence.

Use folio/provider references through the existing protected reference custody. Scheme names alone cannot establish instrument identity. Require explicit verified ISIN, plan, option, currency and holding form, with review for uncertain mappings. A consolidated document can contain multiple folios and sources; do not collapse them or double-count a position already described by another source.

Resolve the source identity contract before staging: a folio number must not be assumed globally unique across AMCs, and the current public instrument-identifier namespaces do not include a CAS-specific reference. A supported adapter needs verified provider/AMC/folio scope and an explicit compatible instrument reference. Do not invent an AMFI scheme code when a statement supplies only an ISIN. Preserve the original scope alongside any versioned normalization; extend namespaces with a forward migration when required.

Detailed fund statements may support complete unit activity without native cash balance checkpoints. The current `complete_activity` completion requires all emitted scopes to reconcile. Use conservative partial coverage until a separately tested scope-specific coverage contract exists; never invent cash opening/closing values or label the entire statement reconciled because units balance. Distinguish source-unit comparison, combined-unit comparison, cash evidence completeness and tax-basis availability.

Existing normalized batches allow 100 rows, including checkpoints. Oversized documents require explicit rejection or a deliberate whole-document grouping model with atomic completion and recovery coverage. Silently splitting a statement into batches cannot establish whole-statement completeness. Overlapping imports require exact source/economic identity and retained review; same date/amount/name is only a possible duplicate.

A multi-folio statement also needs explicit document-to-folio/batch/receipt lineage and a visible partial-completion state. Completing one folio cannot mark the whole document complete. Current service/recovery row budgets were established for synthetic foundation checks; verify representative statement volume and restore capacity, and extend those limits deliberately before real-data acceptance.

Any coverage, lineage or grouping schema extension adds a new forward migration, forced owner policies, least-privilege grants, compatible API contracts, recovery-format coverage and upgrade/rollback-failure tests. Do not edit shared migrations.

## NAV and portfolio meaning

Parse current public NAV data independently of private statements. Keep source numeric strings, source observation date, report identity and original row position. Blank, zero, negative, malformed, future-dated, stale and unsupported values have distinct outcomes; only a usable dated observation for an explicitly mapped instrument can enter valuation. Unsupported plan/option labels remain unresolved. Duplicate or conflicting matches cannot choose the first row automatically.

The existing market occurrence bound is 1,000, while a full report can have more rows. Preserve original row provenance when introducing report-to-market persistence through a deliberate contract/schema extension; do not renumber selected rows and claim they are original occurrences.

The fetcher uses fixed HTTPS destinations, certificate verification, bounded response bytes/time and conservative retry behavior. No user-supplied URLs, arbitrary redirects or ambient proxy credentials. Validate the whole input before writing a selected target; a failed refresh preserves prior evidence and marks the attempt unavailable. Repeated identical evidence cannot multiply prices or change holdings. Scheduling belongs to Stage 10 unless explicitly added to this flow with its own durable job and ownership controls.

Start the portfolio with exact sourced or reconciled fund units and their coverage date. Show native INR valuation, dated NAV, missing/stale reasons and excluded amounts. USD display requires a separately supported directed FX observation; otherwise show conversion unavailable. No approximate hard-coded exchange rate, zero substitution, cost-basis inference, XIRR or tax-return claim. Keep prices and holdings freshness separate.

## Interface and acceptance

The connected interface uses the existing protected shell and persisted display preferences. Provide upload progress, cancellation, password retry without echo, unknown-format and limit errors, mapping review, exact row details, inclusion/exclusion reasons, conflict resolution, completion effects and historical receipt inspection. Imported strings render as text. File contents and financial drafts remain memory-only and clear on lock/sign-out.

Verify dark/light contrast, distinct chart segments, keyboard focus, screen-reader labels, narrow screens and INR/USD/masked-value behavior across every new section. Handle loading, empty, stale, offline and access-denied states without exposing prior-session data. Screenshots and visual checks use fabricated data only.

End-to-end acceptance includes fresh/repeated/overlapping imports, legitimate repeated transactions, missing checkpoints, unknown fees, conflicting identity, parser crash, oversized output, concurrent/stale review, revoked sessions, failed writes, application restart and separate-database encrypted restore. Tests must demonstrate preservation of balances, provenance, decisions and receipts as well as owner isolation. Measure the financial and parsing workload separately from the locked-shell package rehearsal.

Hosted Supabase authentication, database transport/network restrictions, external key custody, private ingress, production backup recovery and source-account access remain unperformed until verified in their actual environments. Local synthetic acceptance does not establish those controls.
