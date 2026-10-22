import { apiGet, apiPost } from './api'

export interface TeamTrackClip {
  id: string
  start_s: number
  end_s: number
  url: string
}

export interface TeamTrackReplay {
  match_id: string
  start_s: number
  end_s: number
  label: string
  clips: TeamTrackClip[]
}

export interface PostureCitation {
  metric_path: string
  value: number
  unit: string
  match_time_window_s: [number, number]
}

export interface PostureResult {
  schema_version: string
  posture: 'attacking' | 'defensive' | 'hybrid' | 'unclear'
  source: 'bedrock' | 'deterministic_fallback'
  analysis_time_utc: string
  model_id: string | null
  trace_id: string
  evidence_strength: number
  explanation: string
  citations: PostureCitation[]
  limitations: string[]
}

export interface CoachContext {
  coach_side: 'home' | 'away' | null
  objective: 'chase' | 'protect' | 'balanced' | null
  available_substitute_roles: ('attacker' | 'midfielder' | 'defender')[]
}

export interface RecommendationDecision {
  decision_id: string
  recommendation_id: string
  decision: 'approved' | 'rejected'
  decided_at_utc: string
  note: string | null
}

export interface RoleRecommendation {
  schema_version: string
  recommendation_id: string
  record_id: string
  event_id: string
  status: 'ready' | 'withheld'
  context: CoachContext
  context_key: string
  evidence_key: string
  request_key: string
  posture_status_at_creation: PersistedEvent['posture_status']
  posture_trace_id: string | null
  condition: string
  action: { consider_replacing: string; with_available_role: string } | null
  rationale: string
  citations: PostureCitation[]
  posture: 'attacking' | 'defensive' | 'hybrid' | null
  /** what the option rests on: a supported posture read, or the verified shape change alone */
  basis: 'posture' | 'shape_matchup' | null
  shape_evidence: { team: string; from: string; to: string; event_time_s: number } | null
  evidence_strength: number
  confidence_note: string
  withheld_reason: string | null
  created_at_utc: string
  coach_response?: RecommendationDecision
}

export interface PersistedEvent {
  schema_version: string
  record_id: string
  analysis_id: string
  match_id: string
  event_id: string
  event_type: string
  team: 'home' | 'away'
  team_name: string
  from_formation: string | null
  to_formation: string | null
  candidate_time_s: number
  detection_time_s: number | null
  status: 'candidate' | 'confirmed' | 'rejected' | 'uncertain'
  verification_match_time_s: number | null
  verification_time_utc: string | null
  posture_status: 'not_requested' | 'pending' | 'completed' | 'unavailable' | 'failed'
  posture_result: PostureResult | null
  recommendation_status: 'not_requested' | 'pending' | 'ready' | 'withheld'
  recommendation: RoleRecommendation | null
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} is invalid`)
  return value as Record<string, unknown>
}

function number(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${label} is invalid`)
  return value
}

function postureResult(value: unknown, label: string): PostureResult | null {
  if (value == null) return null
  const result = object(value, label)
  const postures = ['attacking', 'defensive', 'hybrid', 'unclear']
  const sources = ['bedrock', 'deterministic_fallback']
  if (!postures.includes(String(result.posture)) || !sources.includes(String(result.source))
      || typeof result.explanation !== 'string' || typeof result.trace_id !== 'string'
      || typeof result.analysis_time_utc !== 'string' || !Array.isArray(result.citations)
      || !Array.isArray(result.limitations)) {
    throw new Error(`${label} is invalid`)
  }
  const citations = result.citations.map((item, index) => {
    const citation = object(item, `${label}.citations[${index}]`)
    if (typeof citation.metric_path !== 'string' || typeof citation.unit !== 'string'
        || !Array.isArray(citation.match_time_window_s)
        || citation.match_time_window_s.length !== 2) {
      throw new Error(`${label}.citations[${index}] is invalid`)
    }
    return {
      metric_path: citation.metric_path,
      value: number(citation.value, `${label}.citations[${index}].value`),
      unit: citation.unit,
      match_time_window_s: [
        number(citation.match_time_window_s[0], `${label}.citations[${index}].window[0]`),
        number(citation.match_time_window_s[1], `${label}.citations[${index}].window[1]`),
      ] as [number, number],
    }
  })
  return {
    schema_version: typeof result.schema_version === 'string' ? result.schema_version : '1.0',
    posture: result.posture as PostureResult['posture'],
    source: result.source as PostureResult['source'],
    analysis_time_utc: result.analysis_time_utc,
    model_id: typeof result.model_id === 'string' ? result.model_id : null,
    trace_id: result.trace_id,
    evidence_strength: number(result.evidence_strength, `${label}.evidence_strength`),
    explanation: result.explanation,
    citations,
    limitations: result.limitations.filter((item): item is string => typeof item === 'string'),
  }
}

function recommendationResult(value: unknown, label: string): RoleRecommendation | null {
  if (value == null) return null
  const result = object(value, label)
  if (!['ready', 'withheld'].includes(String(result.status))
      || typeof result.recommendation_id !== 'string' || typeof result.record_id !== 'string'
      || typeof result.event_id !== 'string' || typeof result.condition !== 'string'
      || typeof result.rationale !== 'string' || !Array.isArray(result.citations)
      || typeof result.context_key !== 'string' || typeof result.evidence_key !== 'string'
      || typeof result.request_key !== 'string' || typeof result.created_at_utc !== 'string') {
    throw new Error(`${label} is invalid`)
  }
  const context = object(result.context, `${label}.context`)
  const side = context.coach_side
  const objective = context.objective
  const roles = context.available_substitute_roles
  if ((side !== null && side !== 'home' && side !== 'away')
      || (objective !== null && !['chase', 'protect', 'balanced'].includes(String(objective)))
      || !Array.isArray(roles)
      || roles.some((role) => !['attacker', 'midfielder', 'defender'].includes(String(role)))) {
    throw new Error(`${label}.context is invalid`)
  }
  let action: RoleRecommendation['action'] = null
  if (result.action != null) {
    const parsed = object(result.action, `${label}.action`)
    if (typeof parsed.consider_replacing !== 'string'
        || typeof parsed.with_available_role !== 'string') throw new Error(`${label}.action is invalid`)
    action = { consider_replacing: parsed.consider_replacing,
      with_available_role: parsed.with_available_role }
  }
  const citations = result.citations.map((item, index) => {
    const citation = object(item, `${label}.citations[${index}]`)
    if (typeof citation.metric_path !== 'string' || typeof citation.unit !== 'string'
        || !Array.isArray(citation.match_time_window_s) || citation.match_time_window_s.length !== 2) {
      throw new Error(`${label}.citations[${index}] is invalid`)
    }
    return { metric_path: citation.metric_path, unit: citation.unit,
      value: number(citation.value, `${label}.citations[${index}].value`),
      match_time_window_s: [number(citation.match_time_window_s[0], `${label}.citations[${index}].window[0]`),
        number(citation.match_time_window_s[1], `${label}.citations[${index}].window[1]`)] as [number, number] }
  })
  let coachResponse: RecommendationDecision | undefined
  if (result.coach_response != null) {
    const response = object(result.coach_response, `${label}.coach_response`)
    if (typeof response.decision_id !== 'string' || typeof response.recommendation_id !== 'string'
        || !['approved', 'rejected'].includes(String(response.decision))
        || typeof response.decided_at_utc !== 'string') throw new Error(`${label}.coach_response is invalid`)
    coachResponse = { decision_id: response.decision_id, recommendation_id: response.recommendation_id,
      decision: response.decision as RecommendationDecision['decision'],
      decided_at_utc: response.decided_at_utc,
      note: typeof response.note === 'string' ? response.note : null }
  }
  return {
    schema_version: typeof result.schema_version === 'string' ? result.schema_version : '1.0',
    recommendation_id: result.recommendation_id, record_id: result.record_id, event_id: result.event_id,
    status: result.status as RoleRecommendation['status'],
    context: { coach_side: side as CoachContext['coach_side'],
      objective: objective as CoachContext['objective'],
      available_substitute_roles: roles as CoachContext['available_substitute_roles'] },
    context_key: result.context_key, condition: result.condition, action, rationale: result.rationale,
    evidence_key: result.evidence_key, request_key: result.request_key,
    posture_status_at_creation: String(result.posture_status_at_creation) as PersistedEvent['posture_status'],
    posture_trace_id: typeof result.posture_trace_id === 'string' ? result.posture_trace_id : null,
    citations, posture: ['attacking', 'defensive', 'hybrid'].includes(String(result.posture))
      ? result.posture as RoleRecommendation['posture'] : null,
    basis: result.basis === 'posture' || result.basis === 'shape_matchup' ? result.basis : null,
    shape_evidence: shapeEvidence(result.shape_evidence),
    evidence_strength: number(result.evidence_strength, `${label}.evidence_strength`),
    confidence_note: typeof result.confidence_note === 'string' ? result.confidence_note : '',
    withheld_reason: typeof result.withheld_reason === 'string' ? result.withheld_reason : null,
    created_at_utc: result.created_at_utc, ...(coachResponse ? { coach_response: coachResponse } : {}),
  }
}

function shapeEvidence(value: unknown): RoleRecommendation['shape_evidence'] {
  if (!value || typeof value !== 'object') return null
  const v = value as Record<string, unknown>
  if (typeof v.from !== 'string' || typeof v.to !== 'string' || typeof v.event_time_s !== 'number') return null
  return { team: typeof v.team === 'string' ? v.team : '', from: v.from, to: v.to, event_time_s: v.event_time_s }
}

export async function loadTeamTrackReplay(): Promise<TeamTrackReplay> {
  const raw = object(await apiGet('/api/replay/teamtrack', 'TeamTrack replay'), 'replay')
  if (typeof raw.match_id !== 'string' || typeof raw.label !== 'string' || !Array.isArray(raw.clips)) {
    throw new Error('The TeamTrack replay manifest is incomplete')
  }
  const clips = raw.clips.map((value, i) => {
    const clip = object(value, `clips[${i}]`)
    if (typeof clip.id !== 'string' || typeof clip.url !== 'string') throw new Error(`clips[${i}] is invalid`)
    return {
      id: clip.id,
      url: clip.url,
      start_s: number(clip.start_s, `clips[${i}].start_s`),
      end_s: number(clip.end_s, `clips[${i}].end_s`),
    }
  })
  return {
    match_id: raw.match_id,
    label: raw.label,
    start_s: number(raw.start_s, 'replay.start_s'),
    end_s: number(raw.end_s, 'replay.end_s'),
    clips,
  }
}

export async function loadPersistedEvents(matchId: string): Promise<PersistedEvent[]> {
  const query = new URLSearchParams({ match_id: matchId, limit: '100' })
  const raw = object(await apiGet(`/api/events?${query.toString()}`, 'OpenCV event history'), 'events')
  if (!Array.isArray(raw.events)) throw new Error('The event history is invalid')
  return raw.events.map((value, i) => {
    const event = object(value, `events[${i}]`)
    if (event.team !== 'home' && event.team !== 'away') throw new Error(`events[${i}].team is invalid`)
    if (!['candidate', 'confirmed', 'rejected', 'uncertain'].includes(String(event.status))) {
      throw new Error(`events[${i}].status is invalid`)
    }
    const optionalNumber = (field: string) =>
      event[field] == null ? null : number(event[field], `events[${i}].${field}`)
    return {
      schema_version: typeof event.schema_version === 'string' ? event.schema_version : '1.0',
      record_id: String(event.record_id ?? ''),
      analysis_id: String(event.analysis_id ?? ''),
      match_id: String(event.match_id ?? ''),
      event_id: String(event.event_id ?? ''),
      event_type: String(event.event_type ?? ''),
      team: event.team,
      team_name: String(event.team_name ?? event.team),
      from_formation: typeof event.from_formation === 'string' ? event.from_formation : null,
      to_formation: typeof event.to_formation === 'string' ? event.to_formation : null,
      candidate_time_s: number(event.candidate_time_s, `events[${i}].candidate_time_s`),
      detection_time_s: optionalNumber('detection_time_s'),
      status: event.status as PersistedEvent['status'],
      verification_match_time_s: optionalNumber('verification_match_time_s'),
      verification_time_utc: typeof event.verification_time_utc === 'string' ? event.verification_time_utc : null,
      posture_status: ['not_requested', 'pending', 'completed', 'unavailable', 'failed'].includes(
        String(event.posture_status)) ? event.posture_status as PersistedEvent['posture_status']
        : 'not_requested',
      posture_result: postureResult(event.posture_result, `events[${i}].posture_result`),
      recommendation_status: ['not_requested', 'pending', 'ready', 'withheld'].includes(
        String(event.recommendation_status)) ? event.recommendation_status as PersistedEvent['recommendation_status']
        : 'not_requested',
      recommendation: recommendationResult(event.recommendation, `events[${i}].recommendation`),
    }
  })
}

export async function requestRoleRecommendation(recordId: string,
                                                context: CoachContext): Promise<void> {
  await apiPost(`/api/events/${encodeURIComponent(recordId)}/recommendation`, context,
    'Tactical advice')
}

export async function decideRoleRecommendation(recordId: string, recommendationId: string,
                                               decision: 'approved' | 'rejected',
                                               note?: string): Promise<void> {
  await apiPost(`/api/events/${encodeURIComponent(recordId)}/recommendation/`
    + `${encodeURIComponent(recommendationId)}/decision`, { decision, note: note ?? null },
    'Advice response')
}

export type ReplayEventState =
  | { kind: 'upcoming' }
  | { kind: 'checking' }
  | { kind: 'decided'; status: Exclude<PersistedEvent['status'], 'candidate'> }

/** Do not use the UTC verifier-completion timestamp as a playback/match time. */
export function replayEventStateAt(event: PersistedEvent, matchTimeS: number): ReplayEventState {
  if (matchTimeS < event.candidate_time_s) return { kind: 'upcoming' }
  if (event.status === 'candidate' || event.verification_match_time_s === null
      || matchTimeS < event.verification_match_time_s) return { kind: 'checking' }
  return { kind: 'decided', status: event.status }
}

/** Bedrock posture may only be revealed after the stored verifier boundary on the match clock. */
export function postureVisibleAt(event: PersistedEvent, matchTimeS: number): boolean {
  return event.status === 'confirmed'
    && event.verification_match_time_s !== null
    && matchTimeS >= event.verification_match_time_s
}

/** Plain words for the posture checker's reason codes (the stored code stays in the record). */
const POSTURE_REASONS: [RegExp, string][] = [
  [/^weak_quality_low_segment_confidence$/, 'The shape just before or after the change was not read clearly enough to compare.'],
  [/^weak_quality_high_uncertainty$/, 'Too many readings around the change were unsettled.'],
  [/^weak_quality_low_(coverage_before|coverage_after|footage_frac|visual_reanalysis_coverage)$/, 'Too few players were tracked around the change.'],
  [/^weak_quality_low_player_visibility$/, 'Too few players were visible around the change.'],
  [/^(model|reassessment)_made_unsupported_ball_possession_pressure_or_intent_claim$/, 'The model’s answer talked about the ball, possession, pressing or intent, which this camera does not measure, so it was not used.'],
  [/^malformed_result/, 'The model’s answer was not in the required format.'],
  [/^(missing_or_null_metric|citation_mismatch|duplicate_citation)/, 'The model cited a number that is not in the stored OpenCV measurements.'],
  [/^directional_label_needs_two_paired_metric_types$/, 'A label needs two measurements that agree, before and after the change.'],
  [/^unsupported_(attacking|defensive|hybrid)_label$/, 'The measurements do not support that label.'],
  [/^bedrock_client_unavailable$/, 'Amazon Bedrock is not switched on for this server.'],
  [/^(missing_aws_credentials|bedrock_|model_returned_no_single_text_answer|reassessment_returned)/, 'Amazon Bedrock could not give an answer this time.'],
  [/^(global_api_bedrock_budget_exhausted|posture_budget_unavailable)/, 'Today’s Bedrock budget for this demo is used up.'],
  [/^model_price_unavailable$/, 'The model’s price is not configured, so Bedrock was not called.'],
  [/^visual_reanalysis/, 'A second OpenCV look at the video was not available.'],
]

export function plainPostureReason(reason: string): string {
  for (const [pattern, text] of POSTURE_REASONS) if (pattern.test(reason)) return text
  return reason
}

/** Where the shown posture came from, in one sentence. */
export function postureSourceNote(event: PersistedEvent): string {
  if (event.posture_status === 'unavailable') return 'Amazon Bedrock was not available, so no label was attempted.'
  if (event.posture_status === 'failed') return 'Amazon Bedrock’s answer did not pass the evidence checks, so it was not used.'
  if (event.posture_result?.source === 'bedrock') return 'Assessed by Amazon Bedrock and checked against the stored OpenCV measurements.'
  return 'Amazon Bedrock answered, but the code checks did not support a label, so Gaffer keeps it unclear.'
}
