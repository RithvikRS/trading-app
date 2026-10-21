import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import { getHoldings } from './data/holdings'
import { getEmployeeLots, getHoldingActivity } from './data/holdingRecords'
import { getBankTransactions } from './data/banking'
import { formatMoney } from './data/money'
import type { Currency } from './data/money'

function open(route: string) { window.history.replaceState(null, '', `/#/${route}`); return render(<App />) }
function currency(value: Currency) { fireEvent.change(screen.getByLabelText('Display currency'), { target: { value } }) }
function primaryAmounts(root: ParentNode) { return [...root.querySelectorAll('.amount')].filter(node => !node.closest('.original-value')) }
function expectCurrency(nodes: Element[], value: Currency) {
  expect(nodes.length).toBeGreaterThan(0)
  for (const node of nodes) expect(node.textContent).toMatch(value === 'USD' ? /^-?\$/ : /^-?₹/)
}

describe('workspace reporting currency', () => {
  it('updates Overview summaries, chart, allocation, every expanded account and recent activity in both directions', async () => {
    const user = userEvent.setup()
    const { container } = open('overview')
    for (const button of container.querySelectorAll<HTMLButtonElement>('.account-row')) fireEvent.click(button)
    await user.click(screen.getByRole('button', { name: 'View data' }))
    for (const selected of ['USD', 'INR'] as const) {
      currency(selected)
      expectCurrency(primaryAmounts(container), selected)
      expect(screen.getByRole('slider').getAttribute('aria-valuetext')).toContain(selected === 'USD' ? '$60,911.14' : '₹50,86,080')
      expect(screen.getByRole('columnheader', { name: `Tracked assets (${selected})` })).toBeTruthy()
      expect([...container.querySelectorAll('.account-row')].every(node => node.getAttribute('aria-expanded') === 'true')).toBe(true)
    }
    expect(container.querySelector('.account-detail .original-value')?.textContent).toContain('Original USD')
  })

  it('updates every holding quote and value, keeping row order and the source-currency filter unchanged', async () => {
    const user = userEvent.setup()
    const { container } = open('investments')
    const order = () => [...container.querySelectorAll('.holding-detail-link')].map(node => node.id)
    const initialOrder = order()
    for (const selected of ['USD', 'INR'] as const) {
      currency(selected)
      expectCurrency(primaryAmounts(container), selected)
      expectCurrency([...container.querySelectorAll('.holding-quote-cell .holding-number')], selected)
      expect(order()).toEqual(initialOrder)
    }
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Native currency'), 'INR')
    const filteredOrder = order()
    currency('USD')
    expect(order()).toEqual(filteredOrder)
    expect((screen.getByLabelText('Native currency') as HTMLSelectElement).value).toBe('INR')
    expectCurrency([...container.querySelectorAll('.holding-quote-cell .holding-number')], 'USD')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'partial')
    expect(screen.getByLabelText('Price unavailable').textContent).toBe('—')
    expect(screen.getByLabelText('Value unavailable').textContent).toBe('—')
  })

  it('updates position quotes, every supplied activity and all employee lots without altering source records', () => {
    const holdings = getHoldings()
    const lots = getEmployeeLots('h14')
    for (const holding of holdings) {
      const view = open(`investments/${holding.id}`)
      for (const selected of ['USD', 'INR'] as const) {
        currency(selected)
        const position = screen.getByRole('region', { name: 'Current position' })
        expect(position.querySelector('.hero-amount')?.textContent).toBe(formatMoney(holding.value!, selected))
        expectCurrency([...position.querySelectorAll('.detail-quote')], selected)
        expect(position.textContent).toContain(`Native value · ${holding.instrument.currency}${formatMoney(holding.value!)}`)
        const activity = screen.getByRole('region', { name: 'Selected activity' })
        const events = getHoldingActivity(holding.id)
        expect(primaryAmounts(activity).map(node => node.textContent)).toEqual(events.map(event => formatMoney(event.amount, selected)))
        if (holding.employeePlan) {
          const records = screen.getByRole('region', { name: 'Employee purchase lots' })
          expectCurrency(primaryAmounts(records), selected)
          expectCurrency([...records.querySelectorAll('.detail-quote')], selected)
          expect(records.textContent).toContain('Not supplied')
          expect(records.textContent).toContain('not purchase-date FX or tax basis')
        }
      }
      view.unmount()
    }
    expect(getHoldings()).toEqual(holdings)
    expect(getEmployeeLots('h14')).toEqual(lots)
  })

  it('updates bank rows, subtotals, reconciliation and each inspector while preserving original narration', async () => {
    const user = userEvent.setup()
    const view = open('banking')
    const records = getBankTransactions()
    const rowIds = () => [...view.container.querySelectorAll('.bank-description-cell a')].map(node => node.id)
    const initialOrder = rowIds()
    for (const selected of ['USD', 'INR'] as const) {
      currency(selected)
      expectCurrency(primaryAmounts(view.container), selected)
      expect(screen.getByRole('columnheader', { name: `Amount · ${selected}` })).toBeTruthy()
      expect(rowIds()).toEqual(initialOrder)
    }
    currency('USD')
    await user.type(screen.getByRole('searchbox'), 'coffee')
    expect(view.container.querySelector('.bank-result-bar')?.textContent).toContain('Out $4.31')
    expect(screen.getByRole('region', { name: 'Account and date range movements' }).textContent).toContain('$1,116.94')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'partial')
    expect(screen.getByRole('region', { name: 'Bank balance snapshots' }).textContent).toContain('-$26.35')
    expect(screen.getByRole('region', { name: 'Bank balance snapshots' }).textContent).toContain('Original INR · -₹2,200')
    view.unmount()
    for (const item of records) {
      const detail = open(`banking/${item.id}`)
      const panel = screen.getByRole('dialog', { name: item.description })
      expect(panel.querySelector('.inspector-amount > strong')?.textContent).toBe(formatMoney(item.amount, 'USD'))
      expect(panel.textContent).toContain(item.narration)
      expect(panel.textContent).toContain(`Original INR · ${formatMoney(item.amount)}`)
      detail.unmount()
    }
    expect(getBankTransactions()).toEqual(records)
  }, 15000)

  it.each(['overview', 'investments', 'investments/h14', 'banking'])('masks converted and original values after toggling on %s', async route => {
    const user = userEvent.setup()
    const { container, unmount } = open(route)
    currency('USD')
    await user.click(screen.getByRole('button', { name: 'Hide amounts' }))
    currency('INR')
    expect(container.textContent).not.toMatch(/[₹$]/)
    expect(container.querySelector('.amount, .detail-quote, .original-value')).toBeNull()
    for (const element of container.querySelectorAll('*')) {
      for (const attribute of element.attributes) expect(attribute.value).not.toMatch(/[₹$]/)
    }
    unmount()
    const reloaded = open(route)
    expect((screen.getByLabelText('Display currency') as HTMLSelectElement).value).toBe('INR')
    expect(reloaded.container.textContent).not.toMatch(/[₹$]/)
    expect(within(reloaded.container).getByRole('button', { name: 'Show amounts' })).toBeTruthy()
  })
})
