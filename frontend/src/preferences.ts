import type { Currency } from './data/portfolio'

export type Theme = 'light' | 'dark'
export interface Preferences { theme: Theme; currency: Currency; hidden: boolean }
const KEY = 'portfolio.display.v1'

export function readPreferences(): Preferences {
  const fallback: Preferences = {
    theme: window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
    currency: 'INR', hidden: false,
  }
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    if (!parsed || typeof parsed !== 'object') return fallback
    const item = parsed as Record<string, unknown>
    return {
      theme: item.theme === 'light' || item.theme === 'dark' ? item.theme : fallback.theme,
      currency: item.currency === 'INR' || item.currency === 'USD' ? item.currency : 'INR',
      hidden: typeof item.hidden === 'boolean' ? item.hidden : false,
    }
  } catch { return fallback }
}

export function savePreferences(preferences: Preferences): void {
  try { localStorage.setItem(KEY, JSON.stringify({ theme: preferences.theme, currency: preferences.currency, hidden: preferences.hidden })) } catch { /* The UI also works when storage is unavailable. */ }
}
