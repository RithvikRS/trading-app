import { useContext } from 'react'
import { ArrowDownLeft, ArrowRight, ArrowUpRight, Check, CircleHelp, Link2, RotateCcw, ShieldCheck, Unlink, X } from 'lucide-react'
import { Amount, DisplayContext, ReportingAmount } from './display'
import { bankNames } from './data/banking'
import type { BankTransaction } from './data/banking'
import { pairRecords, transferCoverage, transferLabels, transferQueue } from './data/transfers'
import type { TransferAction, TransferControls, TransferPair, TransferState, TransferStatus } from './data/transfers'
import { recordDate } from './holdingPresentation'

export interface TransferReviewProps {
  records: BankTransaction[]; state: TransferState; controls: TransferControls; visibleIds: Set<string>; incomplete?: boolean
  onControls: (controls: TransferControls) => void; onAction: (action: TransferAction) => void; onOpen: (id: string) => void
}
export default function TransferReview({ records, state, controls, visibleIds, incomplete, onControls, onAction, onOpen }: TransferReviewProps) {
  const { hidden, currency } = useContext(DisplayContext)
  const queue = transferQueue(records, state), coverage = transferCoverage(records, state)
  const status = controls.status
  const pairs = status === 'unmatched' ? [] : queue[status]
  function action(value: TransferAction) {
    onAction(value)
    onControls({ ...controls, selected: null })
    document.getElementById('transfer-review-title')?.focus({ preventScroll: true })
  }
  function leg(item: BankTransaction, key: string) {
    return <div className={`transfer-leg ${item.direction}`}>
      <div className="transfer-leg-heading"><span>{item.direction === 'debit' ? <ArrowUpRight size={15} aria-hidden="true" /> : <ArrowDownLeft size={15} aria-hidden="true" />}{item.direction === 'debit' ? 'From' : 'To'} · {bankNames[item.accountId]}</span><time dateTime={item.date}>{recordDate(item.date)}</time></div>
      <strong className="transfer-leg-amount"><ReportingAmount value={item.amount} /></strong><p>{item.description}</p>
      <small>{hidden ? 'Reference hidden' : item.reference}</small>
      {!visibleIds.has(item.id) && <span className="transfer-outside">Outside activity filters</span>}
      <a className="transfer-inspect" id={`transfer-link-${key}-${item.id}`} href={`#/banking/${item.id}`} aria-label={`Inspect ${item.direction} at ${bankNames[item.accountId]}, ${recordDate(item.date)}`} onClick={event => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpen(item.id) }}>Inspect source<ArrowUpRight size={13} aria-hidden="true" /></a>
    </div>
  }
  function pairCard(pair: TransferPair, index: number) {
    const source = pairRecords(pair, records)
    const selected = controls.selected === pair.id
    const sharedReference = source && source.debit.transferReference && source.debit.transferReference === source.credit.transferReference
    const days = source ? Math.abs(Date.parse(`${source.debit.date}T00:00:00Z`) - Date.parse(`${source.credit.date}T00:00:00Z`)) / 86_400_000 : 0
    const occupied = state.pairs.some(other => other.id !== pair.id && [other.debitId, other.creditId].some(id => id === pair.debitId || id === pair.creditId))
    return <article className={`transfer-pair ${selected ? 'selected' : ''}`} key={pair.id} aria-labelledby={`transfer-heading-${pair.id}`}>
      <div className="transfer-pair-heading"><h3 id={`transfer-heading-${pair.id}`}>{status === 'confirmed' ? 'Confirmed transfer' : status === 'dismissed' ? 'Dismissed candidate' : 'Possible transfer'} {index + 1}</h3><span className={`transfer-state ${status === 'ambiguous' ? 'warning-text' : ''}`}>{status === 'confirmed' ? <Check size={13} aria-hidden="true" /> : <CircleHelp size={13} aria-hidden="true" />}{transferLabels[status]}</span></div>
      {source ? <><div className="transfer-legs">{leg(source.debit, pair.id)}<ArrowRight className="transfer-connector" size={19} aria-hidden="true" />{leg(source.credit, pair.id)}</div>
        <div className="transfer-evidence"><ShieldCheck size={15} aria-hidden="true" /><div><strong>{sharedReference ? 'Matching structured source reference' : 'Equal native amounts · Opposite directions'}</strong><p>Two tracked accounts with the same sample owner. {days === 0 ? 'Same booking date' : `${days} calendar day${days === 1 ? '' : 's'} apart`} · Within the three-day demo window.</p>{sharedReference && <p>{hidden ? 'Structured reference hidden.' : source.debit.transferReference} · Supporting evidence, not proof of a transfer.</p>}{status === 'ambiguous' && <p className="warning-text">A record has more than one possible counterpart. Review all alternatives before choosing.</p>}{occupied && <p className="warning-text">A record is already in another confirmed pair. Restoring this candidate will not make it eligible until that pair is unlinked.</p>}</div></div></> : <p className="transfer-missing warning-text">A source record is unavailable or no longer eligible. No complete transfer is counted.</p>}
      <div className="transfer-actions">
        {status === 'confirmed' ? <button className="outlined-button" onClick={() => action({ type: 'unlink', pair })}><Unlink size={14} aria-hidden="true" />Unlink pair</button>
          : status === 'dismissed' ? <button className="outlined-button" onClick={() => action({ type: 'restore', pair })}><RotateCcw size={14} aria-hidden="true" />Restore candidate</button>
            : <><button className="primary-button" aria-expanded={selected} aria-controls={`confirm-${pair.id}`} onClick={() => onControls({ ...controls, selected: selected ? null : pair.id })}><Link2 size={14} aria-hidden="true" />{selected ? 'Cancel review' : 'Review pair'}</button><button className="outlined-button" onClick={() => action({ type: 'dismiss', pair })}><X size={14} aria-hidden="true" />Dismiss candidate</button></>}
      </div>
      {(status === 'suggested' || status === 'ambiguous') && <div className="transfer-confirm" id={`confirm-${pair.id}`} hidden={!selected}><strong>Confirm these two records as one internal transfer?</strong><p>Both entries will be excluded from income/spending classification. Their amounts and bank balances stay unchanged. You can unlink or undo this decision.</p><button className="primary-button" onClick={() => action({ type: 'confirm', pair })}><Check size={15} aria-hidden="true" />Confirm this pair</button></div>}
    </article>
  }
  return <section className="panel transfer-workspace" aria-labelledby="transfer-review-title">
    <div className="transfer-heading"><div><span className="eyebrow">Follow the connection</span><h2 id="transfer-review-title" tabIndex={-1}>Transfer review</h2><p>Link recorded movements between your accounts.</p></div><span className="quiet-badge">Local sample decisions</span></div>
    <div className="transfer-summary" aria-label="Transfer review coverage"><div><span>Confirmed transfers · Counted once</span><strong><Amount value={coverage.transferred} /></strong><small>{coverage.confirmed} {coverage.confirmed === 1 ? 'pair' : 'pairs'} · {currency}</small></div><div><span>Unreviewed outgoing · Posted</span><strong><Amount value={coverage.debits} /></strong><small>Unresolved coverage, not spending</small></div><div><span>Unreviewed incoming · Posted</span><strong><Amount value={coverage.credits} /></strong><small>{coverage.unresolved} unresolved posted records in total</small></div></div>
    <p className="transfer-scope"><ShieldCheck size={15} aria-hidden="true" />Uses all loaded records, independently of activity filters. Review decisions stay in memory until reload. This reviews records; it does not move money.</p>
    {incomplete && <div className="transfer-incomplete"><strong>SBI activity is stale and incomplete.</strong><p>Candidates and coverage use available records only. No missing counterpart or adjustment is invented; bank balance snapshots remain independent.</p></div>}
    {queue.incomplete.length > 0 && <div className="transfer-incomplete" role="alert"><strong>A confirmed pair has incomplete source coverage.</strong><p>Both sides are treated as unresolved. Restore the source records or unlink the pair; the available leg cannot be reused while the pair is retained.</p>{queue.incomplete.map(pair => <button key={pair.id} className="outlined-button" onClick={() => action({ type: 'unlink', pair })}>Unlink incomplete pair</button>)}</div>}
    <div className="transfer-tabs" role="group" aria-label="Transfer review status">{(Object.keys(transferLabels) as TransferStatus[]).map(value => <button key={value} aria-pressed={status === value} onClick={() => onControls({ ...controls, status: value, selected: null })}>{transferLabels[value]}<span>{queue[value].length}</span></button>)}</div>
    <div className="transfer-queue-context"><span role="status" aria-live="polite">{queue[status].length} {status === 'unmatched' ? `unmatched record${queue[status].length === 1 ? '' : 's'}` : `${status} pair${queue[status].length === 1 ? '' : 's'}`}</span><span>No automatic confirmation · Native amounts must match exactly</span></div>
    <div className="transfer-results">
      {status === 'unmatched' ? queue.unmatched.map(item => <article key={item.id} className="transfer-pair transfer-unmatched" aria-label={`Unmatched ${item.direction} at ${bankNames[item.accountId]}`}>{leg(item, 'unmatched')}<div className="transfer-unmatched-note"><CircleHelp size={20} aria-hidden="true" /><h3>No eligible counterpart</h3><p>No available opposite entry meets the amount, currency, ownership, and three-day rules. This record remains unresolved; it is not automatically treated as income or spending.</p></div></article>) : pairs.map(pairCard)}
      {queue[status].length === 0 && <div className="transfer-empty"><Link2 size={30} aria-hidden="true" /><h3>{status === 'suggested' ? queue.ambiguous.length === 0 && (queue.confirmed.length > 0 || queue.dismissed.length > 0) ? 'All available candidate pairs reviewed.' : 'No unique candidates to review.' : status === 'ambiguous' ? 'No competing candidates.' : status === 'unmatched' ? 'No unmatched eligible records.' : status === 'confirmed' ? 'No complete confirmed pairs.' : 'No dismissed candidates.'}</h3><p>{status === 'suggested' ? 'Check Ambiguous and Unmatched for other unresolved movements.' : status === 'confirmed' ? 'A pair appears here only after confirmation and while both source records are available.' : 'Review other statuses or reset the sample decisions to explore again.'}</p></div>}
    </div>
  </section>
}
