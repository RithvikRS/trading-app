import { useState } from 'react'
import { Check, Tags, Undo2, X } from 'lucide-react'
import { ReportingAmount } from './display'
import { bankCategories, bankNames, sampleRefund } from './data/banking'
import type { BankTransaction } from './data/banking'
import { categoryOptions, categoryRestriction, categorySuggestion, previewCategories, refundEvidence } from './data/categories'
import type { CategoryPreview, CategoryTarget } from './data/categories'
import type { TransferAction, TransferState } from './data/transfers'
import { recordDate } from './holdingPresentation'

export function CorrectionPreview({ preview, records, id, onApply, onCancel }: { preview: CategoryPreview; records: BankTransaction[]; id: string; onApply: () => void; onCancel: () => void }) {
  return <section className="category-preview" aria-labelledby={id}>
    <div className="category-preview-heading"><Tags size={18} aria-hidden="true" /><h3 id={id} tabIndex={-1}>Review category changes</h3></div>
    <p>{preview.ids.length} selected · {preview.edits.length} to change · {preview.excluded.length} excluded</p>
    <ul className="category-preview-list">{preview.edits.map(edit => {
      const item = records.find(record => record.id === edit.id)
      if (!item) return <li key={edit.id}>Source record unavailable. Create a new preview before applying.</li>
      const refund = item.id === sampleRefund.purchaseId && records.find(record => record.id === sampleRefund.creditId)
      return <li key={edit.id}><div><strong>{item.description}</strong><span>{bankNames[item.accountId]} · {recordDate(item.date)} · <ReportingAmount value={item.amount} /></span></div><p className="category-change"><span>{bankCategories[edit.from.category]}</span><span aria-hidden="true"> → </span><span className="sr-only"> changes to </span><strong>{bankCategories[edit.after.category]}</strong></p><small>{edit.after.provenance === 'suggestion' ? 'Accept supplied suggestion' : edit.after.category === 'unresolved' ? 'Clear reviewed classification; leave unresolved' : 'Manual correction'}</small>{refund && <p className="category-linked-note">Linked refund: {refund.description}. {edit.after.category === 'unresolved' ? 'It will remain unresolved until the purchase is classified.' : `Its category will follow ${bankCategories[edit.after.category]}; refund evidence is revalidated before counting it.`} The original credit is unchanged.</p>}</li>
    })}</ul>
    {preview.excluded.length > 0 && <div className="category-exclusions"><h4>Excluded from this change</h4><ul>{preview.excluded.map(entry => <li key={entry.id}><strong>{records.find(item => item.id === entry.id)?.description ?? 'Unavailable record'}</strong><span>{entry.reason}</span></li>)}</ul></div>}
    <p className="category-preview-note">Only the listed category decisions change. Linked refund categories are derived from their purchase. Source records, transfers, and balances stay unchanged. Undo reverses the complete change.</p>
    <div className="category-actions"><button className="primary-button" disabled={preview.edits.length === 0} onClick={onApply}><Check size={15} aria-hidden="true" />Apply {preview.edits.length} {preview.edits.length === 1 ? 'change' : 'changes'}</button><button className="outlined-button" onClick={onCancel}><X size={14} aria-hidden="true" />Cancel preview</button></div>
    {preview.edits.length === 0 && <p role="status">No eligible changes. Choose another category or selection.</p>}
  </section>
}

export function CategoryEditor({ item, records, state, onAction }: { item: BankTransaction; records: BankTransaction[]; state: TransferState; onAction: (action: TransferAction) => void }) {
  const suggestion = categorySuggestion(item, state), restriction = categoryRestriction(item, state)
  const [target, setTarget] = useState<CategoryTarget>(suggestion ? 'suggested' : state.classifications[item.id]?.category ?? (categoryOptions(item).includes(item.sourceCategory) ? item.sourceCategory : 'unresolved'))
  const [preview, setPreview] = useState<CategoryPreview | null>(null)
  const currentTarget = target === 'suggested' && !suggestion ? state.classifications[item.id]?.category ?? 'unresolved' : target
  const refund = refundEvidence(item, records, state)
  function apply(action: TransferAction) { onAction(action); setPreview(null); document.getElementById('category-editor-title')?.focus() }
  return <section className="category-editor" aria-labelledby="category-editor-title">
    <h3 id="category-editor-title" tabIndex={-1}>Review category</h3>
    {restriction ? <p className="category-editor-restriction">{restriction}{refund && ` Current refund category: ${bankCategories[refund.category]}.`}{item.sourceCategory === 'refund' && !refund && ' Its evidence is incomplete, so it remains unresolved.'}</p> : <>
      {suggestion && <div className="category-suggestion"><span>Suggested · {bankCategories[suggestion.category]}</span><p>{suggestion.reason}</p><small>Not applied until reviewed.</small></div>}
      <label className="holding-select"><span>New category</span><select value={currentTarget} onChange={event => { setTarget(event.target.value as CategoryTarget); setPreview(null) }}>{suggestion && <option value="suggested">Accept suggestion · {bankCategories[suggestion.category]}</option>}{categoryOptions(item).map(category => <option key={category} value={category}>{category === 'unresolved' ? 'Leave uncategorized / clear review' : bankCategories[category]}</option>)}</select></label>
      <button className="outlined-button" onClick={() => setPreview(previewCategories([item.id], currentTarget, records, state))}>Preview correction</button>
      {preview && <CorrectionPreview id="inspector-category-preview" preview={preview} records={records} onApply={() => apply({ type: 'categorize', preview })} onCancel={() => setPreview(null)} />}
    </>}
    {state.message && <p className={`category-editor-message ${state.error ? 'warning-text' : ''}`} role={state.error ? 'alert' : 'status'}>{state.message}</p>}
    <button className="outlined-button" disabled={state.history.length === 0} onClick={() => apply({ type: 'undo' })}><Undo2 size={14} aria-hidden="true" />Undo last change</button>
    <p className="category-editor-footnote">Local review only. Decisions and shared undo history clear on reload.</p>
  </section>
}
