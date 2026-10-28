import { expect, it } from 'vitest'
import {
  cashChoicePage, cashResolution, cashScope, cashSelection, cashSelectionHistory, cashSnapshot, cashSnapshotHistory,
  emptyCashChoices, latestCashHistory, MAX_CASH_PAGES, observeSelection, observeSnapshot, pinnedCashHistory,
} from '../../workspace/src/bank-cash-evidence'
import type { HistoryRead } from '../../workspace/src/bank-cash-evidence'
import type { BankAccount } from '../../workspace/src/banking-evidence'
import { cashChoiceFixture as choice, cashSnapshotFixture as snapshot, cancelledCashFixture as cancellation, cashTestBank as bank, cashTestId as id } from './bank-cash-fixtures'

const scope = cashScope(bank, 'INR')
const knownChoice = (revision = 2, changes: Record<string, unknown> = {}) => cashSelection(choice(revision, changes), bank, 'INR')
const knownSnapshot = (revision = 3, changes: Record<string, unknown> = {}) => cashSnapshot(snapshot(revision, changes), scope)
const money = (source: unknown = '12345.60', currency: unknown = 'INR', missing_reason: unknown = null) => ({ role: 'net_cash', source, currency, missing_reason })
const selectionPage = (items: unknown[] = [choice()], next_after: string | null = null) => ({ items, next_after })
const historyPage = <T,>(items: T[], next_before: number | null = null) => ({ items, next_before })
function choiceRows(first = 3, current = true, count = Math.min(first, 25)) {
  return Array.from({ length: count }, (_, index) => choice(first - index, { is_current: index === 0 && current }))
}
function snapshotRows(first = 3, current = true, count = Math.min(first, 25)) {
  return Array.from({ length: count }, (_, index) => snapshot(first - index, { is_current: index === 0 && current }))
}
const selected = (changes: Record<string, unknown> = {}) => ({ selection: choice(), state: 'selected', snapshot: snapshot(), ...changes })

it('requires an explicit declared native currency and revalidates the bank context', () => {
  expect(cashScope(bank, 'USD').currency).toBe('USD')
  expect(cashScope({ ...bank, institution: 'sbi', currencies: ['USD'] }, 'USD').account.institution).toBe('sbi')
  for (const currency of [undefined, null, '', 'EUR', 1, true]) expect(() => cashScope(bank, currency)).toThrow()
  expect(() => cashScope({ ...bank, currencies: ['INR'] }, 'USD')).toThrow()
  expect(() => cashScope({ ...bank, kind: 'brokerage' } as unknown as BankAccount, 'INR')).toThrow()
})

it('validates both declared cash currencies before choosing a native scope', () => {
  const usd = choice(1, { id: id(21), currency: 'USD', snapshot_id: id(31), snapshot_revision: 1 })
  const result = cashChoicePage(selectionPage([choice(), usd]), bank)
  expect(result.items).toEqual([choice(), usd])
  expect(result.progress).toEqual({ pages: 1, ids: [id(20), id(21)], currencies: ['INR', 'USD'] })
  expect(result.items.filter(item => item.currency === 'INR')).toHaveLength(1)
  expect(emptyCashChoices).toEqual({ pages: 0, ids: [], currencies: [] })
  expect(() => cashSelection(usd, bank, 'INR')).toThrow()
})

it('distinguishes no saved choice from an explicit retained clear', () => {
  expect(cashChoicePage(selectionPage([]), bank).items).toEqual([])
  const clear = choice(3, { snapshot_id: null, snapshot_revision: null, reason: 'clear' })
  expect(cashChoicePage(selectionPage([clear]), bank).items[0]).toEqual(clear)
  expect(cashResolution({ selection: clear, state: 'unselected', snapshot: null }, scope, knownChoice()).selection.reason).toBe('clear')
})

it.each([
  { id: '00000000-0000-0000-0000-000000000000' },
  { id: 'bad' }, { id: `${id(20)}\n` }, { snapshot_id: `${id(30)}\n` }, { revision: 0 }, { revision: true }, { revision: 1.2 }, { revision: '2' },
  { revision: Number.MAX_SAFE_INTEGER + 1 }, { is_current: 'true' }, { account_id: id(99) },
  { position_id: id(9), currency: null }, { position_id: id(9) }, { currency: 'EUR' }, { currency: null },
  { snapshot_id: null }, { snapshot_revision: null }, { snapshot_revision: 0 }, { snapshot_revision: true },
  { snapshot_id: id(30), snapshot_revision: 3, reason: 'clear' }, { reason: 'automatic' }, { extra: 'private' },
])('rejects malformed or incompatible saved choice %#', change => {
  expect(() => cashSelection(choice(2, change), bank)).toThrow()
})
it('rejects an initial clear and missing required selection fields', () => {
  expect(() => cashSelection(choice(1, { snapshot_id: null, snapshot_revision: null, reason: 'clear' }), bank)).toThrow()
  const { reason: _reason, ...withoutReason } = choice()
  expect(() => cashSelection(withoutReason, bank)).toThrow()
  expect(() => cashSelection(choice(2, { currency: 'USD' }), { ...bank, currencies: ['INR'] })).toThrow()
})
it.each([
  { items: [choice(), choice()], next_after: null },
  { items: [choice(), choice(3, { id: id(21) })], next_after: null },
  { items: [choice(2, { id: id(21), currency: 'USD' }), choice()], next_after: null },
  { items: [choice(2, { is_current: false })], next_after: null },
  { items: [choice()], next_after: id(20) },
  { items: [], next_after: id(20) },
  { items: Array.from({ length: 26 }, () => choice()), next_after: null },
  { items: [choice()], next_after: null, private: true },
  { items: 'not an array', next_after: null },
])('rejects contradictory discovery pages before exposing a first match %#', value => expect(() => cashChoicePage(value, bank)).toThrow())
it.each([
  { position_id: id(8) }, { currency: 'EUR' }, { snapshot_revision: 0 }, { is_current: false }, { account_id: id(99) },
])('rejects a malformed nonmatching discovery row %#', change => {
  const usd = choice(1, { id: id(21), currency: 'USD', ...change })
  expect(() => cashChoicePage(selectionPage([choice(), usd]), bank)).toThrow()
})
it('keeps discovery cursor and retained-scope bounds strict', () => {
  expect(() => cashChoicePage(selectionPage(), bank, id(20))).toThrow()
  expect(() => cashChoicePage(selectionPage(), bank, null, { pages: 1, ids: [], currencies: [] })).toThrow()
  expect(() => cashChoicePage(selectionPage([]), bank, id(20), { pages: MAX_CASH_PAGES, ids: [id(20)], currencies: ['INR'] })).toThrow()
  expect(() => cashChoicePage(selectionPage([choice(2, { id: id(21) })]), bank, id(20), { pages: 1, ids: [id(20)], currencies: ['INR'] })).toThrow()
  expect(() => cashChoicePage(selectionPage(), bank, 'bad')).toThrow()
})

it.each(['native_cash', 'full_account', null])('retains legal cash scope %s without a completeness inference', snapshot_scope => {
  const item = snapshot(3, { snapshot_scope })
  expect(cashSnapshot(item, scope)).toEqual(item)
  expect(cashResolution(selected({ snapshot: item }), scope, knownChoice()).snapshot).toEqual(item)
})
it.each(['0', '0.00', '-0', '-0.00', '-125.40', '900000000000000001.20'])('preserves exact signed cash spelling %s', source => {
  const item = cashSnapshot(snapshot(3, { components: [money(source)] }), scope)
  expect(item.components[0]!.source).toBe(source)
})
it('retains original source-local time and date-only precision independently', () => {
  expect(knownSnapshot().as_of_instant).toBe('2026-10-20T23:45:16.123456+05:30')
  expect(knownSnapshot(3, { as_of_instant: null }).as_of_date).toBe('2026-10-20')
  expect(knownSnapshot(3, { as_of_date: '0001-01-01', as_of_instant: null }).as_of_date).toBe('0001-01-01')
  expect(knownSnapshot(3, { as_of_date: '9999-12-31', as_of_instant: null }).as_of_date).toBe('9999-12-31')
  expect(knownSnapshot(3, { as_of_date: '2024-02-29', as_of_instant: '2024-02-29T00:00:00Z' }).as_of_instant).toBe('2024-02-29T00:00:00Z')
})
it.each([undefined, null, 123.4, true, '', '+1', '01', '1e3', '1,000', 'NaN', 'Infinity', '1.001', '1000000000000000000', '1\n'])('rejects unavailable or malformed selected native cash %j', source => expect(() => cashSnapshot(snapshot(3, { components: [{ ...money(), source }] }), scope)).toThrow())
it.each([
  { components: [] }, { components: [money(), money()] }, { components: [money(null, 'INR', 'not_supplied')] },
  { components: [money('1', 'USD')] }, { components: [money('1', 'INR', 'unsupported')] },
  { components: [{ ...money(), role: 'quantity', currency: null }] }, { components: [{ ...money(), extra: 'private' }] },
  { components: [{ ...money(), role: 'fee' }] }, { components: {} }, { as_of_date: null, as_of_instant: null },
  { kind: 'position_snapshot' }, { position_id: id(9) }, { instrument_id: id(9) }, { currency: 'USD' }, { account_id: id(99) },
  { snapshot_scope: 'selected_position' }, { snapshot_scope: 'native_cash', reconciliation_boundary: 'guessed' },
  { snapshot_scope: 'full_account', reconciliation_boundary: 'before_period' }, { snapshot_scope: null, reconciliation_boundary: 'after_period' },
  { period_start: null }, { period_end: '2026-09-30' }, { coverage: 'unknown', period_end: null },
  { cash_date_basis: 'as_of' }, { coverage: 'complete' }, { extra: 'private' },
])('rejects malformed cash snapshot scope/components/provenance %#', change => expect(() => cashSnapshot(snapshot(3, change), scope)).toThrow())
it('preserves supported native boundaries and unknown coverage without inventing periods', () => {
  expect(knownSnapshot(3, { reconciliation_boundary: 'before_period', cash_date_basis: 'value' }).reconciliation_boundary).toBe('before_period')
  expect(knownSnapshot(3, { coverage: 'unknown', period_start: null, period_end: null }).period_start).toBeNull()
  expect(knownSnapshot(3, { coverage: 'complete_activity', cash_date_basis: 'settlement' }).coverage).toBe('complete_activity')
})
it.each(['0000-01-01', '2026-02-29', '2026-13-01', '2026-01-00', '2026-1-01', '2026-10-20T00:00:00Z', '2026-10-20\n'])('rejects invalid calendar date %j', date => expect(() => cashSnapshot(snapshot(3, { as_of_date: date, as_of_instant: null }), scope)).toThrow())
it.each([
  '2026-10-20T24:00:00Z', '2026-10-20T00:60:00Z', '2026-10-20T00:00:60Z', '2026-10-20T00:00:00',
  '2026-10-20T00:00:00-00:00', '2026-10-20T00:00:00+14:01', '2026-10-20T00:00:00+15:00', '2026-10-20T00:00:00+05:60',
  '2026-10-20T00:00:00.1234567Z', '2026-10-19T23:45:16+05:30', '2026-10-20T00:00:00Z\n',
])('rejects invalid or mismatched source instant %j', as_of_instant => expect(() => cashSnapshot(snapshot(3, { as_of_instant }), scope)).toThrow())
it.each([
  { as_of_date: '0001-01-01', as_of_instant: '0001-01-01T00:00:00+14:00' },
  { as_of_date: '9999-12-31', as_of_instant: '9999-12-31T23:59:59-14:00' },
])('rejects UTC range overflow while preserving valid local-date rules %#', change => expect(() => cashSnapshot(snapshot(3, change), scope)).toThrow())
it.each([
  { revision: 0 }, { revision: true }, { revision: '3' }, { revision: 3.5 }, { revision: Number.MAX_SAFE_INTEGER + 1 },
  { source_review_revision: false }, { source_review_revision: 0 }, { is_current: 1 }, { account_state: 'closed' },
  { revision: 1, correction_reason: 'source_correction' }, { correction_reason: null },
  { correction_reason: 'posting_update' }, { status: 'active', correction_reason: 'cancellation' }, { status: 'cancelled' },
  { source_id: 'private-invalid-source' }, { source_id: `${id(10)}\n` }, { id: `${id(30)}\n` }, { observation_id: null }, { source_row_id: '00000000-0000-0000-0000-000000000000' },
])('rejects invalid snapshot identity/revision/status %#', change => expect(() => cashSnapshot(snapshot(3, change), scope)).toThrow())

it('retains cancellation as no components and permits labelled archived historical values', () => {
  const cancelled = cashSnapshot(cancellation(), scope)
  expect(cancelled.components).toEqual([]); expect(cancelled.as_of_date).toBeNull()
  expect(knownSnapshot(3, { account_state: 'archived', is_current: false }).components[0]!.source).toBe('12345.60')
  expect(cashSnapshot(snapshot(3, { account_state: 'archived' }), cashScope({ ...bank, state: 'archived' }, 'INR')).account_state).toBe('archived')
  expect(() => cashSnapshot(cancellation(4, { components: [money('0')] }), scope)).toThrow()
  expect(() => cashSnapshot(cancellation(4, { booking_date: null }), scope)).toThrow()
  expect(() => cashSnapshot(snapshot(), cashScope({ ...bank, state: 'archived' }, 'INR'))).toThrow()
})
it('preserves an optional cancellation as-of date without reinstating a balance or precision', () => {
  const supplied = cancellation(4, { as_of_date: '2026-10-20' })
  const result = cashSnapshot(supplied, scope)
  expect(result).toEqual(supplied)
  expect(result.as_of_date).toBe('2026-10-20')
  expect(result.as_of_instant).toBeNull()
  expect(result.snapshot_scope).toBeNull()
  expect(result.reconciliation_boundary).toBeNull()
  expect(result.components).toEqual([])
})
it('rejects an as-of instant on cancelled snapshot evidence even when the local date matches', () => {
  expect(() => cashSnapshot(cancellation(4, { as_of_date: '2026-10-20', as_of_instant: '2026-10-20T23:45:16.123456+05:30' }), scope)).toThrow()
})
it.each(['native_cash', 'full_account'])('rejects scope %s on cancelled snapshot evidence', snapshot_scope => {
  expect(() => cashSnapshot(cancellation(4, { as_of_date: '2026-10-20', snapshot_scope }), scope)).toThrow()
})
it.each(['before_period', 'after_period'])('rejects boundary %s on cancelled snapshot evidence', reconciliation_boundary => {
  expect(() => cashSnapshot(cancellation(4, { as_of_date: '2026-10-20', reconciliation_boundary }), scope)).toThrow()
})
it('keeps equal-head selection facts immutable while permitting a newer target root', () => {
  const opened = knownChoice(), newer = knownChoice(3, { snapshot_id: id(31), snapshot_revision: 1, reason: 'newer_evidence' })
  expect(observeSelection(opened, newer)).toBe(newer)
  expect(observeSelection(newer, { ...newer, is_current: false })).toBe(newer)
  expect(observeSelection(newer, { ...opened, is_current: false })).toBe(newer)
  for (const change of [{ snapshot_id: id(32) }, { snapshot_revision: 2 }, { reason: 'correction' }, { currency: 'USD' as const }]) {
    expect(() => observeSelection(newer, cashSelection({ ...newer, ...change }, bank))).toThrow()
  }
  expect(() => observeSelection(newer, opened)).toThrow()
  expect(() => observeSelection(newer, { ...newer, id: id(21) })).toThrow()
  expect(opened.snapshot_id).toBe(id(30)); expect(opened.revision).toBe(2)
})
it('separates snapshot roots and keeps immutable equal-head facts apart from lifecycle flags', () => {
  const original = knownSnapshot(10), newer = knownSnapshot(11)
  expect(observeSnapshot(original, newer)).toBe(newer)
  expect(observeSnapshot(newer, { ...newer, is_current: false, account_state: 'archived' })).toBe(newer)
  expect(observeSnapshot(newer, knownSnapshot(3, { is_current: false }))).toBe(newer)
  const other = knownSnapshot(1, { id: id(31) })
  expect(observeSnapshot(undefined, other)).toBe(other)
  expect(() => observeSnapshot(newer, other)).toThrow()
  expect(() => observeSnapshot(newer, original)).toThrow()
  for (const change of [
    { source_id: id(88) }, { observation_id: id(89) }, { batch_id: id(90) }, { source_row_id: id(91) }, { source_review_revision: 2 },
    { booking_date: '2026-10-19' }, { coverage: 'partial_activity' as const }, { components: [money('12345.6')] },
  ]) expect(() => observeSnapshot(newer, cashSnapshot({ ...newer, ...change }, scope))).toThrow()
  expect(original.revision).toBe(10)
})
it('resolves a newer choice without transferring an old snapshot root floor to a new root', () => {
  const opened = knownChoice(), newer = knownChoice(3, { snapshot_id: id(31), snapshot_revision: 1, reason: 'newer_evidence' })
  const fresh = snapshot(1, { id: id(31) })
  const result = cashResolution({ selection: newer, state: 'selected', snapshot: fresh }, scope, opened, newer)
  expect(result.snapshot?.id).toBe(id(31)); expect(result.snapshot?.revision).toBe(1)
  expect(() => cashResolution(selected(), scope, opened, newer)).toThrow()
  expect(() => cashResolution({ selection: { ...newer, reason: 'correction' }, state: 'selected', snapshot: fresh }, scope, opened, newer)).toThrow()
})
it.each(['stale', 'cancelled', 'archived', 'conflicting'] as const)('preserves invalid-choice state %s without a usable snapshot', state => {
  const result = cashResolution({ selection: choice(), state, snapshot: null }, scope, knownChoice())
  expect(result.state).toBe(state); expect(result.snapshot).toBeNull(); expect(result.selection.snapshot_id).toBe(id(30))
})
it('preserves resolver precedence for archived clear and archived stale target', () => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), original = knownChoice()
  const clear = choice(3, { snapshot_id: null, snapshot_revision: null, reason: 'clear' })
  expect(cashResolution({ selection: clear, state: 'unselected', snapshot: null }, archivedScope, original).state).toBe('unselected')
  expect(cashResolution({ selection: choice(), state: 'stale', snapshot: null }, archivedScope, original).state).toBe('stale')
  expect(() => cashResolution(selected({ snapshot: snapshot(3, { account_state: 'archived' }) }), archivedScope, original)).toThrow()
})
it.each([
  { state: 'selected', snapshot: null }, { state: 'stale', snapshot: snapshot() }, { state: 'unselected', snapshot: null },
  { state: 'old', snapshot: null }, { selection: null }, { selection: choice(2, { is_current: false }) },
  { selection: choice(2, { id: id(21) }) }, { snapshot: snapshot(3, { id: id(31) }) }, { snapshot: snapshot(4) },
  { snapshot: snapshot(3, { is_current: false }) }, { snapshot: snapshot(3, { account_state: 'archived' }) }, { snapshot: cancellation(3) },
  { private: 'untrusted' },
])('rejects contradictory or mismatched resolved cash %#', change => expect(() => cashResolution(selected(change), scope, knownChoice())).toThrow())
it('rejects equal-head snapshot value drift within a fresh selected resolution', () => {
  expect(() => cashResolution(selected({ snapshot: snapshot(3, { components: [money('9.00')] }) }), scope, knownChoice(), knownChoice(), knownSnapshot())).toThrow()
})

it('reads latest choice history and preserves a known older immutable origin', () => {
  const opened = knownChoice(), head = knownChoice(3), rows = choiceRows()
  expect(cashSelectionHistory(historyPage(rows), scope, opened, head).items).toEqual(rows)
  expect(opened.revision).toBe(2)
})
it('validates choice history continuation and explicit exhaustion', () => {
  const opened = knownChoice(30), first = cashSelectionHistory(historyPage(choiceRows(30), 6), scope, opened)
  expect(first.next_before).toBe(6)
  const earlier = cashSelectionHistory(historyPage(choiceRows(5, false)), scope, opened, opened, { mode: 'earlier', before: 6 })
  expect(earlier.items.map(item => item.revision)).toEqual([5, 4, 3, 2, 1])
  expect(cashSelectionHistory(historyPage([]), scope, opened, opened, { mode: 'earlier', before: 1 }).items).toEqual([])
})
it.each([
  { items: [], next_before: null },
  { items: choiceRows(2), next_before: null },
  { items: choiceRows(3, false), next_before: null },
  { items: [choice(3), choice(1, { is_current: false })], next_before: null },
  { items: [choice(3), choice(2), choice(1, { is_current: false })], next_before: null },
  { items: choiceRows(3), next_before: 1 },
  { items: choiceRows(30, true, 24), next_before: 7 },
  { items: choiceRows(30, true, 26), next_before: 5 },
  { items: choiceRows(3), next_before: null, extra: true },
])('rejects malformed or regressed latest choice history %#', value => expect(() => cashSelectionHistory(value, scope, knownChoice(), knownChoice(3))).toThrow())
it('rejects equal known head mutation and a malformed unrelated choice-history row', () => {
  const origin = knownChoice(), head = knownChoice(3)
  expect(() => cashSelectionHistory(historyPage([choice(3, { reason: 'newer_evidence' }), ...choiceRows(2, false)]), scope, origin, head)).toThrow()
  expect(() => cashSelectionHistory(historyPage([choice(3), choice(2, { is_current: false }), choice(1, { is_current: false, currency: 'USD' })]), scope, origin, head)).toThrow()
})
it('keeps pinned snapshot history distinct from a latest-head request', () => {
  const pin = { id: id(30), revision: 3 }, head = knownSnapshot(8), origin = knownSnapshot(3, { is_current: false })
  expect(pinnedCashHistory(3)).toEqual({ mode: 'pin', revision: 3, before: 4 })
  const result = cashSnapshotHistory(historyPage(snapshotRows(3, false)), scope, pin, head, pinnedCashHistory(3), origin)
  expect(result.items[0]!.revision).toBe(3); expect(result.items[0]!.components[0]!.source).toBe('12345.60')
  expect(head.revision).toBe(8); expect(origin.revision).toBe(3)
  expect(() => cashSnapshotHistory(historyPage(snapshotRows(3)), scope, pin, head, latestCashHistory, origin)).toThrow()
})
it('can inspect an exact active historical value after the selected root was cancelled', () => {
  const opened = knownChoice(), pin = { id: id(30), revision: 3 }, head = cashSnapshot(cancellation(4), scope)
  expect(cashResolution({ selection: choice(), state: 'stale', snapshot: null }, scope, opened).snapshot).toBeNull()
  const old = cashSnapshotHistory(historyPage(snapshotRows(3, false)), scope, pin, head, pinnedCashHistory(3))
  expect(old.items[0]!.status).toBe('active'); expect(old.items[0]!.components[0]!.source).toBe('12345.60')
})
it('accepts pin reads whose requested first revision is still current', () => {
  expect(cashSnapshotHistory(historyPage(snapshotRows()), scope, { id: id(30), revision: 3 }, undefined, pinnedCashHistory(3)).items[0]!.is_current).toBe(true)
})
it('handles maximum safe pinned revision without increment overflow', () => {
  const version = Number.MAX_SAFE_INTEGER, pin = { id: id(30), revision: version }
  expect(pinnedCashHistory(version)).toEqual({ mode: 'pin', revision: version, before: null })
  const rows = snapshotRows(version, true, 25), next = version - 24
  expect(cashSnapshotHistory(historyPage(rows, next), scope, pin, undefined, pinnedCashHistory(version)).items[0]!.revision).toBe(version)
  for (const value of [0, -1, true, '3', 1.5, version + 1]) expect(() => pinnedCashHistory(value as number)).toThrow()
})
it('retains exact equal-revision provenance but allows changes across snapshot revisions', () => {
  const origin = knownSnapshot(3), head = knownSnapshot(4, { source_id: id(88), observation_id: id(89), batch_id: id(90), source_review_revision: 4, as_of_date: '2026-10-21', as_of_instant: null, components: [money('99.00')] })
  const rows = [head, ...snapshotRows(3, false)]
  expect(cashSnapshotHistory(historyPage(rows), scope, { id: id(30), revision: 3 }, head, latestCashHistory, origin).items[0]).toEqual(head)
  expect(() => cashSnapshotHistory(historyPage([head, snapshot(3, { is_current: false, source_id: id(88) }), ...snapshotRows(2, false)]), scope, { id: id(30), revision: 3 }, head, latestCashHistory, origin)).toThrow()
})
it('excludes mutable lifecycle flags from equal-revision historical equality', () => {
  const origin = knownSnapshot(3), rows = snapshotRows(3, false).map(item => ({ ...item, account_state: 'archived' }))
  const result = cashSnapshotHistory(historyPage(rows), scope, { id: id(30), revision: 3 }, origin, pinnedCashHistory(3), origin)
  expect(result.items[0]!.account_state).toBe('archived'); expect(result.items[0]!.is_current).toBe(false)
  expect(origin.account_state).toBe('active'); expect(origin.is_current).toBe(true)
})
it('validates snapshot older pages without applying the latest-head floor to them', () => {
  const head = knownSnapshot(30), pin = { id: id(30), revision: 30 }
  expect(cashSnapshotHistory(historyPage(snapshotRows(30), 6), scope, pin, head, latestCashHistory, head).next_before).toBe(6)
  const older = cashSnapshotHistory(historyPage(snapshotRows(5, false)), scope, pin, head, { mode: 'earlier', before: 6 }, head)
  expect(older.items.map(item => item.revision)).toEqual([5, 4, 3, 2, 1])
  expect(cashSnapshotHistory(historyPage([]), scope, pin, head, { mode: 'earlier', before: 1 }, head).items).toEqual([])
})
it.each([
  { items: [], next_before: null }, { items: snapshotRows(2, false), next_before: null },
  { items: [snapshot(3, { is_current: false }), snapshot(1, { is_current: false })], next_before: null },
  { items: [snapshot(3, { is_current: false }), snapshot(2), snapshot(1, { is_current: false })], next_before: null },
  { items: snapshotRows(3, false), next_before: 1 },
  { items: [snapshot(3, { is_current: false }), snapshot(2, { is_current: false, id: id(31) }), snapshot(1, { is_current: false })], next_before: null },
  { items: [snapshot(3, { is_current: false }), snapshot(2, { is_current: false }), snapshot(1, { is_current: false, components: [money('1.000')] })], next_before: null },
  { items: snapshotRows(3, false), next_before: null, extra: true },
])('rejects missing pinned evidence or malformed unrelated snapshot rows %#', value => expect(() => cashSnapshotHistory(value, scope, { id: id(30), revision: 3 }, knownSnapshot(8), pinnedCashHistory(3))).toThrow())
it('rejects inconsistent retained anchors even on an exhausted snapshot page', () => {
  const pin = { id: id(30), revision: 3 }, head = knownSnapshot(8), origin = knownSnapshot(3), read: HistoryRead = { mode: 'earlier', before: 1 }
  expect(() => cashSnapshotHistory(historyPage([]), scope, pin, knownSnapshot(8, { id: id(31) }), read, origin)).toThrow()
  expect(() => cashSnapshotHistory(historyPage([]), scope, pin, head, read, knownSnapshot(2))).toThrow()
  expect(() => cashSnapshotHistory(historyPage([]), scope, pin, head, read, knownSnapshot(3, { id: id(31) }))).toThrow()
  expect(() => cashSnapshotHistory(historyPage([]), scope, pin, undefined, read)).toThrow()
})
it('permits newly observed archival but rejects a return to active lifecycle facts', () => {
  const origin = knownSnapshot(3), archived = knownSnapshot(3, { account_state: 'archived' })
  expect(() => observeSnapshot(origin, archived)).not.toThrow()
  expect(() => observeSnapshot(archived, origin)).toThrow()
  const archivedRows = snapshotRows(3).map(item => ({ ...item, account_state: 'archived' }))
  expect(cashSnapshotHistory(historyPage(archivedRows), scope, { id: id(30), revision: 3 }, origin, latestCashHistory, origin).items[0]!.account_state).toBe('archived')
  expect(() => cashSnapshotHistory(historyPage(snapshotRows(3)), scope, { id: id(30), revision: 3 }, archived, latestCashHistory, origin)).toThrow()
  expect(() => cashSnapshotHistory(historyPage([snapshot(3, { account_state: 'archived' }), ...snapshotRows(2, false)]), scope, { id: id(30), revision: 3 }, origin, latestCashHistory, origin)).toThrow()
})
it('accepts fresh archived pin evidence while retaining the original active snapshot anchors', () => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), origin = knownSnapshot(3), head = knownSnapshot(8)
  const openedFacts = JSON.stringify(origin), headFacts = JSON.stringify(head)
  const rows = snapshotRows(3, false).map(item => ({ ...item, account_state: 'archived' }))
  const result = cashSnapshotHistory(historyPage(rows), archivedScope, { id: id(30), revision: 3 }, head, pinnedCashHistory(3), origin)
  expect(result.items).toEqual(rows)
  expect(result.items[0]!.components[0]!.source).toBe('12345.60')
  expect(JSON.stringify(origin)).toBe(openedFacts)
  expect(JSON.stringify(head)).toBe(headFacts)
  expect(origin.account_state).toBe('active')
})
it('preserves the original pin and newest floor through archived latest history and return to pin', () => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), origin = knownSnapshot(3), priorHead = knownSnapshot(8)
  const pin = { id: id(30), revision: 3 }, openedFacts = JSON.stringify(origin)
  const latestRows = snapshotRows(10).map(item => ({ ...item, account_state: 'archived' }))
  const latest = cashSnapshotHistory(historyPage(latestRows), archivedScope, pin, priorHead, latestCashHistory, origin)
  const head = latest.items[0]!
  expect(head.revision).toBe(10)
  const pinnedRows = snapshotRows(3, false).map(item => ({ ...item, account_state: 'archived' }))
  const returned = cashSnapshotHistory(historyPage(pinnedRows), archivedScope, pin, head, pinnedCashHistory(3), origin)
  expect(returned.items[0]!.revision).toBe(3)
  expect(JSON.stringify(origin)).toBe(openedFacts)
  expect(head.revision).toBe(10)
  const regressed = snapshotRows(9).map(item => ({ ...item, account_state: 'archived' }))
  expect(() => cashSnapshotHistory(historyPage(regressed), archivedScope, pin, head, latestCashHistory, origin)).toThrow()
  expect(() => cashSnapshotHistory(historyPage([{ ...latestRows[0]!, source_id: id(88) }, ...latestRows.slice(1)]), archivedScope, pin, head, latestCashHistory, origin)).toThrow()
  expect(() => cashSnapshotHistory(historyPage([{ ...pinnedRows[0]!, components: [money('99.00')] }, ...pinnedRows.slice(1)]), archivedScope, pin, head, pinnedCashHistory(3), origin)).toThrow()
})
it.each(['active', 'archived'] as const)('permits a retained active head with an originally %s pin after archival', account_state => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), head = knownSnapshot(8)
  const origin = knownSnapshot(3, { account_state, is_current: false }), pin = { id: id(30), revision: 3 }
  const pinnedRows = snapshotRows(3, false).map(item => ({ ...item, account_state: 'archived' }))
  const latestRows = snapshotRows(8).map(item => ({ ...item, account_state: 'archived' }))
  expect(cashSnapshotHistory(historyPage(pinnedRows), archivedScope, pin, head, pinnedCashHistory(3), origin).items[0]!.revision).toBe(3)
  expect(cashSnapshotHistory(historyPage(latestRows), archivedScope, pin, head, latestCashHistory, origin).items[0]!.revision).toBe(8)
  expect(cashSnapshotHistory(historyPage([]), archivedScope, pin, head, { mode: 'earlier', before: 1 }, origin)).toEqual({ items: [], next_before: null })
  expect(origin.account_state).toBe(account_state)
  expect(head.account_state).toBe('active')
})
it('permits exhausted archived history with only a retained active head', () => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), head = knownSnapshot(8)
  expect(cashSnapshotHistory(historyPage([]), archivedScope, { id: id(30), revision: 3 }, head, { mode: 'earlier', before: 1 })).toEqual({ items: [], next_before: null })
  expect(head.account_state).toBe('active')
})
it.each(['latest', 'pin', 'earlier'] as const)('still rejects fresh active %s history once archived state is learned', mode => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), origin = knownSnapshot(3), head = knownSnapshot(8)
  const read: HistoryRead = mode === 'latest' ? latestCashHistory : mode === 'pin' ? pinnedCashHistory(3) : { mode: 'earlier', before: 3 }
  const rows = mode === 'latest' ? snapshotRows(8) : mode === 'pin' ? snapshotRows(3, false) : snapshotRows(2, false)
  expect(() => cashSnapshotHistory(historyPage(rows), archivedScope, { id: id(30), revision: 3 }, head, read, origin)).toThrow()
})
it('keeps retained anchor account, native values and provenance strict after archival', () => {
  const archivedScope = cashScope({ ...bank, state: 'archived' }, 'INR'), origin = knownSnapshot(3), head = knownSnapshot(8)
  const pin = { id: id(30), revision: 3 }, rows = snapshotRows(3, false).map(item => ({ ...item, account_state: 'archived' }))
  for (const change of [
    { account_id: id(99) }, { currency: 'USD' as const }, { source_id: 'invalid-source' },
    { components: origin.components.map(item => ({ ...item, source: '1.001' })) },
  ]) {
    expect(() => cashSnapshotHistory(historyPage(rows), archivedScope, pin, head, pinnedCashHistory(3), { ...origin, ...change })).toThrow()
    expect(() => cashSnapshotHistory(historyPage([]), archivedScope, pin, { ...head, ...change }, { mode: 'earlier', before: 1 }, origin)).toThrow()
  }
})
it('requires exact older-page starts, matching pin request, and matching root anchors', () => {
  const pin = { id: id(30), revision: 3 }, head = knownSnapshot(8), page = historyPage(snapshotRows(3, false))
  expect(() => cashSnapshotHistory(page, scope, pin, head, { mode: 'earlier', before: 5 })).toThrow()
  expect(() => cashSnapshotHistory(page, scope, pin, head, pinnedCashHistory(2))).toThrow()
  expect(() => cashSnapshotHistory(page, scope, pin, head, { mode: 'pin', revision: 3, before: 5 })).toThrow()
  expect(() => cashSnapshotHistory(page, scope, pin, knownSnapshot(8, { id: id(31) }), pinnedCashHistory(3))).toThrow()
  expect(() => cashSnapshotHistory(page, scope, pin, head, pinnedCashHistory(3), knownSnapshot(2))).toThrow()
  expect(() => cashSelectionHistory(historyPage(choiceRows()), scope, knownChoice(), knownChoice(3), { mode: 'latest', before: 4 } as unknown as HistoryRead)).toThrow()
})
it('keeps projection errors private for malformed financial payloads', () => {
  const privateValue = '12345.678-private'
  let failure: unknown
  try { cashSnapshot(snapshot(3, { components: [money(privateValue)] }), scope) }
  catch (error) { failure = error }
  expect(failure).toBeInstanceOf(Error)
  expect((failure as Error).message).not.toContain(privateValue)
  expect((failure as Error).message).not.toContain(bank.id)
})
