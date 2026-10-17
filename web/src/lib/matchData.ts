import { useMemo } from 'react'
import {
  DEFAULT_MATCH,
  loadAlerts,
  loadExplanations,
  loadMatchState,
  loadReport,
  loadRunRows,
  loadTrace,
} from '../data'
import { useResource } from '../data/useResource'
import { buildTimeline } from '../data/timeline'
import { PositionIndex } from '../components/pitch/positions'
import { cached } from './cache'

const m = DEFAULT_MATCH
export const getAlerts = cached(`${m.id}/alerts`, () => loadAlerts(m))
/** Resolves after the browser has painted the next frame. */
const afterNextPaint = () =>
  new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)))

/**
 * The 2 MB positions file starts only after the small files the first screen needs have arrived
 * and that screen has painted, so on slow networks the text is not stuck behind it.
 */
export const getMatchState = cached(`${m.id}/match_state`, () =>
  Promise.allSettled([getTimeline(), getAlerts()])
    .then(afterNextPaint)
    .then(() => loadMatchState(m)),
)
export const getTrace = cached(`${m.id}/trace`, () => loadTrace(m))
export const getExplanations = cached(`${m.id}/explanations`, () => loadExplanations(m))
export const getRunRows = cached(`${m.id}/run_rows`, () => loadRunRows(m))
export const getReport = cached(`${m.id}/report`, () => loadReport(m))
/** the timeline is built from the coach report's inputs: one download for both */
export const getTimeline = cached(`${m.id}/timeline`, () => getReport().then(buildTimeline))

/** Match positions as an interpolation index, plus the pitch size. */
export function usePositions() {
  const res = useResource(getMatchState, `${m.id}/match_state`)
  const index = useMemo(() => (res.status === 'ready' ? new PositionIndex(res.data) : null), [res])
  return { res, index }
}
