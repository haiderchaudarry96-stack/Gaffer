/* global document, window, PopStateEvent */
// Checks that the idle "Waiting to start" pitch on /app moves on a FRESH, slow first load (the case
// that froze on phones) and after navigating away and back, at phone and desktop size; and that it
// stays still when the browser asks for reduced motion.
// Readings are taken without screenshots in between (a screenshot forces a frame and can hide a
// stalled animation); screenshots are saved afterwards.
// Usage: npm run build && node scripts/check-idle-animation.mjs [out-dir]
// Env: BASE_URL (skip the preview server), CHROMIUM_PATH (default: the local Chrome).
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(process.argv[2] ?? resolve(here, '..', 'screenshots', 'idle-animation'))
mkdirSync(out, { recursive: true })
// a slow mobile connection: the first load is where the dots froze
const SLOW = { offline: false, latency: 300, downloadThroughput: 200 * 1024, uploadThroughput: 100 * 1024 }

async function startPreview() {
  if (process.env.BASE_URL) return { url: process.env.BASE_URL, stop: () => {} }
  const port = 4319
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

/** Dot centres in screen px, plus how many dots carry an animation (SMIL or CSS). */
function probe(page) {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-decorative="true"] svg')
    const dots = [...svg.querySelectorAll('circle[r="1.3"]')]
    return {
      at: performance.now(),
      dots: dots.map((c) => {
        const r = c.getBoundingClientRect()
        return [r.x + r.width / 2, r.y + r.height / 2]
      }),
      animated: dots.filter((c) => c.querySelector('animateTransform') || c.getAnimations().length).length,
    }
  })
}

async function check(page, label) {
  await page.getByText('Waiting to start').waitFor({ timeout: 60000 })
  await page.waitForTimeout(500)
  const a = await probe(page)
  await page.waitForTimeout(1000)
  const b = await probe(page)
  const px = Math.max(...a.dots.map(([x, y], i) => Math.hypot(b.dots[i][0] - x, b.dots[i][1] - y)))
  const pitch = page.locator('[data-decorative="true"]')
  await pitch.screenshot({ path: resolve(out, `${label}-a.png`) })
  await page.waitForTimeout(1000)
  await pitch.screenshot({ path: resolve(out, `${label}-b.png`) })
  const moving = px > 0.05
  console.log(`${label.padEnd(30)} animated dots ${String(a.animated).padStart(2)}/${a.dots.length}  ` +
    `max dot move in ${((b.at - a.at) / 1000).toFixed(1)} s: ${px.toFixed(2).padStart(5)} px  => ${moving ? 'MOVING' : 'STILL'}`)
  return moving
}

const { url, stop } = await startPreview()
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
})
const results = {}
try {
  const sizes = {
    phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
    desktop: { viewport: { width: 1440, height: 900 } },
  }
  for (const [name, opts] of Object.entries(sizes)) {
    for (const reducedMotion of ['no-preference', 'reduce']) {
      const ctx = await browser.newContext({ ...opts, reducedMotion }) // fresh context: nothing cached
      const page = await ctx.newPage()
      const cdp = await ctx.newCDPSession(page)
      await cdp.send('Network.enable')
      await cdp.send('Network.emulateNetworkConditions', SLOW)
      const tag = `${name}-${reducedMotion === 'reduce' ? 'reduced' : 'motion'}`
      await page.goto(`${url}/app`, { waitUntil: 'commit' })
      results[`${tag} first load`] = await check(page, `${tag}-first-load`)
      // away to the landing page (client-side, as the app's links do) and back with the history
      await page.evaluate(() => {
        window.history.pushState({}, '', '/')
        window.dispatchEvent(new PopStateEvent('popstate'))
      })
      await page.getByText('Waiting to start').waitFor({ state: 'detached', timeout: 60000 })
      await page.goBack({ waitUntil: 'commit' })
      results[`${tag} away and back`] = await check(page, `${tag}-away-and-back`)
      await ctx.close()
    }
  }
} finally {
  await browser.close()
  stop()
}
const ok = Object.entries(results).every(([k, moving]) => (k.includes('reduced') ? !moving : moving))
console.log(ok ? 'PASS: moves with motion allowed (first load and away-and-back), still with reduced motion' : 'FAIL')
process.exit(ok ? 0 : 1)
