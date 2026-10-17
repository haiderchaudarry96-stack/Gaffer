# Gaffer API (Phase 4 backend)

FastAPI app in `src/gaffer/api/` (`create_app` in `main.py`). One process serves the API, runs the
analysis worker (one analysis at a time) and, when `web/dist` exists, the built frontend at `/`.
Settings: `config.yaml` → `api:` (limits, caps, demo, storage) and `calibration.four_corner` /
`calibration.auto_detect` (pitch step). Nothing in `api:` can change an agent decision: the rules
fingerprint stays **`ca4ff9bbf7b01c6c`** (reported by `/api/health` and in every finished analysis).

```powershell
uvicorn gaffer.api.main:app --reload            # laptop, http://localhost:8000 (docs at /docs)
```
Docker: `deploy/README.md`.

## Conventions

- JSON everywhere. Errors: non-2xx with `{"detail": "<message>"}` (FastAPI's default). Every
  foreseeable refusal is written for a coach (what is wrong and what to do), e.g.
  *"This video is 9.5 minutes long; the limit is 6 minutes. Trim it to the part of the match you
  want analysed and upload it again."*
- Analysis ids: 12 lowercase hex characters. Match ids inside results: `up_<id>`; alert ids
  `alr_up_<id>_evt_nnn` (the Phase 3 convention `alr_<match_id>_<event_id>`).
- Image URLs in results are absolute (`http://<host>/api/...`), as the frontend expects.
- Responses over 2 KB are gzipped (the demo bundle: 2.1 MB → 0.19 MB). CORS origins: `api.cors_origins`.
- Times are match seconds (`t`, `start_s`) plus `mm:ss` clocks where the agent writes them.

## Endpoints

| Method and path | Request | Response |
|---|---|---|
| `GET /api/health` | — | `{status, opencv_version, rules_fingerprint, bedrock, model_id, region, demo_available, analyses: {running, queued}, usage_today, limits}` |
| `GET /api/demo` | — | the demo match (`samples/w900_1260`) as an **AnalysisResult** + `report_markdown`, `explanations`, `team_model`, `run_rows`, `files` |
| `GET /api/demo/files/{name}` | — | the exact sample file the frontend reads today (whitelist: `api.demo.files`) |
| `GET /api/demo/evidence/{event_id}.jpg` | — | demo evidence image |
| `POST /api/analyses` | `multipart/form-data`: `video` (MP4/MOV, required), `known_source` (`true`/`false`/`auto`, optional), `pitch_points` (JSON `[[x,y]×4]` or `[{x,y}×4]`, optional) | `201` **AnalysisStatus** (`queued`, `needs_confirmation` or `needs_corners`) |
| `POST /api/analyses/{id}/pitch` | `{"confirmed": true}` or `{"pitch_points": [[x,y]×4]}` | AnalysisStatus (`queued`) |
| `POST /api/analyses/{id}/start` | the frontend's pitch step: `{"points": [{x,y}×4], "frame": {width, height, t_s}, "straight_down": bool}` | AnalysisStatus (`queued`) |
| `GET /api/analyses/{id}/pitch-preview` | — | JPEG: the frame with the pitch outline, corners 1–4 and the markings a 4-corner homography puts there |
| `GET /api/analyses/{id}/frame` | — | JPEG: the reference frame (for a 4-point screen) |
| `GET /api/analyses/{id}` | — | AnalysisStatus (poll every 2 s) |
| `GET /api/analyses/{id}/result` | — (`409` until `done`) | **AnalysisResult** |
| `GET /api/analyses/{id}/evidence/{event_id}.jpg` | — | evidence image of a confirmed change |
| `POST /api/alerts/{alert_id}/approve` | optional `{"note": "..."}` | the Alert, `status: approved` |
| `POST /api/alerts/{alert_id}/reject` | optional `{"note": "..."}` | the Alert, `status: rejected` |
| `POST /api/chat` | `{"match_id", "question", "history": [{"role": "user"\|"assistant", "text"}]}`, header `X-Visitor-Id` (optional) | `{answer, citations, trace_id, sources, grounded, questions_left_today}` |
| `GET /`, `/app`, … | — | `web/dist` (single-page app; unknown paths → `index.html`), only when built |

## AnalysisStatus

```jsonc
{
  "id": "27af4f8cb3e1",
  "status": "running",            // uploaded | needs_confirmation | needs_corners | queued | running | done | failed
  "stage": "detecting",           // uploading | detecting | teams | agent | done
  "stage_label": "Detecting players (OpenCV)",
  "progress": 0.157,              // 0..1 overall, never goes backwards
  "eta_s": 76.8,                  // seconds left (null when unknown / done)
  "error": null,                  // coach-readable when failed
  "progress_detail": {"elapsed_s": 16.0, "eta_basis": "measured",
                      "frames": {"done": 410, "total": 720}, "candidates": {"done": 0, "total": 3},
                      "stage_timings_s": {"detecting": 15.5, "teams": 1.1}},
  "video": {"filename": "match.mp4", "bytes": 1044238, "width": 960, "height": 600, "fps": 8.0,
            "frames": 1440, "duration_s": 180.0},
  "source": {"kind": "upload", "reference_frame": 8},   // or {"kind": "teamtrack_top", "note": ...}
  "pitch": {"state": "detected", "corners": [[90.6, 70.0], ...], "detection": {...},
            "message": "...", "preview_url": "http://.../pitch-preview"},
  "queue_position": 0,
  "summary": null,                // when done: candidates, decisions, alerts, arm, llm_down,
                                  // bedrock calls/cost, report_source, rules_fingerprint
  "links": {"self": "...", "result": "...", "pitch_preview": "..."}
}
```

State machine:

```
POST /api/analyses ──► known TeamTrack drone clip ───────────────────────────► queued
                   ──► pitch_points given ───────────────────────────────────► queued
                   ──► auto-detect confident ──► needs_confirmation ─┬─ {confirmed: true} ──► queued
                   │                                                  └─ {pitch_points} ─────► queued
                   └─► auto-detect unsure / no pitch ──► needs_corners ── {pitch_points} ──► queued
queued ──► running (detecting ► teams ► agent) ──► done | failed
```
`/start` (frontend) = `{pitch_points}` (or the frame edges for `straight_down`). The pitch step is
closed once queued (`409`). After a server restart, a `running` analysis becomes `failed`
("upload it again") and `queued` ones are queued again.

**Progress and ETA are measured, never invented.** `progress = elapsed / (elapsed + remaining)`.
*Remaining* = frames left × this upload's measured seconds per frame (detecting), + the team /
tactics step (~5 % of detection, Phase 2), + candidates left × the measured time per checked
candidate — before the first one is checked, `api.jobs.eta_frames_per_candidate` (755) × the
upload's own seconds per frame (4K drone ≈ 226 s; Phase 3 measured 104–252 s + an 8–13 s camera
check). Before any frame is timed, the priors `api.jobs.prior_s_per_video_s` (1.2) and
`prior_s_per_candidate` (200) are used and `eta_basis` says `"prior"`.

## Upload rules (`api.uploads`)

| Rule | Refusal |
|---|---|
| MP4 or MOV | `415` "Gaffer accepts MP4 or MOV videos; …" |
| ≤ 500 MB (`max_bytes`; also checked from `Content-Length` before reading) | `413` |
| OpenCV can open it and decode a frame; it has a frame rate and length | `422` |
| ≤ 6 min (`max_duration_s`), ≥ 5 s | `422` with the length and the limit |
| ≥ 640 px wide; aspect ≤ 2.5 (wider = panorama / side camera) | `422` "top-down views only" |
| TeamTrack side-camera clip (`F_…`) | `422` "top-down (drone) views only" |
| `known_source=true` but not a TeamTrack drone clip | `422` |
| more than `jobs.max_queued` (3) analyses waiting | `503` "busy, try again in a few minutes" |

**Known TeamTrack drone clips** (`D_<date>_<half>_<start>_<end>.mp4` at 3840 × 2160, `known_source`
`auto`/`true`) skip the pitch step: the saved 31-point calibration (`data/calibration/top.json`) is
used, and the match time starts at `<start>` from the file name. If the calibration's reference clip
(`D_20220220_1_1530_1560.mp4`) is not on the server, the same homography is re-anchored to the
upload's first frame (`pitch.method: saved_31_point_reanchored`; the drone drifts up to ~14 px
between clips, Phase 2). `known_source=false` sends a TeamTrack clip through the pitch step.

## Pitch step (non-TeamTrack uploads)

All OpenCV, no learnt model (`perception/pitch.py`, new functions only):

1. **4-corner homography** `four_corner_homography(points, size, 105, 68)`: order **top-left,
   top-right, bottom-right, bottom-left** as seen in the frame; `cv2.getPerspectiveTransform`; the
   longer pair of image edges is the pitch length. Refused (coach-readable): not 4 points, far
   outside the frame, crossed or mirrored order, < 5 % of the frame, or **too tilted** (shorter /
   longer opposite edge < 0.6: not a top-down view).
2. **Auto-detect** `detect_pitch_corners(frame, cfg)` on the frame at 1 s, downscaled to 960 px:
   grass mask (the team classifier's HSV grass band `teams.grass_hue` / `grass_min_saturation`, plus
   a brightness floor) → closing / opening → largest component (`cv2.connectedComponentsWithStats`)
   → convex hull → quadrilateral (`cv2.approxPolyDP`, else `cv2.minAreaRect`) → each edge **snapped
   to the painted boundary line** where visible (top-hat `line_mask`, a 2D offset search for the
   outermost well-supported line, `cv2.fitLine`), corners = intersections.
3. **Confidence** = geometric mean of: quad area share of the frame; aspect vs 105:68; share of the
   edges on painted lines; projected markings (halfway line, circle, boxes through the 4-corner
   homography) vs painted lines (`line_alignment_error`, median ≤ 1.5 m) × share found; corners
   inside the frame. Hard failures (confidence 0): tilted view, clutter (> 8 % of the quad looks
   like paint). Thresholds: `calibration.auto_detect`.
4. **Decision**: confidence ≥ 0.65 and no hard failure → `needs_confirmation` with the corners and
   the overlay JPEG; otherwise → `needs_corners` (a best guess, if any, is in
   `pitch.suggested_corners` for preloading, never used). **Gaffer never analyses on auto-detected
   corners that the coach has not confirmed.**

The calibration is written to `outputs/api/<id>/calibration/top.json` (same format as the 31-point
one); the pipeline and the agent receive a config copy whose `calibration.dir` points there, so the
Phase 2 / 3 code runs unchanged (re-anchoring aligns every frame to the reference frame).

**Accuracy on real footage: to be measured.** On the laptop:
```powershell
py scripts\eval_autodetect.py          # 60 TeamTrack drone clips x 3 frames -> outputs\eval_autodetect.json / .txt
```
It reports success rate, median / worst corner error (m), false accepts / false rejects of the
confidence flag, player-position agreement with the 31-point calibration, a tilted and a cropped
frame that must be refused, and the cost of the 4-corner fallback (perfect and noisy clicks) vs the
31-point calibration. Failure images go to `outputs/failures/autodetect_*.jpg`. On generated frames
only (`--synthetic 12`, also the test): every frame found within 0.11 m, tilted and cropped refused
— generated frames are easy, so this says nothing about real pitches yet.

## The analysis (worker)

One at a time, in this order, all existing code unchanged:

| Stage | What runs |
|---|---|
| `detecting` | `perception.pipeline.run` (top view: re-anchoring, classical detector, ByteTrack, shirt colours at 4 fps); frames counted for progress |
| `teams` | team colours / labels / MatchState (inside the pipeline), then the tactics engine (`MatchContext`: formations, candidate changes) |
| `agent` | Phase 3 `AgentRunner` on every candidate with the video backend (camera check, OpenCV re-analysis, decision by the frozen rules, evidence, pending alert), checked explanations, then the coach report (`agent/report.py`, checked, else template) |

Arm (`api.jobs.arm: auto`): the Nova arm when a Bedrock client can be made and the global daily cap
has room; otherwise the rules arm. If Bedrock fails mid-run, the loop's own fallback finishes with
the rules (`summary.llm_down` says why). Decisions are the rules' either way (Phase 3: 68 / 68 and
14 / 14 identical). Caps: `api.jobs.max_cost_usd_per_analysis` (orchestration),
`presentation.explain` / `presentation.report` (text), and the agent's own per-match OpenCV budget
(1,200 s of re-analysis).

Files in `outputs/api/<id>/` (behind the storage interface; `api.storage.backend: local`, or `s3`:
`gaffer.aws.s3.S3Storage` copies results to `s3://<bucket>/<prefix>/<id>/` and reads them back after
a restart): `upload.mp4|mov`, `upload.json`, `status.json`, `video.clips.json`, `first_frame.jpg`,
`pitch_preview.jpg`, `calibration/top.json`, `match_state.json` + `.teams.json`, `timeline.json`
(verified), `trace.jsonl`, `explanations.json`, `run_rows.json`, `report.json` + `.md`,
`evidence/up_<id>/evt_nnn.jpg`. Alerts go to the shared append-only store
`outputs/alerts.jsonl` (`agent.outputs.alerts`).

## AnalysisResult

`{id, label, kind, match_state, timeline, alerts, trace, report, report_markdown, explanations,
team_model, run_rows, summary}` — `match_state` and `timeline` are the frozen v1.0 contract
(`docs/DATA_CONTRACT.md`; the timeline carries `verification` for decided events), `alerts` are
contract Alerts with their latest state, `trace` is `agent_trace.jsonl` lines (AGENT_DESIGN §7),
`report` is the `agent/report.py` JSON (`inputs`, `report`, `source`), `run_rows` the per-candidate
rows of `scripts/run_agent_video.py`. The demo uses the same shape; its timeline is rebuilt from the
sample MatchState by the tactics engine (same 9 candidate ids) with the stored verdicts filled in.

## Alerts

Approve / reject append to `outputs/alerts.jsonl` through `agent.alerts.AlertStore` (last line per
id wins, history never rewritten). Deciding twice → `409`; unknown id → `404`. The demo alert lives
in `samples/`; its first decision copies it into the store first, then decides it.

## Chat (`POST /api/chat`)

Read-only, over ONE analysis (`match_id` = an analysis id, or `w900_1260` for the demo). Tools: the
agent's five data tools (`get_match_overview`, `get_formation_at`, `list_candidate_changes`,
`get_metrics`, `compare_windows`; same code and schemas as Phase 3) plus `get_decision` (the
agent's verdict, reason and explanation for one candidate) and `get_timeline` (first-pass
segments). No vision tool, no alert, nothing writes.

Grounding (code, `api/chat.py check_answer`): cited `[Rn]` must be results of this question,
`[evt_nnn]` real candidates, an answer with numbers must cite something, every number and mm:ss
clock must appear in this question's tool results (formation digits allowed). A failed check gets
one retry with the problems listed, then a safe reply ("I can't answer that reliably from this
analysis's data. I can tell you …"). Every question is logged to `outputs/api/chat_trace.jsonl`
(question, answer, citations, tools, tokens, cost).

Caps (all in `config.yaml`, changeable without code; restart the server):

| Cap | Setting | When hit |
|---|---|---|
| tokens per question (all rounds) | `api.chat.max_tokens_per_request` (12,000), `max_tool_rounds` (4) | polite "needs more look-ups than one answer is allowed; try a narrower question" |
| questions per visitor per UTC day | `api.chat.max_questions_per_visitor_per_day` (20); visitor = `X-Visitor-Id` header, else client IP, stored hashed | `429` "You've reached today's limit of 20 questions" |
| Bedrock calls / cost per UTC day, whole API (chat + analyses) | `api.bedrock_daily.max_calls` (300), `max_cost_usd` (1.00), persisted in `outputs/api/usage.json` | `429` "daily limit for this demo, come back tomorrow"; analyses fall back to the rules arm |

Bedrock unreachable (no credentials, network, throttling) → `503` "The analyst (Amazon Bedrock)
can't be reached right now: …", and the question is given back to the visitor's allowance. No
Bedrock configured → `503` "needs Amazon Bedrock, which is not configured on this server". The LLM
client is injected (`create_app(llm_factory=...)`); tests use a scripted fake, never the network.

## Tested here, not tested here

Tested in the cloud session (no AWS, no TeamTrack videos): 51 new tests (205 in all) (`tests/test_api.py`,
`test_pitch_corners.py`, `test_eval_autodetect.py`) with generated videos and a mocked LLM,
including a 3-minute generated upload where the agent confirms a 4-4-2 → 3-5-2 change with an
OpenCV re-analysis and the coach approves the alert; a clean virtualenv install from
`requirements.lock` and a real `uvicorn` + `curl` run, serving the built frontend.

**Not tested yet:** real Bedrock calls from the API (chat, Nova arm on uploads); any real
non-TeamTrack footage (pitch detection, the classical drone detector at other resolutions and
camera heights); `eval_autodetect.py` on TeamTrack; S3 against AWS; the Docker image (the sandbox
could not pull a base image).

## Known limits

- Top-down views only; a panning or zooming camera is refused by the agent's camera check (Phase 3).
- The classical drone detector was tuned on 4K TeamTrack footage (~28 px per metre). On a generated
  960 px clip (~7 px/m) it also picked up painted-line junctions (penalty-box and goal-area corners)
  as players: lower-resolution uploads will be noisier.
- The ball, possession and pressing are not measured on the drone view.
- One analysis at a time; others wait (up to 3) — a 6-min 4K clip takes ~7 min of OpenCV on the
  laptop CPU plus the agent checks (up to ~20 min of re-analysis budget).
