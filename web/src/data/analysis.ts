/**
 * Upload-for-analysis flow (contract in docs/API.md).
 *
 *   uploadVideo(file)                -> POST /api/analyses              (multipart "video")
 *        -> queued (known TeamTrack drone clip), needs_confirmation (OpenCV found the pitch:
 *           show pitch.preview_url) or needs_corners (not sure: the coach marks 4 corners)
 *   confirmPitch(id)                 -> POST /api/analyses/{id}/pitch   {confirmed: true}
 *   setPitchPoints(id, points)       -> POST /api/analyses/{id}/pitch   {pitch_points}
 *   startAnalysis(id, pitchPoints)   -> POST /api/analyses/{id}/start   (JSON, same as above)
 *   getAnalysisStatus(id)            -> GET  /api/analyses/{id}
 *   loadAnalysisResult(id)           -> GET  /api/analyses/{id}/result
 *
 * Without VITE_API_URL every call throws ApiNotConfigured: the UI must say the server is not
 * connected and never show progress or results it did not get from the server.
 */
import { apiGet, apiPost, apiUpload, apiUrl, type ApiOptions } from './api'
import type { Alert, CoachReport, FormationTimeline, MatchState, TacticalTimeline, TraceStep } from './types'
import { arr, DataError, num, obj, oneOf, str, validateAlert, validateCoachReport, validateMatchState, validateTraceStep } from './validate'

/** One point the coach placed, in pixels of the video frame (origin top-left). */
export interface PixelPoint {
  x: number
  y: number
}

export interface PitchPointsRequest {
  /** exactly 4: pitch top-left, top-right, bottom-right, bottom-left as seen in the frame */
  points: [PixelPoint, PixelPoint, PixelPoint, PixelPoint]
  frame: { width: number; height: number; t_s: number }
  /** the coach said the video already looks straight down on the full pitch (points = frame edges) */
  straight_down: boolean
}

export const STAGES = ['uploading', 'detecting', 'teams', 'agent', 'done'] as const
export type AnalysisStage = (typeof STAGES)[number]
export const STAGE_LABELS: Record<AnalysisStage, string> = {
  uploading: 'Uploading',
  detecting: 'Detecting players (OpenCV)',
  teams: 'Teams and formations',
  agent: 'Agent checking changes',
  done: 'Done',
}

export const ANALYSIS_STATES = ['uploaded', 'needs_confirmation', 'needs_corners', 'queued', 'running', 'done', 'failed'] as const
export type AnalysisState = (typeof ANALYSIS_STATES)[number]

/** The pitch step of an upload (docs/API.md "Pitch step"); corners are video pixels TL, TR, BR, BL. */
export interface PitchInfo {
  state: string
  /** detected (needs_confirmation) or applied corners */
  corners: [number, number][] | null
  /** needs_corners: OpenCV's best guess, only to preload the 4-point screen (never used unconfirmed) */
  suggested_corners: [number, number][] | null
  /** JPEG of the frame with the outline the corners give */
  preview_url: string | null
  message: string | null
}

export interface AnalysisStatus {
  id: string
  status: AnalysisState
  stage: AnalysisStage
  /** overall progress 0..1, as reported by the server */
  progress: number
  /** server's estimate of the remaining seconds, if it has one */
  eta_s: number | null
  /** remaining estimated budget for agent checks, separate from the server ETA */
  agent_eta_s: number | null
  error: string | null
  /** queued only: analyses that run before this one (the one running now plus those queued earlier) */
  queue_ahead: number | null
  pitch: PitchInfo | null
  /** the uploaded video as the server read it */
  video: { width: number; height: number; duration_s: number } | null
}

export interface AnalysisResult {
  id: string
  label: string
  match_state: MatchState
  timeline: TacticalTimeline
  alerts: Alert[]
  trace: TraceStep[]
  report: CoachReport | null
  /** pixels per metre of the pitch and, below the server's threshold, one plain line (never blocks) */
  resolution: ResolutionNote | null
}

export interface ResolutionNote {
  px_per_m: number | null
  low: boolean
  message: string | null
}

function resolutionNote(v: unknown): ResolutionNote | null {
  if (v === null || v === undefined) return null
  const r = obj(v, 'result.resolution')
  return {
    px_per_m: typeof r.px_per_m === 'number' ? r.px_per_m : null,
    low: r.low === true,
    message: typeof r.message === 'string' ? r.message : null,
  }
}

function corners(v: unknown, path: string): [number, number][] | null {
  if (v === null || v === undefined) return null
  const a = arr(v, path)
  if (a.length !== 4) throw new DataError(`${path}: expected 4 corners, got ${a.length}`)
  return a.map((c, i) => {
    const xy = arr(c, `${path}[${i}]`)
    return [num(xy[0], `${path}[${i}][0]`), num(xy[1], `${path}[${i}][1]`)]
  })
}

function validatePitch(raw: unknown): PitchInfo | null {
  if (raw === null || raw === undefined) return null
  const p = obj(raw, 'analysis.pitch')
  return {
    state: typeof p.state === 'string' ? p.state : 'unknown',
    corners: corners(p.corners, 'analysis.pitch.corners'),
    suggested_corners: corners(p.suggested_corners, 'analysis.pitch.suggested_corners'),
    preview_url: typeof p.preview_url === 'string' ? p.preview_url : null,
    message: typeof p.message === 'string' ? p.message : null,
  }
}

export function validateStatus(raw: unknown): AnalysisStatus {
  const s = obj(raw, 'analysis')
  str(s.id, 'analysis.id')
  oneOf(s.status, ANALYSIS_STATES, 'analysis.status')
  oneOf(s.stage, STAGES, 'analysis.stage')
  const p = num(s.progress, 'analysis.progress')
  if (p < 0 || p > 1) throw new DataError(`analysis.progress: expected 0..1, got ${p}`)
  if (s.eta_s !== null && s.eta_s !== undefined) num(s.eta_s, 'analysis.eta_s')
  if (s.agent_eta_s !== null && s.agent_eta_s !== undefined) num(s.agent_eta_s, 'analysis.agent_eta_s')
  let video: AnalysisStatus['video'] = null
  if (s.video && typeof s.video === 'object') {
    const v = obj(s.video, 'analysis.video')
    video = { width: num(v.width, 'analysis.video.width'), height: num(v.height, 'analysis.video.height'), duration_s: typeof v.duration_s === 'number' ? v.duration_s : 0 }
  }
  return {
    id: s.id as string,
    status: s.status as AnalysisState,
    stage: s.stage as AnalysisStage,
    progress: p,
    eta_s: (s.eta_s as number | null) ?? null,
    agent_eta_s: (s.agent_eta_s as number | null) ?? null,
    error: typeof s.error === 'string' ? s.error : null,
    queue_ahead: s.status === 'queued' && typeof s.queue_position === 'number' ? s.queue_position : null,
    pitch: validatePitch(s.pitch),
    video,
  }
}

/** The status needs the coach before the analysis can start (pitch step). */
export function needsPitchStep(s: AnalysisStatus): boolean {
  return s.status === 'needs_confirmation' || s.status === 'needs_corners'
}

export function validateTacticalTimeline(raw: unknown): TacticalTimeline {
  const t = obj(raw, 'timeline')
  if (t.contract_version !== '1.0') throw new DataError(`timeline.contract_version: expected "1.0", got ${JSON.stringify(t.contract_version)}`)
  str(t.match_id, 'timeline.match_id')
  const teams = obj(t.teams, 'timeline.teams')
  str(teams.home, 'timeline.teams.home')
  str(teams.away, 'timeline.teams.away')
  arr(t.segments, 'timeline.segments').forEach((sg, i) => {
    const so = obj(sg, `timeline.segments[${i}]`)
    num(so.start_s, `timeline.segments[${i}].start_s`)
    num(so.end_s, `timeline.segments[${i}].end_s`)
    for (const side of ['home', 'away']) str(obj(so[side], `timeline.segments[${i}].${side}`).formation, `timeline.segments[${i}].${side}.formation`)
  })
  arr(t.events, 'timeline.events').forEach((e, i) => {
    const p = `timeline.events[${i}]`
    const eo = obj(e, p)
    str(eo.id, `${p}.id`)
    num(eo.t, `${p}.t`)
    oneOf(eo.team, ['home', 'away'], `${p}.team`)
    oneOf(eo.status, ['candidate', 'confirmed', 'rejected', 'uncertain'], `${p}.status`)
    if (eo.verification) oneOf(obj(eo.verification, `${p}.verification`).decision, ['confirmed', 'rejected', 'uncertain'], `${p}.verification.decision`)
  })
  return t as unknown as TacticalTimeline
}

/** Contract timeline -> the view model the desk draws (shape changes only). */
export function timelineFromContract(tt: TacticalTimeline): FormationTimeline {
  const seg = (s: TacticalTimeline['segments'][number]['home']) => ({
    formation: s.formation,
    line_m: s.defensive_line_m,
    depth_m: s.compactness_m,
    width_m: s.width_m,
  })
  const segments = tt.segments.map((s) => ({ start_s: s.start_s, end_s: s.end_s, home: seg(s.home), away: seg(s.away) }))
  return {
    start_s: segments[0]?.start_s ?? 0,
    end_s: segments.at(-1)?.end_s ?? 0,
    teamNames: { home: tt.teams.home, away: tt.teams.away },
    segments,
    events: tt.events
      .filter((e) => e.type === 'shape_change')
      .map((e) => ({
        id: e.id,
        team: e.team,
        t: e.t,
        from: e.from,
        to: e.to,
        status: e.verification?.decision ?? e.status,
        reason: e.verification?.reason ?? null,
      }))
      .sort((a, b) => a.t - b.t),
  }
}

export async function uploadVideo(file: File, onProgress?: (fraction: number) => void, opts?: ApiOptions): Promise<AnalysisStatus> {
  const form = new FormData()
  form.append('video', file, file.name)
  return validateStatus(await apiUpload('/api/analyses', form, 'Upload', onProgress, opts))
}

export interface SampleClip {
  id: string
  label: string
  title: string
  /** one line of truth about what this sample shows */
  note: string
  credit: string
  creditUrl: string | null
  bytes: number
  videoUrl: string
  /** plain file download, for anyone who wants to test with the file */
  downloadUrl: string
  fileName: string
}

/** The server's sample clips ("Try it with a sample clip"); empty when it holds none. */
export async function getSampleClips(opts?: ApiOptions): Promise<SampleClip[]> {
  const r = obj(await apiGet('/api/samples', 'Sample clips', opts), 'samples')
  return arr(r.samples, 'samples.samples').map((raw, i) => {
    const p = `samples.samples[${i}]`
    const s = obj(raw, p)
    return {
      id: str(s.id, `${p}.id`),
      label: str(s.label, `${p}.label`),
      title: typeof s.title === 'string' ? s.title : str(s.label, `${p}.label`),
      note: typeof s.note === 'string' ? s.note : '',
      credit: typeof s.credit === 'string' ? s.credit : '',
      creditUrl: typeof s.credit_url === 'string' ? s.credit_url : null,
      bytes: num(s.bytes, `${p}.bytes`),
      videoUrl: apiUrl(str(s.video_url, `${p}.video_url`), opts),
      downloadUrl: apiUrl(str(s.download_url, `${p}.download_url`), opts),
      fileName: str(s.file_name, `${p}.file_name`),
    }
  })
}

/** Analyse one of the server's sample clips as an unknown upload (the full pitch check runs). */
export async function startSampleAnalysis(id: string, opts?: ApiOptions): Promise<AnalysisStatus> {
  return validateStatus(await apiPost('/api/analyses/sample', { id }, 'Sample analysis', opts))
}

export async function startAnalysis(id: string, request: PitchPointsRequest, opts?: ApiOptions): Promise<AnalysisStatus> {
  if (request.points.length !== 4) throw new DataError('startAnalysis: exactly 4 pitch points are needed')
  return validateStatus(await apiPost(`/api/analyses/${encodeURIComponent(id)}/start`, request, 'Start analysis', opts))
}

/** "Yes, looks right": analyse with the corners OpenCV found. */
export async function confirmPitch(id: string, opts?: ApiOptions): Promise<AnalysisStatus> {
  return validateStatus(await apiPost(`/api/analyses/${encodeURIComponent(id)}/pitch`, { confirmed: true }, 'Confirm the pitch', opts))
}

/** The coach's 4 corners (top-left, top-right, bottom-right, bottom-left) in pixels of the server's reference frame. */
export async function setPitchPoints(id: string, points: PixelPoint[], opts?: ApiOptions): Promise<AnalysisStatus> {
  if (points.length !== 4) throw new DataError('setPitchPoints: exactly 4 pitch points are needed')
  const pitch_points = points.map((p) => [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10])
  return validateStatus(await apiPost(`/api/analyses/${encodeURIComponent(id)}/pitch`, { pitch_points }, 'Mark the pitch', opts))
}

/** The server's reference frame (the frame the 4 corners are measured on). */
export function analysisFrameUrl(id: string, opts?: ApiOptions): string {
  return apiUrl(`/api/analyses/${encodeURIComponent(id)}/frame`, opts)
}

export async function getAnalysisStatus(id: string, opts?: ApiOptions): Promise<AnalysisStatus> {
  return validateStatus(await apiGet(`/api/analyses/${encodeURIComponent(id)}`, 'Analysis status', opts))
}

export async function loadAnalysisResult(id: string, opts?: ApiOptions): Promise<AnalysisResult> {
  const r = obj(await apiGet(`/api/analyses/${encodeURIComponent(id)}/result`, 'Analysis result', opts), 'result')
  return {
    id: str(r.id, 'result.id'),
    label: typeof r.label === 'string' ? r.label : `Uploaded match ${r.id}`,
    match_state: validateMatchState(r.match_state),
    timeline: validateTacticalTimeline(r.timeline),
    alerts: arr(r.alerts, 'result.alerts').map((a, i) => validateAlert(a, `result.alerts[${i}]`)),
    trace: arr(r.trace, 'result.trace').map((s, i) => validateTraceStep(s, `result.trace[${i}]`)),
    report: r.report == null ? null : validateCoachReport(r.report),
    resolution: resolutionNote(r.resolution),
  }
}
