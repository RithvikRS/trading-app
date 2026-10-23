// Only opaque cookies cross the session boundary. This module has no storage adapter.
export type Session = { status: 'authenticated'; expires_at: string; idle_expires_at: string; fresh_until: string; factors: string[]; unverified_factors: string[] }
export type Pending = { status: 'mfa_required'; factors: string[]; setup_key?: string }
export type Screen =
  | { kind: 'checking' }
  | { kind: 'login'; message?: string }
  | { kind: 'mfa'; pending: Pending; deadline: number }
  | { kind: 'recovery'; sent: boolean; message?: string }
  | { kind: 'password'; deadline: number }
  | { kind: 'workspace'; session: Session; deadline: number }
  | { kind: 'blocked'; reason: 'offline' | 'unavailable' | 'forbidden' | 'limited' | 'protocol' | 'signout'; retryAt?: number }

export type State = { screen: Screen; busy: boolean; recovery: boolean }
type Json = Record<string, unknown>
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const ids = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 2 && value.every(id => typeof id === 'string' && uuid.test(id)) && new Set(value).size === value.length
const record = (value: unknown): value is Json => !!value && typeof value === 'object' && !Array.isArray(value)
const exact = (value: Json, keys: string[]) => Object.keys(value).every(key => keys.includes(key))
const invalid = () => new AuthError('protocol')

export class AuthError extends Error {
  constructor(readonly reason: 'unauthorized' | 'offline' | 'unavailable' | 'forbidden' | 'limited' | 'protocol', readonly retryAt?: number) { super('Authentication request failed.') }
}

function csrf(): string {
  const name = location.protocol === 'https:' ? '__Host-portfolio-csrf' : 'trading_dev_csrf'
  const found = document.cookie.split(';').map(part => part.trim()).filter(part => part.startsWith(`${name}=`))
  if (found.length !== 1) throw new AuthError('forbidden')
  const value = found[0]!.slice(name.length + 1)
  if (!/^[A-Za-z0-9_.=-]{16,1024}$/.test(value)) throw new AuthError('forbidden')
  return value
}

async function request(path: string, signal: AbortSignal, body?: Json): Promise<{ data: Json; now: number }> {
  const started = performance.now()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (path !== '/bootstrap') headers['X-CSRFToken'] = csrf()
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch(`/api/v1/auth${path}`, {
      method: body === undefined ? 'GET' : 'POST', headers,
      credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store',
      referrerPolicy: 'no-referrer', signal, body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch { throw new AuthError(navigator.onLine === false ? 'offline' : 'unavailable') }
  if (!response.ok) {
    void response.body?.cancel()
    if (response.status === 401) throw new AuthError('unauthorized')
    if (response.status === 403) throw new AuthError('forbidden')
    if (response.status === 429) throw new AuthError('limited', Date.now() + 5_000)
    throw new AuthError('unavailable')
  }
  if (response.headers.get('content-type')?.split(';')[0] !== 'application/json' || response.headers.get('cache-control') !== 'no-store') throw invalid()
  // Stream a bounded body; never render server errors or unexpected response fields.
  const reader = response.body?.getReader()
  if (!reader) throw invalid()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.length
      if (size > 8192) throw invalid()
      chunks.push(value)
    }
  } finally { await reader.cancel() }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
  let data: unknown
  try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) } catch { throw invalid() }
  if (!record(data)) throw invalid()
  const server = Date.parse(response.headers.get('date') ?? '')
  if (!Number.isFinite(server)) throw invalid()
  // Include transport time and HTTP Date's one-second precision; expire conservatively.
  return { data, now: server + 1000 + performance.now() - started }
}

export function parseSession(data: Json, now: number): Session {
  if (!exact(data, ['status', 'expires_at', 'idle_expires_at', 'fresh_until', 'factors', 'unverified_factors']) || data.status !== 'authenticated' || !ids(data.factors) || !data.factors.length || !ids(data.unverified_factors)) throw invalid()
  for (const key of ['expires_at', 'idle_expires_at', 'fresh_until']) {
    if (typeof data[key] !== 'string' || !/^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|\+00:00)$/.test(data[key]) || !Number.isFinite(Date.parse(data[key]))) throw invalid()
  }
  const session = data as Session
  const remaining = Math.min(Date.parse(session.expires_at), Date.parse(session.idle_expires_at)) - now
  if (remaining <= 0 || remaining > 15 * 60_000 || Date.parse(session.expires_at) - now > 8 * 60 * 60_000) throw new AuthError('unauthorized')
  return session
}

function pending(data: Json): Pending {
  if (data.status !== 'mfa_required' || !exact(data, ['status', 'factors', 'setup_key']) || !ids(data.factors) || !data.factors.length || (data.setup_key !== undefined && (typeof data.setup_key !== 'string' || !/^[A-Z2-7]{16,128}$/.test(data.setup_key)))) throw invalid()
  return data as Pending
}

export class AuthController {
  private state: State = { screen: { kind: 'checking' }, busy: false, recovery: false }
  private listeners = new Set<() => void>()
  private generation = 0
  private controller?: AbortController
  private pendingDeadline = 0
  private timer?: ReturnType<typeof setInterval>
  private channel?: BroadcastChannel
  private signoutAll = false
  private lastCheck = 0
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  snapshot = () => this.state
  private set(screen: Screen, busy = false) { this.state = { ...this.state, screen, busy }; this.listeners.forEach(listener => listener()) }
  private cancel() { this.generation++; this.controller?.abort(); this.controller = undefined }
  private fail(error: unknown, message = 'Your session ended. Sign in again.') {
    const failure = error instanceof AuthError ? error : invalid()
    this.set(failure.reason === 'unauthorized' ? { kind: 'login', message } : { kind: 'blocked', reason: failure.reason, retryAt: failure.retryAt })
  }
  private async run(action: (signal: AbortSignal, current: () => boolean, latest: () => boolean) => Promise<void>) {
    if (this.state.busy) return
    const generation = ++this.generation
    const controller = new AbortController()
    this.controller = controller
    this.set(this.state.screen, true)
    const timeout = setTimeout(() => controller.abort(), 20_000)
    const latest = () => generation === this.generation
    const current = () => latest() && !controller.signal.aborted
    try { await action(controller.signal, current, latest) }
    catch (error) { if (generation === this.generation) this.fail(error) }
    finally {
      clearTimeout(timeout)
      if (generation === this.generation) { this.controller = undefined; this.set(this.state.screen) }
    }
  }
  private activate(data: Json, now: number) {
    const session = parseSession(data, now)
    this.lastCheck = performance.now()
    this.set({ kind: 'workspace', session, deadline: performance.now() + Math.min(Date.parse(session.expires_at), Date.parse(session.idle_expires_at)) - now })
  }
  start() {
    this.cancel()
    this.set({ kind: 'checking' })
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel('portfolio-session-events')
      this.channel.onmessage = event => { if (event.data === 'locked') this.lock('Your session changed in another tab. Sign in again.') }
    }
    this.timer = setInterval(() => {
      const screen = this.state.screen
      if ('deadline' in screen && performance.now() >= screen.deadline) void this.logout(false, 'Your session expired. Sign in again.')
      else if (screen.kind === 'workspace' && performance.now() - this.lastCheck >= 60_000 && document.visibilityState === 'visible') void this.check()
    }, 1000)
    void this.bootstrap()
    return () => { this.cancel(); clearInterval(this.timer); this.channel?.close(); this.set({ kind: 'checking' }) }
  }
  lock(message = 'Sign in to continue.') { this.cancel(); this.set({ kind: 'login', message }) }
  suspend = () => { this.cancel(); this.set({ kind: 'checking' }) }
  resume = () => { if (this.state.screen.kind === 'checking') void this.bootstrap() }
  offline = () => { this.cancel(); this.set({ kind: 'blocked', reason: 'offline' }) }
  bootstrap = async () => {
    if (this.state.busy) return
    this.set({ kind: 'checking' })
    await this.run(async (signal, current, latest) => {
      const { data } = await request('/bootstrap', signal)
      if (!current()) return
      if (data.status !== 'ready' || typeof data.recovery_email_enabled !== 'boolean' || !exact(data, ['status', 'recovery_email_enabled'])) throw invalid()
      this.state = { ...this.state, recovery: data.recovery_email_enabled }
      try {
        const result = await request('/session', signal)
        if (current()) this.activate(result.data, result.now)
      } catch (error) { if (latest()) this.fail(error, 'Sign in to your private workspace.') }
    })
  }
  login = (email: string, password: string) => {
    this.pendingDeadline = performance.now() + 5 * 60_000
    return this.run(async (signal, current) => {
      const { data } = await request('/login', signal, { email, password })
      if (current()) this.set({ kind: 'mfa', pending: pending(data), deadline: this.pendingDeadline })
    })
  }
  verify = (factor_id: string, code: string) => this.run(async (signal, current) => {
    const { data } = await request('/mfa/verify', signal, { factor_id, code })
    if (!current()) return
    if (data.status === 'password_required' && exact(data, ['status'])) this.set({ kind: 'password', deadline: this.pendingDeadline })
    else if (data.status === 'authenticated' && exact(data, ['status'])) {
      this.set({ kind: 'checking' }, true)
      const result = await request('/session', signal)
      if (current()) this.activate(result.data, result.now)
    } else throw invalid()
  })
  check = () => this.run(async (signal, current) => {
    const result = await request('/session', signal)
    if (current()) this.activate(result.data, result.now)
  })
  activity = () => this.run(async (signal, current) => {
    const result = await request('/session/activity', signal, {})
    if (current()) this.activate(result.data, result.now)
  })
  logout = async (all = false, message?: string) => {
    this.signoutAll = all
    this.cancel()
    this.set({ kind: 'checking' })
    this.channel?.postMessage('locked')
    await this.run(async (signal, current, latest) => {
      try {
        const { data } = await request(all ? '/revoke-all' : '/logout', signal, {})
        if (!current()) return
        if (data.status !== 'signed_out' || !['complete', 'unavailable'].includes(String(data.provider_cleanup)) || !exact(data, ['status', 'provider_cleanup'])) throw invalid()
        this.set({ kind: 'login', message: data.provider_cleanup === 'complete' ? message ?? 'Signed out. Your workspace is locked.' : 'Workspace signed out. Provider cleanup is unavailable; contact the operator if needed.' })
      } catch (error) {
        if (!latest()) return
        if (error instanceof AuthError && error.reason === 'unauthorized') this.set({ kind: 'login', message: message ?? 'This session is no longer active.' })
        else this.set({ kind: 'blocked', reason: 'signout' })
      }
    })
  }
  retryLogout = () => this.logout(this.signoutAll)
  recovery = () => { if (this.state.recovery && !this.state.busy) this.set({ kind: 'recovery', sent: false }) }
  requestRecovery = (email: string) => this.run(async (signal, current) => {
    const { data } = await request('/recovery/request', signal, { email })
    if (data.status !== 'recovery_requested' || !exact(data, ['status'])) throw invalid()
    if (current()) this.set({ kind: 'recovery', sent: true, message: 'If this address is eligible, a code has been sent. You will also need your authenticator.' })
  })
  verifyRecovery = (email: string, code: string) => {
    this.pendingDeadline = performance.now() + 5 * 60_000
    return this.run(async (signal, current) => {
      const { data } = await request('/recovery/verify', signal, { email, code })
      if (current()) this.set({ kind: 'mfa', pending: pending(data), deadline: this.pendingDeadline })
    })
  }
  password = (password: string) => this.run(async (signal, current) => {
    const { data } = await request('/recovery/password', signal, { password })
    if (data.status !== 'sign_in_required' || !exact(data, ['status'])) throw invalid()
    if (current()) { this.channel?.postMessage('locked'); this.set({ kind: 'login', message: 'Password changed and sessions revoked. Sign in with your new password.' }) }
  })
}
