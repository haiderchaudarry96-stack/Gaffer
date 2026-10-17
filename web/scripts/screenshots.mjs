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

const APP = '/app?t=1000&paused=1'
const UPLOAD = '/app?t=1000&paused=1&upload=1'

/** choose the test clip in the upload panel and wait for its details */
async function chooseClip(page) {
  await page.setInputFiles('#upload-file', TEST_CLIP)
  await page.getByRole('button', { name: 'Next' }).waitFor()
}
/** click the n-th pitch point at fractions of the frame */
async function placePoints(page, fractions) {
  const frame = page.getByRole('application')
  const box = await frame.boundingBox()
  for (const [fx, fy] of fractions) await page.mouse.click(box.x + fx * box.width, box.y + fy * box.height)
}
// where the synthetic clip's pitch outline is (see makeTestClip)
const CLIP_POINTS = [
  [0.3, 0.22],
  [0.7, 0.22],
  [0.94, 0.86],
  [0.06, 0.86],
]

const SHOTS = [
  ...LANDING(1440, 900, '1440'),
  ...LANDING(375, 812, '375'),
  { name: 'landing-1440-slider', path: '/', width: 1440, height: 900, at: scrollToSel('#compare', 40) },
  { name: 'landing-1440-story', path: '/', width: 1440, height: 900, at: scrollToSel('#verified', 900) },
  { name: 'landing-1440-1-hero-reduced-motion', path: '/', width: 1440, height: 900, reduced: true, at: async (p) => p.evaluate(() => window.scrollTo(0, 0)) },
  { name: 'app-1440-light', path: APP, width: 1440, height: 900 },
  { name: 'app-375-light', path: APP, width: 375, height: 812, fullPage: true },
  { name: 'app-1440-live-replay', path: '/app?live=1&t=1103&paused=1', width: 1440, height: 900 },
  { name: 'app-1440-drawer-details-closed', path: `${APP}&drawer=1`, width: 1440, height: 900, at: async (p) => p.getByRole('button', { name: 'Technical details' }).scrollIntoViewIfNeeded() },
  {
    name: 'app-1440-drawer-details-open',
    path: `${APP}&drawer=1`,
    width: 1440,
    height: 900,
    at: async (p) => {
      await p.getByRole('button', { name: 'Technical details' }).click()
      await p.getByText('Honest reading').scrollIntoViewIfNeeded()
    },
  },
  { name: 'chat-1440-closed', path: APP, width: 1440, height: 900, clip: 'bottom-right' },
  {
    name: 'chat-1440-expanded',
    path: APP,
    width: 1440,
    height: 900,
    at: async (p) => {
      await p.getByRole('button', { name: /Ask Gaffer/ }).hover()
      await p.waitForTimeout(700)
    },
  },
  { name: 'upload-1440-1-file-chosen', path: UPLOAD, width: 1440, height: 900, at: chooseClip },
  {
    name: 'upload-1440-2-pitch-step',
    path: UPLOAD,
    width: 1440,
    height: 900,
    at: async (p) => {
      await chooseClip(p)
      await p.getByRole('button', { name: 'Next' }).click()
      await placePoints(p, CLIP_POINTS.slice(0, 2))
      await p.getByRole('button', { name: /Pitch corner 2 of 4/ }).hover()
    },
  },
  {
    name: 'upload-375-2-pitch-step',
    path: UPLOAD,
    width: 375,
    height: 812,
    at: async (p) => {
      await chooseClip(p)
      await p.getByRole('button', { name: 'Next' }).click()
      await placePoints(p, CLIP_POINTS.slice(0, 1))
      await p.evaluate(() => document.querySelector('dialog[open] .overflow-y-auto')?.scrollTo(0, 0))
    },
  },
  {
    name: 'upload-1440-3-not-connected',
    path: UPLOAD,
    width: 1440,
    height: 900,
    at: async (p) => {
      await chooseClip(p)
      await p.getByRole('button', { name: 'Next' }).click()
      await placePoints(p, CLIP_POINTS)
      await p.getByRole('button', { name: 'Start analysis' }).click()
      await p.getByText('Analysis server not connected in this demo build').waitFor()
    },
  },
]


/**
 * A 6 s test clip for the upload screenshots: a synthetic tilted pitch drawn in the browser
 * (no match footage), encoded with the system ffmpeg. Written to node_modules/.cache.
 */
const TEST_CLIP = resolve(here, '..', 'node_modules', '.cache', 'gaffer_test_clip_0900_0930.mp4')
async function makeTestClip(browser) {
  mkdirSync(dirname(TEST_CLIP), { recursive: true })
  const png = TEST_CLIP.replace('.mp4', '.png')
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
  const stripes = Array.from({ length: 12 }, (_, i) => `<path d="M${384 + i * 43} 158 L${427 + i * 43} 158 L${77 + (i + 1) * 94} 619 L${77 + i * 94} 619 Z" fill="${i % 2 ? '#3f8a3a' : '#4a9a44'}"/>`).join('')
  await page.setContent(`<body style="margin:0"><svg width="1280" height="720" viewBox="0 0 1280 720">
    <rect width="1280" height="720" fill="#2f6b2c"/>${stripes}
    <g fill="none" stroke="#f4f4f0" stroke-width="4"><path d="M384 158 L896 158 L1203 619 L77 619 Z"/><path d="M640 158 L640 619"/>
    <ellipse cx="640" cy="360" rx="95" ry="48"/><path d="M330 240 L430 240 L360 450 L230 450"/><path d="M950 240 L850 240 L920 450 L1050 450"/></g>
    <text x="24" y="44" fill="#fff" font-family="sans-serif" font-size="22">Synthetic test clip for screenshots (not match footage)</text></svg></body>`)
  await page.screenshot({ path: png })
  await page.close()
  const ff = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-loop', '1', '-i', png, '-t', '6', '-r', '25', '-c:v', 'libvpx-vp9', '-b:v', '600k', '-pix_fmt', 'yuv420p', TEST_CLIP])
  if (ff.status !== 0) throw new Error(`ffmpeg failed: ${ff.stderr}`)
}

/** the mascot at 56 and 128 px, cut from the live page's chat button */
async function mascotShots(browser, url) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(url + APP, { waitUntil: 'networkidle' })
  const svg = await page.locator('button[aria-label^="Ask Gaffer"] svg').first().evaluate((el) => el.outerHTML)
  for (const size of [56, 128]) {
    await page.setContent(`<body style="margin:0;padding:16px;background:#fff;display:inline-block">${svg.replace(/width="\d+" height="\d+"/, `width="${size}" height="${size}"`)}</body>`)
    await page.locator('body').screenshot({ path: resolve(out, `mascot-${size}.png`) })
    console.log(`saved screenshots/mascot-${size}.png`)
  }
  await page.close()
}

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
    // the product shot should not show the first-visit hint dot on the upload button
    await ctx.addInitScript(() => localStorage.setItem('gaffer.uploadHintSeen', '1'))
    const page = await ctx.newPage()
    watch(page, 'product')
    await page.goto(`${server.url}/app?t=1000&paused=1`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    const dest = resolve(here, '..', 'public', 'product', 'app-desk.jpg')
    await page.screenshot({ path: dest, type: 'jpeg', quality: 82 })
    console.log(`saved public/product/app-desk.jpg (${Math.round(statSync(dest).size / 1000)} kB)`)
    await ctx.close()
  } else {
    if (!only.length || only.some((o) => 'upload'.includes(o) || o.includes('upload'))) await makeTestClip(browser)
    if (!only.length || only.some((o) => o.includes('mascot'))) await mascotShots(browser, server.url)
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
      const clip = s.clip === 'bottom-right' ? { x: s.width - 420, y: s.height - 300, width: 420, height: 300 } : undefined
      await page.screenshot({ path: resolve(out, `${s.name}.png`), fullPage: !!s.fullPage, clip })
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
