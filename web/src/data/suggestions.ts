/** Suggested chat questions, built from the real timeline (decided changes first). */
import { formatClock } from './time'
import type { FormationTimeline } from './types'

const BACK = ['', 'a back one', 'a back two', 'a back three', 'a back four', 'a back five', 'a back six']

function shapeWords(from: string, to: string): string {
  const a = Number(from.split('-')[0])
  const b = Number(to.split('-')[0])
  return a !== b && BACK[b] ? BACK[b] : to
}

export function suggestedQuestions(tl: FormationTimeline | null, max = 3): string[] {
  if (!tl) return []
  const out: string[] = []
  for (const e of tl.events) {
    const team = tl.teamNames[e.team]
    if (e.status === 'confirmed') out.push(`Why did ${team} switch to ${shapeWords(e.from, e.to)} at ${formatClock(e.t)}?`)
    else if (e.status === 'rejected') out.push(`Why was ${team}'s ${formatClock(e.t)} change rejected?`)
    else if (e.status === 'uncertain') out.push(`Why is ${team}'s ${formatClock(e.t)} change marked uncertain?`)
  }
  const unchecked = tl.events.filter((e) => e.status === 'candidate').length
  if (unchecked > 0) out.push(`Why were ${unchecked} changes not checked?`)
  return out.slice(0, max)
}
