/** Match clock helpers. Times are seconds from kickoff; the clock is mm:ss. */

export function parseClock(clock: string): number {
  const m = /^(\d+):(\d{2})$/.exec(clock.trim())
  if (!m) throw new Error(`not a mm:ss clock: "${clock}"`)
  return Number(m[1]) * 60 + Number(m[2])
}

export function parseClockRange(range: string): [number, number] {
  const parts = range.split('-')
  if (parts.length !== 2) throw new Error(`not a mm:ss-mm:ss range: "${range}"`)
  return [parseClock(parts[0]), parseClock(parts[1])]
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const mm = Math.floor(s / 60)
  const ss = s % 60
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}
