import { useEffect, useMemo } from 'react'
import { m } from 'motion/react'
import { ArrowDown, ArrowRight } from 'lucide-react'
import PitchCanvas from '../pitch/PitchCanvas'
import { ButtonLink } from '../ui/Button'
import { PlaybackClock } from '../../lib/clock'
import { useClockTime, usePrefersReducedMotion } from '../../lib/hooks'
import { getTimeline, usePositions } from '../../lib/matchData'
import { useResource } from '../../data/useResource'
import { formationAt } from '../../data/timeline'
import { formatClock } from '../../data/time'

const HEADLINE = 'See the shape change before the scoreline does.'
const TAGLINE = 'Your tactical analyst. It watches, checks, then tells you.'
/** 16:45: the frame the agent used as evidence for the 16:30 change */
const STILL_T = 1005
const PITCH = { length_m: 105, width_m: 68 }

function FormationText({ value }: { value: string | null }) {
  if (!value) return <>—</>
  if (value === 'uncertain') return <span className="text-base font-medium text-muted">unclear</span>
  return <>{value}</>
}

function LiveHud({ clock }: { clock: PlaybackClock }) {
  const t = useClockTime(clock, 4)
  const tl = useResource(getTimeline, 'timeline')
  const names = tl.status === 'ready' ? tl.data.teamNames : { home: 'White', away: 'Blue' }
  const home = tl.status === 'ready' ? formationAt(tl.data, 'home', t) : null
  const away = tl.status === 'ready' ? formationAt(tl.data, 'away', t) : null
  return (
    <div className="pointer-events-none absolute right-4 bottom-6 z-10 w-[min(19rem,calc(100%-2rem))] rounded-(--radius-card) border border-line bg-surface/80 p-4 backdrop-blur-md sm:right-8 sm:bottom-10">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2 font-mono text-[11px] tracking-widest text-muted uppercase">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-60 motion-reduce:hidden" />
            <span className="relative inline-flex size-2 rounded-full bg-accent" />
          </span>
          Replay · drone view
        </span>
        <span className="font-mono text-sm text-text tabular" aria-label={`Match clock ${formatClock(t)}`}>
          {formatClock(t)}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-3">
        {(['home', 'away'] as const).map((side) => (
          <div key={side}>
            <dt className="flex items-center gap-1.5 text-xs text-muted">
              <span className={`size-2 rounded-full ${side === 'home' ? 'bg-team-a' : 'bg-team-b'}`} aria-hidden="true" />
              {names[side]}
            </dt>
            <dd className="font-mono text-2xl font-semibold text-text tabular">
              <FormationText value={side === 'home' ? home : away} />
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[11px] leading-snug text-muted">First-pass shape reading, before the agent checks it.</p>
    </div>
  )
}

export default function Hero() {
  const reduced = usePrefersReducedMotion()
  const { res, index } = usePositions()
  const clock = useMemo(
    () => new PlaybackClock({ min: 900, max: 1259.5, start: 960, rate: 3, loop: true }),
    [],
  )

  useEffect(() => {
    if (reduced) {
      clock.pause()
      clock.seek(STILL_T)
    } else if (index) {
      clock.play()
    }
    return () => clock.pause()
  }, [clock, reduced, index])

  const words = HEADLINE.split(' ')

  return (
    <section aria-labelledby="hero-title" className="grain relative isolate flex min-h-[100svh] items-center overflow-hidden">
      {/* floodlight glow + pitch-line texture */}
      <div
        className="absolute inset-0 -z-20"
        style={{
          background:
            'radial-gradient(60% 50% at 70% 35%, rgba(200,245,66,0.08), transparent 70%), radial-gradient(80% 60% at 50% 110%, rgba(22,35,28,0.9), var(--bg) 70%)',
        }}
        aria-hidden="true"
      />
      {/* the live pitch, tilted like a broadcast camera */}
      <div className="absolute inset-0 -z-10 [perspective:1400px]" aria-hidden={res.status !== 'ready'}>
        <m.div
          className="absolute inset-x-[-20%] top-[52%] bottom-[-14%] origin-bottom sm:inset-x-[-6%] sm:top-[14%] lg:left-[18%] lg:right-[-8%]"
          style={{ rotateX: 36 }}
          initial={{ opacity: 0 }}
          animate={{ opacity: res.status === 'ready' ? 1 : 0.5 }}
          transition={{ duration: 0.8 }}
        >
          <PitchCanvas
            index={index}
            pitch={PITCH}
            clock={clock}
            variant="hero"
            trails={!reduced}
            className="size-full"
            label="Animated top-down pitch: real tracked player positions from the TeamTrack drone clip, 15:00 to 21:00, White in coral, Blue in sky blue."
          />
        </m.div>
      </div>
      {/* darkening gradients so the copy stays readable */}
      <div
        className="absolute inset-0 -z-10 bg-[linear-gradient(90deg,var(--bg)_0%,rgba(7,13,10,0.8)_32%,rgba(7,13,10,0)_70%),linear-gradient(180deg,rgba(7,13,10,0.9)_0%,transparent_30%,transparent_70%,var(--bg)_100%)]"
        aria-hidden="true"
      />

      <div className="mx-auto w-full max-w-7xl px-4 pt-28 pb-56 sm:px-6 sm:pb-40">
        <m.p
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 px-3 py-1 font-mono text-[11px] tracking-widest text-muted uppercase backdrop-blur"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        >
          OpenCV 5 · self-checking agent · for coaches
        </m.p>
        <h1
          id="hero-title"
          className="max-w-3xl font-display text-[2.6rem] leading-[1.02] font-bold text-text sm:text-6xl lg:text-[5.25rem]"
        >
          {words.map((w, i) => (
            <span key={i} className="inline-block overflow-hidden pb-1 align-bottom">
              <m.span
                className="inline-block"
                initial={{ y: '105%', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.1 + i * 0.07 }}
              >
                {w}
                {i < words.length - 1 ? ' ' : ''}
              </m.span>
            </span>
          ))}
        </h1>
        <m.p
          className="mt-6 max-w-xl text-lg text-muted sm:text-xl"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.65 }}
        >
          {TAGLINE}
        </m.p>
        <m.div
          className="mt-9 flex flex-wrap gap-3"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.8 }}
        >
          <ButtonLink to="/app" size="lg">
            Open the demo <ArrowRight className="size-4" aria-hidden="true" />
          </ButtonLink>
          <ButtonLink to="#how" variant="ghost" size="lg">
            How it checks <ArrowDown className="size-4" aria-hidden="true" />
          </ButtonLink>
        </m.div>
        <p className="mt-8 max-w-md text-xs leading-relaxed text-muted">
          The pitch behind this text is real data: player positions tracked by Gaffer’s OpenCV 5 pipeline on a TeamTrack
          drone clip (match time 15:00–21:00),{' '}
          {reduced ? 'shown as a still at 16:45 because your system asks for reduced motion' : 'replayed at 3× speed'}. No video, no
          mock-up.
          {res.status === 'error' && <span className="block text-warn">Positions could not be loaded: {res.error}</span>}
        </p>
      </div>
      <LiveHud clock={clock} />
    </section>
  )
}
