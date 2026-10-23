/* global window, document, matchMedia */
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, statSync } from 'node:fs'
import { chromium } from 'playwright-core'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const web = resolve(here, '..')
const repo = resolve(web, '..')
const out = resolve(web, 'screenshots', 'upload-ux')
const cache = resolve(web, 'node_modules', '.cache')
const clip = resolve(cache, 'upload-ux-teamtrack-sample.mp4')
const source = resolve(repo, 'data', 'sample_clips', 'teamtrack_top_sample_1080p.mp4')
const vitePort = 4318
const browserPath = process.env.CHROMIUM_PATH ?? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

async function waitForThumbnail(page) {
  await page.locator('img[alt="Video thumbnail"]').waitFor()
  await page.waitForFunction(() => {
    const image = document.querySelector('img[alt="Video thumbnail"]')
    return image?.complete && image.naturalWidth > 0
  })
}

mkdirSync(out, { recursive: true })
mkdirSync(cache, { recursive: true })
if (!statSync(source).isFile()) throw new Error(`TeamTrack sample not found: ${source}`)
const encode = spawnSync('ffmpeg', [
  '-y', '-loglevel', 'error', '-i', source, '-t', '8', '-vf', 'scale=640:-2', '-an',
  '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30', '-movflags', '+faststart', clip,
], { encoding: 'utf8' })
if (encode.status !== 0) throw new Error(`Could not make the small Playwright sample: ${encode.stderr}`)

const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], {
  cwd: web,
  env: { ...process.env, VITE_API_URL: '/' },
  stdio: ['ignore', 'pipe', 'inherit'],
})
const url = `http://127.0.0.1:${vitePort}`
await new Promise((resolveReady, reject) => {
  const timer = setTimeout(() => reject(new Error('Vite dev server did not start')), 20000)
  vite.stdout.on('data', (chunk) => {
    if (String(chunk).includes(String(vitePort))) {
      clearTimeout(timer)
      resolveReady()
    }
  })
  vite.once('error', reject)
})

let browser
try {
  browser = await chromium.launch({ executablePath: browserPath })
  const bytes = statSync(clip).size
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const tag = String(viewport.width)
    const reduce = viewport.width === 390
    const context = await browser.newContext({ viewport, reducedMotion: reduce ? 'reduce' : 'no-preference' })
    const page = await context.newPage()
    await page.route('**/mock/teamtrack-sample.mp4', (route) =>
      route.fulfill({ path: clip, contentType: 'video/mp4', headers: { 'Access-Control-Allow-Origin': '*' } }),
    )
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (path === '/api/sample' && request.method() === 'GET') {
        return route.fulfill({ json: { available: true, label: 'Recorded TeamTrack sample', bytes,
          video_url: '/mock/teamtrack-sample.mp4', file_name: 'teamtrack_sample.mp4' } })
      }
      if (path === '/api/analyses' && request.method() === 'POST') {
        return route.fulfill({ status: 201, json: {
          id: 'an_upload_ux', status: 'needs_confirmation', stage: 'uploading', progress: 0,
          eta_s: null, agent_eta_s: null, error: null,
          video: { width: 640, height: 360, duration_s: 8 },
          pitch: { state: 'detected', corners: [[20, 20], [620, 20], [620, 340], [20, 340]],
            suggested_corners: null, preview_url: null, message: 'Pitch found.' },
        } })
      }
      if (path === '/api/analyses/sample' && request.method() === 'POST') {
        return route.fulfill({ status: 201, json: {
          id: 'an_sample_ux', status: 'needs_confirmation', stage: 'uploading', progress: 0,
          eta_s: null, agent_eta_s: null, error: null,
          video: { width: 640, height: 360, duration_s: 8 },
          pitch: { state: 'detected', corners: [[20, 20], [620, 20], [620, 340], [20, 340]],
            suggested_corners: null, preview_url: null, message: 'Pitch found.' },
        } })
      }
      if (path.endsWith('/pitch') && request.method() === 'POST') {
        return route.fulfill({ json: {
          id: path.includes('sample') ? 'an_sample_ux' : 'an_upload_ux', status: 'running', stage: 'detecting',
          progress: 0.35, eta_s: null, agent_eta_s: 246, error: null,
          video: { width: 640, height: 360, duration_s: 8 }, pitch: null,
        } })
      }
      if (/^\/api\/analyses\/[^/]+$/.test(path) && request.method() === 'GET') {
        return route.fulfill({ json: {
          id: path.includes('sample') ? 'an_sample_ux' : 'an_upload_ux', status: 'running', stage: 'detecting',
          progress: 0.58, eta_s: 142, agent_eta_s: 206, error: null,
          video: { width: 640, height: 360, duration_s: 8 }, pitch: null,
        } })
      }
      return route.fulfill({ status: 404, json: { detail: 'Not part of this mocked upload walkthrough.' } })
    })

    await page.goto(`${url}/app?upload=1`, { waitUntil: 'domcontentloaded' })
    await page.getByText('Drop a match video here').waitFor()
    await page.screenshot({ path: resolve(out, `before-${tag}.png`) })
    if (reduce && !(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches))) {
      throw new Error('390px context did not enable prefers-reduced-motion')
    }
    await page.locator('#upload-file').setInputFiles({
      name: 'teamtrack-local-check.mp4', mimeType: 'video/mp4', buffer: readFileSync(clip),
    })
    await page.getByText('Video ready. Check the details and press Upload.').waitFor()
    await waitForThumbnail(page)
    await page.screenshot({ path: resolve(out, `after-${tag}.png`) })

    const uploadButton = page.getByRole('button', { name: 'Upload', exact: true })
    const geometry = await uploadButton.evaluate((button) => {
      const r = button.getBoundingClientRect()
      return { top: r.top, bottom: r.bottom, focused: document.activeElement === button,
        inViewport: r.top >= 0 && r.bottom <= window.innerHeight }
    })
    if (!geometry.focused || !geometry.inViewport) throw new Error(`${tag}px selected-card check failed: ${JSON.stringify(geometry)}`)
    const guide = page.locator('dialog details')
    if (await guide.evaluate((el) => el.open)) throw new Error(`${tag}px footage guide was not collapsed`)
    await guide.locator('summary').click()
    if (!(await guide.evaluate((el) => el.open))) throw new Error(`${tag}px footage guide did not expand`)
    await guide.locator('summary').click()
    await page.getByText('Processing time depends on resolution and the server; the estimate appears once analysis starts.', { exact: true }).waitFor()
    await uploadButton.click()
    await page.getByRole('button', { name: 'Yes, looks right' }).click()
    await page.getByText('Server estimate appears after the first frames are measured.').waitFor()
    await page.getByText('Server estimate: about 2:22 remaining.').waitFor({ timeout: 5000 })
    await page.getByText('agent checks: up to 4 min').waitFor()
    await page.screenshot({ path: resolve(out, `analysis-eta-${tag}.png`) })
    console.log(`${tag}px: local file selected, card in viewport, Upload focused, guidance collapsed, before and measured ETA states verified${reduce ? ', reduced motion enabled' : ''}`)
    await context.close()
  }

  const sampleContext = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' })
  const samplePage = await sampleContext.newPage()
  const sampleBytes = statSync(clip).size
  await samplePage.route('**/mock/teamtrack-sample.mp4', (route) =>
    route.fulfill({ path: clip, contentType: 'video/mp4', headers: { 'Access-Control-Allow-Origin': '*' } }),
  )
  await samplePage.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/sample') return route.fulfill({ json: { available: true, label: 'Recorded TeamTrack sample',
      bytes: sampleBytes, video_url: '/mock/teamtrack-sample.mp4', file_name: 'teamtrack_sample.mp4' } })
    if (path === '/api/analyses/sample' && route.request().method() === 'POST') {
      return route.fulfill({ status: 201, json: { id: 'an_sample_ux', status: 'needs_confirmation', stage: 'uploading',
        progress: 0, eta_s: null, agent_eta_s: null, error: null, video: { width: 640, height: 360, duration_s: 8 },
        pitch: { state: 'detected', corners: [[20, 20], [620, 20], [620, 340], [20, 340]], suggested_corners: null,
          preview_url: null, message: 'Pitch found.' } } })
    }
    if (path.endsWith('/pitch') && route.request().method() === 'POST') {
      return route.fulfill({ json: { id: 'an_sample_ux', status: 'running', stage: 'detecting', progress: 0.35,
        eta_s: null, agent_eta_s: 246, error: null, video: { width: 640, height: 360, duration_s: 8 }, pitch: null } })
    }
    if (/^\/api\/analyses\/[^/]+$/.test(path) && route.request().method() === 'GET') {
      return route.fulfill({ json: { id: 'an_sample_ux', status: 'running', stage: 'detecting', progress: 0.58,
        eta_s: 142, agent_eta_s: 206, error: null, video: { width: 640, height: 360, duration_s: 8 }, pitch: null } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Not part of this mocked sample walkthrough.' } })
  })
  await samplePage.goto(`${url}/app?upload=1`, { waitUntil: 'domcontentloaded' })
  await samplePage.getByRole('button', { name: 'Try it with a sample clip' }).click()
  await samplePage.getByText('Video ready. Check the details and press Upload.').waitFor()
  await waitForThumbnail(samplePage)
  const sampleUpload = samplePage.getByRole('button', { name: 'Upload', exact: true })
  const sampleGeometry = await sampleUpload.evaluate((button) => {
    const r = button.getBoundingClientRect()
    return { top: r.top, bottom: r.bottom, focused: document.activeElement === button,
      inViewport: r.top >= 0 && r.bottom <= window.innerHeight }
  })
  if (!sampleGeometry.focused || !sampleGeometry.inViewport) throw new Error(`390px sample card check failed: ${JSON.stringify(sampleGeometry)}`)
  await samplePage.screenshot({ path: resolve(out, 'sample-after-390.png') })
  await sampleUpload.click()
  await samplePage.getByRole('button', { name: 'Yes, looks right' }).click()
  await samplePage.getByText('Server estimate: about 2:22 remaining.').waitFor({ timeout: 5000 })
  await samplePage.screenshot({ path: resolve(out, 'sample-analysis-eta-390.png') })
  console.log('390px sample clip: selected and uploaded through mocked sample API; measured ETA displayed')
  await sampleContext.close()
} finally {
  await browser?.close()
  vite.kill()
}
