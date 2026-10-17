# Gaffer web app (Phase 4 frontend)

React + Vite + TypeScript + Tailwind CSS + Motion + Lenis (all MIT). Two routes: `/` (landing page)
and `/app` (analyst desk). Design brief: `../docs/UI_DESIGN.md`; where this README lists a changed
decision, the README wins (decided by the user in the second design pass, 17 Oct).

```bash
cd web
npm install
npm run dev          # copies ../samples into public/sample, then starts Vite on http://localhost:5173
npm run build        # type-check + production build to dist/
npm run lint         # ESLint (incl. jsx-a11y)
npm test             # vitest: every sample file through src/data, live-replay timing, orientation
npm run screenshots  # after a build: Playwright + the pre-installed Chromium -> screenshots/ (+ landing-scroll.webm)
npm run screenshots -- --product   # regenerate public/product/app-desk.jpg (the landing product shot), then rebuild
node scripts/pick-windows.mjs      # recompute the hero window and the /app start time from the data
python3 scripts/crop-evidence.py   # recut the before/after slider images from the evt_003 evidence image
```

`/app` URL parameters (demos and screenshots): `?t=<match seconds>&live=1&drawer=1&paused=1`.

## Data

All data is real Phase 3 output from `../samples/w900_1260/` (TeamTrack drone match, 15:00–21:00).
`scripts/copy-samples.mjs` copies the files the app reads into `public/sample/` (gitignored) before
dev / build / test. Components never fetch files: everything goes through `src/data/` (one loader per
resource, runtime validation). When the FastAPI backend exists, only `src/data/source.ts` changes.
No match video is shipped: the pitch is drawn from the tracked positions; in `/app` a coach can pick a
local video file, which stays in the browser.

## Decisions that differ from docs/UI_DESIGN.md (second pass, user decided)

1. **Colour scheme: dark hero, light body.** Only the landing hero is dark (night / floodlight).
   Everything below it uses a light token set (`.theme-light` in `src/index.css`, next to the dark
   `:root` set): bg `#F3F5EF`, surface `#FFFFFF`, text `#0B1510` (16.9:1), muted `#4A5C52` (6.5:1),
   accent text `#4A6B00` (5.6:1), warn `#9A5B00`, danger `#C2183F` — all text pairs WCAG AA.
   Team colours are darker on light (`#D93A2F`, `#0A7FB0`) and used for dots only (≥ 3:1).
   A fixed backdrop interpolates dark → light over the first 30 % of the first light section
   (instant with reduced motion); the light sections also carry their own light background so
   contrast never depends on scroll position. `/app` stays dark.
2. **No hero video.** The hero is a tilted 2D pitch replaying the real tracked positions of
   19:16–20:20, the longest stretch where both teams keep ≥ 8 outfield players in a team in every
   frame and both shapes are confident (`scripts/pick-windows.mjs`, `src/lib/windows.ts`). It never
   shows "unclear": an unsettled shape shows the last confident one with a "holding" mark.
3. **No motion trails.** Dots show only the current position; movement is the 60 fps interpolation
   between the 2 fps samples.
4. **Pitch orientation.** The pitch is drawn so the home team (White) attacks right. The request was
   "flip x"; a pure x flip would mirror the pitch, so the display uses the same 180° turn as the
   tactics engine (`normalise` in `src/gaffer/tactics/common.py`): x → L − x and y → W − y. The
   minimap now matches the evidence image. Small arrows show each team's direction.
5. **`/app` = progressive disclosure.** Default view: the pitch (or the video with the pitch as an
   inset), the shape timeline and one large alert card. The trace ("How Gaffer checked this") is a
   right-side drawer opened from the card; chat is a small floating button; "Generate report" stays
   in the header and opens the stored report. The brief's list of alert cards in a drawer is replaced
   by one card for the selected change (click a timeline diamond to switch).
6. **`/app` starts at 16:17**, 13 s before the confirmed 16:30 change, the latest moment from which
   White has ≥ 9 and Blue ≥ 8 outfield players in a team in every frame (`pick-windows.mjs`).
7. **Live replay timing comes from the trace.** A change appears when its time is reached; checks
   start once the 60 s look-ahead after detection has been played (the card's "required re-analysis
   span", 18:05 for evt_003) and each step lands after its recorded tool + LLM time (the
   re-analysis was a cache hit in that run; uncached it took 252 s). Live replay plays at 4×.
8. **Landing copy.** One idea, one statement or number and one short line per section; every caveat
   moved into a "Read the small print" accordion per section (none removed). Sections: hero, product
   shot, how it works, a sticky "verified, not guessed" story of the real evt_003 trace, before/after
   slider (the two evidence panels), results, where OpenCV 5 / AWS are used (EC2, S3, CloudWatch
   marked "being deployed"), limits, FAQ. The brief's "layer toggles" section is not built.
9. **Hero second button says "How it checks"** (brief: "How it works").
10. **Timeline labels** are drawn only where they fit completely (measured), never truncated; below
    640 px the bars carry no text and a full-width list of every change is the control.
11. **Accordions and the drawer animate opacity and transform only**; height changes are instant.
12. **Screenshots live in `web/screenshots/`** (the brief says `docs/screenshots/`; `docs/` is not
    edited from the web branch).

## Licences

All dependencies are MIT / ISC; fonts (Space Grotesk, Inter, JetBrains Mono, via Fontsource) are SIL OFL 1.1.
TeamTrack data: Scott et al., 2024, MIT licence. Lighthouse was run with `npx lighthouse@12.8.2`
(Apache-2.0), not added as a dependency.
