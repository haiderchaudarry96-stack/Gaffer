/**
 * A playback clock in match seconds. The pitch canvas reads `now()` every animation frame;
 * React UI subscribes at a lower rate (useClockTime). When a video drives playback,
 * `attachSource` makes the video's currentTime (plus an offset) the source of truth.
 */
export class PlaybackClock {
  private t: number
  private lastWall: number | null = null
  private source: (() => number) | null = null
  private listeners = new Set<() => void>()
  playing = false
  rate: number
  readonly min: number
  readonly max: number
  loop: boolean

  constructor(opts: { min: number; max: number; start?: number; rate?: number; loop?: boolean }) {
    this.min = opts.min
    this.max = opts.max
    this.t = opts.start ?? opts.min
    this.rate = opts.rate ?? 1
    this.loop = opts.loop ?? false
  }

  now(): number {
    if (this.source) return this.clamp(this.source())
    if (this.playing && this.lastWall !== null) {
      const wall = performance.now()
      this.t += ((wall - this.lastWall) / 1000) * this.rate
      this.lastWall = wall
      if (this.t >= this.max) {
        if (this.loop) this.t = this.min + (this.t - this.max)
        else {
          this.t = this.max
          this.pause()
        }
      }
    }
    return this.t
  }

  private clamp(t: number) {
    return Math.min(this.max, Math.max(this.min, t))
  }

  play() {
    if (this.source) return
    if (this.t >= this.max) this.t = this.min
    this.playing = true
    this.lastWall = performance.now()
    this.emit()
  }

  pause() {
    this.now()
    this.playing = false
    this.lastWall = null
    this.emit()
  }

  seek(t: number) {
    this.t = this.clamp(t)
    if (this.playing) this.lastWall = performance.now()
    this.emit()
  }

  setRate(rate: number) {
    this.now()
    this.rate = rate
    this.emit()
  }

  /** Make an external time source (e.g. a <video>) drive the clock; null detaches it. */
  attachSource(source: (() => number) | null) {
    if (!source && this.source) this.t = this.clamp(this.source())
    this.source = source
    this.playing = false
    this.lastWall = null
    this.emit()
  }

  get external() {
    return this.source !== null
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  emit() {
    for (const fn of this.listeners) fn()
  }
}
