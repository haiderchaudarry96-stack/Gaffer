import Dialog from './Dialog'
import Cited from '../ui/Cited'
import Disclosure from '../ui/Disclosure'
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
    <Dialog open={open} onClose={onClose} title={override === undefined ? 'Coach report · recorded example' : 'Coach report'}>
      <div className="space-y-6 p-5">
        <div className="rounded-xl border border-line bg-bg px-4 py-3 text-sm text-muted">
          {override === undefined ? (
            <>
              <p>This saved summary accompanies the recorded example. Review its cited moments alongside the footage before making a decision.</p>
              <Disclosure summary="About this report" className="mt-2">
                <p className="pt-2 text-xs">The example uses a structured template because generated wording did not pass the source checks. Event citations refer to checked changes; segment citations refer to the formation timeline. This is a saved report, not a new analysis.</p>
              </Disclosure>
            </>
          ) : (
            <>Summary of your completed analysis. Use the source citations to review its evidence.</>
          )}
        </div>
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
