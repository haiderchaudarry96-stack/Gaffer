import { CheckCircle2 } from 'lucide-react'
import Panel from './Panel'
import PitchCanvas from '../pitch/PitchCanvas'
import type { PositionIndex } from '../pitch/positions'
import type { PlaybackClock } from '../../lib/clock'
import { useClockTime } from '../../lib/hooks'
import type { FormationTimeline, MatchState, TeamSide, TimelineEvent } from '../../data'
import { formationAt } from '../../data/timeline'
import { formatClock } from '../../data/time'
import { Skeleton } from '../ui/States'

/** The latest agent-confirmed change of a team at or before t, if the team still shows that shape. */
function verifiedAt(tl: FormationTimeline, side: TeamSide, t: number, current: string | null): TimelineEvent | null {
  const decided = tl.events.filter((e) => e.team === side && e.t <= t && e.status !== 'candidate').at(-1)
  return decided && decided.status === 'confirmed' && decided.to === current ? decided : null
}

export default function Minimap({
  clock,
  index,
  match,
  timeline,
}: {
  clock: PlaybackClock
  index: PositionIndex | null
  match: MatchState | null
  timeline: FormationTimeline | null
}) {
  const t = useClockTime(clock, 6)
  const names = timeline?.teamNames ?? { home: 'White', away: 'Blue' }
  const counts = index?.countsAt(t)

  return (
    <Panel
      title="Pitch · tracked positions"
      id="minimap-title"
      actions={<span className="font-mono text-sm text-text tabular">{formatClock(t)}</span>}
    >
      <div className="grid grid-cols-2 gap-3 px-4 pt-4">
        {(['home', 'away'] as const).map((side) => {
          const f = timeline ? formationAt(timeline, side, t) : null
          const v = timeline ? verifiedAt(timeline, side, t, f) : null
          return (
            <div key={side}>
              <p className="flex items-center gap-1.5 text-xs text-muted">
                <span className={`size-2.5 rounded-full ${side === 'home' ? 'bg-team-a' : 'bg-team-b'}`} aria-hidden="true" />
                {names[side]} <span>({side})</span>
              </p>
              {counts && <p className="font-mono text-[11px] text-muted tabular">{counts[side]} outfield in a team now</p>}
              <p className="font-mono text-4xl font-semibold tracking-tight text-text tabular" aria-live="polite">
                {f === 'uncertain' ? <span className="text-xl font-medium text-muted">unclear</span> : (f ?? '—')}
              </p>
              <p className="mt-0.5 flex min-h-5 items-center gap-1 text-xs">
                {v ? (
                  <span className="inline-flex items-center gap-1 text-accent">
                    <CheckCircle2 className="size-3.5" aria-hidden="true" /> confirmed by the agent ({v.id})
                  </span>
                ) : (
                  <span className="text-muted">first-pass reading</span>
                )}
              </p>
            </div>
          )
        })}
      </div>
      <div className="p-3">
        {match ? (
          <PitchCanvas
            index={index}
            pitch={match.pitch}
            clock={clock}
            variant="mini"
            className="aspect-[110/73] w-full"
            label={`Top-down pitch at ${formatClock(t)}: ${names.home} in coral, ${names.away} in sky blue, referees as small grey dots, players without a team yet as hollow rings. Goalkeepers have a dark centre.`}
          />
        ) : (
          <Skeleton className="aspect-[110/73] w-full" />
        )}
        <p className="mt-2 text-[11px] leading-snug text-muted">
          Dot colours are Gaffer’s team colours, not shirt colours ({names.home} = coral, {names.away} = sky blue). Small
          grey dots: referees. Hollow rings: players OpenCV sees but has not yet put in a team. Ball not shown: the drone
          pipeline does not detect it.
        </p>
      </div>
    </Panel>
  )
}
