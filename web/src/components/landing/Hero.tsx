import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, m } from 'motion/react'
import { ArrowDown, ArrowRight } from 'lucide-react'
import PitchCanvas from '../pitch/PitchCanvas'
import { ButtonLink } from '../ui/Button'
import { PlaybackClock } from '../../lib/clock'
import { useClockTime, usePrefersReducedMotion } from '../../lib/hooks'
import { getTimeline, usePositions } from '../../lib/matchData'
import { HERO_WINDOW } from '../../lib/windows'
import { useResource } from '../../data/useResource'
import { displayFormation } from '../../data/timeline'
import { formatClock } from '../../data/time'
import type { EventStatus, FormationTimeline } from '../../data'

const HEADLINE = 'See the shape change before the scoreline does.'
const TAGLINE = 'Your tactical analyst. It watches, checks, then tells you.'
const PITCH = { length_m: 105, width_m: 68 }
const EASE = [0.22, 1, 0.36, 1] as const
const STATUS_WORD: Record<EventStatus, string> = {
  confirmed: 'verified',
  rejected: 'rejected',
  uncertain: 'uncertain',
  candidate: 'candidate',
}

function LiveHud({ clock, tl }: { clock: PlaybackClock; tl: FormationTimeline | null }) {
  const t = useClockTime(clock, 4)
  const names = tl?.teamNames ?? { home: 'White', away: 'Blue' }
  return (
    <div className="pointer-events-none absolute right-4 bottom-6 z-10 w-[min(18rem,calc(100%-2rem))] rounded-(--radius-card) border border-line bg-surface/80 p-4 backdrop-blur-md sm:right-8 sm:bottom-10">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2 font-mono text-[11px] tracking-widest text-muted uppercase">
          <span className="size-2 rounded-full bg-accent" aria-hidden="true" />
          Replay
        </span>
        <span className="font-mono text-sm text-text tabular">{formatClock(t)}</span>
      </div>
      <dl className="grid grid-cols-2 gap-3">
        {(['home', 'away'] as const).map((side) => {
          const shown = tl ? displayFormation(tl, side, t) : null
          return (
            <div key={side}>
              <dt className="flex items-center gap-1.5 text-xs text-muted">
                <span className={`size-2 rounded-full ${side === 'home' ? 'bg-team-a' : 'bg-team-b'}`} aria-hidden="true" />
                {names[side]} {side === 'home' ? '→' : '←'}
              </dt>
              <dd className="font-mono text-2xl font-semibold text-text tabular">{shown?.formation ?? '—'}</dd>
              {shown?.holding && <dd className="text-[11px] text-warn">holding</dd>}
            </div>
          )
        })}
      </dl>
    </div>
  )
}

/** Cycles real shape changes from the timeline under the headline (static with reduced motion). */
function ChangeTicker({ tl, reduced }: { tl: FormationTimeline | null; reduced: boolean }) {
  const items = useMemo(
    () =>
      (tl?.events ?? [])
        .slice()
        .sort((a, b) => Number(b.status !== 'candidate') - Number(a.status !== 'candidate') || a.t - b.t)
        .map((e) => ({ id: e.id, clock: formatClock(e.t), team: tl!.teamNames[e.team], from: e.from, to: e.to, status: e.status })),
    [tl],
  )
  const [i, setI] = useState(0)
  useEffect(() => {
    if (reduced || items.length < 2) return
    const id = setInterval(() => setI((n) => (n + 1) % items.length), 2600)
    return () => clearInterval(id)
  }, [reduced, items.length])
  const it = items[i % Math.max(1, items.length)]
  if (!it) return <div className="h-8" />
  return (
    <div className="mt-6 flex h-8 items-center gap-3 overflow-hidden font-mono text-[13px] whitespace-nowrap sm:text-base" aria-live="off">
      <span className="text-muted">{it.clock}</span>
      <AnimatePresence mode="wait" initial={false}>
        <m.span
          key={it.id}
          initial={{ y: '100%', opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: '-100%', opacity: 0 }}
          transition={{ duration: 0.35, ease: EASE }}
          className="inline-flex items-center gap-2 whitespace-nowrap text-text"
        >
          {it.team} {it.from} → {it.to}
          <span
            className={`rounded-full border px-2 py-0.5 text-[10px] uppercase sm:text-[11px] ${it.status === 'confirmed' ? 'border-accent/60 text-accent' : it.status === 'rejected' ? 'border-danger/60 text-danger' : 'border-line text-muted'}`}
          >
            {STATUS_WORD[it.status]}
          </span>
        </m.span>
      </AnimatePresence>
    </div>
  )
}

export default function Hero() {
  const reduced = usePrefersReducedMotion()
  const { res, index } = usePositions()
  const tl = useResource(getTimeline, 'timeline')
  const timeline = tl.status === 'ready' ? tl.data : null
  // HERO_WINDOW (19:16-20:20) is chosen from the data: see lib/windows.ts
  const clock = useMemo(
    () => new PlaybackClock({ min: HERO_WINDOW[0], max: HERO_WINDOW[1], start: HERO_WINDOW[0], rate: 2, loop: true }),
    [],
  )

  useEffect(() => {
    if (reduced) {
      clock.pause()
      clock.seek(HERO_WINDOW[0] + 20)
    } else if (index) clock.play()
    return () => clock.pause()
  }, [clock, reduced, index])

  const words = HEADLINE.split(' ')

  return (
    <section aria-labelledby="hero-title" className="grain relative isolate flex min-h-[100svh] items-center overflow-hidden bg-bg">
      <div
        className="absolute inset-0 -z-20"
        style={{
          background:
            'radial-gradient(55% 45% at 72% 30%, rgba(200,245,66,0.10), transparent 70%), radial-gradient(80% 60% at 50% 110%, rgba(22,35,28,0.9), var(--bg) 70%)',
        }}
        aria-hidden="true"
      />
      <div className="absolute inset-0 -z-10 [perspective:1400px]">
        <m.div
          className="absolute inset-x-[-25%] top-[50%] bottom-[-10%] origin-bottom sm:inset-x-[-6%] sm:top-[14%] sm:bottom-[-16%] lg:right-[-10%] lg:left-[38%] lg:top-[24%]"
          style={{ rotateX: 34 }}
          initial={{ opacity: 0 }}
          animate={{ opacity: res.status === 'ready' ? 1 : 0.4 }}
          transition={{ duration: 0.8 }}
        >
          <PitchCanvas
            index={index}
            pitch={PITCH}
            clock={clock}
            variant="hero"
            className="size-full"
            label="Replay of real tracked player positions from a TeamTrack drone match, 19:16 to 20:20. White in coral attacks right, Blue in sky blue attacks left."
          />
        </m.div>
      </div>
      <div
        className="absolute inset-0 -z-10 bg-[linear-gradient(90deg,var(--bg)_0%,rgba(7,13,10,0.85)_38%,rgba(7,13,10,0)_72%),linear-gradient(180deg,rgba(7,13,10,0.9)_0%,transparent_28%,transparent_72%,var(--bg)_100%)]"
        aria-hidden="true"
      />

      <div className="mx-auto w-full max-w-7xl px-4 pt-28 pb-64 sm:px-6 sm:pb-40">
        <h1 id="hero-title" className="max-w-4xl font-display text-[2.7rem] leading-[1.02] font-bold text-text sm:text-6xl lg:text-7xl xl:text-[5.25rem]">
          {words.map((w, i) => (
            <span key={i} className="inline-block overflow-hidden pb-1 align-bottom">
              <m.span
                className="inline-block"
                initial={{ y: '105%', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.6, ease: EASE, delay: 0.1 + i * 0.07 }}
              >
                {w}
                {i < words.length - 1 ? ' ' : ''}
              </m.span>
            </span>
          ))}
        </h1>
        <ChangeTicker tl={timeline} reduced={reduced} />
        <m.p
          className="mt-4 max-w-xl text-lg text-muted sm:text-xl"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.6 }}
        >
          {TAGLINE}
        </m.p>
        <m.div
          className="mt-9 flex flex-wrap gap-3"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.75 }}
        >
          <ButtonLink to="/app" size="lg">
            Open the demo <ArrowRight className="size-4" aria-hidden="true" />
          </ButtonLink>
          <ButtonLink to="#how" variant="ghost" size="lg">
            How it checks <ArrowDown className="size-4" aria-hidden="true" />
          </ButtonLink>
        </m.div>
        <p className="mt-6 text-xs text-muted">
          Real tracked positions · TeamTrack drone match
          {res.status === 'error' && <span className="block text-warn">Positions could not be loaded: {res.error}</span>}
        </p>
      </div>
      <LiveHud clock={clock} tl={timeline} />
    </section>
  )
}
