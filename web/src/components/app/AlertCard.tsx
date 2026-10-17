import { useState } from 'react'
import { m } from 'motion/react'
import { ArrowRight, Check, Loader2, Maximize2, RotateCcw, X } from 'lucide-react'
import Badge from '../ui/Badge'
import Cited from '../ui/Cited'
import { Button } from '../ui/Button'
import Dialog from './Dialog'
import { evidenceImageUrl, type Alert, type ReportEvent } from '../../data'
import { splitAlertExplanation } from '../../data/alerts'
import type { LivePhase, LivePlan } from '../../data/live'
import { formatClock } from '../../data/time'
import { STEP_NAMES } from './stepNames'

type LocalDecision = { status: 'approved' | 'rejected'; at: Date } | null


function evidenceAlt(alert: Alert, event: ReportEvent | undefined, team: string): string {
  const parts = [`Evidence for ${alert.event_id}: a drone video frame with ${team}'s players circled and their new formation lines drawn by OpenCV 5.`]
  if (event?.before && event.after) {
    parts.push(`Below, ${team}'s average shape ${event.before.window} (${event.before.formation}) next to ${event.after.window} (${event.after.formation}).`)
  }
  return parts.join(' ')
}

export interface LiveState {
  plan: LivePlan
  phase: LivePhase
  stepsDone: number
  stepTools: string[]
}

/** The one large alert card: live "checking" states, then the verified alert with evidence. */
export default function AlertCard({
  alert,
  event,
  teamName,
  live,
  onOpenTrace,
  onJump,
}: {
  alert: Alert
  event: ReportEvent | undefined
  teamName: string
  live: LiveState | null
  onOpenTrace: (ref?: string) => void
  onJump: (t: number) => void
}) {
  const [decision, setDecision] = useState<LocalDecision>(null)
  const [zoom, setZoom] = useState(false)
  const text = splitAlertExplanation(alert.explanation)
  const img = evidenceImageUrl(alert)
  const status = decision?.status ?? alert.status
  const alt = evidenceAlt(alert, event, teamName)
  const change = event?.change.replace('->', '→') ?? alert.title

  if (live && live.phase !== 'decided') {
    const { plan, phase, stepsDone, stepTools } = live
    const line =
      phase === 'spotted'
        ? `Spotted at ${formatClock(plan.onset)}. Watching whether it holds.`
        : phase === 'waiting'
          ? `Flagged at ${formatClock(plan.detected)}. Checks start after 60 s of play (${formatClock(plan.checksFrom)}).`
          : `Step ${stepsDone + 1} of ${stepTools.length}: ${STEP_NAMES[stepTools[stepsDone]] ?? stepTools[stepsDone]}.`
    return (
      <article aria-live="polite" className="rounded-(--radius-card) border border-warn/50 bg-surface p-6">
        <div className="flex items-center justify-between">
          <Badge status="uncertain">{phase === 'spotted' ? 'possible change' : 'checking'}</Badge>
          <span className="font-mono text-sm text-muted">{formatClock(plan.onset)}</span>
        </div>
        <h2 className="mt-4 font-display text-3xl font-semibold text-text">
          {teamName}: <span className="whitespace-nowrap">{event?.change.split('->')[0]?.trim()}</span> →{' '}
          <span className="whitespace-nowrap">{event?.change.split('->')[1]?.trim()}?</span>
        </h2>
        <p className="mt-3 flex items-start gap-2 text-base text-muted">
          <Loader2 className="mt-1 size-4 shrink-0 animate-spin text-warn motion-reduce:animate-none" aria-hidden="true" />
          {line}
        </p>
        {phase !== 'spotted' && (
          <div className="mt-5 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
            <div className="h-full origin-left rounded-full bg-warn transition-transform duration-500" style={{ transform: `scaleX(${stepsDone / stepTools.length})` }} />
          </div>
        )}
        <Button variant="ghost" className="mt-5" onClick={() => onOpenTrace()}>
          Watch the checks <ArrowRight className="size-4" aria-hidden="true" />
        </Button>
      </article>
    )
  }

  return (
    <m.article
      // transform only: the text can paint at once (no opacity fade)
      initial={{ y: 16, scale: 0.98 }}
      animate={{ y: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 260, damping: 26 }}
      aria-labelledby={`alert-${alert.alert_id}`}
      className={`overflow-hidden rounded-(--radius-card) border bg-surface ${status === 'pending' ? 'border-accent/60 glow-accent-strong' : 'border-line'}`}
    >
      <div className="space-y-4 p-6 pb-4">
        <div className="flex items-center justify-between gap-2">
          <span className="flex flex-wrap items-center gap-2">
            <Badge status="confirmed">verified</Badge>
            <Badge status={status}>{status === 'pending' ? 'waits for you' : status}</Badge>
          </span>
          <button
            type="button"
            onClick={() => onJump(alert.match_time_s)}
            className="rounded-md font-mono text-base text-muted underline-offset-4 hover:text-text hover:underline"
            aria-label={`Jump to ${formatClock(alert.match_time_s)}`}
          >
            {formatClock(alert.match_time_s)}
          </button>
        </div>
        <h2 id={`alert-${alert.alert_id}`} className="font-display text-3xl leading-tight font-semibold text-text">
          {teamName} switched to <span className="whitespace-nowrap">{event?.change.split('->')[1]?.trim() ?? change}</span>
        </h2>
        {text.explanation && (
          <p className="text-lg leading-relaxed text-text">
            <Cited text={text.explanation} onRef={(r) => onOpenTrace(r)} />
          </p>
        )}
        {img && (
          <button
            type="button"
            onClick={() => setZoom(true)}
            className="group relative block w-full overflow-hidden rounded-xl border border-line"
            aria-label="Enlarge the evidence image"
          >
            <img src={img} alt={alt} className="max-h-[30vh] w-full object-cover object-top" loading="lazy" width={1280} height={1341} />
            <span className="absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-full bg-bg/80 px-2.5 py-1 text-xs text-text">
              <Maximize2 className="size-3" aria-hidden="true" /> Evidence
            </span>
          </button>
        )}
      </div>

      <div className="space-y-2 border-t border-line px-6 py-4">
        {decision ? (
          <div className="flex flex-wrap items-center justify-between gap-2" role="status">
            <p className="text-base text-text">
              You {decision.status} it at {decision.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.
              <span className="block text-xs text-muted">Saved in this tab only.</span>
            </p>
            <Button variant="ghost" size="sm" onClick={() => setDecision(null)}>
              <RotateCcw className="size-3.5" aria-hidden="true" /> Undo
            </Button>
          </div>
        ) : (
          <div className="flex gap-3">
            <Button size="lg" className="flex-1" onClick={() => setDecision({ status: 'approved', at: new Date() })}>
              <Check className="size-5" aria-hidden="true" /> Approve
            </Button>
            <Button variant="ghost" size="lg" className="flex-1" onClick={() => setDecision({ status: 'rejected', at: new Date() })}>
              <X className="size-5" aria-hidden="true" /> Reject
            </Button>
          </div>
        )}
        <button
          type="button"
          onClick={() => onOpenTrace()}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-full py-2 text-sm font-medium text-text underline-offset-4 hover:underline"
        >
          See how it checked <ArrowRight className="size-4" aria-hidden="true" />
        </button>
      </div>

      {img && (
        <Dialog open={zoom} onClose={() => setZoom(false)} title={`Evidence · ${alert.event_id}`} wide>
          <img src={img} alt={alt} className="w-full" />
        </Dialog>
      )}
    </m.article>
  )
}
