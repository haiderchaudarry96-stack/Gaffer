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

`/app` URL parameters (demos and screenshots): `?t=<match seconds>&live=1&drawer=1&paused=1&upload=1`.

### Connecting the backend: `VITE_API_URL`

| `VITE_API_URL` | Meaning | Use |
|---|---|---|
| empty / unset | **not connected**: static demo build; upload and chat say plainly that the server is not connected; demo data from the bundled `public/sample/` | static hosting of the demo |
| `/` (or `same-origin`) | **the API is on the server that serves this site**: relative URLs (`/api/...`) | the combined app: one `uvicorn` serving `web/dist` and the API |
| `http://localhost:8000` (any URL) | the API on another origin (CORS: `config.yaml` `api.cors_origins`, credentials allowed) | development: Vite on :5173, uvicorn on :8000 |

```bash
# combined app (one server): build once, then the API serves the site at /
VITE_API_URL=/ npm run build                      # PowerShell: $env:VITE_API_URL="/"; npm run build
cd .. && uvicorn gaffer.api.main:app              # http://localhost:8000/ and /app

# development: hot reload against a local API
VITE_API_URL=http://localhost:8000 npm run dev    # http://localhost:5173
```

**Windows, Git Bash:** do not build with `VITE_API_URL=/ npm run build` in Git Bash: MSYS path
conversion rewrites `/` into `C:/Program Files/Git/`, the site then requests
`file:///C:/Program%20Files/Git/api/...` and nothing loads (seen 21 Oct). Use PowerShell
(`$env:VITE_API_URL="/"; npm run build`), or `MSYS_NO_PATHCONV=1 VITE_API_URL=/ npm run build`.

The value is baked in at build time (Vite). **Connected** (any non-empty value):

- **Demo match** from the API: the files from `GET /api/demo/files/<name>` (the same files as
  `samples/w900_1260/`, nothing bundled is read) and the alert from `GET /api/demo/alerts`.
- **Alerts**: Approve / Reject call `POST /api/alerts/{id}/approve|reject`. On the demo the decision
  is **this visitor's only** (an anonymous cookie; other visitors still see the alert waiting; a
  server restart forgets it); on an uploaded analysis it is saved on the server for everyone
  (`outputs/alerts.jsonl`). No Undo when connected (the server records a decision once).
- **Upload**: choose a video → **Upload** → the server's pitch step:
  `needs_confirmation` → **"Is this your pitch?"** on the outline OpenCV found
  (`pitch.preview_url`): *Yes, looks right* → `POST /api/analyses/{id}/pitch {confirmed: true}`;
  *No, let me adjust* → the guided 4-point screen on the server's reference frame
  (`GET /api/analyses/{id}/frame`), preloaded with `pitch.corners` (draggable) →
  `POST /pitch {pitch_points}`. `needs_corners` → the same 4-point screen, preloaded with
  `pitch.suggested_corners` when OpenCV has a guess (Reset clears it). A known TeamTrack drone clip
  skips the pitch step. Then progress (polled every 2 s) → the result replaces the demo (pitch,
  timeline, alert card, trace, report, chat). A video the browser cannot decode can still be uploaded
  (the server reads it with OpenCV); it just does not play next to the analysis.
- **Chat**: `POST /api/chat` with the visitor cookie (daily question cap per visitor).

End-to-end check (Playwright + the pre-installed Chromium, screenshots in `screenshots/integrate/`):
`scripts/e2e-integrate.mjs` (usage in its header; `../scripts/serve_no_bedrock.py` runs the same app
with Bedrock switched off, so no AWS call is made).

## Data

All data is real Phase 3 output from `../samples/w900_1260/` (TeamTrack drone match, 15:00–21:00).
`scripts/copy-samples.mjs` copies the files the app reads into `public/sample/` (gitignored) before
dev / build / test. Components never fetch files: everything goes through `src/data/` (one loader per
resource, runtime validation). The static frontend does not ship match video. With the FastAPI
backend connected, **Live analysis** plays the allowlisted TeamTrack top-view clips for 15:00–21:00
beside the tactical map; both follow the same match clock. The UI labels this as recorded footage,
not a connected camera feed. Candidate cards come from the N1 event API;
the persisted verification result stays hidden until the stored match-clock evidence boundary.

To prepare the local TeamTrack demo event from the existing OpenCV-produced `w900` MatchState and
the normal rules verifier (no annotations and no Bedrock call), run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/run_agent_video.py --sets w900 --arm rules --fresh --candidates evt_003 --out outputs/agent_video_teamtrack_replay --persist-teamtrack-events
```

`evt_003` is the current OpenCV-generated candidate id for the White 4-4-2 → 3-4-3 example in this
saved `MatchState`; the UI does not special-case it and reads whichever event rows exist in SQLite.
Remove `--candidates evt_003` to verify and persist every candidate (a longer run). The command
writes verified event rows to `api.event_store.path` and evidence/trace artifacts to the output
directory. Keep the dataset files under `data/teamtrack/`; the replay API serves them from a fixed
allowlist and supports byte-range seeking.

The Live analysis setup asks which side the coach represents, the objective (chase, protect, or
balanced), and which substitute roles are actually available. At a confirmed event's stored
verification boundary, the UI requests a deterministic N4 role suggestion from persisted N3 posture
evidence and this context. Missing context/evidence, own-team events, and unsupported posture show a
withheld state without an action. Any suggestion is conditional and role-level; it does not name a
player or make a substitution. Accept/reject and an optional note are stored against that specific
recommendation, separately from the formation alert decision. No Bedrock call is made for N4.

## Decisions that differ from docs/UI_DESIGN.md (second pass, user decided)

1. **Colour scheme: dark hero, light body.** Only the landing hero is dark (night / floodlight).
   Everything below it uses a light token set (`.theme-light` in `src/index.css`, next to the dark
   `:root` set): bg `#F3F5EF`, surface `#FFFFFF`, text `#0B1510` (16.9:1), muted `#4A5C52` (6.5:1),
   accent text `#4A6B00` (5.6:1), warn `#9A5B00`, danger `#C2183F` — all text pairs WCAG AA.
   Team colours are darker on light (`#D93A2F`, `#0A7FB0`) and used for dots only (≥ 3:1).
   A fixed backdrop interpolates dark → light over the first 30 % of the first light section
   (instant with reduced motion); the light sections also carry their own light background so
   contrast never depends on scroll position. (`/app` was dark until the third pass; see 14.)
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
7. **Match replay timing comes from the trace.** A change appears when its time is reached; checks
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
13. **The landing header is always white** (light tokens, solid white `bg-surface`), also over the
    dark hero (user decision after the second pass), with a soft shadow once the page scrolls.

### Third pass (user feedback after running the site locally)

14. **`/app` is light**, with the same tokens and the same white header (shadow when scrolled) as
    the landing body. Reverses "/app stays dark".
15. **Light 2D pitch** wherever the pitch sits on a light background (`/app`, the landing story):
    white grass with pale-green mowing stripes (`#EAF4E4`), thin grey lines (`#B5BFB6`), coral
    `#F2483B` for White and sky blue `#0A8FD4` for Blue (both ≥ 3:1 on white), keepers as ringed
    dots, officials as small dark grey dots (`#4B5563`), players OpenCV has not put in a team yet
    as hollow grey rings. No trails, no glow. Tokens: `--pitch-*` in `src/index.css`. The landing
    hero keeps its dark pitch. Orientation unchanged (home attacks right, like the evidence image).
16. **Upload for analysis** (the full frontend flow; the backend plugs in through
    `src/data/analysis.ts`): a small "Upload for analysis" button with a tooltip and, on the first
    visit, a pulsing lime dot (until the first interaction or 5 s; none with reduced motion).
    The panel: choose an MP4/MOV (drop or button; name, size, duration and size in pixels read in
    the browser) -> **"Show us where the pitch is"** -> analyse. The pitch step never says
    calibration, homography or corners: it shows the first frame, a glowing numbered target and one
    instruction per click ("1. Click the top-left corner of the pitch", ...), placed points keep
    their number and are draggable (tooltip "Pitch corner 2 of 4. Drag to adjust."), undo and
    reset, a "Why do we ask?" popover, a looping illustration of a tilted pitch straightening into
    a flat map (static with reduced motion), and "My video already looks straight down on the full
    pitch" (fills the frame edges; "Use this only for a straight top-down view"). Keyboard: arrow
    keys move the target (Shift = bigger steps), Enter places it, a focused point moves with the
    arrow keys; the next instruction is announced (aria-live). **Without `VITE_API_URL`, "Start
    analysis" shows "Analysis server not connected in this demo build"** and offers "Open the
    analysed demo match instead" (the chosen file then plays next to the stored analysis). No fake
    progress, no fake results. With a backend: upload % -> server stages and progress -> the result
    replaces the demo in the same views (pitch, timeline, alerts, chat).
17. **Agent mascot** (`src/components/mascot/Mascot.tsx`, original inline SVG: a robot with a
    football head, dark visor, cyan eyes, smile, silver headset with microphone, green jersey with
    navy trim and an "AI" badge; eyes blink every ~6 s, not with reduced motion). It is the chat
    button, the alert card avatar and the drawer header icon.
18. **Chat**: the round mascot button (soft lime ring, small three-dot bubble) expands on hover,
    keyboard focus or tap into a 360 × 480 chat box (header "Gaffer · Your tactical analyst",
    suggested questions built from the real timeline, input "Ask Gaffer about this analysis").
    It collapses when the pointer leaves with an empty input, on a tap outside, or on Escape;
    focus is trapped while it is open. Sending goes through `src/data/chat.ts`; without a backend
    it says "The agent runs in Gaffer's Python backend on Amazon Bedrock; answers go live when this
    site is connected to it." and marks a sent question as not sent.
19. **Drawer summary**: the coach-facing line is just "Confirmed by the agent at 16:30" (or the
    event's decision). The LLM call count, cost, rules verdict and the honest note sit in a
    collapsed "Technical details" toggle (text unchanged).

### Desk modes (22 Oct: /app no longer opens on the finished demo)

| Mode | How you get there | What is shown |
|---|---|---|
| **idle** (default) | `/app` | A decorative pitch (11 neutral drifting dots, a scan line; still with reduced motion) labelled "Waiting to start", the start panel ("Live analysis — recorded TeamTrack match (simulation)", "Upload your own video", link "Review a completed analysis") and an empty timeline. No match data, video, chips, alert or chat. |
| **live** | Live analysis setup → Start | The recorded TeamTrack video plays from 15:00. Dots come from the MatchState frame at the playhead, formation chips and the timeline are cut at the playhead (`data/liveSession.ts revealTimeline`), the 16:30 candidate is "checking" from its onset and verified only from its stored boundary (18:05); seeking back hides it again. A reading strip shows frames read and detections so far. Coach decisions (alert approve / reject, advice accept / reject) are kept for this session only and never read from or written to the shared demo stores; "Start a new session" (setup dialog) starts fresh. No chat (it knows the whole match). |
| **review** | "Review a completed analysis", `?mode=review` (or the old `?t=` / `?live=1` / `?drawer=1` links) | The finished demo analysis in full, labelled "Completed analysis", with Match replay, report and chat. |
| **upload** | an upload finishes | The finished upload in full ("Completed analysis"), with "Replay in match time" (the same reveal, from the upload's start). |

"Start screen" in the header returns to idle from any mode.

Stage layout (22 Oct): whenever there is a video (the recorded replay in live and review, or an
uploaded file) the video panel and the tactical pitch sit side by side at the same width, stacked
(video on top) below 900 px, with one transport (play / pause, seek, 1x / 2x / 4x) and no native
video controls or picture-in-picture minimap. A file the browser cannot decode keeps its panel with
"This browser can't preview the file; the analysis below still comes from it." A finished
analysis without candidates says why when the clip is under 120 s ("Gaffer needs about a minute
after a change to confirm it; this clip is N s long.").

## Backend API (as used by the frontend)

The full reference is `../docs/API.md`. All JSON; base URL from `VITE_API_URL` (above). Errors: a
non-2xx status with `{"detail": "<message>"}` (FastAPI's default); the UI shows the detail. Types
live in `src/data/analysis.ts`, `src/data/chat.ts` and `src/data/types.ts` (MatchState,
TacticalTimeline, Alert, trace steps as in `docs/DATA_CONTRACT.md` and `docs/AGENT_DESIGN.md` §7).
Tests: `src/data/api.test.ts` (mocked fetch).

| Method and path | Request | Response |
|---|---|---|
| `GET /api/demo/files/{name}`, `GET /api/demo/alerts` | — | a demo file; the demo alerts with this visitor's decisions |
| `POST /api/analyses` | `multipart/form-data`, field `video` (MP4/MOV) | `201` AnalysisStatus (`queued`, `needs_confirmation` or `needs_corners`) |
| `POST /api/analyses/{id}/pitch` | `{"confirmed": true}` or `{"pitch_points": [[x, y]×4]}` (top-left, top-right, bottom-right, bottom-left, video pixels of the server's reference frame) | AnalysisStatus (`queued`) |
| `GET /api/analyses/{id}/frame`, `.../pitch-preview` | — | JPEG: the reference frame; the frame with the outline |
| `POST /api/analyses/{id}/start` | `{"points": [{x,y}×4], "frame": {"width","height","t_s"}, "straight_down": bool}` (kept; the connected UI uses `/pitch`) | AnalysisStatus |
| `GET /api/analyses/{id}` | — | AnalysisStatus |
| `GET /api/analyses/{id}/result` | — (only when `status = "done"`) | AnalysisResult |
| `POST /api/alerts/{id}/approve`, `.../reject` | optional `{"note"}` | the Alert with its new status |
| `POST /api/chat` | `{"match_id", "question", "history": [{"role": "user"\|"assistant", "text"}]}` | `{"answer", "citations": ["R2", "evt_003", …], "trace_id"}` |

- **AnalysisStatus**: `{"id", "status": "uploaded"|"needs_confirmation"|"needs_corners"|"queued"|
  "running"|"done"|"failed", "stage": "uploading"|"detecting"|"teams"|"agent"|"done", "progress":
  0..1 (overall), "eta_s": number|null, "error": string|null, "pitch": {state, corners,
  suggested_corners, preview_url, message}|null, "video": {width, height, duration_s, …}}`. The UI
  polls every 2 s and labels the stages Uploading, Detecting players (OpenCV), Teams and formations,
  Agent checking changes, Done (a `queued` analysis shows "waiting for the analyser").
- **AnalysisResult**: `{"id", "label", "match_state": MatchState, "timeline": TacticalTimeline,
  "alerts": [Alert], "trace": [trace step], "report": CoachReport|null}`. Evidence images in alerts
  should be absolute URLs the backend serves.
- The time estimate in the UI uses the measured 1.2 s of processing per second of drone video
  (laptop CPU), plus agent checks; the server's `eta_s` is shown when it sends one.

## Licences

All dependencies are MIT / ISC; fonts (Space Grotesk, Inter, JetBrains Mono, via Fontsource) are SIL OFL 1.1.
TeamTrack data: Scott et al., 2024, MIT licence. Lighthouse was run with `npx lighthouse@12.8.2`
(Apache-2.0), not added as a dependency.
