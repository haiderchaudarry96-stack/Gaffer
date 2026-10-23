/**
 * Decorative pitch for the idle desk ("Waiting to start"). It is NOT data: 11 soft neutral dots
 * (no team colours, no labels, no clock) drift slowly between two loose shapes (a ring and a
 * wave) that are not formations. With prefers-reduced-motion it is a still image.
 */

import type { CSSProperties } from 'react'

// pitch 105 x 68 m drawn in a 110 x 73 box (2.5 m margin), like the real minimap
const W = 105
const H = 68

// two loose arrangements (pitch metres); each dot drifts from A to B and back
const RING = Array.from({ length: 11 }, (_, i) => {
  const a = (i / 11) * Math.PI * 2
  return [W / 2 + Math.cos(a) * 22, H / 2 + Math.sin(a) * 16] as const
})
const WAVE = Array.from({ length: 11 }, (_, i) => [14 + i * 7.7, H / 2 + Math.sin(i * 0.9) * 13] as const)

export default function AmbientPitch({ reduced, className = '' }: { reduced: boolean; className?: string }) {
  return (
    <div className={`relative ${className}`} data-decorative="true">
      <svg viewBox="-2.5 -2.5 110 73" className="size-full text-muted" aria-hidden="true" focusable="false">
        <g fill="none" stroke="currentColor" strokeOpacity="0.28" strokeWidth="0.4">
          <rect x="0" y="0" width={W} height={H} rx="0.5" />
          <line x1={W / 2} y1="0" x2={W / 2} y2={H} />
          <circle cx={W / 2} cy={H / 2} r="9.15" />
          <rect x="0" y={H / 2 - 20.16} width="16.5" height="40.32" />
          <rect x={W - 16.5} y={H / 2 - 20.16} width="16.5" height="40.32" />
        </g>
        {!reduced && (
          // a slow scan line over the markings: clearly an effect, not a reading
          <rect className="ambient-scan" x="-8" y="-2.5" width="6" height="73" fill="currentColor" fillOpacity="0.06" />
        )}
        {/* CSS animations (index.css), not SMIL: Chrome sometimes never schedules a SMIL frame for
            an SVG that React inserts during a slow first load, so the dots stood still. */}
        <g fill="currentColor" fillOpacity="0.32">
          {RING.map(([x, y], i) => {
            const [bx, by] = WAVE[(i * 4) % 11]
            const drift = {
              '--dx': `${(bx - x).toFixed(1)}px`, // px = user units inside the SVG
              '--dy': `${(by - y).toFixed(1)}px`,
              animationDuration: `${22 + (i % 4) * 3}s`,
            } as CSSProperties
            return <circle key={i} cx={x} cy={y} r="1.3" className={reduced ? undefined : 'ambient-dot'} style={reduced ? undefined : drift} />
          })}
        </g>
      </svg>
      <p className="absolute inset-x-0 bottom-3 text-center font-mono text-xs tracking-widest text-muted uppercase">
        Waiting to start
      </p>
    </div>
  )
}
