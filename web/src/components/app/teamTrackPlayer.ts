import type { TeamTrackClip } from '../../data/teamtrack'
import type { VideoSource } from './transport'

export function teamTrackClipIndex(clips: TeamTrackClip[], matchTimeS: number): number {
  const found = clips.findIndex((clip) => matchTimeS >= clip.start_s && matchTimeS < clip.end_s)
  return found >= 0 ? found : clips.length - 1
}

export function teamTrackClipLocalTime(clip: TeamTrackClip, matchTimeS: number): number {
  return Math.min(clip.end_s - clip.start_s, Math.max(0, matchTimeS - clip.start_s))
}

/** Seconds before a clip's end at which the next clip starts loading, at the latest. */
export const PRELOAD_LEAD_S = 12

/**
 * Start loading the next clip once the current one is fully buffered (no competition for the
 * connection), or at the latest `PRELOAD_LEAD_S` before the boundary.
 */
export function shouldPreloadNext(localTimeS: number, durationS: number, bufferedEndS: number): boolean {
  if (!Number.isFinite(durationS) || durationS <= 0) return false
  return bufferedEndS >= durationS - 0.25 || durationS - localTimeS <= PRELOAD_LEAD_S
}

function bufferedEnd(el: HTMLVideoElement): number {
  const ranges = el.buffered
  for (let i = 0; i < ranges.length; i++) {
    if (el.currentTime >= ranges.start(i) - 0.1 && el.currentTime <= ranges.end(i) + 0.1) return ranges.end(i)
  }
  return 0
}

/**
 * The recorded replay as one continuous video over its 30 s clips. With two `<video>` elements the
 * second one loads the next clip while the first plays, and they swap at the boundary (no new
 * request and no decoder start at 30 s). With one element it falls back to swapping `src`.
 */
export class TeamTrackVideoSource implements VideoSource {
  readonly offset: number
  readonly elements: HTMLVideoElement[]
  private readonly clips: TeamTrackClip[]
  private readonly onClip: (clip: TeamTrackClip) => void
  private readonly onError: (message: string) => void
  private readonly onActive: (slot: number) => void
  private slot = 0
  private index = 0
  /** clip index loaded (or loading) in the standby element; -1 = none */
  private standbyIndex = -1
  /** a clip whose preload failed; not retried (the boundary loads it the old way) */
  private failedPreload = -1
  private heldTime: number
  private ready = false
  private wantsPlay = false
  private rate = 1
  private disposed = false

  constructor(
    el: HTMLVideoElement | HTMLVideoElement[],
    clips: TeamTrackClip[],
    onClip: (clip: TeamTrackClip) => void,
    onError: (message: string) => void,
    onActive: (slot: number) => void = () => {},
  ) {
    if (!clips.length) throw new Error('The TeamTrack replay has no playable clips')
    this.elements = (Array.isArray(el) ? el : [el]).slice(0, 2)
    this.clips = clips
    this.onClip = onClip
    this.onError = onError
    this.onActive = onActive
    this.offset = clips[0].start_s
    this.heldTime = clips[0].start_s
    for (const video of this.elements) {
      video.addEventListener('loadedmetadata', this.handleMetadata)
      video.addEventListener('timeupdate', this.handleProgress)
      video.addEventListener('progress', this.handleProgress)
      video.addEventListener('ended', this.handleEnded)
      video.addEventListener('error', this.handleError)
    }
    this.show(0)
    this.loadClip(0, clips[0].start_s, false)
  }

  /** The element that is playing now (the other one, if any, preloads the next clip). */
  get el(): HTMLVideoElement {
    return this.elements[this.slot]
  }

  private get standby(): HTMLVideoElement | null {
    return this.elements.length > 1 ? this.elements[1 - this.slot] : null
  }

  now = () => {
    if (this.ready) {
      const clip = this.clips[this.index]
      return Math.min(clip.end_s, Math.max(clip.start_s, clip.start_s + this.el.currentTime))
    }
    return this.heldTime
  }

  seekMatch = (matchTimeS: number) => {
    const t = Math.min(this.clips.at(-1)!.end_s, Math.max(this.clips[0].start_s, matchTimeS))
    const next = this.indexFor(t)
    if (next !== this.index) {
      if (next === this.standbyIndex) this.swap(t)
      else this.loadClip(next, t, this.wantsPlay)
      return
    }
    this.heldTime = t
    if (this.ready) this.el.currentTime = teamTrackClipLocalTime(this.clips[next], t)
  }

  play = () => {
    this.wantsPlay = true
    if (this.ready) void this.el.play().catch(() => this.onError('The browser could not play this recorded clip.'))
  }

  pause = () => {
    this.heldTime = this.now()
    this.wantsPlay = false
    this.el.pause()
  }

  setRate = (rate: number) => {
    this.rate = rate
    for (const video of this.elements) video.playbackRate = rate
  }

  dispose = () => {
    this.disposed = true
    this.wantsPlay = false
    for (const video of this.elements) {
      video.pause()
      video.removeEventListener('loadedmetadata', this.handleMetadata)
      video.removeEventListener('timeupdate', this.handleProgress)
      video.removeEventListener('progress', this.handleProgress)
      video.removeEventListener('ended', this.handleEnded)
      video.removeEventListener('error', this.handleError)
    }
  }

  private indexFor(t: number) {
    return teamTrackClipIndex(this.clips, t)
  }

  /** Only the active element is visible; the standby stays transparent underneath. */
  private show(slot: number) {
    this.elements.forEach((video, i) => {
      video.style.opacity = i === slot ? '1' : '0'
    })
    this.onActive(slot)
  }

  private loadClip(index: number, matchTimeS: number, resume: boolean) {
    if (this.disposed) return
    const clip = this.clips[index]
    this.index = index
    this.heldTime = matchTimeS
    this.ready = false
    this.wantsPlay = resume
    this.el.pause()
    this.el.src = clip.url
    this.el.playbackRate = this.rate
    this.onClip(clip)
    this.el.load()
  }

  /** Make the standby element (already holding clip `standbyIndex`) the active one. */
  private swap(matchTimeS: number) {
    const previous = this.el
    this.slot = 1 - this.slot
    this.index = this.standbyIndex
    this.standbyIndex = -1
    const clip = this.clips[this.index]
    const el = this.el
    this.heldTime = matchTimeS
    el.playbackRate = this.rate
    this.ready = el.readyState >= 1
    if (this.ready) el.currentTime = teamTrackClipLocalTime(clip, matchTimeS)
    this.show(this.slot)
    this.onClip(clip)
    if (this.ready && this.wantsPlay) this.play()
    previous.pause()
  }

  private preloadNext() {
    const standby = this.standby
    const next = this.index + 1
    if (!standby || this.disposed || next >= this.clips.length || this.standbyIndex === next
        || this.failedPreload === next) return
    this.standbyIndex = next
    standby.preload = 'auto'
    standby.src = this.clips[next].url
    standby.playbackRate = this.rate
    standby.load()
  }

  private handleMetadata = (event: Event) => {
    if (this.disposed) return
    if (event.target !== this.el) return // the standby: it waits on its first frame
    const clip = this.clips[this.index]
    const localTime = teamTrackClipLocalTime(clip, this.heldTime)
    this.el.currentTime = localTime
    this.el.playbackRate = this.rate
    this.ready = true
    if (this.wantsPlay) this.play()
  }

  private handleProgress = (event: Event) => {
    if (!this.ready || this.disposed || event.target !== this.el) return
    if (event.type === 'timeupdate') this.heldTime = this.now()
    const el = this.el
    if (shouldPreloadNext(el.currentTime, el.duration, bufferedEnd(el))) this.preloadNext()
  }

  private handleEnded = (event: Event) => {
    if (event.target === this.el) this.advance()
  }

  private advance() {
    if (!this.ready || this.disposed) return
    if (this.index < this.clips.length - 1) {
      const next = this.index + 1
      if (this.standbyIndex === next) this.swap(this.clips[next].start_s)
      else this.loadClip(next, this.clips[next].start_s, this.wantsPlay)
      return
    }
    this.heldTime = this.clips.at(-1)!.end_s
    this.wantsPlay = false
    this.el.pause()
  }

  private handleError = (event: Event) => {
    if (this.disposed) return
    if (event.target !== this.el) {
      // a failed preload is not fatal: the boundary then loads the clip the old way
      this.failedPreload = this.standbyIndex
      this.standbyIndex = -1
      return
    }
    this.onError('This TeamTrack clip could not be decoded or loaded.')
  }
}
