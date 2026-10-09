# Gaffer — Build Plan (OpenCV AI Competition 2026)

**Official deadline: 26 October 2026, 11:45 PM Pacific (Devpost) = 27 October, 11:45 AM Pakistan time.**
**No fixed dates per phase.** Go as fast as quality allows — the whole project may take about a week. Submit at least **two days before** the official deadline. In every phase, the simplest version that passes acceptance comes first; polish second.

A phase is finished only when its **acceptance criteria** are all true and the work is committed. Do not start the next phase before that.

Order matters: OpenCV is 30% of the score, so real-video perception is a core phase here, **not** a cuttable extra.

---

## Phase 0 — Scaffold + prove the stack works
**Order: first. Small — usually under a day.**

Remove the three risks that could kill the project on day one: Python environment, OpenCV 5, and Bedrock access.

**Build**
- Repo skeleton, `pyproject.toml`, `requirements.lock`, `.env.example`, `.gitignore`, MIT `LICENSE`, README stub, `config.yaml`
- `scripts/smoke_test_opencv.py` — prints `cv2.__version__` (must be 5.x), loads the ONNX detector with `cv2.dnn`, runs it on one image, saves an annotated output, prints inference time
- `src/gaffer/llm/bedrock_client.py` — Bedrock **Converse API** via `boto3`: chat, **tool calling**, retries with backoff, usage + latency logging to `outputs/llm_calls.jsonl`
- `scripts/smoke_test_bedrock.py` — one plain call, then one tool-calling call with a dummy tool, printing reply, latency, tokens
- `scripts/inspect_data.py` — **data inspection (EDA)** of `data/teamtrack/`, see below → `docs/DATA_NOTES.md` + images in `outputs/eda/`

**Data inspection (EDA) — what `inspect_data.py` must answer**
1. Inventory: which videos and CSVs exist per view, file sizes, which CSV belongs to which video, are clips consecutive
2. Video metadata with OpenCV: resolution, fps, frame count, duration, codec; does the frame count match the CSV row count
3. CSV structure: exact header rows, how to load it with pandas (multi-level header), column naming, units (pixels?), missing values / NaN pattern
4. Per frame: number of annotated objects, per `TeamID`; which TeamIDs exist (2 teams? referee? ball? goalkeepers?)
5. Box sizes: width/height distribution in pixels per view (how small are far players → detector input size)
6. Fisheye side view: how strong is the distortion at the edges (visual check)
7. Pitch: are pitch lines and corners visible in the top view; estimate pitch size in metres if possible
8. Visual output: for 3 frames per view, the frame with ground-truth boxes drawn and coloured by TeamID; a heat-map of player positions; a plot of objects-per-frame over time
9. Anything surprising, written as a short list in `docs/DATA_NOTES.md`

**Acceptance**
- [ ] Python 3.12 venv works; `cv2.__version__` starts with `5`
- [ ] `cv2.dnn` produces person boxes on a test image
- [ ] `docs/DATA_NOTES.md` explains the TeamTrack format with real numbers, and the GT-box images look right
- [ ] A real Bedrock reply comes back; tool calling works end to end (or: client fully tested against a mock and marked "blocked on AWS quota" until the increase is approved)
- [ ] Model id and region live in `config.yaml` and `CLAUDE.md`
- [ ] Missing AWS credentials / model not enabled → clear message, not a traceback

---

## Phase 1 — Synthetic match data + tactics engine
**No video, no LLM.**

**Build**
- `schema.py` — `MatchState`, `TacticalTimeline` per `docs/DATA_CONTRACT.md`, validated and versioned
- `scripts/make_synthetic_match.py` — 90-minute two-team match, realistic shape + noise, ball drift, half-time side switch, **scripted formation changes at known times**, plus some **partial-visibility frames** (fewer than 22 players) to mimic a real camera; ground truth saved separately
- `tactics/formation.py` — rolling window, attacking-direction normalisation, line clustering, template matching, confidence
- `tactics/events.py` — per-team change detector with hysteresis (candidate only after ≥20 s persistence); emits events with `status: "candidate"`
- `tactics/metrics.py` — defensive line height, compactness, width, centroid, pressing proxy
- `tactics/timeline.py` — compact `tactical_timeline.json`
- `scripts/eval_synthetic.py`

**Acceptance**
- [ ] Formation accuracy printed as a number
- [ ] Shape changes: hits / misses / false positives / mean delay printed
- [ ] A 3-second flicker does **not** produce an event (test)
- [ ] Full-match timeline under ~8 KB
- [ ] Tests pass

---

## Phase 2 — Real video perception with OpenCV 5
**Core phase — this is the 30% criterion. Biggest phase; give it the most time.**

**Build**
Footage: **TeamTrack** `soccer_top` (main) and `soccer_side` (fisheye), see `docs/DATA_NOTES.md`. Optional hard-mode clip with a panning/zooming camera.

- `perception/detector.py` — ONNX detector through **`cv2.dnn`** (players, goalkeepers, referee, ball if available), NMS, confidence threshold and sampling rate from config; tiled / higher-resolution inference if far players are too small (measure)
- `perception/fisheye.py` — undistort the side view with **`cv2.fisheye`** (calibrate from pitch lines, which must become straight)
- `perception/tracker.py` — `supervision` ByteTrack (MIT) for persistent IDs
- `perception/team_classifier.py` — torso crop, grass masked out in HSV, **`cv2.kmeans`** into 2 teams + referee, per-track majority vote, `"unknown"` until settled
- `perception/pitch.py` + `scripts/calibrate.py` — manual 4+ point calibration → **`cv2.findHomography`** → metres on a 105×68 m pitch; optional automatic white-line detection (`cv2.inRange` + `cv2.HoughLinesP`) to refine
- `perception/camera_motion.py` — if the camera pans: track background features with **`cv2.calcOpticalFlowPyrLK`**, estimate motion with **`cv2.estimateAffinePartial2D`**, update the homography between keyframes; detect hard camera cuts
- `perception/pipeline.py` — video in → contract-valid `match_state.json` out (with per-frame quality), per-stage timing summary
- `scripts/teamtrack_to_matchstate.py` — the **oracle**: ground-truth boxes + TeamIDs → `MatchState` (`source: "annotation"`) using the same homography
- `scripts/eval_real.py` — against TeamTrack ground truth: detection precision/recall (IoU ≥ 0.5), team-classification accuracy, and **formation agreement: tactics engine on pipeline output vs on the oracle**
- `scripts/download_teamtrack.py` — re-downloads exactly the files we use (reproducibility)
- `data/README.md` — every clip with source, licence and credit

**Acceptance**
- [ ] TeamTrack top-view clips → `match_state.json` that validates; side view after fisheye correction too
- [ ] Tactics engine runs on it **with no code change**
- [ ] Detection P/R, team accuracy and formation agreement vs oracle measured, per view
- [ ] Laptop CPU FPS and homography reprojection error measured
- [ ] At least 3 real failure cases written in `docs/FAILURE_LOG.md`

**Timebox:** if after about two working days nothing usable comes out, simplify (fixed camera, manual calibration only, shorter clip) — do not abandon real video.

---

## Phase 3 — The agentic vision loop (Bedrock)
**This wins the Agentic Vision Award.**

**Build**
- `agent/tools.py`
  - data tools: `get_match_overview`, `get_formation_at`, `list_candidate_changes`, `get_metrics`, `compare_windows`
  - **vision tools (run OpenCV):** `check_frame_quality`, `reanalyse_window`, `render_evidence`
  - **action tool:** `propose_alert` — creates a pending alert that needs coach approval
- `agent/loop.py` — perceive → decide → act loop per candidate change; grounding rule; confirm / reject / uncertain with a reason
- `agent/alerts.py` — alert store with `pending / approved / rejected`, written to `outputs/alerts.jsonl`
- `agent/report.py` — coach report: formation story, each confirmed change and what it was probably trying to fix, 3 recommendations, every claim cited
- Trace logging to `outputs/agent_trace.jsonl`
- `scripts/eval_agent.py` — **one-shot detector (alert on every candidate) vs self-verifying agent**: false alerts, missed changes, latency, tokens, cost — on synthetic (with injected noise/occlusion) and the real clip
- `docs/agent_workflow.png` — perception → decision → action diagram (required for the award)

**Acceptance**
- [ ] A trace shows an OpenCV tool result changing the agent's next call
- [ ] At least one candidate rejected because re-analysis did not confirm it
- [ ] Alerts wait for coach approval; decisions logged
- [ ] Measured difference between one-shot and agent written into `CLAUDE.md`
- [ ] Agent logic tested with a mocked LLM

---

## Phase 4 — Web app + AWS deploy
**UX is 10% of the score and the first thing judges see — see `docs/UI_DESIGN.md`.**

**Build**
- FastAPI backend serving a **React + Vite + Tailwind + Motion** frontend (all MIT, free) built to `docs/UI_DESIGN.md`
- **Landing page** (`/`): Veo-inspired product story — video hero, 01/02/03 steps, before/after drag slider, On/Off layer toggles on a live pitch, sticky "verified, not guessed" story, count-up results, tech cards, FAQ
- **App** (`/app`): video player · synced 2D minimap with formation label · per-team formation timeline with change markers · **alert cards with evidence image and Approve / Reject buttons** · "how I checked this" trace · chat · "Generate report"
- **"Live replay" mode**: plays the match as if live; candidates appear and get verified at the moment they happen
- AWS: Docker image on **EC2** (instance role, no keys), **S3** for clips/outputs/evidence, **Bedrock** for the agent, **CloudWatch** logs + a few custom metrics (FPS, agent latency, alerts), **AWS Budgets** alarm
- `deploy/` — Dockerfile, setup script, step-by-step deploy doc

**Acceptance**
- [ ] Public URL loads in under 5 s with pre-processed matches
- [ ] A vision tool call actually runs OpenCV on EC2 during the demo
- [ ] A stranger understands the screen in 30 s
- [ ] Every item in the "Quality bar" of `docs/UI_DESIGN.md` is met (performance, accessibility, reduced motion, no copied brand)
- [ ] Clean redeploy from the docs works
- [ ] Budget alarm set

---

## Phase 5 — Submission package
**No new features.** (Draft the report and demo script in parallel from Phase 3 onward so this phase is assembly, not writing from scratch.)

**Build**
- `docs/TECHNICAL_REPORT.md` — problem, users, architecture, OpenCV 5 implementation, AWS deployment, evaluation, limitations, failure cases, responsible use
- README for judges: pitch, GIF, architecture diagram, quickstart, key numbers, **"Where OpenCV 5 is used"**, **"Where AWS is used"**, agent trace example
- `docs/architecture.png` and `docs/agent_workflow.png` final
- `docs/demo_script.md` — **≤5 min** video script (see below)
- Final audit

**Video plan (≤ 5:00)**
| Time | Content |
|---|---|
| 0:00–0:25 | Team on camera + the problem (grassroots coaches have no analyst) |
| 0:25–0:50 | What Gaffer does in one sentence |
| 0:50–2:40 | Live demo: live replay → candidate change → agent looks again → evidence → coach approves |
| 2:40–3:40 | Architecture: OpenCV 5 pieces, AWS pieces, agent loop trace |
| 3:40–4:30 | Results + honest failure cases |
| 4:30–4:50 | Impact + close |

**Acceptance**
- [ ] Every Final Submission Requirement on the Devpost page ticked
- [ ] Quickstart works on a clean clone
- [ ] Video public/unlisted, under 5 minutes, no copyrighted music
- [ ] Demo URL live and staying live through judging (27 Oct – 9 Nov)
- [ ] Submitted on Devpost at least **two days before** the deadline

---

## Order at a glance

| Phase | Must be true at the end |
|---|---|
| 0 | OpenCV 5 works, data inspected, Bedrock client ready (real call or mock) |
| 1 | Synthetic eval prints real numbers |
| 2 | TeamTrack clip → valid `match_state.json`, accuracy measured |
| 3 | Trace proves vision changes the agent's next action |
| 4 | Professional animated web app live on AWS |
| 5 | Report + video done, submitted |

**Real footage: ✅ TeamTrack downloaded on 9 Oct.**

**AWS by phase:** Phase 0 → Bedrock (smoke test via `aws configure` credentials). Phases 1–2 → none. Phase 3 → Bedrock (agent). Phase 4 → EC2, S3, CloudWatch, IAM instance role, Budgets. Phase 5 → nothing new.

---

## Risks

| Risk | Mitigation |
|---|---|
| TeamTrack clips too short for real shape changes | Concatenate consecutive clips; shape changes are proven on synthetic data, TeamTrack proves perception accuracy; fetch more soccer clips with the download script if needed |
| Fisheye distortion breaks homography | Undistort first with `cv2.fisheye`; top view is the fallback main clip |
| Detector too weak on small far-away players | Higher input resolution on crops, lower sampling fps, football-specific ONNX model as fallback |
| Panning camera breaks homography | Camera-motion compensation; fallback: fixed-camera clip only |
| Python 3.14 package problems | Python 3.12 venv; no PyTorch |
| AWS card / Free-plan limits | Test account on day 0; check service availability before designing around it |
| Credits run out during judging | Small instance, budget alarm, pre-processed matches, LLM mocked in tests |
| Agent looks like a chatbot | Vision tools + approval action + trace proof — Phase 3 acceptance |
| Last-minute video panic | Script written in Phase 5 before recording |

---

## Cut list

If time runs short, cut in this order. Never cut upward.

1. Best Use of COOL path (only if everything else is done early)
2. Automatic white-line detection (manual calibration is enough)
3. Chat panel (alerts + report are enough)
4. Pressing metrics (formation + compactness is enough)
5. Camera-motion compensation + hard-mode clip (TeamTrack cameras are fixed)
6. Fisheye side view (top view alone is enough)

**Never cut:** OpenCV perception on real video, the agentic vision loop with approval, the AWS deployment, the evaluation numbers, failure cases, the technical report, the video.
