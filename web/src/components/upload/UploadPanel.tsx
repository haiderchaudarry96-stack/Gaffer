import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ArrowLeft, ArrowRight, Check, CloudOff, FileVideo, Loader2, Upload } from 'lucide-react'
import Dialog from '../app/Dialog'
import { Button } from '../ui/Button'
import PitchPoints from './PitchPoints'
import { formatBytes, formatDuration, isAcceptedVideo, readVideo, type LocalVideoInfo } from './readVideo'
import { apiConfigured } from '../../data/api'
import {
  estimateProcessingSeconds,
  getAnalysisStatus,
  loadAnalysisResult,
  SECONDS_PER_VIDEO_SECOND,
  STAGE_LABELS,
  STAGES,
  startAnalysis,
  uploadVideo,
  type AnalysisResult,
  type AnalysisStatus,
  type PixelPoint,
} from '../../data/analysis'

type Step =
  | { kind: 'choose' }
  | { kind: 'place' }
  | { kind: 'not-connected' }
  | { kind: 'progress'; status: AnalysisStatus | null; upload: number }
  | { kind: 'error'; message: string }

const POLL_MS = 2000

/**
 * Upload for analysis: choose a video -> show us where the pitch is -> analyse.
 * Talks to the backend only through src/data/analysis.ts. Without VITE_API_URL it says the
 * server is not connected and offers the analysed demo match: no fake progress, no fake results.
 */
export default function UploadPanel({
  open,
  onClose,
  onUseDemo,
  onResult,
}: {
  open: boolean
  onClose: () => void
  /** play the chosen file next to the stored demo analysis */
  onUseDemo: (video: LocalVideoInfo) => void
  onResult: (result: AnalysisResult, video: LocalVideoInfo) => void
}) {
  const [step, setStep] = useState<Step>({ kind: 'choose' })
  const [video, setVideo] = useState<LocalVideoInfo | null>(null)
  const [reading, setReading] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)
  const [points, setPoints] = useState<PixelPoint[]>([])
  const [straightDown, setStraightDown] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const pick = async (file: File | undefined) => {
    if (!file) return
    setFileError(null)
    if (!isAcceptedVideo(file)) {
      setFileError('Please choose an MP4 or MOV video.')
      return
    }
    setReading(true)
    try {
      const info = await readVideo(file)
      if (video) URL.revokeObjectURL(video.url)
      setVideo(info)
      setPoints([])
      setStraightDown(false)
    } catch (e) {
      setFileError(e instanceof Error ? e.message : 'Could not read this video.')
    } finally {
      setReading(false)
    }
  }

  const start = async () => {
    if (!video || points.length !== 4) return
    if (!apiConfigured()) {
      setStep({ kind: 'not-connected' })
      return
    }
    setStep({ kind: 'progress', status: null, upload: 0 })
    try {
      const created = await uploadVideo(video.file, (f) => alive.current && setStep({ kind: 'progress', status: null, upload: f }))
      let status = await startAnalysis(created.id, {
        points: points as [PixelPoint, PixelPoint, PixelPoint, PixelPoint],
        frame: { width: video.width, height: video.height, t_s: video.frameT },
        straight_down: straightDown,
      })
      while (alive.current && status.status !== 'done' && status.status !== 'failed') {
        setStep({ kind: 'progress', status, upload: 1 })
        await new Promise((r) => setTimeout(r, POLL_MS))
        status = await getAnalysisStatus(created.id)
      }
      if (!alive.current) return
      if (status.status === 'failed') throw new Error(status.error ?? 'The analysis failed on the server.')
      setStep({ kind: 'progress', status, upload: 1 })
      const result = await loadAnalysisResult(created.id)
      onResult(result, video)
    } catch (e) {
      if (alive.current) setStep({ kind: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void pick(e.dataTransfer.files?.[0])
  }

  const est = video ? estimateProcessingSeconds(video.duration) : 0
  const title = step.kind === 'place' ? 'Show us where the pitch is' : step.kind === 'not-connected' ? 'Not connected' : 'Upload for analysis'

  return (
    <Dialog open={open} onClose={onClose} title={title} wide>
      <div className="p-5 sm:p-6">
        <ol className="mb-6 flex flex-wrap gap-x-5 gap-y-1 text-sm" aria-label="Steps">
          {['Choose a video', 'Show us where the pitch is', 'Analyse'].map((label, i) => {
            const at = step.kind === 'choose' ? 0 : step.kind === 'place' ? 1 : 2
            return (
              <li key={label} className={`flex items-center gap-2 ${i === at ? 'font-semibold text-text' : 'text-muted'}`} aria-current={i === at ? 'step' : undefined}>
                <span className={`grid size-6 place-items-center rounded-full text-xs ${i < at ? 'bg-accent text-on-accent' : i === at ? 'border-2 border-text' : 'border border-line'}`}>
                  {i < at ? <Check className="size-3.5" aria-hidden="true" /> : i + 1}
                </span>
                {label}
              </li>
            )
          })}
        </ol>

        {step.kind === 'choose' && (
          <div className="space-y-5">
            <label
              htmlFor="upload-file"
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${dragOver ? 'border-accent-ink bg-accent/10' : 'border-line bg-bg hover:border-muted'}`}
            >
              <Upload className="size-7 text-muted" aria-hidden="true" />
              <span className="font-display text-lg font-semibold text-text">Drop a match video here</span>
              <span className="text-sm text-muted">MP4 or MOV</span>
              <span className="mt-1 inline-flex h-10 items-center rounded-full bg-accent px-5 text-sm font-semibold text-on-accent">Choose file</span>
              <input
                ref={inputRef}
                id="upload-file"
                type="file"
                accept="video/mp4,video/quicktime,.mp4,.mov"
                className="sr-only"
                onChange={(e) => void pick(e.target.files?.[0])}
              />
            </label>
            <p className="text-sm text-muted">
              Works best with a drone or fixed camera that shows the whole pitch. Panning/zooming cameras are not supported.
            </p>
            {reading && (
              <p className="flex items-center gap-2 text-sm text-muted" role="status">
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> Reading the video in your browser…
              </p>
            )}
            {fileError && (
              <p className="text-sm text-danger" role="alert">
                {fileError}
              </p>
            )}
            {video && (
              <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-line bg-surface p-4">
                <img src={video.frameUrl} alt="" className="h-16 w-28 rounded-lg object-cover" />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 font-medium break-all text-text">
                    <FileVideo className="size-4 shrink-0 text-muted" aria-hidden="true" /> {video.file.name}
                  </p>
                  <p className="mt-1 font-mono text-sm text-muted">
                    {formatBytes(video.file.size)} · {formatDuration(video.duration)} · {video.width}×{video.height}
                  </p>
                </div>
                <Button onClick={() => setStep({ kind: 'place' })}>
                  Next <ArrowRight className="size-4" aria-hidden="true" />
                </Button>
              </div>
            )}
          </div>
        )}

        {step.kind === 'place' && video && (
          <div className="space-y-5">
            <PitchPoints
              frameUrl={video.frameUrl}
              fileName={video.file.name}
              width={video.width}
              height={video.height}
              points={points}
              straightDown={straightDown}
              onChange={(p, s) => {
                setPoints(p)
                setStraightDown(s)
              }}
            />
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <Button variant="ghost" onClick={() => setStep({ kind: 'choose' })}>
                <ArrowLeft className="size-4" aria-hidden="true" /> Back
              </Button>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted">About {formatDuration(est)} of processing, plus agent checks</span>
                <Button onClick={() => void start()} disabled={points.length !== 4}>
                  Start analysis
                </Button>
              </div>
            </div>
          </div>
        )}

        {step.kind === 'not-connected' && video && (
          <div className="space-y-5" role="status">
            <div className="flex items-start gap-4 rounded-2xl border border-warn/40 bg-warn/5 p-5">
              <CloudOff className="mt-0.5 size-6 shrink-0 text-warn" aria-hidden="true" />
              <div>
                <p className="font-display text-xl font-semibold text-text">Analysis server not connected in this demo build</p>
                <p className="mt-2 text-muted">
                  Nothing was uploaded and nothing was analysed. Your video and the 4 points stay in this browser. In the full
                  product this step sends both to Gaffer’s backend (OpenCV on AWS) and shows its progress here.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="ghost" onClick={() => setStep({ kind: 'place' })}>
                <ArrowLeft className="size-4" aria-hidden="true" /> Back
              </Button>
              <Button onClick={() => onUseDemo(video)}>Open the analysed demo match instead</Button>
            </div>
            <p className="text-xs text-muted">Your video then plays next to the stored analysis of the demo match (TeamTrack, 15:00–21:00).</p>
          </div>
        )}

        {step.kind === 'progress' && video && (
          <div className="space-y-5">
            <ol className="space-y-3" aria-label="Analysis progress">
              {STAGES.map((s) => {
                const current = step.status?.stage ?? 'uploading'
                const ci = STAGES.indexOf(current)
                const si = STAGES.indexOf(s)
                const done = si < ci || (s === 'done' && step.status?.status === 'done')
                const active = si === ci && !done
                return (
                  <li key={s} className={`flex items-center gap-3 ${active ? 'font-semibold text-text' : done ? 'text-text' : 'text-muted'}`}>
                    <span className={`grid size-7 place-items-center rounded-full ${done ? 'bg-accent text-on-accent' : active ? 'border-2 border-accent-ink' : 'border border-line'}`}>
                      {done ? <Check className="size-4" aria-hidden="true" /> : active ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
                    </span>
                    {STAGE_LABELS[s]}
                    {active && s === 'uploading' && <span className="ml-auto font-mono text-sm">{Math.round(step.upload * 100)} %</span>}
                  </li>
                )
              })}
            </ol>
            {step.status && (
              <div aria-live="polite">
                <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full origin-left rounded-full bg-accent transition-transform duration-500" style={{ transform: `scaleX(${step.status.progress})` }} />
                </div>
                <p className="mt-2 font-mono text-sm text-text">{Math.round(step.status.progress * 100)} %</p>
              </div>
            )}
            <p className="text-sm text-muted">
              Estimate: about {SECONDS_PER_VIDEO_SECOND} s of processing per second of video ({formatDuration(est)} for this file), plus agent
              checks{step.status?.eta_s != null ? `; the server says about ${formatDuration(step.status.eta_s)} left` : ''}.
            </p>
          </div>
        )}

        {step.kind === 'error' && (
          <div className="space-y-4" role="alert">
            <p className="font-display text-xl font-semibold text-text">The analysis did not finish</p>
            <p className="text-muted">{step.message}</p>
            <Button variant="ghost" onClick={() => setStep({ kind: 'place' })}>
              <ArrowLeft className="size-4" aria-hidden="true" /> Back
            </Button>
          </div>
        )}
      </div>
    </Dialog>
  )
}
