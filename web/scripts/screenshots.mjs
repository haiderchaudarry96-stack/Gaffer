/* global window, document */
// Screenshots (and a short scroll recording) with the pre-installed Chromium; no browser download.
// Usage: npm run build && npm run screenshots [filter...]
//        npm run screenshots -- --product   (only regenerates public/product/app-desk.jpg; rebuild after)
// Env: CHROMIUM_PATH (default /opt/pw-browsers/chromium-1194/chrome-linux/chrome), BASE_URL (skip the preview server).
import { spawn } from 'node:child_process'
import { spawnSync } from 'node:child_process'
import { mkdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { chromium } from 'playwright-core'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '..', 'screenshots')
mkdirSync(out, { recursive: true })
const executablePath = process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'
const args = process.argv.slice(2)
const productOnly = args.includes('--product')
const only = args.filter((a) => !a.startsWith('--'))

async function startPreview() {
  if (process.env.BASE_URL) return { url: process.env.BASE_URL, stop: () => {} }
  const port = 4317
  const vite = resolve(here, '..', 'node_modules', 'vite', 'bin', 'vite.js')
  const proc = spawn(process.execPath, [vite, 'preview', '--port', String(port), '--strictPort'], {
    cwd: resolve(here, '..'),
    stdio: ['ignore', 'pipe', 'inherit'],
  })
  await new Promise((ok, bad) => {
    const timer = setTimeout(() => bad(new Error('preview server did not start')), 20000)
    proc.stdout.on('data', (d) => {
      if (String(d).includes(String(port))) {
        clearTimeout(timer)
        ok()
      }
    })
  })
  return { url: `http://localhost:${port}`, stop: () => proc.kill() }
}

/** scroll through the page so every once-only reveal fires */
async function warmUp(page) {
  const h = await page.evaluate(() => document.body.scrollHeight)
  for (let y = 0; y < h; y += 400) {
    await page.evaluate((yy) => window.scrollTo(0, yy), y)
    await page.waitForTimeout(90)
  }
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await page.waitForTimeout(600)
}

const scrollToSel = (sel, offset = 0) => async (page) => {
  await page.evaluate(
    ([s, o]) => {
      const el = document.querySelector(s)
      window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY + o)
    },
    [sel, offset],
  )
}

const LANDING = (w, h, tag) => [
  { name: `landing-${tag}-1-hero`, path: '/', width: w, height: h, at: async (p) => p.evaluate(() => window.scrollTo(0, 0)) },
  { name: `landing-${tag}-2-light`, path: '/', width: w, height: h, at: scrollToSel('#desk-title', -h * 0.55) },
  { name: `landing-${tag}-3-bottom`, path: '/', width: w, height: h, at: async (p) => p.evaluate(() => window.scrollTo(0, document.body.scrollHeight)) },
]

const SHOTS = [
  ...LANDING(1440, 900, '1440'),
  ...LANDING(375, 812, '375'),
  { name: 'landing-1440-slider', path: '/', width: 1440, height: 900, at: scrollToSel('#compare', 40) },
  { name: 'landing-1440-story', path: '/', width: 1440, height: 900, at: scrollToSel('#verified', 900) },
  { name: 'landing-1440-1-hero-reduced-motion', path: '/', width: 1440, height: 900, reduced: true, at: async (p) => p.evaluate(() => window.scrollTo(0, 0)) },
  { name: 'app-1440-default', path: '/app?t=1000&paused=1', width: 1440, height: 900 },
  { name: 'app-1440-drawer', path: '/app?t=1000&paused=1&drawer=1', width: 1440, height: 900 },
  { name: 'app-1440-live-replay', path: '/app?live=1&t=1103&paused=1', width: 1440, height: 900 },
  { name: 'app-375-default', path: '/app?t=1000&paused=1', width: 375, height: 812, fullPage: true },
]


const server = await startPreview()
let browser
const errors = []
const watch = (page, name) => {
  page.on('console', (m) => m.type() === 'error' && errors.push(`${name}: ${m.text()}`))
  page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`))
}
try {
  browser = await chromium.launch({ executablePath })
  if (productOnly) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await ctx.newPage()
    watch(page, 'product')
    await page.goto(`${server.url}/app?t=1000&paused=1`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    const dest = resolve(here, '..', 'public', 'product', 'app-desk.jpg')
    await page.screenshot({ path: dest, type: 'jpeg', quality: 82 })
    console.log(`saved public/product/app-desk.jpg (${Math.round(statSync(dest).size / 1000)} kB)`)
    await ctx.close()
  } else {
    for (const s of SHOTS) {
      if (only.length && !only.some((o) => s.name.includes(o))) continue
      const ctx = await browser.newContext({
        viewport: { width: s.width, height: s.height },
        reducedMotion: s.reduced ? 'reduce' : 'no-preference',
      })
      const page = await ctx.newPage()
      watch(page, s.name)
      await page.goto(server.url + s.path, { waitUntil: 'networkidle' })
      if (s.path === '/') await warmUp(page)
      if (s.at) await s.at(page)
      await page.waitForTimeout(1400)
      await page.screenshot({ path: resolve(out, `${s.name}.png`), fullPage: !!s.fullPage })
      console.log(`saved screenshots/${s.name}.png`)
      await ctx.close()
    }
    if (!only.length || only.includes('video')) {
      // Scroll recording: Chrome screencast frames (CDP) encoded to WebM with the system ffmpeg.
      // Wheel events, so Lenis smooth-scrolls as it would for a visitor.
      const FPS = 25
      const tmp = join(out, '_frames')
      rmSync(tmp, { recursive: true, force: true })
      mkdirSync(tmp)
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } })
      const page = await ctx.newPage()
      watch(page, 'video')
      await page.goto(server.url + '/', { waitUntil: 'networkidle' })
      const cdp = await ctx.newCDPSession(page)
      const frames = []
      cdp.on('Page.screencastFrame', async (f) => {
        frames.push({ data: f.data, t: f.metadata.timestamp })
        await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {})
      })
      await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 80, maxWidth: 1280, maxHeight: 720 })
      await page.waitForTimeout(3000)
      await page.mouse.move(640, 400)
      for (let i = 0; i < 120; i++) {
        await page.mouse.wheel(0, 110)
        await page.waitForTimeout(120)
      }
      await page.waitForTimeout(1000)
      await cdp.send('Page.stopScreencast')
      await ctx.close()
      // constant frame rate: output frame k shows the last captured frame at time t0 + k / FPS
      let n = 0
      const t0 = frames[0].t
      for (let i = 0; i < frames.length; i++) {
        const until = Math.round(((frames[i + 1]?.t ?? frames[i].t + 1 / FPS) - t0) * FPS)
        const buf = Buffer.from(frames[i].data, 'base64')
        while (n < until) writeFileSync(join(tmp, `${String(n++).padStart(5, '0')}.jpg`), buf)
      }
      const dest = join(out, 'landing-scroll.webm')
      const ff = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', join(tmp, '%05d.jpg'), '-c:v', 'libvpx-vp9', '-b:v', '1500k', '-pix_fmt', 'yuv420p', dest])
      rmSync(tmp, { recursive: true, force: true })
      if (ff.status !== 0) throw new Error(`ffmpeg failed: ${ff.stderr}`)
      console.log(`saved screenshots/landing-scroll.webm (${(n / FPS).toFixed(1)} s, ${(statSync(dest).size / 1e6).toFixed(1)} MB)`)
    }
  }
} finally {
  await browser?.close()
  server.stop()
}
if (errors.length) {
  console.error('console errors:\n' + errors.join('\n'))
  process.exit(1)
}
console.log('no console errors')
process.exit(0)
