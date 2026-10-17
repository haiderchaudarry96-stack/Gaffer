import Badge from '../ui/Badge'
import Cited from '../ui/Cited'
import type { ExplanationCandidate, TimelineEvent } from '../../data'
import { formatClock } from '../../data/time'

/** A candidate the agent checked but did not alert, or one it never checked. */
export default function CandidateCard({
  event,
  teamName,
  explanation,
  onJump,
}: {
  event: TimelineEvent
  teamName: string
  explanation: ExplanationCandidate | undefined
  onJump: (t: number) => void
}) {
  return (
    <article className="rounded-(--radius-card) border border-line bg-surface p-4" aria-labelledby={`cand-${event.id}`}>
      <div className="flex items-center justify-between gap-2">
        <Badge status={event.status}>{event.status === 'candidate' ? 'not checked' : `${event.status} · no alert`}</Badge>
        <button
          type="button"
          onClick={() => onJump(event.t)}
          className="rounded-md font-mono text-sm text-muted underline-offset-4 hover:text-text hover:underline"
          aria-label={`Jump to ${formatClock(event.t)}`}
        >
          {formatClock(event.t)}
        </button>
      </div>
      <h3 id={`cand-${event.id}`} className="mt-2 font-display text-lg font-semibold text-text">
        {teamName}: {event.from} → {event.to} <span className="font-mono text-xs font-normal text-muted">{event.id}</span>
      </h3>
      {event.status === 'candidate' ? (
        <p className="mt-2 text-sm text-muted">
          A first-pass reading from the tactics engine. The agent was not run on it in this window (each check costs
          minutes of OpenCV time on a laptop), so it is not a finding.
        </p>
      ) : (
        <>
          {explanation && (
            <p className="mt-2 text-sm leading-relaxed text-text">
              <Cited text={explanation.after} />
            </p>
          )}
          {event.reason && (
            <p className="mt-2 rounded-xl border border-line bg-bg/60 px-3 py-2 text-xs text-muted">
              <span className="font-semibold text-text">Rules verdict (code): </span>
              {event.reason}
            </p>
          )}
          {event.id === 'evt_007' && (
            <p className="mt-2 text-xs leading-relaxed text-warn">
              Known miss: the 6 fps second look still saw 4-2-3-1 in 100 % of 12 readings and the ground truth shows it
              held 220 s. The return-leg rule rejects it; the tested fix added 25 false alerts on synthetic data, so it
              stays off.
            </p>
          )}
        </>
      )}
    </article>
  )
}
