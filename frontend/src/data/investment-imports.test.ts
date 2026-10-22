import { describe, expect, it } from 'vitest'
import { getInvestmentBatches, investmentDecimal, investmentIdentity, isInvestmentImportId, normalizeInvestment, previewInvestment } from './investment-imports'
import type { InvestmentImportId, InvestmentRaw } from './investment-imports'
import { changeInvestmentReview, investmentBatchReview, permittedInvestmentChoices, proposeInvestment, reviewInvestment } from './investment-review'
import type { InvestmentOperation } from './investment-review'
import { changeImportReview, createImportReviewState, proposeImport, resetImportReviews, undoImportReview } from './import-review'
import type { ImportReviewState } from './import-review'
import { getImportBatches } from './imports'
const batch = (id: InvestmentImportId = 'i08') => getInvestmentBatches().find(value => value.id === id)!
const apply = (id: InvestmentImportId, state: ImportReviewState, action: InvestmentOperation) => { const source = batch(id); return changeInvestmentReview(state, source, proposeInvestment(source, state, action)) }
const suggested = (id: InvestmentImportId) => apply(id, createImportReviewState(), { type: 'suggestions' })

describe('Typed investment import evidence and decisions', () => {
  it.each([
    ['i08', [4, 0, 1, 0], true, 4], ['i09', [5, 0, 0, 0], true, 5], ['i10', [0, 0, 0, 1], false, 1],
    ['i11', [1, 0, 0, 0], true, 2], ['i12', [5, 0, 0, 0], false, 4], ['i13', [0, 0, 0, 7], false, 4], ['i14', [3, 0, 0, 0], true, 4],
  ] as const)('%s has independently expected choices and scope checks', (id, counts, ready, checks) => {
    const review = reviewInvestment(batch(id), suggested(id))
    expect(Object.values(review.counts)).toEqual(counts); expect(review.ready).toBe(ready); expect(review.sourceChecks).toHaveLength(checks)
    expect(Object.values(review.counts).reduce((a, b) => a + b, 0)).toBe(batch(id).rows.length)
    if (ready) expect(review.selectedChecks.every(check => check.passed)).toBe(true)
  })
  it('keeps Indian values, US fractions and cash snapshots separate without duplicate cash', () => {
    const india = reviewInvestment(batch('i08'), suggested('i08')), us = reviewInvestment(batch('i09'), suggested('i09'))
    expect(india.groups.map(group => [group.label, group.value.minor])).toEqual([['Marked position values', 96865000n], ['Cash snapshots', 1850000n]])
    expect(us.groups.map(group => [group.label, group.value.minor])).toEqual([['Marked position values', 1520000n], ['Cash snapshots', 12000n]])
    expect(us.sourceChecks.filter(check => check.kind === 'units').map(check => check.actual)).toEqual([2000000000n, 825000000n, 970000000n, 400000000n])
    expect(india.selected.filter(row => row.original.kind === 'cash')).toHaveLength(1)
    expect(india.rows.find(row => row.row.id === 'cash-ind-in-copy')?.canonicalId).toBe('cash-ind-in')
  })
  it.each(['incoming', 'existing'] as const)('retains one identical fund position when preferring %s', choice => {
    const source = batch('i10'), preview = previewInvestment(source)[0]!
    expect(preview.disposition).toBe('overlap')
    const state = apply('i10', createImportReviewState(), { type: 'row', rowId: 'position-h11', choice }), review = reviewInvestment(source, state)
    expect(review.ready).toBe(true); expect(review.selected).toHaveLength(1); expect(review.newIdentities).toBe(0)
    expect(review.selected[0]!.original.source).toBe(choice === 'incoming' ? 'indmoney-example' : 'consolidated-example')
    expect(review.groups[0]!.value.minor).toBe(31000000n); expect(review.selectedChecks[0]!.actual).toBe(200000000000n)
    expect(investmentBatchReview(state, 'i10').decisions['position-h11']!.matches).toHaveLength(1)
    expect(batch('i10')).toEqual(source)
  })
  it('keeps regular/direct plans, folios, and same-security accounts distinct with unknown valuation', () => {
    const funds = reviewInvestment(batch('i11'), suggested('i11'))
    expect(funds.selected).toHaveLength(2); expect(funds.groups[0]!.missing).toBe(1); expect(funds.groups[0]!.value.minor).toBe(31000000n)
    expect(new Set(funds.selected.map(investmentIdentity)).size).toBe(2)
    const employee = reviewInvestment(batch('i12'), suggested('i12'))
    expect(employee.selected.filter(row => row.original.kind === 'position').map(row => row.original.account).sort()).toEqual(['ind-us', 'ubs'])
    expect(employee.rows[0]!.disposition).toBe('new')
  })
  it('preserves lot purchase amounts, missing fee/basis and independent dividend components', () => {
    const review = reviewInvestment(batch('i12'), suggested('i12')), group = (label: string) => review.groups.find(item => item.label === label)!
    expect(review.sourceChecks.find(check => check.label.includes('Remaining lots'))).toMatchObject({ actual: 2400000000n, expected: 2400000000n, passed: true })
    expect(group('Source lot purchase amounts').value.minor).toBe(629920n)
    expect(group('Lot fees')).toMatchObject({ missing: 1, value: { minor: 125n } })
    expect(group('Supplied tax basis').missing).toBe(3)
    expect(group('Gross cash dividends').value.minor).toBe(3096n); expect(group('Dividend withholding').value.minor).toBe(774n); expect(group('Net cash dividends').value.minor).toBe(2322n)
    expect(review.blockers.join(' ')).toMatch(/tax basis/)
    expect(review.ready).toBe(false)
  })
  it('checks activity units and native cash separately from marked value and cash snapshot', () => {
    const review = reviewInvestment(batch('i14'), suggested('i14'))
    expect(review.sourceChecks.map(check => [check.actual, check.expected, check.passed])).toEqual([[400000000n, 400000000n, true], [400000000n, 400000000n, true], [12000n, 12000n, true], [12000n, 12000n, true]])
    expect(review.groups.map(group => [group.label, group.value.minor])).toEqual([['Marked position values', 120000n], ['Purchase cash outflow', 112000n], ['Activity fees', 0n], ['Cash snapshots', 12000n]])
    const source = batch('i14'); source.positions[0]!.opening = null; source.cash[0]!.opening = null
    expect(reviewInvestment(source, createImportReviewState()).sourceChecks.filter(check => check.actual === null)).toHaveLength(2)
  })
  it('does not allow snapshot source preference to override units or quote differences', () => {
    for (const field of ['units', 'quote'] as const) {
      const source = batch('i10'); source.rows[0]!.original[field] = '2100'
      const row = previewInvestment(source)[0]!
      expect(row.disposition).toBe('conflict'); expect(permittedInvestmentChoices(row)).toEqual(['exclude'])
      const initial = createImportReviewState(), changed = changeInvestmentReview(initial, source, proposeInvestment(source, initial, { type: 'row', rowId: row.row.id, choice: 'incoming' }))
      expect(changed.history).toHaveLength(0); expect(changed.investments).toBe(initial.investments)
    }
  })
  it.each([
    { owner: 'other' }, { account: 'ubs' }, { instrument: 'UNKNOWN' }, { plan: 'Regular' }, { option: 'Distribution' }, { form: 'demat' }, { folio: '' }, { scheme: 'another-scheme' }, { source: 'unknown' }, { recordId: '../x' },
    { units: '2000.000000001' }, { units: '-1' }, { units: '1e3' }, { units: '1,000' }, { quote: '155.0000001' }, { currency: 'USD' }, { snapshotAt: '2026-02-30T03:30:00Z' }, { quoteAt: '2026-10-32T03:30:00Z' }, { kind: 'corporate-action' }, { amount: '310000' },
  ] satisfies Partial<InvestmentRaw>[])('rejects incompatible or malformed position evidence %j', fields => {
    const source = batch('i10'), row = source.rows[0]!
    Object.assign(row.original, fields); expect(normalizeInvestment(row, source).issues.length).toBeGreaterThan(0)
    expect(previewInvestment(source)[0]!.disposition).toBe('invalid')
  })
  it('uses exact eight/six/two-place scales and never rounds unsupported input', () => {
    expect(investmentDecimal('0.00000001', 8)).toBe(1n); expect(investmentDecimal('0.000000001', 8)).toBeNull()
    expect(investmentDecimal('1.001', 2)).toBeNull()
    const source = batch(), row = source.rows[0]!
    Object.assign(row.original, { units: '0.00000001', quote: '500000', quoteAt: '2026-10-20T12:30:00Z' })
    expect(normalizeInvestment(row, source).value?.minor).toBe(1n)
  })
  it('requires opening/activity units for every source account, not only the catalog account', () => {
    const source = batch('i14'); source.account = 'ubs'; source.accounts.push('ubs'); source.positions[0]!.opening = null
    const state = createImportReviewState(), selected = changeInvestmentReview(state, source, proposeInvestment(source, state, { type: 'suggestions' }))
    const review = reviewInvestment(source, selected)
    expect(review.sourceChecks.find(check => check.label.includes('Opening + activity'))).toMatchObject({ actual: null, passed: false })
    expect(review.ready).toBe(false)
  })
  it('blocks unbounded marked values and missing cash or comparison checkpoints', () => {
    const source = batch(), row = source.rows[0]!
    Object.assign(row.original, { units: '999999999', quote: '999999999' })
    expect(normalizeInvestment(row, source).value).toBeNull()
    expect(normalizeInvestment(row, source).issues.length).toBeGreaterThan(0)
    const history = batch('i14'); history.cash = []; history.rows = history.rows.filter(row => row.original.kind !== 'cash')
    const state = createImportReviewState(), selected = changeInvestmentReview(state, history, proposeInvestment(history, state, { type: 'suggestions' }))
    expect(reviewInvestment(history, selected).blockers.join(' ')).toMatch(/Cash activity lacks/)
    expect(reviewInvestment(history, selected).ready).toBe(false)
    const fund = batch('i11'); fund.positions = fund.positions.filter(checkpoint => checkpoint.holdingId !== 'h11')
    expect(reviewInvestment(fund, state).blockers.join(' ')).toMatch(/independent position or cash checkpoint/)
  })
  it('rejects inconsistent cash components, reused incoming IDs, and ambiguous baseline versions', () => {
    const employee = batch('i12'), dividend = employee.rows.find(row => row.id === 'cash-dividend')!
    dividend.original.net = '30.96'; expect(normalizeInvestment(dividend, employee).issues.join(' ')).toMatch(/Dividend/)
    const india = batch(); india.rows[4]!.id = india.rows[3]!.id
    expect(previewInvestment(india).filter(row => row.disposition === 'invalid')).toHaveLength(2)
    const fund = batch('i10'); fund.baseline.rows.push(structuredClone(fund.baseline.rows[0]!))
    expect(previewInvestment(fund)[0]!.disposition).toBe('conflict')
  })
  it.each(['i12', 'i13'] as const)('exclusions never complete missing or conflicting %s evidence', id => {
    let state = createImportReviewState()
    for (const row of batch(id).rows) state = apply(id, state, { type: 'row', rowId: row.id, choice: 'exclude' })
    expect(reviewInvestment(batch(id), state).counts.unresolved).toBe(0); expect(reviewInvestment(batch(id), state).ready).toBe(false)
    expect(apply(id, state, { type: 'complete' }).history).toBe(state.history)
  })
  it('cannot omit a cash snapshot, selected position, activity, or the canonical duplicate', () => {
    for (const [id, rowId] of [['i08', 'cash-ind-in'], ['i09', 'position-h07'], ['i14', 'activity-purchase']] as const) {
      const state = apply(id, suggested(id), { type: 'row', rowId, choice: 'exclude' })
      expect(reviewInvestment(batch(id), state).ready).toBe(false)
    }
    const source = batch('i09'); source.positions.pop()
    expect(reviewInvestment(source, createImportReviewState()).blockers.join(' ')).toMatch(/independent position or cash checkpoint/)
  })
  it.each(['source', 'baseline', 'revision', 'mapping', 'missing row', 'checkpoint'] as const)('rejects stale %s actions and retains incompatible choices', change => {
    const source = batch(), state = suggested('i08'), proposal = proposeInvestment(source, state, { type: 'complete' })
    if (change === 'source') source.rows[0]!.original.units = '151'
    if (change === 'baseline') source.baseline.id = 'changed'
    if (change === 'revision') source.revision = 'r2'
    if (change === 'mapping') source.accounts = ['ubs']
    if (change === 'missing row') source.rows.pop()
    if (change === 'checkpoint') source.positions[0]!.units = '151'
    const result = changeInvestmentReview(state, source, proposal)
    expect(result.investments).toBe(state.investments); expect(result.history).toBe(state.history); expect(result.message).toMatch(/changed/)
    expect(reviewInvestment(source, state).rows.every(row => row.status === 'Needs review · Evidence changed')).toBe(true)
  })
  it('binds operation, prior choices, scope, and shared serial; failed changes are atomic', () => {
    const source = batch(), state = suggested('i08'), proposal = proposeInvestment(source, state, { type: 'row', rowId: 'position-h01', choice: 'exclude' })
    const tampered = { ...proposal, operation: { ...proposal.operation, type: 'row' as const, rowId: 'cash-ind-in', choice: 'exclude' as const } }
    expect(changeInvestmentReview(state, source, tampered).history).toBe(state.history)
    const changed = apply('i08', state, { type: 'row', rowId: 'position-h01', choice: 'restore' })
    expect(changeInvestmentReview(undoImportReview(changed), source, proposal).message).toMatch(/changed/)
    expect(changeInvestmentReview(resetImportReviews(state), source, proposal).message).toMatch(/changed/)
    expect(changeInvestmentReview(state, batch('i09'), proposal).message).toMatch(/changed/)
  })
  it('completes idempotently, reopens before editing, and preserves source versions', () => {
    const source = batch('i10'), original = structuredClone(source)
    let state = apply('i10', createImportReviewState(), { type: 'row', rowId: 'position-h11', choice: 'existing' })
    const completion = proposeInvestment(source, state, { type: 'complete' }); state = changeInvestmentReview(state, source, completion)
    expect(changeInvestmentReview(state, source, completion)).toBe(state); expect(apply('i10', state, { type: 'complete' })).toBe(state)
    expect(apply('i10', state, { type: 'row', rowId: 'position-h11', choice: 'incoming' }).history).toBe(state.history)
    state = apply('i10', state, { type: 'reopen' }); expect(reviewInvestment(source, state).receipt).toBeNull()
    state = apply('i10', state, { type: 'row', rowId: 'position-h11', choice: 'incoming' })
    expect(investmentBatchReview(state, 'i10').decisions['position-h11']!.previous).toBe('existing')
    expect(source).toEqual(original)
  })
  it('shares bank/investment undo/reset without losing either branch of decisions', () => {
    const bank = getImportBatches()[0]!, initial = createImportReviewState()
    const bankState = changeImportReview(initial, bank, proposeImport(bank, initial, { type: 'suggestions' }))
    const both = apply('i09', bankState, { type: 'suggestions' })
    expect(both.batches).toBe(bankState.batches); expect(undoImportReview(both).investments).toEqual({})
    const bankAgain = changeImportReview(both, bank, proposeImport(bank, both, { type: 'complete' }))
    expect(bankAgain.investments).toBe(both.investments); expect(undoImportReview(bankAgain).batches).toBe(both.batches)
    expect(resetImportReviews(bankAgain)).toMatchObject({ batches: {}, investments: {}, history: [] })
  })
  it('preserves choices through set-aside/reopen, rejects hidden actions, and invalidates stale receipts', () => {
    const source = batch(), state = suggested('i08'), aside = apply('i08', state, { type: 'aside' })
    expect(reviewInvestment(source, aside).ready).toBe(false)
    expect(reviewInvestment(source, apply('i08', aside, { type: 'reopen' })).ready).toBe(true)
    expect(changeInvestmentReview(state, source, proposeInvestment(source, state, { type: 'complete' }), false).history).toBe(state.history)
    const done = apply('i08', state, { type: 'complete' }); source.revision = 'r2'
    expect(reviewInvestment(source, done).receipt).toBeNull(); expect(reviewInvestment(source, done).ready).toBe(false)
  })
  it('allowlists batch IDs and makes fixtures independent copies', () => {
    for (const id of ['i15', '../i08', '__proto__', 'i08/position-h01', 'I08']) expect(isInvestmentImportId(id)).toBe(false)
    const original = getInvestmentBatches(), edited = getInvestmentBatches(); edited[0]!.rows[0]!.original.amount = '1'
    expect(getInvestmentBatches()).toEqual(original)
  })
})
