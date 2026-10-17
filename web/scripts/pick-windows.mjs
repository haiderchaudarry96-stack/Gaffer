// Picks the hero replay window and the /app start time from the real MatchState + timeline.
// Run: node scripts/pick-windows.mjs   (reads ../samples/w900_1260). The chosen values are
// hard-coded in src/lib/windows.ts with this script's output in a comment.
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'samples', 'w900_1260')
const m = JSON.parse(readFileSync(resolve(dir, 'match_state_top_w900_1260_4fps.json'), 'utf8'))
const report = JSON.parse(readFileSync(resolve(dir, 'report_w900_1260.json'), 'utf8'))
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.round(s % 60)).padStart(2, '0')}`
const parse = (c) => c.split(':').reduce((a, b) => a * 60 + Number(b), 0)

const count = (f, side) => f.players.filter((p) => p.team === side && p.role === 'outfield').length
const per = m.frames.map((f) => ({ t: f.t, home: count(f, 'home'), away: count(f, 'away') }))

// confident = the first-pass segment formation is not "uncertain" for both teams
const segs = report.inputs.segments.map((s) => {
  const [a, b] = s.seg.split('-').map(parse)
  return { a, b, home: s.White.formation, away: s.Blue.formation }
})
const confident = (t) => {
  const s = segs.find((x) => t >= x.a && t < x.b)
  return s && s.home !== 'uncertain' && s.away !== 'uncertain'
}

// Hero: longest run where every frame has >= 8 outfield players in a team for BOTH teams
// and both shapes are confident.
let best = null
let start = null
for (let i = 0; i <= per.length; i++) {
  const ok = i < per.length && per[i].home >= 8 && per[i].away >= 8 && confident(per[i].t)
  if (ok && start === null) start = i
  if (!ok && start !== null) {
    const run = { a: per[start].t, b: per[i - 1].t, n: i - start }
    if (!best || run.n > best.n) best = run
    start = null
  }
}
const mean = (a, b, side) => {
  const xs = per.filter((p) => p.t >= a && p.t <= b).map((p) => p[side])
  return (xs.reduce((x, y) => x + y, 0) / xs.length).toFixed(2)
}
console.log(`hero: ${clock(best.a)}-${clock(best.b)} (${best.n} frames), mean outfield in a team: White ${mean(best.a, best.b, 'home')}, Blue ${mean(best.a, best.b, 'away')}`)

// /app start: latest t in [16:10, 16:25] from which every frame up to 16:30 has White >= 9 and Blue >= 8.
for (let t = 970; t <= 985; t += 0.5) {
  const win = per.filter((p) => p.t >= t && p.t <= 990)
  if (win.every((p) => p.home >= 9 && p.away >= 8)) {
    console.log(`app start: ${clock(t)} (every frame to 16:30: White >= 9, Blue >= 8 outfield in a team)`)
    break
  }
}
