import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, FileText, House, Radio, Upload, Video } from 'lucide-react'
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
import RecordedEventCard from '../components/app/RecordedEventCard'
import NoChangesCard from '../components/app/NoChangesCard'
import IdleDesk from '../components/app/IdleDesk'
import ReadingStrip from '../components/app/ReadingStrip'
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
import { loadPersistedEvents, loadTeamTrackReplay,
  requestRoleRecommendation, type CoachContext, type PersistedEvent, type TeamTrackReplay } from '../data/teamtrack'
import { currentReplayEvent, freshSession, initialDeskMode, readingIndex, readingStats, revealTimeline,
  visibleReplayEvents, withDecision, type DeskMode, type SessionDecisions } from '../data/liveSession'

/** An analysis returned by the backend for an uploaded video, ready for the same views. */
interface Uploaded {
  result: AnalysisResult
  index: PositionIndex
  timeline: TimelineView
  window: [number, number]
  /** where the desk opens: shortly before the first confirmed change */
  start: number
}

/**
 * The analyst desk. Default view: pitch (or video), shape timeline, one alert card.
 * Everything else (trace, chat, report) is one click away.
 * Modes: idle (default: nothing shown until the coach starts), live (Live analysis on the recorded
 * TeamTrack match, revealed up to the playhead), review (the finished demo analysis) and upload
 * (a finished upload). URL parameters: ?mode=review (or ?t= / ?live=1 / ?drawer=1: review),
 * ?paused=1, ?upload=1 (opens the upload panel).
 */
export default function AppPage() {
  const reduced = usePrefersReducedMotion()
  const [params] = useSearchParams()
  const [uploaded, setUploaded] = useState<Uploaded | null>(null)
  const [recordedReplay, setRecordedReplay] = useState<TeamTrackReplay | null>(null)
  const [persistedEvents, setPersistedEvents] = useState<PersistedEvent[]>([])
  const [liveAnalysisOpen, setLiveAnalysisOpen] = useState(false)
  const [liveAnalysisLoading, setLiveAnalysisLoading] = useState(false)
  const [liveAnalysisError, setLiveAnalysisError] = useState<string | null>(null)
  const [coachSide, setCoachSide] = useState<TeamSide | ''>('')
  const [matchObjective, setMatchObjective] = useState('')
  const [availableRoles, setAvailableRoles] = useState<Array<'attacker' | 'midfielder' | 'defender'>>([])
  const [recommendationErrors, setRecommendationErrors] = useState<Record<string, string>>({})
  const recommendationAttempts = useRef(new Set<string>())
  const [deskMode, setDeskMode] = useState<DeskMode>(() => initialDeskMode(params))
  // this Live analysis session's coach decisions; a new session starts empty
  const [session, setSession] = useState<SessionDecisions>(freshSession)
  const autoplay = useRef(false)
  // review of the demo: its recorded TeamTrack video next to the pitch (none in a static build)
  const [reviewReplay, setReviewReplay] = useState<TeamTrackReplay | null>(null)
  const [w0, w1] = uploaded?.window ?? DEFAULT_MATCH.window
  const startT = uploaded ? uploaded.start : Number(params.get('t') ?? APP_START_S)
  const clock = useMemo(() => new PlaybackClock({ min: w0, max: w1, start: startT, rate: 1 }), [w0, w1, startT])
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

  const view: 'idle' | 'live' | 'review' | 'upload' = uploaded ? 'upload' : recordedReplay ? 'live' : deskMode
  const reading = useMemo(() => readingIndex(view === 'live' ? matchState : null), [view, matchState])

  // a finished analysis plays once the positions are in; never with reduced motion or ?paused=1
  const finished = view === 'review' || view === 'upload'
  useEffect(() => {
    if (index && finished && !reduced && params.get('paused') !== '1') clock.play() // no-op with a video
    return () => clock.pause()
  }, [index, reduced, clock, params, finished])

  useEffect(() => {
    if (view !== 'review' || reviewReplay) return
    let active = true
    loadTeamTrackReplay()
      .then((source) => active && setReviewReplay({ ...source, label: 'Recorded TeamTrack footage · completed analysis' }))
      .catch(() => {}) // static build or no clips on this server: the pitch alone
    return () => {
      active = false
    }
  }, [view, reviewReplay])

  useEffect(() => {
    document.title = 'Analyst desk — Gaffer'
    return () => {
      document.title = 'Gaffer — your tactical analyst'
    }
  }, [])

  const posturePending = persistedEvents.some((event) => event.posture_status === 'pending')
  useEffect(() => {
    const matchId = recordedReplay?.match_id
    if (!matchId || !posturePending) return
    let active = true
    let remainingPolls = 24
    let timer: number | undefined
    const poll = async () => {
      if (!active || remainingPolls <= 0) return
      remainingPolls -= 1
      try {
        const latest = await loadPersistedEvents(matchId)
        if (!active) return
        setPersistedEvents(latest)
        if (latest.some((event) => event.posture_status === 'pending') && remainingPolls > 0) {
          timer = window.setTimeout(() => void poll(), 5000)
        }
      } catch {
        if (active && remainingPolls > 0) timer = window.setTimeout(() => void poll(), 5000)
      }
    }
    timer = window.setTimeout(() => void poll(), 5000)
    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [recordedReplay?.match_id, posturePending])

  useEffect(() => {
    if (!recordedReplay) return
    const context: CoachContext = {
      coach_side: coachSide || null,
      objective: matchObjective === 'chase' || matchObjective === 'protect'
        || matchObjective === 'balanced' ? matchObjective : null,
      available_substitute_roles: [...availableRoles].sort(),
    }
    const contextKey = JSON.stringify(context)
    for (const event of persistedEvents) {
      if (event.status !== 'confirmed' || event.verification_match_time_s === null
          || t < event.verification_match_time_s
          || event.posture_status === 'pending') continue
      const old = event.recommendation
      const sameContext = old?.context.coach_side === context.coach_side
        && old.context.objective === context.objective
        && [...old.context.available_substitute_roles].sort().join(',')
          === context.available_substitute_roles.join(',')
      if (old?.coach_response) continue
      if (old && sameContext
          && old.posture_status_at_creation === event.posture_status
          && old.posture_trace_id === (event.posture_result?.trace_id ?? null)) continue
      const attemptKey = `${event.record_id}:${contextKey}`
      if (recommendationAttempts.current.has(attemptKey)) continue
      recommendationAttempts.current.add(attemptKey)
      void requestRoleRecommendation(event.record_id, context)
        .then(() => loadPersistedEvents(recordedReplay.match_id))
        .then((latest) => {
          setPersistedEvents(latest)
          setRecommendationErrors((current) => {
            const next = { ...current }
            delete next[event.record_id]
            return next
          })
        })
        .catch((error: unknown) => {
          const message = error instanceof Error ? error.message : ''
          if (message.includes('HTTP 409')
              && message.includes('Coach context cannot replace advice that already has a saved response.')) {
            void loadPersistedEvents(recordedReplay.match_id).then(setPersistedEvents)
            return
          }
          setRecommendationErrors((current) => ({
            ...current,
            [event.record_id]: error instanceof Error
              ? error.message : 'Could not prepare role advice.',
          }))
        })
    }
  }, [recordedReplay, persistedEvents, coachSide, matchObjective, availableRoles, t])

  const onVideo = useCallback((v: VideoSource | null) => setVideo(v), [])

  const tl = uploaded?.timeline ?? (timeline.status === 'ready' ? timeline.data : null)
  const names = tl?.teamNames ?? { home: 'White', away: 'Blue' }
  const allTrace: TraceStep[] = useMemo(() => (uploaded ? uploaded.result.trace : trace.status === 'ready' ? trace.data : []), [trace, uploaded])
  const alertList = uploaded ? uploaded.result.alerts : alerts.status === 'ready' ? alerts.data : null
  // the API knows the demo by its sample id (config api.demo.id = DEFAULT_MATCH.id), not by the
  // match_state's own match_id (teamtrack_top_w900_1260): sending that gave HTTP 404 in chat
  const chatMatchId = uploaded ? uploaded.result.id : DEFAULT_MATCH.id

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

  const shownEvents: ShownEvent[] = recordedReplay
    ? visibleReplayEvents(persistedEvents, t)
    : (tl?.events ?? [])
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

  const current = recordedReplay ? currentReplayEvent(persistedEvents, t, selected, coachSide) : null
  const currentPersisted = current?.record
  const selectedEvent: TimelineEvent | undefined = recordedReplay
    ? current ? {
        id: current.record.event_id,
        team: current.record.team,
        t: current.record.candidate_time_s,
        from: current.record.from_formation ?? 'unknown',
        to: current.record.to_formation ?? 'unknown',
        status: current.state.kind === 'decided' ? current.state.status : 'candidate',
        reason: null,
      } : undefined
    : tl?.events.find((e) => e.id === selected)
  const alert = alertList?.find((a) => a.event_id === selected)
  const steps = traceForEvent(allTrace, selected)
  // run rows and explanations are read for the stored demo analysis only; an upload's result
  // carries its own coach report (same format), used for the alert's before / after shapes
  const row = !uploaded && rows.status === 'ready' ? rows.data.find((r) => r.event_id === selected) : undefined
  const reportData = uploaded ? uploaded.result.report : report.status === 'ready' ? report.data : null
  const reportEvent = reportData?.inputs.events.find((e) => e.id === selected)
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
    setRecordedReplay(null)
    setPersistedEvents([])
    const next = !live
    setLive(next)
    if (next) {
      // an upload replays from its start, the demo from shortly before its story event
      setSelected(uploaded ? (uploaded.timeline.events.find((e) => e.status === 'confirmed')?.id
        ?? uploaded.timeline.events[0]?.id ?? '') : STORY_EVENT)
      transport.seek(uploaded ? uploaded.window[0] : APP_START_S)
      transport.setRate(uploaded ? 1 : 4)
      if (!reduced) {
        if (video) {
          if (video.play) video.play()
          else void video.el.play()
        } else clock.play()
      }
    }
  }
  const backToStart = () => {
    clock.pause()
    setUploaded(null)
    setRecordedReplay(null)
    setPersistedEvents([])
    setLocalVideo(null)
    setLive(false)
    setDeskMode('idle')
    setSelected(STORY_EVENT)
  }
  const startLiveAnalysis = async () => {
    setLiveAnalysisLoading(true)
    setLiveAnalysisError(null)
    try {
      const source = await loadTeamTrackReplay()
      const events = await loadPersistedEvents(source.match_id)
      setUploaded(null)
      setLocalVideo(null)
      setLive(false)
      // a fresh session: no decisions, no advice attempts or errors carried over
      setSession(freshSession())
      setRecommendationErrors({})
      recommendationAttempts.current.clear()
      setPersistedEvents(events)
      setRecordedReplay(source)
      setSelected('')
      clock.pause()
      clock.seek(source.start_s)
      autoplay.current = !reduced
      setLiveAnalysisOpen(false)
    } catch (error) {
      setLiveAnalysisError(error instanceof Error ? error.message : 'Could not load the recorded TeamTrack replay.')
    } finally {
      setLiveAnalysisLoading(false)
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
    setRecordedReplay(null)
    setPersistedEvents([])
    setLocalVideo(videoFrom(v, DEFAULT_MATCH.window[0]))
    setUploadOpen(false)
  }
  const showResult = (result: AnalysisResult, v: LocalVideoInfo) => {
    setRecordedReplay(null)
    setPersistedEvents([])
    const frames = result.match_state.frames
    const win: [number, number] = [frames[0]?.t ?? 0, (frames.at(-1)?.t ?? 0) + 0.5]
    const tlView = timelineFromContract(result.timeline)
    const first = tlView.events.find((e) => e.status === 'confirmed') ?? tlView.events[0]
    // team labels settle a few seconds into a video: open just before the first confirmed change
    const start = first ? Math.max(win[0], first.t - 15) : win[0]
    setUploaded({ result, index: new PositionIndex(result.match_state), timeline: tlView, window: win, start })
    // a video this browser cannot decode is analysed by the server but not played here
    // a video this browser cannot decode keeps its panel, which says so (the pitch keeps its size)
    setLocalVideo({ ...videoFrom(v, win[0]), playable: v.previewable })
    setSelected(tlView.events.find((e) => e.status === 'confirmed')?.id ?? tlView.events[0]?.id ?? '')
    setLive(false)
    setUploadOpen(false)
  }

  // a video starts playing once its player is attached (muted: allowed): the recorded footage
  // at 15:00 in Live analysis, the demo or upload video in a finished view
  const autoplayFinished = finished && !reduced && params.get('paused') !== '1'
  useEffect(() => {
    if (!video || (!autoplay.current && !autoplayFinished)) return
    autoplay.current = false
    if (video.play) video.play()
    else void video.el.play().catch(() => {}) // a browser that refuses autoplay: Play is there
  }, [video, autoplayFinished])

  // live modes: the chips and the timeline know nothing after the playhead
  const reveal = view === 'live' || live
  const shownTl = reveal && tl ? revealTimeline(tl, t) : tl
  const verdict = alert ? splitAlertExplanation(alert.explanation).verified : (selectedEvent?.reason ?? null)

  const replayState = current?.state ?? null
  const savedRecommendation = currentPersisted?.recommendation
  const currentRoles = [...availableRoles].sort().join(',')
  const savedRoles = [...(savedRecommendation?.context.available_substitute_roles ?? [])].sort().join(',')
  const recommendationNotice = savedRecommendation?.coach_response
    && (savedRecommendation.context.coach_side !== (coachSide || null)
      || savedRecommendation.context.objective !== (matchObjective || null)
      || savedRoles !== currentRoles)
    ? 'This advice already has a saved coach response. Its original team, objective, and available roles stay linked to that decision; changing setup cannot replace it.'
    : undefined

  let card = <Skeleton className="h-[34rem]" />
  if (recordedReplay && !currentPersisted) {
    card = (
      <article className="rounded-(--radius-card) border border-line bg-surface p-6" aria-live="polite">
        <p className="text-sm text-muted">Recorded TeamTrack footage · replay, not a live camera</p>
        <h2 className="mt-2 font-display text-2xl font-semibold text-text">
          {persistedEvents.length === 0 ? 'No OpenCV event records are stored' : 'Watching the match'}
        </h2>
        <p className="mt-3 text-muted">
          {persistedEvents.length === 0
            ? 'The video and map are available, but this replay has no persisted OpenCV events to show. No event has been fabricated.'
            : 'Formation-change candidates will appear when playback reaches their recorded match time.'}
        </p>
      </article>
    )
  } else if (recordedReplay && currentPersisted && replayState && replayState.kind !== 'upcoming') {
    card = <RecordedEventCard event={currentPersisted} state={replayState} coachSide={coachSide}
      matchTimeS={t} onRefresh={() => {
        if (recordedReplay) void loadPersistedEvents(recordedReplay.match_id).then(setPersistedEvents)
      }} recommendationError={recommendationErrors[currentPersisted.record_id]}
        recommendationNotice={recommendationNotice}
        session={{ alert: session.alert[currentPersisted.record_id],
          advice: currentPersisted.recommendation ? session.advice[currentPersisted.recommendation.recommendation_id] : undefined }}
        onSessionDecide={(kind, key, decision, note) => setSession((s) => withDecision(s, kind, key, decision, note))} />
  } else if (!recordedReplay && tl && alertList && !selectedEvent) {
    card = <NoChangesCard clipSeconds={uploaded ? uploaded.window[1] - uploaded.window[0] : undefined} />
  }
  if (!recordedReplay && tl && alertList && selectedEvent) {
    if (liveState && liveState.phase === 'before') {
      card = (
        <article className="rounded-(--radius-card) border border-line bg-surface p-6" aria-live="polite">
          <p className="text-sm text-muted">Match replay</p>
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
          {finished && (
            <>
              <label htmlFor="match-select" className="sr-only">
                Match
              </label>
              <select
                id="match-select"
                className="order-last h-9 w-full rounded-full border border-line bg-surface px-3 text-sm text-text sm:order-none sm:w-auto"
                value={uploaded ? uploaded.result.id : DEFAULT_MATCH.id}
                onChange={(e) => {
                  if (e.target.value === DEFAULT_MATCH.id) {
                    setUploaded(null)
                    setRecordedReplay(null)
                    setPersistedEvents([])
                    setDeskMode('review')
                  }
                }}
              >
                {uploaded && <option value={uploaded.result.id}>{uploaded.result.label}</option>}
                {MATCHES.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} (completed analysis)
                  </option>
                ))}
              </select>
            </>
          )}
          <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:ml-auto sm:w-auto sm:flex-nowrap">
            <Link to="/" className="hidden items-center gap-1 rounded-full px-3 py-2 text-sm text-muted hover:text-text lg:inline-flex">
              <ArrowLeft className="size-4" aria-hidden="true" /> Story
            </Link>
            {view !== 'idle' && (
              <Button variant="ghost" size="sm" onClick={backToStart}>
                <House className="size-4" aria-hidden="true" /> Start screen
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => { clock.pause(); setLiveAnalysisError(null); setLiveAnalysisOpen(true) }}>
              <Video className="size-4" aria-hidden="true" /> Live analysis
            </Button>
            {view === 'idle' && (
              <Button variant="ghost" size="sm" onClick={() => setUploadOpen(true)}>
                <Upload className="size-4" aria-hidden="true" /> Upload video
              </Button>
            )}
            {finished && (
              <button
                type="button"
                role="switch"
                aria-checked={live}
                onClick={toggleLive}
                className={`inline-flex h-9 items-center gap-2 rounded-full border px-3 text-sm ${live ? 'border-warn text-text' : 'border-line text-muted hover:text-text'}`}
              >
                <Radio className={`size-4 ${live ? 'text-warn' : ''}`} aria-hidden="true" />
                {uploaded ? 'Replay in match time' : 'Match replay'}
                <span className={`relative h-4 w-7 rounded-full border transition-colors ${live ? 'border-warn bg-warn' : 'border-line bg-surface-2'}`} aria-hidden="true">
                  <span className={`absolute top-px left-0 size-3 rounded-full bg-surface shadow transition-transform ${live ? 'translate-x-3' : 'translate-x-px'}`} />
                </span>
              </button>
            )}
            {finished && (
              <Button variant="ghost" size="sm" onClick={() => setReportOpen(true)}>
                <FileText className="size-4" aria-hidden="true" /> <span className="hidden sm:inline">Generate</span> report
              </Button>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto grid max-w-[1600px] gap-6 p-4 sm:p-6 xl:grid-cols-[minmax(0,1fr)_440px] xl:gap-8 xl:p-8">
        <h1 className="sr-only">
          {view === 'idle' ? 'Gaffer analyst desk: start an analysis'
            : uploaded ? `Gaffer analyst desk: ${uploaded.result.label}`
              : view === 'live' ? 'Gaffer analyst desk: Live analysis of a recorded TeamTrack match'
                : 'Gaffer analyst desk: completed analysis, TeamTrack drone match, 15:00 to 21:00'}
        </h1>
        {view === 'idle' ? (
          <IdleDesk
            reduced={reduced}
            onLive={() => { setLiveAnalysisError(null); setLiveAnalysisOpen(true) }}
            onUpload={() => setUploadOpen(true)}
            onReview={() => setDeskMode('review')}
          />
        ) : (
          <>
            {loadError && loadError.status === 'error' && (
              <div className="xl:col-span-2">
                <ErrorState title="Some match data could not be loaded" detail={loadError.error} />
              </div>
            )}
            {view === 'live' && recordedReplay && (
              <div className="xl:col-span-2">
                <ReadingStrip stats={readingStats(reading, recordedReplay.start_s, t)} playing={transport.playing} />
              </div>
            )}
            {finished && (
              <p className="rounded-(--radius-card) border border-line bg-surface px-4 py-2 text-sm text-muted xl:col-span-2">
                <span className="font-semibold text-text">Completed analysis</span>
                {' · '}{uploaded
                  ? 'your upload, analysed in full: every shape, change and alert below is the finished result.'
                  : 'the finished 15:00–21:00 analysis of the recorded TeamTrack match, shown in full for review.'}
                {' '}<button type="button" onClick={toggleLive} className="font-medium text-accent-ink underline underline-offset-4 hover:text-text">
                  {live ? 'Show the full result' : 'Replay in match time'}
                </button>
                {uploaded?.result.resolution?.low && uploaded.result.resolution.message && (
                  <span role="note" data-testid="low-resolution-note" className="mt-1 block text-warn">{uploaded.result.resolution.message}</span>
                )}
              </p>
            )}
            {/* mobile order: stage, alert, timeline; desktop: stage + timeline left, alert right */}
            <div className="min-w-0 xl:col-start-1">
              <Stage
                clock={clock}
                transport={transport}
                index={index}
                match={matchState}
                timeline={shownTl}
                verifiedFor={verifiedFor}
                onVideo={onVideo}
                video={localVideo}
                replay={recordedReplay ?? (view === 'review' ? reviewReplay : null)}
                onRemoveVideo={() => setLocalVideo(null)}
                onUpload={() => setUploadOpen(true)}
              />
            </div>
            <aside aria-label="Alert" className="min-w-0 xl:sticky xl:top-24 xl:col-start-2 xl:row-span-2 xl:self-start">
              {card}
            </aside>
            <div className="min-w-0 xl:col-start-1">
              <FormationTimeline clock={clock} timeline={shownTl} events={shownEvents} selected={selected} onSelect={selectEvent} revealToPlayhead={reveal} />
            </div>
          </>
        )}
      </main>

      <Dialog open={liveAnalysisOpen} onClose={() => setLiveAnalysisOpen(false)} title="Set up Live analysis" wide>
        <div className="space-y-5 p-5 sm:p-7">
          <div className="rounded-xl border border-line bg-bg px-4 py-3 text-sm text-muted">
            This demo replays recorded TeamTrack footage. It is not a live camera feed, and no camera is connected. A live-camera setup would need a fixed elevated position, the entire pitch in view, and clearly different jerseys for each team.
          </div>
          <label className="block space-y-2 text-sm font-medium text-text" htmlFor="coach-side">
            <span>Which demo side are you coaching?</span>
            <select id="coach-side" value={coachSide} onChange={(event) => setCoachSide(event.target.value as TeamSide)} className="h-11 w-full rounded-xl border border-line bg-surface px-3">
              <option value="">Select a side</option>
              <option value="home">{names.home}</option>
              <option value="away">{names.away}</option>
            </select>
          </label>
          <label className="block space-y-2 text-sm font-medium text-text" htmlFor="match-objective">
            <span>Match objective</span>
            <select id="match-objective" value={matchObjective} onChange={(event) => setMatchObjective(event.target.value)} className="h-11 w-full rounded-xl border border-line bg-surface px-3">
              <option value="">No objective selected</option>
              <option value="chase">Chase a goal</option>
              <option value="protect">Protect a lead</option>
              <option value="balanced">Balanced</option>
            </select>
          </label>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-text">Available substitute roles</legend>
            <p className="text-xs text-muted">Select only roles actually available. No player names are needed.</p>
            <div className="grid gap-2 sm:grid-cols-3">
              {(['attacker', 'midfielder', 'defender'] as const).map((role) => (
                <label key={role} className="flex min-h-11 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm capitalize text-text">
                  <input type="checkbox" checked={availableRoles.includes(role)}
                    onChange={(event) => setAvailableRoles((roles) => event.target.checked
                      ? [...roles, role] : roles.filter((item) => item !== role))} />
                  {role}
                </label>
              ))}
            </div>
          </fieldset>
          {liveAnalysisError && <p role="alert" className="rounded-xl border border-danger/40 bg-danger/5 px-4 py-3 text-sm text-danger">{liveAnalysisError}</p>}
          <div className="flex flex-wrap justify-end gap-3">
            <Button variant="ghost" onClick={() => setLiveAnalysisOpen(false)}>Cancel</Button>
            {recordedReplay && (
              <Button variant="ghost" disabled={liveAnalysisLoading} onClick={() => void startLiveAnalysis()}>
                Start a new session
              </Button>
            )}
            <Button variant="primary" disabled={liveAnalysisLoading} onClick={() => {
              if (recordedReplay) setLiveAnalysisOpen(false)
              else void startLiveAnalysis()
            }}>
              {liveAnalysisLoading ? 'Loading replay…' : recordedReplay ? 'Save context and resume' : 'Start recorded match analysis'}
            </Button>
          </div>
        </div>
      </Dialog>

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
              <p className="font-semibold text-warn">Suggestion (checked against the formation change; not a decision)</p>
              <p className="mt-1 text-muted">“{alert.suggestion}”</p>
            </div>
          )}
        </div>
      </Dialog>
      <ReportDialog open={reportOpen} onClose={() => setReportOpen(false)} override={uploaded ? uploaded.result.report : undefined} />
      <UploadPanel open={uploadOpen} onClose={() => setUploadOpen(false)} onUseDemo={openDemoWith} onResult={showResult} />
      {/* the chat reads the whole finished analysis: offered in review, never mid-session */}
      {finished && <ChatFab matchId={chatMatchId} suggestions={suggestedQuestions(tl)} />}
    </div>
  )
}
