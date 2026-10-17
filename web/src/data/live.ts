/**
 * Live replay timing for a decided candidate, read from its recorded trace.
 *
 * - onset / detected: from the candidate card ("onset 990.0 s", "detected 1025.0 s").
 * - The checks can only start once the required re-analysis span has been played
 *   ("required re-analysis span [945, 1085]": the 60 s look-ahead after detection).
 * - Each tool step then lands after its recorded time (tool duration + LLM latency). The
 *   re-analysis was a cache hit in this run (2.8 s); uncached it took 252 s of OpenCV.
 */
import type { TraceStep, TraceToolCall } from './types'

export interface LivePlan {
  onset: number
  detected: number
  checksFrom: number
  /** match time at which each tool step (in trace order) is complete */
  stepTimes: number[]
  decidedAt: number
}

export function livePlan(steps: TraceStep[]): LivePlan | null {
  const card = steps.find((s) => s.kind === 'card')
  if (!card || card.kind !== 'card') return null
  const onset = Number(/onset ([\d.]+) s/.exec(card.card)?.[1])
  const detected = Number(/detected ([\d.]+) s/.exec(card.card)?.[1])
  const span = /required re-analysis span \[([\d.]+), ([\d.]+)\]/.exec(card.card)
  if (!Number.isFinite(onset) || !Number.isFinite(detected) || !span) return null
  const checksFrom = Number(span[2])
  const tools = steps.filter((s): s is TraceToolCall => s.kind === 'tool_call')
  let t = checksFrom
  const stepTimes = tools.map((s) => {
    t += (s.duration_ms + (s.llm?.latency_ms ?? 0)) / 1000
    return t
  })
  return { onset, detected, checksFrom, stepTimes, decidedAt: stepTimes.at(-1) ?? checksFrom }
}

export type LivePhase = 'before' | 'spotted' | 'waiting' | 'checking' | 'decided'

export function livePhase(plan: LivePlan, t: number): { phase: LivePhase; stepsDone: number } {
  if (t < plan.onset) return { phase: 'before', stepsDone: 0 }
  if (t < plan.detected) return { phase: 'spotted', stepsDone: 0 }
  if (t < plan.checksFrom) return { phase: 'waiting', stepsDone: 0 }
  const stepsDone = plan.stepTimes.filter((x) => x <= t).length
  return { phase: stepsDone >= plan.stepTimes.length ? 'decided' : 'checking', stepsDone }
}
