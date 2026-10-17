/**
 * The pre-processed matches the demo can show. One entry today: the 900-1260 s window of the
 * TeamTrack drone match (samples/w900_1260, copied to public/sample/ by scripts/copy-samples.mjs).
 */
export interface MatchEntry {
  id: string
  label: string
  /** first and last second of footage in this match file */
  window: [number, number]
  files: {
    matchState: string
    teamModel: string
    alerts: string
    trace: string
    explanations: string
    report: string
    reportMarkdown: string
    runRows: string
  }
  /** the explanations file covers several runs; this match is the "w900" set */
  explanationSet: string
  /** extra files (images) that alerts may reference, by base name */
  assets: string[]
}

export const MATCHES: MatchEntry[] = [
  {
    id: 'w900_1260',
    label: 'TeamTrack drone · White vs Blue · 15:00–21:00',
    window: [900, 1260],
    files: {
      matchState: 'match_state_top_w900_1260_4fps.json',
      teamModel: 'match_state_top_w900_1260_4fps.teams.json',
      alerts: 'alerts_llm.jsonl',
      trace: 'trace_llm.jsonl',
      explanations: 'explanations.json',
      report: 'report_w900_1260.json',
      reportMarkdown: 'report_w900_1260.md',
      runRows: 'report_llm.json',
    },
    explanationSet: 'w900',
    assets: ['evt_003.jpg'],
  },
]

export const DEFAULT_MATCH = MATCHES[0]

export function getMatch(id: string): MatchEntry {
  const m = MATCHES.find((x) => x.id === id)
  if (!m) throw new Error(`unknown match "${id}"`)
  return m
}
