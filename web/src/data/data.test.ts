/**
 * Loads every sample file through the real data-layer loaders (bytes read from
 * public/sample/, filled by scripts/copy-samples.mjs before `npm test`) and checks the shapes.
 */
import { readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  DataError,
  DEFAULT_MATCH,
  evidenceImageUrl,
  loadAlerts,
  loadExplanations,
  loadMatchState,
  loadReport,
  loadReportMarkdown,
  loadRunRows,
  loadTeamModel,
  loadTimeline,
  loadTrace,
  traceForEvent,
  type ReadText,
} from './index'
import { splitAlertExplanation } from './alerts'
import { validateAlert, validateMatchState } from './validate'

const root = resolve(__dirname, '..', '..', 'public', 'sample')
const diskReader: ReadText = (p) => readFile(join(root, p), 'utf8')

describe('sample data (w900_1260)', () => {
  it('every file the manifest names exists', async () => {
    const files = [...Object.values(DEFAULT_MATCH.files), ...DEFAULT_MATCH.assets]
    for (const f of files) {
      const buf = await readFile(join(root, DEFAULT_MATCH.id, f))
      expect(buf.byteLength, f).toBeGreaterThan(0)
    }
  })

  it('match_state follows the contract', async () => {
    const m = await loadMatchState(DEFAULT_MATCH, diskReader)
    expect(m.contract_version).toBe('1.0')
    expect(m.source).toBe('video')
    expect(m.frames.length).toBeGreaterThan(100)
    expect(m.frames[0].t).toBeGreaterThanOrEqual(DEFAULT_MATCH.window[0])
    expect(m.frames.at(-1)!.t).toBeLessThanOrEqual(DEFAULT_MATCH.window[1])
    expect(m.teams.home.name).toBe('White')
    expect(m.teams.away.name).toBe('Blue')
  })

  it('teams file has view and directions', async () => {
    const t = await loadTeamModel(DEFAULT_MATCH, diskReader)
    expect(t.view).toBe('top')
    expect(['left', 'right']).toContain(t.directions.home)
  })

  it('alerts: one pending alert for evt_003 with an evidence image in the sample', async () => {
    const alerts = await loadAlerts(DEFAULT_MATCH, diskReader)
    expect(alerts).toHaveLength(1)
    const [a] = alerts
    expect(a.event_id).toBe('evt_003')
    expect(a.status).toBe('pending')
    expect(evidenceImageUrl(a)).toMatch(/evt_003\.jpg$/)
    const text = splitAlertExplanation(a.explanation)
    expect(text.verified).toContain('91%')
    expect(text.explanationSource).toBe('agent')
  })

  it('trace: tool calls in order with prev_ref chain, one decision per candidate', async () => {
    const steps = await loadTrace(DEFAULT_MATCH, diskReader)
    const evt = traceForEvent(steps, 'evt_003')
    expect(evt[0].kind).toBe('card')
    const tools = evt.filter((s) => s.kind === 'tool_call').map((s) => (s.kind === 'tool_call' ? s.tool : ''))
    expect(tools).toEqual(['check_frame_quality', 'reanalyse_window', 'record_decision', 'render_evidence', 'propose_alert'])
    const decisions = evt.filter((s) => s.kind === 'decision')
    expect(decisions).toHaveLength(1)
  })

  it('explanations for this window: evt_003 confirmed, evt_007 rejected', async () => {
    const ex = await loadExplanations(DEFAULT_MATCH, diskReader)
    const byId = Object.fromEntries(ex.map((e) => [e.event_id, e]))
    expect(byId.evt_003.decision).toBe('confirmed')
    expect(byId.evt_007.decision).toBe('rejected')
  })

  it('run rows: first pass and decision per candidate', async () => {
    const rows = await loadRunRows(DEFAULT_MATCH, diskReader)
    expect(rows.map((r) => r.event_id)).toEqual(['evt_003', 'evt_007'])
    expect(rows.every((r) => r.opencv_changed_decision === false)).toBe(true)
  })

  it('coach report + timeline: contiguous segments covering 15:00-21:00, all 9 candidates', async () => {
    const r = await loadReport(DEFAULT_MATCH, diskReader)
    expect(r.source).toBe('code template')
    const tl = await loadTimeline(DEFAULT_MATCH, diskReader)
    expect(tl.start_s).toBe(900)
    expect(tl.end_s).toBe(1260)
    expect(tl.segments[0].start_s).toBe(900)
    expect(tl.segments.at(-1)!.end_s).toBe(1260)
    for (let i = 1; i < tl.segments.length; i++) expect(tl.segments[i].start_s).toBe(tl.segments[i - 1].end_s)
    expect(tl.events).toHaveLength(9)
    expect(tl.events.find((e) => e.id === 'evt_003')).toMatchObject({ team: 'home', t: 990, status: 'confirmed' })
    expect(tl.events.find((e) => e.id === 'evt_007')).toMatchObject({ team: 'away', t: 1130, status: 'rejected' })
    const md = await loadReportMarkdown(DEFAULT_MATCH, diskReader)
    expect(md).toContain('# Coach report')
  })
})

describe('validators reject bad data loudly', () => {
  it('wrong contract version', () => {
    expect(() => validateMatchState({ contract_version: '2.0' })).toThrow(DataError)
  })
  it('unsorted frames', () => {
    const base = {
      contract_version: '1.0', match_id: 'x', source: 'video', fps: 2, duration_s: 1,
      pitch: { length_m: 105, width_m: 68 }, source_video: null,
      teams: {
        home: { name: 'A', colour: '#fff', attacking_direction_first_half: 'left' },
        away: { name: 'B', colour: '#000', attacking_direction_first_half: 'right' },
      },
      periods: [], meta: { generator: 'g', opencv_version: '5', created_utc: '', notes: '' },
      frames: [{ t: 2, players: [], ball: null, possession: null }, { t: 1, players: [], ball: null, possession: null }],
    }
    expect(() => validateMatchState(base)).toThrow(/sorted/)
  })
  it('alert with an unknown status', () => {
    expect(() => validateAlert({ alert_id: 'a', status: 'maybe' })).toThrow(DataError)
  })
})

describe('second pass helpers', () => {
  it('live plan for evt_003 follows the trace: detected 17:05, checks from 18:05, steps in order', async () => {
    const { livePlan, livePhase } = await import('./live')
    const steps = traceForEvent(await loadTrace(DEFAULT_MATCH, diskReader), 'evt_003')
    const plan = livePlan(steps)!
    expect(plan.onset).toBe(990)
    expect(plan.detected).toBe(1025)
    expect(plan.checksFrom).toBe(1085)
    expect(plan.stepTimes).toHaveLength(5)
    for (let i = 1; i < 5; i++) expect(plan.stepTimes[i]).toBeGreaterThan(plan.stepTimes[i - 1])
    expect(livePhase(plan, 1000).phase).toBe('spotted')
    expect(livePhase(plan, 1050).phase).toBe('waiting')
    expect(livePhase(plan, plan.decidedAt).phase).toBe('decided')
  })

  it('displayFormation never returns "uncertain"', async () => {
    const { displayFormation } = await import('./timeline')
    const tl = await loadTimeline(DEFAULT_MATCH, diskReader)
    for (let t = tl.start_s; t < tl.end_s; t += 5) {
      for (const side of ['home', 'away'] as const) expect(displayFormation(tl, side, t).formation).not.toBe('uncertain')
    }
    // White is unsettled until 16:30: shown as the 4-4-2 it was holding
    expect(displayFormation(tl, 'home', 977)).toEqual({ formation: '4-4-2', holding: true })
  })

  it('orientation turns the pitch so home attacks right', async () => {
    const { orientationAt, orient } = await import('../lib/orientation')
    const m = await loadMatchState(DEFAULT_MATCH, diskReader)
    const o = orientationAt(m, 1000)
    expect(o.turn).toBe(m.teams.home.attacking_direction_first_half === 'left')
    expect(orient(10, 5, { ...o, turn: true }, 105, 68)).toEqual([95, 63])
  })
})
