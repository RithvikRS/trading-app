import { accounts, FX_DATE } from './portfolio'
import { getHoldings } from './holdings'
import { getBankSnapshots } from './banking'
import { bankCoverage } from './cashFlow'

export const sourceIds = ['ind-in', 'ind-us', 'advisor', 'ubs', 'hdfc', 'sbi'] as const
export type SourceId = typeof sourceIds[number]
export type ConnectorId = 'ind-in' | 'ind-us'
export const isSourceId = (value: string): value is SourceId => sourceIds.some(id => id === value)
export const isConnectorId = (value: string): value is ConnectorId => value === 'ind-in' || value === 'ind-us'
export const sourceNames: Record<SourceId, string> = { 'ind-in': 'INDmoney India', 'ind-us': 'INDmoney US', advisor: 'Advisor mutual funds', ubs: 'UBS Accenture ESPP', hdfc: 'HDFC Bank', sbi: 'SBI' }

export function sourceDate(value: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Kolkata' }).format(new Date(value)) + ' IST'
}
export function sourceDay(value: string) {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`))
}
export interface SourceStream { name: string; status: string; date: string; note: string }
export interface SourceCoverage {
  id: SourceId; name: string; account: string; mode: 'connector' | 'statement'; bank: boolean
  attention: boolean; summary: string; asOf: string; period: string; streams: SourceStream[]
}

// Coverage is derived from financial fixtures, never from a simulated attempt or receipt.
export function getSourceCoverage(partial = false): SourceCoverage[] {
  const holdings = getHoldings(partial)
  return sourceIds.map(id => {
    const account = accounts.find(item => item.id === id)!
    const common = { id, name: sourceNames[id], account: `Sample ${account.description}`, mode: isConnectorId(id) ? 'connector' as const : 'statement' as const }
    if (id === 'hdfc' || id === 'sbi') {
      const snapshots = getBankSnapshots(partial, null).filter(item => item.accountId === id)
      const latest = snapshots[snapshots.length - 1]!
      return { ...common, bank: true, attention: !latest.complete, summary: latest.complete ? 'Full months + month to date' : 'October activity incomplete', asOf: sourceDate(latest.balanceDate), period: '1 Aug–20 Oct 2026 · October ends at 10:00 IST', streams: [
        { name: 'Bank balance', status: 'Snapshot supplied', date: sourceDate(latest.balanceDate), note: 'Separately dated closing balance. Activity gaps do not remove this snapshot.' },
        ...snapshots.map(snapshot => ({ name: `${sourceDay(snapshot.from).split(' ').slice(1).join(' ')} activity`, status: !snapshot.complete ? 'Partial / stale' : snapshot.from.startsWith('2026-10') ? 'Month to date' : 'Full month', date: sourceDate(snapshot.activityDate), note: `${sourceDay(snapshot.from)} – ${sourceDay(snapshot.to)}. ${!snapshot.complete ? bankCoverage(partial).filter(item => item.accountId === id && !item.complete).map(item => `${sourceDay(item.from)} – ${sourceDay(item.to)}: ${item.reason}.`).join(' ') : 'Supplied statement interval.'}` })),
        { name: 'Later activity', status: 'Never supplied', date: 'After 20 Oct 2026, 10:00 IST', note: 'The rest of October is not included. No later spending or balance can be inferred.' },
        { name: 'Prices / NAV', status: 'Not applicable', date: '—', note: 'Bank cash does not use a market quote.' },
        { name: 'Display FX', status: 'Bundled rate', date: FX_DATE, note: 'Display conversion only; native statement reconciliation remains in INR.' },
      ] }
    }
    const positions = holdings.filter(item => item.accountId === id)
    const missing = positions.some(item => !item.quote), stale = positions.some(item => item.stale)
    const dates = [...new Set(positions.flatMap(item => item.quote ? [sourceDate(item.quote.date)] : []))]
    return { ...common, bank: false, attention: missing || stale, summary: missing ? 'NAV missing' : stale ? 'Holdings snapshot stale' : 'Snapshot + selected activity', asOf: sourceDate(positions[0]!.holdingsDate), period: 'No complete investment statement period supplied', streams: [
      { name: 'Holdings', status: stale ? 'Stale snapshot' : 'Snapshot supplied', date: sourceDate(positions[0]!.holdingsDate), note: 'A position snapshot does not establish complete trade history.' },
      { name: id === 'advisor' ? 'NAV' : 'Prices / NAV', status: missing ? 'Missing stream' : 'Quotes supplied', date: dates.join(' · ') || '20 Oct 2026 NAV unavailable', note: missing ? 'The regular-plan fund has no supplied NAV. It is excluded from valued totals.' : 'Bundled illustrative quotes, separately dated from holdings. No market-data service is connected.' },
      { name: 'Investment activity', status: 'Selected examples', date: 'Individual record dates', note: 'Purchases and distributions are illustrative events, not a reconciled or complete activity period.' },
      { name: 'Broker cash', status: isConnectorId(id) ? 'Snapshot supplied' : 'Never supplied', date: isConnectorId(id) ? 'No independent cash timestamp supplied' : '—', note: isConnectorId(id) ? 'Included once in Overview. The holdings timestamp does not establish cash freshness.' : 'No separate cash balance is supplied for this account; absence is not a zero balance.' },
      ...(id === 'ubs' ? [{ name: 'Employee lots', status: 'Selected examples', date: '15 Nov 2025 – 15 Aug 2026', note: 'Remaining sample lot units match the position. Complete tax basis, fees, and corporate-action history are not supplied.' }] : []),
      { name: 'Display FX', status: 'Bundled rate', date: FX_DATE, note: 'Display conversion only; not acquisition FX or tax basis.' },
    ] }
  })
}

export const scenarios = {
  available: 'Available snapshot', never: 'Never received', partial: 'Stale / partial success',
  transient: 'Transient failure', limited: 'Rate limited', expired: 'Expired access', revoked: 'Revoked access',
} as const
export type Scenario = keyof typeof scenarios
export const isScenario = (value: string): value is Scenario => Object.hasOwn(scenarios, value)
export type Outcome = 'not-started' | 'received' | 'partial' | 'failed' | 'rate-limited' | 'blocked' | 'running' | 'cancelled'
export const outcomeLabels: Record<Outcome, string> = { 'not-started': 'Not attempted', received: 'Sample received', partial: 'Partial sample received', failed: 'Transient failure', 'rate-limited': 'Rate limited', blocked: 'Access blocked', running: 'In progress · Simulation', cancelled: 'Sample attempt cancelled' }
export const INITIAL_ATTEMPT = '20 Oct 2026, 19:00 IST'
export const PREVIOUS_RECEIPT = '20 Oct 2026, 18:45 IST'
export const NEXT_ATTEMPT = '20 Oct 2026, 19:05 IST'
export const NEXT_RECEIPT = '20 Oct 2026, 19:06 IST'
export interface Attempt { at: string; outcome: Outcome }
export interface ConnectionSimulation {
  scenario: Scenario; authorization: 'illustrative' | 'expired' | 'revoked'; outcome: Outcome
  receipt: string | null; attempt: string | null; retryWindow: boolean; finished: boolean; history: Attempt[]
}
export interface ConnectionState { sources: Record<ConnectorId, ConnectionSimulation>; message: string }
export function createSimulation(scenario: Scenario): ConnectionSimulation {
  const outcome: Outcome = scenario === 'never' ? 'not-started' : scenario === 'partial' ? 'partial' : scenario === 'transient' ? 'failed' : scenario === 'limited' ? 'rate-limited' : scenario === 'expired' || scenario === 'revoked' ? 'blocked' : 'received'
  return { scenario, authorization: scenario === 'expired' || scenario === 'revoked' ? scenario : 'illustrative', outcome, receipt: scenario === 'never' ? null : scenario === 'available' || scenario === 'partial' ? INITIAL_ATTEMPT : PREVIOUS_RECEIPT, attempt: scenario === 'never' ? null : INITIAL_ATTEMPT, retryWindow: false, finished: false, history: scenario === 'never' ? [] : [{ at: INITIAL_ATTEMPT, outcome }] }
}
export function createConnectionState(): ConnectionState {
  return { sources: { 'ind-in': createSimulation('available'), 'ind-us': createSimulation('transient') }, message: '' }
}
export type ConnectionAction = { type: 'reset' } | { type: 'pause' } | { type: 'scenario'; id: string; scenario: string } | { type: 'run' | 'finish' | 'renew' | 'window' | 'cancel'; id: string }
export function canRunSample(value: ConnectionSimulation) {
  return !value.finished && value.outcome !== 'running' && value.authorization === 'illustrative' && (value.scenario !== 'limited' || value.retryWindow)
}
export function changeConnections(state: ConnectionState, action: ConnectionAction): ConnectionState {
  if (action.type === 'reset') return { ...createConnectionState(), message: 'Sample connection states reset. Financial records and other reviews are unchanged.' }
  if (action.type === 'pause') {
    const sources = { ...state.sources }
    let cancelled = false
    for (const id of ['ind-in', 'ind-us'] as const) if (sources[id].outcome === 'running') {
      cancelled = true
      sources[id] = { ...sources[id], outcome: 'cancelled', history: [...sources[id].history, { at: NEXT_ATTEMPT, outcome: 'cancelled' as const }].slice(-3) }
    }
    return cancelled ? { sources, message: 'In-progress sample attempts cancelled. Retained receipts and financial dates are unchanged.' } : state
  }
  if (!isConnectorId(action.id)) return state
  const current = state.sources[action.id]
  let next = current, message = ''
  if (action.type === 'scenario') {
    if (!isScenario(action.scenario) || current.outcome === 'running') return state
    next = createSimulation(action.scenario)
    message = `${sourceNames[action.id]}: ${scenarios[action.scenario]} example loaded. Financial coverage is unchanged.`
  } else if (action.type === 'renew') {
    if (current.authorization === 'illustrative' || current.outcome === 'running') return state
    next = { ...current, authorization: 'illustrative' }
    message = 'Illustrative access renewed locally. Run a sample attempt to see its outcome; no provider access was granted.'
  } else if (action.type === 'window') {
    if (current.scenario !== 'limited' || current.retryWindow || current.finished || current.outcome === 'running') return state
    next = { ...current, retryWindow: true }
    message = 'Supplied retry window reached in this simulation. Retry is now available; no timer or scheduled request is running.'
  } else if (action.type === 'run') {
    if (!canRunSample(current)) return state
    next = { ...current, outcome: 'running', attempt: NEXT_ATTEMPT }
    message = 'Sample attempt in progress. Choose Show sample outcome to advance this local walkthrough. No request is running.'
  } else if (action.type === 'cancel') {
    if (current.outcome !== 'running') return state
    next = { ...current, outcome: 'cancelled', history: [...current.history, { at: NEXT_ATTEMPT, outcome: 'cancelled' as const }].slice(-3) }
    message = 'Sample attempt cancelled. Retained receipts and financial dates are unchanged.'
  } else if (action.type === 'finish') {
    if (current.outcome !== 'running' || current.authorization !== 'illustrative') return state
    const outcome = current.scenario === 'partial' ? 'partial' as const : 'received' as const
    next = { ...current, outcome, receipt: NEXT_RECEIPT, finished: true, history: [...current.history, { at: NEXT_ATTEMPT, outcome }].slice(-3) }
    message = 'Sample outcome shown. Receipt time changed only inside this walkthrough; financial dates and records are unchanged.'
  }
  return next === current ? state : { sources: { ...state.sources, [action.id]: next }, message }
}

export interface ConnectionControls { query: string; filter: 'all' | 'investment' | 'bank'; selected: SourceId | null }
export const initialConnectionControls: ConnectionControls = { query: '', filter: 'all', selected: null }
export function selectSources(sources: readonly SourceCoverage[], controls: ConnectionControls) {
  const query = controls.query.slice(0, 80).trim().toLocaleLowerCase('en-US')
  return sources.filter(source => (controls.filter === 'all' || source.bank === (controls.filter === 'bank')) && `${source.name} ${source.account}`.toLocaleLowerCase('en-US').includes(query))
}
