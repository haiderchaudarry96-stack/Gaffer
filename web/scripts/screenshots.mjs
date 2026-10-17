/* global window, document */
// Takes the Phase 4 checkpoint screenshots with the pre-installed Chromium (no browser download).
// Usage: npm run build && npm run screenshots   (serves dist/ with `vite preview` on a free port)
// Env: CHROMIUM_PATH (default /opt/pw-browsers/chromium-1194/chrome-linux/chrome), BASE_URL (skip the preview server).
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '..', 'screenshots')
mkdirSync(out, { recursive: true })
const executablePath = process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'
const only = process.argv.slice(2)

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

const SHOTS = [
  { name: 'landing-1440', path: '/', width: 1440, height: 900, fullPage: true },
  { name: 'landing-375', path: '/', width: 375, height: 812, fullPage: true },
  { name: 'app-1440', path: '/app', width: 1440, height: 900, fullPage: true },
  { name: 'app-375', path: '/app', width: 375, height: 812, fullPage: true },
]

const server = await startPreview()
const browser = await chromium.launch({ executablePath })
const errors = []
try {
  for (const reduced of [false, true]) {
    for (const s of SHOTS) {
      const name = `${s.name}${reduced ? '-reduced-motion' : ''}`
      if (only.length && !only.some((o) => name.includes(o))) continue
      const ctx = await browser.newContext({
        viewport: { width: s.width, height: s.height },
        deviceScaleFactor: 1,
        reducedMotion: reduced ? 'reduce' : 'no-preference',
      })
      const page = await ctx.newPage()
      page.on('console', (m) => m.type() === 'error' && errors.push(`${name}: ${m.text()}`))
      page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`))
      await page.goto(server.url + s.path, { waitUntil: 'networkidle' })
      if (s.fullPage) {
        // scroll through so every scroll-reveal fires, then back to the top
        const h = await page.evaluate(() => document.body.scrollHeight)
        for (let y = 0; y < h; y += 300) {
          await page.evaluate((yy) => window.scrollTo(0, yy), y)
          await page.waitForTimeout(150)
        }
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
        await page.waitForTimeout(800)
        await page.evaluate(() => window.scrollTo(0, 0))
      }
      await page.waitForTimeout(1500)
      await page.screenshot({ path: resolve(out, `${name}.png`), fullPage: s.fullPage })
      console.log(`saved screenshots/${name}.png`)
      await ctx.close()
    }
  }
} finally {
  await browser.close()
  server.stop()
}
if (errors.length) {
  console.error('console errors:\n' + errors.join('\n'))
  process.exit(1)
}
console.log('no console errors')
process.exit(0)
