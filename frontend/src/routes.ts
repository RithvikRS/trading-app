import { useLayoutEffect, useRef, useState } from 'react'
import { isHoldingId } from './data/holdings'
import { isBankTransactionId } from './data/banking'

export type Route = { screen: 'overview' | 'investments' | 'banking' | 'budgets' | 'unavailable' } | { screen: 'holding'; holdingId: string } | { screen: 'transaction'; transactionId: string }
export type Screen = Route['screen']
export function readRoute(hash: string): Route {
  if (hash === '' || hash === '#overview' || hash === '#/overview') return { screen: 'overview' }
  if (hash === '#/investments') return { screen: 'investments' }
  if (hash === '#/banking') return { screen: 'banking' }
  if (hash === '#/budgets') return { screen: 'budgets' }
  const transaction = /^#\/banking\/(t\d{2})$/.exec(hash)
  if (transaction && isBankTransactionId(transaction[1]!)) return { screen: 'transaction', transactionId: transaction[1]! }
  const match = /^#\/investments\/(h\d{2})$/.exec(hash)
  if (match && isHoldingId(match[1]!)) return { screen: 'holding', holdingId: match[1]! }
  return { screen: 'unavailable' }
}
export function readScreen(hash: string): Screen { return readRoute(hash).screen }
function routeKey(route: Route) { return route.screen === 'holding' ? `holding:${route.holdingId}` : route.screen === 'transaction' ? `transaction:${route.transactionId}` : route.screen }

export function useScreen() {
  const [route, setRoute] = useState(() => readRoute(window.location.hash))
  const current = useRef(route)
  const scroll = useRef<Record<string, number>>({})
  const transactionOrigin = useRef<'banking' | 'budgets'>('banking')
  function scrollKey(value: Route) { return value.screen === 'transaction' ? transactionOrigin.current : routeKey(value) }
  const listOrigin = useRef<string | null>(null)
  const focusTarget = useRef('page-title')
  const navigated = useRef(false)

  function transition(next: Route, push = false) {
    const previous = current.current
    if (routeKey(next) === routeKey(previous)) return
    scroll.current[scrollKey(previous)] = window.scrollY
    if (previous.screen === 'investments' && next.screen === 'holding') listOrigin.current = next.holdingId
    if ((previous.screen === 'banking' || previous.screen === 'budgets') && next.screen === 'transaction') {
      transactionOrigin.current = previous.screen
      const active = document.activeElement?.id
      if (active?.includes('-link-') && active.endsWith(`-${next.transactionId}`)) listOrigin.current = active
      else if (!listOrigin.current?.endsWith(`-${next.transactionId}`)) listOrigin.current = `${previous.screen === 'budgets' ? 'budget' : 'transaction'}-link-${next.transactionId}`
    }
    focusTarget.current = next.screen === 'investments' && previous.screen === 'holding' && listOrigin.current === previous.holdingId
      ? `holding-link-${previous.holdingId}` : next.screen === transactionOrigin.current && previous.screen === 'transaction' && listOrigin.current ? listOrigin.current : next.screen === 'transaction' ? 'transaction-title' : 'page-title'
    if (push) window.history.pushState(null, '', next.screen === 'holding' ? `#/investments/${next.holdingId}` : next.screen === 'transaction' ? `#/banking/${next.transactionId}` : `#/${next.screen}`)
    current.current = next
    navigated.current = true
    setRoute(next)
  }

  useLayoutEffect(() => {
    const previousRestoration = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    const sync = () => transition(readRoute(window.location.hash))
    window.addEventListener('hashchange', sync)
    window.addEventListener('popstate', sync)
    return () => { window.removeEventListener('hashchange', sync); window.removeEventListener('popstate', sync); window.history.scrollRestoration = previousRestoration }
  }, [])
  useLayoutEffect(() => {
    if (!navigated.current) return
    const target = document.getElementById(focusTarget.current) ?? (focusTarget.current.startsWith('category-link-') ? document.getElementById('category-review-title') : null) ?? (focusTarget.current.startsWith('cash-link-') ? document.getElementById('cash-sources-title') : null) ?? (focusTarget.current.startsWith('recurring-link-') ? document.getElementById('recurring-patterns-title') : null) ?? (focusTarget.current.startsWith('budget-link-') ? document.getElementById('budget-categories-title') : null) ?? document.getElementById('page-title')
    target?.focus({ preventScroll: true })
    // History traversal may scroll to the fragment after popstate dispatch.
    const frame = requestAnimationFrame(() => window.scrollTo({ top: scroll.current[scrollKey(route)] ?? 0, behavior: 'instant' }))
    return () => cancelAnimationFrame(frame)
  }, [route])
  return {
    screen: route.screen, route, transactionOrigin: transactionOrigin.current,
    navigate: (screen: 'overview' | 'investments' | 'banking' | 'budgets') => transition({ screen }, true),
    openHolding: (holdingId: string) => { if (isHoldingId(holdingId)) transition({ screen: 'holding', holdingId }, true) },
    openTransaction: (transactionId: string) => { if (isBankTransactionId(transactionId)) transition({ screen: 'transaction', transactionId }, true) },
  }
}
