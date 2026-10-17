/**
 * Types for the data the web app reads.
 *
 * MatchState and Alert follow docs/DATA_CONTRACT.md (contract_version "1.0").
 * The trace, explanation, report and run-row types follow what the Phase 3 code writes
 * (docs/AGENT_DESIGN.md §7, §5) and are typed only as far as the app uses them.
 */

export type TeamSide = 'home' | 'away'
export type PlayerTeam = TeamSide | 'referee' | 'unknown'

// ---------- MatchState (DATA_CONTRACT.md) ----------

export interface Player {
  track_id: number
  team: PlayerTeam
  role: 'outfield' | 'goalkeeper'
  /** metres, 0..length along the pitch */
  x: number
  /** metres, 0..width across the pitch */
  y: number
  confidence: number
  interpolated: boolean
}

export interface Ball {
  x: number
  y: number
  visible: boolean
}

export interface FrameQuality {
  players_detected: number
  homography_ok: boolean
  reprojection_error_m: number | null
  camera_cut: boolean
}

export interface Frame {
  /** seconds from kickoff */
  t: number
  players: Player[]
  ball: Ball | null
  possession: 'home' | 'away' | 'contested' | 'dead' | null
  quality?: FrameQuality | null
}

export interface TeamInfo {
  name: string
  colour: string
  attacking_direction_first_half: 'left' | 'right'
}

export interface MatchState {
  contract_version: '1.0'
  match_id: string
  source: 'synthetic' | 'video' | 'annotation'
  /** sampling rate of `frames`, not of the source video */
  fps: number
  duration_s: number
  pitch: { length_m: number; width_m: number }
  source_video: { uri: string; native_fps: number; width: number; height: number } | null
  teams: Record<TeamSide, TeamInfo>
  periods: { name: string; start_s: number; end_s: number }[]
  frames: Frame[]
  meta: { generator: string; opencv_version: string; created_utc: string; notes: string }
}

/** `<match>.teams.json`, written by the perception pipeline (not part of the contract). */
export interface TeamModelFile {
  view: string
  directions: Record<TeamSide, 'left' | 'right'>
}

// ---------- Alerts (DATA_CONTRACT.md) ----------

export type AlertStatus = 'pending' | 'approved' | 'rejected'

export interface Alert {
  alert_id: string
  event_id: string
  created_utc: string
  match_time_s: number
  title: string
  /** "Verified: <rules reason>\nExplanation (agent|template): <text>" (AGENT_DESIGN §2 step 7) */
  explanation: string
  suggestion: string
  evidence_image: string | null
  status: AlertStatus
  decided_utc: string | null
  coach_note: string | null
}

// ---------- Agent trace (AGENT_DESIGN.md §7) ----------

export interface TraceLlmUsage {
  model_id: string
  in: number
  out: number
  latency_ms: number
}

interface TraceBase {
  ts: string
  run_id: string
  match_id: string
  trace_id?: string
  event_id?: string
  arm?: string
  backend?: string
  step?: number
}

export interface TraceCard extends TraceBase {
  kind: 'card'
  actor: string
  ref: string
  card: string
}

export interface TraceToolCall extends TraceBase {
  kind: 'tool_call'
  actor: string
  tool: string
  args: Record<string, unknown>
  ref: string
  prev_ref: string | null
  result_summary: Record<string, unknown>
  duration_ms: number
  error: unknown
  llm: TraceLlmUsage | null
}

export interface TraceDecision extends TraceBase {
  kind: 'decision'
  decision: 'confirmed' | 'rejected' | 'uncertain'
  decided_by: string
  reason: string
  explanation: string | null
  citations: { ref: string; t: number | null }[]
  verdict: RulesVerdict
  alert_id: string | null
  llm_calls: number
  cost_usd: number
}

export interface TraceMatchSummary extends TraceBase {
  kind: 'match_summary'
  llm_calls: number
  cost_usd: number
}

/** Other kinds (guard_block, fallback) are kept but not typed further. */
export interface TraceOther extends TraceBase {
  kind: 'guard_block' | 'fallback'
  [key: string]: unknown
}

export type TraceStep = TraceCard | TraceToolCall | TraceDecision | TraceMatchSummary | TraceOther

export interface RulesVerdict {
  verdict: string
  failed: string[]
  missing: string[]
  next_step?: string
}

// ---------- Explanations (scripts/explain_real.py output) ----------

export interface ExplanationCandidate {
  set: string
  event_id: string
  team: string
  change: string
  clock: string
  decision: 'confirmed' | 'rejected' | 'uncertain'
  cause: string
  reason_now: string
  /** the checked explanation shown to the coach */
  after: string
  /** "agent" (Nova's words, passed the check) or "template" */
  source: 'agent' | 'template'
  facts: {
    rule: string
    results: Record<string, Record<string, unknown>>
  }
}

export interface ExplanationsFile {
  summary: { candidates: number; decisions_identical_to_step6: boolean; fingerprint: string }
  llm: { calls: number; cost_usd: number }
  candidates: ExplanationCandidate[]
}

// ---------- Agent run rows (report_llm.json) ----------

export interface FirstPass {
  verdict: string
  reason: string
  coverage_before: number
  coverage_after: number
  after_share_new: number
  confident_after: number
}

export interface AgentRunRow {
  set: string
  event_id: string
  team: TeamSide
  t: number
  clock: string
  from: string
  to: string
  first_pass: FirstPass
  decision: 'confirmed' | 'rejected' | 'uncertain'
  reason: string
  decided_by: string
  tool_calls: string[]
  opencv_changed_decision: boolean
  first_pass_decision: string
  llm_calls: number
  cost_usd: number
  trace_id: string
}

// ---------- Coach report (agent/report.py output) ----------

export interface SegmentTeam {
  formation: string
  line_m: number | null
  depth_m: number | null
  width_m: number | null
}

export interface ReportSegment {
  /** "mm:ss-mm:ss" */
  seg: string
  [teamName: string]: SegmentTeam | string
}

export interface ReportWindow {
  window: string
  formation: string
  line_m: number | null
  depth_m: number | null
  width_m: number | null
  own_box_pct: number | null
}

export interface ReportEvent {
  id: string
  team: string
  change: string
  onset: string
  lines?: string
  decision?: 'confirmed' | 'rejected' | 'uncertain'
  reason?: string
  explanation?: string
  new_shape_pct?: number
  clear_readings_after?: number
  fps?: number
  /** typical windows drawn in the evidence panels (confirmed events) */
  before?: ReportWindow
  after?: ReportWindow
  alert?: { id: string; status: string; evidence_image: string }
}

export interface CoachReport {
  inputs: {
    match: {
      id: string
      teams: Record<TeamSide, string>
      footage: string
      view: string
      unavailable: string[]
      note: string
    }
    segments: ReportSegment[]
    events: ReportEvent[]
    not_verified: ReportEvent[]
  }
  report: {
    formation_story: string[]
    changes: { event: string; what_changed: string; may_have_fixed: string }[]
    not_alerted: string[]
    recommendations: string[]
    limits: string[]
  }
  /** "code template" or the model */
  source: string
  attempts: { problems: string[] }[]
}

// ---------- Derived view model (built in the data layer, see timeline.ts) ----------

export type EventStatus = 'confirmed' | 'rejected' | 'uncertain' | 'candidate'

export interface TimelineEvent {
  id: string
  team: TeamSide
  t: number
  from: string
  to: string
  /** "candidate" = first-pass reading the agent did not check */
  status: EventStatus
  reason: string | null
}

export interface TimelineSegment {
  start_s: number
  end_s: number
  home: SegmentTeam
  away: SegmentTeam
}

export interface FormationTimeline {
  start_s: number
  end_s: number
  teamNames: Record<TeamSide, string>
  segments: TimelineSegment[]
  events: TimelineEvent[]
}
