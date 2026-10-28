import type { BankAccount } from '../../workspace/src/banking-evidence'

export const cashTestId = (value: number) => `8c000000-0000-4000-8000-${String(value).padStart(12, '0')}`
export const cashTestBank: BankAccount = { id: cashTestId(1), kind: 'bank', institution: 'hdfc', market: 'IN', label: 'Everyday account', currencies: ['INR', 'USD'], revision: 1, state: 'active' }
export function cashChoiceFixture(revision = 2, changes: Record<string, unknown> = {}) {
  return { id: cashTestId(20), revision, is_current: true, account_id: cashTestBank.id, position_id: null, currency: 'INR', snapshot_id: cashTestId(30), snapshot_revision: 3, reason: revision === 1 ? 'reviewed' : 'correction', ...changes }
}
export function cashSnapshotFixture(revision = 3, changes: Record<string, unknown> = {}) {
  return {
    id: cashTestId(30), revision, is_current: true, account_id: cashTestBank.id, account_state: 'active', position_id: null, instrument_id: null, currency: 'INR', kind: 'cash_snapshot',
    status: 'active', correction_reason: revision === 1 ? null : 'source_correction', as_of_date: '2026-10-20', as_of_instant: '2026-10-20T23:45:16.123456+05:30',
    snapshot_scope: 'native_cash', reconciliation_boundary: null, booking_date: '2026-10-20', source_row_id: cashTestId(1000 + revision % 1000), source_review_revision: 1, source_id: cashTestId(10), observation_id: cashTestId(11), batch_id: cashTestId(12),
    coverage: 'snapshot', period_start: '2026-10-01', period_end: '2026-10-20', cash_date_basis: null, components: [{ role: 'net_cash', source: '12345.60', currency: 'INR', missing_reason: null }], ...changes,
  }
}
export function cancelledCashFixture(revision = 4, changes: Record<string, unknown> = {}) {
  return cashSnapshotFixture(revision, { status: 'cancelled', correction_reason: 'cancellation', as_of_date: null, as_of_instant: null, snapshot_scope: null, booking_date: '2026-10-21', components: [], ...changes })
}
