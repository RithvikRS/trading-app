import { useState } from 'react'
import { ArrowUpRight, Link2, ShieldCheck } from 'lucide-react'
import type { AuthController } from './auth'
import type { ConnectionState } from './indmoney'

const labels = { disconnected: 'Not authorized', pending: 'Authorization in progress', authorized: 'Authorization saved', refreshing: 'Renewal in progress', reconnect_required: 'Reconnection needed' }
export default function IndmoneyConnection({ auth, state, busy }: { auth: AuthController; state?: ConnectionState; busy: boolean }) {
  const [confirm, setConfirm] = useState(false)
  const value = state?.kind === 'ready' ? state.value : undefined
  return <section className="ws-card ws-connection" aria-labelledby="indmoney-heading" aria-busy={state?.kind === 'loading'}>
    <div className="ws-card-title"><Link2 size={21} aria-hidden="true" /><h2 id="indmoney-heading">INDmoney authorization</h2></div>
    <p>Authorize read-only portfolio access on INDmoney’s own sign-in page. Your provider password and verification codes stay there.</p>
    <p className="ws-connection-status" role="status"><ShieldCheck size={16} aria-hidden="true" />{state?.kind === 'loading' ? 'Checking your connection…' : state?.kind === 'unconfigured' ? 'Connection setup is not enabled.' : state?.kind === 'failed' ? 'The result could not be confirmed. Check status before trying again.' : value ? labels[value.status] : 'Check setup to get started or finish a returned authorization.'}</p>
    {value?.status === 'authorized' && <p className="ws-hint">Authorization is saved securely. Account identity, holdings, history and scheduled updates have not been verified or imported.</p>}
    {value?.status === 'reconnect_required' && <p className="ws-hint">Disconnect the previous authorization before starting again.</p>}
    {state?.kind === 'ready' && state.cleanup === 'unavailable' && <p className="ws-notice" role="alert">Local access is disabled. Provider revocation could not be confirmed; review connected apps in INDmoney.</p>}
    {state?.kind === 'ready' && state.cleanup === 'confirmed' && <p className="ws-hint">Local credentials removed. The provider accepted revocation of the known tokens.</p>}
    <div className="ws-connection-actions"><button className="ws-secondary" disabled={busy} onClick={() => { setConfirm(false); void auth.connection('status') }}>Check connection status</button>
      {value && ['disconnected', 'pending'].includes(value.status) && !value.can_complete && <button className="ws-primary" disabled={busy} onClick={() => void auth.connection('authorize')}>Continue to INDmoney<ArrowUpRight size={16} aria-hidden="true" /></button>}
      {value?.can_complete && <button className="ws-primary" disabled={busy} onClick={() => void auth.connection('complete')}>Finish authorization</button>}
      {value?.status === 'authorized' && <button className="ws-secondary" disabled={busy} onClick={() => void auth.connection('refresh')}>Renew authorization</button>}
      {value && value.status !== 'disconnected' && <button className="ws-text" disabled={busy} onClick={() => setConfirm(true)}>Disconnect</button>}
    </div>
    {confirm && value && value.status !== 'disconnected' && <div className="ws-confirm"><p>Remove local authorization and request revocation of known provider tokens?</p><button className="ws-secondary" disabled={busy} onClick={() => { setConfirm(false); void auth.connection('disconnect') }}>Disconnect INDmoney</button><button className="ws-text" disabled={busy} onClick={() => setConfirm(false)}>Keep authorization</button></div>}
    <p className="ws-hint">Starting and finishing authorization require a recent password and authenticator sign-in. Return here and check status after provider consent. This connection cannot place trades.</p>
  </section>
}
