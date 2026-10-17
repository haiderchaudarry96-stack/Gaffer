import { useEffect, useRef, useState } from 'react'
import type { PlaybackClock } from '../../lib/clock'
import { useClockTime } from '../../lib/hooks'
import type { EventStatus, FormationTimeline as TL, TeamSide, TimelineEvent } from '../../data'
import { formatClock } from '../../data/time'
import { Skeleton } from '../ui/States'

const MARKER: Record<EventStatus, string> = {
  confirmed: 'bg-accent border-accent',
  rejected: 'bg-danger border-danger',
  uncertain: 'bg-warn border-warn',
  candidate: 'bg-surface border-muted',
}
const STATUS_TEXT: Record<EventStatus, string> = {
  confirmed: 'verified by the agent',
  rejected: 'rejected by the agent',
  uncertain: 'uncertain',
  candidate: 'not checked',
}
/** approximate width of one 12 px JetBrains Mono character, plus the label's padding */
const CHAR_PX = 7.3
const LABEL_PAD_PX = 18

export interface ShownEvent {
  event: TimelineEvent
  status: EventStatus
  /** live replay: spotted, being checked */
  pending: boolean
}

function Marker({
  e,
  name,
  selected,
  onSelect,
}: {
  e: ShownEvent
  name: string
  selected: boolean
  onSelect: (e: TimelineEvent) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(e.event)}
      className={`grid size-7 place-items-center rounded-full ${selected ? 'bg-text/10 ring-1 ring-text' : 'hover:bg-text/10'}`}
      aria-label={`${formatClock(e.event.t)} ${name} ${e.event.from} to ${e.event.to}, ${e.pending ? 'being checked' : STATUS_TEXT[e.status]}`}
      aria-pressed={selected}
    >
      <span className="relative grid place-items-center">
        {e.pending && <span className="absolute size-4 animate-ping rounded-full bg-warn/60 motion-reduce:hidden" />}
        <span className={`size-3 rotate-45 border-2 ${e.pending ? 'border-warn bg-warn' : MARKER[e.status]}`} />
      </span>
    </button>
  )
}

export default function FormationTimeline({
  clock,
  timeline,
  events,
  selected,
  onSelect,
}: {
  clock: PlaybackClock
  timeline: TL | null
  events: ShownEvent[]
  selected: string | null
  onSelect: (e: TimelineEvent) => void
}) {
  const t = useClockTime(clock, 8)
  // measure the bar so a label is drawn only where it fits completely (never truncated)
  const barRef = useRef<HTMLDivElement>(null)
  const [barPx, setBarPx] = useState(0)
  useEffect(() => {
    const el = barRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setBarPx(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [timeline])
  if (!timeline) return <Skeleton className="h-44" />
  const { start_s, end_s } = timeline
  const frac = (s: number) => (Math.min(end_s, Math.max(start_s, s)) - start_s) / (end_s - start_s)
  const pct = (s: number) => `${frac(s) * 100}%`
  const minutes: number[] = []
  for (let m = Math.ceil(start_s / 60) * 60; m <= end_s; m += 60) minutes.push(m)
  const sides: TeamSide[] = ['home', 'away']

  return (
    <section aria-labelledby="timeline-title" className="rounded-(--radius-card) border border-line bg-surface px-4 py-4 sm:px-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="timeline-title" className="font-sans text-base font-semibold tracking-normal text-text">
          Shape timeline
        </h2>
        <p className="text-xs text-muted">
          <span className="hidden sm:inline">Diamonds mark shape changes. Click one to jump.</span>
          <span className="sm:hidden">Tap a change below to jump there.</span>
        </p>
      </div>

      {sides.map((side) => {
        const own = events.filter((e) => e.event.team === side)
        return (
          <div key={side} className="mb-2 grid grid-cols-[4.5rem_1fr] items-end gap-3 sm:grid-cols-[5.5rem_1fr]">
            <span className="flex items-center gap-1.5 pb-2 text-sm font-medium text-text">
              <span className={`size-2.5 rounded-full ${side === 'home' ? 'bg-team-a' : 'bg-team-b'}`} aria-hidden="true" />
              {timeline.teamNames[side]}
            </span>
            <div ref={side === 'home' ? barRef : undefined}>
              {/* marker lane, above the bar so labels are never covered */}
              <div className="relative h-7">
                {own.map((e) => (
                  <div key={e.event.id} className="absolute top-0 -translate-x-1/2" style={{ left: pct(e.event.t) }}>
                    {/* buttons from 640 px up; on narrow screens the diamonds are decoration and the list below is the control */}
                    <div className="hidden sm:block">
                      <Marker e={e} name={timeline.teamNames[side]} selected={selected === e.event.id} onSelect={onSelect} />
                    </div>
                    <span className="grid size-7 place-items-center sm:hidden" aria-hidden="true">
                      <span className={`size-2.5 rotate-45 border-2 ${e.pending ? 'border-warn bg-warn' : MARKER[e.status]}`} />
                    </span>
                  </div>
                ))}
              </div>
              <ol className="relative h-9" aria-label={`${timeline.teamNames[side]} shapes`}>
                {timeline.segments.map((s, i) => {
                  const f = s[side].formation
                  const label = f === 'uncertain' ? '' : f
                  const fits = label !== '' && (frac(s.end_s) - frac(s.start_s)) * barPx >= label.length * CHAR_PX + LABEL_PAD_PX
                  return (
                    <li
                      key={i}
                      title={`${formatClock(s.start_s)}–${formatClock(s.end_s)} ${f === 'uncertain' ? 'unsettled' : f}`}
                      className={`absolute inset-y-0 overflow-hidden rounded-md ${f === 'uncertain' ? 'border border-dashed border-line' : 'bg-surface-2'}`}
                      style={{ left: pct(s.start_s), width: `calc(${(frac(s.end_s) - frac(s.start_s)) * 100}% - 2px)` }}
                    >
                      <span className="sr-only">
                        {formatClock(s.start_s)} to {formatClock(s.end_s)}: {f === 'uncertain' ? 'unsettled' : f}
                      </span>
                      {/* labels only where they fit completely; dashed = shape unsettled */}
                      {fits && (
                        <span aria-hidden="true" className="block px-2 pt-2 font-mono text-xs whitespace-nowrap text-text">
                          {label}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ol>
            </div>
          </div>
        )
      })}

      <div className="relative ml-[5.25rem] h-5 sm:ml-[6.25rem]">
        {minutes.map((m, i) => (
          <span
            key={m}
            className={`absolute top-1 -translate-x-1/2 font-mono text-[11px] text-muted ${i % 2 ? 'hidden sm:inline' : ''}`}
            style={{ left: pct(m) }}
          >
            {formatClock(m)}
          </span>
        ))}
        <span className="pointer-events-none absolute -top-[9.5rem] h-[9.5rem] w-0.5 -translate-x-1/2 rounded bg-accent" style={{ left: pct(t) }} aria-hidden="true" />
      </div>

      {/* narrow screens: the changes as a readable list instead of tiny bar labels */}
      <ul className="mt-3 space-y-1 sm:hidden" aria-label="Shape changes">
        {events.map((e) => (
            <li key={e.event.id}>
              <button
                type="button"
                onClick={() => onSelect(e.event)}
                aria-pressed={selected === e.event.id}
                className={`flex min-h-11 w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-surface-2 ${selected === e.event.id ? 'bg-surface-2' : ''}`}
              >
                <span className={`size-2.5 rotate-45 border-2 ${e.pending ? 'border-warn bg-warn' : MARKER[e.status]}`} aria-hidden="true" />
                <span className="font-mono text-muted">{formatClock(e.event.t)}</span>
                <span className="text-text">
                  {timeline.teamNames[e.event.team]} <span className="whitespace-nowrap">{e.event.from}</span> →{' '}
                  <span className="whitespace-nowrap">{e.event.to}</span>
                </span>
                <span className="ml-auto text-xs whitespace-nowrap text-muted">{e.pending ? 'checking' : e.status === 'confirmed' ? 'verified' : e.status === 'candidate' ? 'not checked' : e.status}</span>
              </button>
            </li>
          ))}
      </ul>
    </section>
  )
}
