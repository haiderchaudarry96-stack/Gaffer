import { describe, expect, it } from 'vitest'
import type { FormationTimeline, MatchState } from './types'
import type { PersistedEvent } from './teamtrack'
import { currentReplayEvent, freshSession, initialDeskMode, readingIndex, readingStats, revealTimeline,
  visibleReplayEvents, withDecision } from './liveSession'

/** the real demo event: White 4-4-2 -> 3-4-3 at 16:30, verified at the 18:05 evidence boundary */
const evt003: PersistedEvent = {
  schema_version: '1.1', record_id: 'rec-003', analysis_id: 'teamtrack_demo_w900_1260',
  match_id: 'teamtrack_top_w900_1260', event_id: 'evt_003', event_type: 'shape_change', team: 'home',
  team_name: 'White', from_formation: '4-4-2', to_formation: '3-4-3', candidate_time_s: 990,
  detection_time_s: 1025, status: 'confirmed', verification_match_time_s: 1085,
  verification_time_utc: '2026-10-19T16:46:46Z', posture_status: 'completed', posture_result: null,
  recommendation_status: 'not_requested', recommendation: null,
}

const team = (formation: string) => ({ formation, line_m: 20, depth_m: 30, width_m: 40 })
const tl: FormationTimeline = {
  start_s: 900, end_s: 1260, teamNames: { home: 'White', away: 'Blue' },
  segments: [
    { start_s: 900, end_s: 990, home: team('4-4-2'), away: team('4-2-3-1') },
    { start_s: 990, end_s: 1130, home: team('3-4-3'), away: team('4-4-2') },
    { start_s: 1130, end_s: 1260, home: team('3-4-3'), away: team('4-2-3-1') },
  ],
  events: [
    { id: 'evt_003', team: 'home', t: 990, from: '4-4-2', to: '3-4-3', status: 'confirmed', reason: null },
    { id: 'evt_007', team: 'away', t: 1130, from: '4-4-2', to: '4-2-3-1', status: 'rejected', reason: null },
  ],
}

describe('desk mode', () => {
  it('opens idle; only an explicit link opens the completed analysis', () => {
    expect(initialDeskMode(new URLSearchParams(''))).toBe('idle')
    expect(initialDeskMode(new URLSearchParams('paused=1'))).toBe('idle')
    expect(initialDeskMode(new URLSearchParams('upload=1'))).toBe('idle')
    expect(initialDeskMode(new URLSearchParams('mode=review'))).toBe('review')
    expect(initialDeskMode(new URLSearchParams('t=990&drawer=1'))).toBe('review')
  })
})

describe('reveal by playhead', () => {
  it('cuts the timeline at the playhead: no segment or change after it', () => {
    const at = revealTimeline(tl, 960)
    expect(at.segments).toHaveLength(1)
    expect(at.segments[0].end_s).toBe(960)
    expect(at.events).toEqual([])
    expect(Math.max(...at.segments.map((s) => s.end_s))).toBeLessThanOrEqual(960)
    const later = revealTimeline(tl, 1100)
    expect(later.segments.map((s) => s.end_s)).toEqual([990, 1100])
    expect(later.events.map((e) => e.id)).toEqual(['evt_003'])
    // seeking back hides everything after the playhead again
    expect(revealTimeline(tl, 960)).toEqual(at)
    expect(tl.segments).toHaveLength(3) // the source is not changed
  })

  it('shows the candidate as checking from 16:30 and its verdict only from 18:05', () => {
    const at = (t: number) => ({ shown: visibleReplayEvents([evt003], t), card: currentReplayEvent([evt003], t, '', 'away') })
    expect(at(960).shown).toEqual([])
    expect(at(960).card).toBeNull()
    expect(at(989.5).card).toBeNull()
    expect(at(990).shown[0]).toMatchObject({ pending: true, status: 'candidate' })
    expect(at(990).card?.state).toEqual({ kind: 'checking' })
    expect(at(1084.5).card?.state).toEqual({ kind: 'checking' })
    expect(at(1085).card?.state).toEqual({ kind: 'decided', status: 'confirmed' })
    expect(at(1085).shown[0]).toMatchObject({ pending: false, status: 'confirmed' })
    // back to 16:00: nothing again
    expect(at(960).shown).toEqual([])
    expect(at(960).card).toBeNull()
  })

  it('counts frames and detections read up to the playhead only', () => {
    const frames = [900, 900.25, 900.5, 900.75, 901].map((t, i) => ({ t, players: Array.from({ length: 20 + i }, () => ({})) }))
    const idx = readingIndex({ frames } as unknown as MatchState)
    expect(readingStats(idx, 900, 899)).toEqual({ frames: 0, detections: 0, inView: 0 })
    expect(readingStats(idx, 900, 900.5)).toEqual({ frames: 3, detections: 20 + 21 + 22, inView: 22 })
    expect(readingStats(idx, 900, 1000)).toEqual({ frames: 5, detections: 110, inView: 24 })
    expect(readingStats(readingIndex(null), 900, 1000)).toEqual({ frames: 0, detections: 0, inView: 0 })
  })
})

describe('fresh session', () => {
  it('starts with no decisions and keeps each kind separate', () => {
    const s0 = freshSession()
    expect(s0).toEqual({ alert: {}, advice: {} })
    const s1 = withDecision(s0, 'alert', 'rec-003', 'approved', '  looks right ')
    expect(s1.alert['rec-003']).toEqual({ decision: 'approved', note: 'looks right' })
    expect(s1.advice).toEqual({})
    expect(s0).toEqual({ alert: {}, advice: {} }) // not mutated
    expect(freshSession()).toEqual({ alert: {}, advice: {} }) // a new session forgets them
  })
})
