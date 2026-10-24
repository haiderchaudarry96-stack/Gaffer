import { describe, expect, it } from 'vitest'
import type { TeamTrackClip } from '../../data/teamtrack'
import { PRELOAD_LEAD_S, TeamTrackVideoSource, shouldPreloadNext } from './teamTrackPlayer'

/** Just enough of an HTMLVideoElement for the player (node test environment, no DOM). */
class FakeVideo extends EventTarget {
  src = ''
  preload = 'metadata'
  currentTime = 0
  duration = 30.03
  playbackRate = 1
  paused = true
  readyState = 0
  loads = 0
  style = { opacity: '' }
  bufferedEnd = 0
  get buffered() {
    const end = this.bufferedEnd
    return { length: end > 0 ? 1 : 0, start: () => 0, end: () => end }
  }
  load() { this.loads += 1; this.readyState = 0 }
  play() { this.paused = false; return Promise.resolve() }
  pause() { this.paused = true }
  emit(type: string) { this.dispatchEvent(new Event(type)) }
  ready() { this.readyState = 4; this.emit('loadedmetadata') }
}

const clips: TeamTrackClip[] = Array.from({ length: 3 }, (_, i) => ({
  id: `${900 + i * 30}-${930 + i * 30}`, start_s: 900 + i * 30, end_s: 930 + i * 30, url: `/clip/${i}`,
}))

const make = () => {
  const a = new FakeVideo()
  const b = new FakeVideo()
  const shown: string[] = []
  const slots: number[] = []
  const src = new TeamTrackVideoSource([a, b] as unknown as HTMLVideoElement[], clips,
    (clip) => shown.push(clip.id), () => {}, (slot) => slots.push(slot))
  return { a, b, src, shown, slots }
}

describe('replay preload decision', () => {
  it('waits until the clip is fully buffered or the boundary is near', () => {
    expect(shouldPreloadNext(2, 30, 10)).toBe(false)
    expect(shouldPreloadNext(2, 30, 30)).toBe(true)
    expect(shouldPreloadNext(30 - PRELOAD_LEAD_S, 30, 20)).toBe(true)
    expect(shouldPreloadNext(5, Number.NaN, 0)).toBe(false)
  })
})

describe('double-buffered replay player', () => {
  it('preloads the next clip in the hidden element and swaps at the boundary without a new load', () => {
    const { a, b, src, shown, slots } = make()
    expect(a.src).toBe('/clip/0')
    expect(b.style.opacity).toBe('0')
    a.ready()
    src.play()
    expect(a.paused).toBe(false)
    expect(b.src).toBe('') // nothing preloaded while the first clip still downloads

    a.currentTime = 3
    a.bufferedEnd = 30.03
    a.emit('progress')
    expect(b.src).toBe('/clip/1')
    expect(b.preload).toBe('auto')
    b.ready()
    expect(b.paused).toBe(true) // the standby waits on its first frame

    a.currentTime = 30.03
    a.emit('ended')
    expect(src.el).toBe(b)
    expect(b.paused).toBe(false)
    expect(b.loads).toBe(1) // the swap itself starts no new load
    expect(b.style.opacity).toBe('1')
    expect(a.style.opacity).toBe('0')
    expect(shown).toEqual(['900-930', '930-960'])
    expect(slots.at(-1)).toBe(1)
    b.currentTime = 1.5
    expect(src.now()).toBeCloseTo(931.5)
  })

  it('falls back to loading in place when the next clip was not preloaded', () => {
    const { a, b, src } = make()
    a.ready()
    src.play()
    a.currentTime = 2
    a.emit('ended')
    expect(src.el).toBe(a)
    expect(a.src).toBe('/clip/1')
    expect(b.src).toBe('')
  })

  it('a seek into the preloaded clip uses the standby; rate applies to both elements', () => {
    const { a, b, src } = make()
    a.ready()
    a.bufferedEnd = 30.03
    a.emit('progress')
    b.ready()
    src.setRate(2)
    src.seekMatch(940)
    expect(src.el).toBe(b)
    expect(b.currentTime).toBe(10)
    expect(a.playbackRate).toBe(2)
    expect(b.playbackRate).toBe(2)
  })

  it('a failed preload is not fatal and not retried', () => {
    const errors: string[] = []
    const a = new FakeVideo()
    const b = new FakeVideo()
    const src = new TeamTrackVideoSource([a, b] as unknown as HTMLVideoElement[], clips, () => {},
      (m) => errors.push(m))
    a.ready()
    a.bufferedEnd = 30.03
    a.emit('progress')
    b.emit('error')
    b.src = ''
    a.emit('progress')
    expect(b.src).toBe('')
    expect(errors).toEqual([])
    expect(src.el).toBe(a)
  })
})
