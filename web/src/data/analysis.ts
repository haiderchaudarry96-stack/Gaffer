/**
 * Upload-for-analysis flow (contract in web/README.md, "Backend API").
 *
 *   uploadVideo(file)                -> POST /api/analyses              (multipart "video")
 *   startAnalysis(id, pitchPoints)   -> POST /api/analyses/{id}/start   (JSON)
 *   getAnalysisStatus(id)            -> GET  /api/analyses/{id}
 *   loadAnalysisResult(id)           -> GET  /api/analyses/{id}/result
 *
 * Without VITE_API_URL every call throws ApiNotConfigured: the UI must say the server is not
 * connected and never show progress or results it did not get from the server.
 */
import { apiGet, apiPost, apiUpload, type ApiOptions } from './api'
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

export interface AnalysisStatus {
  id: string
  status: 'uploaded' | 'queued' | 'running' | 'done' | 'failed'
  stage: AnalysisStage
  /** overall progress 0..1, as reported by the server */
  progress: number
  /** server's estimate of the remaining seconds, if it has one */
  eta_s: number | null
  error: string | null
}

export interface AnalysisResult {
  id: string
  label: string
  match_state: MatchState
  timeline: TacticalTimeline
  alerts: Alert[]
  trace: TraceStep[]
  report: CoachReport | null
}

/** Measured on the laptop CPU for the drone view (CLAUDE.md key numbers: 1.2-1.4 s per s of video). */
export const SECONDS_PER_VIDEO_SECOND = 1.2

export function estimateProcessingSeconds(videoSeconds: number): number {
  return Math.round(videoSeconds * SECONDS_PER_VIDEO_SECOND)
}

function validateStatus(raw: unknown): AnalysisStatus {
  const s = obj(raw, 'analysis')
  str(s.id, 'analysis.id')
  oneOf(s.status, ['uploaded', 'queued', 'running', 'done', 'failed'], 'analysis.status')
  oneOf(s.stage, STAGES, 'analysis.stage')
  const p = num(s.progress, 'analysis.progress')
  if (p < 0 || p > 1) throw new DataError(`analysis.progress: expected 0..1, got ${p}`)
  if (s.eta_s !== null && s.eta_s !== undefined) num(s.eta_s, 'analysis.eta_s')
  return { id: s.id as string, status: s.status as AnalysisStatus['status'], stage: s.stage as AnalysisStage, progress: p, eta_s: (s.eta_s as number | null) ?? null, error: typeof s.error === 'string' ? s.error : null }
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

export async function startAnalysis(id: string, request: PitchPointsRequest, opts?: ApiOptions): Promise<AnalysisStatus> {
  if (request.points.length !== 4) throw new DataError('startAnalysis: exactly 4 pitch points are needed')
  return validateStatus(await apiPost(`/api/analyses/${encodeURIComponent(id)}/start`, request, 'Start analysis', opts))
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
  }
}
