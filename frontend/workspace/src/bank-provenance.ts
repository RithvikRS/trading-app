import { activityCoveragePage, eventEvidence } from './activity-evidence'
import type { EventEvidence, EventIdentity } from './activity-evidence'
import { bankAccount, bankEvent } from './banking-evidence'
import type { BankAccount } from './banking-evidence'
import { receiptContext } from './receipt-evidence'
import type { ReceiptContext } from './receipt-evidence'
import type { Page, SourceObservation } from './investments'

function invalid(): never { throw new Error('Invalid saved bank source evidence') }
export const MAX_SOURCE_PAGES = 100
export const bankCoverageLabels = { snapshot: 'Snapshot evidence only', partial_activity: 'Partial activity reported', complete_activity: 'Source claims complete activity', unknown: 'Coverage unknown' } as const
export type BankOrigin = ReceiptContext & Pick<EventEvidence, 'source_id' | 'observation_id' | 'period_start' | 'period_end' | 'cash_date_basis' | 'status' | 'posting_state'> & { native_currency: 'INR' | 'USD' | null }
export type BankProvenance = { account: BankAccount; origin: BankOrigin; back: { kind: 'activity' } | { kind: 'history'; root: EventIdentity; highestSeenRevision: number } }
export function bankProvenance(selected: BankAccount, value: EventEvidence, historyRoot?: EventIdentity, highestSeenRevision?: number): BankProvenance {
  const account = bankAccount(selected), item = bankEvent(eventEvidence(value, account.id), account)
  if (historyRoot && (historyRoot.id !== item.id || historyRoot.account_id !== account.id || historyRoot.position_id !== null || historyRoot.instrument_id !== null || historyRoot.kind !== item.kind || !Number.isSafeInteger(historyRoot.revision) || historyRoot.revision < 1)) invalid()
  if (highestSeenRevision !== undefined && (!historyRoot || !Number.isSafeInteger(highestSeenRevision) || highestSeenRevision < historyRoot.revision)) invalid()
  return { account, origin: { ...receiptContext('event', item), source_id: item.source_id, observation_id: item.observation_id, period_start: item.period_start, period_end: item.period_end, cash_date_basis: item.cash_date_basis, status: item.status, posting_state: item.posting_state, native_currency: item.components.find(value => value.role === 'net_cash')?.currency ?? null }, back: historyRoot ? { kind: 'history', root: { ...historyRoot }, highestSeenRevision: Math.max(highestSeenRevision ?? historyRoot.revision, item.revision) } : { kind: 'activity' } }
}
export type SourceProgress = Readonly<{ pages: number; originSeen: boolean }>
export type BankSourcePage = Page<SourceObservation> & { progress: SourceProgress }
export const emptySourceProgress: SourceProgress = Object.freeze({ pages: 0, originSeen: false })
export function bankSourcePage(value: unknown, origin: BankOrigin, after: string | null = null, preceding: SourceProgress = emptySourceProgress): BankSourcePage {
  if (!Number.isSafeInteger(preceding.pages) || preceding.pages < 0 || preceding.pages >= MAX_SOURCE_PAGES || typeof preceding.originSeen !== 'boolean' || (after === null) !== (preceding.pages === 0) || preceding.pages === 0 && preceding.originSeen) invalid()
  const result = activityCoveragePage(value, origin.source_id, after)
  for (const item of result.items) if (item.id === origin.observation_id && (item.coverage !== origin.coverage || item.period_start !== origin.period_start || item.period_end !== origin.period_end)) invalid()
  const progress = { pages: preceding.pages + 1, originSeen: preceding.originSeen || result.items.some(item => item.id === origin.observation_id) }
  if (result.next_after === null && !progress.originSeen) invalid()
  return { ...result, progress }
}
