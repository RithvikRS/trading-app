import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import App from './App'
import { getHoldings } from './data/holdings'
import { convert, formatMoney } from './data/money'
import { readRoute } from './routes'
import { accountName } from './holdingPresentation'

function renderRoute(hash = '#/investments/h14') {
  window.history.replaceState(null, '', `/${hash}`)
  return render(<App />)
}
function region(name: string) { return screen.getByRole('region', { name }) }

describe('holding details', () => {
  it('opens each known account-specific position directly with reconciled current values', () => {
    for (const holding of getHoldings()) {
      const view = renderRoute(`#/investments/${holding.id}`)
      expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(`${holding.instrument.name}.`)
      expect(view.container.querySelector('.detail-account')?.textContent).toContain(accountName(holding.accountId))
      expect(region('Current position').textContent).toContain(formatMoney(convert(holding.value!, 'INR')))
      expect(region('Current position').textContent).toContain(formatMoney(holding.value!))
      expect(screen.getByRole('link', { name: 'Investments', current: 'page' })).toBeTruthy()
      view.unmount()
    }
  })
  it('keeps INDmoney and UBS Accenture links distinct and shows lots only for UBS', async () => {
    const user = userEvent.setup()
    renderRoute('#/investments')
    await user.click(screen.getByRole('link', { name: 'View Accenture at INDmoney US' }))
    expect(window.location.hash).toBe('#/investments/h09')
    expect(screen.queryByRole('region', { name: 'Employee purchase lots' })).toBeNull()
    expect(region('Selected activity').textContent).toContain('$1,120.00')
    await user.click(screen.getByRole('link', { name: 'Back to holdings' }))
    await user.click(screen.getByRole('link', { name: 'View Accenture at UBS' }))
    expect(window.location.hash).toBe('#/investments/h14')
    expect(region('Employee purchase lots').textContent).toContain('24 units match this holding')
    expect(region('Employee purchase lots').textContent).toContain('Not supplied')
    expect(region('Employee purchase lots').textContent).toContain('$0.00')
  })
  it('preserves search, filters, expanded controls, sorting, scroll and originating-row focus on return', async () => {
    const user = userEvent.setup()
    renderRoute('#/investments')
    await user.type(screen.getByRole('searchbox'), 'ACN')
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Market'), 'US')
    await user.selectOptions(screen.getByLabelText('Sort'), 'name:asc')
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 620 })
    await user.click(screen.getByRole('link', { name: 'View Accenture at UBS' }))
    expect(document.activeElement?.id).toBe('page-title')
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 })
    await user.click(screen.getByRole('link', { name: 'Back to holdings' }))
    expect((screen.getByRole('searchbox') as HTMLInputElement).value).toBe('ACN')
    expect((screen.getByLabelText('Market') as HTMLSelectElement).value).toBe('US')
    expect((screen.getByLabelText('Sort') as HTMLSelectElement).value).toBe('name:asc')
    expect(screen.getByRole('button', { name: /Filters\s*1/ }).getAttribute('aria-expanded')).toBe('true')
    expect(document.activeElement?.id).toBe('holding-link-h14')
    await waitFor(() => expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 620, behavior: 'instant' }))
    await act(async () => { window.history.back() })
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Accenture.'))
    await act(async () => { window.history.forward() })
    await waitFor(() => expect(document.activeElement?.id).toBe('holding-link-h14'))
    expect(window.location.hash).toBe('#/investments')
    expect(JSON.stringify(localStorage)).not.toContain('ACN')
  })
  it('retains originating-row focus after the mobile drawer finishes closing', async () => {
    const user = userEvent.setup()
    renderRoute('#/investments')
    await user.click(screen.getByRole('link', { name: 'View Accenture at UBS' }))
    const close = vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (this: HTMLDialogElement) { this.removeAttribute('open') })
    try {
      await user.click(screen.getByRole('button', { name: 'Open navigation' }))
      const drawer = screen.getByRole('dialog', { name: 'Navigation' })
      await user.click(within(drawer).getByRole('link', { name: 'Investments' }))
      fireEvent(drawer, new Event('close'))
      expect(document.activeElement?.id).toBe('holding-link-h14')
    } finally { close.mockRestore() }
  })
  it('shows fund plan/option/folio identity and preserves unpriced data on failure and retry', async () => {
    const user = userEvent.setup()
    renderRoute('#/investments/h13')
    expect(region('Fund information').textContent).toContain('Regular')
    expect(region('Fund information').textContent).toContain('Growth')
    expect(region('Fund information').textContent).toContain('Sample folio D')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'partial')
    expect(region('Current position').textContent).not.toContain('₹0')
    expect(region('Current position').textContent).toContain('5,000')
    expect(region('Source & freshness').textContent).toContain('No nav supplied')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'error')
    expect(region('Current position').textContent).toContain('Value unavailable')
    await user.click(screen.getByRole('button', { name: 'Retry demo' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(region('Current position').textContent).toContain('Value unavailable')
  })
  it('labels stale holdings separately from the quote and retains native historical amounts across currency changes', async () => {
    const user = userEvent.setup()
    renderRoute()
    const originalLots = region('Employee purchase lots').textContent
    const originalActivity = region('Selected activity').textContent
    await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
    expect(region('Current position').textContent).toContain('$7,200.00')
    expect(region('Employee purchase lots').textContent).toBe(originalLots)
    expect(region('Selected activity').textContent).toBe(originalActivity)
    await user.selectOptions(screen.getByLabelText('Demo state'), 'partial')
    expect(region('Source & freshness').textContent).toContain('17 Oct 2026, 09:00 IST')
    expect(region('Source & freshness').textContent).toContain('20 Oct 2026, 01:30 IST')
    expect(region('Current position').textContent).toContain('13.8%')
    expect(region('Current position').textContent).toContain('coverage is incomplete')
  })
  it('masks current values, units, quotes, lots, activity and FX without leaking values through attributes', async () => {
    const user = userEvent.setup()
    const { container } = renderRoute()
    await user.click(screen.getByRole('button', { name: 'Hide amounts' }))
    expect(container.textContent).not.toMatch(/[₹$]/)
    expect(container.querySelector('.detail-quantity, .detail-quote, .amount')).toBeNull()
    for (const element of container.querySelectorAll('[title], [aria-label], [aria-valuetext]')) expect(['title', 'aria-label', 'aria-valuetext'].map(name => element.getAttribute(name)).join(' ')).not.toMatch(/[₹$]/)
    await user.click(screen.getByRole('link', { name: 'Back to holdings' }))
    expect(container.querySelector('.holding-number, .amount')).toBeNull()
  })
  it('supports direct links and falls back to the list heading when no originating row is available', async () => {
    const user = userEvent.setup()
    const { unmount } = renderRoute()
    unmount()
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Accenture.')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'loading')
    expect(screen.getByRole('status').textContent).toBe('Loading sample holding')
    expect(screen.queryByRole('region', { name: 'Current position' })).toBeNull()
    await user.selectOptions(screen.getByLabelText('Demo state'), 'empty')
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('isn’t available')
    await user.click(screen.getByRole('button', { name: 'Load sample holding' }))
    expect(region('Current position').textContent).toContain('₹6,01,200')
    await user.click(screen.getByRole('link', { name: 'Back to holdings' }))
    expect(document.activeElement?.id).toBe('page-title')
  })
  it('rejects unknown or encoded identifiers and safely explains unavailable routes', () => {
    for (const hash of ['#/investments/h99', '#/investments/%68%31%34', '#/investments/h14/extra', '#/investments/<img>', '#/investments/h14?account=ubs']) expect(readRoute(hash)).toEqual({ screen: 'unavailable' })
    renderRoute('#/investments/h99')
    expect(screen.getByRole('heading', { name: 'This view is unavailable.' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Go to investments' })).toBeTruthy()
  })
  it('distinguishes no supplied activity and unknown cost basis from zero', () => {
    renderRoute('#/investments/h02')
    expect(region('Selected activity').textContent).toContain('No sample activity supplied.')
    expect(screen.getByRole('heading', { name: 'Cost basis unavailable' })).toBeTruthy()
    expect(screen.queryByText('₹0')).toBeNull()
  })
  it.each(['h14', 'h13'])('has no detectable structural accessibility violations for %s', async holdingId => {
    const { container } = renderRoute(`#/investments/${holdingId}`)
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map(item => `${item.id}: ${item.description}`)).toEqual([])
  })
})
