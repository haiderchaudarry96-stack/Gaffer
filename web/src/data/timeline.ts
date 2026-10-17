/**
 * Builds the per-team formation timeline the app draws.
 *
 * The samples do not include the tactics engine's TacticalTimeline JSON, so this uses the
 * coach report's inputs, which carry the same first-pass segments (formation + line/depth/width
 * per team, mm:ss bounds) and every candidate change (decided by the agent or not checked).
 * Segment confidence and exact second-level bounds are therefore not available here.
 */
import { parseClock, parseClockRange } from './time'
import type { CoachReport, FormationTimeline, SegmentTeam, TeamSide, TimelineEvent } from './types'
import { DataError } from './validate'

function parseChange(change: string, path: string): [string, string] {
  const parts = change.split('->').map((s) => s.trim())
  if (parts.length !== 2 || !parts[0] || !parts[1]) throw new DataError(`${path}: cannot read change "${change}"`)
  return [parts[0], parts[1]]
}

export function buildTimeline(report: CoachReport): FormationTimeline {
  const names = report.inputs.match.teams
  const sideOf = (name: string, path: string): TeamSide => {
    if (name === names.home) return 'home'
    if (name === names.away) return 'away'
    throw new DataError(`${path}: team "${name}" is neither ${names.home} nor ${names.away}`)
  }
  const [start_s, end_s] = parseClockRange(report.inputs.match.footage)

  const segments = report.inputs.segments.map((s) => {
    const [a, b] = parseClockRange(s.seg)
    return {
      start_s: a,
      end_s: b,
      home: s[names.home] as SegmentTeam,
      away: s[names.away] as SegmentTeam,
    }
  })

  const events: TimelineEvent[] = []
  report.inputs.events.forEach((e, i) => {
    const [from, to] = parseChange(e.change, `events[${i}]`)
    events.push({
      id: e.id,
      team: sideOf(e.team, `events[${i}]`),
      t: parseClock(e.onset),
      from,
      to,
      status: e.decision ?? 'candidate',
      reason: e.reason ?? null,
    })
  })
  report.inputs.not_verified.forEach((e, i) => {
    const [from, to] = parseChange(e.change, `not_verified[${i}]`)
    events.push({
      id: e.id,
      team: sideOf(e.team, `not_verified[${i}]`),
      t: parseClock(e.onset),
      from,
      to,
      status: 'candidate',
      reason: null,
    })
  })
  events.sort((a, b) => a.t - b.t || a.id.localeCompare(b.id))

  return { start_s, end_s, teamNames: { home: names.home, away: names.away }, segments, events }
}

/** The first-pass formation of a team at time t, or null outside the timeline. */
export function formationAt(tl: FormationTimeline, side: TeamSide, t: number): string | null {
  const seg = tl.segments.find((s) => t >= s.start_s && t < s.end_s) ?? (t >= tl.end_s ? tl.segments.at(-1) : undefined)
  return seg ? seg[side].formation : null
}

export interface ShownFormation {
  formation: string | null
  /** true when the engine is unsure right now and we show the last confident shape */
  holding: boolean
}

/**
 * The shape to show at time t. Never shows "uncertain": when the current segment is uncertain we
 * show the last confident shape, marked as holding. If there is none earlier in the window, the
 * next candidate's "from" shape is used: the engine only emits a change from its last confident
 * label, so that is the shape it was holding.
 */
export function displayFormation(tl: FormationTimeline, side: TeamSide, t: number): ShownFormation {
  const now = formationAt(tl, side, t)
  if (now && now !== 'uncertain') return { formation: now, holding: false }
  const earlier = tl.segments.filter((s) => s.start_s <= t && s[side].formation !== 'uncertain').at(-1)
  if (earlier) return { formation: earlier[side].formation, holding: true }
  const next = tl.events.find((e) => e.team === side && e.t >= t)
  return { formation: next ? next.from : null, holding: true }
}
