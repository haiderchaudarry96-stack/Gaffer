/**
 * The live-style session on the analyst desk: what may be shown at a match time, and the
 * coach's decisions made in this session only.
 *
 * Rule: nothing after the playhead. Dots come from the MatchState frame at the playhead (the
 * pitch already draws that), shapes and changes are cut at the playhead, a candidate is
 * "checking" from its onset and shows its verdict only from its stored verification boundary.
 */
import type { FormationTimeline, MatchState, TimelineEvent } from './types'
import { replayEventStateAt, type PersistedEvent, type ReplayEventState } from './teamtrack'

/** Where /app opens: idle (nothing started) unless a link asks for the finished review. */
export type DeskMode = 'idle' | 'review'

export function initialDeskMode(params: URLSearchParams): DeskMode {
  if (params.get('mode') === 'review') return 'review'
  // older deep links into the finished view (screenshots, docs) keep working
  if (params.has('live') || params.has('drawer') || params.has('t')) return 'review'
  return 'idle'
}

/** The timeline as known at match time t: segments cut at t, changes up to t, nothing later. */
export function revealTimeline(tl: FormationTimeline, t: number): FormationTimeline {
  return {
    ...tl,
    segments: tl.segments
      .filter((s) => s.start_s < t)
      .map((s) => (s.end_s > t ? { ...s, end_s: t } : s)),
    events: tl.events.filter((e) => e.t <= t),
  }
}

export interface ReadingStats {
  /** MatchState frames from the session start up to the playhead */
  frames: number
  /** player detections in those frames */
  detections: number
  /** players in the frame at the playhead */
  inView: number
}

/** Frame times and cumulative player counts, for `readingStats` (built once per match). */
export interface ReadingIndex {
  times: number[]
  cumulative: number[]
  counts: number[]
}

export function readingIndex(match: MatchState | null): ReadingIndex {
  const times: number[] = []
  const counts: number[] = []
  const cumulative: number[] = []
  let total = 0
  for (const f of match?.frames ?? []) {
    times.push(f.t)
    counts.push(f.players.length)
    total += f.players.length
    cumulative.push(total)
  }
  return { times, cumulative, counts }
}

/** number of frames with time <= t (binary search) */
function upTo(times: number[], t: number): number {
  let lo = 0
  let hi = times.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= t) lo = mid + 1
    else hi = mid
  }
  return lo
}

export function readingStats(idx: ReadingIndex, from: number, t: number): ReadingStats {
  const end = upTo(idx.times, t)
  const start = upTo(idx.times, from - 1e-6)
  if (end <= start) return { frames: 0, detections: 0, inView: 0 }
  const before = start > 0 ? idx.cumulative[start - 1] : 0
  return { frames: end - start, detections: idx.cumulative[end - 1] - before, inView: idx.counts[end - 1] }
}

export interface ShownReplayEvent {
  event: TimelineEvent
  status: TimelineEvent['status']
  pending: boolean
}

/** Persisted OpenCV events as the timeline shows them at t (none before their onset). */
export function visibleReplayEvents(records: PersistedEvent[], t: number): ShownReplayEvent[] {
  return records.flatMap((record) => {
    const state = replayEventStateAt(record, t)
    if (state.kind === 'upcoming') return []
    const status = state.kind === 'decided' ? state.status : 'candidate'
    const event: TimelineEvent = {
      id: record.event_id, team: record.team, t: record.candidate_time_s,
      from: record.from_formation ?? 'unknown', to: record.to_formation ?? 'unknown', status, reason: null,
    }
    return [{ event, status, pending: state.kind === 'checking' }]
  })
}

/** The event the side card shows at t: the selected one if it has started, else the latest. */
export function currentReplayEvent(records: PersistedEvent[], t: number, selected: string,
                                   coachSide: string): { record: PersistedEvent; state: ReplayEventState } | null {
  const started = records.filter((r) => r.candidate_time_s <= t)
  const latest = started.at(-1)?.candidate_time_s
  const group = started.filter((r) => r.candidate_time_s === latest)
  const record = started.find((r) => r.event_id === selected)
    ?? group.find((r) => r.team === coachSide) ?? group.at(-1)
  return record ? { record, state: replayEventStateAt(record, t) } : null
}

export interface SessionDecision {
  decision: 'approved' | 'rejected'
  note: string
}

/**
 * Coach decisions made in this Live analysis session (the recorded demo is shared by every
 * visitor, so its stores are never shown as "already decided" and a new session starts empty).
 * Keys: the event record id for the alert, the recommendation id for role advice.
 */
export interface SessionDecisions {
  alert: Record<string, SessionDecision>
  advice: Record<string, SessionDecision>
}

export function freshSession(): SessionDecisions {
  return { alert: {}, advice: {} }
}

export function withDecision(s: SessionDecisions, kind: keyof SessionDecisions, key: string,
                             decision: SessionDecision['decision'], note: string): SessionDecisions {
  return { ...s, [kind]: { ...s[kind], [key]: { decision, note: note.trim() } } }
}
