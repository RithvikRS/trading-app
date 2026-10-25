# UBS employee-share integration: Step 7A

Research date: **25 October 2026**. This increment records public feasibility and delivery boundaries for the owner's Accenture employee-share account. It adds no connector, parser, credential, database change or financial record.

[Step 7B.1](lot-inspection.md) implements protected saved-lot inspection and retained history. [Step 7B.2](account-activity-inspection.md) adds account-wide event revisions and source-coverage inspection. [Step 7B.3](saved-receipt-inspection.md) adds saved historical completion receipts and batch-wide row effects. These shared interfaces use existing owned reads; they establish neither UBS account access nor a supported export format or complete historical coverage. Native comparison equations and their frozen inputs remain separate inspection work.

Prefer a supported, narrowly scoped API or data-download interface when UBS confirms that it covers this account and permits this client. Public evidence identifies possible routes, but **no personal Accenture-plan API, export layout or historical coverage has been verified**. Statements remain a fallback for demonstrated gaps.

## Public evidence

All sources below were checked on the research date. Public product descriptions establish candidates, not account entitlement or successful access.

| Question | Primary evidence | Finding and limit |
| --- | --- | --- |
| Which stock-plan portal? | [UBS Accenture Benefits](https://www.ubs.com/microsites/accenture/en/contact-us.html), [UBS One Source guidance](https://www.ubs.com/us/en/wealth-management/ubs-onesource.html) | The Accenture page explicitly links One Source for ACN. The linked public destination resolves to `onesource.ubs.com/ACN/`; its account content was not accessible in this review. Actual owner access remains untested. |
| Is there a supported software-download route? | [UBS Online Services User Agreement, July 2025, sections 5 and 21(e)](https://onlineservices.ubs.com/staticfiles/olspages/adobe/OLS_General_User_Agreement.pdf) | The agreement describes account aggregation and enrolled OFX downloads into financial software. It does not establish eligibility for this One Source account, a custom-client specification, read-only credentials or history depth. Downloaded information does not replace official account records. |
| Can the public developer catalog be used? | [UBS API products](https://developer.ubs.com/custom-product-page), [developer documentation](https://developer.ubs.com/documentation) | The catalog includes Swiss corporate and EU cash-account APIs and a securities-settlement-status product. These descriptions do not establish an Accenture ESPP history service. The settlement reference exposed no anonymous specification. Portal try-out responses are static mock data, not account-access evidence. |
| Is personal client onboarding established? | [UBS ecosystem](https://developer.ubs.com/ubs-ecosystem) | The page describes partner evaluation. It does not promise self-service production access for a personal tracker. No registration or support contact was made. |
| Which documents are documented? | [UBS stock-plan support](https://www.ubs.com/us/en/wealth-management/contact-us.html) | Stock-plan support lists account statements, transaction confirmations/notices and prior tax reports. These are report-family candidates. File type, locale, field layout, purchase-lot detail and oldest available date for this account are unknown. |
| Can email supply the documents? | [UBS e-Delivery Agreement, August 2018](https://onlineservices.ubs.com/staticfiles/pws/adobe/Online_Account_Alerts_and_Delivery_Agreements.pdf) | The older agreement includes stock-benefit accounts and generally describes email links to secure downloads. It does not establish attached statements, a document API or current owner delivery settings. |
| What does Accenture publish about the plan? | [Accenture India benefits](https://www.accenture.com/in-en/careers/local/benefits) | The page advertises a 15% ESPP discount and contributions up to 10% of pay. This is plan-level context, not evidence of any particular purchase, monetary discount, basis or payroll deduction. |

The OFX lead is worth checking before choosing file acquisition. No documented history-retention period, pagination contract, Accenture CSV/XLS/PDF schema, personal-client fee, renewal guarantee or provider-enforced read-only scope was established. That is an evidence gap, not proof that an interface is unavailable.

Do not reuse web-login passwords, PINs, OTPs, session cookies or trading-capable credentials to turn this lead into an unofficial connector. The [security boundary](security.md#secrets-and-encryption) and [connector acceptance criteria](integrations.md#connector-acceptance) still apply. A portal's internal requests and third-party aggregator directory listings are not supported custom-client contracts.

## Financial evidence boundaries

Use the existing `employee_stock` / UBS / United States account and `ubs_espp` source namespace from [accounts and mappings](accounts-source-mappings.md). Declared native currencies require source evidence; an INR display preference cannot change USD evidence. Map the supplied security/listing identity explicitly using [instrument identities](instrument-identities.md), not the ACN ticker alone.

| Evidence | Preserve | Do not infer |
| --- | --- | --- |
| Shares held | Dated position snapshot, supplied share precision, custody/account scope and source | A purchase event, acquisition date or complete history from current quantity |
| ESPP acquisition lot | Original quantity, independently supplied acquisition/observation dates, purchase cost and unit price | Remaining units or disposal allocation from original quantity |
| Remaining lot | Supplied remaining units and observation date; acquisition date only if supplied | Original quantity or a sale merely because remaining units are zero |
| Discount | Supplied monetary discount separately from purchase cost | A monetary amount from the advertised 15%; the existing `discount_amount` contract does not accept a percentage |
| Reported tax basis | Source-labeled basis, currency and missing reason | Taxable gain, Indian tax basis, adjusted basis or equality with cash paid |
| Purchase or sale activity | Supplied quantity, native net cash, fees, relevant independent dates and posting state | Cash paid from quantity multiplied by price; an ESPP lot observation creates no movement |
| Dividend | Independently supplied gross, withholding, fees and net cash | Both gross and net as separate income movements; automatic reinvestment |
| Payroll and cash | Independently evidenced contributions, cash credits/debits, refunds and transfers | A payroll contribution as a purchase, income or available UBS cash |
| Corporate action or share transfer | Source identity, dates and explicit before/after evidence | A synthetic buy/sell or a generic cash movement to force unsupported semantics into the ledger |

These are application requirements, not claims that UBS supplies each field. [Exact values](financial-values.md), [event movements](financial-events.md), [lot evidence](lot-evidence-corrections.md) and [snapshot evidence](snapshot-evidence.md) already distinguish these facts. Their bounds and unknown-value rules apply unchanged. Fractional shares and reported decimal spelling must survive normalization exactly.

Corporate-action transformations, disposal allocation, percentage discounts, entitlement/vesting balances, payroll-detail modeling and multi-currency settlement need their own contracts when encountered. Unsupported evidence must remain visibly unresolved and prevent a complete-history claim. Do not silently discard it or relabel a batch as partial to bypass reconciliation.

## Identity, overlap and historical coverage

UBS statements, confirmations, lot reports and any future API may describe the same economics. Separate source occurrences are not separate purchases merely because they came from different reports. Reuse [protected transaction identities and corroborating evidence](event-evidence.md) only where exact identity/economics support it. Matching dates, amounts or share quantities alone cannot merge legitimate repeats.

A UBS-held ACN position and a separately purchased ACN position at INDmoney remain different account positions even when the instrument is the same. If INDmoney later reports an externally linked UBS holding, require evidence of the same underlying account before mapping it; select one snapshot explicitly instead of adding both. A subsequent share transfer requires independently supported transfer semantics and evidence on both sides, not a sale and repurchase invented from snapshots.

The portfolio's direct and regular mutual-fund plans remain distinct instrument variants. Neither UBS integration nor aggregate-provider overlap can collapse those variants or change existing CAS/advisor mappings.

Each observation retains its own supplied period and coverage claim. Do not join overlapping intervals into lifetime coverage, interpret a missing period as no activity, or sum acquisition and remaining-lot observations. Partial API history can coexist with older statements, but it becomes reconciled coverage only after exact source and combined share/cash checks. Use [statement boundaries](statement-boundaries.md), [reconciliation](reconciliation-contracts.md) and [source-history inspection](source-history.md). Opening balances and cash-date basis must be explicit. Existing bounded page/table limits must be evaluated against the actual history volume before promising a complete backfill.

## Small delivery increments

| Increment | Work | Acceptance boundary and dependency |
| --- | --- | --- |
| **7A: public feasibility** | This evidence matrix and delivery plan | Public facts linked and dated; no asserted API/export compatibility, login or private data. Implemented by this document. |
| **7B.1: lot evidence inspection** | [Implemented protected lot inspection](lot-inspection.md) over existing owned reads | Synthetic verification covers separate acquisition/remaining scopes, cost/discount/basis, missing values, correction history, exact parent/revision binding, masking, stale-response disposal, keyboard access and both themes. No provider access, inferred balances, disposal allocation or return. |
| **7B.2: activity and coverage inspection** | [Implemented protected account activity](account-activity-inspection.md) over existing event/history/source reads | Includes other positions and account-level cash. UUID keyset pages are not chronological history. Posted/pending, active/cancelled and current/historical states, exact native values and each revision's source remain distinct. Synthetic verification covers identity/revision binding, bounded navigation, masking and late responses. No acquisition, financial posting, inferred reversal, balance or completeness claim. |
| **7B.3: saved completion inspection** | [Implemented historical batch receipt inspection](saved-receipt-inspection.md) over existing receipt/row reads | Event or lot revision context binds the exact batch and coverage. Whole-batch record/link/correction/exclusion effects retain original review and target revisions. Bounded pages validate final row/selection counts and originating lineage without keeping prior row payloads. Reconciled mode is historical metadata; equations and frozen comparison inputs are not yet inspected. No acquisition, completion mutation, current balance or tax/return claim. |
| **7C: account-specific acquisition contract** | Evaluate supported API/OFX access first; identify documents only for missing coverage | Provider-dependent. Establish custom-client eligibility, scopes, credential separation, permitted storage/use, fees, stable identities, history range, paging, renewal/revocation and all required activity types. An official specification and account-specific evidence are required before enabling network acquisition. If files are needed, identify one actual report/layout and its export options before writing a parser. |
| **7D.1: bounded acquisition and staging** | Implement one verified interface/layout, with exact normalization and immutable source observations | Depends on 7C. Synthetic fixtures must follow the verified contract. Reject unknown versions, truncation, ambiguous identifiers/dates/currencies and unsupported economics. No financial posting or automatic completion. Apply existing sandboxed parser transport for files; use isolated encrypted server-side custody for a supported API. |
| **7D.2: reviewed lots and activity** | Add explicit evidence mapping and completion for the supported subset | Depends on 7D.1 and required domain contracts. Exact replay creates no duplicate event; cross-report evidence cannot double count; conflicts and incomplete history remain visible. Whole-batch previews, revision checks, atomic receipts, owner isolation and recovery must cover every new durable field. |
| **7E: reconciliation and connected coverage** | Reconcile evidenced shares and native cash across periods and sources | Depends on supported activity plus source boundaries. Opening plus posted movements must match closing evidence where complete coverage is claimed; gaps/unsupported actions block that claim. Corrected evidence invalidates stale choices while preserving prior receipts. Test failure/retry and restore, with no tax or performance claim. |

The two synthetic inspection increments are independent of provider onboarding. Acquisition, financial posting and complete-history acceptance depend on evidence and must not advance by inventing UBS field names. Each increment stays independently reviewable and follows the existing [verification workflow](verification.md).

## Evidence still needed

For acquisition selection, record only non-sensitive capability metadata first: the account's portal/product family, any provider-documented API/OFX option, report names and export file types, supported date ranges, and whether lot/cash/dividend history is included. Do not put credentials, account references or real reports in chat, repository fixtures, logs or screenshots.

A later local compatibility exercise must use a documented protected intake, minimize identifiers, and produce synthetic fixtures with the same verified structure. For APIs it must also demonstrate read-only authorization, bounded reads, refresh/revocation and safe failure behavior. Until those checks exist, no live UBS connection or report format is supported.
