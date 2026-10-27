import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, FileCheck2, RefreshCw } from 'lucide-react'
import type { AuthController } from './auth'
import type { Page } from './investments'
import { completedRows, emptyReceiptProgress, receiptPage } from './receipt-evidence'
import type { CompletedPage, ReceiptContext, ReceiptProgress, SavedReceipt } from './receipt-evidence'
import ComparisonInspection from './ComparisonInspection'
import type { ComparisonView } from './ComparisonInspection'
import { nativeComparison, scopePage } from './comparison-evidence'
import type { NativeComparison, NativeScope } from './comparison-evidence'
import InputInspection from './InputInspection'
import type { InputView } from './InputInspection'
import { emptyInputProgress, inputPage } from './input-evidence'
import type { InputProgress, InputSelection } from './input-evidence'
import { BankReceiptMetadata, BankReceiptRow } from './BankReceiptDetails'
import BankComparisonInspection from './BankComparisonInspection'
import type { BankComparisonView } from './BankComparisonInspection'
import { bankComparison, bankScopePage, emptyBankScopeProgress } from './bank-comparison-evidence'
import type { BankScopeProgress } from './bank-comparison-evidence'
import type { BankProvenance } from './bank-provenance'

type BankReturn = { onUnavailable: () => void; backLabel: 'saved activity' | 'revision history' }
export type ReceiptNavigation = { mode: 'full' } | ({ mode: 'row-effects' } & BankReturn) | ({ mode: 'bank-comparisons'; context: BankProvenance } & BankReturn)
type View = InputView | ComparisonView | BankComparisonView | { kind: 'receipts'; page: Page<SavedReceipt>; after: string | null } | { kind: 'rows'; receipt: SavedReceipt; page: CompletedPage; after: string | null; preceding: ReceiptProgress }
const coverage = { snapshot: 'Snapshot evidence only', partial_activity: 'Partial activity', complete_activity: 'Complete activity for the saved scope', unknown: 'Coverage unknown' }
const outcome = { recorded: 'Recorded', linked: 'Linked existing evidence', corrected: 'Corrected', excluded: 'Excluded' }
function Metadata({ receipt, full, bankComparisons }: { receipt: SavedReceipt; full: boolean; bankComparisons: boolean }) {
  if (!full) return <BankReceiptMetadata receipt={receipt} comparisons={bankComparisons} />
  return <><div className="wi-line"><h4>Saved completion</h4><span className="ws-pill">{receipt.mode === 'limited' ? 'Limited coverage' : 'Reconciled at completion'}</span></div><dl className="wi-meta"><div><dt>Receipt</dt><dd>{receipt.id}</dd></div><div><dt>Completed at</dt><dd>{receipt.created_at}</dd></div><div><dt>Batch revision</dt><dd>{receipt.batch_revision}</dd></div><div><dt>Coverage</dt><dd>{coverage[receipt.coverage]}</dd></div><div><dt>Source rows</dt><dd>{receipt.row_count}</dd></div><div><dt>Saved selections</dt><dd>{receipt.selection_count}</dd></div><div><dt>Comparison scopes</dt><dd>{receipt.scope_count}</dd></div></dl><p className="ws-hint">{receipt.mode === 'limited' ? 'No reconciliation comparison was retained for this completion.' : full ? 'Reconciliation applies only to the frozen scopes at this completion. Inspect native comparisons for the saved equations. Original input rows are available for each side and group.' : 'Reconciliation applies only to the saved scopes at this completion. This view shows the historical metadata and row effects.'} These counts describe the whole batch and do not establish current holdings or complete account history.</p></>
}
export default function ReceiptInspection({ auth, context, initial, masked, busy, onBack, navigation }: { auth: AuthController; context: ReceiptContext; initial: Page<SavedReceipt>; masked: boolean; busy: boolean; onBack: () => void; navigation: ReceiptNavigation }) {
  const [view, setView] = useState<View | undefined>({ kind: 'receipts', page: initial, after: null })
  const [loading, setLoading] = useState(false), [failed, setFailed] = useState(false)
  const mounted = useRef(true), generation = useRef(0), heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { if (view?.kind !== 'scopes' && view?.kind !== 'comparison' && view?.kind !== 'inputs' && view?.kind !== 'bank-scopes' && view?.kind !== 'bank-comparison') heading.current?.focus() }, [view, loading, failed])
  const disabled = busy || loading, full = navigation.mode === 'full'
  const work = async (read: () => Promise<View | undefined>) => {
    const current = ++generation.current; setView(undefined); setFailed(false); setLoading(true)
    try { const next = await read(); if (mounted.current && current === generation.current) setView(next) }
    catch { if (mounted.current && current === generation.current) { if (navigation.mode !== 'full') navigation.onUnavailable(); else setFailed(true) } }
    finally { if (mounted.current && current === generation.current) setLoading(false) }
  }
  const receipts = (after: string | null = null) => work(async () => {
    const result = await auth.finance('/receipts/query', { batch_id: context.batch_id, limit: 25, after }, value => receiptPage(value, context, after))
    return result && { kind: 'receipts', page: result, after }
  })
  const rows = (receipt: SavedReceipt, after: string | null = null, preceding: ReceiptProgress = emptyReceiptProgress) => work(async () => {
    const result = await auth.finance('/receipts/rows/query', { receipt_id: receipt.id, limit: 25, after }, value => completedRows(value, receipt, context, after, preceding))
    return result && { kind: 'rows', receipt, page: result, after, preceding }
  })
  const comparisons = (receipt: SavedReceipt, after: string | null = null, preceding = 0) => work(async () => {
    if (!full) return undefined
    const result = await auth.finance('/receipts/scopes/query', { receipt_id: receipt.id, limit: 25, after }, value => scopePage(value, receipt, after, preceding))
    return result && { kind: 'scopes', receipt, page: result, after, preceding }
  })
  const inspect = (receipt: SavedReceipt, selected: NativeScope) => work(async () => {
    if (!full) return undefined
    const result = await auth.finance('/receipts/scopes/inspect', { id: selected.id }, value => nativeComparison(value, selected, receipt))
    return result && { kind: 'comparison', receipt, selected, comparison: result }
  })
  const inputs = (receipt: SavedReceipt, comparison: NativeComparison, selection: InputSelection, after: string | null = null, preceding: InputProgress = emptyInputProgress) => work(async () => {
    if (!full) return undefined
    const result = await auth.finance('/receipts/inputs/query', { scope_id: comparison.scope.id, side: selection.side, part: selection.part, limit: 25, after }, value => inputPage(value, comparison, receipt, context, selection, after, preceding))
    return result && { kind: 'inputs', receipt, comparison, selection, page: result, after, preceding }
  })
  const bankScopes = (receipt: SavedReceipt, after: string | null = null, preceding: BankScopeProgress = emptyBankScopeProgress) => work(async () => {
    if (navigation.mode !== 'bank-comparisons') return undefined
    const result = await auth.finance('/receipts/scopes/query', { receipt_id: receipt.id, limit: 25, after }, value => bankScopePage(value, receipt, navigation.context, after, preceding))
    return result && { kind: 'bank-scopes', receipt, page: result, after, preceding }
  })
  const inspectBank = (receipt: SavedReceipt, selected: NativeScope) => work(async () => {
    if (navigation.mode !== 'bank-comparisons') return undefined
    const result = await auth.finance('/receipts/scopes/inspect', { id: selected.id }, value => bankComparison(value, selected, receipt, navigation.context))
    return result && { kind: 'bank-comparison', receipt, selected, comparison: result }
  })
  return <section className="wi-receipts" aria-labelledby="receipt-heading">
    {view?.kind !== 'scopes' && view?.kind !== 'comparison' && view?.kind !== 'inputs' && view?.kind !== 'bank-scopes' && view?.kind !== 'bank-comparison' && <button className="ws-text" disabled={disabled} onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />Back to {navigation.mode !== 'full' ? navigation.backLabel : context.kind === 'event' ? 'account activity' : 'lot observations'}</button>}
    <div className="wi-detail-title"><span className="ws-eyebrow">Historical completion evidence</span><h3 id="receipt-heading" tabIndex={-1} ref={heading}>Batch completion</h3>{full && <p hidden={view?.kind === 'scopes' || view?.kind === 'comparison' || view?.kind === 'inputs' || view?.kind === 'bank-scopes' || view?.kind === 'bank-comparison'}>Batch {context.batch_id}<br />Opened from {context.kind === 'event' ? 'event' : 'lot observation'} {context.id} · revision {context.revision}</p>}</div>
    {full && view?.kind !== 'comparison' && view?.kind !== 'inputs' && <p className="ws-notice">Receipts describe a completed historical operation for the whole batch. They can include other accounts, positions and cash evidence. Later corrections or changed selections do not rewrite a receipt, and it does not establish current balances, tax basis or lifetime history.</p>}
    {!full && <><p className="ws-hint">Whole-batch records, including other accounts and positions.</p><details className="wb-about"><summary>About batch receipts</summary><p className="ws-hint">Receipts preserve historical completion. Later corrections and selections do not rewrite them or establish current balances or complete account history. Pages use identity order, not completion-time order. Coverage claims and saved effects remain separate.</p><dl className="wb-meta"><div><dt>Batch</dt><dd>{context.batch_id}</dd></div><div><dt>Opened from event</dt><dd>{context.id}</dd></div><div><dt>Event revision</dt><dd>{context.revision}</dd></div></dl></details></>}
    {loading && <p role="status" className="wi-empty">Checking saved completion evidence…</p>}
    {failed && <div role="alert" className="ws-notice"><strong>Completion evidence could not be verified.</strong><p>Earlier details have been cleared. No automatic retry is performed.</p><button className="ws-text" disabled={disabled} onClick={() => void receipts()}>Reload batch receipts</button></div>}
    {view?.kind === 'receipts' && <><div className="wi-line"><h4>Receipts for this batch</h4><button className="ws-text" disabled={disabled} onClick={() => void receipts(view.after)}><RefreshCw size={14} aria-hidden="true" />Refresh receipts</button></div>{full && <p className="ws-hint">Pages use stable identity order, not completion-time order. Source coverage claims and saved completion effects are separate evidence.</p>}
      {!view.page.items.length && <p className="wi-empty">No completion receipt on this page. This does not establish zero activity, invalid evidence or a complete import history.</p>}
      {view.page.items.map(receipt => <article className="wi-evidence" key={receipt.id}><Metadata receipt={receipt} full={full} bankComparisons={navigation.mode === 'bank-comparisons'} /><button className="ws-text" disabled={disabled} aria-label={!full ? `Row effects for receipt ${receipt.id}` : undefined} onClick={() => void rows(receipt)}>{full ? `Inspect row effects for receipt ${receipt.id}` : 'Row effects'}<FileCheck2 size={15} aria-hidden="true" /></button>{full && receipt.mode === 'reconciled' && <button className="ws-text" disabled={disabled} onClick={() => void comparisons(receipt)}>Inspect native comparisons<ArrowRight size={15} aria-hidden="true" /></button>}{navigation.mode === 'bank-comparisons' && receipt.mode === 'reconciled' && <button className="ws-text" disabled={disabled} onClick={() => void bankScopes(receipt)}>Saved comparisons<ArrowRight size={15} aria-hidden="true" /></button>}</article>)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void receipts()}>First receipt page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void receipts(view.page.next_after)}>Next receipt page<ArrowRight size={14} aria-hidden="true" /></button></div></>}
    {view?.kind === 'rows' && <><button className="ws-text" disabled={disabled} onClick={() => void receipts()}>Back to batch receipts</button><article className="wi-evidence"><Metadata receipt={view.receipt} full={full} bankComparisons={navigation.mode === 'bank-comparisons'} /></article><div className="wi-line"><h4>Historical row effects</h4><button className="ws-text" disabled={disabled} onClick={() => void rows(view.receipt, view.after, view.preceding)}><RefreshCw size={14} aria-hidden="true" />Refresh row effects</button></div><p className="ws-hint">{full ? 'All effects on this page remain visible. An exact originating row is labeled only when source row, review revision, target identity and saved record revision agree. An absent row on one page is not a missing or excluded completion.' : 'All batch effects remain visible. The originating revision is identified only by its exact saved references.'}</p>
      {view.page.items.map(row => !full ? <BankReceiptRow row={row} sourceRow={context.source_row_id} key={row.id} /> : <article className="wi-evidence" key={row.id}><div className="wi-line"><h4>{outcome[row.outcome]}</h4><span className="ws-pill">{row.id === context.source_row_id ? 'Originating evidence revision' : 'Another source row in this batch'}</span></div><dl className="wi-meta"><div><dt>Source row</dt><dd>{row.id}</dd></div><div><dt>Review revision</dt><dd>{row.review_revision}</dd></div><div><dt>Operation</dt><dd>{row.operation}</dd></div>{row.record_revision !== null && <><div><dt>Saved target</dt><dd>{row.event_id ? 'Event' : row.lot_observation_id ? 'Lot observation' : 'Snapshot'} {row.event_id ?? row.lot_observation_id ?? row.snapshot_id}</dd></div><div><dt>Saved revision</dt><dd>{row.record_revision}</dd></div></>}{row.provider_identity_id && <div><dt>Identity link</dt><dd>{row.provider_identity_id}</dd></div>}{row.selection_id && <><div><dt>Selection</dt><dd>{row.selection_id}</dd></div><div><dt>Selection revision</dt><dd>{row.selection_revision}</dd></div></>}</dl><p className="ws-hint">{row.outcome === 'excluded' ? 'No financial target was created by this exclusion.' : row.outcome === 'linked' ? 'The source occurrence linked to existing evidence. It is not an additional movement.' : row.outcome === 'corrected' ? 'This records the correction made at completion, not a current selection or a new independent movement.' : 'This records the saved target revision at completion. Its present state may differ.'}</p></article>)}
      <div className="wi-line"><button className="ws-text" disabled={disabled || view.after === null} onClick={() => void rows(view.receipt)}>First row page</button><button className="ws-text" disabled={disabled || !view.page.next_after} onClick={() => void rows(view.receipt, view.page.next_after, view.page.progress)}>Next row page<ArrowRight size={14} aria-hidden="true" /></button></div></>}
    {full && (view?.kind === 'scopes' || view?.kind === 'comparison') && <ComparisonInspection view={view} masked={masked} disabled={disabled} onBack={() => void receipts()} onScopes={(after, preceding) => void comparisons(view.receipt, after, preceding)} onInspect={scope => void inspect(view.receipt, scope)} onInputs={selection => { if (view.kind === 'comparison') void inputs(view.receipt, view.comparison, selection) }} />}
    {navigation.mode === 'bank-comparisons' && (view?.kind === 'bank-scopes' || view?.kind === 'bank-comparison') && <BankComparisonInspection view={view} context={navigation.context} masked={masked} disabled={disabled} onBack={() => void receipts()} onScopes={(after, preceding) => void bankScopes(view.receipt, after, preceding)} onInspect={scope => void inspectBank(view.receipt, scope)} />}
    {full && view?.kind === 'inputs' && <InputInspection view={view} masked={masked} disabled={disabled} onBack={() => void inspect(view.receipt, view.comparison.scope)} onInputs={(selection, after, preceding) => void inputs(view.receipt, view.comparison, selection, after, preceding)} />}
  </section>
}