import { createImportReviewState, changeImportReview, proposeImport, resetImportReviews, undoImportReview } from './import-review'
import { describe, expect, it } from 'vitest'
import { getImportBatches, previewImport, normalizeImportRow, selectImportRows, initialImportFilters, isImportId, isDisposition, clearImportSearch, clearImportSelection } from './imports'
import type { ImportId, OriginalRow } from './imports'
import { getBankSnapshots, getBankTransactions, bankReconciliation } from './banking'
import { getHoldings } from './holdings'
import { getPositions, getSummary } from './portfolio'
import { createTransferState } from './transfers'
import { createBudgetState, budgetOverview } from './budgets'
import { cashFlow, bankCoverage } from './cashFlow'
import { createRecurringState, recurringOverview } from './recurring'
import { createConnectionState, changeConnections } from './connections'

const batch = (id: ImportId) => getImportBatches().find(item => item.id === id)!
const totals = (id: ImportId, subset: 'source' | 'candidates' = 'source') => previewImport(batch(id))[subset].groups.map(group => [group.currency, group.status, group.count, group.credits.minor, group.debits.minor, group.net.minor])
// Compare exact financial values and Set members without depending on VM realm prototypes.
const financialSnapshot = (value: unknown) => JSON.stringify(value, (_key, field: unknown) => typeof field === 'bigint' ? { type: 'bigint', value: field.toString() } : field instanceof Set ? { type: 'Set', values: [...field] } : field)

describe('Bank sample import evidence', () => {
  // Independent expectations are documented in docs/import-samples.md.
  it.each([
    ['i01', 16, [16, 0, 0, 0, 0, 0]], ['i02', 16, [0, 16, 0, 0, 0, 0]],
    ['i03', 16, [10, 5, 0, 1, 0, 0]], ['i04', 3, [2, 0, 1, 0, 0, 0]],
    ['i05', 12, [0, 11, 0, 0, 1, 0]], ['i06', 7, [0, 0, 0, 0, 0, 7]], ['i07', 11, [11, 0, 0, 0, 0, 0]],
  ] as const)('%s partitions every source row once', (id, length, counts) => {
    const preview = previewImport(batch(id))
    expect(preview.rows).toHaveLength(length)
    expect(Object.values(preview.counts)).toEqual(counts)
    expect(Object.values(preview.counts).reduce((sum, count) => sum + count, 0)).toBe(length)
    expect(new Set(preview.rows.map(row => row.row.id)).size).toBe(length)
  })
  it('keeps original posted/pending totals separate from unique candidate movements', () => {
    for (const id of ['i01', 'i02', 'i03'] as const) expect(totals(id)).toEqual([['INR', 'posted', 15, 9580000n, 8666590n, 913410n], ['INR', 'pending', 1, 0n, 129900n, -129900n]])
    expect(totals('i01', 'candidates')).toEqual(totals('i01'))
    expect(totals('i02', 'candidates')).toEqual([])
    expect(totals('i03', 'candidates')).toEqual([['INR', 'posted', 9, 80000n, 6215590n, -6135590n], ['INR', 'pending', 1, 0n, 129900n, -129900n]])
    expect(totals('i04')).toEqual([['INR', 'posted', 3, 0n, 54000n, -54000n]])
    expect(totals('i04', 'candidates')).toEqual([['INR', 'posted', 2, 0n, 36000n, -36000n]])
    expect(totals('i05')).toEqual([['INR', 'posted', 11, 4325000n, 669900n, 3655100n], ['INR', 'pending', 1, 200000n, 0n, 200000n]])
    expect(totals('i07')).toEqual([['INR', 'posted', 10, 4325000n, 439900n, 3885100n], ['INR', 'pending', 1, 200000n, 0n, 200000n]])
  })
  it('does not silently convert mixed currencies or count malformed money as zero', () => {
    expect(totals('i06')).toEqual([['INR', 'posted', 5, 9500000n, 553000n, 8947000n], ['USD', 'posted', 1, 0n, 18000n, -18000n]])
    const preview = previewImport(batch('i06'))
    expect(preview.source.unreadable).toBe(1)
    expect(preview.rows.find(row => row.row.id === 'issue-amount')!.normalized.amount).toBeNull()
    expect(preview.reconciliation.difference).toBeNull()
    expect(totals('i06', 'candidates')).toEqual([])
  })
  it.each([['i01', 18642000n, 0n], ['i02', 18642000n, 0n], ['i03', 18642000n, 0n], ['i04', null, null], ['i05', 7475000n, 10000n], ['i06', null, null], ['i07', 7705000n, -220000n]] as const)('%s reconciles whole source evidence, not incremental candidates', (id, computed, difference) => {
    const actual = previewImport(batch(id)).reconciliation
    expect(actual.computed?.minor ?? null).toBe(computed)
    expect(actual.difference?.minor ?? null).toBe(difference)
  })
  it('separates a batch replay label from row evidence', () => {
    const replay = batch('i02')
    expect(previewImport(replay).replay).toBe(true)
    replay.baseline.receivedFingerprints = []
    expect(previewImport(replay).replay).toBe(false)
    expect(previewImport(replay).counts.present).toBe(16)
    replay.baseline.rows = []
    replay.baseline.receivedFingerprints = [replay.fingerprint]
    expect(previewImport(replay).counts.new).toBe(16)
  })
  it('preserves legitimate repeats and uses stable canonical IDs independently of row order', () => {
    const sample = batch('i04'), before = previewImport(sample)
    expect(before.rows.find(row => row.row.id === 'row-t05-copy')!.canonicalId).toBe('row-t05')
    sample.rows.reverse()
    expect(previewImport(sample).rows.sort((a, b) => a.row.id.localeCompare(b.row.id))).toEqual(before.rows.sort((a, b) => a.row.id.localeCompare(b.row.id)))
    sample.baseline.rows = [structuredClone(sample.rows.find(row => row.id === 'row-t05')!)]
    const overlap = previewImport(sample)
    expect(overlap.counts).toEqual({ new: 0, present: 1, duplicate: 1, overlap: 1, conflict: 0, invalid: 0 })
    expect(overlap.candidates.groups).toEqual([])
  })
  it('preserves both versions of conflicting source identities in a batch and baseline', () => {
    const sample = batch('i04')
    sample.rows.find(row => row.id === 'row-t05-copy')!.original.amount = '181.00'
    const conflict = previewImport(sample)
    expect(conflict.counts.conflict).toBe(2)
    expect(conflict.counts.new).toBe(1)
    expect(conflict.rows.find(row => row.row.id === 'row-t05')!.matches[0]!.original.amount).toBe('181.00')
    const sbi = previewImport(batch('i05')).rows.find(row => row.disposition === 'conflict')!
    expect(sbi.normalized.amount?.minor).toBe(230000n)
    expect(sbi.matches[0]!.original.amount).toBe('2200.00')
  })
  it('rejects repeated incoming row IDs and ambiguous comparison identities', () => {
    const sample = batch('i04')
    sample.rows[2]!.id = sample.rows[0]!.id
    expect(previewImport(sample).counts.invalid).toBe(2)
    const replay = batch('i02'); replay.baseline.rows.push(structuredClone(replay.baseline.rows[0]!))
    expect(previewImport(replay).counts.conflict).toBe(1)
  })
  it.each([
    { amount: '0' }, { amount: '-1' }, { amount: '1.234' }, { amount: '1e2' }, { amount: '9999999999' }, { amount: 'NaN' }, { currency: 'EUR' },
    { bookingDate: '10/11/2026', dateFormat: 'Unspecified' }, { bookingDate: '2026-02-30' }, { valueDate: '2026-13-01' }, { bookingDate: '2026-09-30' },
    { transactionId: '' }, { transactionId: '__proto__' }, { account: 'sbi' }, { owner: 'someone-else' }, { provider: 'sbi-statement-example' },
    { currency: 'USD' }, { direction: 'sideways' }, { status: 'failed' }, { kind: 'security-event' }, { description: ' ' }, { reference: '' }, { narration: 'x'.repeat(501) },
  ] satisfies Partial<OriginalRow>[])('retains invalid original evidence without guessing or repairing %j', override => {
    const sample = batch('i01'), row = structuredClone(sample.rows[0]!)
    Object.assign(row.original, override)
    expect(normalizeImportRow(row, sample).issues.length).toBeGreaterThan(0)
    expect(row.original).toMatchObject(override)
  })
  it('normalizes only explicit valid dates and bounded exact amounts', () => {
    const sample = batch('i01'), row = sample.rows[0]!
    Object.assign(row.original, { bookingDate: '01/10/2026', valueDate: '', dateFormat: 'DD/MM/YYYY', amount: '0.01' })
    expect(normalizeImportRow(row, sample)).toMatchObject({ date: '2026-10-01', valueDate: null, amount: { minor: 1n }, issues: [] })
  })
  it('keeps filters literal, whole-batch results intact, and selections independent of cleared searches', () => {
    const sample = batch('i06'), preview = previewImport(sample)
    expect(selectImportRows(preview.rows, { ...initialImportFilters, query: '<img src=x onerror=alert(1)>' }).map(row => row.row.id)).toEqual(['issue-kind'])
    expect(selectImportRows(preview.rows, { ...initialImportFilters, account: 'sbi' }).map(row => row.row.id)).toEqual(['issue-owner'])
    expect(selectImportRows(preview.rows, { ...initialImportFilters, disposition: 'new' })).toEqual([])
    expect(previewImport(sample)).toEqual(preview)
    const controls = { query: 'sample', account: 'all' as const, batches: { i06: { filters: { ...initialImportFilters, query: 'secret' }, selected: 'issue-kind' } } }
    expect(clearImportSearch(controls).batches.i06).toEqual({ filters: initialImportFilters, selected: 'issue-kind' })
    expect(clearImportSelection(controls).batches.i06).toEqual({ filters: controls.batches.i06.filters, selected: null })
    for (const value of ['__proto__', 'constructor', '../i01', 'i08', 'I01']) { expect(isImportId(value)).toBe(false); expect(isDisposition(value)).toBe(false) }
  })
  it.each([false, true])('leaves financial sources and separate review domains unchanged, partial=%s', partial => {
    const records = getBankTransactions(partial, null), review = createTransferState(), budgets = createBudgetState(), recurring = createRecurringState()
    const snapshot = () => ({ holdings: getHoldings(partial), assets: getSummary(getPositions(partial)), banks: getBankSnapshots(partial, null).map(source => bankReconciliation(source, records)), budget: budgetOverview(budgets, records, review, partial), cash: cashFlow(records, review, '2026-10-01', '2026-10-20'), recurring: recurringOverview(records, review, recurring, '2026-10', bankCoverage(partial)), review, budgets })
    const initial = snapshot(), before = financialSnapshot(initial), samples = getImportBatches(), original = structuredClone(samples)
    expect(initial.assets.total.minor).toBe(partial ? 466108000n : 508608000n); expect(initial.banks).toHaveLength(6)
    let importState = createImportReviewState()
    for (const sample of samples) {
      importState = changeImportReview(importState, sample, proposeImport(sample, importState, { type: 'suggestions' }))
      importState = changeImportReview(importState, sample, proposeImport(sample, importState, { type: 'complete' }))
      importState = changeImportReview(importState, sample, proposeImport(sample, importState, { type: 'reopen' }))
      importState = changeImportReview(importState, sample, proposeImport(sample, importState, { type: 'row', rowId: sample.rows[0]!.id, choice: 'exclude' }))
    }
    undoImportReview(importState); resetImportReviews(importState)
    expect(samples).toEqual(original); expect(financialSnapshot(snapshot())).toBe(before)
    const connection = changeConnections(createConnectionState(), { type: 'scenario', id: 'ind-in', scenario: 'revoked' })
    changeConnections(connection, { type: 'reset' })
    expect(getImportBatches()).toEqual(original)
    samples[0]!.rows[0]!.original.amount = '1'
    expect(getImportBatches()).toEqual(original)
  })
})
