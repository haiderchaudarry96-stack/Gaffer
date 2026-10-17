import { useEffect, useId, useRef, useState } from 'react'
import { useInView } from 'motion/react'
import Reveal from '../ui/Reveal'
import { SmallPrint } from '../ui/Disclosure'
import { usePrefersReducedMotion } from '../../lib/hooks'

const BASE = import.meta.env.BASE_URL

/**
 * Drag (or use the arrow keys) to compare White's average shape before and after the 16:30 change.
 * Both images are the two panels of the real evidence image (scripts/crop-evidence.py). The
 * "before" layer is clipped with clip-path, so dragging repaints without any layout work.
 */
export default function BeforeAfter() {
  const [pos, setPos] = useState(50)
  const id = useId()
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.6 })
  const reduced = usePrefersReducedMotion()

  // nudge once to show that it moves (not with reduced motion)
  useEffect(() => {
    if (!inView || reduced) return
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / 1400)
      setPos(50 - 16 * Math.sin(k * Math.PI))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [inView, reduced])

  return (
    <section id="compare" aria-labelledby="compare-title" className="scroll-mt-20 py-24 sm:py-32">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <p className="mb-4 font-mono text-xs tracking-widest text-accent-ink uppercase">What OpenCV sees</p>
          <h2 id="compare-title" className="max-w-4xl text-4xl leading-[1.05] font-bold text-text sm:text-6xl">
            A back four became a back three.
          </h2>
          <p className="mt-5 max-w-2xl text-lg text-muted sm:text-xl">Drag to compare White before and after 16:30.</p>
        </Reveal>
        <Reveal>
          <div ref={ref} className="relative mt-12 aspect-[636/383] w-full max-w-5xl overflow-hidden rounded-(--radius-card) border border-line select-none">
            <img
              src={`${BASE}product/evt003-after.jpg`}
              alt="After: White's average shape 16:35 to 17:05, a 3-4-3, drawn by OpenCV from tracked positions."
              className="absolute inset-0 size-full object-cover"
              width={636}
              height={383}
              loading="lazy"
            />
            <img
              src={`${BASE}product/evt003-before.jpg`}
              alt="Before: White's average shape 15:05 to 15:35, a 4-4-2, drawn by OpenCV from tracked positions."
              className="absolute inset-0 size-full object-cover"
              style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}
              width={636}
              height={383}
              loading="lazy"
            />
            <span className="absolute top-3 left-3 rounded-full bg-black/70 px-3 py-1 font-mono text-sm text-white">Before · 4-4-2</span>
            <span className="absolute top-3 right-3 rounded-full bg-black/70 px-3 py-1 font-mono text-sm text-white">After · 3-4-3</span>
            <div className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-white" style={{ left: `${pos}%` }} aria-hidden="true">
              <span className="absolute top-1/2 left-1/2 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white font-mono text-sm text-black shadow-lg">
                ⇆
              </span>
            </div>
            <label htmlFor={id} className="sr-only">
              Compare before and after: share of the before image shown
            </label>
            <input
              id={id}
              type="range"
              min={0}
              max={100}
              value={Math.round(pos)}
              onChange={(e) => setPos(Number(e.target.value))}
              aria-valuetext={`${Math.round(pos)} % before`}
              className="absolute inset-0 size-full cursor-ew-resize opacity-0"
            />
          </div>
        </Reveal>
        <SmallPrint
          items={[
            'Both panels are from the agent’s real evidence image for the 16:30 alert: White’s average shape in its most confident window before (15:05–15:35, 4-4-2, 20 % of positions in its own box) and after (16:35–17:05, 3-4-3, 12 %). Drawn by OpenCV 5 from tracked positions, attacking right; they are not video frames.',
            'The “before” window was picked to avoid a set piece: an earlier window had 45 % of positions in the own box. That 25 % threshold was set on this one case.',
          ]}
        />
      </div>
    </section>
  )
}
