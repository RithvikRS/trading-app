import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ArrowRight, BarChart3, Check, ChevronRight, CircleHelp, EyeOff, Fingerprint, KeyRound, Landmark, LayoutDashboard, Link2, LoaderCircle, LockKeyhole, LogOut, Moon, ShieldCheck, Sun, Wallet, WifiOff } from 'lucide-react'
import { AuthController } from './auth'
import type { Screen } from './auth'

function Brand() { return <span className="ws-brand"><span><BarChart3 size={23} aria-hidden="true" /></span>Portfolio<b>.</b></span> }
function Submit({ busy, children }: { busy: boolean; children: ReactNode }) { return <button className="ws-primary" type="submit" disabled={busy}>{busy ? <><LoaderCircle size={18} className="ws-spin" aria-hidden="true" />Please wait…</> : <>{children}<ArrowRight size={18} aria-hidden="true" /></>}</button> }

function Login({ auth, busy }: { auth: AuthController; busy: boolean }) {
  return <form onSubmit={(event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = event.currentTarget, values = new FormData(form)
    void auth.login(String(values.get('email')), String(values.get('password')))
    form.reset()
  }}>
    <label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" maxLength={254} required disabled={busy} placeholder="you@example.com" />
    <label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" maxLength={1024} required disabled={busy} />
    <Submit busy={busy}>Continue securely</Submit>
  </form>
}

function MFA({ screen, auth, busy }: { screen: Extract<Screen, { kind: 'mfa' }>; auth: AuthController; busy: boolean }) {
  const [factor, setFactor] = useState(screen.pending.factors[0]!)
  return <>
    {screen.pending.setup_key && <div className="ws-setup"><strong>Add Portfolio to your authenticator</strong><p>Choose “Enter a setup key” in your authenticator app, select a time-based code, and enter this key. Keep the app open until verification completes.</p><label htmlFor="setup-key">Setup key · shown only during this step</label><input id="setup-key" readOnly value={screen.pending.setup_key} autoComplete="off" spellCheck={false} /><p>Do not share this key. If setup is interrupted and you lose the key, contact the operator.</p></div>}
    <form onSubmit={event => { event.preventDefault(); const form = event.currentTarget; void auth.verify(factor, String(new FormData(form).get('code'))); form.reset() }}>
      {screen.pending.factors.length > 1 && <><label htmlFor="factor">Authenticator</label><select id="factor" value={factor} onChange={event => setFactor(event.target.value)} disabled={busy}>{screen.pending.factors.map((id, i) => <option value={id} key={id}>Authenticator {i + 1}</option>)}</select><p className="ws-hint">Choose the authenticator you have access to. The other can be your backup.</p></>}
      <label htmlFor="code">6-digit authenticator code</label><input id="code" name="code" className="ws-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={busy} placeholder="000000" aria-describedby="code-help" />
      <p className="ws-hint" id="code-help">Paste is supported. An incorrect or expired code requires a fresh sign-in.</p>
      <Submit busy={busy}>Verify authenticator</Submit>
    </form>
    <button className="ws-text" disabled={busy} onClick={() => void auth.logout()}>Cancel and sign out</button>
  </>
}

function Recovery({ screen, auth, busy }: { screen: Extract<Screen, { kind: 'recovery' }>; auth: AuthController; busy: boolean }) {
  return <form key={String(screen.sent)} onSubmit={event => {
    event.preventDefault()
    const form = event.currentTarget, values = new FormData(form)
    if (screen.sent) void auth.verifyRecovery(String(values.get('email')), String(values.get('code')))
    else void auth.requestRecovery(String(values.get('email')))
    form.reset()
  }}>
    <label htmlFor="recovery-email">Account email</label><input id="recovery-email" name="email" type="email" autoComplete="username" maxLength={254} required disabled={busy} />
    {screen.sent && <><label htmlFor="recovery-code">Code from your email</label><input id="recovery-code" name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,10}" minLength={6} maxLength={10} required disabled={busy} /></>}
    <Submit busy={busy}>{screen.sent ? 'Verify email code' : 'Send recovery code'}</Submit>
    <p className="ws-hint">Email access and an existing authenticator are both required. If every authenticator is lost, contact the operator; recovery cannot bypass MFA.</p>
    <button type="button" className="ws-text" disabled={busy} onClick={() => auth.lock()}>Back to sign in</button>
  </form>
}

function Password({ auth, busy }: { auth: AuthController; busy: boolean }) {
  const [error, setError] = useState('')
  return <form onSubmit={event => {
    event.preventDefault()
    const form = event.currentTarget, values = new FormData(form)
    if (values.get('password') !== values.get('confirm')) { setError('The passwords do not match. Enter both again.'); form.reset(); form.querySelector('input')?.focus(); return }
    setError(''); void auth.password(String(values.get('password'))); form.reset()
  }}>
    {error && <p role="alert" className="ws-notice">{error}</p>}
    <label htmlFor="new-password">New password</label><input id="new-password" name="password" type="password" autoComplete="new-password" minLength={16} maxLength={128} required disabled={busy} aria-describedby="password-help" />
    <label htmlFor="confirm-password">Confirm new password</label><input id="confirm-password" name="confirm" type="password" autoComplete="new-password" minLength={16} maxLength={128} required disabled={busy} />
    <p className="ws-hint" id="password-help">Use 16–128 characters. Password managers and paste are supported. Changing it ends all workspace sessions.</p>
    <Submit busy={busy}>Change password</Submit>
    <button className="ws-text" type="button" disabled={busy} onClick={() => void auth.logout()}>Cancel and sign out</button>
  </form>
}

const problems = {
  offline: ['You’re offline.', 'Reconnect, then check your session to continue. Your workspace is hidden while offline.'],
  unavailable: ['Connection unavailable.', 'We couldn’t verify your session. Check your connection or contact the operator if this continues.'],
  forbidden: ['Request blocked.', 'This request could not be verified. Open the workspace at its configured address and try again.'],
  limited: ['A short pause.', 'Too many requests, or another tab is checking this session. Wait a moment before trying again.'],
  protocol: ['Unable to verify this response.', 'The workspace is locked. Try again, or contact the operator if this continues.'],
  signout: ['Sign-out is not confirmed.', 'This screen is locked, but the server could not confirm revocation. Reconnect and retry sign-out.'],
} as const

function Gate({ screen, auth, busy, recovery }: { screen: Exclude<Screen, { kind: 'workspace' }>; auth: AuthController; busy: boolean; recovery: boolean }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const [clock, setClock] = useState(Date.now())
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(timer) }, [])
  const title = screen.kind === 'checking' ? 'Checking your session.' : screen.kind === 'mfa' ? screen.pending.setup_key ? 'One more layer of security.' : 'Verify it’s you.' : screen.kind === 'recovery' ? 'Recover your access.' : screen.kind === 'password' ? 'Choose a new password.' : screen.kind === 'blocked' ? problems[screen.reason][0] : 'Welcome to your workspace.'
  const message = screen.kind === 'blocked' ? problems[screen.reason][1] : screen.kind === 'mfa' ? 'Use your authenticator to complete this step. Your workspace stays locked until verification succeeds.' : screen.kind === 'password' ? 'Your identity is verified for recovery. Set a new password, then sign in again.' : screen.kind === 'recovery' ? screen.message ?? 'Start with your account email. Recovery does not grant workspace access.' : screen.kind === 'login' ? screen.message ?? 'Sign in with your account, then verify your authenticator.' : 'Verifying access before opening anything private.'
  useEffect(() => { heading.current?.focus() }, [screen.kind, message])
  return <main id="main" className="ws-gate">
    <section className="ws-story" aria-label="About your workspace"><span className="ws-eyebrow">A private perspective</span><h2>Your finances.<br />Your space.<br /><em>Your peace of mind.</em></h2><p>A considered home for your financial picture, across accounts and markets.</p>
      <div className="ws-orbit" aria-hidden="true"><div><LockKeyhole size={35} /></div><span className="ws-orbit-one"><Landmark size={24} /></span><span className="ws-orbit-two"><BarChart3 size={24} /></span><span className="ws-orbit-three"><Wallet size={23} /></span></div>
      <div className="ws-story-foot"><ShieldCheck size={18} aria-hidden="true" /><span>Private access. An extra layer of verification.</span></div>
    </section>
    <section className="ws-auth" aria-labelledby="auth-heading"><div className="ws-auth-icon">{screen.kind === 'checking' ? <LoaderCircle className="ws-spin" aria-hidden="true" /> : screen.kind === 'blocked' && screen.reason === 'offline' ? <WifiOff aria-hidden="true" /> : screen.kind === 'mfa' ? <Fingerprint aria-hidden="true" /> : <KeyRound aria-hidden="true" />}</div><span className="ws-eyebrow">{screen.kind === 'mfa' ? 'Authenticator verification' : 'Personal access'}</span><h1 id="auth-heading" ref={heading} tabIndex={-1}>{title}</h1><p className="ws-intro" role={screen.kind === 'blocked' ? 'alert' : 'status'}>{message}</p>
      {screen.kind === 'login' && <><Login auth={auth} busy={busy} />{recovery ? <button className="ws-text" disabled={busy} onClick={auth.recovery}>Forgot your password?</button> : <p className="ws-hint">Need help signing in? Email recovery is not enabled. Contact the operator for assistance.</p>}<div className="ws-restricted"><LockKeyhole size={15} aria-hidden="true" /><span>Access is limited to the configured account. Public registration is closed.</span></div></>}
      {screen.kind === 'mfa' && <MFA screen={screen} auth={auth} busy={busy} />}
      {screen.kind === 'recovery' && <Recovery screen={screen} auth={auth} busy={busy} />}
      {screen.kind === 'password' && <Password auth={auth} busy={busy} />}
      {screen.kind === 'blocked' && <button className="ws-primary" disabled={busy || (screen.retryAt !== undefined && clock < screen.retryAt)} onClick={() => void (screen.reason === 'signout' ? auth.retryLogout() : auth.bootstrap())}>{screen.reason === 'signout' ? 'Retry sign-out' : 'Check again'}<ArrowRight size={18} aria-hidden="true" /></button>}
    </section>
  </main>
}

function EmptyWorkspace({ auth, screen, busy }: { auth: AuthController; screen: Extract<Screen, { kind: 'workspace' }>; busy: boolean }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const [confirm, setConfirm] = useState(false)
  const [remaining, setRemaining] = useState(0)
  useEffect(() => { heading.current?.focus() }, [])
  useEffect(() => {
    const update = () => setRemaining(Math.max(0, Math.ceil((screen.deadline - performance.now()) / 60_000)))
    update(); const timer = setInterval(update, 1000); return () => clearInterval(timer)
  }, [screen.deadline])
  return <div className="ws-layout"><aside className="ws-sidebar"><span className="ws-eyebrow">Workspace</span><nav aria-label="Workspace navigation"><a href="#main" aria-current="page"><LayoutDashboard size={18} aria-hidden="true" />Overview<ChevronRight size={15} aria-hidden="true" /></a>{[[BarChart3, 'Investments'], [Landmark, 'Banking'], [Wallet, 'Budgets'], [Link2, 'Connections']].map(([Icon, name]) => { const Symbol = Icon as typeof BarChart3; return <span className="ws-planned" key={String(name)}><Symbol size={18} aria-hidden="true" />{String(name)}<small>Later</small></span> })}</nav><div className="ws-sidebar-note"><ShieldCheck size={25} aria-hidden="true" /><strong>A quieter kind of clarity.</strong><p>Your workspace is private.<br />You’re in control of access.</p></div></aside>
    <main id="main" className="ws-home"><div className="ws-home-heading"><div><span className="ws-eyebrow">Your personal workspace</span><h1 ref={heading} tabIndex={-1}>A fresh start.</h1><p>One place for your financial picture, as it takes shape.</p></div><span className="ws-pill"><ShieldCheck size={15} aria-hidden="true" />Session verified</span></div>
      <section className="ws-empty" aria-labelledby="empty-heading"><div className="ws-empty-art" aria-hidden="true"><Landmark size={30} /><span><Check size={16} /></span></div><span className="ws-eyebrow">Room for the bigger picture</span><h2 id="empty-heading">Your workspace is ready.<br />Your financial picture comes next.</h2><p>Account connections and imports are not available here yet. This workspace doesn’t load financial records, balances, or sample data.</p><div className="ws-empty-bottom"><EyeOff size={16} aria-hidden="true" /><span>Amounts stay private by default.</span></div></section>
      <div className="ws-home-grid"><section className="ws-card" aria-labelledby="session-heading"><div className="ws-card-title"><ShieldCheck size={21} aria-hidden="true" /><h2 id="session-heading">Your session</h2></div><p>You’re signed in with an authenticator. The server checks access while this workspace is open.</p><div className="ws-session-detail"><span>Idle time remaining</span><strong>{remaining} min</strong></div>{remaining <= 1 && <p role="status" className="ws-notice">Your session is about to expire. Continue to keep it active.</p>}<button className="ws-secondary" disabled={busy} onClick={() => void auth.activity()}>Keep session active<ArrowRight size={16} aria-hidden="true" /></button><p className="ws-hint">Automatic checks don’t extend your session.</p></section>
      <section className="ws-card" aria-labelledby="access-heading"><div className="ws-card-title"><KeyRound size={21} aria-hidden="true" /><h2 id="access-heading">Manage access</h2></div><p>Sign out when you’re finished. If you’re using a shared device, end all workspace sessions.</p><button className="ws-secondary" onClick={() => void auth.logout()}><LogOut size={16} aria-hidden="true" />Sign out here</button>{confirm ? <div className="ws-confirm"><p role="status">Sign out every workspace session, including this one?</p><button className="ws-secondary" onClick={() => void auth.logout(true)}>Sign out everywhere</button><button className="ws-text" onClick={() => setConfirm(false)}>Cancel</button></div> : <button className="ws-text" disabled={busy} onClick={() => setConfirm(true)}>End all sessions</button>}</section></div>
      <p className="ws-footnote"><CircleHelp size={15} aria-hidden="true" />Financial features will appear as they become available.</p>
    </main></div>
}

export default function Workspace({ controller }: { controller?: AuthController }) {
  const [auth] = useState(() => controller ?? new AuthController())
  const state = useSyncExternalStore(auth.subscribe, auth.snapshot)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => auth.start(), [auth])
  useEffect(() => {
    const visibility = () => {
      if (document.visibilityState === 'hidden' && auth.snapshot().screen.kind === 'workspace') auth.suspend()
      else if (document.visibilityState === 'visible') auth.resume()
    }
    window.addEventListener('offline', auth.offline)
    window.addEventListener('pagehide', auth.suspend)
    window.addEventListener('pageshow', auth.resume)
    document.addEventListener('visibilitychange', visibility)
    return () => { window.removeEventListener('offline', auth.offline); window.removeEventListener('pagehide', auth.suspend); window.removeEventListener('pageshow', auth.resume); document.removeEventListener('visibilitychange', visibility) }
  }, [auth])
  return <div className="workspace"><a className="skip-link" href="#main">Skip to content</a><header className="ws-header"><Brand /><div><span className="ws-header-label"><LockKeyhole size={14} aria-hidden="true" />Private workspace</span><button className="ws-theme" aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon size={19} aria-hidden="true" /> : <Sun size={19} aria-hidden="true" />}</button></div></header>
    {state.screen.kind === 'workspace' ? <EmptyWorkspace auth={auth} screen={state.screen} busy={state.busy} /> : <Gate auth={auth} screen={state.screen} busy={state.busy} recovery={state.recovery} />}
    <footer className="ws-footer"><span>Portfolio · Personal finance, thoughtfully.</span><span><ShieldCheck size={13} aria-hidden="true" />Private by design</span></footer>
  </div>
}
