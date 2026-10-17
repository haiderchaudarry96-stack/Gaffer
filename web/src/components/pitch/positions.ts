/**
 * Player positions at any time t, interpolated between the 2 fps MatchState frames by track id.
 * Unknown-team players are kept as "unassigned" (drawn as hollow rings, never given a team and
 * never counted for a team: DATA_CONTRACT "ignored by consumers, never guessed").
 */
import type { Frame, MatchState, PlayerTeam } from '../../data'
import { orient, orientationAt } from '../../lib/orientation'

export interface Dot {
  id: number
  team: PlayerTeam
  goalkeeper: boolean
  x: number
  y: number
}

interface Indexed {
  t: number
  byId: Map<number, Frame['players'][number]>
}

export class PositionIndex {
  private frames: Indexed[]
  readonly start: number
  readonly end: number

  constructor(match: MatchState) {
    const { length_m: L, width_m: W } = match.pitch
    // positions are stored already turned for display (home attacks right), see lib/orientation.ts
    this.frames = match.frames.map((f) => {
      const o = orientationAt(match, f.t)
      return {
        t: f.t,
        byId: new Map(
          f.players.map((p) => {
            const [x, y] = orient(p.x, p.y, o, L, W)
            return [p.track_id, { ...p, x, y }]
          }),
        ),
      }
    })
    this.start = match.frames[0]?.t ?? 0
    this.end = match.frames.at(-1)?.t ?? 0
  }

  private indexAt(t: number): number {
    const f = this.frames
    let lo = 0
    let hi = f.length - 1
    if (t <= f[0].t) return 0
    if (t >= f[hi].t) return hi
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (f[mid].t <= t) lo = mid
      else hi = mid
    }
    return lo
  }

  /** Interpolated dots at time t (seconds from kickoff). */
  at(t: number, out: Dot[] = []): Dot[] {
    out.length = 0
    if (!this.frames.length) return out
    const i = this.indexAt(t)
    const a = this.frames[i]
    const b = this.frames[Math.min(i + 1, this.frames.length - 1)]
    const span = b.t - a.t
    const k = span > 0 ? Math.min(1, Math.max(0, (t - a.t) / span)) : 0
    for (const [id, p] of a.byId) {
      const q = b.byId.get(id)
      const x = q ? p.x + (q.x - p.x) * k : p.x
      const y = q ? p.y + (q.y - p.y) * k : p.y
      out.push({ id, team: p.team, goalkeeper: p.role === 'goalkeeper', x, y })
    }
    return out
  }

  /** Number of home / away outfield players in the frame nearest to t. */
  countsAt(t: number): { home: number; away: number } {
    const f = this.frames[this.indexAt(t)]
    let home = 0
    let away = 0
    for (const p of f?.byId.values() ?? []) {
      if (p.role !== 'outfield') continue
      if (p.team === 'home') home++
      else if (p.team === 'away') away++
    }
    return { home, away }
  }
}
