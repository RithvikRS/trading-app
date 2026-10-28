import { useEffect } from 'react'
import { ArrowLeft, ArrowRight, Building2, CircleHelp, Landmark, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import type { AuthController } from './auth'
import BankAccountSetup from './BankAccountSetup'
import BankSourceAssignments from './BankSourceAssignments'
import { MAX_ACCOUNT_PAGES } from './accounts'
import type { AccountsState } from './accounts'

const institutions = { hdfc: 'HDFC', sbi: 'SBI', indmoney: 'INDmoney', fund_registrar: 'Fund registrar', ubs: 'UBS' }
const kinds = { bank: 'Bank account', brokerage: 'Brokerage', mutual_fund: 'Mutual fund', employee_stock: 'Employee shares' }

export default function Accounts({ auth, state, busy }: { auth: AuthController; state: AccountsState; busy: boolean }) {
  useEffect(() => { if (state.kind === 'idle' && !busy) void auth.loadAccounts() }, [auth, state.kind, busy])
  const page = state.kind === 'ready' ? state.page : undefined
  const cursor = state.kind === 'idle' ? undefined : state.cursor
  const loading = state.kind === 'idle' || state.kind === 'loading'
  return <section className="ws-accounts" aria-labelledby="accounts-heading" aria-busy={loading}>
    <div className="ws-accounts-intro"><div className="ws-accounts-icon"><Landmark size={25} aria-hidden="true" /></div><div><span className="ws-eyebrow">Your account directory</span><h2 id="accounts-heading">A place for every account.</h2><p>Saved accounts, their institutions and native currencies. Account status describes this workspace; it does not confirm a live provider connection.</p></div></div>
    <div className="ws-accounts-toolbar"><span><ShieldCheck size={15} aria-hidden="true" />Saved account information</span><button className="ws-secondary" disabled={busy || loading} onClick={() => void auth.loadAccounts('refresh')}><RefreshCw size={15} aria-hidden="true" />Refresh accounts</button></div>
    <BankAccountSetup auth={auth} busy={busy || loading} />
    <BankSourceAssignments auth={auth} busy={busy || loading} />
    {loading && <div className="ws-accounts-message" role="status"><LoaderCircle className="ws-spin" size={25} aria-hidden="true" /><h3>Loading your accounts…</h3><p>Checking access and reading saved account information.</p></div>}
    {state.kind === 'failed' && <div className="ws-accounts-message"><CircleHelp size={25} aria-hidden="true" /><h3 role="alert">{state.limited ? 'Account requests are temporarily limited.' : 'Accounts are unavailable right now.'}</h3><p>{state.limited ? 'Wait a moment, then refresh your accounts.' : 'Refresh to try again. The previous page is hidden while its contents cannot be verified.'}</p></div>}
    {page && page.items.length === 0 && <div className="ws-accounts-message"><Building2 size={28} aria-hidden="true" /><h3>{cursor?.after ? 'There are no accounts on this page.' : 'No accounts saved yet.'}</h3><p>{cursor?.after ? 'The directory may have changed. Return to the first page to check it again.' : 'Saved accounts appear here. Add an HDFC or SBI bank account to start your directory.'}</p></div>}
    {page && page.items.length > 0 && <ul className="ws-account-list" aria-label="Saved accounts">{page.items.map(account => <li key={account.id} className="ws-account"><div className={`ws-account-mark ws-account-mark-${account.market.toLowerCase()}`} aria-hidden="true"><Landmark size={22} /></div><div className="ws-account-summary"><span>{institutions[account.institution]}</span><h3>{account.label}</h3><p>{kinds[account.kind]} · {account.market === 'IN' ? 'India' : 'United States'}</p></div><div className="ws-account-currencies"><span>Native currencies</span><strong>{account.currencies.join(' · ')}</strong></div><span className={`ws-account-state${account.state === 'archived' ? ' ws-account-archived' : ''}`}>{account.state === 'active' ? 'Active' : 'Archived'}</span></li>)}</ul>}
    {!loading && cursor && <div className="ws-account-pagination"><p role="status">Page {cursor.previous.length + 1}{page ? ` · ${page.items.length} ${page.items.length === 1 ? 'account' : 'accounts'} on this page` : ''}</p><div><button className="ws-secondary" disabled={busy || !cursor.previous.length} onClick={() => void auth.loadAccounts('previous')}><ArrowLeft size={15} aria-hidden="true" />Previous</button><button className="ws-secondary" disabled={busy || !page?.next_after || cursor.previous.length >= MAX_ACCOUNT_PAGES - 1} onClick={() => void auth.loadAccounts('next')}>Next<ArrowRight size={15} aria-hidden="true" /></button>{cursor.after && <button className="ws-text" disabled={busy} onClick={() => void auth.loadAccounts('first')}>Back to first page</button>}</div></div>}
    {cursor && cursor.previous.length >= MAX_ACCOUNT_PAGES - 1 && page?.next_after && <p className="ws-notice" role="status">This view reached its page limit. Some accounts are not displayed.</p>}
    <p className="ws-accounts-note"><CircleHelp size={15} aria-hidden="true" /><span>This directory shows no balances or investment values. Native currencies describe each account and stay the same when you change your display currency.</span></p>
  </section>
}
