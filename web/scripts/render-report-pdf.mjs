/* global document, window, getComputedStyle, Node, NodeFilter */
// Renders docs/TECHNICAL_REPORT.md (the source of truth) to docs/Gaffer_Technical_Report.pdf (A4).
//
//   node web/scripts/render-report-pdf.mjs                    -> docs/Gaffer_Technical_Report.pdf
//   node web/scripts/render-report-pdf.mjs --images <dir>     -> also one PNG per page, for review
//
// Tools: the repo's playwright-core drives the local Edge/Chromium (CHROMIUM_PATH overrides) and prints
// the PDF. Pinned npm packages are installed once into a cache folder outside the repo (no change to
// web/package.json): marked@18.1.1 (MIT, Markdown -> HTML), pdfjs-dist@6.4.299 (Apache-2.0, reads the
// printed PDF's link destinations to fill the contents page numbers, and renders review PNGs), and the
// static builds of the site's fonts, @fontsource/{inter,space-grotesk,jetbrains-mono}@5.3.0 (OFL-1.1):
// static fonts embed as TrueType, where the site's variable fonts would be embedded as Type 3 outlines.
//
// Conventions read from the Markdown: everything before the first "## " heading is the title page;
// the "## Contents" list is replaced by a generated contents page with page numbers; a paragraph
// "*Figure N: ...*" after an image and "*Table N: ...*" before a table become captions, kept on one page
// with what they caption; a following "Source: ..." line stays with its table. Relative repository
// links become https://github.com/haiderchaudarry96-stack/Gaffer/blob/main/... URLs.
import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { dirname, extname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { chromium } from 'playwright-core'

const REPO_URL = 'https://github.com/haiderchaudarry96-stack/Gaffer'
const TOOLS = { marked: '18.1.1', 'pdfjs-dist': '6.4.299', '@fontsource/inter': '5.3.0', '@fontsource/space-grotesk': '5.3.0', '@fontsource/jetbrains-mono': '5.3.0' }

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(web, '..')
const docs = resolve(repo, 'docs')
const src = resolve(docs, 'TECHNICAL_REPORT.md')
const out = resolve(docs, 'Gaffer_Technical_Report.pdf')
const imagesArg = process.argv.indexOf('--images')
const imagesDir = imagesArg > 0 ? resolve(process.argv[imagesArg + 1]) : null

// --- pinned tools, cached outside the repo -------------------------------------------------------
const toolsDir = join(tmpdir(), 'gaffer-report-tools-1')  // bump the suffix when TOOLS changes
if (Object.keys(TOOLS).some((k) => !existsSync(join(toolsDir, 'node_modules', k)))) {
  mkdirSync(toolsDir, { recursive: true })
  console.log(`installing ${Object.entries(TOOLS).map(([k, v]) => `${k}@${v}`).join(', ')} into ${toolsDir}`)
  const pkgs = Object.entries(TOOLS).map(([k, v]) => `${k}@${v}`).join(' ')
  execSync(`npm install --no-audit --no-fund --prefix "${toolsDir}" ${pkgs}`, { stdio: 'inherit' })
}
const { marked } = await import(pathToFileURL(join(toolsDir, 'node_modules/marked/lib/marked.esm.js')).href)
const pdfjs = await import(pathToFileURL(join(toolsDir, 'node_modules/pdfjs-dist/legacy/build/pdf.mjs')).href)

// --- Markdown -> HTML page -----------------------------------------------------------------------
const md = readFileSync(src, 'utf8')
const body = marked.parse(md, { gfm: true })
const FONTS = [['Inter', 'inter', [400, 500, 600, 700]], ['Space Grotesk', 'space-grotesk', [500, 700]], ['JetBrains Mono', 'jetbrains-mono', [400, 500]]]
const fontFaces = FONTS.flatMap(([family, pkg, weights]) => weights.flatMap((w) => ['latin', 'latin-ext'].map((sub) => {
  const url = pathToFileURL(join(toolsDir, 'node_modules/@fontsource', pkg, 'files', `${pkg}-${sub}-${w}-normal.woff2`)).href
  return `@font-face{font-family:"${family}";src:url("${url}");font-weight:${w};font-style:normal}`
}))).join('\n')
const css = readFileSync(resolve(web, 'scripts/report.css'), 'utf8')
const html = `<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<base href="${pathToFileURL(docs).href}/">
<title>Gaffer: a self-verifying tactical analyst for grassroots football</title>
<meta name="author" content="Haider Sultan">
<style>
${fontFaces}
${css}
</style></head><body><main id="report">${body}</main></body></html>`
const tmp = join(tmpdir(), 'gaffer-report-build')
mkdirSync(tmp, { recursive: true })
const htmlFile = join(tmp, 'report.html')
writeFileSync(htmlFile, html)

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
})
const page = await browser.newPage()
await page.goto(pathToFileURL(htmlFile).href)
// load every face up front: weights used only in the page margins are otherwise never fetched
await page.evaluate(() => Promise.all([...document.fonts].map((f) => f.load())).then(() => document.fonts.ready))

// --- DOM structure: ids, title page, contents, captions, links, no-wrap numbers -----------------------
const warnings = await page.evaluate(({ REPO_URL }) => {
  const warn = []
  const main = document.getElementById('report')
  // GitHub-style heading slugs (same rule GitHub uses for #anchors)
  const used = new Map()
  const slug = (s) => {
    const base = s.toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s/g, '-')
    const n = used.get(base) ?? 0
    used.set(base, n + 1)
    return n ? `${base}-${n}` : base
  }
  for (const h of main.querySelectorAll('h1, h2, h3, h4')) h.id = slug(h.textContent)

  // Title page = everything before the first h2
  const title = document.createElement('section')
  title.className = 'title-page'
  while (main.firstChild && !(main.firstChild.nodeType === 1 && main.firstChild.tagName === 'H2')) title.appendChild(main.firstChild)
  main.prepend(title)

  // Contents: replace the Markdown list with a generated one (h2 + h3), page numbers filled later
  const contentsH = [...main.querySelectorAll('h2')].find((h) => h.textContent.trim() === 'Contents')
  const after = []
  for (let n = contentsH.nextElementSibling; n && n.tagName !== 'H2'; n = n.nextElementSibling) after.push(n)
  after.forEach((n) => n.remove())
  const toc = document.createElement('nav')
  toc.className = 'toc'
  const heads = [...main.querySelectorAll('h2, h3')].filter((h) => h !== contentsH && !h.closest('.title-page'))
  for (const h of heads) {
    const a = document.createElement('a')
    a.href = `#${h.id}`
    a.className = `toc-${h.tagName.toLowerCase()}`
    a.innerHTML = `<span class="toc-title">${h.textContent}</span><span class="toc-dots"></span><span class="toc-page" data-for="${h.id}">00</span>`
    toc.appendChild(a)
  }
  contentsH.after(toc)
  const contentsSection = document.createElement('section')
  contentsSection.className = 'contents-page'
  contentsH.before(contentsSection)
  contentsSection.append(contentsH, toc)

  // Sections that start on a new page
  for (const h of main.querySelectorAll('h2')) {
    const t = h.textContent
    if (/^(Executive summary|1 Problem|References|Appendix)/.test(t)) h.classList.add('new-page')
  }

  // Captions
  const capRe = /^(Figure|Table) (A?\d+):/
  for (const p of [...main.querySelectorAll('p')]) {
    const em = p.children.length === 1 && p.firstElementChild.tagName === 'EM' && p.textContent.trim() === p.firstElementChild.textContent.trim() ? p.firstElementChild : null
    const m = em && em.textContent.trim().match(capRe)
    if (!m) continue
    const fig = document.createElement('figure')
    const cap = document.createElement('figcaption')
    const label = `${m[1]} ${m[2]}:`
    cap.innerHTML = `<strong>${label}</strong>${em.innerHTML.trim().slice(label.length)}`
    if (m[1] === 'Figure') {
      const prev = p.previousElementSibling
      const img = prev && prev.querySelector('img')
      if (!img || prev.textContent.trim()) { warn.push(`figure caption without an image: ${label}`); continue }
      fig.className = 'figure'
      prev.before(fig)
      fig.append(img, cap)
      prev.remove()
      p.remove()
    } else {
      const table = p.nextElementSibling
      if (!table || table.tagName !== 'TABLE') { warn.push(`table caption without a table: ${label}`); continue }
      fig.className = 'table-figure'
      p.before(fig)
      fig.append(cap, table)
      const next = fig.nextElementSibling
      if (next && next.tagName === 'P' && /^Source:/.test(next.textContent)) { next.className = 'source'; fig.append(next) }
      p.remove()
      if (/^Table A/.test(label) === false && table.rows[0].cells.length >= 5) fig.classList.add('wide')
    }
  }
  for (const img of main.querySelectorAll('img')) if (!img.closest('figure') && !img.closest('.title-page')) warn.push(`image without a caption: ${img.getAttribute('src')}`)
  for (const t of main.querySelectorAll('table')) if (!t.closest('figure')) warn.push(`table without a caption: ${t.rows[0].textContent.slice(0, 40)}`)

  // Repository links -> GitHub URLs (the report lives in docs/)
  for (const a of main.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href')
    if (/^(https?:|mailto:|#)/.test(href)) continue
    const url = new URL(href, 'https://x/docs/')
    const path = url.pathname.replace(/^\//, '')
    const isDir = path.endsWith('/')
    a.href = `${REPO_URL}/${isDir ? 'tree' : 'blob'}/main/${path.replace(/\/$/, '')}${url.hash}`
  }
  for (const a of main.querySelectorAll('a[href^="#"]')) {
    if (!document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)))) warn.push(`broken internal link ${a.getAttribute('href')}`)
  }

  // Table cells: let code break only after / _ . ( and keep short numeric cells on one line
  for (const c of main.querySelectorAll('td code, th code')) {
    c.innerHTML = c.textContent.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/([/_.(])/g, '$1<wbr>')
  }
  for (const td of main.querySelectorAll('td')) {
    const t = td.textContent.trim()
    if (t.length <= 28 && /\d/.test(t) && /^[\d\s.,/%()–\-;:→±$<≤≥+]*$/.test(t)) td.classList.add('num')
  }

  // Keep numbers, units and formations from wrapping inside tables and running text
  const numRe = /((?:Table|Figure|Section|Appendix) A?\d+(?:\.\d+)?)|(\d+(?:-\d+){2,3})|(\d+(?:-[A-Za-z]+)+)|([$±−]?\d[\d,.]*(?:\s?(?:%|s|m|ms|KB|MB|GB|GiB|px\/s|px\/m|px|fps|min|k))?(?:\s?\/\s?\d[\d,.]*(?:\s?%)?)?)/g
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement.closest('pre, code, .toc, .title-page, script, style') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  })
  const texts = []
  while (walker.nextNode()) texts.push(walker.currentNode)
  for (const n of texts) {
    const s = n.nodeValue
    if (!/\d/.test(s)) continue
    const frag = document.createDocumentFragment()
    let last = 0
    for (const m of s.matchAll(numRe)) {
      if (m[0].length < 2 && !/\d-\d/.test(m[0])) continue
      frag.append(s.slice(last, m.index))
      const span = document.createElement('span')
      span.className = 'nw'
      span.textContent = m[0]
      frag.append(span)
      last = m.index + m[0].length
    }
    if (last === 0) continue
    frag.append(s.slice(last))
    n.replaceWith(frag)
  }
  void getComputedStyle; void window; void Node
  return warn
}, { REPO_URL })
for (const w of warnings) console.log(`  WARN ${w}`)
await page.evaluate(() => Promise.all([...document.images].map((i) => (i.complete ? null : new Promise((r) => { i.onload = i.onerror = r })))))
const missing = await page.evaluate(() => [...document.images].filter((i) => !i.naturalWidth).map((i) => i.getAttribute('src')))
for (const m of missing) console.log(`  WARN image did not load: ${m}`)

// --- print, read the contents destinations back, fill page numbers, print again ---------------------
const pdfOpts = { format: 'A4', printBackground: true, preferCSSPageSize: true, outline: true, tagged: true }
// Chromium writes the contents links as direct page destinations. The first internal links of the
// document (title page and summary have none) are the contents entries, in order.
async function headingPages(buf, ids) {
  const task = pdfjs.getDocument({ data: new Uint8Array(buf), verbosity: 0 })
  const doc = await task.promise
  const links = []
  for (let i = 1; i <= doc.numPages && links.length < ids.length; i++) {
    const pg = await doc.getPage(i)
    const anns = (await pg.getAnnotations()).filter((a) => a.subtype === 'Link' && a.dest)
    anns.sort((a, b) => b.rect[3] - a.rect[3] || a.rect[0] - b.rect[0])
    for (const a of anns) {
      const dest = typeof a.dest === 'string' ? (await doc.getDestination(a.dest)) : a.dest
      const key = JSON.stringify(dest)
      if (links.length && links[links.length - 1].key === key) continue // one link split over two lines
      links.push({ key, page: (await doc.getPageIndex(dest[0])) + 1 })
    }
  }
  const map = {}
  ids.forEach((id, k) => { map[id] = links[k]?.page })
  const n = doc.numPages
  await task.destroy()
  return { map, n }
}
let buf, pages, prev = ''
for (let pass = 1; pass <= 4; pass++) {
  buf = await page.pdf(pdfOpts)
  const ids = await page.evaluate(() => [...document.querySelectorAll('.toc-page')].map((s) => s.dataset.for))
  pages = await headingPages(buf, ids)
  const missingDest = ids.filter((id) => !pages.map[id])
  if (missingDest.length) console.log(`  WARN no PDF destination for: ${missingDest.join(', ')}`)
  const sig = JSON.stringify(ids.map((id) => pages.map[id]))
  if (sig === prev) { console.log(`contents page numbers stable after pass ${pass}`); break }
  prev = sig
  await page.evaluate((map) => {
    for (const s of document.querySelectorAll('.toc-page')) s.textContent = String(map[s.dataset.for] ?? '?')
  }, pages.map)
}
writeFileSync(out, buf)
console.log(`wrote docs/Gaffer_Technical_Report.pdf: ${pages.n} pages, ${(buf.length / 1e6).toFixed(2)} MB`)
const tocList = await page.evaluate(() => [...document.querySelectorAll('.toc a')].map((a) => `${a.querySelector('.toc-page').textContent.padStart(3)}  ${a.querySelector('.toc-title').textContent}`))
console.log(tocList.join('\n'))

// --- optional: one PNG per page (pdf.js in the browser, served from a local port) -----------------------
if (imagesDir) {
  mkdirSync(imagesDir, { recursive: true })
  const pdfjsDir = join(toolsDir, 'node_modules/pdfjs-dist')
  const types = { '.mjs': 'text/javascript', '.js': 'text/javascript', '.html': 'text/html', '.pdf': 'application/pdf' }
  const server = createServer((req, res) => {
    const u = decodeURIComponent(req.url.split('?')[0])
    const file = u === '/report.pdf' ? out : u === '/' ? null : join(pdfjsDir, u.replace(/^\/pdfjs\//, ''))
    if (u === '/') { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<!doctype html><body style="margin:0">'); return }
    if (!file || !existsSync(file)) { res.writeHead(404); res.end(); return }
    res.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream' })
    res.end(readFileSync(file))
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  const base = `http://127.0.0.1:${server.address().port}`
  const view = await browser.newPage()
  await view.goto(`${base}/`)
  const n = await view.evaluate(async (base) => {
    const lib = await import(`${base}/pdfjs/legacy/build/pdf.mjs`)
    lib.GlobalWorkerOptions.workerSrc = `${base}/pdfjs/legacy/build/pdf.worker.mjs`
    window.__doc = await lib.getDocument({ url: `${base}/report.pdf` }).promise
    return window.__doc.numPages
  }, base)
  for (let i = 1; i <= n; i++) {
    const dataUrl = await view.evaluate(async (i) => {
      const p = await window.__doc.getPage(i)
      const vp = p.getViewport({ scale: 1.6 })
      const c = document.createElement('canvas')
      c.width = vp.width; c.height = vp.height
      const ctx = c.getContext('2d')
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height)
      await p.render({ canvasContext: ctx, viewport: vp }).promise
      return c.toDataURL('image/png')
    }, i)
    writeFileSync(join(imagesDir, `page-${String(i).padStart(2, '0')}.png`), Buffer.from(dataUrl.split(',')[1], 'base64'))
  }
  server.close()
  console.log(`wrote ${n} page images to ${imagesDir}`)
}
await browser.close()
