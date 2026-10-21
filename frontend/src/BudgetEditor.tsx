import { useContext, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Eye, EyeOff, ShieldCheck, X } from 'lucide-react'
import { bankCategories } from './data/banking'
import type { BankCategory } from './data/banking'
import { parseBudgetLimit } from './data/budgets'
import type { BudgetAction } from './data/budgets'
import { Amount, DisplayContext } from './display'

export default function BudgetEditor({ category, limit, onAction, onClose, onTogglePrivacy }: { category: BankCategory; limit?: bigint; onAction: (action: BudgetAction) => void; onClose: () => void; onTogglePrivacy: () => void }) {
  const { hidden, currency } = useContext(DisplayContext)
  const [draft, setDraft] = useState(limit === undefined ? '' : `${limit / 100n}.${(limit % 100n).toString().padStart(2, '0')}`)
  const [error, setError] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const parsed = parseBudgetLimit(draft)
  useLayoutEffect(() => {
    const element = dialog.current!, origin = document.activeElement as HTMLElement | null
    element.showModal(); document.getElementById('budget-editor-title')?.focus()
    const previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'
    return () => { element.close(); document.body.style.overflow = previousOverflow; origin?.focus({ preventScroll: true }) }
  }, [])
  function containFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== 'Tab') return
    const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? [])
    if (event.shiftKey && (document.activeElement === controls[0] || document.activeElement?.id === 'budget-editor-title')) { event.preventDefault(); controls.at(-1)?.focus() }
    else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus() }
  }
  return <dialog ref={dialog} className="budget-editor" aria-labelledby="budget-editor-title" onKeyDown={containFocus} onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="budget-editor-top"><span className="eyebrow">October 2026 · Both banks</span><div><button className="icon-button" aria-label={hidden ? 'Show amounts in budget editor' : 'Hide amounts in budget editor'} onClick={onTogglePrivacy}>{hidden ? <Eye size={18} /> : <EyeOff size={18} />}</button><button className="icon-button" aria-label="Close budget editor" onClick={onClose}><X size={20} /></button></div></div>
    <h2 id="budget-editor-title" tabIndex={-1}>{bankCategories[category]} budget</h2><p>A monthly limit for this category. Your bank records stay unchanged.</p>
    <form onSubmit={event => { event.preventDefault(); if (hidden) return; if (parsed.error) { setError(parsed.error); document.getElementById('budget-limit')?.focus(); return }; onAction({ type: 'set', category, decimal: draft }); onClose() }}>
      {hidden ? <div className="budget-editor-private"><EyeOff size={24} aria-hidden="true" /><strong>Amount entry hidden</strong><p>Show amounts to edit or save. Your draft stays in memory.</p></div> : <>
        <label htmlFor="budget-limit">Monthly limit · INR</label><input id="budget-limit" inputMode="decimal" autoComplete="off" maxLength={32} value={draft} aria-invalid={!!error} aria-describedby="budget-input-note budget-input-error" onChange={event => { setDraft(event.target.value); setError('') }} />
        <p id="budget-input-note">Use digits and a decimal point, without commas. Zero sets a zero-spend target. Editing always uses INR.</p>
        <p id="budget-input-error" role={error ? 'alert' : undefined}>{error}</p>
        {currency !== 'INR' && parsed.minor !== undefined && <div className="budget-equivalent">Display equivalent · USD <strong><Amount value={{ currency: 'INR', minor: parsed.minor }} /></strong><small>Dated demo FX; your INR limit is unchanged.</small></div>}
      </>}
      <div className="budget-editor-actions"><button type="submit" className="primary-button" disabled={hidden}>Save limit</button><button type="button" className="outlined-button" onClick={onClose}>Cancel</button></div>
      {limit !== undefined && <button type="button" className="text-button budget-remove" disabled={hidden} onClick={() => { onAction({ type: 'remove', category }); onClose() }}>Remove category limit</button>}
    </form>
    <p className="budget-editor-footnote"><ShieldCheck size={14} aria-hidden="true" />Local sample limit · Undo available · Reload clears edits</p>
  </dialog>
}
