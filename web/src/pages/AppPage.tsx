import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileText, Radio } from 'lucide-react'
import Logo from '../components/ui/Logo'
import { Button } from '../components/ui/Button'
import { ErrorState, Skeleton } from '../components/ui/States'
import Stage, { type LocalVideo } from '../components/app/Stage'
import UploadPanel from '../components/upload/UploadPanel'
import type { LocalVideoInfo } from '../components/upload/readVideo'
import Mascot from '../components/mascot/Mascot'
import { PositionIndex } from '../components/pitch/positions'
import FormationTimeline, { type ShownEvent } from '../components/app/FormationTimeline'
import AlertCard, { type LiveState } from '../components/app/AlertCard'
import CandidateCard from '../components/app/CandidateCard'
import TracePanel from '../components/app/TracePanel'
import ChatFab from '../components/app/ChatFab'
import ReportDialog from '../components/app/ReportDialog'
import Dialog from '../components/app/Dialog'
import Cited from '../components/ui/Cited'
import { offsetFromFileName, useTransport, type VideoSource } from '../components/app/transport'
import { PlaybackClock } from '../lib/clock'
import { useClockTime, usePrefersReducedMotion, useScrolled } from '../lib/hooks'
import { APP_START_S, STORY_EVENT } from '../lib/windows'
import { getAlerts, getExplanations, getReport, getRunRows, getTimeline, getTrace, usePositions } from '../lib/matchData'
import { useResource } from '../data/useResource'
import { DEFAULT_MATCH, MATCHES, traceForEvent, type TeamSide, type TimelineEvent, type TraceStep } from '../data'
import { splitAlertExplanation } from '../data/alerts'
import { livePhase, livePlan } from '../data/live'
import { timelineFromContract, type AnalysisResult } from '../data/analysis'
import { suggestedQuestions } from '../data/suggestions'
import type { FormationTimeline as TimelineView } from '../data'

/** An analysis returned by the backend for an uploaded video, ready for the same views. */
interface Uploaded {
  result: AnalysisResult
  index: PositionIndex
  timeline: TimelineView
  window: [number, number]
}

/**
 * The analyst desk. Default view: pitch (or video), shape timeline, one alert card.
 * Everything else (trace, chat, report) is one click away.
 * URL parameters (for demos and screenshots): ?t=<seconds>&live=1&drawer=1&paused=1&upload=1
 */
export default function AppPage() {
  const reduced = usePrefersReducedMotion()
  const [params] = useSearchParams()
  const [uploaded, setUploaded] = useState<Uploaded | null>(null)
  const [w0, w1] = uploaded?.window ?? DEFAULT_MATCH.window
  const startT = uploaded ? w0 : Number(params.get('t') ?? APP_START_S)
  const clock = useMemo(() => new PlaybackClock({ min: w0, max: w1 - 0.5, start: startT, rate: 1 }), [w0, w1, startT])
  const [video, setVideo] = useState<VideoSource | null>(null)
  const [localVideo, setLocalVideo] = useState<LocalVideo | null>(null)
  const [uploadOpen, setUploadOpen] = useState(params.get('upload') === '1')
  const transport = useTransport(clock, video)
  const [live, setLive] = useState(params.get('live') === '1')
  const [selected, setSelected] = useState<string>(STORY_EVENT)
  const [drawer, setDrawer] = useState<{ open: boolean; ref: string | null }>({ open: params.get('drawer') === '1', ref: null })
  const [reportOpen, setReportOpen] = useState(false)
  const t = useClockTime(clock, 4)
  const scrolled = useScrolled()

  const { res: matchRes, index: demoIndex } = usePositions()
  const timeline = useResource(getTimeline, 'timeline')
  const alerts = useResource(getAlerts, 'alerts')
  const trace = useResource(getTrace, 'trace')
  const explanations = useResource(getExplanations, 'explanations')
  const rows = useResource(getRunRows, 'run_rows')
  const report = useResource(getReport, 'report')

  const index = uploaded?.index ?? demoIndex
  const matchState = uploaded ? uploaded.result.match_state : matchRes.status === 'ready' ? matchRes.data : null

  // play once the positions are in; never auto-play with reduced motion or ?paused=1
  useEffect(() => {
    if (index && !reduced && params.get('paused') !== '1') clock.play()
    return () => clock.pause()
  }, [index, reduced, clock, params])

  useEffect(() => {
    document.title = 'Analyst desk — Gaffer'
    return () => {
      document.title = 'Gaffer — your tactical analyst'
    }
  }, [])

  const onVideo = useCallback((v: VideoSource | null) => setVideo(v), [])

  const tl = uploaded?.timeline ?? (timeline.status === 'ready' ? timeline.data : null)
  const names = tl?.teamNames ?? { home: 'White', away: 'Blue' }
  const allTrace: TraceStep[] = useMemo(() => (uploaded ? uploaded.result.trace : trace.status === 'ready' ? trace.data : []), [trace, uploaded])
  const alertList = uploaded ? uploaded.result.alerts : alerts.status === 'ready' ? alerts.data : null
  const chatMatchId = uploaded ? uploaded.result.id : (matchState?.match_id ?? DEFAULT_MATCH.id)

  // live replay timing per decided event, read from its trace
  const plans = useMemo(() => {
    const out = new Map<string, NonNullable<ReturnType<typeof livePlan>>>()
    for (const e of tl?.events ?? []) {
      if (e.status === 'candidate') continue
      const p = livePlan(traceForEvent(allTrace, e.id))
      if (p) out.set(e.id, p)
    }
    return out
  }, [tl, allTrace])

  const shownEvents: ShownEvent[] = (tl?.events ?? [])
    .map((e) => {
      if (!live) return { event: e, status: e.status, pending: false }
      if (t < e.t) return null // live: a marker appears when its time is reached
      const plan = plans.get(e.id)
      if (!plan) return { event: e, status: e.status, pending: false }
      const ph = livePhase(plan, t)
      return ph.phase === 'decided' ? { event: e, status: e.status, pending: false } : { event: e, status: 'candidate' as const, pending: true }
    })
    .filter((x): x is ShownEvent => x !== null)

  const verifiedFor = (side: TeamSide, at: number) => {
    const done = shownEvents.filter((e) => e.event.team === side && e.event.t <= at && !e.pending && e.status !== 'candidate').at(-1)
    return done && done.status === 'confirmed' ? done.event.id : null
  }

  const selectedEvent = tl?.events.find((e) => e.id === selected)
  const alert = alertList?.find((a) => a.event_id === selected)
  const steps = traceForEvent(allTrace, selected)
  // run rows, explanations and the report exist for the stored demo analysis only
  const row = !uploaded && rows.status === 'ready' ? rows.data.find((r) => r.event_id === selected) : undefined
  const reportEvent = !uploaded && report.status === 'ready' ? report.data.inputs.events.find((e) => e.id === selected) : undefined
  const explanation = !uploaded && explanations.status === 'ready' ? explanations.data.find((e) => e.event_id === selected) : undefined
  const plan = plans.get(selected)
  const liveState: LiveState | null =
    live && plan
      ? {
          plan,
          ...livePhase(plan, t),
          stepTools: steps.flatMap((s) => (s.kind === 'tool_call' ? [s.tool] : [])),
        }
      : null

  const selectEvent = (e: TimelineEvent) => {
    setSelected(e.id)
    transport.seek(e.t)
  }
  const toggleLive = () => {
    const next = !live
    setLive(next)
    if (next) {
      setSelected(STORY_EVENT)
      transport.seek(APP_START_S)
      transport.setRate(4)
      if (!reduced) clock.play()
    }
  }
  const loadError = uploaded ? undefined : [matchRes, timeline, alerts, trace].find((r) => r.status === 'error')

  const videoFrom = (v: LocalVideoInfo, fallbackOffset: number): LocalVideo => ({
    url: v.url,
    name: v.file.name,
    offset: offsetFromFileName(v.file.name) ?? fallbackOffset,
  })
  const openDemoWith = (v: LocalVideoInfo) => {
    setUploaded(null)
    setLocalVideo(videoFrom(v, DEFAULT_MATCH.window[0]))
    setUploadOpen(false)
  }
  const showResult = (result: AnalysisResult, v: LocalVideoInfo) => {
    const frames = result.match_state.frames
    const win: [number, number] = [frames[0]?.t ?? 0, (frames.at(-1)?.t ?? 0) + 0.5]
    const tlView = timelineFromContract(result.timeline)
    setUploaded({ result, index: new PositionIndex(result.match_state), timeline: tlView, window: win })
    // a video this browser cannot decode is analysed by the server but not played here
    setLocalVideo(v.previewable ? videoFrom(v, win[0]) : null)
    setSelected(tlView.events.find((e) => e.status === 'confirmed')?.id ?? tlView.events[0]?.id ?? '')
    setLive(false)
    setUploadOpen(false)
  }
  const verdict = alert ? splitAlertExplanation(alert.explanation).verified : (selectedEvent?.reason ?? null)

  let card = <Skeleton className="h-[34rem]" />
  if (tl && alertList && !selectedEvent) {
    card = (
      <article className="rounded-(--radius-card) border border-line bg-surface p-6">
        <h2 className="font-display text-2xl font-semibold text-text">No shape changes found</h2>
        <p className="mt-2 text-muted">The analysis has no candidate changes to show.</p>
      </article>
    )
  }
  if (tl && alertList && selectedEvent) {
    if (liveState && liveState.phase === 'before') {
      card = (
        <article className="rounded-(--radius-card) border border-line bg-surface p-6" aria-live="polite">
          <p className="text-sm text-muted">Live replay</p>
          <h2 className="mt-2 font-display text-3xl font-semibold text-text">Watching both shapes…</h2>
          <p className="mt-3 text-lg text-muted">No change spotted yet.</p>
        </article>
      )
    } else if (alert) {
      card = (
        <AlertCard
          key={`${alert.alert_id}-${liveState?.phase === 'decided' || !liveState}`}
          alert={alert}
          event={reportEvent}
          teamName={names[selectedEvent.team]}
          live={liveState}
          onOpenTrace={(ref) => setDrawer({ open: true, ref: ref ?? null })}
          onJump={transport.seek}
          scope={uploaded ? 'upload' : 'demo'}
        />
      )
    } else {
      card = (
        <CandidateCard
          event={selectedEvent}
          teamName={names[selectedEvent.team]}
          explanation={explanation}
          onJump={transport.seek}
          onOpenTrace={() => setDrawer({ open: true, ref: null })}
        />
      )
    }
  }

  return (
    // /app uses the same light tokens as the landing body (README decision 14)
    <div className="theme-light min-h-screen bg-bg pb-24">
      <header
        className={`sticky top-0 z-30 border-b border-line bg-surface transition-shadow duration-300 ${scrolled ? 'shadow-[0_8px_24px_-16px_rgba(7,13,10,0.35)]' : ''}`}
      >
        <a
          href="#main"
          className="sr-only rounded-full bg-accent px-4 py-2 font-semibold text-on-accent focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-50"
        >
          Skip to content
        </a>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
          <Logo />
          <label htmlFor="match-select" className="sr-only">
            Match
          </label>
          <select
            id="match-select"
            className="order-last h-9 w-full rounded-full border border-line bg-surface px-3 text-sm text-text sm:order-none sm:w-auto"
            value={uploaded ? uploaded.result.id : DEFAULT_MATCH.id}
            onChange={(e) => e.target.value === DEFAULT_MATCH.id && setUploaded(null)}
          >
            {uploaded && <option value={uploaded.result.id}>{uploaded.result.label}</option>}
            {MATCHES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
          <div className="ml-auto flex items-center gap-2">
            <Link to="/" className="hidden items-center gap-1 rounded-full px-3 py-2 text-sm text-muted hover:text-text lg:inline-flex">
              <ArrowLeft className="size-4" aria-hidden="true" /> Story
            </Link>
            <button
              type="button"
              role="switch"
              aria-checked={live}
              onClick={toggleLive}
              className={`inline-flex h-9 items-center gap-2 rounded-full border px-3 text-sm ${live ? 'border-warn text-text' : 'border-line text-muted hover:text-text'}`}
            >
              <Radio className={`size-4 ${live ? 'text-warn' : ''}`} aria-hidden="true" />
              Live replay
              <span className={`relative h-4 w-7 rounded-full border transition-colors ${live ? 'border-warn bg-warn' : 'border-line bg-surface-2'}`} aria-hidden="true">
                <span className={`absolute top-px left-0 size-3 rounded-full bg-surface shadow transition-transform ${live ? 'translate-x-3' : 'translate-x-px'}`} />
              </span>
            </button>
            <Button variant="ghost" size="sm" onClick={() => setReportOpen(true)}>
              <FileText className="size-4" aria-hidden="true" /> <span className="hidden sm:inline">Generate</span> report
            </Button>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto grid max-w-[1600px] gap-6 p-4 sm:p-6 xl:grid-cols-[minmax(0,1fr)_440px] xl:gap-8 xl:p-8">
        <h1 className="sr-only">{uploaded ? `Gaffer analyst desk: ${uploaded.result.label}` : 'Gaffer analyst desk: TeamTrack drone match, 15:00 to 21:00'}</h1>
        {loadError && loadError.status === 'error' && (
          <div className="xl:col-span-2">
            <ErrorState title="Some match data could not be loaded" detail={loadError.error} />
          </div>
        )}
        {/* mobile order: stage, alert, timeline; desktop: stage + timeline left, alert right */}
        <div className="min-w-0 xl:col-start-1 xl:row-start-1">
          <Stage
            clock={clock}
            transport={transport}
            index={index}
            match={matchState}
            timeline={tl}
            verifiedFor={verifiedFor}
            onVideo={onVideo}
            video={localVideo}
            onRemoveVideo={() => setLocalVideo(null)}
            onUpload={() => setUploadOpen(true)}
          />
        </div>
        <aside aria-label="Alert" className="min-w-0 xl:sticky xl:top-24 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:self-start">
          {card}
        </aside>
        <div className="min-w-0 xl:col-start-1 xl:row-start-2">
          <FormationTimeline clock={clock} timeline={tl} events={shownEvents} selected={selected} onSelect={selectEvent} />
        </div>
      </main>

      <Dialog
        open={drawer.open}
        onClose={() => setDrawer({ open: false, ref: null })}
        title={`How Gaffer checked ${selected}`}
        variant="drawer"
        icon={<Mascot size={40} />}
      >
        <div className="space-y-4 p-5">
          {verdict && (!liveState || liveState.phase === 'decided') && (
            <p className="rounded-xl border border-line bg-bg/60 px-4 py-3 text-sm text-muted">
              <span className="font-semibold text-text">Rules verdict (code): </span>
              <Cited text={verdict} />
            </p>
          )}
          {trace.status === 'ready' || uploaded ? (
            <TracePanel
              steps={steps}
              row={row}
              focusRef={drawer.ref}
              teamName={selectedEvent ? names[selectedEvent.team] : ''}
              stepsShown={liveState && liveState.phase !== 'decided' ? liveState.stepsDone : undefined}
              eventTime={selectedEvent?.t ?? null}
            />
          ) : (
            <Skeleton className="h-64" />
          )}
          {liveState && liveState.phase !== 'decided' && (
            <p className="text-sm text-muted">Steps appear at their recorded times.</p>
          )}
          {alert && (!liveState || liveState.phase === 'decided') && (
            <div className="rounded-xl border border-warn/40 bg-warn/5 px-4 py-3 text-sm">
              <p className="font-semibold text-warn">Suggestion (unchecked model text)</p>
              <p className="mt-1 text-muted">“{alert.suggestion}”</p>
              {!uploaded && <p className="mt-1 text-muted">Known to be weak: 4-4-2 → 3-4-3 adds a forward, not a central midfielder.</p>}
            </div>
          )}
        </div>
      </Dialog>
      <ReportDialog open={reportOpen} onClose={() => setReportOpen(false)} override={uploaded ? uploaded.result.report : undefined} />
      <UploadPanel open={uploadOpen} onClose={() => setUploadOpen(false)} onUseDemo={openDemoWith} onResult={showResult} />
      <ChatFab matchId={chatMatchId} suggestions={suggestedQuestions(tl)} />
    </div>
  )
}
