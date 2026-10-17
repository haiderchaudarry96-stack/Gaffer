/** Helpers for the alert text format written by agent/alerts.py (AGENT_DESIGN §2, step 7). */

export interface AlertText {
  /** the code-written rules reason ("Verified: ...") */
  verified: string | null
  /** the checked explanation */
  explanation: string | null
  /** who wrote the explanation: "agent" (Nova, passed the check) or "template" (code) */
  explanationSource: 'agent' | 'template' | null
  /** anything that did not match the format */
  other: string | null
}

export function splitAlertExplanation(text: string): AlertText {
  let verified: string | null = null
  let explanation: string | null = null
  let explanationSource: AlertText['explanationSource'] = null
  const other: string[] = []
  for (const line of text.split('\n')) {
    const v = /^Verified:\s*(.*)$/.exec(line)
    const e = /^Explanation \((agent|template)\):\s*(.*)$/.exec(line)
    if (v) verified = v[1]
    else if (e) {
      explanationSource = e[1] as 'agent' | 'template'
      explanation = e[2]
    } else if (line.trim()) other.push(line)
  }
  return { verified, explanation, explanationSource, other: other.length ? other.join('\n') : null }
}

/** Splits "[R2]"-style citations out of a sentence so the UI can render them as chips. */
export function splitCitations(text: string): { text: string; ref: string | null }[] {
  const parts: { text: string; ref: string | null }[] = []
  const re = /\[(R\d+|evt_\d{3}|seg [0-9:\-–]+)\]/g
  let last = 0
  for (const m of text.matchAll(re)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), ref: null })
    parts.push({ text: m[0], ref: m[1] })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last), ref: null })
  return parts
}
