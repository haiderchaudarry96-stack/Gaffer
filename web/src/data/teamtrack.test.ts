import { describe, expect, it } from 'vitest'
import type { PersistedEvent, TeamTrackClip } from './teamtrack'
import { plainPostureReason, postureSourceNote, postureVisibleAt, replayEventStateAt } from './teamtrack'
import { teamTrackClipIndex, teamTrackClipLocalTime } from '../components/app/teamTrackPlayer'

const event: PersistedEvent = {
  schema_version: '1.1',
  record_id: 'record-1',
  analysis_id: 'teamtrack-demo',
  match_id: 'teamtrack_top_w900_1260',
  event_id: 'evt_003',
  event_type: 'shape_change',
  team: 'home',
  team_name: 'White',
  from_formation: '4-4-2',
  to_formation: '3-4-3',
  candidate_time_s: 990,
  detection_time_s: 1025,
  status: 'confirmed',
  verification_match_time_s: 1020,
  verification_time_utc: '2026-10-19T10:00:00Z',
  posture_status: 'completed',
  posture_result: {
    schema_version: '1.0', posture: 'attacking', source: 'bedrock',
    analysis_time_utc: '2026-10-21T08:00:00Z', model_id: 'test-model', trace_id: 'trace-1',
    evidence_strength: 0.7, explanation: 'Observed shape moved forward.', citations: [],
    limitations: [],
  },
  recommendation_status: 'not_requested',
  recommendation: null,
}

const clips: TeamTrackClip[] = Array.from({ length: 12 }, (_, i) => ({
  id: `${900 + i * 30}-${930 + i * 30}`,
  start_s: 900 + i * 30,
  end_s: 930 + i * 30,
  url: `/clip/${i}`,
}))

describe('recorded TeamTrack replay timing', () => {
  it('maps every 30-second boundary to the next clip at local time zero', () => {
    for (let i = 0; i < 11; i += 1) {
      const boundary = clips[i].end_s
      expect(teamTrackClipIndex(clips, boundary)).toBe(i + 1)
      expect(teamTrackClipLocalTime(clips[i + 1], boundary)).toBe(0)
      expect(teamTrackClipIndex(clips, boundary - 0.25)).toBe(i)
      expect(teamTrackClipLocalTime(clips[i], boundary - 0.25)).toBe(29.75)
    }
    expect(teamTrackClipIndex(clips, 900)).toBe(0)
    expect(teamTrackClipIndex(clips, 1260)).toBe(11)
    expect(teamTrackClipLocalTime(clips[11], 1260)).toBe(30)
  })

  it('shows a candidate at onset and withholds verifier status until its match-clock boundary', () => {
    expect(replayEventStateAt(event, 989.5)).toEqual({ kind: 'upcoming' })
    expect(replayEventStateAt(event, 990)).toEqual({ kind: 'checking' })
    expect(replayEventStateAt(event, 1019.9)).toEqual({ kind: 'checking' })
    expect(replayEventStateAt(event, 1020)).toEqual({ kind: 'decided', status: 'confirmed' })
  })

  it('does not use UTC time or invent a reveal point when match-clock evidence is missing', () => {
    const noBoundary = { ...event, verification_match_time_s: null }
    expect(replayEventStateAt(noBoundary, 2000)).toEqual({ kind: 'checking' })
    expect(postureVisibleAt(noBoundary, 2000)).toBe(false)
  })

  it('withholds posture until the verified match-clock boundary, even if UTC analysis finished', () => {
    expect(postureVisibleAt(event, 1019.99)).toBe(false)
    expect(postureVisibleAt(event, 1020)).toBe(true)
    expect(postureVisibleAt({ ...event, status: 'uncertain' }, 2000)).toBe(false)
  })
})

describe('posture reasons in plain words', () => {
  it('maps every stored code the real demo produced and keeps free text', () => {
    expect(plainPostureReason('weak_quality_low_segment_confidence')).toMatch(/not read clearly enough/)
    expect(plainPostureReason('model_made_unsupported_ball_possession_pressure_or_intent_claim')).toMatch(/does not measure/)
    expect(plainPostureReason('bedrock_client_unavailable')).toMatch(/not switched on/)
    expect(plainPostureReason('missing_or_null_metric:defensive_line_m')).toMatch(/not in the stored OpenCV/)
    expect(plainPostureReason('Ball and possession are not measured.')).toBe('Ball and possession are not measured.')
  })
  it('says where the posture came from', () => {
    const base = { ...event, posture_status: 'completed' as const }
    expect(postureSourceNote({ ...base, posture_result: { ...base.posture_result!, source: 'bedrock' } })).toMatch(/Assessed by Amazon Bedrock/)
    expect(postureSourceNote({ ...base, posture_result: { ...base.posture_result!, source: 'deterministic_fallback' } })).toMatch(/code checks did not support/)
    expect(postureSourceNote({ ...event, posture_status: 'unavailable' })).toMatch(/not available/)
  })
})
