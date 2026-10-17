import { useEffect, useState, useSyncExternalStore } from 'react'
import type { PlaybackClock } from './clock'

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribeReducedMotion(cb: () => void) {
  const mq = window.matchMedia(QUERY)
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}

/** True when the OS asks for reduced motion. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(QUERY).matches,
    () => false,
  )
}

/**
 * The clock's time, refreshed about `hz` times per second (and on every play/pause/seek),
 * for React UI that does not need 60 fps.
 */
export function useClockTime(clock: PlaybackClock, hz = 8): number {
  const [t, setT] = useState(() => clock.now())
  useEffect(() => {
    let raf = 0
    let last = 0
    const tick = (wall: number) => {
      if (wall - last >= 1000 / hz) {
        last = wall
        setT(clock.now())
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const unsub = clock.subscribe(() => setT(clock.now()))
    return () => {
      cancelAnimationFrame(raf)
      unsub()
    }
  }, [clock, hz])
  return t
}

/** Re-render when the clock's play state changes. */
export function useClockPlaying(clock: PlaybackClock): boolean {
  return useSyncExternalStore(
    (cb) => clock.subscribe(cb),
    () => clock.playing,
    () => false,
  )
}
