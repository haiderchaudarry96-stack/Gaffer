import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ArrowLeft, ArrowRight, Check, CloudOff, FileVideo, Loader2, PlayCircle, Upload } from 'lucide-react'
import Dialog from '../app/Dialog'
import { Button } from '../ui/Button'
import PitchPoints from './PitchPoints'
import FootageGuide from './FootageGuide'
import { formatBytes, formatDuration, isAcceptedVideo, readVideo, unreadableVideo, type LocalVideoInfo } from './readVideo'
import { apiConfigured } from '../../data/api'
import {
  analysisFrameUrl,
  confirmPitch,
  estimateProcessingSeconds,
  getAnalysisStatus,
  getSampleClip,
  loadAnalysisResult,
  needsPitchStep,
  SECONDS_PER_VIDEO_SECOND,
  setPitchPoints,
  startSampleAnalysis,
  STAGE_LABELS,
  STAGES,
  uploadVideo,
  type AnalysisResult,
  type AnalysisStatus,
  type PixelPoint,
  type SampleClip,
} from '../../data/analysis'

type Step =
  | { kind: 'choose' }
  /** not connected: the 4 points on the frame the browser read (nothing leaves the browser) */
  | { kind: 'place' }
  | { kind: 'not-connected' }
  /** connected: OpenCV found the pitch; the coach confirms the outline or adjusts it */
  | { kind: 'confirm'; status: AnalysisStatus }
  /** connected: the 4 points on the server's reference frame (adjust, or OpenCV was not sure) */
  | { kind: 'mark'; status: AnalysisStatus; adjusting: boolean }
  | { kind: 'progress'; status: AnalysisStatus | null; upload: number }
  | { kind: 'error'; message: string; back: Step | null }

const POLL_MS = 2000
const toPoints = (c: [number, number][] | null | undefined): PixelPoint[] => (c ?? []).map(([x, y]) => ({ x, y }))

/**
 * Upload for analysis.
 * Connected (VITE_API_URL set): choose a video -> upload -> the server's pitch step
 * (needs_confirmation: "Is this your pitch?" on OpenCV's outline; needs_corners: the guided
 * 4-point screen, preloaded with OpenCV's best guess) -> progress -> the result replaces the demo.
 * Not connected: choose -> 4 points on the browser's frame -> "not connected", and the analysed
 * demo match instead. No fake progress, no fake results.
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
  const connected = apiConfigured()
  const [step, setStep] = useState<Step>({ kind: 'choose' })
  const [video, setVideo] = useState<LocalVideoInfo | null>(null)
  const [reading, setReading] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)
  const [points, setPoints] = useState<PixelPoint[]>([])
  const [straightDown, setStraightDown] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const alive = useRef(true)
  const [sample, setSample] = useState<SampleClip | null>(null)

  // "Try it with a sample clip": only when the server holds one (hidden otherwise)
  useEffect(() => {
    if (!open || !connected) return
    let live = true
    getSampleClip().then((s) => live && setSample(s), () => live && setSample(null))
    return () => {
      live = false
    }
  }, [open, connected])

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
      let info: LocalVideoInfo
      try {
        info = await readVideo(file)
      } catch (e) {
        // connected, the server reads the video with OpenCV: a browser that cannot preview it
        // (codec) is no reason to refuse the upload
        if (!connected) throw e
        info = unreadableVideo(file)
      }
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

  const fail = (e: unknown, back: Step | null) => {
    if (alive.current) setStep({ kind: 'error', message: e instanceof Error ? e.message : String(e), back })
  }

  /** poll until done or failed, then hand the result to the desk */
  const follow = async (first: AnalysisStatus) => {
    if (!video) return
    let status = first
    while (alive.current && status.status !== 'done' && status.status !== 'failed') {
      setStep({ kind: 'progress', status, upload: 1 })
      await new Promise((r) => setTimeout(r, POLL_MS))
      status = await getAnalysisStatus(first.id)
    }
    if (!alive.current) return
    if (status.status === 'failed') throw new Error(status.error ?? 'The analysis failed on the server.')
    setStep({ kind: 'progress', status, upload: 1 })
    onResult(await loadAnalysisResult(first.id), video)
  }

  /** where the server's answer to an upload leads */
  const route = async (status: AnalysisStatus) => {
    if (status.status === 'needs_confirmation') {
      setPoints(toPoints(status.pitch?.corners))
      setStep({ kind: 'confirm', status })
    } else if (status.status === 'needs_corners') {
      setPoints(toPoints(status.pitch?.suggested_corners))
      setStraightDown(false)
      setStep({ kind: 'mark', status, adjusting: false })
    } else {
      await follow(status)
    }
  }

  /** connected: the server analyses its own sample clip as an unknown upload (pitch check runs) */
  const trySample = async () => {
    if (!sample) return
    const info: LocalVideoInfo = { file: new File([], sample.fileName, { type: 'video/mp4' }), url: sample.videoUrl,
      duration: 0, width: 0, height: 0, frameUrl: '', frameT: 0, previewable: true }
    setVideo(info)
    setStep({ kind: 'progress', status: null, upload: 1 })
    try {
      const created = await startSampleAnalysis()
      const v = created.video
      setVideo({ ...info, duration: v?.duration_s ?? 0, width: v?.width ?? 0, height: v?.height ?? 0 })
      await route(created)
    } catch (e) {
      fail(e, { kind: 'choose' })
    }
  }

  /** connected: upload first, the server decides the pitch step */
  const upload = async () => {
    if (!video) return
    setStep({ kind: 'progress', status: null, upload: 0 })
    try {
      const created = await uploadVideo(video.file, (f) => alive.current && setStep({ kind: 'progress', status: null, upload: f }))
      await route(created)
    } catch (e) {
      fail(e, { kind: 'choose' })
    }
  }

  const send = async (call: () => Promise<AnalysisStatus>, back: Step) => {
    setBusy(true)
    try {
      const status = await call()
      setBusy(false)
      if (needsPitchStep(status)) await route(status)
      else await follow(status)
    } catch (e) {
      setBusy(false)
      fail(e, back)
    }
  }

  /** not connected: the 4 points stay in the browser; say so plainly */
  const startOffline = () => {
    if (video && points.length === 4) setStep({ kind: 'not-connected' })
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void pick(e.dataTransfer.files?.[0])
  }

  const est = video ? estimateProcessingSeconds(video.duration) : 0
  const title =
    step.kind === 'confirm'
      ? 'Is this your pitch?'
      : step.kind === 'place' || step.kind === 'mark'
        ? 'Show us where the pitch is'
        : step.kind === 'not-connected'
          ? 'Not connected'
          : 'Upload for analysis'
  const at = step.kind === 'choose' ? 0 : step.kind === 'place' || step.kind === 'confirm' || step.kind === 'mark' ? 1 : 2

  return (
    <Dialog open={open} onClose={onClose} title={title} wide>
      <div className="p-5 sm:p-6">
        <ol className="mb-6 flex flex-wrap gap-x-5 gap-y-1 text-sm" aria-label="Steps">
          {['Choose a video', 'Show us where the pitch is', 'Analyse'].map((label, i) => (
            <li key={label} className={`flex items-center gap-2 ${i === at ? 'font-semibold text-text' : 'text-muted'}`} aria-current={i === at ? 'step' : undefined}>
              <span className={`grid size-6 place-items-center rounded-full text-xs ${i < at ? 'bg-accent text-on-accent' : i === at ? 'border-2 border-text' : 'border border-line'}`}>
                {i < at ? <Check className="size-3.5" aria-hidden="true" /> : i + 1}
              </span>
              {label}
            </li>
          ))}
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
            {connected && sample && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-4">
                <div>
                  <p className="font-medium text-text">No video at hand?</p>
                  <p className="text-sm text-muted">{sample.label}, held by this server ({formatBytes(sample.bytes)}). It goes through the same pitch check as an upload.</p>
                </div>
                <Button variant="ghost" onClick={() => void trySample()}>
                  <PlayCircle className="size-4" aria-hidden="true" /> Try it with a sample clip
                </Button>
              </div>
            )}
            <FootageGuide />
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
                {video.frameUrl ? (
                  <img src={video.frameUrl} alt="" className="h-16 w-28 rounded-lg object-cover" />
                ) : (
                  <span className="grid h-16 w-28 place-items-center rounded-lg bg-surface-2" aria-hidden="true">
                    <FileVideo className="size-6 text-muted" />
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 font-medium break-all text-text">
                    <FileVideo className="size-4 shrink-0 text-muted" aria-hidden="true" /> {video.file.name}
                  </p>
                  <p className="mt-1 font-mono text-sm text-muted">
                    {formatBytes(video.file.size)}
                    {video.previewable ? ` · ${formatDuration(video.duration)} · ${video.width}×${video.height}` : ''}
                  </p>
                  {!video.previewable && <p className="mt-1 text-xs text-muted">This browser can’t preview it; Gaffer’s server reads it with OpenCV.</p>}
                </div>
                <Button onClick={() => (connected ? void upload() : setStep({ kind: 'place' }))}>
                  {connected ? 'Upload' : 'Next'} <ArrowRight className="size-4" aria-hidden="true" />
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
                <Button onClick={startOffline} disabled={points.length !== 4}>
                  Start analysis
                </Button>
              </div>
            </div>
          </div>
        )}

        {step.kind === 'confirm' && video && (
          <div className="space-y-5">
            <p className="text-lg text-text">We found the pitch. Check that the green outline sits on the pitch’s boundary lines.</p>
            {step.status.pitch?.preview_url ? (
              <img
                src={step.status.pitch.preview_url}
                alt={`First frame of ${video.file.name} with the pitch outline Gaffer found, corners numbered 1 to 4`}
                className="mx-auto max-h-[52vh] w-auto max-w-full rounded-xl border border-line"
                data-testid="pitch-preview"
              />
            ) : (
              <p className="text-muted">The outline image is missing.</p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setPoints(toPoints(step.status.pitch?.corners))
                  setStraightDown(false)
                  setStep({ kind: 'mark', status: step.status, adjusting: true })
                }}
              >
                No, let me adjust
              </Button>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted">About {formatDuration(estimateProcessingSeconds(step.status.video?.duration_s ?? video.duration))} of processing, plus agent checks</span>
                <Button disabled={busy} onClick={() => void send(() => confirmPitch(step.status.id), step)}>
                  {busy ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Check className="size-4" aria-hidden="true" />} Yes, looks right
                </Button>
              </div>
            </div>
          </div>
        )}

        {step.kind === 'mark' && video && step.status.video && (
          <div className="space-y-5">
            <p className="text-sm text-muted" role="status">
              {step.adjusting
                ? 'Our outline is loaded: drag the numbered points onto the pitch corners.'
                : step.status.pitch?.suggested_corners
                  ? 'We weren’t sure where the pitch is. Our best guess is loaded: drag the points onto the pitch corners.'
                  : 'We couldn’t find the pitch on our own. Click its 4 corners in order.'}
            </p>
            <PitchPoints
              frameUrl={analysisFrameUrl(step.status.id)}
              fileName={video.file.name}
              width={step.status.video.width}
              height={step.status.video.height}
              points={points}
              straightDown={straightDown}
              onChange={(p, s) => {
                setPoints(p)
                setStraightDown(s)
              }}
            />
            <div className="sticky bottom-0 z-20 -mx-1 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface px-1 pt-4 pb-1">
              <Button variant="ghost" disabled={busy} onClick={() => (step.adjusting ? setStep({ kind: 'confirm', status: step.status }) : setStep({ kind: 'choose' }))}>
                <ArrowLeft className="size-4" aria-hidden="true" /> Back
              </Button>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted">About {formatDuration(estimateProcessingSeconds(step.status.video.duration_s))} of processing, plus agent checks</span>
                <Button disabled={points.length !== 4 || busy} onClick={() => void send(() => setPitchPoints(step.status.id, points), step)}>
                  {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />} Start analysis
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

        {step.kind === 'progress' && video && <Progress step={step} est={estimateProcessingSeconds(step.status?.video?.duration_s ?? video.duration)} />}

        {step.kind === 'error' && (
          <div className="space-y-4" role="alert">
            <p className="font-display text-xl font-semibold text-text">The analysis did not start or finish</p>
            <p className="text-muted">{step.message}</p>
            <Button variant="ghost" onClick={() => setStep(step.back ?? { kind: 'choose' })}>
              <ArrowLeft className="size-4" aria-hidden="true" /> Back
            </Button>
          </div>
        )}
      </div>
    </Dialog>
  )
}

function Progress({ step, est }: { step: Extract<Step, { kind: 'progress' }>; est: number }) {
  const st = step.status
  // queued: the upload is done and the analyser has not picked it up yet
  const current = st?.status === 'queued' ? 'detecting' : (st?.stage ?? 'uploading')
  const ci = STAGES.indexOf(current)
  return (
    <div className="space-y-5">
      <ol className="space-y-3" aria-label="Analysis progress">
        {STAGES.map((s) => {
          const si = STAGES.indexOf(s)
          const done = si < ci || (s === 'done' && st?.status === 'done')
          const active = si === ci && !done
          return (
            <li key={s} className={`flex items-center gap-3 ${active ? 'font-semibold text-text' : done ? 'text-text' : 'text-muted'}`}>
              <span className={`grid size-7 place-items-center rounded-full ${done ? 'bg-accent text-on-accent' : active ? 'border-2 border-accent-ink' : 'border border-line'}`}>
                {done ? <Check className="size-4" aria-hidden="true" /> : active ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
              </span>
              {STAGE_LABELS[s]}
              {active && s === 'uploading' && <span className="ml-auto font-mono text-sm">{Math.round(step.upload * 100)} %</span>}
              {active && st?.status === 'queued' && <span className="ml-auto text-sm font-normal text-muted">waiting for the analyser…</span>}
            </li>
          )
        })}
      </ol>
      {st && (
        <div aria-live="polite">
          <div className="h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full origin-left rounded-full bg-accent transition-transform duration-500" style={{ transform: `scaleX(${st.progress})` }} />
          </div>
          <p className="mt-2 font-mono text-sm text-text">{Math.round(st.progress * 100)} %</p>
        </div>
      )}
      <p className="text-sm text-muted">
        Estimate: about {SECONDS_PER_VIDEO_SECOND} s of processing per second of video
        {est > 0 ? ` (${formatDuration(est)} for this file)` : ''}, plus agent checks
        {st?.eta_s != null ? `; the server says about ${formatDuration(st.eta_s)} left` : ''}.
      </p>
    </div>
  )
}
