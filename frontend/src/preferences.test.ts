import { describe, expect, it, vi } from 'vitest'
import { readPreferences, savePreferences } from './preferences'

describe('display preference storage', () => {
  it('validates malformed and unexpected stored input', () => {
    localStorage.setItem('portfolio.display.v1', '{broken')
    expect(readPreferences()).toEqual({ theme: 'light', currency: 'INR', hidden: false })
    localStorage.setItem('portfolio.display.v1', JSON.stringify({ theme: 'unknown', currency: 'EUR', hidden: 'false', extra: 'ignored' }))
    expect(readPreferences()).toEqual({ theme: 'light', currency: 'INR', hidden: false })
  })
  it('stores only display preferences and restores them', () => {
    const preferences = { theme: 'dark' as const, currency: 'USD' as const, hidden: true, unexpected: 'not persisted' }
    savePreferences(preferences)
    expect(JSON.parse(localStorage.getItem('portfolio.display.v1')!)).toEqual({ theme: 'dark', currency: 'USD', hidden: true })
    expect(readPreferences()).toEqual({ theme: 'dark', currency: 'USD', hidden: true })
  })
  it('works without browser storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Storage unavailable') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage unavailable') })
    expect(readPreferences()).toEqual({ theme: 'light', currency: 'INR', hidden: false })
    expect(() => savePreferences({ theme: 'dark', currency: 'USD', hidden: true })).not.toThrow()
  })
})
