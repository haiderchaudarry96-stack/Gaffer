import { useEffect, useRef, type ReactNode } from 'react'
import { m } from 'motion/react'
import { ArrowDown, Cpu, Eye, Sparkles } from 'lucide-react'
import type { AgentRunRow, TraceStep, TraceToolCall } from '../../data'
import { formatClock } from '../../data/time'

const OPENCV_TOOLS = new Set(['check_frame_quality', 'reanalyse_window', 'render_evidence'])

const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
const pct = (v: unknown, digits = 0) => (num(v) !== undefined ? `${(num(v)! * 100).toFixed(digits)} %` : '—')
const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})
const windowText = (v: unknown) => {
  const w = Array.isArray(v) ? v : []
  return w.length === 2 && num(w[0]) !== undefined ? `${formatClock(w[0] as number)}–${formatClock(w[1] as number)}` : '—'
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="font-mono text-text tabular">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function RulesLine({ rules }: { rules: Record<string, unknown> }) {
  const verdict = typeof rules.verdict === 'string' ? rules.verdict : null
  if (!verdict) return null
  const failed = Array.isArray(rules.failed) ? (rules.failed as string[]) : []
  const missing = Array.isArray(rules.missing) ? (rules.missing as string[]) : []
  const colour = verdict === 'confirm' ? 'text-accent-ink' : verdict === 'reject' ? 'text-danger' : 'text-warn'
  return (
    <p className="mt-2 text-xs text-muted">
      Rules after this result: <span className={`font-mono font-semibold ${colour}`}>{verdict}</span>
      {failed.length > 0 && <> · failed {failed.join(', ')}</>}
      {missing.length > 0 && <> · still missing {missing.join(', ')}</>}
    </p>
  )
}

function toolFacts(s: TraceToolCall): [string, ReactNode][] {
  const r = s.result_summary
  switch (s.tool) {
    case 'check_frame_quality': {
      const cov = rec(r.coverage)
      return [
        ['window', windowText(r.window)],
        ['pitch lines fit', pct(r.homography_ok_share)],
        ['camera shift', `${num(r.camera_shift_px_per_s_max) ?? '—'} px/s`],
        ['zoom change', pct(r.zoom_change_max, 1)],
        ['camera cut', r.camera_cut === true ? 'yes' : r.camera_cut === false ? 'no' : '—'],
        ['coverage home / away', `${pct(cov.home)} / ${pct(cov.away)}`],
        ['OpenCV time', `${((num(r.opencv_ms) ?? 0) / 1000).toFixed(1)} s`],
      ]
    }
    case 'reanalyse_window': {
      const vs = rec(r.vs_event)
      return [
        ['window', `${windowText(r.window)} at ${num(r.sample_fps) ?? '—'} fps`],
        ['frames re-run', `${num(r.frames) ?? '—'}`],
        [
          'OpenCV time',
          `${num(r.processing_s) ?? '—'} s${r.cache === 'hit' ? ' (cached from an earlier run; this call took ' + (s.duration_ms / 1000).toFixed(1) + ' s)' : ''}`,
        ],
        ['new shape held', `${pct(vs.after_share_new)} of ${num(vs.confident_after) ?? '—'} clear readings`],
        ['coverage before / after', `${pct(vs.coverage_before)} / ${pct(vs.coverage_after)}`],
        ['went back', vs.reverted_after_s == null ? 'no' : `after ${vs.reverted_after_s} s`],
        ...(typeof vs.return_of === 'string' ? ([['undoes', vs.return_of]] as [string, ReactNode][]) : []),
      ]
    }
    case 'record_decision':
      return [
        ['decision', String(r.event_status ?? '—')],
        ['recorded reason (code)', String(r.recorded_reason ?? '—')],
      ]
    case 'render_evidence':
      return [
        ['frame', typeof r.clock === 'string' ? r.clock : '—'],
        ['size', `${Math.round((num(r.bytes) ?? 0) / 1000)} KB JPEG`],
      ]
    case 'propose_alert':
      return [
        ['alert', String(r.alert_id ?? '—')],
        ['status', String(r.status ?? '—')],
      ]
    default:
      return []
  }
}

function actorLabel(actor: string) {
  if (actor === 'llm') return 'Nova 2 Lite'
  if (actor === 'rules') return 'rules (no LLM)'
  return actor
}

/** "How Gaffer checked this": the recorded agent trace of one candidate, step by step. */
export default function TracePanel({
  steps,
  row,
  focusRef,
  teamName,
  stepsShown,
}: {
  steps: TraceStep[]
  row: AgentRunRow | undefined
  focusRef: string | null
  teamName: string
  /** live replay: only the first n tool steps have happened yet */
  stepsShown?: number
}) {
  const listRef = useRef<HTMLOListElement>(null)

  useEffect(() => {
    if (!focusRef || !listRef.current) return
    const el = listRef.current.querySelector<HTMLElement>(`[data-ref="${focusRef}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    el?.focus({ preventScroll: true })
  }, [focusRef])

  const allTools = steps.filter((s): s is TraceToolCall => s.kind === 'tool_call')
  const tools = stepsShown === undefined ? allTools : allTools.slice(0, stepsShown)
  const done = tools.length === allTools.length
  const card = steps.find((s) => s.kind === 'card')
  const decision = done ? steps.find((s) => s.kind === 'decision') : undefined

  return (
    <div>
      <ol ref={listRef} className="space-y-2">
        {card && card.kind === 'card' && (
          <m.li
            data-ref="R0"
            tabIndex={-1}
            className={`rounded-xl border p-3 ${focusRef === 'R0' ? 'border-accent' : 'border-line'} bg-bg/50`}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <StepHeader refId="R0" title="candidate card" actor="code" />
            <p className="mt-1.5 text-xs text-muted">The tactics engine’s first pass over the stored positions.</p>
            {row && (
              <Facts
                rows={[
                  ['change', `${teamName} ${row.from} → ${row.to} at ${row.clock}`],
                  ['new shape held', `${pct(row.first_pass.after_share_new)} of ${row.first_pass.confident_after} clear readings`],
                  ['coverage before / after', `${pct(row.first_pass.coverage_before)} / ${pct(row.first_pass.coverage_after)}`],
                ]}
              />
            )}
            <RulesLine rules={parseCardRules(card.card)} />
            {tools[0] && <NextArrow to={tools[0]} />}
          </m.li>
        )}
        {tools.map((s, i) => {
          const rules = rec(s.result_summary.rules)
          const opencv = OPENCV_TOOLS.has(s.tool) && s.backend === 'video'
          return (
            <m.li
              key={s.ref}
              data-ref={s.ref}
              tabIndex={-1}
              className={`rounded-xl border p-3 ${focusRef === s.ref ? 'border-accent' : 'border-line'} bg-bg/50`}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1], delay: stepsShown === undefined ? 0.08 * (i + 1) : 0 }}
            >
              <StepHeader refId={s.ref} title={s.tool} actor={actorLabel(s.actor)} opencv={opencv} />
              <Facts rows={toolFacts(s)} />
              <RulesLine rules={rules} />
              {s.tool === 'propose_alert' && (
                <p className="mt-2 text-[11px] text-muted">
                  The alert’s coach-facing text was rewritten and checked afterwards (build step 7); the decision was
                  replayed and is unchanged.
                </p>
              )}
              {tools[i + 1] && <NextArrow to={tools[i + 1]} />}
            </m.li>
          )
        })}
      </ol>
      {decision && decision.kind === 'decision' && (
        <div className="mt-3 rounded-xl border border-line p-3 text-xs text-muted">
          <p>
            <span className="font-semibold text-text">Decided: {decision.decision}</span> by the {decision.decided_by} ·
            rules verdict <span className="font-mono">{decision.verdict.verdict}</span> · {decision.llm_calls} LLM calls ·
            ${decision.cost_usd.toFixed(4)}
          </p>
          {row && !row.opencv_changed_decision && (
            <p className="mt-2 leading-relaxed">
              Honest reading: the first pass alone gives the same decision ({row.first_pass_decision}). Here OpenCV set the
              path (camera check, second look) and produced the evidence; it did not change the verdict. On real footage
              that happened only on a simulated camera pan.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function StepHeader({ refId, title, actor, opencv = false }: { refId: string; title: string; actor: string; opencv?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded-md border border-line bg-surface-2 px-1.5 font-mono text-[11px] text-text">{refId}</span>
      <span className="font-mono text-[13px] font-semibold text-text">{title}</span>
      <span className="ml-auto flex items-center gap-1.5">
        {opencv && (
          <span className="inline-flex items-center gap-1 rounded-full border border-accent/40 px-2 py-0.5 text-[10px] font-semibold text-accent-ink uppercase">
            <Eye className="size-3" aria-hidden="true" /> OpenCV
          </span>
        )}
        <span className="inline-flex items-center gap-1 text-[11px] text-muted">
          {actor === 'Nova 2 Lite' ? <Sparkles className="size-3" aria-hidden="true" /> : <Cpu className="size-3" aria-hidden="true" />}
          {actor}
        </span>
      </span>
    </div>
  )
}

function NextArrow({ to }: { to: TraceToolCall }) {
  return (
    <p className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-accent-ink">
      <ArrowDown className="size-3" aria-hidden="true" /> next call: <span className="font-mono">{to.tool}</span>
      {to.tool === 'reanalyse_window' && typeof to.args.sample_fps === 'number' && <span className="font-mono">at {to.args.sample_fps} fps</span>}
    </p>
  )
}

/** The card's "rules: verdict need_more, failed ['coverage'], missing [...]" line. */
function parseCardRules(card: string): Record<string, unknown> {
  const line = card.split('\n').find((l) => l.startsWith('rules:'))
  if (!line) return {}
  const verdict = /verdict (\w+)/.exec(line)?.[1]
  const list = (name: string) => {
    const m = new RegExp(`${name} \\[([^\\]]*)\\]`).exec(line)
    return m ? [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1]) : []
  }
  return { verdict, failed: list('failed'), missing: list('missing') }
}
