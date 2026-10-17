import Dialog from './Dialog'
import Cited from '../ui/Cited'
import { useResource } from '../../data/useResource'
import { getReport } from '../../lib/matchData'
import { ErrorState, Skeleton } from '../ui/States'
import type { CoachReport } from '../../data'

function Section({ title, items, ordered = false }: { title: string; items: string[]; ordered?: boolean }) {
  const List = ordered ? 'ol' : 'ul'
  return (
    <section className="space-y-2">
      <h3 className="font-sans text-sm font-semibold tracking-normal text-text">{title}</h3>
      <List className={`space-y-2 pl-5 text-sm leading-relaxed text-muted ${ordered ? 'list-decimal' : 'list-disc'}`}>
        {items.map((t, i) => (
          <li key={i}>
            <Cited text={t} />
          </li>
        ))}
      </List>
    </section>
  )
}

/** Shows the stored coach report for this window (generating a new one needs the backend). */
export default function ReportDialog({
  open,
  onClose,
  override,
}: {
  open: boolean
  onClose: () => void
  /** an uploaded analysis's report (null: it has none); undefined = the stored demo report */
  override?: CoachReport | null
}) {
  const demo = useResource(getReport, 'report')
  const res =
    override === undefined
      ? demo
      : override === null
        ? ({ status: 'error', error: 'This analysis has no coach report yet.' } as const)
        : ({ status: 'ready', data: override } as const)
  return (
    <Dialog open={open} onClose={onClose} title="Coach report · 15:00–21:00">
      <div className="space-y-6 p-5">
        <p className="rounded-xl border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-muted">
          {override === undefined ? (
            <>
              This is the <span className="text-text">stored</span> report from the Phase 3 run; generating a new one needs
              the backend. Written by the <span className="text-text">code template</span>: Nova 2 Lite’s version failed
              the grounding check twice. Every number cites its source: [evt_…] is an agent decision, [seg a-b] the
              tactics timeline.
            </>
          ) : (
            <>Report of the uploaded analysis, as returned by the backend.</>
          )}
        </p>
        {res.status === 'loading' && <Skeleton className="h-64" />}
        {res.status === 'error' && <ErrorState title="Could not load the report" detail={res.error} />}
        {res.status === 'ready' && (
          <>
            <Section title="Formation story" items={res.data.report.formation_story} />
            {res.data.report.changes.map((c) => (
              <section key={c.event} className="space-y-2">
                <h3 className="font-sans text-sm font-semibold tracking-normal text-text">Confirmed change · {c.event}</h3>
                <p className="text-sm leading-relaxed text-muted">
                  <span className="text-text">What changed: </span>
                  <Cited text={c.what_changed} />
                </p>
                <p className="text-sm leading-relaxed text-muted">
                  <span className="text-text">What it may have been trying to fix: </span>
                  <Cited text={c.may_have_fixed} />
                </p>
              </section>
            ))}
            <Section title="Not alerted" items={res.data.report.not_alerted} />
            <Section title="Three recommendations" items={res.data.report.recommendations} ordered />
            <Section title="Limits" items={res.data.report.limits} />
          </>
        )}
      </div>
    </Dialog>
  )
}
