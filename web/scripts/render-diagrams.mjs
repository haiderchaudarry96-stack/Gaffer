/* global document */
// Renders the three product diagrams (dark + light) from docs/diagrams/diagrams.mjs:
//   docs/diagrams/{architecture,agent_workflow,use_cases}[_light].svg   (editable, Figma-importable)
//   docs/{architecture,agent_workflow,use_cases}[_light].png            (3840 x 2160, Playwright at 2x)
// Fonts come from the installed @fontsource packages (the site's fonts). Text that overflows its box is reported.
//   node web/scripts/render-diagrams.mjs        (CHROMIUM_PATH overrides the default Windows Edge install)
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { chromium } from 'playwright-core'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const docs = resolve(root, '../docs')
const { DIAGRAMS, THEMES } = await import(pathToFileURL(resolve(docs, 'diagrams/diagrams.mjs')).href)

const fontUrl = (p) => pathToFileURL(resolve(root, 'node_modules/@fontsource-variable', p)).href
const fonts = `
@font-face{font-family:"Space Grotesk";src:url("${fontUrl('space-grotesk/files/space-grotesk-latin-wght-normal.woff2')}");font-weight:300 700}
@font-face{font-family:"Inter";src:url("${fontUrl('inter/files/inter-latin-wght-normal.woff2')}");font-weight:100 900}
@font-face{font-family:"JetBrains Mono";src:url("${fontUrl('jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2')}");font-weight:100 800}`

mkdirSync(resolve(docs, 'diagrams'), { recursive: true })
const tmp = mkdtempSync(join(tmpdir(), 'gaffer-diagrams-'))
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
})
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 })
let problems = 0

for (const d of DIAGRAMS) {
  for (const t of [THEMES.dark, THEMES.light]) {
    const suffix = t.name === 'light' ? '_light' : ''
    const svg = d.build(t)
    writeFileSync(resolve(docs, 'diagrams', `${d.name}${suffix}.svg`), svg)
    const file = join(tmp, `${d.name}${suffix}.html`)
    writeFileSync(file, `<!doctype html><meta charset="utf-8"><style>${fonts}html,body{margin:0;background:${t.bg}}svg{display:block}</style>${svg}`)
    await page.goto(pathToFileURL(file).href)
    await page.evaluate(() => document.fonts.ready)
    await page.waitForTimeout(300)
    // Every <text> with a data-maxw must fit; every other text must stay inside the canvas.
    const bad = await page.evaluate(() => {
      const found = []
      for (const el of document.querySelectorAll('svg text')) {
        const b = el.getBBox()
        const max = Number(el.getAttribute('data-maxw'))
        const label = el.textContent.slice(0, 50)
        if (max && b.width > max) found.push(`${label}: ${Math.round(b.width)} > ${max}`)
        if (b.x < 0 || b.x + b.width > 1920 || b.y + b.height > 1080) found.push(`${label}: outside the canvas`)
      }
      return found
    })
    for (const m of bad) { console.log(`  OVERFLOW [${d.name}${suffix}] ${m}`); problems++ }
    const png = resolve(docs, `${d.png}${suffix}.png`)
    await page.screenshot({ path: png })
    console.log(`wrote docs/${d.png}${suffix}.png + docs/diagrams/${d.name}${suffix}.svg`)
  }
}
await browser.close()
if (problems) { console.log(`${problems} text overflow(s)`); process.exitCode = 1 }
