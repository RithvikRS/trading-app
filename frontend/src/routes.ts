import { useLayoutEffect, useRef, useState } from 'react'
import { isHoldingId } from './data/holdings'

export type Route = { screen: 'overview' | 'investments' | 'unavailable' } | { screen: 'holding'; holdingId: string }
export type Screen = Route['screen']
export function readRoute(hash: string): Route {
  if (hash === '' || hash === '#overview' || hash === '#/overview') return { screen: 'overview' }
  if (hash === '#/investments') return { screen: 'investments' }
  const match = /^#\/investments\/(h\d{2})$/.exec(hash)
  if (match && isHoldingId(match[1]!)) return { screen: 'holding', holdingId: match[1]! }
  return { screen: 'unavailable' }
}
export function readScreen(hash: string): Screen { return readRoute(hash).screen }
function routeKey(route: Route) { return route.screen === 'holding' ? `holding:${route.holdingId}` : route.screen }

export function useScreen() {
  const [route, setRoute] = useState(() => readRoute(window.location.hash))
  const current = useRef(route)
  const scroll = useRef<Record<string, number>>({})
  const listOrigin = useRef<string | null>(null)
  const focusTarget = useRef('page-title')
  const navigated = useRef(false)

  function transition(next: Route, push = false) {
    const previous = current.current
    if (routeKey(next) === routeKey(previous)) return
    scroll.current[routeKey(previous)] = window.scrollY
    if (previous.screen === 'investments' && next.screen === 'holding') listOrigin.current = next.holdingId
    focusTarget.current = next.screen === 'investments' && previous.screen === 'holding' && listOrigin.current === previous.holdingId
      ? `holding-link-${previous.holdingId}` : 'page-title'
    if (push) window.history.pushState(null, '', next.screen === 'holding' ? `#/investments/${next.holdingId}` : `#/${next.screen}`)
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
    const target = document.getElementById(focusTarget.current) ?? document.getElementById('page-title')
    target?.focus({ preventScroll: true })
    // History traversal may scroll to the fragment after popstate dispatch.
    const frame = requestAnimationFrame(() => window.scrollTo({ top: scroll.current[routeKey(route)] ?? 0, behavior: 'instant' }))
    return () => cancelAnimationFrame(frame)
  }, [route])
  return {
    screen: route.screen, route,
    navigate: (screen: 'overview' | 'investments') => transition({ screen }, true),
    openHolding: (holdingId: string) => { if (isHoldingId(holdingId)) transition({ screen: 'holding', holdingId }, true) },
  }
}
