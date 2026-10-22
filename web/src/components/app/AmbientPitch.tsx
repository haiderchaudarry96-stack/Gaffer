/**
 * Decorative pitch for the idle desk ("Waiting to start"). It is NOT data: 11 soft neutral dots
 * (no team colours, no labels, no clock) drift slowly between two loose shapes (a ring and a
 * wave) that are not formations. With prefers-reduced-motion it is a still image.
 */

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
          <rect x="-2.5" y="-2.5" width="6" height="73" fill="currentColor" fillOpacity="0.06">
            <animate attributeName="x" values="-8;108;-8" dur="16s" repeatCount="indefinite" />
          </rect>
        )}
        <g fill="currentColor" fillOpacity="0.32">
          {RING.map(([x, y], i) => {
            const [bx, by] = WAVE[(i * 4) % 11]
            return (
              <circle key={i} cx={x} cy={y} r="1.3">
                {!reduced && (
                  <animateTransform attributeName="transform" type="translate" dur={`${22 + (i % 4) * 3}s`}
                    values={`0 0; ${(bx - x).toFixed(1)} ${(by - y).toFixed(1)}; 0 0`} keyTimes="0; 0.5; 1"
                    calcMode="spline" keySplines="0.45 0 0.55 1; 0.45 0 0.55 1" repeatCount="indefinite" />
                )}
              </circle>
            )
          })}
        </g>
      </svg>
      <p className="absolute inset-x-0 bottom-3 text-center font-mono text-xs tracking-widest text-muted uppercase">
        Waiting to start
      </p>
    </div>
  )
}
