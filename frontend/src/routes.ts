import { useLayoutEffect, useRef, useState } from 'react'

export type Screen = 'overview' | 'investments' | 'unavailable'
export function readScreen(hash: string): Screen {
  if (hash === '' || hash === '#overview' || hash === '#/overview') return 'overview'
  if (hash === '#/investments') return 'investments'
  return 'unavailable'
}

export function useScreen() {
  const [screen, setScreen] = useState(() => readScreen(window.location.hash))
  const current = useRef(screen)
  const scroll = useRef<Partial<Record<Screen, number>>>({})
  const navigated = useRef(false)
  useLayoutEffect(() => {
    const previousRestoration = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    const sync = () => {
      const next = readScreen(window.location.hash)
      if (next === current.current) return
      scroll.current[current.current] = window.scrollY
      current.current = next
      navigated.current = true
      setScreen(next)
    }
    window.addEventListener('hashchange', sync)
    window.addEventListener('popstate', sync)
    return () => { window.removeEventListener('hashchange', sync); window.removeEventListener('popstate', sync); window.history.scrollRestoration = previousRestoration }
  }, [])
  useLayoutEffect(() => {
    if (!navigated.current) return
    document.getElementById('page-title')?.focus({ preventScroll: true })
    // History traversal may scroll to the fragment after popstate dispatch.
    const frame = requestAnimationFrame(() => window.scrollTo({ top: scroll.current[screen] ?? 0, behavior: 'instant' }))
    return () => cancelAnimationFrame(frame)
  }, [screen])
  function navigate(next: Exclude<Screen, 'unavailable'>) {
    if (next === current.current) return
    // Capture before changing the URL: native hash navigation can reset scroll first.
    scroll.current[current.current] = window.scrollY
    window.history.pushState(null, '', `#/${next}`)
    current.current = next
    navigated.current = true
    setScreen(next)
  }
  return { screen, navigate }
}
