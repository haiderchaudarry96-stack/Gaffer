import { CheckCircle2, XCircle } from 'lucide-react'
import { SECONDS_PER_VIDEO_SECOND } from '../../data/analysis'

/** A pitch outline from a camera's point of view: a trapezoid (top near/far) plus a halfway line. */
function Pitch({ near, far, y0 = 20, y1 = 76, clip = false }: { near: number; far: number; y0?: number; y1?: number; clip?: boolean }) {
  const cx = 60
  const pts = `${cx - far},${y0} ${cx + far},${y0} ${cx + near},${y1} ${cx - near},${y1}`
  return (
    <g>
      <polygon points={pts} fill="#2f7d45" stroke="#e8f5e9" strokeWidth="1.5" />
      <line x1={cx} y1={y0} x2={cx} y2={y1} stroke="#e8f5e9" strokeWidth="1.2" />
      {!clip && <ellipse cx={cx} cy={(y0 + y1) / 2} rx={(near + far) / 9} ry={(y1 - y0) / 7} fill="none" stroke="#e8f5e9" strokeWidth="1.2" />}
    </g>
  )
}

function Players({ spread = 1 }: { spread?: number }) {
  const dots = [[30, 40, 'a'], [44, 58, 'a'], [52, 34, 'a'], [70, 50, 'b'], [82, 36, 'b'], [90, 62, 'b']] as const
  return (
    <g>
      {dots.map(([x, y, t], i) => (
        <circle key={i} cx={60 + (x - 60) * spread} cy={y} r="2.6" fill={t === 'a' ? 'var(--team-a)' : 'var(--team-b)'} />
      ))}
    </g>
  )
}

const CARDS = [
  {
    ok: true,
    title: 'Good: high, fixed camera',
    text: 'Top-down drone or a high fixed camera that shows the whole pitch, all four corners, all match.',
    art: (
      <>
        <Pitch near={46} far={46} y0={16} y1={80} />
        <Players />
      </>
    ),
  },
  {
    ok: false,
    title: 'Not supported: TV broadcast',
    text: 'Zoomed in on the ball, cuts between cameras, overlays: most of the pitch is out of view.',
    art: (
      <>
        <rect x="0" y="0" width="120" height="96" fill="#2f7d45" />
        <line x1="78" y1="0" x2="62" y2="96" stroke="#e8f5e9" strokeWidth="1.5" />
        <Players spread={1.6} />
        <rect x="6" y="6" width="34" height="11" rx="2" fill="#0b1510" opacity="0.85" />
        <text x="23" y="14.5" fontSize="7" textAnchor="middle" fill="#fff" fontFamily="monospace">1 - 0</text>
      </>
    ),
  },
  {
    ok: false,
    title: 'Not supported: side or panning camera',
    text: 'Low on the touchline or following play: the far side is squashed and the view keeps moving.',
    art: (
      <>
        <Pitch near={58} far={22} y0={44} y1={86} clip />
        <Players spread={0.7} />
        <path d="M22 26 h76 M90 20 l8 6 l-8 6 M30 20 l-8 6 l8 6" stroke="var(--color-muted, #7a8a80)" strokeWidth="2" fill="none" strokeLinecap="round" />
      </>
    ),
  },
]

/** What footage works, with the upload limits and a realistic wait (before choosing a file). */
export default function FootageGuide() {
  const perMinute = Math.round(60 * SECONDS_PER_VIDEO_SECOND / 6) / 10 // minutes of processing per video minute
  return (
    <section aria-labelledby="footage-guide-title" className="rounded-2xl border border-line bg-bg p-4">
      <h3 id="footage-guide-title" className="text-sm font-semibold text-text">What footage works</h3>
      <ul className="mt-3 grid gap-3 sm:grid-cols-3">
        {CARDS.map((c) => (
          <li key={c.title} className={`rounded-xl border p-3 ${c.ok ? 'border-accent/50' : 'border-line'}`}>
            <svg viewBox="0 0 120 96" className="w-full rounded-lg" role="img" aria-label={c.title}>
              {c.art}
            </svg>
            <p className={`mt-2 flex items-center gap-1.5 text-sm font-medium ${c.ok ? 'text-accent-ink' : 'text-danger'}`}>
              {c.ok ? <CheckCircle2 className="size-4 shrink-0" aria-hidden="true" /> : <XCircle className="size-4 shrink-0" aria-hidden="true" />}
              {c.title}
            </p>
            <p className="mt-1 text-xs text-muted">{c.text}</p>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">
        Limits: up to <strong className="text-text">6 minutes</strong> and <strong className="text-text">500 MB</strong>, MP4 or MOV,
        two teams in clearly different shirts. Expect about {perMinute} minutes of processing per minute of video on
        the demo server (a 6-minute clip takes roughly {Math.round(6 * perMinute)} minutes), plus the agent’s checks.
      </p>
    </section>
  )
}
