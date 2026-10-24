// Logo check (24 Oct): landing header, /app header and the favicon "in a browser tab" at 1440 and 390 px.
// Headless Chromium has no tab strip, so the tab shot is a composite: a tab-shaped bar built from the
// page's real <title> and the favicon file the page actually links (fetched from the server), at 16 px
// x4 zoom next to the 1:1 size. The header shots are the real app.
//   py scripts/serve_no_bedrock.py --port 8013 --out outputs/api_no_bedrock_logo
//   node web/scripts/logo-screenshots.mjs [out-dir]        # default: web/screenshots/logo
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(process.argv[2] ?? resolve(here, '..', 'screenshots', 'logo'))
mkdirSync(out, { recursive: true })
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8013'
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
})
const problems = []
for (const [label, width, height] of [['1440', 1440, 900], ['390', 390, 844]]) {
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce', deviceScaleFactor: 2 })
  const p = await ctx.newPage()
  p.on('console', (m) => { if (m.type() === 'error') problems.push(`${label} console: ${m.text()}`) })
  p.on('pageerror', (e) => problems.push(`${label} page: ${e.message}`))
  await p.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(600)
  await p.screenshot({ path: resolve(out, `landing-header-${label}.png`), clip: { x: 0, y: 0, width, height: 96 } })
  const title = await p.title()
  const links = await p.$$eval('link[rel~="icon"], link[rel="apple-touch-icon"]', (ls) =>
    ls.map((l) => ({ rel: l.rel, href: l.href, sizes: l.getAttribute('sizes'), type: l.type })))
  const checked = []
  for (const l of links) {
    const r = await ctx.request.get(l.href)
    checked.push({ ...l, status: r.status(), bytes: (await r.body()).length })
  }
  console.log(label, 'title:', title)
  console.table(checked)
  const svgHref = links.find((l) => l.type === 'image/svg+xml').href
  await p.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(600)
  await p.screenshot({ path: resolve(out, `app-header-${label}.png`), clip: { x: 0, y: 0, width, height: 96 } })
  const tab = await ctx.newPage()
  await tab.setViewportSize({ width: Math.min(width, 520), height: 150 })
  await tab.setContent(`<style>
    body{margin:0;background:#202124;font:13px system-ui,sans-serif;color:#e8eaed}
    .strip{height:40px;display:flex;align-items:flex-end;padding:0 8px}
    .tab{display:flex;align-items:center;gap:8px;background:#35363a;border-radius:10px 10px 0 0;padding:0 14px;height:34px;max-width:260px}
    .tab span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .zoom{display:flex;gap:18px;align-items:center;padding:14px 16px;background:#35363a;color:#9aa0a6;font-size:12px}
    img{image-rendering:auto}
  </style>
  <div class="strip"><div class="tab"><img width="16" height="16" src="${svgHref}"><span>${title}</span></div></div>
  <div class="zoom"><span>16 px</span><img width="16" height="16" src="${svgHref}"><span>32 px</span><img width="32" height="32" src="${svgHref}"><span>64 px</span><img width="64" height="64" src="${svgHref}"></div>`)
  await tab.waitForTimeout(300)
  await tab.screenshot({ path: resolve(out, `favicon-tab-${label}.png`) })
  await ctx.close()
}
await browser.close()
console.log(problems.length ? `PROBLEMS:\n${problems.join('\n')}` : 'no console errors')
