import { useEffect, useRef, useState } from 'react'
import { useInView } from 'motion/react'
import { usePrefersReducedMotion } from '../../lib/hooks'

const DURATION_MS = 800
const easeOut = (x: number) => 1 - Math.pow(1 - x, 3)

/** Counts up to `value` once when scrolled into view; shows the value at once with reduced motion. */
export default function CountUp({ value, decimals = 0, suffix = '' }: { value: number; decimals?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, margin: '0px 0px -15% 0px' })
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(0)

  useEffect(() => {
    if (!inView || reduced) return
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / DURATION_MS)
      setShown(value * easeOut(k))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [inView, reduced, value])

  const v = reduced ? value : shown
  return (
    <span ref={ref} className="tabular">
      {v.toFixed(decimals)}
      {suffix}
    </span>
  )
}
