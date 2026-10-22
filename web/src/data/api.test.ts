/** The analysis and chat data layer against a mocked network (no server, no AWS). */
import { readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, ApiNotConfigured, apiBase, apiConfigured, apiUrl, type Http } from './api'
import {
  analysisFrameUrl,
  confirmPitch,
  estimateProcessingSeconds,
  setPitchPoints,
  getAnalysisStatus,
  getSampleClip,
  loadAnalysisResult,
  startAnalysis,
  timelineFromContract,
  uploadVideo,
  type PitchPointsRequest,
} from './analysis'
import { sendChat } from './chat'
import { validateTraceStep } from './validate'

const BASE = 'https://api.test'
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function fakeHttp(routes: Record<string, (init?: RequestInit) => Response>, uploadReply?: unknown): Http & { calls: string[] } {
  const calls: string[] = []
  return {
    calls,
    fetch: vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? 'GET'} ${url.replace(BASE, '')}`
      calls.push(key)
      const route = routes[key]
      if (!route) return new Response('not found', { status: 404 })
      return route(init)
    }),
    upload: vi.fn(async (url: string, _form: FormData, onProgress?: (f: number) => void) => {
      calls.push(`UPLOAD ${url.replace(BASE, '')}`)
      onProgress?.(0.5)
      onProgress?.(1)
      return { status: 201, body: JSON.stringify(uploadReply) }
    }),
  }
}

const status = (over: object = {}) => ({ id: 'an_1', status: 'running', stage: 'detecting', progress: 0.3, eta_s: 120, error: null, ...over })
const points: PitchPointsRequest = {
  points: [
    { x: 10, y: 10 },
    { x: 1900, y: 12 },
    { x: 1910, y: 1070 },
    { x: 5, y: 1075 },
  ],
  frame: { width: 1920, height: 1080, t_s: 0 },
  straight_down: false,
}

describe('analysis API client', () => {
  it('is not configured without a base URL and refuses to call', async () => {
    expect(apiConfigured('')).toBe(false)
    await expect(getAnalysisStatus('x', { base: '' })).rejects.toBeInstanceOf(ApiNotConfigured)
  })

  it('uploads, starts, polls and loads a result through the documented endpoints', async () => {
    const sample = resolve(__dirname, '..', '..', 'public', 'sample', 'w900_1260')
    const matchState = JSON.parse(await readFile(join(sample, 'match_state_top_w900_1260_4fps.json'), 'utf8'))
    const alerts = (await readFile(join(sample, 'alerts_llm.jsonl'), 'utf8')).trim().split('\n').map((l) => JSON.parse(l))
    const timeline = {
      contract_version: '1.0',
      match_id: 'up_1',
      teams: { home: 'White', away: 'Blue' },
      segments: [
        { start_s: 900, end_s: 990, home: { formation: '4-4-2', confidence: 0.8, defensive_line_m: 20, compactness_m: 25, width_m: 30 }, away: { formation: '4-2-3-1', confidence: 0.7, defensive_line_m: 60, compactness_m: 30, width_m: 33 } },
      ],
      events: [
        { id: 'evt_001', t: 990, type: 'shape_change', team: 'home', from: '4-4-2', to: '3-4-3', confidence: 1, evidence: '', status: 'confirmed', verification: { decided_by: 'agent', decision: 'confirmed', reason: 'held', tool_calls: [], evidence_image: null, trace_id: null } },
        { id: 'evt_002', t: 1000, type: 'line_drop', team: 'away', from: '', to: '', confidence: 0.5, evidence: '', status: 'candidate', verification: null },
      ],
    }
    const http = fakeHttp(
      {
        'POST /api/analyses/an_1/start': (init) => {
          expect(JSON.parse(String(init?.body))).toMatchObject({ straight_down: false, frame: { width: 1920 } })
          return json(status({ status: 'queued', stage: 'detecting', progress: 0.05 }))
        },
        'GET /api/analyses/an_1': () => json(status({ status: 'done', stage: 'done', progress: 1, eta_s: 0 })),
        'GET /api/analyses/an_1/result': () => json({ id: 'an_1', label: 'My match', match_state: matchState, timeline, alerts, trace: [], report: null }),
      },
      status({ status: 'uploaded', stage: 'uploading', progress: 0 }),
    )
    const progress: number[] = []
    const file = new File([new Uint8Array(8)], 'match.mp4', { type: 'video/mp4' })
    const up = await uploadVideo(file, (f) => progress.push(f), { http, base: BASE })
    expect(up.id).toBe('an_1')
    expect(progress).toEqual([0.5, 1])
    await startAnalysis(up.id, points, { http, base: BASE })
    const done = await getAnalysisStatus(up.id, { http, base: BASE })
    expect(done.stage).toBe('done')
    const result = await loadAnalysisResult(up.id, { http, base: BASE })
    expect(result.alerts[0].event_id).toBe('evt_003')
    const view = timelineFromContract(result.timeline)
    expect(view.events).toEqual([{ id: 'evt_001', team: 'home', t: 990, from: '4-4-2', to: '3-4-3', status: 'confirmed', reason: 'held' }])
    expect(http.calls).toEqual(['UPLOAD /api/analyses', 'POST /api/analyses/an_1/start', 'GET /api/analyses/an_1', 'GET /api/analyses/an_1/result'])
  })

  it('reports server errors with the status and detail, and rejects bad payloads', async () => {
    const http = fakeHttp({ 'GET /api/analyses/bad': () => json({ detail: 'no such analysis' }, 404), 'GET /api/analyses/odd': () => json({ id: 'odd', status: 'running', stage: 'warp', progress: 2 }) })
    await expect(getAnalysisStatus('bad', { http, base: BASE })).rejects.toThrow(/HTTP 404.*no such analysis/)
    await expect(getAnalysisStatus('bad', { http, base: BASE })).rejects.toBeInstanceOf(ApiError)
    await expect(getAnalysisStatus('odd', { http, base: BASE })).rejects.toThrow(/analysis.stage/)
  })

  it('needs exactly 4 pitch points', async () => {
    const http = fakeHttp({})
    const bad = { ...points, points: points.points.slice(0, 3) } as unknown as PitchPointsRequest
    await expect(startAnalysis('an_1', bad, { http, base: BASE })).rejects.toThrow(/4 pitch points/)
    expect(http.calls).toEqual([])
  })

  it('treats "/" and "same-origin" as the server that serves the site (relative URLs)', () => {
    for (const v of ['/', 'same-origin', ' SAME-ORIGIN ']) {
      expect(apiConfigured(v)).toBe(true)
      expect(apiBase(v)).toBe('')
      expect(apiUrl('/api/demo', { base: v })).toBe('/api/demo')
    }
    expect(apiBase('http://localhost:8000/')).toBe('http://localhost:8000')
    expect(analysisFrameUrl('an 1', { base: '/' })).toBe('/api/analyses/an%201/frame')
    expect(apiConfigured('  ')).toBe(false)
    expect(() => apiUrl('/api/demo', { base: '' })).toThrow(ApiNotConfigured)
  })

  it('sends the visitor cookie on every call (credentials: include)', async () => {
    const http = fakeHttp({ 'GET /api/analyses/a': () => json(status({ id: 'a' })) })
    await getAnalysisStatus('a', { http, base: BASE })
    expect(http.fetch).toHaveBeenCalledWith(`${BASE}/api/analyses/a`, expect.objectContaining({ credentials: 'include' }))
  })

  it('reads the pitch step: needs_confirmation -> confirm, needs_corners -> 4 points', async () => {
    const corners = [
      [90.6, 70],
      [870, 72],
      [868, 540],
      [92, 538],
    ]
    const pitch = { state: 'detected', corners, preview_url: 'http://x/api/analyses/an_1/pitch-preview', message: 'found it' }
    const video = { filename: 'm.mp4', width: 960, height: 600, fps: 8, frames: 480, duration_s: 60 }
    const http = fakeHttp(
      {
        'POST /api/analyses/an_1/pitch': (init) => {
          expect(JSON.parse(String(init?.body))).toEqual({ confirmed: true })
          return json(status({ status: 'queued', stage: 'uploading', progress: 0, pitch: { ...pitch, state: 'confirmed' } }))
        },
        'POST /api/analyses/an_2/pitch': (init) => {
          expect(JSON.parse(String(init?.body))).toEqual({ pitch_points: [[10.1, 20], [900, 20], [900, 580], [10, 580]] })
          return json(status({ id: 'an_2', status: 'queued', stage: 'uploading', progress: 0 }))
        },
      },
      status({ status: 'needs_confirmation', stage: 'uploading', progress: 0, pitch, video }),
    )
    const file = new File([new Uint8Array(8)], 'm.mp4', { type: 'video/mp4' })
    const up = await uploadVideo(file, undefined, { http, base: BASE })
    expect(up.status).toBe('needs_confirmation')
    expect(up.pitch?.corners).toEqual(corners)
    expect(up.pitch?.preview_url).toBe(pitch.preview_url)
    expect(up.video).toEqual({ width: 960, height: 600, duration_s: 60 })
    expect((await confirmPitch('an_1', { http, base: BASE })).status).toBe('queued')
    const pts = [
      { x: 10.12, y: 20 },
      { x: 900, y: 20 },
      { x: 900, y: 580 },
      { x: 10, y: 580 },
    ]
    expect((await setPitchPoints('an_2', pts, { http, base: BASE })).status).toBe('queued')
    await expect(setPitchPoints('an_2', pts.slice(0, 3), { http, base: BASE })).rejects.toThrow(/4 pitch points/)
    // needs_corners carries a best guess for preloading, and no confirmed corners
    const guess = await uploadVideo(file, undefined, {
      http: fakeHttp({}, status({ status: 'needs_corners', stage: 'uploading', progress: 0, pitch: { state: 'needs_corners', corners: null, suggested_corners: corners } })),
      base: BASE,
    })
    expect(guess.pitch?.corners).toBeNull()
    expect(guess.pitch?.suggested_corners).toEqual(corners)
  })

  it('accepts the explanation step of current agent traces (uploads)', () => {
    const step = { ts: '2026-10-17T12:10:56Z', run_id: 'api_1', match_id: 'up_1', event_id: 'evt_001', step: 4, actor: 'code', kind: 'explanation', source: 'template', text: 'White kept the 3-5-2 [R2].' }
    expect(validateTraceStep(step).kind).toBe('explanation')
    expect(() => validateTraceStep({ ...step, kind: 'nonsense' })).toThrow(/kind/)
  })

  it('estimates processing from the measured 1.2 s per second of video', () => {
    expect(estimateProcessingSeconds(300)).toBe(360)
  })
})

describe('chat API client', () => {
  it('posts the question with history and returns the answer', async () => {
    const http = fakeHttp({
      'POST /api/chat': (init) => {
        const body = JSON.parse(String(init?.body))
        expect(body).toEqual({ match_id: 'teamtrack_top_w900_1260', question: 'Why 3-4-3?', history: [{ role: 'user', text: 'hi' }] })
        return json({ answer: 'Because it held in 91% of readings [R2].', citations: ['R2'], trace_id: 'tr_1' })
      },
    })
    const a = await sendChat({ match_id: 'teamtrack_top_w900_1260', question: '  Why 3-4-3? ', history: [{ role: 'user', text: 'hi' }] }, { http, base: BASE })
    expect(a).toEqual({ answer: 'Because it held in 91% of readings [R2].', citations: ['R2'], trace_id: 'tr_1' })
  })

  it('does not call anything when the backend is not configured', async () => {
    const http = fakeHttp({})
    await expect(sendChat({ match_id: 'm', question: 'q', history: [] }, { http, base: '' })).rejects.toBeInstanceOf(ApiNotConfigured)
    expect(http.calls).toEqual([])
  })
})

describe('sample clip client', () => {
  it('is null when the server has no sample, and absolute when it has one', async () => {
    expect(await getSampleClip({ http: fakeHttp({ 'GET /api/sample': () => json({ available: false }) }), base: BASE })).toBeNull()
    const http = fakeHttp({ 'GET /api/sample': () => json({ available: true, label: 'Clip', bytes: 10,
      video_url: '/api/sample/video', file_name: 'gaffer_sample_clip.mp4' }) })
    expect(await getSampleClip({ http, base: BASE })).toEqual({ label: 'Clip', bytes: 10,
      videoUrl: `${BASE}/api/sample/video`, fileName: 'gaffer_sample_clip.mp4' })
  })
})
