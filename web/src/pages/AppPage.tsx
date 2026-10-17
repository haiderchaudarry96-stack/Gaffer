import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, FileText, ListChecks } from 'lucide-react'
import Logo from '../components/ui/Logo'
import { Button } from '../components/ui/Button'
import { ErrorState, Skeleton } from '../components/ui/States'
import VideoPanel from '../components/app/VideoPanel'
import Minimap from '../components/app/Minimap'
import PlaybackBar from '../components/app/PlaybackBar'
import FormationTimeline from '../components/app/FormationTimeline'
import AlertCard from '../components/app/AlertCard'
import CandidateCard from '../components/app/CandidateCard'
import TracePanel from '../components/app/TracePanel'
import ChatPanel from '../components/app/ChatPanel'
import ReportDialog from '../components/app/ReportDialog'
import Panel from '../components/app/Panel'
import { useTransport, type VideoSource } from '../components/app/transport'
import { PlaybackClock } from '../lib/clock'
import { usePrefersReducedMotion } from '../lib/hooks'
import {
  getAlerts,
  getExplanations,
  getReport,
  getRunRows,
  getTimeline,
  getTrace,
  usePositions,
} from '../lib/matchData'
import { useResource } from '../data/useResource'
import { DEFAULT_MATCH, MATCHES, traceForEvent, type TimelineEvent } from '../data'

/** Start just before the confirmed 16:30 change so it arrives within seconds. */
const START_T = 950

export default function AppPage() {
  const reduced = usePrefersReducedMotion()
  const [w0, w1] = DEFAULT_MATCH.window
  const clock = useMemo(() => new PlaybackClock({ min: w0, max: w1 - 0.5, start: START_T, rate: 2 }), [w0, w1])
  const [video, setVideo] = useState<VideoSource | null>(null)
  const transport = useTransport(clock, video)
  const [selected, setSelected] = useState<string>('evt_003')
  const [focusRef, setFocusRef] = useState<string | null>(null)
  const [reportOpen, setReportOpen] = useState(false)

  const { res: matchRes, index } = usePositions()
  const timeline = useResource(getTimeline, 'timeline')
  const alerts = useResource(getAlerts, 'alerts')
  const trace = useResource(getTrace, 'trace')
  const explanations = useResource(getExplanations, 'explanations')
  const rows = useResource(getRunRows, 'run_rows')
  const report = useResource(getReport, 'report')

  // play the stored positions once they are in (never auto-play with reduced motion)
  useEffect(() => {
    if (index && !reduced) clock.play()
    return () => clock.pause()
  }, [index, reduced, clock])

  useEffect(() => {
    document.title = 'Analyst desk — Gaffer'
    return () => {
      document.title = 'Gaffer — your tactical analyst'
    }
  }, [])

  const onVideo = useCallback((v: VideoSource | null) => setVideo(v), [])

  const tl = timeline.status === 'ready' ? timeline.data : null
  const names = tl?.teamNames ?? { home: 'White', away: 'Blue' }
  const selectedEvent = tl?.events.find((e) => e.id === selected)
  const alertForSelected = alerts.status === 'ready' ? alerts.data.find((a) => a.event_id === selected) : undefined
  const steps = trace.status === 'ready' ? traceForEvent(trace.data, selected) : []
  const row = rows.status === 'ready' ? rows.data.find((r) => r.event_id === selected) : undefined
  const reportEvent = report.status === 'ready' ? report.data.inputs.events.find((e) => e.id === selected) : undefined
  const explanation = explanations.status === 'ready' ? explanations.data.find((e) => e.event_id === selected) : undefined

  const selectEvent = (e: TimelineEvent) => {
    setSelected(e.id)
    setFocusRef(null)
    transport.seek(e.t)
  }
  const cite = (ref: string) => setFocusRef(ref === focusRef ? `${ref} ` : ref)
  const loadError = [matchRes, timeline, alerts, trace].find((r) => r.status === 'error')

  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <Logo />
          <span className="hidden h-6 w-px bg-line sm:block" aria-hidden="true" />
          <label htmlFor="match-select" className="sr-only">
            Match
          </label>
          <select
            id="match-select"
            className="h-9 max-w-[min(26rem,100%)] rounded-full border border-line bg-surface px-3 text-sm text-text"
            defaultValue={DEFAULT_MATCH.id}
          >
            {MATCHES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
          <div className="ml-auto flex items-center gap-2">
            <Link to="/" className="hidden items-center gap-1 rounded-full px-3 py-2 text-sm text-muted hover:text-text sm:inline-flex">
              <ArrowLeft className="size-4" aria-hidden="true" /> Back to the story
            </Link>
            <Button variant="ghost" size="sm" onClick={() => setReportOpen(true)}>
              <FileText className="size-4" aria-hidden="true" /> Generate report
            </Button>
          </div>
        </div>
      </header>

      <main id="main" className="grid gap-4 p-4 sm:p-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        <h1 className="sr-only">Gaffer analyst desk: TeamTrack drone match, 15:00 to 21:00</h1>
        <div className="flex min-w-0 flex-col gap-4">
          {loadError && loadError.status === 'error' && (
            <ErrorState title="Some match data could not be loaded" detail={loadError.error}>
              <p className="text-sm text-muted">Run the app with npm run dev so the sample files are copied in.</p>
            </ErrorState>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <VideoPanel clock={clock} defaultOffset={w0} onVideo={onVideo} />
            <Minimap clock={clock} index={index} match={matchRes.status === 'ready' ? matchRes.data : null} timeline={tl} />
          </div>
          <PlaybackBar clock={clock} transport={transport} hasVideo={!!video} />
          <FormationTimeline clock={clock} timeline={tl} selected={selected} onSelect={selectEvent} />
          {selectedEvent && selectedEvent.status !== 'candidate' && (
            <Panel title="How Gaffer checked this" id="trace-title" actions={<ListChecks className="size-4 text-muted" aria-hidden="true" />}>
              <details open className="group p-4">
                <summary className="mb-3 cursor-pointer text-xs text-muted">
                  Recorded agent trace for {selected}: each tool call in order, with the OpenCV result that set the next call.
                </summary>
                {trace.status === 'ready' ? (
                  <TracePanel steps={steps} row={row} focusRef={focusRef?.trim() ?? null} teamName={names[selectedEvent.team]} />
                ) : (
                  <Skeleton className="h-64" />
                )}
              </details>
            </Panel>
          )}

        </div>

        <aside aria-label="Alerts and checks" className="flex min-w-0 flex-col gap-4">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-lg font-semibold text-text">Alerts</h2>
            <span className="text-xs text-muted">
              {alerts.status === 'ready' ? `${alerts.data.length} pending · 2 of ${tl?.events.length ?? '…'} candidates checked` : ''}
            </span>
          </div>

          {!tl || alerts.status !== 'ready' ? (
            <Skeleton className="h-96" />
          ) : alertForSelected ? (
            <AlertCard
              key={alertForSelected.alert_id}
              alert={alertForSelected}
              event={reportEvent}
              teamName={selectedEvent ? names[selectedEvent.team] : ''}
              onCite={cite}
              onJump={transport.seek}
            />
          ) : selectedEvent ? (
            <CandidateCard event={selectedEvent} teamName={names[selectedEvent.team]} explanation={explanation} onJump={transport.seek} />
          ) : null}

          {tl && (
            <nav aria-label="Checked candidates" className="flex flex-wrap gap-2">
              {tl.events
                .filter((e) => e.status !== 'candidate')
                .map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    onClick={() => selectEvent(e)}
                    aria-pressed={selected === e.id}
                    className={`rounded-full border px-3 py-1.5 text-xs ${selected === e.id ? 'border-text text-text' : 'border-line text-muted hover:text-text'}`}
                  >
                    {e.id} · {names[e.team]} {e.from} → {e.to} · {e.status}
                  </button>
                ))}
            </nav>
          )}

          <ChatPanel />
        </aside>
      </main>
      <ReportDialog open={reportOpen} onClose={() => setReportOpen(false)} />
    </div>
  )
}
