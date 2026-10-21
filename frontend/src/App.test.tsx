import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import axe from 'axe-core'
import App from './App'

describe('Overview interactions', () => {
  it('changes reporting currency without changing the underlying snapshot or range total', async () => {
    const user = userEvent.setup()
    render(<App />)
    const summary = screen.getByRole('region', { name: 'Asset summary' })
    expect(within(summary).getByText('₹50,86,080')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
    expect(within(summary).getByText('$60,911.14')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /^1M$/ }))
    expect(within(summary).getByText('$60,911.14')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'View data' }))
    expect(screen.getAllByRole('row')).toHaveLength(6)
    expect(screen.getByRole('slider').getAttribute('aria-valuetext')).toContain('$60,911.14')
    await user.click(screen.getByRole('button', { name: /^3M$/ }))
    expect(screen.getAllByRole('row')).toHaveLength(15)
  })

  it('masks all absolute amounts, including expanded rows, chart data and accessible attributes', async () => {
    const user = userEvent.setup()
    const { container } = render(<App />)
    await user.click(screen.getByRole('button', { name: /^INDmoney US/ }))
    await user.click(screen.getByRole('button', { name: 'View data' }))
    await user.click(screen.getByRole('button', { name: 'About this view' }))
    await user.click(screen.getByRole('button', { name: 'Hide amounts' }))
    expect(container.textContent).not.toMatch(/[₹$]/)
    expect(container.querySelector('input[type="range"]')).toBeNull()
    expect(container.querySelector('.value-chart')).toBeNull()
    for (const element of container.querySelectorAll('[aria-label], [aria-valuetext], [title]')) {
      expect(['aria-label', 'aria-valuetext', 'title'].map(name => element.getAttribute(name)).join(' ')).not.toMatch(/[₹$]/)
    }
    expect(screen.getAllByLabelText('Amount hidden').length).toBeGreaterThan(10)
    await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
    expect(container.textContent).not.toMatch(/[₹$]/)
    await user.click(screen.getByRole('button', { name: 'Show amounts' }))
    expect(screen.getAllByText('$60,911.14').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /^INDmoney US/ }).getAttribute('aria-expanded')).toBe('true')
  })

  it('shows missing coverage and retains the partial snapshot through a failed load and retry', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.selectOptions(screen.getByLabelText('Demo state'), 'partial')
    expect(screen.getByText('Valued assets')).toBeTruthy()
    expect(screen.getByText('₹46,61,080')).toBeTruthy()
    expect(within(screen.getByRole('button', { name: /^Advisor funds/ })).getByLabelText('Value unavailable')).toBeTruthy()
    expect(screen.getByText('Holdings stale')).toBeTruthy()
    expect(screen.queryByRole('slider')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Review coverage' }))
    expect(screen.getByText(/One regular-plan holding is excluded/)).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Demo state'), 'error')
    expect(screen.getByRole('alert').textContent).toContain('last available sample snapshot')
    expect(screen.getByText('₹46,61,080')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Retry demo' }))
    expect((screen.getByRole('button', { name: 'Retrying…' }) as HTMLButtonElement).disabled).toBe(true)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect((screen.getByLabelText('Demo state') as HTMLSelectElement).value).toBe('partial')
    expect(screen.getByText('₹46,61,080')).toBeTruthy()
  })

  it('distinguishes loading from empty and restores the demo from empty', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.selectOptions(screen.getByLabelText('Demo state'), 'loading')
    expect(screen.getByRole('status').textContent).toBe('Loading sample portfolio')
    expect(screen.queryByRole('region', { name: 'Asset summary' })).toBeNull()
    await user.selectOptions(screen.getByLabelText('Demo state'), 'empty')
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByRole('region', { name: 'Asset summary' })).toBeNull()
    await user.selectOptions(screen.getByLabelText('Demo state'), 'error')
    expect(screen.getByRole('alert').textContent).toContain('no accounts')
    await user.click(screen.getByRole('button', { name: 'Explore sample portfolio' }))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('region', { name: 'Asset summary' })).toBeTruthy()
  })

  it('persists privacy, currency and theme across a reload', async () => {
    const user = userEvent.setup()
    const first = render(<App />)
    await user.click(screen.getByRole('button', { name: 'Use dark theme' }))
    await user.click(screen.getByRole('button', { name: 'Hide amounts' }))
    await user.selectOptions(screen.getByLabelText('Display currency'), 'USD')
    first.unmount()
    const second = render(<App />)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(screen.getByRole('button', { name: 'Show amounts' })).toBeTruthy()
    expect((screen.getByLabelText('Display currency') as HTMLSelectElement).value).toBe('USD')
    expect(second.container.textContent).not.toMatch(/[₹$]/)
  })

  it('provides named landmarks and controls without detectable structural accessibility violations', async () => {
    const { container } = render(<App />)
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map(item => `${item.id}: ${item.description}`)).toEqual([])
  })
})
