import { useEffect, useState } from 'react'
import type { PlaybackClock } from '../../lib/clock'

/** A loaded local video and the match second at which it starts. */
export interface VideoSource {
  el: HTMLVideoElement
  offset: number
}

/**
 * One play / pause / seek interface for the desk, whether the stored positions (clock) or a
 * local video drive the time. With a video, the clock follows video.currentTime + offset.
 */
export function useTransport(clock: PlaybackClock, video: VideoSource | null) {
  const [, force] = useState(0)

  useEffect(() => {
    const unsub = clock.subscribe(() => force((n) => n + 1))
    if (!video) return unsub
    const el = video.el
    const on = () => force((n) => n + 1)
    el.addEventListener('play', on)
    el.addEventListener('pause', on)
    el.addEventListener('ratechange', on)
    return () => {
      unsub()
      el.removeEventListener('play', on)
      el.removeEventListener('pause', on)
      el.removeEventListener('ratechange', on)
    }
  }, [clock, video])

  const playing = video ? !video.el.paused : clock.playing
  const rate = video ? video.el.playbackRate : clock.rate

  return {
    playing,
    rate,
    toggle() {
      if (video) {
        if (video.el.paused) void video.el.play()
        else video.el.pause()
      } else if (clock.playing) clock.pause()
      else clock.play()
    },
    seek(t: number) {
      if (video) seekVideo(video.el, Math.max(0, t - video.offset))
      else clock.seek(t)
    },
    setRate(r: number) {
      if (video) setVideoRate(video.el, r)
      else clock.setRate(r)
    },
  }
}

// DOM writes live outside the hook (the hooks linter treats hook arguments as immutable).
function seekVideo(el: HTMLVideoElement, seconds: number) {
  el.currentTime = seconds
}
function setVideoRate(el: HTMLVideoElement, rate: number) {
  el.playbackRate = rate
}

export type Transport = ReturnType<typeof useTransport>

/** TeamTrack clips are named <match>_<start s>_<end s>.mp4, e.g. D_20220220_1_0900_0930.mp4. */
export function offsetFromFileName(name: string): number | null {
  const m = /_(\d{3,4})_(\d{3,4})\.(mp4|webm|mov|mkv)$/i.exec(name)
  if (!m) return null
  const start = Number(m[1])
  const end = Number(m[2])
  return end > start ? start : null
}
