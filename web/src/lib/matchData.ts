import { useMemo } from 'react'
import {
  DEFAULT_MATCH,
  loadAlerts,
  loadExplanations,
  loadMatchState,
  loadReport,
  loadRunRows,
  loadTimeline,
  loadTrace,
} from '../data'
import { useResource } from '../data/useResource'
import { PositionIndex } from '../components/pitch/positions'
import { cached } from './cache'

const m = DEFAULT_MATCH
export const getMatchState = cached(`${m.id}/match_state`, () => loadMatchState(m))
export const getTimeline = cached(`${m.id}/timeline`, () => loadTimeline(m))
export const getAlerts = cached(`${m.id}/alerts`, () => loadAlerts(m))
export const getTrace = cached(`${m.id}/trace`, () => loadTrace(m))
export const getExplanations = cached(`${m.id}/explanations`, () => loadExplanations(m))
export const getRunRows = cached(`${m.id}/run_rows`, () => loadRunRows(m))
export const getReport = cached(`${m.id}/report`, () => loadReport(m))

/** Match positions as an interpolation index, plus the pitch size. */
export function usePositions() {
  const res = useResource(getMatchState, `${m.id}/match_state`)
  const index = useMemo(() => (res.status === 'ready' ? new PositionIndex(res.data) : null), [res])
  return { res, index }
}
