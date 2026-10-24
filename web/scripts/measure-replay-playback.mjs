/* global document, window, HTMLVideoElement */
// Measures Live analysis replay playback under network throttling (Chrome DevTools "Fast 4G").
//
//   CHROMIUM_PATH=... BASE_URL=http://127.0.0.1:8011 node web/scripts/measure-replay-playback.mjs [label] [seconds]
//
// Starts the recorded TeamTrack replay at 1440x900, plays at 1x for `seconds` of wall time
// (default 75: crosses the 15:30 and 16:00 clip boundaries) and prints one JSON line:
// waiting / stalled events, total time spent waiting, dropped frames, time to first frame and,
// for each clip boundary, the wall-clock gap between the last frame of one clip and the first
// frame of the next (requestVideoFrameCallback presentation times).
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8011'
const executablePath = process.env.CHROMIUM_PATH
const label = process.argv[2] ?? 'run'
const seconds = Number(process.argv[3] ?? 75)
const throttle = process.env.THROTTLE !== 'off'
if (!executablePath) throw new Error('Set CHROMIUM_PATH to an installed Chrome, Chromium or Edge')

// Chrome DevTools "Fast 4G" preset (9 Mbit/s x 0.9 down, 1.5 Mbit/s x 0.9 up, 60 ms x 2.75 RTT)
const FAST_4G = { offline: false, latency: 165,
  downloadThroughput: (9_000_000 * 0.9) / 8, uploadThroughput: (1_500_000 * 0.9) / 8 }

const browser = await chromium.launch({ executablePath, headless: true,
  args: ['--autoplay-policy=no-user-gesture-required'] })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await context.addInitScript(() => {
    const log = []
    const frames = []
    window.__replayLog = log
    window.__replayFrames = frames
    const clipOf = (el) => /clips\/([0-9-]+)/.exec(el.currentSrc || el.src || '')?.[1] ?? null
    for (const type of ['waiting', 'stalled', 'playing', 'ended', 'loadstart', 'canplay', 'pause', 'play']) {
      document.addEventListener(type, (e) => {
        if (e.target instanceof HTMLVideoElement && e.target.matches('[data-replay-video], video[aria-label^="Recorded TeamTrack"]')) {
          log.push({ type, t: performance.now(), clip: clipOf(e.target), local: e.target.currentTime })
        }
      }, true)
    }
    const watched = new WeakSet()
    const watch = (el) => {
      if (watched.has(el)) return
      watched.add(el)
      const tick = (now, meta) => {
        // only frames the viewer can see (the hidden standby parks on its first frame)
        if (el.style.opacity !== '0') frames.push({ t: now, clip: clipOf(el), media: meta.mediaTime })
        el.requestVideoFrameCallback(tick)
      }
      el.requestVideoFrameCallback(tick)
    }
    setInterval(() => document.querySelectorAll('video').forEach(watch), 100)
  })
  const page = await context.newPage()
  const cdp = await context.newCDPSession(page)
  await cdp.send('Network.enable')
  // browser cache off, like DevTools with "Disable cache": every run starts cold
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })

  await page.goto(`${base}/app`)
  await page.getByRole('button', { name: 'Live analysis', exact: true }).click()
  await page.getByRole('dialog', { name: 'Set up Live analysis' }).waitFor()
  if (throttle) await cdp.send('Network.emulateNetworkConditions', FAST_4G)
  const t0 = await page.evaluate(() => performance.now())
  await page.getByRole('button', { name: 'Start recorded match analysis' }).click()
  await page.locator('video[aria-label^="Recorded TeamTrack"]').waitFor({ timeout: 60_000 })
  const rate1 = page.getByRole('button', { name: '1×' })
  if (await rate1.count()) await rate1.first().click()
  await page.waitForTimeout(seconds * 1000)

  const result = await page.evaluate((start) => {
    const log = window.__replayLog
    const frames = window.__replayFrames.slice().sort((a, b) => a.t - b.t)
    let waitingMs = 0
    let open = null
    for (const e of log) {
      if (e.type === 'waiting' && open === null) open = e.t
      if ((e.type === 'playing' || e.type === 'canplay') && open !== null) { waitingMs += e.t - open; open = null }
    }
    if (open !== null) waitingMs += performance.now() - open
    const boundaries = []
    for (let i = 1; i < frames.length; i++) {
      if (frames[i].clip !== frames[i - 1].clip && frames[i].clip && frames[i - 1].clip) {
        boundaries.push({ from: frames[i - 1].clip, to: frames[i].clip,
          gap_ms: Math.round(frames[i].t - frames[i - 1].t) })
      }
    }
    let worst = 0
    for (let i = 1; i < frames.length; i++) worst = Math.max(worst, frames[i].t - frames[i - 1].t)
    const videos = Array.from(document.querySelectorAll('video'))
    const quality = videos.reduce((acc, v) => {
      const q = v.getVideoPlaybackQuality()
      return { total: acc.total + q.totalVideoFrames, dropped: acc.dropped + q.droppedVideoFrames }
    }, { total: 0, dropped: 0 })
    const slider = document.querySelector('input[type="range"]')
    return {
      waiting_events: log.filter((e) => e.type === 'waiting').length,
      stalled_events: log.filter((e) => e.type === 'stalled').length,
      waiting_ms: Math.round(waitingMs),
      first_frame_ms: frames.length ? Math.round(frames[0].t - start) : null,
      frames_presented: frames.length,
      longest_frame_gap_ms: Math.round(worst),
      boundaries,
      dropped_frames: quality.dropped,
      decoded_frames: quality.total,
      match_time_end_s: slider ? Number(slider.value) : null,
      video_elements: videos.length,
      playback_rate: videos.map((v) => v.playbackRate)[0] ?? null,
    }
  }, t0)
  console.log(JSON.stringify({ label, throttle: throttle ? 'Fast 4G' : 'off', seconds, ...result }))
} finally {
  await browser.close()
}
