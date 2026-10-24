/* global document, window */
// Screenshots of the landing page's "Live on AWS" card, the AWS cards, the limits and the FAQ at
// 1440 and 390 px, from the real built site served by a Gaffer server (24 Oct).
//
//   py scripts/serve_no_bedrock.py --port 8013 --out outputs/api_no_bedrock_aws
//   node web/scripts/aws-section-shots.mjs [out-dir]        # default: web/screenshots/aws-truth
//
// Env: BASE_URL (default http://127.0.0.1:8013), CHROMIUM_PATH (default: the local Chrome).
// Off AWS the card shows "Not running on AWS"; on the EC2 server it shows the instance type.
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(process.argv[2] ?? resolve(here, '..', 'screenshots', 'aws-truth'))
mkdirSync(out, { recursive: true })
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8013'
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
})
const problems = []

for (const [w, h] of [[1440, 900], [390, 844]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' })
  const p = await ctx.newPage()
  p.on('console', (m) => m.type() === 'error' && problems.push(`${w}: ${m.text()}`))
  p.on('pageerror', (e) => problems.push(`${w}: ${e.message}`))
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  // scroll through so every once-only reveal fires
  const total = await p.evaluate(() => document.body.scrollHeight)
  for (let y = 0; y < total; y += 400) {
    await p.evaluate((yy) => window.scrollTo(0, yy), y)
    await p.waitForTimeout(60)
  }
  const card = p.getByTestId('live-on-aws')
  await card.waitFor()
  await p.waitForFunction(() => !document.querySelector('[data-testid=live-on-aws]')?.textContent?.includes('Reading the server'))
  await card.scrollIntoViewIfNeeded()
  await p.evaluate(() => window.scrollBy(0, -140))
  await p.waitForTimeout(500)
  await p.screenshot({ path: resolve(out, `landing-${w}-live-on-aws.png`) })
  console.log('landing live-on-aws', w, '->', (await card.innerText()).replace(/\s+/g, ' ').slice(0, 160))

  // the judge details, opened: the AWS cards and their small print
  await p.getByRole('button', { name: 'Open judge and technical details' }).click()
  const awsHeading = p.getByRole('heading', { name: 'Where AWS is used' })
  await awsHeading.scrollIntoViewIfNeeded()
  await p.waitForTimeout(500)
  await p.screenshot({ path: resolve(out, `landing-${w}-aws-cards.png`) })
  const tech = p.locator('#tech')
  await tech.getByRole('button', { name: 'Read the small print' }).click()
  await p.waitForTimeout(400)
  await tech.getByText('AWS (ap-southeast-2, Sydney)').scrollIntoViewIfNeeded()
  await p.screenshot({ path: resolve(out, `landing-${w}-aws-small-print.png`) })

  // limits (chip + small print)
  const limits = p.locator('#limits')
  await limits.getByRole('button', { name: 'Read the small print' }).click()
  await limits.scrollIntoViewIfNeeded()
  await p.waitForTimeout(500)
  await p.screenshot({ path: resolve(out, `landing-${w}-limits.png`) })

  // FAQ: "Is it live?", "What about player privacy?", "What does a match cost?"
  for (const q of ['Is it live?', 'What about player privacy?', 'What does a match cost?']) {
    await p.locator('#faq').getByRole('button', { name: q }).click()
  }
  await p.locator('#faq').getByRole('button', { name: 'Is it live?' }).scrollIntoViewIfNeeded()
  await p.waitForTimeout(500)
  await p.screenshot({ path: resolve(out, `landing-${w}-faq.png`) })
  if (w === 390) {
    await p.locator('#faq').getByRole('button', { name: 'What about player privacy?' }).scrollIntoViewIfNeeded()
    await p.waitForTimeout(300)
    await p.screenshot({ path: resolve(out, `landing-${w}-faq-privacy.png`) })
  }
  await ctx.close()
}
await browser.close()
console.log(problems.length ? `console problems:\n${problems.join('\n')}` : 'no console errors')
