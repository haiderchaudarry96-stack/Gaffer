// UI acceptance fixtures: no video analysis or model call is made by this script.
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright-core'
const base = process.env.BASE_URL ?? 'http://127.0.0.1:8017'
const out = resolve('../docs/startup/screenshots/post-deployment')
await mkdir(out, { recursive: true })
const demo = await (await fetch(`${base}/api/demo`)).json()
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true })
try {
  for (const [width, height] of [[1440, 900], [390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' })
    page.setDefaultTimeout(25000)
    let phase = 'running'
    let refused = false
    const id = 'abcdef123456'
    const status = (state) => ({ id, status: state, stage: state === 'done' ? 'done' : 'detecting', progress: state === 'done' ? 1 : 0.5,
      eta_s: state === 'running' ? 142 : null, agent_eta_s: state === 'running' ? 206 : null, error: null,
      video: { width: 1920, height: 1080, duration_s: 30 }, pitch: null })
    await page.route('**/api/analyses**', async (route) => {
      const r = route.request()
      const path = new URL(r.url()).pathname
      if (path.endsWith('/frame')) return route.fulfill({ path: resolve('public/product/evt003-after.jpg'), contentType: 'image/jpeg' })
      if (path === '/api/analyses' && r.method() === 'POST') {
        if (refused) return route.fulfill({ status: 503, json: { detail: 'The server is busy. Please try again shortly.' } })
        return route.fulfill({ status: 201, json: { ...status('needs_confirmation'), stage: 'uploading', progress: 0,
          pitch: { state: 'detected', corners: [[90, 70], [1830, 70], [1830, 1000], [90, 1000]],
            suggested_corners: null, preview_url: `${base}/product/evt003-after.jpg`, message: 'Check the pitch outline.' } } })
      }
      if (path.endsWith('/pitch')) return route.fulfill({ json: status('running') })
      if (path.endsWith('/result')) return route.fulfill({ json: { ...demo, id, label: 'UI acceptance fixture' } })
      if (path === `/api/analyses/${id}`) return route.fulfill({ json: status(phase) })
      return route.continue()
    })
    const choose = async () => {
      await page.goto(`${base}/app?upload=1&paused=1`)
      await page.locator('#upload-file').setInputFiles(resolve('../data/sample_clips/teamtrack_top_sample_1080p.mp4'))
      await page.getByRole('button', { name: 'Upload', exact: true }).click()
    }
    const shot = async (name) => page.screenshot({ path: resolve(out, `fixture-${name}-${width}.png`),
      fullPage: await page.locator('dialog[open]').count() === 0 })
    await choose()
    await page.getByRole('button', { name: 'Yes, looks right', exact: true }).waitFor()
    await shot('pitch-confirm')
    await page.getByRole('button', { name: 'No, let me adjust', exact: true }).click()
    await page.getByRole('button', { name: 'Start analysis', exact: true }).waitFor()
    await shot('pitch-adjust')
    await page.getByRole('button', { name: 'Start analysis', exact: true }).click()
    await page.getByText('Server estimate: about 2:22 remaining.', { exact: true }).waitFor()
    await page.getByText('agent checks: up to 4 min', { exact: true }).waitFor()
    await shot('progress')
    phase = 'done'
    await page.getByText('Completed analysis', { exact: true }).waitFor()
    await page.getByLabel('Match', { exact: true }).waitFor()
    await shot('upload-result')
    refused = true
    await choose()
    await page.getByRole('alert').getByText('The server is busy. Please try again shortly.', { exact: false }).waitFor()
    await shot('upload-error')
    assert((await page.getByRole('alert').innerText()).includes('Back'), 'the failure gives a recovery action')
    console.log(`PASS: ${width}x${height} mocked pitch confirmation/adjustment, measured ETA, result and busy error`)
    await page.close()
  }
} finally { await browser.close() }
