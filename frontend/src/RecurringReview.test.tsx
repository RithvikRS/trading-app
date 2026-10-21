import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { describe, expect, it } from 'vitest'
import App from './App'
import RecurringReview from './RecurringReview'
import { getBankTransactions } from './data/banking'
import { createRecurringState, initialRecurringControls } from './data/recurring'
import { createTransferState } from './data/transfers'

async function open() {
  window.history.replaceState(null, '', '/#/budgets')
  const mounted = render(<App />), user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Recurring' }))
  return { ...mounted, user }
}
const summary = () => screen.getByRole('region', { name: 'Recurring summary' })
const upcoming = () => screen.getByRole('region', { name: 'Expected commitments' })
const detail = (name: string) => within(screen.getByRole('region', { name: `${name} evidence` }))
async function expand(user: ReturnType<typeof userEvent.setup>, name: string) { await user.click(screen.getByRole('button', { name: new RegExp(`^${name}`) })) }
async function confirm(user: ReturnType<typeof userEvent.setup>, name: string) { await expand(user, name); await user.click(detail(name).getByRole('button', { name: 'Confirm recurring' })) }

describe('recurring review workspace', () => {
  it('reviews fixed and variable patterns separately without changing monthly budgets or cash flow', async () => {
    const { user } = await open()
    expect(summary().textContent).toContain('None included')
    await confirm(user, 'Monthly service fee'); expect(summary().textContent).toContain('₹5.9')
    await confirm(user, 'Grocery top-up'); expect(summary().textContent).toContain('1 expected')
    expect(upcoming().textContent).toContain('₹1,800'); expect(upcoming().textContent).toContain('₹2,200')
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }))
    expect(screen.getByRole('region', { name: 'Monthly budget summary' }).textContent).toContain('₹35,959')
    await user.click(screen.getByRole('button', { name: 'Cash flow' }))
    expect(screen.getByRole('region', { name: 'Cash-flow summary' }).textContent).toContain('₹35,964.9')
    await user.click(screen.getByRole('button', { name: 'Recurring' })); expect(summary().textContent).toContain('2 confirmed')
    await user.selectOptions(screen.getByLabelText('Recurring month'), '2026-09')
    expect(summary().textContent).toContain('Evidence only'); expect(screen.queryByRole('region', { name: 'Expected commitments' })).toBeNull()
    expect(detail('Grocery top-up').getByRole('link', { name: /September grocery top-up/ })).toBeTruthy()
  })
  it('supports dismissal, restoration, independent undo/reset and empty filters', async () => {
    const { user } = await open()
    await confirm(user, 'Monthly service fee')
    await user.click(detail('Monthly service fee').getByRole('button', { name: 'Dismiss suggestion' }))
    expect(summary().textContent).toContain('None included')
    await user.click(detail('Monthly service fee').getByRole('button', { name: 'Restore suggestion' }))
    expect(detail('Monthly service fee').getByRole('button', { name: 'Confirm recurring' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Undo recurring change' })); expect(detail('Monthly service fee').getByRole('button', { name: 'Restore suggestion' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Undo recurring change' })); expect(summary().textContent).toContain('1 confirmed')
    await user.selectOptions(screen.getByLabelText('Pattern review'), 'dismissed'); expect(screen.getByText(/No patterns match/)).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Pattern review'), 'confirmed')
    expect(screen.getByRole('button', { name: /^Monthly service fee/ })).toBeTruthy(); expect(screen.queryByRole('button', { name: /^Home rent/ })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Reset sample recurring decisions' })); expect(summary().textContent).toContain('0 confirmed')
    expect((screen.getByRole('button', { name: 'Undo recurring change' }) as HTMLButtonElement).disabled).toBe(true)
  })
  it('shows pending and ambiguous evidence without allowing confirmation', async () => {
    const { user } = await open(); await expand(user, 'Home purchases')
    expect((detail('Home purchases').getByRole('button', { name: 'Confirm recurring' }) as HTMLButtonElement).disabled).toBe(true)
    expect(detail('Home purchases').getByRole('link', { name: /Online purchase.*Pending source/ })).toBeTruthy()
    expect(detail('Home purchases').getByRole('link', { name: /Home essentials.*Unassigned posted purchase/ })).toBeTruthy()
    await user.click(detail('Home purchases').getByRole('link', { name: /Online purchase/ }))
    expect(screen.getByRole('dialog').textContent).toContain('Pending record.')
  })
  it('updates confirmation validity after a source correction and preserves inspector origin/focus', async () => {
    const { user } = await open(); await confirm(user, 'Monthly service fee')
    await user.click(detail('Monthly service fee').getByRole('link', { name: /August service fee/ }))
    expect(window.location.hash).toBe('#/banking/t42')
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('New category'), 'unresolved')
    await user.click(dialog.getByRole('button', { name: 'Preview correction' })); await user.click(dialog.getByRole('button', { name: 'Apply 1 change' }))
    await user.click(dialog.getByRole('button', { name: 'Close transaction details' }))
    expect(window.location.hash).toBe('#/budgets'); expect(document.activeElement?.id).toBe('recurring-link-service-fee-t42')
    expect(screen.getByRole('button', { name: /^Monthly service fee/ }).textContent).toContain('Needs review · Confirmation retained')
    expect(summary().textContent).toContain('None included')
    await user.click(screen.getByRole('button', { name: 'Reset sample recurring decisions' }))
    await user.click(detail('Monthly service fee').getByRole('link', { name: /August service fee/ }))
    expect(screen.getByRole('dialog').textContent).toContain('Effective categoryUncategorized')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close transaction details' }))
    expect((screen.getByRole('button', { name: 'Undo recurring change' }) as HTMLButtonElement).disabled).toBe(true)
    expect(summary().textContent).toContain('0 confirmed')
  })
  it('keeps selections through partial/loading/error/retry, clears them on empty and drops decisions on reload', async () => {
    const { user, unmount } = await open(); await confirm(user, 'Water & maintenance')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'partial')
    expect(detail('Water & maintenance').getByText('Source unavailable · t26')).toBeTruthy()
    expect(screen.getByRole('button', { name: /^Water & maintenance/ }).textContent).toContain('Confirmation retained')
    await user.selectOptions(screen.getByLabelText('Demo state'), 'error')
    expect(screen.getByRole('alert').textContent).toContain('last available sample snapshot')
    await user.click(screen.getByRole('button', { name: 'Retry demo' })); await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(detail('Water & maintenance').getByText('Source unavailable · t26')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Demo state'), 'loading'); expect(screen.queryByRole('region', { name: 'Recurring summary' })).toBeNull(); expect(screen.queryByRole('button', { name: 'Dismiss suggestion' })).toBeNull()
    await user.selectOptions(screen.getByLabelText('Demo state'), 'populated'); expect(summary().textContent).toContain('1 confirmed')
    expect(detail('Water & maintenance').getByRole('link', { name: /Water and maintenance bill/ })).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Recurring month'), '2026-08'); await user.selectOptions(screen.getByLabelText('Demo state'), 'empty')
    expect(screen.queryByLabelText('Recurring month')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Explore sample recurring expenses' }))
    expect((screen.getByLabelText('Recurring month') as HTMLSelectElement).value).toBe('2026-10'); expect(summary().textContent).toContain('0 confirmed')
    await confirm(user, 'Monthly service fee'); unmount()
    render(<App />); await user.click(screen.getByRole('button', { name: 'Recurring' })); expect(summary().textContent).toContain('0 confirmed')
  })
  it('converts every monetary surface, removes masked ranges from the DOM and persists only display preferences', async () => {
    const { user } = await open(); await confirm(user, 'Monthly service fee'); await confirm(user, 'Grocery top-up')
    await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
    const workspace = document.querySelector('.recurring-workspace')!
    expect(summary().textContent).toContain('$0.07'); expect(upcoming().textContent).toContain('$21.56'); expect(upcoming().textContent).toContain('$26.35')
    expect(workspace.textContent).not.toContain('₹')
    await user.click(screen.getByRole('button', { name: 'Hide amounts' }))
    expect(workspace.outerHTML).not.toMatch(/\$|₹|1,800|2,200|21\.56|26\.35|180000|220000|data-value|title="[\d₹$]/)
    expect(workspace.querySelectorAll('[aria-label="Amount hidden"]').length).toBeGreaterThan(5)
    await user.click(detail('Grocery top-up').getByRole('link', { name: /August grocery top-up/ }))
    expect(screen.getByRole('dialog').textContent).not.toContain('INR 1800')
    expect(window.location.hash).toBe('#/banking/t36')
    const persisted = JSON.stringify({ ...localStorage }); expect(persisted).not.toMatch(/grocery|confirmed|1800|590|recurring|2026-08/)
    expect(sessionStorage.length).toBe(0)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close transaction details' }))
    await user.click(screen.getByRole('button', { name: 'Show amounts' })); expect(upcoming().textContent).toContain('$21.56')
    await user.selectOptions(screen.getByLabelText('Display currency'), 'INR'); expect(upcoming().textContent).toContain('₹1,800')
  })
  it('restores source links on Back/Forward and falls back to the list heading for missing evidence', async () => {
    const { user } = await open(); await expand(user, 'Water & maintenance')
    await user.click(detail('Water & maintenance').getByRole('link', { name: /Water and maintenance bill/ }))
    act(() => { window.history.replaceState(null, '', '/#/budgets'); window.dispatchEvent(new PopStateEvent('popstate')) })
    expect(document.activeElement?.id).toBe('recurring-link-maintenance-t26')
    act(() => { window.history.replaceState(null, '', '/#/banking/t26'); window.dispatchEvent(new PopStateEvent('popstate')) })
    expect(screen.getByRole('dialog')).toBeTruthy()
    // A source update can arrive while its inspector is open.
    fireEvent.change(screen.getByLabelText('Demo state'), { target: { value: 'partial' } })
    expect(screen.getByRole('dialog').textContent).toContain('Transaction unavailable')
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(document.activeElement?.id).toBe('recurring-patterns-title')
  })
  it('supports keyboard controls and has no automated accessibility violations when expanded or masked', async () => {
    const { user, container } = await open()
    screen.getByRole('button', { name: /^Monthly service fee/ }).focus(); await user.keyboard('{Enter}')
    detail('Monthly service fee').getByRole('button', { name: 'Confirm recurring' }).focus(); await user.keyboard('{Enter}')
    expect(summary().textContent).toContain('1 confirmed')
    expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
    await user.click(screen.getByRole('button', { name: 'Hide amounts' })); await user.click(screen.getByRole('button', { name: 'Use dark theme' }))
    expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([])
  })
  it('renders markup-like source labels as text', () => {
    const records = getBankTransactions(false, null).map(item => item.id === 't42' ? { ...item, description: '<img src=x onerror=alert(1)>' } : item)
    const { container } = render(<RecurringReview view="populated" records={records} review={createTransferState()} state={createRecurringState()} controls={{ ...initialRecurringControls, expanded: 'service-fee' }} onAction={() => {}} onChange={() => {}} onOpen={() => {}} onReset={() => {}} />)
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy(); expect(container.querySelector('img')).toBeNull()
  })
})
