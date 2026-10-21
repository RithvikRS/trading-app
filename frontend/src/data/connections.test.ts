import { describe, expect, it } from 'vitest'
import { canRunSample, changeConnections, createConnectionState, getSourceCoverage, initialConnectionControls, isScenario, scenarios, selectSources } from './connections'
import type { ConnectionAction, ConnectionState } from './connections'
import { bankReconciliation, getBankSnapshots, getBankTransactions } from './banking'
import { getHoldings } from './holdings'
import { getPositions, getSummary } from './portfolio'
import { budgetOverview, changeBudgets, createBudgetState } from './budgets'
import { bankCoverage, cashFlow } from './cashFlow'
import { changeTransfers, createTransferState } from './transfers'
import { previewCategories } from './categories'
import { changeRecurring, createRecurringState, recurringEvidence, recurringOverview, recurringPatterns } from './recurring'

const act = (state: ConnectionState, action: ConnectionAction) => changeConnections(state, action)
const scenario = (name: string) => act(createConnectionState(), { type: 'scenario', id: 'ind-in', scenario: name })
const run = (state: ConnectionState) => act(state, { type: 'run', id: 'ind-in' })
const finish = (state: ConnectionState) => act(state, { type: 'finish', id: 'ind-in' })

describe('source coverage and bounded connection walkthroughs', () => {
  it('derives all six sources and keeps bank balance, activity and market dates separate', () => {
    const full = getSourceCoverage(), partial = getSourceCoverage(true)
    expect(full.map(source => source.id)).toEqual(['ind-in', 'ind-us', 'advisor', 'ubs', 'hdfc', 'sbi'])
    expect(full.filter(source => source.mode === 'statement').map(source => source.id)).toEqual(['advisor', 'ubs', 'hdfc', 'sbi'])
    expect(partial.filter(source => source.attention).map(source => source.id)).toEqual(['advisor', 'ubs', 'sbi'])
    const sbi = partial.find(source => source.id === 'sbi')!
    expect(sbi.asOf).toBe('20 Oct 2026, 10:00 IST')
    expect(sbi.streams.find(stream => stream.name === 'Oct 2026 activity')?.date).toBe('19 Oct 2026, 10:00 IST')
    expect(sbi.streams.filter(stream => stream.status === 'Full month')).toHaveLength(2)
    expect(sbi.streams.find(stream => stream.status === 'Partial / stale')?.note).toContain('19 Oct 2026 – 20 Oct 2026: Missing bill')
    expect(full.find(source => source.id === 'sbi')?.streams.find(stream => stream.name === 'Oct 2026 activity')?.status).toBe('Month to date')
    expect(partial.find(source => source.id === 'ubs')?.asOf).toBe('17 Oct 2026, 09:00 IST')
    expect(partial.find(source => source.id === 'ubs')?.streams.find(stream => stream.name === 'Prices / NAV')?.date).toBe('20 Oct 2026, 01:30 IST')
    expect(partial.find(source => source.id === 'advisor')?.streams.find(stream => stream.name === 'NAV')?.status).toBe('Missing stream')
    expect(full.find(source => source.id === 'ind-in')?.streams.find(stream => stream.name === 'Broker cash')?.date).toContain('No independent cash timestamp')
  })
  it('keeps a never-received scenario distinct from available bundled financial data', () => {
    const state = scenario('never')
    expect(state.sources['ind-in'].receipt).toBeNull(); expect(state.sources['ind-in'].attempt).toBeNull()
    expect(state.sources['ind-in'].history).toEqual([])
    expect(getSourceCoverage()[0]?.asOf).toBe('20 Oct 2026, 17:30 IST')
    expect(finish(run(state)).sources['ind-in'].receipt).toBe('20 Oct 2026, 19:06 IST')
  })
  it.each(['expired', 'revoked'])('blocks %s access until explicit renewal and preserves previous receipt', name => {
    let state = scenario(name), before = structuredClone(state)
    expect(canRunSample(state.sources['ind-in'])).toBe(false)
    expect(run(state)).toBe(state); expect(finish(state)).toBe(state)
    state = act(state, { type: 'renew', id: 'ind-in' })
    expect(state.sources['ind-in'].outcome).toBe('blocked')
    expect(state.sources['ind-in'].receipt).toBe(before.sources['ind-in'].receipt)
    expect(canRunSample(state.sources['ind-in'])).toBe(true)
    state = finish(run(state)); expect(state.sources['ind-in'].outcome).toBe('received')
    expect(before.sources['ind-in'].authorization).toBe(name)
  })
  it('blocks rate-limited retries until the supplied window is explicitly simulated', () => {
    let state = scenario('limited')
    expect(run(state)).toBe(state)
    expect(act(state, { type: 'renew', id: 'ind-in' })).toBe(state)
    state = act(state, { type: 'window', id: 'ind-in' }); expect(state.sources['ind-in'].receipt).toBe('20 Oct 2026, 18:45 IST')
    expect(finish(run(state)).sources['ind-in'].outcome).toBe('received')
    expect(act(scenario('available'), { type: 'window', id: 'ind-in' }).sources['ind-in'].retryWindow).toBe(false)
  })
  it.each(['available', 'transient', 'partial'])('makes %s attempts deterministic, non-overlapping and bounded', name => {
    const initial = scenario(name), before = structuredClone(initial)
    const running = run(initial)
    expect(running.sources['ind-in'].outcome).toBe('running')
    expect(running.sources['ind-in'].receipt).toBe(initial.sources['ind-in'].receipt)
    expect(run(running)).toBe(running)
    expect(act(running, { type: 'scenario', id: 'ind-in', scenario: 'never' })).toBe(running)
    const done = finish(running)
    expect(done.sources['ind-in'].outcome).toBe(name === 'partial' ? 'partial' : 'received')
    expect(done.sources['ind-in'].history).toHaveLength(2)
    expect(finish(done)).toBe(done); expect(run(done)).toBe(done)
    expect(initial).toEqual(before); expect(done.sources['ind-us']).toBe(initial.sources['ind-us'])
  })
  it('cancels one attempt independently, cancels all for loading, bounds history, and rejects late completion', () => {
    let state = run(createConnectionState())
    state = act(state, { type: 'run', id: 'ind-us' })
    state = act(state, { type: 'cancel', id: 'ind-in' })
    expect(state.sources['ind-us'].outcome).toBe('running'); expect(finish(state)).toBe(state)
    state = act(state, { type: 'pause' }); expect(state.sources['ind-us'].outcome).toBe('cancelled')
    for (let index = 0; index < 10; index++) state = act(run(state), { type: 'cancel', id: 'ind-in' })
    expect(state.sources['ind-in'].history).toHaveLength(3)
    expect(state.sources['ind-in'].receipt).toBe('20 Oct 2026, 19:00 IST')
    expect(finish(run(state)).sources['ind-in'].finished).toBe(true)
  })
  it('rejects unknown identifiers and scenarios and never creates authorization for statement sources', () => {
    const state = createConnectionState()
    for (const id of ['hdfc', 'sbi', 'ubs', 'advisor', '__proto__', '../x']) {
      for (const type of ['run', 'finish', 'renew', 'window', 'cancel'] as const) expect(act(state, { type, id })).toBe(state)
      expect(act(state, { type: 'scenario', id, scenario: 'available' })).toBe(state)
    }
    for (const value of ['constructor', '__proto__', '<script>', 'AVAILABLE']) {
      expect(isScenario(value)).toBe(false)
      expect(act(state, { type: 'scenario', id: 'ind-in', scenario: value })).toBe(state)
    }
    expect(selectSources(getSourceCoverage(), { ...initialConnectionControls, query: '<img src=x>' })).toEqual([])
    expect(selectSources(getSourceCoverage(), { ...initialConnectionControls, filter: 'bank' }).map(source => source.id)).toEqual(['hdfc', 'sbi'])
  })
  it.each([false, true])('preserves financial and review invariants across every scenario, partial=%s', partial => {
    const records = getBankTransactions(partial, null)
    let review = createTransferState()
    review = changeTransfers(review, { type: 'categorize', preview: previewCategories(['t14'], 'shopping', records, review) }, records)
    const budgets = changeBudgets(createBudgetState(), { type: 'set', category: 'health', decimal: '3000' })
    const pattern = recurringPatterns.find(item => item.id === 'service-fee')!
    const recurring = changeRecurring(createRecurringState(), { type: 'confirm', id: pattern.id, evidence: recurringEvidence(pattern, records, review).key }, records, review)
    const snapshot = () => ({ holdings: getHoldings(partial), assets: getSummary(getPositions(partial)), banks: getBankSnapshots(partial, null).map(source => bankReconciliation(source, records)), budget: budgetOverview(budgets, records, review, partial), cash: cashFlow(records, review, '2026-10-01', '2026-10-20'), recurring: recurringOverview(records, review, recurring, '2026-10', bankCoverage(partial)), coverage: getSourceCoverage(partial), review, budgets })
    const before = structuredClone(snapshot())
    expect(before.assets.total.minor).toBe(partial ? 466108000n : 508608000n)
    expect(before.banks).toHaveLength(6)
    for (const name of Object.keys(scenarios)) {
      let state = scenario(name)
      state = act(state, { type: 'renew', id: 'ind-in' }); state = act(state, { type: 'window', id: 'ind-in' })
      state = finish(run(state)); act(state, { type: 'reset' })
      expect(snapshot()).toEqual(before)
    }
  })
})
