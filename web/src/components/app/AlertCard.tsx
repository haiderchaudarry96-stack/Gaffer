import { useState } from 'react'
import { motion } from 'motion/react'
import { Check, Info, Maximize2, RotateCcw, X } from 'lucide-react'
import Badge from '../ui/Badge'
import Cited from '../ui/Cited'
import { Button } from '../ui/Button'
import Dialog from './Dialog'
import { evidenceImageUrl, type Alert, type ReportEvent } from '../../data'
import { splitAlertExplanation } from '../../data/alerts'
import { formatClock } from '../../data/time'

type LocalDecision = { status: 'approved' | 'rejected'; at: Date } | null

function evidenceAlt(alert: Alert, event: ReportEvent | undefined, team: string): string {
  const parts = [`Evidence for ${alert.event_id}: a drone video frame with ${team}'s players circled and their new formation lines drawn by OpenCV 5.`]
  if (event?.before && event.after) {
    parts.push(
      `Below, ${team}'s average shape ${event.before.window} (${event.before.formation}) next to ${event.after.window} (${event.after.formation}).`,
    )
  }
  return parts.join(' ')
}

export default function AlertCard({
  alert,
  event,
  teamName,
  onCite,
  onJump,
}: {
  alert: Alert
  event: ReportEvent | undefined
  teamName: string
  onCite: (ref: string) => void
  onJump: (t: number) => void
}) {
  const [decision, setDecision] = useState<LocalDecision>(null)
  const [zoom, setZoom] = useState(false)
  const text = splitAlertExplanation(alert.explanation)
  const img = evidenceImageUrl(alert)
  const status = decision?.status ?? alert.status
  const alt = evidenceAlt(alert, event, teamName)

  return (
    <motion.article
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 28 }}
      aria-labelledby={`alert-${alert.alert_id}`}
      className={`rounded-(--radius-card) border bg-surface ${status === 'pending' ? 'border-accent/60 glow-accent' : 'border-line'}`}
    >
      <div className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Badge status="confirmed">verified change</Badge>
            <Badge status={status}>{status === 'pending' ? 'waits for you' : status}</Badge>
          </span>
          <button
            type="button"
            onClick={() => onJump(alert.match_time_s)}
            className="rounded-md font-mono text-sm text-muted underline-offset-4 hover:text-text hover:underline"
            aria-label={`Jump to ${formatClock(alert.match_time_s)}`}
          >
            {formatClock(alert.match_time_s)}
          </button>
        </div>
        <h3 id={`alert-${alert.alert_id}`} className="font-display text-xl font-semibold text-text">
          {alert.title.replace('->', '→')}
        </h3>

        {text.explanation && (
          <p className="text-[15px] leading-relaxed text-text">
            <Cited text={text.explanation} onRef={onCite} />
            <span className="mt-1 block text-[11px] text-muted">
              {text.explanationSource === 'agent'
                ? 'Written by Nova 2 Lite from the rules’ facts, then checked by code (numbers, cause, no contradiction).'
                : 'Written by a code template from the rules’ facts.'}
            </span>
          </p>
        )}
        {text.verified && (
          <p className="rounded-xl border border-line bg-bg/60 px-3 py-2 text-xs leading-relaxed text-muted">
            <span className="font-semibold text-text">Rules verdict (code): </span>
            <Cited text={text.verified} onRef={onCite} />
          </p>
        )}
        {text.other && <p className="text-xs text-muted">{text.other}</p>}

        {img && (
          <button
            type="button"
            onClick={() => setZoom(true)}
            className="group relative block w-full overflow-hidden rounded-xl border border-line"
            aria-label="Enlarge the evidence image"
          >
            <img src={img} alt={alt} className="w-full" loading="lazy" width={1280} height={1341} />
            <span className="absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-full bg-bg/80 px-2 py-1 text-[11px] text-text opacity-90 group-hover:opacity-100">
              <Maximize2 className="size-3" aria-hidden="true" /> Enlarge
            </span>
          </button>
        )}

        <details className="group rounded-xl border border-warn/30 bg-warn/5 px-3 py-2 text-xs">
          <summary className="flex cursor-pointer items-center gap-1.5 font-medium text-warn">
            <Info className="size-3.5" aria-hidden="true" /> Suggestion (unchecked model text)
          </summary>
          <p className="mt-2 text-muted">“{alert.suggestion}”</p>
          <p className="mt-2 text-muted">
            Not checked by code and known to be weak here: a 4-4-2 → 3-4-3 switch adds a forward, not a central
            midfielder.
          </p>
        </details>
      </div>

      <div className="border-t border-line p-4">
        {decision ? (
          <div className="flex flex-wrap items-center justify-between gap-2" role="status">
            <p className="text-sm text-text">
              You {decision.status} this alert at {decision.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.
              <span className="block text-[11px] text-muted">Kept in this browser tab only; the backend will log it to alerts.jsonl.</span>
            </p>
            <Button variant="ghost" size="sm" onClick={() => setDecision(null)}>
              <RotateCcw className="size-3.5" aria-hidden="true" /> Undo
            </Button>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button size="md" className="flex-1" onClick={() => setDecision({ status: 'approved', at: new Date() })}>
              <Check className="size-4" aria-hidden="true" /> Approve
            </Button>
            <Button variant="ghost" size="md" className="flex-1" onClick={() => setDecision({ status: 'rejected', at: new Date() })}>
              <X className="size-4" aria-hidden="true" /> Reject
            </Button>
          </div>
        )}
      </div>

      {img && (
        <Dialog open={zoom} onClose={() => setZoom(false)} title={`Evidence · ${alert.event_id}`} wide>
          <img src={img} alt={alt} className="w-full" />
        </Dialog>
      )}
    </motion.article>
  )
}
