import { m } from 'motion/react'
import { usePrefersReducedMotion } from '../../lib/hooks'

// the pitch as a camera sees it (tilted) and as Gaffer maps it (flat, top-down)
const TILTED = 'M48 22 L112 22 L150 86 L10 86 Z'
const FLAT = 'M14 16 L146 16 L146 86 L14 86 Z'
const MID_TILTED = 'M80 22 L80 86'
const MID_FLAT = 'M80 16 L80 86'

function Pitch({ d, mid, ry }: { d: string; mid: string; ry: number }) {
  return (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d={d} />
      <path d={mid} />
      <ellipse cx="80" cy="54" rx="13" ry={ry} />
    </g>
  )
}

/**
 * A short loop: the tilted pitch straightens into a flat top-down map (Motion morphs the path).
 * With reduced motion it is a static before -> after pair.
 */
export default function StraightenIllustration() {
  const reduced = usePrefersReducedMotion()
  if (reduced) {
    return (
      <div className="flex items-center gap-2 text-accent-ink" aria-hidden="true">
        <svg viewBox="0 0 160 100" className="w-24">
          <Pitch d={TILTED} mid={MID_TILTED} ry={7} />
        </svg>
        <span className="text-muted">→</span>
        <svg viewBox="0 0 160 100" className="w-24">
          <Pitch d={FLAT} mid={MID_FLAT} ry={13} />
        </svg>
      </div>
    )
  }
  const loop = { duration: 3.6, repeat: Infinity, ease: [0.45, 0, 0.55, 1] as const, times: [0, 0.3, 0.7, 1] }
  return (
    <svg viewBox="0 0 160 100" className="w-40 text-accent-ink" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
        <m.path initial={{ d: TILTED }} animate={{ d: [TILTED, FLAT, FLAT, TILTED] }} transition={loop} />
        <m.path initial={{ d: MID_TILTED }} animate={{ d: [MID_TILTED, MID_FLAT, MID_FLAT, MID_TILTED] }} transition={loop} />
        <m.ellipse cx="80" cy="54" rx="13" initial={{ ry: 7 }} animate={{ ry: [7, 13, 13, 7] }} transition={loop} />
      </g>
    </svg>
  )
}
