/* global document */
// Renders the social preview image web/public/og-image.png (1200 x 630) with Edge/Chromium:
// logo (public/favicon.svg), headline, and the evidence panel of the 16:30 change
// (public/product/evt003-after.jpg, the OpenCV-drawn "after" shape panel). Fonts come from the installed @fontsource packages.
//   node web/scripts/render-og.mjs      (CHROMIUM_PATH overrides the default Windows Edge install)
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { chromium } from 'playwright-core'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const url = (p) => pathToFileURL(resolve(root, p)).href
const logo = readFileSync(resolve(root, 'public/favicon.svg'), 'utf8').replace('<title>Gaffer</title>', '')
const html = `<!doctype html><meta charset="utf-8"><style>
@font-face{font-family:SG;src:url("${url('node_modules/@fontsource-variable/space-grotesk/files/space-grotesk-latin-wght-normal.woff2')}");font-weight:300 700}
@font-face{font-family:IN;src:url("${url('node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2')}");font-weight:100 900}
*{box-sizing:border-box}
body{margin:0;width:1200px;height:630px;overflow:hidden;font-family:IN,sans-serif;color:#eef4f0;
 background:radial-gradient(900px 520px at 85% 10%,rgba(200,245,66,.16),transparent 60%),radial-gradient(700px 500px at 0% 100%,rgba(68,200,255,.12),transparent 60%),#070d0a}
.wrap{display:grid;grid-template-columns:560px 1fr;gap:44px;height:100%;padding:64px 64px 56px}
.brand{display:flex;align-items:center;gap:18px}
.brand svg{width:84px;height:84px}
.brand b{font:700 54px SG,sans-serif;letter-spacing:-.02em}
h1{font:700 52px/1.08 SG,sans-serif;letter-spacing:-.02em;margin:46px 0 22px}
h1 span{background:linear-gradient(90deg,#c8f542,#7be39a);-webkit-background-clip:text;color:transparent}
p{font-size:23px;line-height:1.45;color:#a9b9af;margin:0}
.tags{position:absolute;left:64px;bottom:52px;display:flex;gap:12px;font:600 17px IN,sans-serif}
.tags i{font-style:normal;padding:9px 16px;border-radius:999px;border:1px solid rgba(238,244,240,.22);background:rgba(255,255,255,.06);color:#dfe9e2}
.card{align-self:center;border-radius:26px;padding:14px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.18);box-shadow:0 30px 80px rgba(0,0,0,.5)}
.card img{display:block;width:100%;height:330px;object-fit:cover;border-radius:16px}
.chip{display:flex;gap:10px;align-items:center;margin:14px 6px 4px;font:600 19px IN,sans-serif}
.chip em{font-style:normal;font-size:14px;letter-spacing:.08em;padding:6px 11px;border-radius:999px;background:rgba(200,245,66,.16);border:1px solid rgba(200,245,66,.55);color:#c8f542}
.chip span{color:#a9b9af;margin-left:auto;font-weight:500}
</style><div class="wrap"><div><div class="brand">${logo}<b>Gaffer</b></div>
<h1>The tactical analyst that <span>checks its own eyes</span> before it speaks.</h1>
<p>Spots the moment a team changes shape, looks again with OpenCV 5, then asks the coach.</p></div>
<div class="card"><img src="${url('public/product/evt003-after.jpg')}"><div class="chip"><em>VERIFIED</em>White switched to 3-4-3<span>16:30</span></div></div>
<div class="tags"><i>OpenCV 5</i><i>Amazon Bedrock</i><i>For grassroots coaches</i></div></div>`
const dir = mkdtempSync(join(tmpdir(), 'gaffer-og-'))
const file = join(dir, 'og.html')
writeFileSync(file, html)
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
})
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 })
await page.goto(pathToFileURL(file).href)
await page.evaluate(() => document.fonts.ready)
await page.waitForTimeout(400)
await page.screenshot({ path: resolve(root, 'public/og-image.png') })
await browser.close()
console.log('wrote public/og-image.png')
