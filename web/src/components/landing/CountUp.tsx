import { useEffect, useRef, useState } from 'react'
import { animate, useInView } from 'motion/react'
import { usePrefersReducedMotion } from '../../lib/hooks'

/** Counts up to `value` once when scrolled into view; shows the value at once with reduced motion. */
export default function CountUp({ value, decimals = 0, suffix = '' }: { value: number; decimals?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, margin: '0px 0px -15% 0px' })
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(0)

  useEffect(() => {
    if (!inView || reduced) return
    const controls = animate(0, value, {
      duration: 0.8,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setShown(v),
    })
    return () => controls.stop()
  }, [inView, reduced, value])

  const v = reduced ? value : shown
  return (
    <span ref={ref} className="tabular">
      {v.toFixed(decimals)}
      {suffix}
    </span>
  )
}
