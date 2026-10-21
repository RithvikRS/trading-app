import { useContext, useLayoutEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowDownLeft, ArrowUpRight, Eye, EyeOff, FileText, ShieldCheck, X } from 'lucide-react'
import { Amount, DisplayContext } from './display'
import { BANK_PERIOD, bankCategories, bankNames, reviewLabels, sampleRefund } from './data/banking'
import type { BankSnapshot, BankTransaction } from './data/banking'
import { recordDate, sourceTimestamp } from './holdingPresentation'
import { FX_DATE } from './data/portfolio'
import { effectiveClassification, transferReviewStatus } from './data/transfers'
import type { TransferAction, TransferState } from './data/transfers'
import { CategoryEditor } from './CategoryCorrection'
import { refundEvidence } from './data/categories'

interface Props { onReviewAction: (action: TransferAction) => void; review: TransferState; id: string; records: BankTransaction[]; snapshots: BankSnapshot[]; loading: boolean; onClose: () => void; onTogglePrivacy: () => void }
export default function TransactionInspector({ onReviewAction, review, id, records, snapshots, loading, onClose, onTogglePrivacy }: Props) {
  const { hidden, currency } = useContext(DisplayContext)
  const dialog = useRef<HTMLDialogElement>(null)
  const item = records.find(record => record.id === id)
  const classification = item && effectiveClassification(item, records, review)
  const refund = item && refundEvidence(item, records, review)
  const snapshot = item && snapshots.find(source => source.accountId === item.accountId)
  useLayoutEffect(() => {
    const element = dialog.current!
    element.showModal()
    document.getElementById('transaction-title')?.focus({ preventScroll: true })
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { element.close(); document.body.style.overflow = previousOverflow }
  }, [])
  function containFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== 'Tab') return
    const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], select:not(:disabled), input:not(:disabled)') ?? []).filter(element => !element.closest('[hidden]'))
    const first = controls?.[0], last = controls?.[controls.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement?.id === 'transaction-title')) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
  return <dialog ref={dialog} className="transaction-inspector" aria-labelledby="transaction-title" onCancel={event => { event.preventDefault(); onClose() }} onKeyDown={containFocus}>
    <div className="inspector-top"><span><FileText size={16} aria-hidden="true" />Transaction details</span><div><button className="icon-button" aria-label={hidden ? 'Show amounts in inspector' : 'Hide amounts in inspector'} aria-pressed={hidden} onClick={onTogglePrivacy}>{hidden ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}</button><button className="icon-button" aria-label="Close transaction details" onClick={onClose}><X size={20} aria-hidden="true" /></button></div></div>
    <div className="inspector-content">
      <span className="eyebrow">Fictional source record</span><h2 id="transaction-title" tabIndex={-1}>{loading ? 'Loading transaction' : item ? item.description : 'Transaction unavailable'}</h2>
      {loading ? <div role="status"><span className="sr-only">Loading sample transaction</span><div className="skeleton chart" /></div> : !item || !snapshot ? <p className="inspector-unavailable">This transaction is not present in the current sample view. Close these details to explore the available activity.</p> : <>
        <p className="inspector-subtitle">{bankNames[item.accountId]} · Savings · {item.status === 'posted' ? 'Posted' : 'Pending'}</p>
        <div className="inspector-amount"><span>{item.direction === 'credit' ? <ArrowDownLeft size={18} aria-hidden="true" /> : <ArrowUpRight size={18} aria-hidden="true" />}{item.direction === 'credit' ? 'Credit' : 'Debit'} · {currency}{currency === item.amount.currency ? ' · Original amount' : ' · Display equivalent'}</span><strong><Amount value={item.amount} /></strong>{currency !== item.amount.currency && <small>Original {item.amount.currency} · <Amount value={item.amount} original /><br />Demo FX {FX_DATE} · Display only, not transaction-date FX</small>}</div>
        {item.status === 'pending' && <p className="inspector-notice warning-text">Pending record. Excluded from posted movements and statement reconciliation.</p>}
        {!snapshot.complete && <p className="inspector-notice warning-text">This account’s activity is stale and incomplete. Its balance snapshot is recorded separately.</p>}
        <section aria-labelledby="transaction-source-title"><h3 id="transaction-source-title">Original source</h3><dl className="inspector-fields"><div><dt>Booking date</dt><dd><time dateTime={item.date}>{recordDate(item.date)}</time></dd></div><div><dt>Value date</dt><dd>{item.valueDate ? <time dateTime={item.valueDate}>{recordDate(item.valueDate)}</time> : 'Not supplied'}</dd></div><div><dt>Counterparty</dt><dd>{item.counterparty}</dd></div><div><dt>Reference</dt><dd>{hidden ? 'Reference hidden' : item.reference}</dd></div><div><dt>Recorded category</dt><dd>{bankCategories[item.sourceCategory]}</dd></div></dl><div className="inspector-narration"><span>Original narration</span><p>{hidden ? 'Narration hidden while amounts are hidden.' : item.narration}</p></div></section>
        <section aria-labelledby="transaction-context-title"><h3 id="transaction-context-title">Record context</h3><dl className="inspector-fields"><div><dt>Effective category</dt><dd>{classification && bankCategories[classification.category]}{refund && ` · ${bankCategories[refund.category]}`}</dd></div><div><dt>Review state</dt><dd>{reviewLabels[transferReviewStatus(item, records, review)]}</dd></div><div><dt>Classification evidence</dt><dd>{refund ? 'Refund role supplied by the source; its spending category follows the linked purchase and its current review.' : classification?.provenance === 'transfer' ? 'Confirmed sample pair. Both source legs are present; the source category is retained separately.' : classification?.provenance === 'incomplete' ? item.sourceCategory === 'refund' ? 'Refund evidence or purchase classification is incomplete. This credit remains unresolved.' : 'A paired source record is unavailable. The whole pair is unresolved until its source coverage is restored or it is unlinked.' : classification?.category === 'unresolved' ? 'No confirmed pair or reviewed category. This movement remains unresolved.' : classification?.provenance === 'manual' ? 'Manual category decision; the original source category is retained.' : classification?.provenance === 'suggestion' ? 'Supplied sample suggestion explicitly accepted.' : 'Category supplied by the fictional source record.'}</dd></div>{item.id === sampleRefund.creditId && <div><dt>Refund evidence</dt><dd>{refund ? `Verified sample refund against Home essentials · ${bankCategories[refund.category]}. The original purchase remains unchanged.` : 'The linked purchase is missing, ineligible, or uncategorized. No verified refund is counted.'}</dd></div>}</dl><p className="inspector-note">Review recorded transfers in the Transfers view. Category corrections are separate from original source fields. Decisions do not move money or modify bank records.</p></section>
        <CategoryEditor item={item} records={records} state={review} onAction={onReviewAction} />
        <section aria-labelledby="transaction-provenance-title"><h3 id="transaction-provenance-title">Source & coverage</h3><dl className="inspector-fields"><div><dt>Source</dt><dd>{item.sourceId}<small>Bundled fictional statement · No live connection</small></dd></div><div><dt>Supplied period</dt><dd>{recordDate(BANK_PERIOD.from)}–{recordDate(BANK_PERIOD.to)}<small>Through 20 Oct 2026, 10:00 IST{!snapshot.complete && ' · Incomplete'}</small></dd></div><div><dt>Activity snapshot</dt><dd>{sourceTimestamp(snapshot.activityDate)}</dd></div><div><dt>Balance snapshot</dt><dd>{sourceTimestamp(snapshot.balanceDate)}</dd></div></dl><p className="inspector-note">Booking and value dates have no assumed execution time. Activity coverage and balance freshness are independent.</p></section>
      </>}
      <p className="inspector-footer"><ShieldCheck size={14} aria-hidden="true" />Local sample · No financial data is saved</p>
    </div>
  </dialog>
}
