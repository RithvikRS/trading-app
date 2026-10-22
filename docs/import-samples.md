# Bank import sample evidence

Step 2E.2 uses seven bundled fictional examples. These are illustrative normalized statement records, not supported HDFC/SBI CSV or PDF formats. All examples are read-only. They cannot write to Banking or create an import receipt.

## Scope and comparison baselines

Each batch has an allowlisted ID, revision `r1`, supplied example fingerprint, known institution/account, sample owner, explicit date format, native currency, and stable row IDs independent of array order. Fingerprints are fixture labels, not hashes of uploaded files. Baselines are fixed copies selected for each scenario; they do not represent the current Banking store and are unaffected by global partial mode or connection simulations. The real financial screens retain their existing records.

| ID | Scenario | Incoming rows | Isolated comparison baseline |
| --- | --- | ---: | --- |
| i01 | First HDFC statement | 16 | Empty example store |
| i02 | Exact HDFC replay | 16 | All 16 HDFC October records; same example fingerprint already received |
| i03 | Overlapping HDFC statement | 16 | Five records corresponding to t01–t05 |
| i04 | Repeated HDFC payments | 3 | Empty example store; incoming rows are t05, t06, and one identical copy of t05 |
| i05 | Conflicting SBI source identity | 12 | All 12 SBI October records; incoming t26 changes INR 2,200 to INR 2,300 |
| i06 | HDFC field-validation excerpt | 7 | Empty example store |
| i07 | Incomplete SBI statement | 11 | Empty example store; incoming statement omits t26 |

Most examples cover 1–20 October 2026, through 10:00 IST. i04 is an excerpt for 5 October with no supplied opening/closing balances. i06 is an incomplete validation excerpt. i07 retains the 20 October balance but its activity date is 19 October, 10:00 IST. None implies complete October coverage.

## Independent expected results

Counts partition every incoming row exactly once. Candidate amounts contain only **New candidate** rows; possible overlaps, conflicts, invalid records, already-present rows, and within-batch copies do not enter that subset. No candidate amount is committed or represented as the complete effect of a future import.

| ID | New | Already present | Duplicate within batch | Possible overlap | Conflict | Invalid / unsupported |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| i01 | 16 | 0 | 0 | 0 | 0 | 0 |
| i02 | 0 | 16 | 0 | 0 | 0 | 0 |
| i03 | 10 | 5 | 0 | 1 | 0 | 0 |
| i04 | 2 | 0 | 1 | 0 | 0 | 0 |
| i05 | 0 | 11 | 0 | 0 | 1 | 0 |
| i06 | 0 | 0 | 0 | 0 | 0 | 7 |
| i07 | 11 | 0 | 0 | 0 | 0 | 0 |

| ID | Readable posted credits | Readable posted debits | Pending credits / debits | Supplied opening → closing | Closing minus calculated closing |
| --- | ---: | ---: | --- | --- | --- |
| i01–i03 | INR 95,800 | INR 86,665.90 | INR 0 / 1,299 | INR 177,285.90 → 186,420 | INR 0 |
| i04 | INR 0 | INR 540 | No pending rows | Not supplied | Unavailable |
| i05 | INR 43,250 | INR 6,699 | INR 2,000 / 0 | INR 38,199 → 74,850 | INR 100 |
| i06 | INR 95,000; USD 0 | INR 5,530; USD 180 | No pending rows | INR 177,285.90 → 186,420 | Unavailable: one unreadable amount and incompatible currency |
| i07 | INR 43,250 | INR 4,399 | INR 2,000 / 0 | INR 38,199 → 74,850 | INR −2,200 |

New-candidate posted net movement is INR 9,134.10 for i01, INR −61,355.90 for i03, INR −360 for i04, and INR 38,851 for i07. i01/i03 also contain the INR 1,299 pending debit; i07 contains the INR 2,000 pending credit. i02/i05/i06 have no new-candidate amounts. Source subtotals deliberately include every readable supplied occurrence, including repeated/conflicting rows; candidate subtotals use each eligible source identity at most once. Source balance arithmetic never uses display FX and does not establish identity, complete coverage, or permission to save.

## Identity and validation examples

The two café payments have equal dates, descriptions, and amounts but different source identities/references. They remain distinct in i04. In i03, the second resembles a baseline entry under a different identity, so it needs interpretation; similarity alone never automatically skips it. An exact within-batch copy links to the canonical incoming row, selected by stable row ID rather than list position. Conflicting immutable fields under one scoped source identity preserve both versions.

i06 contains an ambiguous booking date with an unspecified format, malformed decimal text, an impossible value date, a missing transaction identity, incompatible account/owner evidence, an unexpected USD record in an INR statement, and an unsupported security event. The last record includes literal HTML-like text to verify plain-text rendering. Invalid amounts are unavailable, never zero; readable amounts on otherwise invalid rows remain explicitly labeled partial evidence in their original currency/status group. No mapping or field correction is available in this increment.

Inspection keeps original strings beside normalized fields and matched baseline evidence. While amounts are hidden, original text, descriptions, references, and search fields that could contain monetary text are removed from the rendered content. Native/display amounts and reconciliation values use shared masking. Routes contain only the allowlisted batch ID; filters and selected rows remain in memory. See [prototype notes](ui-prototype.md) for implemented behavior and validation.

## Reversible review expectations (Step 2E.3)

Review choices start empty. Suggested choices include only valid new candidates and skip exact existing/within-batch matches; they leave overlaps and invalid/conflicting rows for individual inspection. A single confirmation applies eligible choices atomically and has one undo entry. Exclusion uses a fixed further-source-review reason and never removes underlying completeness, identity, or reconciliation blockers.

| Sample | Expected review outcome |
| --- | --- |
| i01 | Suggested choices: 16 included, 0 present/excluded/unresolved. Proposed posted net INR 9,134.10, pending debit INR 1,299. Combined closing INR 186,420; both differences zero. Can complete. |
| i02 | Suggested choices: 0 included, 16 present, 0 excluded/unresolved. No incremental movements. The retained baseline closes at INR 186,420. Can complete; repeat confirmation creates no extra receipt. |
| i03 | Suggested choices: 10 included, 5 present, 1 unresolved. Supplied distinct-identity evidence for row-t06 versus row-t05 permits individual inclusion. Then 11 included, 5 present; proposed posted credits INR 800, debits INR 62,335.90, net INR −61,535.90; pending debit INR 1,299. Combined closing INR 186,420. Can complete. |
| i04 | Suggested choices: 2 included, 1 excluded exact copy, 0 unresolved. Unique proposed debit INR 360. The source still contains INR 540 across its three occurrences. Missing balances and incomplete coverage block completion. Skipping the copy cannot replace a missing canonical decision. |
| i05 | 11 present and 1 unresolved after suggestions. Excluding the conflict retains source/identity and reconciliation blockers. No overwrite or completion. |
| i06 | Seven unresolved rows; exclusions record choices but retain all mandatory-field/scope/coverage blockers. No mapping can change owner, bank identity, unsupported kind, or malformed fields. |
| i07 | 11 included after suggestions. Pending credit INR 2,000 stays separate; missing coverage and INR −2,200 difference still block completion. |

The supplied distinct-pair annotation in i03 is evidence for two separate source references, not a general rule that any unequal IDs prove separate payments. Removing that evidence disables inclusion of the overlap. The only compatible mapping for these examples is their already-supplied bank account; there is no supported alternate account or corrective mapping editor.

A review receipt records the batch revision, choices/reasons, counts, native proposed groups, and reconciled difference in memory. Reopening removes its current receipt before editing. Undo restores the previous review state; reset clears all import reviews/history only. Changed source, baseline, mapping, revision, or current decisions invalidates a pending action atomically. Existing decisions whose evidence changes stay visibly incompatible until restored and reviewed again. Source snapshots and all financial workspace totals remain unchanged.


## Investment sample expectations (Step 2E.4)

These are generic normalized fictional examples, not supported provider exports. They retain the existing holding/quote dates and use isolated comparison copies. All quantities use eight decimal places internally, quotes six, and money native cents/paise. Position values round half away from zero only after exact quantity × quote multiplication. No source units are summed across different instruments, folios, plans, or accounts. Current demo FX is presentation-only.

| ID | Supplied evidence and expected outcome |
| --- | --- |
| i08 | Indian stock/ETF snapshots: Reliance 150, HDFC 200, India ETF 1,000; values INR 420,000 + 330,000 + 218,650 = 968,650. Separate cash snapshot INR 18,500 appears twice with the same identity. Four unique records plus one skipped copy; cash counts once. Snapshot-only completion is available, with transaction history explicitly absent. |
| i09 | US snapshots: Apple 20, total-market ETF 8.25, technology ETF 9.7, Accenture 4. Values USD 4,200 + 4,950 + 4,850 + 1,200 = 15,200. Separate broker cash USD 120. Five unique records; snapshot-only completion is available. |
| i10 | Northstar Direct / Growth / SOA / Sample folio B / INDmoney India: 2,000 units from INDmoney and a matching consolidated-statement comparison, both at the same snapshot instant. Select either source for that position only. The result remains 2,000 units / INR 310,000, never 4,000 units. No incremental position is added. |
| i11 | Advisor Northstar Regular / Growth / SOA / Sample folio D: 5,000 units. The similarly named Direct / Growth position at INDmoney is a separate account, scheme and folio (2,000 units). The advisor quote is deliberately unavailable in this example. Identity/position review can complete with valuation unknown; no cost or NAV is inferred. |
| i12 | UBS ACN 24 units, independently compared with INDmoney US ACN 4 units. Remaining lots are 8 + 6.5 + 9.5 = 24. Purchase amounts USD 1,964 + 1,705.60 + 2,629.60 = 6,299.20; known fees USD 0 + 1.25, with one unavailable fee. Lot dates are 15 Nov 2025, 15 May 2026, and 15 Aug 2026. A separate supplied cash dividend example is gross USD 30.96, withholding USD 7.74, net USD 23.22 on 21 Aug 2026; withholding is an additional fictional walkthrough field. The lot sum matches, but missing opening/activity history, cash checkpoints, fee, and tax-basis evidence block this lot/history review. |
| i13 | One conflicting occurrence and six invalid occurrences. Mixed evidence: a Direct fund snapshot changes 2,000 to 2,100 units; another lacks its folio; quantity/quote precision exceeds supported scales; ownership is incompatible; an unsupported corporate action is supplied; an acquisition record lacks date/purchase/basis. Neither exclusion nor source preference repairs these blockers. Literal HTML-like source text remains plain text. |
| i14 | Bounded INDmoney US ACN purchase history: supplied opening 0 units on 1 Jul 2026 + existing fictional purchase of 4 on 21 Jul 2026 = closing 4 on 20 Oct 2026. Purchase USD 1,120, explicitly supplied fee USD 0. Separate cash opening USD 1,240 − purchase USD 1,120 = closing snapshot USD 120. These openings/completeness/fee are additional fictional walkthrough evidence, not assumptions about the live source or complete investment history. Three typed records; activity and cash checks pass. |

Snapshot review attests only to the selected identities and supplied position checkpoints. It does not attest to transactions, cost basis, taxes, lots, or complete account coverage. Lot/history examples require their stated openings and supported activity. Cash balances, dividend components, purchase amounts, fees, and marked position values remain separate native groups; they are never added together into an investment total. Fund source preference is bounded to an identical account/instrument/folio/plan/option/form/date and cannot override units or immutable-field conflicts. Bank and investment reviews share one import undo/reset history while remaining isolated from financial screens and connection simulations.
