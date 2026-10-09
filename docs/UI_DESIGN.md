# UI design brief — Gaffer

Read this before building any frontend (Phase 4). User experience is 10% of the score, and the web app is the first thing every judge sees. It must look like a **real sports-tech product**, not a hackathon dashboard.

---

## 1. Inspiration — and the line we don't cross

The user loves the **Veo Cam 3 product page** (`veo.com/product/veo-cam-3`). Take inspiration from its **structure, rhythm and feel**:

- A big, full-bleed **match-video hero** with a short, confident headline and two clear calls to action
- **Numbered steps (01 / 02 / 03)** that explain the product in seconds
- One idea per section, lots of breathing room, short benefit-driven copy
- **Interactive** moments: Veo has a "hold and drag" 180° pitch viewer and **On/Off feature toggles** that change what you see
- Clean **spec cards**, an **FAQ accordion**, and a tidy multi-column footer
- Sporty, premium, product-focused mood

**Do not copy Veo.** No Veo name, logo, product photos, video, copy text, icons, or their exact colours and fonts. Gaffer has its own brand (below). "Inspired by the layout and motion of a modern sports-tech product page" — never a clone. This also matters for the competition's IP rules.

---

## 2. Brand

**Name:** Gaffer. **Tagline:** *Your tactical analyst. It watches, checks, then tells you.*
**Mood:** night match under floodlights, broadcast-graphics precision, calm confidence.

### Colour tokens (dark-first)

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#070D0A` | Page background (near-black, slight pitch green) |
| `--surface` | `#0F1914` | Cards, panels |
| `--surface-2` | `#16231C` | Raised elements, hover |
| `--line` | `#22332A` | Borders, pitch lines on dark |
| `--text` | `#EEF4F0` | Primary text |
| `--muted` | `#8FA398` | Secondary text |
| `--accent` | `#C8F542` | Floodlight lime — primary buttons, highlights, confirmed alerts |
| `--team-a` | `#FF5B4F` | Team A dots/lines |
| `--team-b` | `#44C8FF` | Team B dots/lines |
| `--warn` | `#FFB020` | Uncertain / candidate changes |
| `--danger` | `#FF4D6D` | Rejected changes |

Accent is used sparingly — one lime element per view draws the eye. All text meets WCAG AA contrast on its background.

### Typography (Google Fonts, free, OFL)

- Headings: **Space Grotesk** 600–700, tight letter-spacing (-0.02em), big sizes (hero 64–88 px desktop)
- Body/UI: **Inter** 400–600, 16 px base
- Numbers, timestamps, formations ("4-4-2", "62:14"): **JetBrains Mono** — tabular, broadcast feel

### Shape & texture

- Radius 14–20 px on cards, pill buttons
- Thin 1 px `--line` borders instead of heavy shadows; soft glow (`--accent` at 20% blur) only on the primary CTA and confirmed alerts
- Subtle pitch-line SVG pattern and grain in section backgrounds

---

## 3. Two surfaces

### A. Landing page (`/`) — the story, Veo-style

| # | Section | What it shows | Motion / interaction |
|---|---|---|---|
| 1 | Sticky nav | Logo, How it works, See it work, Results, Tech, GitHub, **Open the demo** (lime pill) | Blurs and shrinks on scroll |
| 2 | Hero | Full-bleed looping TeamTrack drone clip (muted, darkened gradient), headline *"See the shape change before the scoreline does."*, sub-line, CTAs **Open the demo** / **How it works** | Headline words rise in with stagger; live mini-pitch with moving team dots floats over the video corner |
| 3 | How it works — 01 / 02 / 03 | 01 *Upload a match video* · 02 *OpenCV maps every player onto the pitch* · 03 *The agent double-checks, then alerts the coach* | Cards reveal on scroll; a connecting line draws between them |
| 4 | What OpenCV sees | **Before/after drag slider**: raw frame ↔ annotated frame (boxes, team colours, pitch lines) — our answer to Veo's drag viewer | Drag handle; auto-nudges once to hint it's draggable |
| 5 | Layer toggles | **On/Off switches** — Team colours · Formation lines · Heatmap · Defensive line — controlling a live animated 2D pitch | Layers fade/morph in and out |
| 6 | Verified, not guessed | **Sticky scroll story** of the minute-62 example: candidate → quality check → re-analysis → confirmed → coach approves | Left column pinned pitch animation; right column steps scroll past and drive it |
| 7 | Results | 3–4 big numbers: formation accuracy, false alerts cut by the agent, FPS, players tracked | Count-up when in view |
| 8 | Built with | Cards: OpenCV 5, Amazon Bedrock (Nova 2 Lite), EC2, S3, CloudWatch — one line each on *what it does in Gaffer* | Hover lift |
| 9 | FAQ | "Do I need special cameras?", "Is it live?", "What about player privacy?", "What data was it tested on?" | Accordion with smooth height |
| 10 | Footer | Credits & licences (TeamTrack MIT + paper, OpenCV, etc.), GitHub, competition name | — |

### B. The app (`/app`) — the analyst's desk

- **Top bar:** match selector (pre-processed matches), **Live replay** toggle, **Generate report** button
- **Main left:** video player with optional overlay (boxes + team colours)
- **Main right:** 2D top-down pitch, synced to video time; current formation per team in big mono text ("4-4-2")
- **Bottom:** formation timeline per team; change markers coloured by status (lime confirmed, amber uncertain, red rejected); click jumps the video
- **Right drawer:** alert cards — title, one-line explanation, evidence image, **Approve / Reject** buttons, collapsible **"How Gaffer checked this"** trace (each OpenCV tool call as a step with its result)
- **Empty, loading and error states** designed, not default (skeleton shimmer while loading; friendly message if Bedrock quota is exhausted)

**Live replay mode:** the match plays as if live; candidate changes appear as amber pulses, the trace steps tick through, then the alert slides in — the most impressive 20 seconds of the demo video.

---

## 4. Motion principles

- Purposeful: motion explains (data flowing, state changing), never decorates for its own sake
- Durations 200–600 ms; easing `cubic-bezier(0.22, 1, 0.36, 1)`; springs for alerts and drawers
- Scroll reveals: fade + 24 px rise, staggered 60–80 ms; trigger once
- Pitch dots animate on a `<canvas>` (or SVG for small counts) at 60 fps with interpolation between samples
- Smooth scrolling on the landing page only, not inside the app
- **Respect `prefers-reduced-motion`**: disable parallax, smooth scroll and auto-play; keep instant state changes
- Never block reading: nothing animates longer than ~800 ms, no scroll-jacking beyond the one sticky story section

---

## 5. Stack — free and open-source only

| Need | Use | Licence |
|---|---|---|
| Framework | **React + TypeScript + Vite** | MIT |
| Styling | **Tailwind CSS** (tokens above as CSS variables) | MIT |
| Animation | **Motion** (`motion` / framer-motion) | MIT |
| Smooth scroll | **Lenis** | MIT |
| Icons | **Lucide** | ISC |
| Charts (if any) | **Recharts** or hand-built SVG | MIT |
| Fonts | Space Grotesk, Inter, JetBrains Mono via Google Fonts or self-hosted | OFL |
| Video | Native HTML5 `<video>`, H.264 MP4 + WebM, poster image | — |

**Rules:**
- **No paid APIs or paid assets** — no paid UI kits, stock video, premium fonts, map tiles, or analytics SaaS. If a library has a paid tier, use only the free/open part or pick an MIT alternative and say so.
- All visuals come from our own renders or TeamTrack (MIT) clips.
- The built frontend is static files served by the FastAPI app on EC2 — no separate paid hosting.
- Node.js (LTS) is needed on the laptop to build the frontend: `node --version`; install with `winget install OpenJS.NodeJS.LTS` if missing.

---

## 6. Quality bar (Phase 4 acceptance)

- [ ] A stranger understands what Gaffer does within 30 seconds of the landing page
- [ ] Hero video ≤ 3 MB, page usable in < 3 s on a normal connection; Lighthouse performance ≥ 85 and accessibility ≥ 90 (desktop)
- [ ] Keyboard navigable, visible focus states, alt text, AA contrast
- [ ] `prefers-reduced-motion` respected
- [ ] Works on desktop (1280 px+) perfectly, landing page also fine on mobile
- [ ] Nothing in the UI copies Veo's brand, copy or assets
- [ ] Screenshots of landing + app saved to `docs/screenshots/` for the report and README
