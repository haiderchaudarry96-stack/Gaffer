// Gaffer diagrams: the editable source of docs/architecture*.png and docs/agent_workflow*.png.
//
// Each function returns one self-contained SVG string (1920 x 1080, real <text>, grouped shapes with
// ids, literal colours, no CSS classes, no markers, no raster) so the files import cleanly into Figma.
// The dark and light versions come from the same layout with different tokens (THEMES), so they cannot
// drift apart. Fonts are the site's: Space Grotesk (display), Inter (text), JetBrains Mono (code).
//
//   node web/scripts/render-diagrams.mjs        -> docs/diagrams/*.svg + docs/*.png (2x, Playwright)
//
// Every box states something that is true of the as-built system (docs/TECHNICAL_REPORT.md,
// docs/AGENT_DESIGN.md, docs/AGENT_TRACE_EXAMPLES.md, deploy/DEPLOY_AWS.md). Numbers in the workflow
// example are copied from AGENT_TRACE_EXAMPLES.md (a).

export const THEMES = {
  dark: {
    name: 'dark', bg: '#070D0A', cloud: '#0A120E', surface: '#0F1914', surface2: '#16231C', line: '#2F4538',
    text: '#EEF4F0', muted: '#8FA398', accent: '#C8F542', ink: '#C8F542', onAccent: '#070D0A',
    arrow: '#8FA398', danger: '#FF4D6D', warn: '#FFB020', loopOpacity: 0.07, chipFill: '#16231C',
  },
  light: {
    name: 'light', bg: '#F3F5EF', cloud: '#E9EEE5', surface: '#FFFFFF', surface2: '#E7ECE4', line: '#AFBDB1',
    text: '#0B1510', muted: '#4A5C52', accent: '#C8F542', ink: '#4A6B00', onAccent: '#070D0A',
    arrow: '#4A5C52', danger: '#C2183F', warn: '#9A5B00', loopOpacity: 0.28, chipFill: '#E7ECE4',
  },
}

const FONT = {
  display: 'Space Grotesk, Inter, sans-serif',
  sans: 'Inter, sans-serif',
  mono: 'JetBrains Mono, monospace',
}

// Simple 24 x 24 line icons (own drawings, 1.8 px stroke at 24; no third-party marks).
const ICONS = {
  browser: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9.5h18"/><circle cx="6.5" cy="6.8" r="0.6"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  pitch: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M12 5v14"/><circle cx="12" cy="12" r="2.6"/>',
  route: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.5 6H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h6.5"/>',
  sparkle: '<path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z"/><path d="M19 15v4M17 17h4"/>',
  bucket: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6l2 13c.2 1 2.8 2 6 2s5.8-1 6-2l2-13"/>',
  chart: '<path d="M4 4v16h16"/><path d="M7.5 15l3.5-5 3 3 5-6"/>',
  disk: '<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M14 9l2 2"/>',
  server: '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01"/>',
  cloud: '<path d="M7 18a4 4 0 0 1-.5-7.97A6 6 0 0 1 18 9.5 4.5 4.5 0 0 1 17.5 18z"/>',
  scan: '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-3.5M4 5v3.5h3.5"/><path d="M4 13a8 8 0 0 0 14.5 3.5M20 19v-3.5h-3.5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M4 18l5.5-5.5L13 16l3-3 4 4"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2.5"/><path d="M9 4V3h6v1M9 11h6M9 15h4"/>',
  bell: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 21h4"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  scale: '<path d="M12 4v16M7 20h10M5 8h14"/><path d="M5 8l-3 6a3 3 0 0 0 6 0zM19 8l-3 6a3 3 0 0 0 6 0z"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.2 7.6-8 9-4.8-1.4-8-4.5-8-9V6z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
  loop: '<path d="M20 11a8 8 0 0 0-14.5-3.5M4 5v3.5h3.5"/><path d="M4 13a8 8 0 0 0 14.5 3.5M20 19v-3.5h-3.5"/>',
  check: '<path d="M6 12.5l4 4 8-9"/>',
  cross: '<path d="M7 7l10 10M17 7L7 17"/>',
  question: '<path d="M9 9a3 3 0 1 1 4.4 2.6c-.9.5-1.4 1.1-1.4 2.1M12 17.5h.01"/>',
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function kit(t) {
  const text = (x, y, s, o = {}) => {
    const { size = 20, weight = 400, fill = t.text, font = 'sans', anchor = 'start', ls, maxw } = o
    return `<text x="${x}" y="${y}" font-family="${FONT[font]}" font-size="${size}" font-weight="${weight}" fill="${fill}"` +
      `${anchor !== 'start' ? ` text-anchor="${anchor}"` : ''}${ls ? ` letter-spacing="${ls}"` : ''}` +
      `${maxw ? ` data-maxw="${maxw}"` : ''}>${esc(s)}</text>`
  }
  const rect = (x, y, w, h, o = {}) => {
    const { r = 14, fill = t.surface, stroke = t.line, sw = 1.5, dash, fo } = o
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}"` +
      `${fo !== undefined ? ` fill-opacity="${fo}"` : ''}` +
      `${stroke ? ` stroke="${stroke}" stroke-width="${sw}"` : ''}${dash ? ` stroke-dasharray="${dash}"` : ''}/>`
  }
  const icon = (name, x, y, size, color, vw = 1.9) =>
    `<g transform="translate(${x} ${y}) scale(${size / 24})" fill="none" stroke="${color}" ` +
    `stroke-width="${((vw * 24) / size).toFixed(2)}" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</g>`

  // Axis-aligned arrow with explicit head polygons (Figma ignores SVG markers).
  const arrow = (x1, y1, x2, y2, o = {}) => {
    const { color = t.ink, w = 3, both = false, head = 12 } = o
    const ux = Math.sign(x2 - x1), uy = Math.sign(y2 - y1)
    const hw = head * 0.58
    const hd = (tx, ty, dx, dy) => {
      const bx = tx - dx * head, by = ty - dy * head
      return `<polygon points="${tx},${ty} ${bx + -dy * hw},${by + dx * hw} ${bx - -dy * hw},${by - dx * hw}" fill="${color}"/>`
    }
    const sx = both ? x1 + ux * (head - 1) : x1, sy = both ? y1 + uy * (head - 1) : y1
    const ex = x2 - ux * (head - 1), ey = y2 - uy * (head - 1)
    return `<g><line x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" stroke="${color}" stroke-width="${w}"/>` +
      `${hd(x2, y2, ux, uy)}${both ? hd(x1, y1, -ux, -uy) : ''}</g>`
  }
  const badge = (cx, cy, n, id) =>
    `<g id="${id}"><circle cx="${cx}" cy="${cy}" r="14" fill="${t.accent}" stroke="${t.ink}" stroke-width="1.5"/>` +
    `<text x="${cx}" y="${cy + 6}" font-family="${FONT.display}" font-size="17" font-weight="700" fill="${t.onAccent}" text-anchor="middle">${n}</text></g>`

  const logo = (x, y, size) =>
    `<g id="logo" transform="translate(${x} ${y}) scale(${size / 64})">` +
    '<rect width="64" height="64" rx="14" fill="#070D0A"/>' +
    '<rect x="9" y="12" width="46" height="40" rx="4" fill="#16231C" stroke="#8FA398" stroke-width="3"/>' +
    '<line x1="32" y1="12" x2="32" y2="52" stroke="#8FA398" stroke-width="2.2"/>' +
    '<circle cx="19" cy="23" r="4.2" fill="#FF5B4F"/><circle cx="19" cy="41" r="4.2" fill="#FF5B4F"/>' +
    '<circle cx="45" cy="23" r="4.2" fill="#44C8FF"/>' +
    '<path d="M30 41 L38 49 L56 30" fill="none" stroke="#070D0A" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M30 41 L38 49 L56 30" fill="none" stroke="#C8F542" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></g>'

  const header = (what, caption, right) =>
    `<g id="header">${logo(56, 28, 56)}` +
    `<text x="128" y="68" font-family="${FONT.display}" font-size="40" font-weight="700" fill="${t.text}" letter-spacing="-0.5">Gaffer` +
    `<tspan fill="${t.muted}" font-weight="500" dx="14">${esc(what)}</tspan></text>` +
    text(128, 102, caption, { size: 21, fill: t.muted, maxw: 1320 }) +
    (right ? text(1864, 68, right, { size: 18, font: 'mono', fill: t.muted, anchor: 'end' }) : '') + '</g>'

  const wrap = (title, desc, body) =>
    `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080" role="img" aria-labelledby="t d">\n` +
    `<title id="t">${esc(title)}</title><desc id="d">${esc(desc)}</desc>\n` +
    `<rect id="background" width="1920" height="1080" fill="${t.bg}"/>\n${body}\n</svg>\n`

  return { text, rect, icon, arrow, badge, header, wrap }
}

// ---------------------------------------------------------------------------------------------------
export function architecture(t) {
  const { text, rect, icon, arrow, badge, header, wrap } = kit(t)
  const out = []

  // Tall station: icon, title, short lines.
  const station = (id, x, y, w, h, ic, title, lines, o = {}) => {
    const { accentLine = -1, fill = t.surface, stroke = t.line, tsize = 26 } = o
    let s = `<g id="${id}">${rect(x, y, w, h, { fill, stroke })}` + icon(ic, x + 20, y + 18, 30, t.ink)
    s += text(x + 20, y + 84, title, { size: tsize, weight: 700, font: 'display', maxw: w - 32 })
    lines.forEach((l, i) => {
      s += text(x + 20, y + 120 + i * 30, l, { size: 20, fill: i === accentLine ? t.ink : t.muted, weight: i === accentLine ? 600 : 400, maxw: w - 32 })
    })
    return s + '</g>'
  }
  // Wide row card: icon left, title + two lines.
  const rowCard = (id, x, y, w, h, ic, title, lines) => {
    let s = `<g id="${id}">${rect(x, y, w, h)}` + icon(ic, x + 22, y + 22, 34, t.ink)
    s += text(x + 78, y + 42, title, { size: 26, weight: 700, font: 'display', maxw: w - 98 })
    lines.forEach((l, i) => { s += text(x + 78, y + 74 + i * 28, l, { size: 20, fill: t.muted, maxw: w - 98 }) })
    return s + '</g>'
  }

  out.push(header('Architecture', 'OpenCV 5 does the seeing on EC2. Bedrock Nova 2 Lite only reads numbers and short text, never pixels.', 'gaffer-tactics.duckdns.org'))

  // AWS cloud frame
  out.push(`<g id="aws-cloud">${rect(340, 150, 1524, 816, { r: 24, fill: t.cloud, stroke: t.line, sw: 2, dash: '10 8' })}` +
    icon('cloud', 366, 168, 30, t.muted) +
    text(406, 191, 'AWS Cloud', { size: 24, weight: 700, font: 'display', maxw: 200 }) +
    text(540, 191, 'ap-southeast-2 (Sydney)', { size: 20, fill: t.muted, maxw: 300 }) + '</g>')

  // Coach's browser (outside the cloud)
  out.push(station('coach-browser', 56, 308, 240, 260, 'browser', 'Coach’s browser',
    ['upload or sample clip', '2D pitch + timeline', 'evidence + chat', 'approve / reject', 'Live on AWS card'], { accentLine: 4, tsize: 24 }))

  // EC2
  out.push(`<g id="ec2">${rect(372, 214, 1132, 436, { r: 20, fill: t.surface, stroke: t.line, sw: 2 })}` +
    icon('server', 396, 232, 32, t.ink) +
    text(440, 258, 'Amazon EC2', { size: 26, weight: 700, font: 'display', maxw: 200 }) +
    text(600, 258, 'm7i-flex.large · Docker', { size: 20, fill: t.muted, maxw: 300 }) +
    text(1480, 258, 'Elastic IP · ports 80 + 443 only · no SSH', { size: 18, font: 'mono', fill: t.muted, anchor: 'end', maxw: 560 }) + '</g>')

  out.push(station('caddy', 400, 328, 184, 220, 'lock', 'Caddy', ['HTTPS (TLS)', 'auto certificate', 'in front of', 'the app'], { fill: t.surface2 }))

  // Gaffer container
  out.push(`<g id="gaffer-container">${rect(640, 276, 836, 348, { r: 18, fill: t.surface, stroke: t.ink, sw: 2, dash: '8 6' })}` +
    text(662, 306, 'Gaffer container', { size: 20, weight: 700, font: 'display', maxw: 220 }) +
    text(842, 306, 'one worker, one analysis at a time', { size: 18, fill: t.muted, maxw: 420 }) + '</g>')

  // Perception: title + four sub-steps with lime bullets
  const px = 662, py = 328
  let per = `<g id="perception">${rect(px, py, 280, 220, { fill: t.surface2, stroke: t.ink, sw: 2 })}` + icon('eye', px + 20, py + 18, 30, t.ink)
  per += text(px + 20, py + 84, 'OpenCV 5 perception', { size: 24, weight: 700, font: 'display', maxw: 246 })
  ;['Self-calibration', 'Pitch + homography', 'Detection', 'Tracking + team colours'].forEach((l, i) => {
    per += `<circle cx="${px + 26}" cy="${py + 114 + i * 28}" r="4" fill="${t.ink}"/>` + text(px + 40, py + 121 + i * 28, l, { size: 20, maxw: 234 })
  })
  out.push(per + '</g>')

  out.push(station('tactics', 998, 328, 176, 220, 'pitch', 'Tactics', ['formation per', '30 s window', 'shape changes']))
  out.push(station('agent', 1230, 328, 224, 220, 'route', 'Agent', ['rules decide', 'Nova orchestrates', 'OpenCV re-checks'], { stroke: t.ink }))

  out.push(`<g id="api-strip">${rect(662, 566, 792, 40, { r: 10, fill: t.surface2, stroke: null })}` +
    text(678, 593, 'FastAPI · serves the web app · /api/runtime → “Live on AWS” card', { size: 18, font: 'mono', fill: t.muted, maxw: 760 }) + '</g>')

  // Bedrock
  out.push(station('bedrock', 1548, 308, 296, 260, 'sparkle', 'Amazon Bedrock',
    ['Nova 2 Lite', 'numbers + short text', 'never pixels'], { accentLine: 2 }))

  // Row B: S3, CloudWatch, EBS
  out.push(rowCard('s3', 372, 700, 464, 110, 'bucket', 'Amazon S3', ['clips, samples, model', 'fetched at container start']))
  out.push(rowCard('cloudwatch', 876, 700, 464, 110, 'chart', 'Amazon CloudWatch', ['logs + metrics', 'log group /gaffer/app']))
  out.push(rowCard('ebs', 1380, 700, 464, 110, 'disk', 'EBS volume · 30 GB', ['uploads, results, event DB', 'raw video deleted after 24 h']))

  // IAM band
  out.push(`<g id="iam">${rect(372, 850, 1472, 78, { r: 16, fill: t.surface2, stroke: t.line })}` + icon('key', 396, 872, 34, t.ink) +
    text(446, 897, 'IAM instance role', { size: 26, weight: 700, font: 'display', maxw: 260 }) +
    text(676, 897, 'No access keys on disk. Allows Nova 2 Lite, one S3 bucket, one log group.', { size: 20, fill: t.muted, maxw: 1140 }) + '</g>')

  // Arrows (main path = ink, side links = muted)
  const A = []
  A.push(arrow(296, 402, 400, 402) + arrow(400, 474, 296, 474))               // 1 and 6, browser <-> Caddy
  A.push(arrow(584, 438, 662, 438))                                          // 2 Caddy -> perception
  A.push(arrow(942, 438, 998, 438))                                         // 3 -> tactics
  A.push(arrow(1174, 438, 1230, 438))                                        // 4 -> agent
  A.push(arrow(1454, 438, 1548, 438, { both: true }))                        // 5 agent <-> Bedrock
  A.push(arrow(604, 650, 604, 700, { color: t.arrow, both: true, w: 2.5, head: 10 }))
  A.push(arrow(1108, 650, 1108, 700, { color: t.arrow, w: 2.5, head: 10 }))
  A.push(arrow(1440, 650, 1440, 700, { color: t.arrow, both: true, w: 2.5, head: 10 }))
  out.push(`<g id="arrows">${A.join('')}</g>`)
  out.push(`<g id="step-badges">${badge(320, 376, 1, 'step-1')}${badge(320, 448, 6, 'step-6')}${badge(623, 410, 2, 'step-2')}` +
    `${badge(970, 410, 3, 'step-3')}${badge(1202, 410, 4, 'step-4')}${badge(1526, 410, 5, 'step-5')}</g>`)

  // Legend: the six numbered steps
  const steps = ['Coach uploads a clip', 'OpenCV reads the video', 'Positions per frame', 'Candidate shape change', 'Nova + rules verify', 'Coach approves the alert']
  let lg = '<g id="legend">'
  steps.forEach((s, i) => {
    const x = 56 + i * 304
    lg += badge(x + 14, 1022, i + 1, `legend-${i + 1}`) + text(x + 38, 1029, s, { size: 20, maxw: 258 })
  })
  out.push(lg + '</g>')

  return wrap('Gaffer architecture',
    'The coach’s browser talks HTTPS to Caddy on one EC2 instance in Sydney. The Gaffer container runs OpenCV 5 perception, the tactics engine and the agent; the agent reads numbers and short text from Amazon Bedrock. S3 holds clips and the model, CloudWatch gets logs and metrics, and an IAM instance role replaces access keys.',
    out.join('\n'))
}

// ---------------------------------------------------------------------------------------------------
export function workflow(t) {
  const { text, rect, icon, arrow, badge, header, wrap } = kit(t)
  const out = []
  out.push(header('Agent workflow', 'Perceive with OpenCV, decide with rules, act only with the coach’s approval.', 'config fingerprint ca4ff9bbf7b01c6c'))

  const colX = [56, 680, 1304], colW = 560, top = 134, colH = 470
  const heads = [
    ['PERCEIVE', 'OpenCV 5 tools, run on EC2'],
    ['DECIDE', 'rules decide, Nova orchestrates'],
    ['ACT', 'nothing is sent without the coach'],
  ]
  heads.forEach(([h, sub], i) => {
    out.push(`<g id="col-${h.toLowerCase()}">${rect(colX[i], top, colW, colH, { r: 22, fill: t.cloud, stroke: t.line, sw: 2 })}` +
      badge(colX[i] + 38, top + 40, i + 1, `col-${i + 1}`) +
      text(colX[i] + 66, top + 48, h, { size: 28, weight: 700, font: 'display', ls: 2 }) +
      text(colX[i] + 66, top + 76, sub, { size: 19, fill: t.muted, maxw: 470 }) + '</g>')
  })

  const cardsTop = 224, cardsH = 366
  const card = (id, ci, idx, n, o) => {
    const gap = 12, h = (cardsH - gap * (n - 1)) / n
    const x = colX[ci] + 20, y = cardsTop + idx * (h + gap), w = colW - 40
    const { ic, title, tfont = 'display', tsize = 24, lines, chip, stroke = t.line } = o
    let s = `<g id="${id}">${rect(x, y, w, h, { r: 14, fill: t.surface, stroke })}` + icon(ic, x + 18, y + 16, 30, t.ink)
    s += text(x + 62, y + 38, title, { size: tsize, weight: tfont === 'mono' ? 600 : 700, font: tfont, maxw: chip ? w - 62 - 150 : w - 78 })
    if (chip) {
      const cw = chip.length * 9.6 + 24
      s += rect(x + w - 16 - cw, y + 14, cw, 30, { r: 15, fill: t.chipFill, stroke: t.line, sw: 1 }) +
        text(x + w - 16 - cw / 2, y + 35, chip, { size: 16, font: 'mono', fill: t.muted, anchor: 'middle' })
    }
    lines.forEach((l, i) => { s += text(x + 62, y + 38 + 30 + i * 26, l, { size: 19, fill: t.muted, maxw: w - 78 }) })
    return s + '</g>'
  }

  out.push(card('tool-check-frame-quality', 0, 0, 3, { ic: 'scan', title: 'check_frame_quality', tfont: 'mono', tsize: 22,
    lines: ['Camera still? Pitch lines fitted? Any cut?', 'If not: refuse, no alert'] }))
  out.push(card('tool-reanalyse-window', 0, 1, 3, { ic: 'refresh', title: 'reanalyse_window', tfont: 'mono', tsize: 22,
    lines: ['Re-reads the window at 4 to 6 fps', 'Budget: 360 s per call, 1,200 s per match'] }))
  out.push(card('tool-render-evidence', 0, 2, 3, { ic: 'image', title: 'render_evidence', tfont: 'mono', tsize: 22,
    lines: ['Annotated frame with formation lines', 'plus before / after shape panels'] }))

  out.push(card('decide-rules', 1, 0, 3, { ic: 'scale', title: 'Rules decide', chip: 'code',
    lines: ['Persistence, revert, return leg, coverage', 'Deterministic: same inputs, same verdict'] }))
  out.push(card('decide-nova', 1, 1, 3, { ic: 'sparkle', title: 'Nova 2 Lite', chip: 'Bedrock',
    lines: ['Picks the next tool and words the reason', 'Cannot overrule the rules’ verdict'] }))
  out.push(card('decide-guard', 1, 2, 3, { ic: 'shield', title: 'Guard + budgets', chip: 'limits',
    lines: ['At most 8 LLM and 3 vision calls per candidate', 'Rules-only fallback if Bedrock is down'] }))

  out.push(card('act-record', 2, 0, 4, { ic: 'clipboard', title: 'record_decision', tfont: 'mono', tsize: 21,
    lines: ['confirmed, rejected or uncertain, with citations'] }))
  out.push(card('act-evidence', 2, 1, 4, { ic: 'image', title: 'Evidence image', tsize: 22,
    lines: ['OpenCV frame + before / after shapes'] }))
  out.push(card('act-propose', 2, 2, 4, { ic: 'bell', title: 'propose_alert', tfont: 'mono', tsize: 21,
    lines: ['status pending, waits for the coach'] }))
  out.push(card('act-coach', 2, 3, 4, { ic: 'user', title: 'Coach approves or rejects', tsize: 22,
    lines: ['Every decision is logged'], stroke: t.ink }))

  // Arrows between columns: the loop (perceive <-> decide) and the hand-off (decide -> act)
  out.push(`<g id="column-arrows">${arrow(616, 400, 680, 400, { both: true, w: 3.5 })}` +
    `<circle cx="648" cy="400" r="21" fill="${t.bg}" stroke="${t.ink}" stroke-width="2.5"/>` + icon('loop', 634, 386, 28, t.ink, 2.2) +
    `<line x1="648" y1="421" x2="648" y2="636" stroke="${t.ink}" stroke-width="3" stroke-dasharray="3 7" stroke-linecap="round"/>` +
    `${arrow(1240, 400, 1304, 400, { color: t.arrow, w: 3 })}</g>`)

  // The lime loop: real example
  const by = 636, bh = 216
  out.push(`<g id="loop-example">${rect(56, by, 1808, bh, { r: 22, fill: t.accent, fo: t.loopOpacity, stroke: t.ink, sw: 2.5 })}` +
    icon('loop', 82, by + 20, 34, t.ink, 2.2) +
    text(128, by + 46, 'OpenCV result changes the next call', { size: 30, weight: 700, font: 'display', fill: t.ink, maxw: 700 }) +
    text(1840, by + 44, 'real trace · White 4-4-2 → 3-4-3 at 16:30', { size: 19, font: 'mono', fill: t.muted, anchor: 'end', maxw: 640 }) + '</g>')

  const steps = [
    { n: 1, title: 'First pass: coverage low', mono: false, lines: ['52 % of frames show ≥ 8 White', 'outfield players (60 % needed)'] },
    { n: 2, title: 'check_frame_quality', mono: true, lines: ['camera still, lines fit 100 %', 'coverage low: look again'] },
    { n: 3, title: 'reanalyse_window, 6 fps', mono: true, lines: ['highest rate, as coverage was low', '3-4-3 in 91 % of 11 clear readings'] },
    { n: 4, title: 'Confirmed', mono: false, lines: ['render_evidence → propose_alert', 'pending until the coach decides'] },
  ]
  const sw = 415, sgap = 36, sy = by + 64, sh = 100
  let chain = '<g id="loop-steps">'
  steps.forEach((s, i) => {
    const x = 76 + i * (sw + sgap)
    chain += `<g id="loop-step-${s.n}">${rect(x, sy, sw, sh, { r: 14, fill: t.surface, stroke: i === 3 ? t.ink : t.line, sw: i === 3 ? 2 : 1.5 })}` +
      badge(x + 30, sy + 30, s.n, `loop-badge-${s.n}`) +
      text(x + 56, sy + 36, s.title, { size: 21, weight: 700, font: s.mono ? 'mono' : 'display', maxw: sw - 72 })
    s.lines.forEach((l, k) => { chain += text(x + 20, sy + 64 + k * 24, l, { size: 19, fill: t.muted, maxw: sw - 36 }) })
    chain += '</g>'
    if (i < 3) chain += arrow(x + sw + 6, sy + sh / 2, x + sw + sgap - 6, sy + sh / 2, { w: 3, head: 11 })
  })
  out.push(chain + '</g>')
  out.push(text(76, by + bh - 16, 'Honest reading: the first pass alone would also have confirmed. OpenCV chose the path (6 fps) and built the evidence.', { size: 18, fill: t.muted, maxw: 1700 }))

  // Three outcomes
  const oy = 874, oh = 84
  const oc = [
    { id: 'outcome-confirmed', color: t.ink, ic: 'check', title: 'Confirmed → alert', line: 'pending until the coach approves' },
    { id: 'outcome-rejected', color: t.danger, ic: 'cross', title: 'Rejected + reason', line: 'no alert, the reason is shown' },
    { id: 'outcome-uncertain', color: t.warn, ic: 'question', title: 'Uncertain + reason', line: 'e.g. camera moved, over budget, clip too short' },
  ]
  out.push(text(56, oy + 36, 'Every candidate', { size: 20, weight: 600, maxw: 190 }) + text(56, oy + 62, 'ends as one of', { size: 20, fill: t.muted, maxw: 190 }))
  oc.forEach((o, i) => {
    const x = 252 + i * 544
    out.push(`<g id="${o.id}">${rect(x, oy, 524, oh, { r: 16, fill: t.surface, stroke: o.color, sw: 2 })}` +
      `<circle cx="${x + 38}" cy="${oy + oh / 2}" r="19" fill="none" stroke="${o.color}" stroke-width="2.5"/>` +
      icon(o.ic, x + 38 - 12, oy + oh / 2 - 12, 24, o.color, 2.4) +
      text(x + 72, oy + 36, o.title, { size: 23, weight: 700, font: 'display', maxw: 436 }) +
      text(x + 72, oy + 64, o.line, { size: 19, fill: t.muted, maxw: 436 }) + '</g>')
  })

  // Observability strip
  const vy = 976, vh = 60
  let obs = `<g id="observability">${rect(56, vy, 1808, vh, { r: 16, fill: t.surface2, stroke: t.line, sw: 1.5 })}` +
    icon('chart', 76, vy + 14, 32, t.ink) + text(124, vy + 38, 'Every step is logged', { size: 22, weight: 700, font: 'display', maxw: 250 })
  let cx = 400
  ;['agent_trace.jsonl', 'llm_calls.jsonl', 'alerts.jsonl', 'CloudWatch /gaffer/app'].forEach((c, i) => {
    const w = c.length * 10.8 + 34
    obs += rect(cx, vy + 11, w, 38, { r: 19, fill: t.surface, stroke: t.line, sw: 1.2 }) + text(cx + w / 2, vy + 36, c, { size: 18, font: 'mono', anchor: 'middle', maxw: w - 16 })
    cx += w + 14
    void i
  })
  obs += text(1840, vy + 37, 'tool calls · tokens + cost · coach decisions', { size: 18, fill: t.muted, anchor: 'end', maxw: 520 })
  out.push(obs + '</g>')

  return wrap('Gaffer agent workflow',
    'Three columns: Perceive (OpenCV tools check_frame_quality, reanalyse_window, render_evidence), Decide (rules, Nova 2 Lite, guard and budgets) and Act (record_decision, evidence image, propose_alert, the coach). A highlighted loop shows a real trace where an OpenCV result changed the next call. Every candidate ends confirmed, rejected or uncertain; every step is logged.',
    out.join('\n'))
}

export const DIAGRAMS = [
  { name: 'architecture', build: architecture, png: 'architecture' },
  { name: 'agent_workflow', build: workflow, png: 'agent_workflow' },
]
