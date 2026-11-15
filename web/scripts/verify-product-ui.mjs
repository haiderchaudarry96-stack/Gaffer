/* global document, window */
// Review the connected local product UI without invoking the language model.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8017'
const out = resolve('../docs/startup/screenshots/post-deployment')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true })
const findings = []
try {
  for (const [width, height] of [[1440, 900], [768, 1024], [390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' })
    page.setDefaultTimeout(25_000)
    const errors = []
    const requests = []
    page.on('pageerror', (e) => errors.push(e.message))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('request', (r) => requests.push(r.url()))
    const shot = async (name) => page.screenshot({ path: resolve(out, `after-${name}-${width}.png`),
      fullPage: await page.locator('dialog[open]').count() === 0 })
    const fits = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2), 'no horizontal overflow')
    await page.goto(base)
    await page.locator('#hero-title').waitFor()
    await page.locator('#faq-title').waitFor()
    for (const [label, id] of [['Product', 'product'], ['How It Works', 'how'], ['Features', 'features'], ['Demo', 'demo'], ['FAQ', 'faq']]) {
      if (width < 768) {
        await page.getByRole('button', { name: 'Open menu', exact: true }).click()
        await page.locator('#mobile-menu').getByRole('link', { name: label, exact: true }).click()
      } else {
        await page.getByRole('navigation', { name: 'Main', exact: true }).getByRole('link', { name: label, exact: true }).click()
      }
      assert.equal(new URL(page.url()).hash, `#${id}`)
      assert.equal(await page.locator(`#${id}`).count(), 1)
    }
    await page.getByRole('button', { name: 'Can I connect a live camera?', exact: true }).focus()
    await page.keyboard.press('Enter')
    await page.getByText('The current version works with uploaded recordings and a recorded match replay.', { exact: false }).waitFor()
    for (let y = 0; y < await page.evaluate(() => document.body.scrollHeight); y += 700) {
      await page.evaluate((value) => window.scrollTo(0, value), y)
      await page.waitForTimeout(60)
    }
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.evaluate(() => document.fonts.ready)
    const text = await page.locator('body').innerText()
    assert.doesNotMatch(text, /cv2\.|EC2|CloudWatch|ap-southeast|uptime|calls today|97\.7%|98\.6%/i)
    assert(!requests.some((url) => url.includes('/api/runtime')), 'landing makes no monitoring request')
    await fits()
    await shot('landing')
    await page.getByRole('link', { name: 'Explore Gaffer', exact: true }).first().click()
    await page.getByRole('heading', { name: 'Start an analysis', exact: true }).waitFor()
    await fits()
    await shot('app')
    await page.getByRole('button', { name: 'Recorded analysis', exact: true }).click()
    await page.getByRole('dialog', { name: 'Set up recorded analysis' }).waitFor()
    assert(await page.evaluate(() => document.querySelector('dialog[open]')?.contains(document.activeElement)), 'setup receives focus')
    await shot('setup')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Upload your own video', exact: true }).click()
    await page.getByText('Drop a match video here', { exact: true }).waitFor()
    await shot('upload')
    await page.locator('#upload-file').setInputFiles(resolve('../data/sample_clips/teamtrack_top_sample_1080p.mp4'))
    const upload = page.getByRole('button', { name: 'Upload', exact: true })
    await upload.waitFor()
    await page.waitForFunction(() => document.activeElement?.textContent?.trim() === 'Upload')
    const bounds = await upload.boundingBox()
    assert(bounds && bounds.y >= 0 && bounds.y + bounds.height <= height, 'selected Upload is visible and focused')
    await shot('selected-file')
    await page.keyboard.press('Escape')
    await page.goto(`${base}/app?upload=1`)
    await page.getByRole('button', { name: 'Try this clip', exact: true }).first().click()
    await page.getByText('Video ready. Check the details and press Upload.', { exact: true }).waitFor()
    await page.waitForFunction(() => document.activeElement?.textContent?.trim() === 'Upload')
    await shot('sample-selected')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Review a completed analysis', exact: true }).click()
    await page.getByText('Completed analysis', { exact: true }).waitFor()
    await page.locator('article[aria-labelledby^="alert-"]').waitFor()
    await fits()
    await shot('review')
    await page.getByRole('button', { name: 'View coach report', exact: true }).click()
    await page.getByRole('dialog', { name: 'Coach report · recorded example' }).waitFor()
    await page.getByRole('heading', { name: 'Formation story', exact: true }).waitFor()
    await shot('report')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Ask Gaffer, your tactical analyst', exact: true }).click()
    await page.getByRole('button', { name: 'Close chat', exact: true }).waitFor()
    await shot('chat')
    await page.getByRole('button', { name: 'Close chat', exact: true }).click()
    await page.goto(`${base}/page-that-does-not-exist`)
    await page.getByText('That page does not exist.', { exact: true }).waitFor()
    await shot('not-found')
    await page.getByRole('link', { name: 'Back to Gaffer', exact: true }).click()
    await page.locator('#hero-title').waitFor()
    assert.deepEqual(errors, [])
    findings.push({ width, height, navigation: '5/5', consoleErrors: errors, screens: ['landing', 'idle', 'setup', 'upload', 'selected-file', 'review', 'report', 'chat', 'not-found'] })
    console.log(`PASS: ${width}x${height}; navigation, focus, upload visibility and all review screens`)
    await page.close()
  }
  await writeFile(resolve(out, 'ui-results.json'), JSON.stringify(findings, null, 2))
} finally {
  await browser.close()
}
