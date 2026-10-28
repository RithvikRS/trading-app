import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, CircleHelp, Landmark, LoaderCircle, Plus } from 'lucide-react'
import { FinancialRequestError } from './auth'
import type { AuthController } from './auth'
import { bankSetupCommand, bankSetupInput, MAX_BANK_SETUP_REVISION, parseBankSetupReceipt, parseBankSetupSnapshot } from './bank-setup'
import type { BankSetupCommand, BankSetupCurrency, BankSetupInstitution, BankSetupReceipt, BankSetupSnapshot } from './bank-setup'
import './bank-setup.css'

type View =
  | { kind: 'closed' }
  | { kind: 'reading'; message: string }
  | { kind: 'form'; snapshot: BankSetupSnapshot }
  | { kind: 'saving'; command: BankSetupCommand }
  | { kind: 'uncertain'; command: BankSetupCommand }
  | { kind: 'review'; snapshot: BankSetupSnapshot; directoryReady: boolean }
  | { kind: 'saved'; receipt: BankSetupReceipt }
  | { kind: 'unavailable' }
const institutions = { hdfc: 'HDFC', sbi: 'SBI' }

function Receipt({ receipt, latest = false }: { receipt: BankSetupReceipt; latest?: boolean }) {
  return <aside className="bs-receipt" aria-label={latest ? 'Latest saved creation receipt' : 'Original creation receipt'}><span className="ws-eyebrow">{latest ? 'Latest saved creation receipt' : 'Original creation receipt'}</span><h4>{institutions[receipt.institution]} · {receipt.label}</h4><p>{receipt.currencies.join(' · ')} native currencies · Creation revision {receipt.revision}</p><p className="ws-hint">This confirms a historical creation. It does not describe the account’s current status, a bank connection or a balance.</p><details><summary>Receipt identifiers</summary><dl><div><dt>Account</dt><dd>{receipt.account_id}</dd></div><div><dt>Request</dt><dd>{receipt.intent_id}</dd></div></dl></details></aside>
}

export default function BankAccountSetup({ auth, busy }: { auth: AuthController; busy: boolean }) {
  const [view, setView] = useState<View>({ kind: 'closed' })
  const [institution, setInstitution] = useState<BankSetupInstitution>('hdfc'), [label, setLabel] = useState(''), [currencies, setCurrencies] = useState<BankSetupCurrency[]>([])
  const [error, setError] = useState(''), [reviewed, setReviewed] = useState(false)
  const mounted = useRef(true), generation = useRef(0), guard = useRef(false), context = useRef<string | undefined>(undefined)
  const reviewRequired = useRef(true), wasOpen = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null), entry = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    mounted.current = true
    const screen = auth.snapshot().screen
    context.current = screen.kind === 'workspace' ? screen.session.workspace_context : undefined
    const unsubscribe = auth.subscribe(() => {
      const next = auth.snapshot().screen
      if (next.kind !== 'workspace' || next.session.workspace_context !== context.current) {
        generation.current++; guard.current = false; context.current = undefined
        setView({ kind: 'closed' }); setLabel(''); setCurrencies([]); setError(''); setReviewed(false)
      }
    })
    return () => { mounted.current = false; generation.current++; guard.current = false; unsubscribe() }
  }, [auth])
  useEffect(() => {
    if (view.kind !== 'closed') heading.current?.focus()
    else if (wasOpen.current) entry.current?.focus()
    wasOpen.current = view.kind !== 'closed'
  }, [view.kind])
  const current = (token: number) => {
    const screen = auth.snapshot().screen
    return mounted.current && generation.current === token && screen.kind === 'workspace' && screen.session.workspace_context === context.current
  }
  const begin = () => {
    const state = auth.snapshot()
    if (guard.current || busy || state.busy || state.screen.kind !== 'workspace' || state.screen.session.workspace_context !== context.current) return undefined
    guard.current = true; setError(''); return ++generation.current
  }
  const end = (token: number) => { if (current(token)) guard.current = false }
  const close = () => { generation.current++; guard.current = false; reviewRequired.current = true; setView({ kind: 'closed' }); setLabel(''); setCurrencies([]); setError(''); setReviewed(false) }
  const form = (snapshot: BankSetupSnapshot) => { setLabel(''); setInstitution('hdfc'); setCurrencies([]); setReviewed(false); setView({ kind: 'form', snapshot }) }
  const review = async (snapshot: BankSetupSnapshot, token: number) => {
    reviewRequired.current = true; setLabel(''); setCurrencies([])
    await auth.loadAccounts('first')
    if (!current(token)) return
    const screen = auth.snapshot().screen
    reviewRequired.current = true; setReviewed(false)
    setView({ kind: 'review', snapshot, directoryReady: screen.kind === 'workspace' && screen.accounts.kind === 'ready' })
  }
  const load = async (mode: 'form' | 'review') => {
    const token = begin(); if (token === undefined) return
    const screen = auth.snapshot().screen
    const directoryReady = screen.kind === 'workspace' && screen.accounts.kind === 'ready'
    const openForm = mode === 'form' && (!reviewRequired.current || reviewed && directoryReady)
    const reviewedRevision = view.kind === 'review' ? view.snapshot.revision : undefined
    if (!openForm) reviewRequired.current = true
    setView({ kind: 'reading', message: 'Checking saved bank account setup…' })
    try {
      const snapshot = await auth.finance('/bank-account-setup/query', {}, value => current(token) ? parseBankSetupSnapshot(value) : undefined)
      if (!current(token) || !snapshot) return
      if (!openForm || reviewedRevision !== undefined && snapshot.revision !== reviewedRevision) await review(snapshot, token)
      else { reviewRequired.current = false; form(snapshot) }
    } catch { if (current(token)) setView({ kind: 'unavailable' }) }
    finally { end(token) }
  }
  const save = async (command: BankSetupCommand, token: number) => {
    reviewRequired.current = true
    setView({ kind: 'saving', command })
    try {
      const receipt = await auth.finance('/bank-account-setup/create', command, value => current(token) ? parseBankSetupReceipt(value, command) : undefined)
      if (!current(token) || !receipt) return
      setView({ kind: 'saved', receipt }); setLabel(''); setCurrencies([])
      await auth.loadAccounts('first')
    } catch (failure) {
      if (!current(token)) return
      if (failure instanceof FinancialRequestError && failure.conflict) {
        // A conflict is not proof that an earlier uncertain request did not save.
        setView({ kind: 'reading', message: 'Checking saved records after a conflict…' })
        try {
          const snapshot = await auth.finance('/bank-account-setup/query', {}, value => current(token) ? parseBankSetupSnapshot(value) : undefined)
          if (current(token) && snapshot) await review(snapshot, token)
        } catch { if (current(token)) setView({ kind: 'unavailable' }) }
      } else setView({ kind: 'uncertain', command })
    }
  }
  const submit = async () => {
    if (view.kind !== 'form') return
    let input
    try { input = bankSetupInput({ institution, label, currencies }) }
    catch { setError('Use a name of 1–64 characters starting with a letter, followed by letters, spaces, periods, parentheses or hyphens. Choose at least one native currency.'); return }
    const token = begin(); if (token === undefined) return
    const openedRevision = view.snapshot.revision
    setView({ kind: 'reading', message: 'Checking the saved revision before creating…' })
    try {
      const snapshot = await auth.finance('/bank-account-setup/query', {}, value => current(token) ? parseBankSetupSnapshot(value) : undefined)
      if (!current(token) || !snapshot) return
      if (snapshot.revision !== openedRevision) { await review(snapshot, token); return }
      if (snapshot.revision >= MAX_BANK_SETUP_REVISION) { form(snapshot); return }
      let command: BankSetupCommand
      try { command = bankSetupCommand(crypto.randomUUID(), snapshot.revision, input) }
      catch { form(snapshot); setError('A secure request could not be prepared. Re-enter the account details to try again.'); return }
      await save(command, token)
    } catch { if (current(token)) setView({ kind: 'unavailable' }) }
    finally { end(token) }
  }
  const retry = async () => {
    if (view.kind !== 'uncertain') return
    const command = view.command, token = begin(); if (token === undefined) return
    try { await save(command, token) } finally { end(token) }
  }
  const waiting = view.kind === 'reading' || view.kind === 'saving', disabled = busy || waiting
  return <div className="bs-setup">
    <div className="bs-entry"><div><Landmark size={19} aria-hidden="true" /><span>Add an HDFC or SBI account to your directory.</span></div><button ref={entry} type="button" className="ws-secondary" disabled={busy || view.kind !== 'closed'} onClick={() => void load('form')}><Plus size={16} aria-hidden="true" />Add bank account</button></div>
    {view.kind !== 'closed' && <section className="bs-panel" aria-labelledby="bank-setup-heading" aria-busy={waiting}><div className="bs-title"><div><span className="ws-eyebrow">Bank account setup</span><h3 id="bank-setup-heading" ref={heading} tabIndex={-1}>{view.kind === 'saved' ? 'Creation confirmed.' : view.kind === 'uncertain' ? 'The save is not confirmed.' : view.kind === 'review' ? 'Review your saved accounts.' : 'Give your account a place.'}</h3></div>{view.kind === 'saved' ? <Check size={23} aria-hidden="true" /> : <Landmark size={23} aria-hidden="true" />}</div>
      {view.kind === 'reading' && <p className="bs-status" role="status"><LoaderCircle className="ws-spin" size={19} aria-hidden="true" />{view.message}</p>}
      {view.kind === 'form' && <>
        <p className="bs-intro">Save an institution, a safe account name and its native currencies. Check the directory for an existing account before creating a new account.</p>
        {view.snapshot.last_saved && <Receipt receipt={view.snapshot.last_saved} latest />}
        <p className="ws-hint">The latest receipt cannot establish whether an older unconfirmed request saved. Other tabs may have created accounts since then.</p>
        {view.snapshot.revision >= MAX_BANK_SETUP_REVISION ? <p className="ws-notice" role="status">The bank account setup limit has been reached. Review your saved accounts.</p> : <form className="bs-form" noValidate onSubmit={event => { event.preventDefault(); void submit() }}>
          <div className="bs-fields"><div><label htmlFor="bank-setup-institution">Institution</label><select id="bank-setup-institution" value={institution} disabled={disabled} onChange={event => { setInstitution(event.target.value as BankSetupInstitution); setError('') }}><option value="hdfc">HDFC</option><option value="sbi">SBI</option></select></div><div><label htmlFor="bank-setup-label">Account name</label><input id="bank-setup-label" value={label} disabled={disabled} onChange={event => { setLabel(event.target.value); setError('') }} maxLength={64} autoComplete="off" spellCheck={false} required aria-describedby="bank-setup-label-help" /><p id="bank-setup-label-help" className="ws-hint">1–64 characters: letters, spaces, periods, parentheses and hyphens. Start with a letter; leave out account numbers and personal identifiers.</p></div></div>
          <fieldset className="bs-currencies" disabled={disabled} aria-describedby="bank-setup-currency-help"><legend>Native currencies</legend>{(['INR', 'USD'] as const).map(currency => <label key={currency}><input type="checkbox" checked={currencies.includes(currency)} onChange={event => { setCurrencies(previous => event.target.checked ? (['INR', 'USD'] as const).filter(item => item === currency || previous.includes(item)) : previous.filter(item => item !== currency)); setError('') }} />{currency}</label>)}</fieldset><p id="bank-setup-currency-help" className="ws-hint">Choose INR, USD or both. Your display currency preference does not change this choice.</p>
          {error && <p className="ws-notice" role="alert">{error}</p>}<button className="ws-primary" type="submit" disabled={disabled}>Create bank account<ArrowRight size={16} aria-hidden="true" /></button>
        </form>}
      </>}
      {(view.kind === 'saving' || view.kind === 'uncertain') && <><p className="bs-status" role="status">{view.kind === 'saving' ? 'Saving account details…' : 'The request may have saved. Retry the same request to ask for its original confirmation.'}</p><div className="bs-frozen"><strong>{institutions[view.command.institution]} · {view.command.label}</strong><span>{view.command.currencies.join(' · ')} native currencies</span></div>{view.kind === 'uncertain' && <div className="bs-actions"><button className="ws-primary" disabled={disabled} onClick={() => void retry()}>Retry the same save</button><button className="ws-secondary" disabled={disabled} onClick={() => void load('review')}>Review saved directory</button></div>}</>}
      {view.kind === 'review' && <><p className="ws-notice">Review the saved directory before creating an account. An account missing from this page may be on another page.</p>{view.snapshot.last_saved && <Receipt receipt={view.snapshot.last_saved} latest />}<p className="ws-hint">The latest receipt does not prove an older unconfirmed request failed. Continuing starts a new request. Create an account only if you intend a new directory entry.</p>{view.directoryReady ? <><label className="bs-review"><input type="checkbox" checked={reviewed} disabled={disabled} onChange={event => setReviewed(event.target.checked)} />I have reviewed the saved directory and intend to create a new account.</label><button className="ws-primary" disabled={disabled || !reviewed} onClick={() => void load('form')}>Start a new bank account</button></> : <><p role="alert">The directory could not be refreshed. Refresh it before continuing.</p><button className="ws-secondary" disabled={disabled} onClick={() => void load('review')}>Reload directory for review</button></>}</>}
      {view.kind === 'saved' && <><Receipt receipt={view.receipt} /><p className="ws-hint" role="status">The directory below shows its refresh status. This receipt confirms the original creation even if the account is on a later page or its status has since changed.</p><button className="ws-secondary" disabled={disabled} onClick={() => void load('review')}>Review directory before another account</button></>}
      {view.kind === 'unavailable' && <div className="bs-status" role="alert"><CircleHelp size={19} aria-hidden="true" /><div><strong>Saved setup could not be checked.</strong><p>Review the saved directory before starting a new request. No request is automatically repeated.</p><button className="ws-secondary" disabled={disabled} onClick={() => void load('review')}>Review saved directory</button></div></div>}
      <p className="bs-scope">Account setup saves directory information only. It does not connect to a bank or add balances or activity.</p><button type="button" className="ws-text" disabled={waiting} onClick={close}>Close setup</button>
    </section>}
  </div>
}
