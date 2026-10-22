import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import RecordedEventCard from './RecordedEventCard'
import type { PersistedEvent } from '../../data/teamtrack'

/** the demo event at 18:05 with ready advice that ANOTHER visitor already answered (shared DB) */
const event: PersistedEvent = {
  schema_version: '1.1', record_id: 'rec-003', analysis_id: 'teamtrack_demo_w900_1260',
  match_id: 'teamtrack_top_w900_1260', event_id: 'evt_003', event_type: 'shape_change', team: 'home',
  team_name: 'White', from_formation: '4-4-2', to_formation: '3-4-3', candidate_time_s: 990,
  detection_time_s: 1025, status: 'confirmed', verification_match_time_s: 1085,
  verification_time_utc: '2026-10-19T16:46:46Z', posture_status: 'completed',
  posture_result: { schema_version: '1.0', posture: 'defensive', source: 'bedrock', analysis_time_utc: 'x',
    model_id: 'm', trace_id: 't', evidence_strength: 0.6, explanation: 'Line dropped.', citations: [], limitations: [] },
  recommendation_status: 'ready',
  recommendation: {
    schema_version: '1.0', recommendation_id: 'reco-1', record_id: 'rec-003', event_id: 'evt_003', status: 'ready',
    context: { coach_side: 'away', objective: 'chase', available_substitute_roles: ['attacker'] },
    context_key: 'c', evidence_key: 'e', request_key: 'r', posture_status_at_creation: 'completed',
    posture_trace_id: 't', condition: 'If the opponent stays deep while you chase a goal.',
    action: { consider_replacing: 'defender', with_available_role: 'attacker' }, rationale: 'r',
    citations: [], posture: 'defensive', basis: 'posture', shape_evidence: null, evidence_strength: 0.6,
    confidence_note: 'n', withheld_reason: null, created_at_utc: 'x',
    coach_response: { decision_id: 'd', recommendation_id: 'reco-1', decision: 'approved',
      decided_at_utc: 'x', note: 'someone else decided this' },
  },
}

const card = (session?: { alert?: { decision: 'approved' | 'rejected'; note: string }; advice?: { decision: 'approved' | 'rejected'; note: string } }) =>
  renderToStaticMarkup(<RecordedEventCard event={event} state={{ kind: 'decided', status: 'confirmed' }}
    coachSide="away" matchTimeS={1085} onRefresh={() => {}} session={session ?? {}} onSessionDecide={() => {}} />)

describe('a fresh Live analysis session', () => {
  it('never shows an earlier (shared) decision as already made', () => {
    const html = card()
    expect(html).not.toContain('someone else decided this')
    expect(html).not.toContain('Coach approved this suggestion')
    expect(html).toContain('Accept suggestion')
    expect(html).toContain('Approve alert')
    expect(html).toContain('Reject alert')
  })

  it("shows this session's own decisions, labelled as session-only", () => {
    const html = card({ alert: { decision: 'approved', note: 'seen it' }, advice: { decision: 'rejected', note: '' } })
    expect(html).toContain('You approved this alert.')
    expect(html).toContain('seen it')
    expect(html).toContain('Coach rejected this suggestion.')
    expect(html).toContain('Saved for this session only')
    expect(html).not.toContain('Approve alert')
  })
})
