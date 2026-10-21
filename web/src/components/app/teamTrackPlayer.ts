import type { TeamTrackClip } from '../../data/teamtrack'
import type { VideoSource } from './transport'

export function teamTrackClipIndex(clips: TeamTrackClip[], matchTimeS: number): number {
  const found = clips.findIndex((clip) => matchTimeS >= clip.start_s && matchTimeS < clip.end_s)
  return found >= 0 ? found : clips.length - 1
}

export function teamTrackClipLocalTime(clip: TeamTrackClip, matchTimeS: number): number {
  return Math.min(clip.end_s - clip.start_s, Math.max(0, matchTimeS - clip.start_s))
}

export class TeamTrackVideoSource implements VideoSource {
  readonly el: HTMLVideoElement
  readonly offset: number
  private readonly clips: TeamTrackClip[]
  private readonly onClip: (clip: TeamTrackClip) => void
  private readonly onError: (message: string) => void
  private index = 0
  private heldTime: number
  private ready = false
  private wantsPlay = false
  private rate = 1
  private disposed = false

  constructor(
    el: HTMLVideoElement,
    clips: TeamTrackClip[],
    onClip: (clip: TeamTrackClip) => void,
    onError: (message: string) => void,
  ) {
    if (!clips.length) throw new Error('The TeamTrack replay has no playable clips')
    this.el = el
    this.clips = clips
    this.onClip = onClip
    this.onError = onError
    this.offset = clips[0].start_s
    this.heldTime = clips[0].start_s
    el.addEventListener('loadedmetadata', this.handleMetadata)
    el.addEventListener('timeupdate', this.handleTimeUpdate)
    el.addEventListener('ended', this.handleEnded)
    el.addEventListener('error', this.handleError)
    this.loadClip(0, clips[0].start_s, false)
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
      this.loadClip(next, t, this.wantsPlay)
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
    this.el.playbackRate = rate
  }

  dispose = () => {
    this.disposed = true
    this.wantsPlay = false
    this.el.pause()
    this.el.removeEventListener('loadedmetadata', this.handleMetadata)
    this.el.removeEventListener('timeupdate', this.handleTimeUpdate)
    this.el.removeEventListener('ended', this.handleEnded)
    this.el.removeEventListener('error', this.handleError)
  }

  private indexFor(t: number) {
    return teamTrackClipIndex(this.clips, t)
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

  private handleMetadata = () => {
    if (this.disposed) return
    const clip = this.clips[this.index]
    const localTime = teamTrackClipLocalTime(clip, this.heldTime)
    this.el.currentTime = localTime
    this.el.playbackRate = this.rate
    this.ready = true
    if (this.wantsPlay) this.play()
  }

  private handleTimeUpdate = () => {
    if (!this.ready || this.disposed) return
    this.heldTime = this.now()
  }

  private handleEnded = () => this.advance()

  private advance() {
    if (!this.ready || this.disposed) return
    if (this.index < this.clips.length - 1) {
      const next = this.index + 1
      this.loadClip(next, this.clips[next].start_s, this.wantsPlay)
      return
    }
    this.heldTime = this.clips.at(-1)!.end_s
    this.wantsPlay = false
    this.el.pause()
  }

  private handleError = () => {
    if (!this.disposed) this.onError('This TeamTrack clip could not be decoded or loaded.')
  }
}
