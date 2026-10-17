import Panel from './Panel'
import type { PlaybackClock } from '../../lib/clock'
import { useClockTime } from '../../lib/hooks'
import type { EventStatus, FormationTimeline as TL, TeamSide, TimelineEvent } from '../../data'
import { formatClock } from '../../data/time'
import { Skeleton } from '../ui/States'

const MARKER: Record<EventStatus, string> = {
  confirmed: 'bg-accent border-accent',
  rejected: 'bg-danger border-danger',
  uncertain: 'bg-warn border-warn',
  candidate: 'bg-bg border-muted',
}
const STATUS_TEXT: Record<EventStatus, string> = {
  confirmed: 'confirmed by the agent',
  rejected: 'rejected by the agent',
  uncertain: 'marked uncertain by the agent',
  candidate: 'candidate, not checked by the agent',
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted" aria-label="Marker legend">
      {(['confirmed', 'uncertain', 'rejected', 'candidate'] as const).map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <span className={`size-2.5 rotate-45 border ${MARKER[s]}`} aria-hidden="true" />
          {s === 'candidate' ? 'not checked' : s}
        </li>
      ))}
    </ul>
  )
}

export default function FormationTimeline({
  clock,
  timeline,
  selected,
  onSelect,
}: {
  clock: PlaybackClock
  timeline: TL | null
  selected: string | null
  onSelect: (e: TimelineEvent) => void
}) {
  const t = useClockTime(clock, 8)
  if (!timeline) {
    return (
      <Panel title="Formation timeline" id="timeline-title">
        <div className="space-y-3 p-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      </Panel>
    )
  }
  const { start_s, end_s } = timeline
  const pct = (s: number) => `${((s - start_s) / (end_s - start_s)) * 100}%`
  const minutes: number[] = []
  for (let m = Math.ceil(start_s / 60) * 60; m <= end_s; m += 60) minutes.push(m)

  return (
    <Panel title="Formation timeline" id="timeline-title" actions={<Legend />}>
      <div className="overflow-x-auto px-4 pt-3 pb-4">
        <div className="min-w-[640px]">
          {(['home', 'away'] as TeamSide[]).map((side) => (
            <div key={side} className="mb-3 grid grid-cols-[84px_1fr] items-center gap-3">
              <span className="flex items-center gap-1.5 text-sm font-medium text-text">
                <span className={`size-2.5 rounded-full ${side === 'home' ? 'bg-team-a' : 'bg-team-b'}`} aria-hidden="true" />
                {timeline.teamNames[side]}
              </span>
              <div className="relative h-11">
                <ol className="absolute inset-0" aria-label={`${timeline.teamNames[side]} first-pass formations`}>
                  {timeline.segments.map((s, i) => {
                    const f = s[side].formation
                    return (
                      <li
                        key={i}
                        className={`absolute inset-y-1 overflow-hidden rounded-md border px-1.5 ${f === 'uncertain' ? 'border-dashed border-line bg-transparent' : 'border-line bg-surface-2'}`}
                        style={{ left: pct(s.start_s), width: `calc(${pct(s.end_s)} - ${pct(s.start_s)} - 2px)` }}
                        title={`${formatClock(s.start_s)}–${formatClock(s.end_s)}: ${f}`}
                      >
                        <span className="sr-only">
                          {formatClock(s.start_s)} to {formatClock(s.end_s)}:{' '}
                        </span>
                        <span className={`block truncate pt-2 font-mono text-xs ${f === 'uncertain' ? 'text-muted' : 'text-text'}`}>
                          {f === 'uncertain' ? 'unclear' : f}
                        </span>
                      </li>
                    )
                  })}
                </ol>
                {timeline.events
                  .filter((e) => e.team === side)
                  .map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => onSelect(e)}
                      className={`absolute top-1/2 z-10 grid size-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full ${selected === e.id ? 'bg-text/15 ring-1 ring-text' : 'hover:bg-text/10'}`}
                      style={{ left: pct(e.t) }}
                      aria-label={`${e.id} at ${formatClock(e.t)}: ${timeline.teamNames[side]} ${e.from} to ${e.to}, ${STATUS_TEXT[e.status]}. Jump there.`}
                      aria-pressed={selected === e.id}
                    >
                      <span className={`size-3 rotate-45 border-2 ${MARKER[e.status]} ${e.status === 'confirmed' ? 'shadow-[0_0_10px_var(--accent)]' : ''}`} />
                    </button>
                  ))}
              </div>
            </div>
          ))}
          <div className="relative ml-[96px] h-5 border-t border-line">
            {minutes.map((m) => (
              <span key={m} className="absolute top-1 -translate-x-1/2 font-mono text-[10px] text-muted" style={{ left: pct(m) }}>
                {formatClock(m)}
              </span>
            ))}
            {/* playhead */}
            <span
              className="pointer-events-none absolute -top-[7rem] h-[7rem] w-px bg-accent"
              style={{ left: pct(Math.min(end_s, Math.max(start_s, t))) }}
              aria-hidden="true"
            />
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Bars: the tactics engine’s first-pass reading (no confidence values in this sample). Markers: every candidate
            change; the agent checked two of them in this window. Click a marker to jump there.
          </p>
        </div>
      </div>
    </Panel>
  )
}
