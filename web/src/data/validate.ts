/**
 * Small runtime checks for the files the app reads. Invalid data is rejected loudly
 * (DATA_CONTRACT.md: "Invalid files are rejected loudly"), with the JSON path in the message.
 */
import type {
  AgentRunRow,
  Alert,
  CoachReport,
  ExplanationsFile,
  MatchState,
  TeamModelFile,
  TraceStep,
} from './types'

export class DataError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DataError'
  }
}

type Obj = Record<string, unknown>

function fail(path: string, want: string, got: unknown): never {
  const shown = got === undefined ? 'missing' : JSON.stringify(got)?.slice(0, 60)
  throw new DataError(`${path}: expected ${want}, got ${shown}`)
}

export function obj(v: unknown, path: string): Obj {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) fail(path, 'object', v)
  return v as Obj
}
export function arr(v: unknown, path: string): unknown[] {
  if (!Array.isArray(v)) fail(path, 'array', v)
  return v
}
export function num(v: unknown, path: string): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) fail(path, 'number', v)
  return v
}
export function str(v: unknown, path: string): string {
  if (typeof v !== 'string') fail(path, 'string', v)
  return v
}
export function bool(v: unknown, path: string): boolean {
  if (typeof v !== 'boolean') fail(path, 'boolean', v)
  return v
}
export function oneOf<T extends string>(v: unknown, allowed: readonly T[], path: string): T {
  if (typeof v !== 'string' || !(allowed as readonly string[]).includes(v)) fail(path, allowed.join(' | '), v)
  return v as T
}
function nullOr<T>(v: unknown, path: string, check: (v: unknown, path: string) => T): T | null {
  return v === null ? null : check(v, path)
}
function strArr(v: unknown, path: string): string[] {
  return arr(v, path).map((x, i) => str(x, `${path}[${i}]`))
}

const TEAMS = ['home', 'away'] as const
const PLAYER_TEAMS = ['home', 'away', 'referee', 'unknown'] as const
const DECISIONS = ['confirmed', 'rejected', 'uncertain'] as const

// ---------- MatchState ----------

export function validateMatchState(raw: unknown): MatchState {
  const m = obj(raw, 'match_state')
  if (m.contract_version !== '1.0') {
    throw new DataError(`match_state.contract_version: expected "1.0", got ${JSON.stringify(m.contract_version)}`)
  }
  str(m.match_id, 'match_state.match_id')
  oneOf(m.source, ['synthetic', 'video', 'annotation'], 'match_state.source')
  num(m.fps, 'match_state.fps')
  num(m.duration_s, 'match_state.duration_s')
  const pitch = obj(m.pitch, 'match_state.pitch')
  num(pitch.length_m, 'match_state.pitch.length_m')
  num(pitch.width_m, 'match_state.pitch.width_m')
  nullOr(m.source_video, 'match_state.source_video', (v, p) => {
    const sv = obj(v, p)
    str(sv.uri, `${p}.uri`)
    num(sv.native_fps, `${p}.native_fps`)
    num(sv.width, `${p}.width`)
    num(sv.height, `${p}.height`)
    return sv
  })
  const teams = obj(m.teams, 'match_state.teams')
  for (const side of TEAMS) {
    const t = obj(teams[side], `match_state.teams.${side}`)
    str(t.name, `match_state.teams.${side}.name`)
    str(t.colour, `match_state.teams.${side}.colour`)
    oneOf(t.attacking_direction_first_half, ['left', 'right'], `match_state.teams.${side}.attacking_direction_first_half`)
  }
  arr(m.periods, 'match_state.periods').forEach((p, i) => {
    const po = obj(p, `match_state.periods[${i}]`)
    str(po.name, `match_state.periods[${i}].name`)
    num(po.start_s, `match_state.periods[${i}].start_s`)
    num(po.end_s, `match_state.periods[${i}].end_s`)
  })
  const frames = arr(m.frames, 'match_state.frames')
  let lastT = -Infinity
  frames.forEach((f, i) => {
    const p = `match_state.frames[${i}]`
    const fo = obj(f, p)
    const t = num(fo.t, `${p}.t`)
    if (t <= lastT) throw new DataError(`${p}.t: frames must be sorted by t without duplicates (${t} after ${lastT})`)
    lastT = t
    arr(fo.players, `${p}.players`).forEach((pl, j) => {
      const pp = `${p}.players[${j}]`
      const po = obj(pl, pp)
      num(po.track_id, `${pp}.track_id`)
      oneOf(po.team, PLAYER_TEAMS, `${pp}.team`)
      oneOf(po.role, ['outfield', 'goalkeeper'], `${pp}.role`)
      num(po.x, `${pp}.x`)
      num(po.y, `${pp}.y`)
      num(po.confidence, `${pp}.confidence`)
      bool(po.interpolated, `${pp}.interpolated`)
    })
    nullOr(fo.ball ?? null, `${p}.ball`, (v, bp) => {
      const b = obj(v, bp)
      num(b.x, `${bp}.x`)
      num(b.y, `${bp}.y`)
      bool(b.visible, `${bp}.visible`)
      return b
    })
    if (fo.possession !== null && fo.possession !== undefined) {
      oneOf(fo.possession, ['home', 'away', 'contested', 'dead'], `${p}.possession`)
    }
  })
  const meta = obj(m.meta, 'match_state.meta')
  str(meta.generator, 'match_state.meta.generator')
  str(meta.opencv_version, 'match_state.meta.opencv_version')
  return m as unknown as MatchState
}

export function validateTeamModel(raw: unknown): TeamModelFile {
  const t = obj(raw, 'teams_file')
  str(t.view, 'teams_file.view')
  const d = obj(t.directions, 'teams_file.directions')
  for (const side of TEAMS) oneOf(d[side], ['left', 'right'], `teams_file.directions.${side}`)
  return t as unknown as TeamModelFile
}

// ---------- Alerts ----------

export function validateAlert(raw: unknown, path = 'alert'): Alert {
  const a = obj(raw, path)
  str(a.alert_id, `${path}.alert_id`)
  str(a.event_id, `${path}.event_id`)
  str(a.created_utc, `${path}.created_utc`)
  num(a.match_time_s, `${path}.match_time_s`)
  str(a.title, `${path}.title`)
  str(a.explanation, `${path}.explanation`)
  str(a.suggestion, `${path}.suggestion`)
  nullOr(a.evidence_image, `${path}.evidence_image`, str)
  oneOf(a.status, ['pending', 'approved', 'rejected'], `${path}.status`)
  nullOr(a.decided_utc, `${path}.decided_utc`, str)
  nullOr(a.coach_note, `${path}.coach_note`, str)
  return a as unknown as Alert
}

// ---------- Trace ----------

export function validateTraceStep(raw: unknown, path = 'trace'): TraceStep {
  const s = obj(raw, path)
  str(s.ts, `${path}.ts`)
  str(s.match_id, `${path}.match_id`)
  const kind = oneOf(s.kind, ['card', 'tool_call', 'guard_block', 'decision', 'fallback', 'explanation', 'match_summary'], `${path}.kind`)
  if (kind !== 'match_summary') str(s.event_id, `${path}.event_id`)
  if (kind === 'card') {
    str(s.ref, `${path}.ref`)
    str(s.card, `${path}.card`)
  } else if (kind === 'tool_call') {
    str(s.tool, `${path}.tool`)
    str(s.actor, `${path}.actor`)
    str(s.ref, `${path}.ref`)
    obj(s.args, `${path}.args`)
    obj(s.result_summary, `${path}.result_summary`)
    num(s.duration_ms, `${path}.duration_ms`)
  } else if (kind === 'decision') {
    oneOf(s.decision, DECISIONS, `${path}.decision`)
    str(s.reason, `${path}.reason`)
    str(s.decided_by, `${path}.decided_by`)
    const v = obj(s.verdict, `${path}.verdict`)
    str(v.verdict, `${path}.verdict.verdict`)
  }
  return s as unknown as TraceStep
}

// ---------- Explanations ----------

export function validateExplanations(raw: unknown): ExplanationsFile {
  const e = obj(raw, 'explanations')
  obj(e.summary, 'explanations.summary')
  arr(e.candidates, 'explanations.candidates').forEach((c, i) => {
    const p = `explanations.candidates[${i}]`
    const co = obj(c, p)
    for (const k of ['set', 'event_id', 'team', 'change', 'clock', 'cause', 'reason_now', 'after']) str(co[k], `${p}.${k}`)
    oneOf(co.decision, DECISIONS, `${p}.decision`)
    oneOf(co.source, ['agent', 'template'], `${p}.source`)
    const facts = obj(co.facts, `${p}.facts`)
    str(facts.rule, `${p}.facts.rule`)
    obj(facts.results, `${p}.facts.results`)
  })
  return e as unknown as ExplanationsFile
}

// ---------- Agent run rows ----------

export function validateRunRows(raw: unknown): AgentRunRow[] {
  const r = obj(raw, 'report_llm')
  return arr(r.rows, 'report_llm.rows').map((row, i) => {
    const p = `report_llm.rows[${i}]`
    const ro = obj(row, p)
    str(ro.event_id, `${p}.event_id`)
    oneOf(ro.team, TEAMS, `${p}.team`)
    num(ro.t, `${p}.t`)
    oneOf(ro.decision, DECISIONS, `${p}.decision`)
    strArr(ro.tool_calls, `${p}.tool_calls`)
    bool(ro.opencv_changed_decision, `${p}.opencv_changed_decision`)
    const fp = obj(ro.first_pass, `${p}.first_pass`)
    num(fp.coverage_before, `${p}.first_pass.coverage_before`)
    num(fp.after_share_new, `${p}.first_pass.after_share_new`)
    num(fp.confident_after, `${p}.first_pass.confident_after`)
    return ro as unknown as AgentRunRow
  })
}

// ---------- Coach report ----------

export function validateCoachReport(raw: unknown): CoachReport {
  const r = obj(raw, 'report')
  const inputs = obj(r.inputs, 'report.inputs')
  const match = obj(inputs.match, 'report.inputs.match')
  const teams = obj(match.teams, 'report.inputs.match.teams')
  const names = TEAMS.map((side) => str(teams[side], `report.inputs.match.teams.${side}`))
  str(match.footage, 'report.inputs.match.footage')
  strArr(match.unavailable, 'report.inputs.match.unavailable')
  arr(inputs.segments, 'report.inputs.segments').forEach((s, i) => {
    const p = `report.inputs.segments[${i}]`
    const so = obj(s, p)
    str(so.seg, `${p}.seg`)
    for (const name of names) {
      const t = obj(so[name], `${p}.${name}`)
      str(t.formation, `${p}.${name}.formation`)
    }
  })
  for (const key of ['events', 'not_verified'] as const) {
    arr(inputs[key], `report.inputs.${key}`).forEach((e, i) => {
      const p = `report.inputs.${key}[${i}]`
      const eo = obj(e, p)
      for (const k of ['id', 'team', 'change', 'onset']) str(eo[k], `${p}.${k}`)
      if (eo.decision !== undefined) oneOf(eo.decision, DECISIONS, `${p}.decision`)
    })
  }
  const rep = obj(r.report, 'report.report')
  strArr(rep.formation_story, 'report.report.formation_story')
  strArr(rep.not_alerted, 'report.report.not_alerted')
  strArr(rep.recommendations, 'report.report.recommendations')
  strArr(rep.limits, 'report.report.limits')
  arr(rep.changes, 'report.report.changes').forEach((c, i) => {
    const co = obj(c, `report.report.changes[${i}]`)
    str(co.event, `report.report.changes[${i}].event`)
    str(co.what_changed, `report.report.changes[${i}].what_changed`)
    str(co.may_have_fixed, `report.report.changes[${i}].may_have_fixed`)
  })
  str(r.source, 'report.source')
  return r as unknown as CoachReport
}

// ---------- JSONL ----------

export function parseJsonl(text: string, name: string): unknown[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line, i) => {
      try {
        return JSON.parse(line) as unknown
      } catch {
        throw new DataError(`${name}: line ${i + 1} is not valid JSON`)
      }
    })
}
