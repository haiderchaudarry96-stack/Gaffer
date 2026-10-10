# CLAUDE.md — Gaffer

Read this file at the start of every session. Update the **Current status** section at the end of every session.

---

## What this project is

**Gaffer** is an AI football tactical analyst for coaches. It watches match video with **OpenCV 5**, works out each team's formation over time, detects when a team **switches shape during the match**, and an AI agent **verifies each detected change by sending OpenCV back to look again** before alerting the coach with visual evidence and asking for approval.

Built for the **OpenCV AI Competition 2026, powered by AWS** (opencv26.devpost.com).
Final deadline: **26 October 2026, 11:45 PM Pacific (Devpost) = 27 October, 11:45 AM Pakistan time.** There are **no fixed dates per phase** — the user may finish the whole project in about a week. Work as fast as quality allows: build the simplest version that meets each phase's acceptance criteria first, then polish. Keep the last two days before the official deadline as buffer, and say early if a phase is slipping.

One-line pitch: *Broadcast-level tactical analysis costs clubs thousands. Gaffer gives any coach a tactical analyst that watches the match, spots the moment the opponent changes shape, and checks its own eyes before it speaks.*

---

## Work on the current phase only

The project is built in six phases (0–5). **Do only the phase the user has just pasted in.** Never start, scaffold, stub out or "get a head start on" a later phase, even when it looks trivial and even when the current phase finishes early. `docs/PLAN.md` describes all phases so you understand where the current one fits — it is context, not a work queue.

When a phase's acceptance criteria are met: stop, show the results, update **Current status** below, show `git status` with a suggested commit message, and wait. The user starts the next session.

---

## Read these before working

- `docs/PLAN.md` — phases, dates and acceptance criteria. Check the criteria before declaring a phase done.
- `docs/DATA_CONTRACT.md` — the frozen schemas. Read before touching any code that produces or consumes match data.
- `docs/DATA_SOURCES.md` — footage, model weights and **licences**.
- `docs/FAILURE_LOG.md` — log failure cases and limitations **as they happen**. The judges explicitly require failure cases as evidence.
- `docs/UI_DESIGN.md` — the frontend design brief (Phase 4): Veo-inspired professional sports-tech look, Gaffer's own brand, animations, free/open-source stack only.
- `docs/DATA_NOTES.md` — what the real data actually looks like (written in Phase 0 by inspecting it). Trust it over assumptions.

---

## The data we have

**Main real footage: TeamTrack** (Nagoya University) — MIT licence, Kaggle `atomscott/teamtrack`. Credit: *Scott et al., "TeamTrack: A Dataset for Multi-Sport Multi-Object Tracking in Full-pitch Videos", 2024* + the MIT notice, in README and report.

Already downloaded by the user (test split only, a subset of files):

```
data/teamtrack/
  soccer_top/   videos/*.mp4  annotations/*.csv    # drone, top-down view
  soccer_side/  videos/*.mp4  annotations/*.csv    # fixed fisheye side view
```

- File names like `D_20220220_1_1530_1560.mp4` — each clip is ~30 s; consecutive names are consecutive segments of the same match. Concatenate in order for longer sequences.
- Annotation CSVs are a **multi-row-header** table (SportsLabKit style): header rows `TeamID`, `PlayerID`, `Attributes` (`bb_left`, `bb_top`, `bb_width`, `bb_height`), then one row per `frame`. Roughly 23 objects × 4 columns. Read with pandas using a multi-level header; verify the exact layout in Phase 0 and write it down in `docs/DATA_NOTES.md`.
- The annotations give **ground-truth boxes and team IDs for every frame**. They are our evaluation backbone: detection precision/recall, team-classification accuracy, and an **"oracle" `MatchState`** built from ground-truth boxes, so formations from our OpenCV pipeline can be compared with formations from perfect detections.
- Videos are large and gitignored. `scripts/download_teamtrack.py` (Phase 2) re-downloads exactly the files we use, for reproducibility.

**Hard-mode clip (optional): "2019-11-10: U13 CCL VLSC vs SOCA"** by YouTube channel *Bil Kleb* — CC BY licence, `youtube.com/watch?v=3vxIlarKxjw`. Elevated camera that **pans and zooms**. The user has asked the owner for the original file; use it only if a legitimate file is available. Youth players: never identify anyone, no face close-ups in the demo.

**Synthetic data** (Phase 1) — exact ground truth for formation changes, which real clips cannot provide in volume.

**Own futsal footage** — unlikely. Keep pitch size and formation templates config-driven so futsal (40×20 m, 4 outfield players, 2-2 / 1-2-1 / 3-1 / 4-0) can be added without code changes if footage appears.

---

## Non-negotiable constraints (from the official rules)

1. **OpenCV 5 must do substantive image/video analysis.** Not just reading frames. In Gaffer, OpenCV 5 does: detection inference (`cv2.dnn`), team colour clustering (`cv2.kmeans` in HSV/Lab), fisheye correction (`cv2.fisheye`), pitch line detection and **homography** (`cv2.findHomography`, `cv2.perspectiveTransform`), camera-motion compensation (`cv2.calcOpticalFlowPyrLK` + `cv2.estimateAffinePartial2D`), and evidence rendering. Pin `opencv-contrib-python>=5.0,<6` (headless variant on the server). Print `cv2.__version__` in the smoke test and the README.
2. **A meaningful component must run on AWS.** Our plan: the perception/vision tools run on **EC2**, the agent's LLM runs on **Amazon Bedrock**, clips and outputs live in **S3**, logs and metrics go to **CloudWatch**.
3. **Agentic Vision Award rule:** OpenCV output must **change what the agent does next** (a later tool call, an action, or a request for human approval). *A chatbot that only explains a fixed vision result does not qualify.* Every design decision in `agent/` must keep this true and provable from the trace.
4. **No pirated broadcast footage and no copyrighted music.** Only clips we own or whose licence permits this use. Record every source in `docs/DATA_SOURCES.md` and `data/README.md`.
5. **Secrets never get committed.** `.env` is gitignored; `.env.example` is not. On EC2, use an **IAM instance role**, never access keys on disk.
6. **No AGPL dependencies (no Ultralytics YOLO).** The code does not have to be open source for this competition, but the repo stays MIT so it remains a clean portfolio project. Before adding any dependency, check its licence is MIT / Apache 2.0 / BSD or similar and say so when you propose it.
7. **Pinned dependencies + clear build/deploy/test instructions** are a submission requirement. Keep `requirements.lock` (exact versions) up to date whenever a dependency changes.

### Judging (weights)

| Criterion | Weight | What it means for us |
|---|---|---|
| Technical execution — correctness and depth of OpenCV 5 | **30%** | OpenCV does the real vision work; measured accuracy and FPS |
| Innovation | 20% | Self-verifying agent: vision results drive the next action |
| Real-world impact | 20% | Grassroots coaches have no access to tactical analysis |
| User experience | 10% | Professional, animated sports-tech UI per `docs/UI_DESIGN.md`; a coach understands it in 30 seconds |
| Documentation & presentation | 10% | Technical report, architecture diagram, ≤5 min video |
| Cloud delivery, reproducibility, responsible operation | 10% | AWS deploy, pinned deps, observability, privacy |

Unlike a pure-AI hackathon, **UX and impact are scored here** — the UI must look like a real product (see `docs/UI_DESIGN.md`), but never at the cost of the vision pipeline or the evaluation. Frontend stack is free/open-source only (React, Vite, Tailwind, Motion, Lenis); no paid APIs or assets anywhere in the project.

---

## Architecture

```
video clip ─► PERCEPTION (OpenCV 5) ─► match_state.json ─► TACTICS ENGINE ─► tactical_timeline.json
(TeamTrack     cv2.dnn detector          (data contract)    formations,        candidate shape changes
 top / side,   + ByteTrack                                  metrics,                   │
 or synthetic) + cv2.kmeans teams                           change detector            ▼
               + cv2.fisheye undistort                                      AGENT (Amazon Bedrock)
               + homography                                  ┌──────────────────────────┤
               + camera-motion comp.                         │                          │
                       ▲                                     │ perceive → decide → act  │
                       │   vision tools (run OpenCV on EC2)  │                          │
                       └─── check_frame_quality ◄────────────┤ low confidence? look     │
                            reanalyse_window   ◄─────────────┤ again at higher fps      │
                            render_evidence    ◄─────────────┤ confirmed? build proof   │
                                                             │                          │
                                                             └─► propose_alert ─► COACH APPROVES / REJECTS
                                                                                        │
                                                                    WEB UI: video + 2D pitch + alerts + chat
AWS:  S3 (clips, outputs, evidence PNGs) · EC2 (FastAPI + perception) · Bedrock (LLM) · CloudWatch (logs/metrics) · IAM role · Budget alarm
```

### Central design rule 1 — the data contract

`match_state.json` is a **frozen contract** (see `docs/DATA_CONTRACT.md`). Both the synthetic generator and the real video pipeline emit it, identically. The tactics engine and the agent only read the contract.

Why: the tactics engine and agent can be built and tested on synthetic data with ground truth, and the synthetic data gives us **measurable accuracy numbers** that real footage alone cannot.

Never change the contract after Phase 1 without telling the user the migration cost.

### Central design rule 2 — the agentic vision loop

The tactics engine only produces **candidate** shape changes. The agent decides what happens to each one:

1. Read the candidate (team, time, from → to, confidence).
2. Call `check_frame_quality` on that window (OpenCV: players visible, camera cut detected, homography reprojection error).
3. If quality is poor or confidence is low → call `reanalyse_window` (OpenCV re-runs perception on that window at a higher sampling rate) and read the new result.
4. Decide: **confirm** → `render_evidence` (annotated frame + minimap PNG) → `propose_alert` which waits for the coach to approve; or **reject** with a reason; or **mark uncertain** and say why.

The trace must show, step by step, that an OpenCV result changed the next call. This is what the Agentic Vision Award checks.

### Central design rule 3 — query, never stuff

The LLM never receives raw pixels or thousands of coordinates. Tools return **small JSON**. Keep every tool result compact.

### Grounding rule

Every tactical claim cites a timestamp and the metric or tool result it came from. If the data does not support a claim, the agent says so. An agent that admits uncertainty beats one that bluffs.

---

## Repo layout

```
src/gaffer/
  schema.py               # pydantic models — the data contract
  config.py               # loads config.yaml
  llm/bedrock_client.py   # Bedrock Converse API: chat, tool calling, retries, usage logging
  perception/             # detector (cv2.dnn), tracker, team_classifier, pitch (homography), camera_motion, pipeline
  tactics/                # formation, events, metrics, timeline
  agent/                  # tools (data + vision), loop, report, alerts
  api/                    # FastAPI app + static frontend
  aws/                    # s3 helpers, cloudwatch metrics
scripts/                  # smoke tests, inspect_data, make_synthetic_match, eval_synthetic,
                          # teamtrack_to_matchstate, download_teamtrack, calibrate, eval_real, eval_agent
tests/                    # pytest (LLM always mocked)
data/                     # teamtrack/ (videos gitignored), synthetic/, labels/, data/README.md with licences
outputs/                  # generated artefacts, llm_calls.jsonl, agent_trace.jsonl, alerts.jsonl
deploy/                   # Dockerfile, EC2 setup script, docs
docs/                     # PLAN, DATA_CONTRACT, DATA_SOURCES, FAILURE_LOG, TECHNICAL_REPORT, architecture.png, demo_script
config.yaml               # every threshold, window size, template, model id, region
requirements.lock         # exact pinned versions
```

---

## Hardware and environment reality

- User's laptop: **Windows, Intel Iris integrated GPU, no NVIDIA GPU.** CPU-only must always work. Prefer small models and generous frame sampling (2–5 fps is enough for formations).
- Default Python on the laptop is **3.14**, which many ML packages do not support yet. **Use Python 3.12 in a venv** (`py -3.12 -m venv .venv`). Use `py`, not `python`, in PowerShell commands.
- **No PyTorch needed.** Detection runs through `cv2.dnn` on an ONNX model. This keeps installs small, makes OpenCV the inference engine (good for the 30% criterion), and avoids Python-version problems.
- **AWS setup (already done by the user — do not redo it):**
  - Region **ap-southeast-2 (Sydney)** for everything. The Free-plan account's project is locked to Sydney; other regions require upgrading to the Paid plan — never suggest that.
  - Laptop credentials: IAM user **`Gaffer-dev`** via `aws configure` (default profile, stored in `~\.aws`). `aws sts get-caller-identity` works. Never ask for, print, or write keys anywhere.
  - `Gaffer-dev` currently has **only `AmazonBedrockFullAccess`**. Anything else (S3, EC2, CloudWatch) needs the user to add permissions in the console — tell them exactly which, least privilege, in Phase 4.
  - **Model: Amazon Nova 2 Lite**, base model id `amazon.nova-2-lite-v1:0`. In Sydney it runs only through a **cross-region inference profile** (on-demand is not supported): **`global.amazon.nova-2-lite-v1:0`** (confirmed with `aws bedrock list-inference-profiles`, 9 Oct, in `config.yaml`). Backup model: **Nova Micro**, **`apac.amazon.nova-micro-v1:0`** (confirmed). Model id is config-only, never hard-coded.
  - Third-party models (Anthropic etc.) are blocked on the Free plan by a service control policy. Use Amazon Nova only.
  - **Known issue (Oct 2026):** the new account's Bedrock quotas show **0 TPM / 0 RPM** for all Nova models, so real calls return `ThrottlingException: Too many tokens per day`. Quota increases to the default values were requested on 9 Oct. Until approved: build and test against a mocked client, make the smoke test report the throttling clearly (not a traceback), and re-run it when the user says quotas are approved. **Update 9 Oct (evening): real calls now succeed** for both Nova 2 Lite and Nova Micro (plain + tool calling), so the quota appears to be live; the client still fails fast with a clear message if daily-token throttling comes back.
  - Claude Code on this laptop has the **AWS agent toolkit skills and the AWS MCP server** installed. They are allowed for reading/inspecting (listing models, profiles, quotas). Never use them to **create, modify or delete** AWS resources without stating the cost and getting the user's explicit OK first.
- AWS is needed in **Phase 0** (Bedrock smoke test), **Phase 3** (Bedrock agent) and **Phase 4** (EC2, S3, CloudWatch, IAM role). Phases 1–2 need no AWS.
- AWS account is on the **Free plan** with credits. Before suggesting any AWS resource, state its approximate hourly/monthly cost and check it is allowed on the Free plan. Never create anything expensive without asking.
- Work in `C:\OpenCV hackathon\gaffer` (path has a space: quote it in shell commands), never inside OneDrive.
---

## Conventions

- Python 3.12. Type hints and docstrings everywhere. `ruff` for lint, `pytest` for tests.
- **Every** threshold, window size, formation template, colour range, model id and AWS region lives in `config.yaml`. Nothing hard-coded.
- Fixed random seed `42` wherever randomness appears.
- Graceful, specific errors: missing AWS credentials, Bedrock model not enabled, missing ONNX weights, no calibration file, too few visible players, unreadable video. Never a bare traceback for a foreseeable condition.
- Log every LLM call (model, tokens, latency) to `outputs/llm_calls.jsonl`; every agent tool call (args, result, duration) to `outputs/agent_trace.jsonl`; every alert and the coach's decision to `outputs/alerts.jsonl`. In the deployed app, also send these to CloudWatch.
- Tests mock the LLM. Never spend Bedrock credits inside `pytest`.
- Print a per-stage timing summary for anything that processes video.
- **Never run `git add`, `git commit` or `git push`.** The user commits and pushes manually after each phase. To show what changed, use `git status` / `git diff` only, and suggest a meaningful commit message.
- Never read or print files in `~\.aws`.

---

## How to work with the user

- At the start of a phase: **propose the module plan and wait for approval** before writing code.
- The user is a CS student. When a decision involves licensing, AWS cost, or football tactics, explain the reasoning in a sentence or two rather than deciding silently.
- If a phase is going sideways, say so plainly instead of piling on patches.
- When you hit a real failure case (wrong formation, lost tracks, bad homography), add it to `docs/FAILURE_LOG.md` with a screenshot path. These become evidence in the report.

---

## Commands

```powershell
# setup (Windows)
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env            # AWS profile/region, never keys in git

# smoke tests + data inspection
py scripts\smoke_test_opencv.py
py scripts\smoke_test_bedrock.py
py scripts\inspect_data.py              # writes docs\DATA_NOTES.md + sample frames

# synthetic data + tactics eval
py scripts\make_synthetic_match.py --out data\synthetic\match_001.json
py scripts\eval_synthetic.py --heldout # OFFICIAL: held-out seeds 100-109 (--no-equivalence = ablation)
py scripts\eval_synthetic.py           # match_001 + seeds 43-52 (tuning-time set); --dev = tuning seeds
py -m gaffer.tactics.timeline --match data\synthetic\match_001.json --out outputs\tactical_timeline.json
py scripts\plot_formation_windows.py --team home --start 1450 --end 1900 --out outputs\failures\<name>.png

# real video (TeamTrack)
py scripts\teamtrack_to_matchstate.py --view top      # oracle MatchState from ground-truth boxes
py scripts\calibrate.py --view top      # landmarks: data\calibration\top_points.json (--click to re-pick)
py scripts\calibrate.py --view side     # compares homography / sectioned / cv2.fisheye / cylindrical
py -m gaffer.perception.pipeline --source data\teamtrack\soccer_top\videos\<clip>.mp4 --out outputs\match_state.json
py scripts\eval_real.py                  # detection P/R, team accuracy, formation: pipeline vs oracle

# agent
py -m gaffer.agent.loop --match outputs\match_state.json
py scripts\eval_agent.py           # one-shot alerts vs self-verifying agent

# app
uvicorn gaffer.api.main:app --reload

# checks
ruff check . ; pytest -q
```

---

## Key numbers to keep updated

These go into the technical report, README and video. Re-measure at the end of each relevant phase.

- OpenCV version: `5.0.0` (`opencv-contrib-python==5.0.0.93`)
- YOLOX-S (COCO) via `cv2.dnn`, laptop CPU: ~115–145 ms per 640×640 inference; side view 11 persons on a native crop, 0 on the full frame; top view ~1/12 recall (Phase 0 smoke test)
- Bedrock smoke test (Nova 2 Lite): plain call 2.1 s / 93 tokens; tool round trip 2 calls, ~2.1 s / 2,100 tokens
- **Official synthetic numbers = held-out seeds 100–109** (10 matches never used before, engine unchanged since Phase 1; see FAILURE_LOG 2026-10-10 held-out entry):
  - Formation accuracy per 30 s window: **97.0 % when confident** (97.5 % family), coverage 79.3 %; full view 96.8 % / coverage 99.9 %; broadcast window 98.6 % / coverage 29.3 %; strict (uncertain = wrong) 76.9 %. Upper bound: generator and engine share one model of a formation.
  - Shape changes (36 true, ±90 s): **31 hits / 5 misses (4 found late after low visibility) / 52 false positives (36 are 4-3-3 ↔ 4-2-3-1 flips, 33 of them in 2 matches) / mean delay 51 s** (max 105 s), new formation right 30/31. Timeline max **15.3 KB** (breaks the 8 KB target on 2 matches), mean 7.2 KB.
  - Without the 3-5-2 = 5-3-2 equivalence: same accuracy (97.0 %), same hits, **67** false positives, timeline max 16.4 KB → the equivalence (decided after seeing eval seeds) generalises.
  - Tuning-time eval set (seeds 42–52, superseded, kept for history): 96.4 % when confident, 39/43 hits, 27 FPs, 41 s delay, timeline max 7.9 KB. Tactics engine ~20–30 s per 90-min match on laptop CPU.
  - **One-shot detector baseline for Phase 3 = the held-out 52 false positives** (31/36 hits): the self-verifying agent must beat this.
  - Timeline size: worst case **16.4 KB** (held-out, no equivalence; 15.3 KB with it). Limit relaxed on 10 Oct from 8 KB to **"compact, under 20 KB"**: in Phase 3 the agent reads the timeline through tools, never as one blob. Do not tune the engine for size.
- TeamTrack detection precision / recall (top view, side view): `TBD`
- TeamTrack team-classification accuracy: `TBD`
- Formation agreement, OpenCV pipeline vs oracle (ground-truth boxes): `TBD`
- Perception throughput — laptop CPU FPS, EC2 FPS: `TBD`
- Pitch size fitted from IFAB markings (31 top-view landmarks): **105.9 × 68.2 m** → within 2 %, so config keeps 105 × 68.
- Calibration, held-out (leave-one-out) landmark error / line-alignment error: **top 0.11 m mean, 0.38 m max / 0.036 m median** (single homography, 31 landmarks); **side 0.53 m mean, 1.77 m max / 0.08 m median** (2 sectioned homographies, 29 landmarks; single homography 0.60 m, `cv2.fisheye` 0.86 m, cylindrical does not fit). Per-clip drift re-anchoring error: `TBD`.
- Alerts: one-shot detector vs self-verifying agent — false alerts / missed changes: `TBD vs TBD`
- Mean agent latency per alert, mean Bedrock tokens per alert, cost per match: `TBD`

---

## Current status

**Phase:** 2 — in progress (Day 1). Calibration done for both views; **stopped for the user to check the calibration overlays** before building on them.
**Bedrock model + region:** `global.amazon.nova-2-lite-v1:0` (fallback `apac.amazon.nova-micro-v1:0`), ap-southeast-2. Real calls + tool calling work.
**Done:** Phase 0 + Phase 1: contract frozen at v1.0 (`schema.py`; nullable segment metrics, GT `noise_events`/`visibility`); synthetic 90-min generator (`gaffer/synthetic.py`, decoys, broadcast-window visibility, 2 fps, match file gitignored); tactics engine (template fit with Hungarian assignment, families `3-5-2`≈`5-3-2`, hysteresis detector, metrics, <8 KB timeline); 65 tests (47 new); eval numbers above; 5 failure cases logged with images.
**Phase 2 so far (10 Oct):** Step 0 held-out check recorded (official synthetic numbers above; `eval_synthetic.py --heldout`). `perception/pitch.py` (pitch model, top-hat line mask, landmark snapping, pitch-size fit, homography, leave-one-out + line-alignment error), `perception/undistort.py` (side-model comparison, bird's-eye rectification), `scripts/calibrate.py`, `data/calibration/*`, 8 new tests (73 total). Findings: the side panorama is near-rectilinear, not a fisheye; top and side clips are NOT simultaneous (no cross-view check possible); DATA_NOTES corrected. `supervision` 0.30.9 installed and locked. `*.clips.json` convention documented (DATA_CONTRACT, data/README.md).
**Next:** once the user approves the overlays: oracle (`teamtrack_to_matchstate.py`) + min-players coverage report (stop if low), top-view detector comparison (classical vs tiled YOLOX), per-clip drift re-anchoring; then Day 2 (side detection, tracking with ID switches at 2 vs 5 fps, team colours, pipeline, eval_real). Tactics engine must run on pipeline/oracle output unchanged.
**Blockers:** none

<!-- Update the five lines above at the end of every session. Keep it short. -->
