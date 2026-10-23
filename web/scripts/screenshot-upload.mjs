/* global document */
// Upload one video through the app UI, confirm the detected pitch, wait for the analysis and save
// screenshots of the pitch step and the result (generalisation session, 23 Oct).
//
//   python scripts/serve_no_bedrock.py --port 8011 --out outputs/api_zenodo_shot
//   node web/scripts/screenshot-upload.mjs <video.mp4> <out-dir>
//
// Env: BASE_URL (default http://127.0.0.1:8011), CHROMIUM_PATH (default: the local Chrome).
import { mkdirSync } from 'node:fs'
import { basename, resolve } from 'node:path'
import { chromium } from 'playwright-core'

const [video, outDir] = process.argv.slice(2)
if (!video || !outDir) throw new Error('usage: node screenshot-upload.mjs <video.mp4> <out-dir>')
mkdirSync(outDir, { recursive: true })
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8011'
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
const p = await ctx.newPage()
const problems = []
p.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text()}`) })
p.on('pageerror', (e) => problems.push(`page: ${e.message}`))
const shot = async (name) => {
  await p.waitForTimeout(400)
  await p.screenshot({ path: resolve(outDir, name) })
  log('screenshot', name)
}
await p.goto(`${BASE}/app?paused=1&upload=1`)
await p.locator('dialog[open]').waitFor()
await p.locator('#upload-file').setInputFiles(video)
await p.getByRole('button', { name: 'Upload', exact: true }).click()
await p.getByRole('heading', { name: 'Is this your pitch?' }).waitFor({ timeout: 180_000 })
await shot('1-is-this-your-pitch.png')
await p.getByRole('button', { name: 'Yes, looks right' }).click()
await p.getByRole('list', { name: 'Analysis progress' }).waitFor()
await p.locator('#match-select option', { hasText: basename(video) })
  .waitFor({ state: 'attached', timeout: 30 * 60_000 })
await p.locator('dialog[open]').waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {})
await p.waitForTimeout(2000)
await shot('2-result-desk.png')
// play the clip forward so the 2D pitch shows settled team labels, then a third screenshot
const names = await p.getByRole('button').allTextContents()
log('buttons:', JSON.stringify(names.filter((n) => n.trim()).slice(0, 30)))
const playBtn = p.getByRole('button', { name: /^play/i }).first()
if (await playBtn.count()) {
  await p.getByRole('button', { name: '4×' }).first().click().catch(() => {})
  await playBtn.click()
  await p.waitForTimeout(Number(process.env.PLAY_MS ?? 4500))
  await p.getByRole('button', { name: /^pause/i }).first().click().catch(() => {})
  await shot('3-result-mid-clip.png')
} else {
  log('no play button found; skipped the mid-clip screenshot')
}
const status = await p.evaluate(() => document.body.innerText.slice(0, 4000))
log('page text (start):', status.replace(/\s+/g, ' ').slice(0, 600))
log(problems.length ? `problems: ${problems.join(' | ')}` : 'no console or page errors')
await browser.close()
