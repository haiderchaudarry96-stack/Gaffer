// Renders the raster icons from web/public/favicon.svg (the logo master) with Edge/Chromium:
// favicon-16.png, favicon-32.png, apple-touch-icon.png (180 px, solid background, no rounded corners
// so iOS applies its own mask). CHROMIUM_PATH overrides the default Windows Edge install.
//   node web/scripts/render-icons.mjs
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const pub = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'public')
const svg = readFileSync(resolve(pub, 'favicon.svg'), 'utf8')
// iOS rounds the corners itself: the touch icon is the same drawing on a full-bleed square.
const square = svg.replace('rx="14"', 'rx="0"')
const uri = (s) => `data:image/svg+xml;base64,${Buffer.from(s).toString('base64')}`
const jobs = [
  ['favicon-16.png', 16, svg],
  ['favicon-32.png', 32, svg],
  ['apple-touch-icon.png', 180, square],
]
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
})
for (const [name, px, source] of jobs) {
  const page = await browser.newPage({ viewport: { width: px, height: px }, deviceScaleFactor: 1 })
  await page.setContent(`<style>html,body{margin:0;background:transparent}img{display:block}</style><img width="${px}" height="${px}" src="${uri(source)}">`)
  await page.screenshot({ path: resolve(pub, name), omitBackground: true })
  await page.close()
  console.log('wrote', name)
}
await browser.close()
