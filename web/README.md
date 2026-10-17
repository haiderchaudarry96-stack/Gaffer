# Gaffer web app (Phase 4 frontend)

React + Vite + TypeScript + Tailwind CSS + Motion. Two routes: `/` (landing page) and `/app` (analyst desk).
Design brief: `../docs/UI_DESIGN.md`.

```bash
cd web
npm install
npm run dev          # copies ../samples into public/sample, then starts Vite on http://localhost:5173
npm run build        # type-check + production build to dist/
npm run lint         # ESLint (incl. jsx-a11y)
npm test             # vitest: loads every sample file through src/data and checks its shape
npm run screenshots  # after a build: Playwright + the pre-installed Chromium -> screenshots/
```

## Data

All data is real Phase 3 output from `../samples/w900_1260/` (TeamTrack drone match, 15:00–21:00).
`scripts/copy-samples.mjs` copies the files the app reads into `public/sample/` (gitignored) before
dev / build / test. Components never fetch files: everything goes through `src/data/` (one loader per
resource, runtime validation). When the FastAPI backend exists, only `src/data/source.ts` changes.

No match video is shipped. The pitch animations are drawn from the tracked positions in
`match_state`; in `/app` you can pick a local video file, which stays in the browser.

## Licences

All dependencies are MIT / ISC; fonts (Space Grotesk, Inter, JetBrains Mono, via Fontsource) are SIL OFL 1.1.
TeamTrack data: Scott et al., 2024, MIT licence.
