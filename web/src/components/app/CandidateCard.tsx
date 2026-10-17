import { ArrowRight } from 'lucide-react'
import Badge from '../ui/Badge'
import Cited from '../ui/Cited'
import { Button } from '../ui/Button'
import type { ExplanationCandidate, TimelineEvent } from '../../data'
import { formatClock } from '../../data/time'

/** A candidate the agent checked but did not alert, or one it never checked. */
export default function CandidateCard({
  event,
  teamName,
  explanation,
  onJump,
  onOpenTrace,
}: {
  event: TimelineEvent
  teamName: string
  explanation: ExplanationCandidate | undefined
  onJump: (t: number) => void
  onOpenTrace: () => void
}) {
  const checked = event.status !== 'candidate'
  return (
    <article className="rounded-(--radius-card) border border-line bg-surface p-6" aria-labelledby={`cand-${event.id}`}>
      <div className="flex items-center justify-between gap-2">
        <Badge status={event.status}>{checked ? `${event.status} · no alert` : 'not checked'}</Badge>
        <button
          type="button"
          onClick={() => onJump(event.t)}
          className="rounded-md font-mono text-base text-muted underline-offset-4 hover:text-text hover:underline"
          aria-label={`Jump to ${formatClock(event.t)}`}
        >
          {formatClock(event.t)}
        </button>
      </div>
      <h2 id={`cand-${event.id}`} className="mt-4 font-display text-3xl leading-tight font-semibold text-text">
        {teamName}: <span className="whitespace-nowrap">{event.from}</span> → <span className="whitespace-nowrap">{event.to}</span>
      </h2>
      {checked ? (
        <>
          {explanation && (
            <p className="mt-3 text-lg leading-relaxed text-text">
              <Cited text={explanation.after} />
            </p>
          )}
          {event.id === 'evt_007' && (
            <p className="mt-3 text-sm text-warn">A known miss: this real change held 220 s.</p>
          )}
          <Button variant="ghost" className="mt-5" onClick={onOpenTrace}>
            See how it checked <ArrowRight className="size-4" aria-hidden="true" />
          </Button>
        </>
      ) : (
        <p className="mt-3 text-lg text-muted">A first-pass reading. The agent did not check this one.</p>
      )}
    </article>
  )
}
