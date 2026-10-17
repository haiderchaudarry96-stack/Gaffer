import type { MatchState, TeamSide } from '../data'

/**
 * Pitch orientation for display.
 *
 * Rule: draw the pitch so the HOME team attacks to the right (+x) in the current period.
 * MatchState stores raw coordinates (DATA_CONTRACT: normalisation is the consumer's job) and
 * says home attacks "left" in the first half here. The tactics engine and the evidence image
 * normalise with a 180-degree turn, x -> L - x AND y -> W - y (src/gaffer/tactics/common.py
 * `normalise`), not a mirror; flipping x alone would mirror the pitch (left/right wings swap).
 * We use the same turn, so the minimap matches the evidence panels (White attacking right).
 * Away then attacks left. Directions swap each period, so this is decided per period.
 */
export interface Orientation {
  /** true when raw coordinates must be turned 180 degrees */
  turn: boolean
  /** which way each team attacks on screen */
  attacks: Record<TeamSide, 'left' | 'right'>
}

export function orientationAt(match: Pick<MatchState, 'teams' | 'periods'>, t: number): Orientation {
  const idx = Math.max(0, match.periods.findIndex((p) => t >= p.start_s && t < p.end_s))
  const homeFirst = match.teams.home.attacking_direction_first_half
  const homeNow = idx % 2 === 0 ? homeFirst : homeFirst === 'left' ? 'right' : 'left'
  return { turn: homeNow === 'left', attacks: { home: 'right', away: 'left' } }
}

export function orient(x: number, y: number, o: Orientation, L: number, W: number): [number, number] {
  return o.turn ? [L - x, W - y] : [x, y]
}
