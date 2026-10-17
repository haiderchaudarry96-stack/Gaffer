/**
 * The single data layer of the web app. One function per resource; components never fetch
 * files themselves. Each loader takes an optional reader so tests (and later the FastAPI
 * backend) can supply the bytes.
 */
import { DEFAULT_MATCH, type MatchEntry } from './matches'
import { apiGet, apiPost } from './api'
import { demoFromApi, httpReader, readJson, sampleUrl, type ReadText } from './source'
import { buildTimeline } from './timeline'
import type {
  AgentRunRow,
  Alert,
  CoachReport,
  ExplanationCandidate,
  ExplanationsFile,
  FormationTimeline,
  MatchState,
  TeamModelFile,
  TraceStep,
} from './types'
import {
  arr,
  DataError,
  parseJsonl,
  validateAlert,
  validateCoachReport,
  validateExplanations,
  validateMatchState,
  validateRunRows,
  validateTeamModel,
  validateTraceStep,
} from './validate'

export { DataError } from './validate'
export type { ReadText } from './source'

const path = (match: MatchEntry, file: string) => `${match.id}/${file}`

export async function loadMatchState(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<MatchState> {
  return validateMatchState(await readJson(read, path(match, match.files.matchState)))
}

export async function loadTeamModel(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<TeamModelFile> {
  return validateTeamModel(await readJson(read, path(match, match.files.teamModel)))
}

/**
 * Alerts, last line per alert_id wins (append-only store, AGENT_DESIGN §7). Connected to the
 * backend, the demo alerts come from GET /api/demo/alerts: as shipped, plus this visitor's own
 * approve / reject (never another visitor's).
 */
export async function loadAlerts(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<Alert[]> {
  const name = path(match, match.files.alerts)
  const raw: unknown[] =
    read === httpReader && demoFromApi()
      ? arr(await apiGet('/api/demo/alerts', 'Demo alerts'), 'demo alerts')
      : parseJsonl(await read(name), name)
  const rows = raw.map((r, i) => validateAlert(r, `${name}[${i}]`))
  const latest = new Map<string, Alert>()
  for (const a of rows) latest.set(a.alert_id, a)
  return [...latest.values()].sort((a, b) => a.match_time_s - b.match_time_s)
}

export async function loadTrace(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<TraceStep[]> {
  const name = path(match, match.files.trace)
  return parseJsonl(await read(name), name).map((r, i) => validateTraceStep(r, `${name}[${i}]`))
}

export async function loadExplanations(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<ExplanationCandidate[]> {
  const file: ExplanationsFile = validateExplanations(await readJson(read, path(match, match.files.explanations)))
  return file.candidates.filter((c) => c.set === match.explanationSet)
}

export async function loadReport(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<CoachReport> {
  return validateCoachReport(await readJson(read, path(match, match.files.report)))
}

export async function loadReportMarkdown(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<string> {
  const text = await read(path(match, match.files.reportMarkdown))
  if (!text.trim()) throw new DataError(`${match.files.reportMarkdown} is empty`)
  return text
}

/** Per-candidate rows of the agent run (first pass, camera check, re-analysis, decision). */
export async function loadRunRows(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<AgentRunRow[]> {
  return validateRunRows(await readJson(read, path(match, match.files.runRows)))
}

/** The per-team formation timeline (first pass) with every candidate and the agent's decisions. */
export async function loadTimeline(match: MatchEntry = DEFAULT_MATCH, read: ReadText = httpReader): Promise<FormationTimeline> {
  return buildTimeline(await loadReport(match, read))
}

/**
 * URL of an alert's evidence image. Alerts store the path the agent wrote on the laptop
 * (outputs/...); the sample ships the same image by base name.
 */
export function evidenceImageUrl(alert: Alert, match: MatchEntry = DEFAULT_MATCH): string | null {
  if (!alert.evidence_image) return null
  // a backend analysis returns a URL it serves itself
  if (/^https?:\/\//.test(alert.evidence_image)) return alert.evidence_image
  const base = alert.evidence_image.split('/').at(-1) ?? ''
  return match.assets.includes(base) ? sampleUrl(path(match, base)) : null
}

/** The coach's decision on an alert, sent to the backend (POST /api/alerts/{id}/approve|reject).
 * The demo alert is decided for this visitor only; an uploaded analysis's alert for everyone. */
export async function decideAlert(alertId: string, approve: boolean, note?: string): Promise<Alert> {
  const verb = approve ? 'approve' : 'reject'
  const raw = await apiPost(`/api/alerts/${encodeURIComponent(alertId)}/${verb}`, note ? { note } : {}, approve ? 'Approve' : 'Reject')
  return validateAlert(raw, 'alert')
}

/** Trace steps of one candidate, in order. */
export function traceForEvent(steps: TraceStep[], eventId: string): TraceStep[] {
  return steps.filter((s) => s.kind !== 'match_summary' && s.event_id === eventId)
}

export { DEFAULT_MATCH, MATCHES, getMatch } from './matches'
export type { MatchEntry } from './matches'
export * from './types'
