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
