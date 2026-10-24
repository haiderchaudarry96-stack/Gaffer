import { useEffect, useId, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, Pause, Play, X } from 'lucide-react'
import UploadButton from '../upload/UploadButton'
import PitchCanvas from '../pitch/PitchCanvas'
import type { PositionIndex } from '../pitch/positions'
import type { PlaybackClock } from '../../lib/clock'
import { useClockTime } from '../../lib/hooks'
import type { FormationTimeline, MatchState, TeamSide } from '../../data'
import { displayFormation } from '../../data/timeline'
import { formatClock } from '../../data/time'
import { Skeleton } from '../ui/States'
import type { Transport, VideoSource } from './transport'
import { TeamTrackVideoSource } from './teamTrackPlayer'
import type { TeamTrackReplay } from '../../data/teamtrack'

/** A video the coach picked from their disk; it stays in the browser. */
export interface LocalVideo {
  url: string
  name: string
  /** match second at which the video starts */
  offset: number
  /** false: this browser cannot decode it (codec); the analysis still comes from it */
  playable?: boolean
}

/** the browser cannot show the uploaded file: said plainly, the pitch keeps its size */
export const CANNOT_PREVIEW = 'This browser can\u2019t preview the file; the analysis below still comes from it.'

const RATES = [1, 2, 4]

function FormationChip({
  side,
  name,
  timeline,
  t,
  confirmedId,
}: {
  side: TeamSide
  name: string
  timeline: FormationTimeline | null
  t: number
  confirmedId: string | null
}) {
  const shown = timeline ? displayFormation(timeline, side, t) : null
  const Arrow = side === 'home' ? ArrowRight : ArrowLeft
  return (
    <div className={`flex flex-col ${side === 'away' ? 'items-end text-right' : ''}`}>
      <span className="flex items-center gap-1.5 text-sm text-muted">
        <span className={`size-2.5 rounded-full ${side === 'home' ? 'bg-team-a' : 'bg-team-b'}`} aria-hidden="true" />
        {name}
        <Arrow className="size-3.5" aria-label={side === 'home' ? 'attacks right' : 'attacks left'} />
      </span>
      <span className="font-mono text-3xl font-semibold tracking-tight text-text tabular sm:text-4xl" aria-live="polite">
        {shown?.formation ?? '—'}
      </span>
      <span className="flex min-h-5 items-center gap-1 text-xs">
        {confirmedId ? (
          <span className="inline-flex items-center gap-1 font-medium text-accent-ink">
            <CheckCircle2 className="size-3.5" aria-hidden="true" /> verified
          </span>
        ) : shown?.holding ? (
          <span className="text-warn">holding · shape unsettled</span>
        ) : null}
      </span>
    </div>
  )
}

/**
 * The main stage. With a video (the recorded TeamTrack replay, or an uploaded file) the video and
 * the tactical pitch sit side by side at the same width (stacked below 900 px), and one transport
 * drives both: the clock follows the video's currentTime + start offset. No native video controls
 * (one clock) and no picture-in-picture. Without a video, the pitch alone.
 */
export default function Stage({
  clock,
  transport,
  index,
  match,
  timeline,
  verifiedFor,
  onVideo,
  video: file,
  replay = null,
  onRemoveVideo,
  onUpload,
}: {
  clock: PlaybackClock
  transport: Transport
  index: PositionIndex | null
  match: MatchState | null
  timeline: FormationTimeline | null
  /** id of an agent-confirmed change the team is showing at time t, if any */
  verifiedFor: (side: TeamSide, t: number) => string | null
  onVideo: (v: VideoSource | null) => void
  video: LocalVideo | null
  replay?: TeamTrackReplay | null
  onRemoveVideo: () => void
  onUpload: () => void
}) {
  const t = useClockTime(clock, 8)
  const rangeId = useId()
  const videoRef = useRef<HTMLVideoElement>(null)
  const standbyRef = useRef<HTMLVideoElement>(null)
  const [activeSlot, setActiveSlot] = useState(0)
  const [activeClip, setActiveClip] = useState<string | null>(null)
  const [replayError, setReplayError] = useState<{ source: TeamTrackReplay; message: string } | null>(null)
  // a file the browser failed to decode at runtime (by url); it then counts as not playable
  const [brokenUrl, setBrokenUrl] = useState<string | null>(null)
  const filePlayable = Boolean(file && file.playable !== false && brokenUrl !== file.url)
  const names = timeline?.teamNames ?? { home: 'White', away: 'Blue' }

  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    if (replay) {
      // two elements: one plays, the other loads the next 30 s clip (no hitch at the boundary)
      const els = standbyRef.current ? [el, standbyRef.current] : [el]
      const source = new TeamTrackVideoSource(els, replay.clips, (clip) => setActiveClip(clip.id),
        (message) => setReplayError({ source: replay, message }), setActiveSlot)
      clock.attachSource(source.now)
      onVideo(source)
      return () => {
        source.dispose()
        clock.attachSource(null)
        onVideo(null)
      }
    }
    if (!file || !filePlayable) return
    const source: VideoSource = { el, offset: file.offset }
    clock.attachSource(() => source.offset + el.currentTime)
    onVideo(source)
    return () => {
      clock.attachSource(null)
      onVideo(null)
    }
  }, [file, filePlayable, replay, clock, onVideo])

  const pitch = match ? (
    <PitchCanvas
      index={index}
      pitch={match.pitch}
      clock={clock}
      variant="mini"
      className="size-full"
      label={`Top-down pitch at ${formatClock(t)}. ${names.home} in coral attacks right, ${names.away} in blue attacks left.`}
    />
  ) : (
    <Skeleton className="size-full" />
  )

  return (
    <section aria-labelledby="stage-title" className="flex flex-col overflow-hidden rounded-(--radius-card) border border-line bg-surface">
      <h2 id="stage-title" className="sr-only">
        Pitch and video
      </h2>
      <div className="flex items-start justify-between gap-4 px-5 pt-3 sm:px-6">
        <FormationChip side="home" name={names.home} timeline={timeline} t={t} confirmedId={verifiedFor('home', t)} />
        <div className="pt-1 text-center">
          <span className="font-mono text-lg text-text tabular sm:text-xl">{formatClock(t)}</span>
        </div>
        <FormationChip side="away" name={names.away} timeline={timeline} t={t} confirmedId={verifiedFor('away', t)} />
      </div>

      {replay || file ? (
        <div data-layout="side-by-side"
          className="mx-auto mt-3 grid w-[calc(100%-1.5rem)] grid-cols-1 gap-3 sm:w-[calc(100%-2rem)] min-[900px]:grid-cols-2">
          <div data-panel="video" className="min-w-0 overflow-hidden rounded-xl border border-line bg-black">
            <div className="relative aspect-video">
              {replay ? (
                <>
                  <video
                    key="teamtrack-replay-0"
                    ref={videoRef}
                    muted
                    playsInline
                    {...replayVideoProps(0, activeSlot, activeClip)}
                  />
                  <video
                    key="teamtrack-replay-1"
                    ref={standbyRef}
                    muted
                    playsInline
                    {...replayVideoProps(1, activeSlot, activeClip)}
                  />
                </>
              ) : file && filePlayable ? (
                <video
                  key={file.url}
                  ref={videoRef}
                  src={file.url}
                  muted
                  playsInline
                  preload="metadata"
                  onError={() => setBrokenUrl(file.url)}
                  className="size-full bg-black object-contain"
                  aria-label={`Your video ${file.name}, starting at match time ${formatClock(file.offset)}`}
                />
              ) : (
                <div role="status" className="grid size-full place-items-center bg-surface-2 p-6 text-center text-sm text-muted">
                  {CANNOT_PREVIEW}
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 bg-surface px-3 py-2 text-xs text-muted">
              {replay ? (
                <>
                  <span>{replay.label}</span>
                  <span className="font-mono tabular">Clip {activeClip ?? 'loading'}</span>
                </>
              ) : file ? (
                <>
                  <span className="min-w-0 truncate">Your video · {file.name}</span>
                  <span className="font-mono tabular">from {formatClock(file.offset)}</span>
                </>
              ) : null}
            </div>
            {replay && replayError?.source === replay && <p role="alert" className="bg-danger/10 px-3 py-2 text-sm text-danger">{replayError.message}</p>}
          </div>
          <div data-panel="pitch" className="aspect-[110/73] min-w-0 overflow-hidden rounded-xl border border-line bg-bg" aria-label="Synchronized tactical map">
            {pitch}
          </div>
        </div>
      ) : (
        <div data-layout="pitch-only" className="relative mx-auto mt-3 aspect-[110/73] w-[calc(100%-1.5rem)] max-w-[calc(40vh*110/73)] sm:w-[calc(100%-2rem)]">
          {pitch}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
        <button
          type="button"
          onClick={transport.toggle}
          className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-on-accent"
          aria-label={transport.playing ? 'Pause' : 'Play'}
        >
          {transport.playing ? <Pause className="size-4" aria-hidden="true" /> : <Play className="size-4 translate-x-px" aria-hidden="true" />}
        </button>
        <label htmlFor={rangeId} className="sr-only">
          Match time
        </label>
        <input
          id={rangeId}
          type="range"
          min={clock.min}
          max={clock.max}
          step={0.5}
          value={t}
          onChange={(e) => transport.seek(Number(e.target.value))}
          aria-valuetext={formatClock(t)}
          className="h-1.5 min-w-32 flex-1 cursor-pointer accent-[var(--accent)]"
        />
        <div role="group" aria-label="Playback speed" className="flex rounded-full border border-line p-0.5">
          {RATES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => transport.setRate(r)}
              aria-pressed={transport.rate === r}
              className={`rounded-full px-2.5 py-1 font-mono text-xs ${transport.rate === r ? 'bg-surface-2 text-text' : 'text-muted hover:text-text'}`}
            >
              {r}×
            </button>
          ))}
        </div>
        {file && !replay ? (
          <button
            type="button"
            onClick={onRemoveVideo}
            className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-sm text-muted hover:bg-surface-2 hover:text-text"
          >
            <X className="size-4" aria-hidden="true" /> Remove video
          </button>
        ) : null}
        <UploadButton onClick={onUpload} />
      </div>
    </section>
  )
}

/** One of the two stacked replay elements; only the playing one is visible and labelled. */
function replayVideoProps(slot: number, activeSlot: number, activeClip: string | null) {
  const active = slot === activeSlot
  return {
    'data-replay-video': slot,
    preload: 'metadata',
    className: 'absolute inset-0 size-full bg-black object-contain',
    // initial only: the player switches opacity directly at the boundary (React never resets it)
    style: { opacity: slot === 0 ? 1 : 0 },
    'aria-hidden': active ? undefined : true,
    'aria-label': active ? `Recorded TeamTrack match video, ${activeClip ?? 'loading segment'}` : undefined,
  } as const
}
