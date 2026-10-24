// Screenshots for the README / Devpost (24 Oct): landing, upload step with both sample clips,
// the selected-file card, analysis progress, a finished result, the alert with its evidence, the
// chat, and the Zenodo result. Uses the real app against a server with Bedrock off, so the chat
// shot shows the honest off-topic refusal (answered in code, no AWS call).
//
//   py scripts/serve_no_bedrock.py --port 8012 --out outputs/api_no_bedrock_timing
//   node web/scripts/doc-screenshots.mjs [out-dir]        # default: docs/screenshots
//
// Env: BASE_URL (default http://127.0.0.1:8012), CHROMIUM_PATH (default: the local Chrome).
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(process.argv[2] ?? resolve(here, '..', '..', 'docs', 'screenshots'))
mkdirSync(out, { recursive: true })
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8012'
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
const p = await ctx.newPage()
const problems = []
p.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text()}`) })
p.on('pageerror', (e) => problems.push(`page: ${e.message}`))
const shot = async (name, opts = {}) => {
  await p.waitForTimeout(500)
  await p.screenshot({ path: resolve(out, name), ...opts })
  log('screenshot', name)
}

// 01 landing
await p.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await shot('01-landing.png')

/** choose a sample, upload it through the pitch step, wait for the finished result */
async function runSample(title, prefix, { progress = false } = {}) {
  await p.goto(`${BASE}/app?paused=1&upload=1`, { waitUntil: 'domcontentloaded' })
  await p.locator('dialog[open]').waitFor()
  await p.getByText('No video at hand? Try a sample clip').waitFor()
  if (prefix === '01') await shot('02-upload-samples.png')
  const card = p.locator('li', { hasText: title })
  await card.getByRole('button', { name: 'Try this clip' }).click()
  await p.getByText('Video ready. Check the details and press Upload.').waitFor({ timeout: 60_000 })
  await p.locator('img[alt="Video thumbnail"]').waitFor()
  if (prefix === '01') await shot('03-selected-file.png')
  await p.getByRole('button', { name: 'Upload', exact: true }).click()
  await p.getByRole('heading', { name: 'Is this your pitch?' }).waitFor({ timeout: 180_000 })
  await p.getByRole('button', { name: 'Yes, looks right' }).click()
  if (progress) {
    await p.getByRole('list', { name: 'Analysis progress' }).waitFor()
    await p.waitForTimeout(6000)
    await shot('04-analysis-progress.png')
  }
  await p.locator('dialog[open]').waitFor({ state: 'detached', timeout: 15 * 60_000 })
  await p.waitForTimeout(2500)
}

await runSample('The demo match (TeamTrack)', '01', { progress: true })
await shot('05-result.png')
await runSample('New ground (Zenodo)', '02')
await shot('08-zenodo-result.png')

// 06 the 16:30 alert with its evidence (the completed demo analysis)
await p.goto(`${BASE}/app?mode=review&paused=1`, { waitUntil: 'networkidle' })
await p.waitForTimeout(2500)
const aside = p.locator('aside[aria-label="Alert"]')
await aside.scrollIntoViewIfNeeded()
await shot('06-alert-evidence.png')

// 07 chat: an off-topic question is refused in code (no Bedrock call)
await p.getByRole('button', { name: /Ask Gaffer/ }).click()
await p.getByPlaceholder('Ask Gaffer about this analysis').fill('Who will win the match?')
await p.getByRole('button', { name: 'Send question' }).click()
await p.waitForTimeout(2500)
await shot('07-chat.png')

await browser.close()
if (problems.length) {
  console.log('PROBLEMS:\n' + problems.join('\n'))
  process.exitCode = 1
} else log('no console or page errors')
