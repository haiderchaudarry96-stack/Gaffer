/* global document */
// End-to-end check of the combined app (one uvicorn serving web/dist + /api), with the
// pre-installed Chromium (no browser download). Screenshots -> screenshots/integrate/.
//
//   cd web && VITE_API_URL=/ npm run build && cd ..
//   python scripts/serve_no_bedrock.py --port 8000 --out <dir>      # or: uvicorn gaffer.api.main:app
//   node web/scripts/e2e-integrate.mjs <video-pitch-found.mp4> <video-pitch-unsure.mp4>
//
// The two videos are generated top-down matches, 960 x 600 (tests/videogen.py): the first has a
// pitch OpenCV finds (-> "Is this your pitch?"), the second worn markings it is unsure about
// (-> the 4-point screen); CORNERS are that pitch's corners in video pixels (TL, TR, BR, BL).
// Env: BASE_URL (default http://127.0.0.1:8000), CHROMIUM_PATH, CORNERS (JSON, 4 [x, y]).
// Fails on any console error, page error or failed request.
import { mkdirSync } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '..', 'screenshots', 'integrate')
mkdirSync(out, { recursive: true })
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8000'
const [videoFound, videoUnsure] = process.argv.slice(2)
if (!videoFound || !videoUnsure) throw new Error('usage: node e2e-integrate.mjs <video-pitch-found.mp4> <video-pitch-unsure.mp4>')
const CORNERS = JSON.parse(process.env.CORNERS ?? '[[90,70],[870,72],[868,540],[92,538]]')
const ANALYSIS_TIMEOUT = 15 * 60_000

const problems = []
const notes = []
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const check = (ok, what) => {
  if (!ok) throw new Error(`CHECK FAILED: ${what}`)
  log('ok:', what)
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' })

/** a fresh browser profile = a new visitor (own cookie jar) */
async function visitor(name) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
  const page = await ctx.newPage()
  const requests = []
  page.on('console', (m) => m.type() === 'error' && problems.push(`[${name}] console: ${m.text()}`))
  page.on('pageerror', (e) => problems.push(`[${name}] page error: ${e.message}`))
  page.on('requestfailed', (r) => {
    const msg = `[${name}] request failed: ${r.url()} ${r.failure()?.errorText}`
    // the browser's own preview of the chosen local file (blob:) is aborted when it cannot decode
    // the codec (generated clips are MPEG-4 Part 2); the upload goes ahead without a preview
    if (r.url().startsWith('blob:')) notes.push(msg)
    else problems.push(msg)
  })
  page.on('response', (r) => r.status() >= 400 && problems.push(`[${name}] HTTP ${r.status()} ${r.url()}`))
  page.on('request', (r) => requests.push(r.url()))
  return { ctx, page, requests }
}

const shot = async (page, name, opts = {}) => {
  await page.waitForTimeout(250)
  await page.screenshot({ path: resolve(out, name), ...opts })
  log('screenshot', name)
}
const alertCard = (page) => page.locator('article[aria-labelledby^="alert-"]')
const dialog = (page) => page.locator('dialog[open]')
const imageLoaded = (page, sel) => page.waitForFunction((s) => {
  const img = document.querySelector(s)
  return img && img.complete && img.naturalWidth > 0
}, sel, { timeout: 30_000 })

// ---------------------------------------------------------------- 1. demo from the API, per-visitor approval
const a = await visitor('visitor A')
await a.page.goto(`${BASE}/app?paused=1`)
await alertCard(a.page).waitFor({ timeout: 60_000 })
await a.page.getByText('waits for you').waitFor()
await imageLoaded(a.page, 'article[aria-labelledby^="alert-"] img')
const demoApi = a.requests.filter((u) => u.includes('/api/demo/'))
check(demoApi.some((u) => u.includes('/api/demo/files/')) && demoApi.some((u) => u.endsWith('/api/demo/alerts')), 'demo loaded from /api/demo/files/* and /api/demo/alerts')
check(!a.requests.some((u) => u.includes('/sample/')), 'no bundled /sample/ file requested')
await shot(a.page, '01-demo-loaded-from-api.png')

await alertCard(a.page).getByRole('button', { name: 'Approve' }).click()
await a.page.getByText(/You approved it at/).waitFor()
await shot(a.page, '02-visitor-a-approved.png')

const b = await visitor('visitor B')
await b.page.goto(`${BASE}/app?paused=1`)
await alertCard(b.page).waitFor({ timeout: 60_000 })
await b.page.getByText('waits for you').waitFor()
check((await alertCard(b.page).getByRole('button', { name: 'Approve' }).count()) === 1, 'visitor B still sees the demo alert pending')
await shot(b.page, '03-visitor-b-still-pending.png')

await a.page.reload()
await alertCard(a.page).waitFor({ timeout: 60_000 })
await a.page.getByText(/You approved it at/).waitFor()
check(true, 'visitor A still sees their approval after a reload (kept on the server, per visitor)')
await shot(a.page, '04-visitor-a-after-reload.png')
await b.ctx.close()

// ---------------------------------------------------------------- 2. upload: pitch found -> confirm -> analysis
const c = await visitor('coach upload')
const p = c.page
await p.goto(`${BASE}/app?paused=1&upload=1`)
await dialog(p).waitFor()
await p.locator('#upload-file').setInputFiles(videoFound)
await p.getByRole('button', { name: 'Upload', exact: true }).click()
await p.getByRole('heading', { name: 'Is this your pitch?' }).waitFor({ timeout: 120_000 })
await imageLoaded(p, '[data-testid="pitch-preview"]')
await shot(p, '05-needs-confirmation.png')

// "No, let me adjust" opens the 4-point screen preloaded with the found corners; back again
await p.getByRole('button', { name: 'No, let me adjust' }).click()
await p.getByRole('heading', { name: 'Show us where the pitch is' }).waitFor()
check((await p.getByRole('button', { name: /^Pitch corner \d of 4/ }).count()) === 4, '"No, let me adjust": 4 draggable points preloaded')
await imageLoaded(p, '[role="application"] img')
await shot(p, '06-adjust-preloaded-corners.png')
await p.getByRole('button', { name: 'Back' }).click()
await p.getByRole('heading', { name: 'Is this your pitch?' }).waitFor()

await p.getByRole('button', { name: 'Yes, looks right' }).click()
await p.getByRole('list', { name: 'Analysis progress' }).waitFor()
// a server stage past uploading, with its progress bar
await p.waitForFunction(() => /\d+ %/.test(document.querySelector('dialog[open] [aria-live="polite"]')?.textContent ?? ''), null, { timeout: 60_000 })
await shot(p, '07-progress.png')
log('waiting for the analysis (OpenCV pipeline + agent, rules arm)…')
await p.locator('#match-select option', { hasText: basename(videoFound) }).waitFor({ state: 'attached', timeout: ANALYSIS_TIMEOUT })
await dialog(p).waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {})
await alertCard(p).waitFor({ timeout: 30_000 })
await imageLoaded(p, 'article[aria-labelledby^="alert-"] img')
check((await p.locator('#match-select').inputValue()) !== 'w900_1260', 'the uploaded analysis replaced the demo')
await shot(p, '08-upload-result-desk.png')
await shot(p, '09-upload-result-desk-full.png', { fullPage: true })
await alertCard(p).getByRole('button', { name: 'Approve' }).click()
await p.getByText(/You approved it at/).waitFor()
await p.getByText('Saved on the analysis server.').waitFor()
await shot(p, '10-upload-alert-approved.png')

// ---------------------------------------------------------------- 3. upload: pitch unsure -> 4 clicks
await p.goto(`${BASE}/app?paused=1&upload=1`)
await dialog(p).waitFor()
await p.locator('#upload-file').setInputFiles(videoUnsure)
await p.getByRole('button', { name: 'Upload', exact: true }).click()
await p.getByRole('heading', { name: 'Show us where the pitch is' }).waitFor({ timeout: 120_000 })
await p.getByText(/We weren’t sure where the pitch is|We couldn’t find the pitch/).waitFor()
const frame = p.locator('[role="application"]')
await imageLoaded(p, '[role="application"] img')
await shot(p, '11-needs-corners-preloaded-guess.png')
if (await p.getByRole('button', { name: 'Reset' }).isEnabled()) await p.getByRole('button', { name: 'Reset' }).click()
const box = await frame.boundingBox()
const [vw, vh] = [960, 600]
for (const [x, y] of CORNERS) {
  await p.mouse.click(box.x + (x / vw) * box.width, box.y + (y / vh) * box.height)
  await p.waitForTimeout(150)
}
check((await p.getByRole('button', { name: /^Pitch corner \d of 4/ }).count()) === 4, 'needs_corners: 4 points placed with 4 clicks')
await p.mouse.move(box.x + 5, box.y + box.height + 40)
await shot(p, '12-needs-corners-four-clicks.png')
await p.getByRole('button', { name: 'Start analysis' }).click()
await p.getByRole('list', { name: 'Analysis progress' }).waitFor({ timeout: 60_000 })
await shot(p, '13-needs-corners-progress.png')
log('waiting for the second analysis…')
await p.locator('#match-select option', { hasText: basename(videoUnsure) }).waitFor({ state: 'attached', timeout: ANALYSIS_TIMEOUT })
await dialog(p).waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {})
await p.waitForTimeout(800)
await shot(p, '14-needs-corners-result-desk.png')

await browser.close()
if (notes.length) log(`note: ${notes.length} local preview request(s) aborted by the browser (codec it cannot decode; expected for generated clips)`)
if (problems.length) {
  console.error(`\n${problems.length} problem(s):\n${problems.join('\n')}`)
  process.exit(1)
}
log(`done: no console errors, page errors or failed requests; screenshots in ${out}`)
