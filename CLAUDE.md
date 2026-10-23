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
- `docs/AGENT_DESIGN.md` — Phase 3 agent design: tools, decision rules, eval criteria, build order. Read before touching `agent/`.

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
  perception/             # detector (cv2.dnn), tracker, team_classifier, pitch (homography), drift, pipeline
                          # (camera_motion.py was cut 15 Oct: pan/zoom cameras are a stated limitation)
  tactics/                # formation, events, metrics, timeline
  agent/                  # tools (data + vision), loop, verify, vision, explain, report, alerts
  api/                    # FastAPI backend (docs/API.md): main (routes), uploads (rules), calib
                          # (pitch step), jobs (single worker, progress), results (demo + analyses),
                          # chat (read-only, grounded, capped), usage (daily caps), storage
  aws/                    # s3.py (S3Storage, same interface as local storage); assets.py (S3 asset fetch at container start)
scripts/                  # smoke tests, inspect_data, make_synthetic_match, eval_synthetic, eval_autodetect,
                          # teamtrack_to_matchstate, download_teamtrack, calibrate, eval_real, eval_agent,
                          # tune_teams / tune_officials / tune_line_drop (dev data only)
tests/                    # pytest (LLM always mocked)
data/                     # teamtrack/ (videos gitignored), synthetic/, labels/, data/README.md with licences
outputs/                  # generated artefacts, llm_calls.jsonl, agent_trace.jsonl, alerts.jsonl
deploy/                   # Dockerfile (one process, builds web/), start.sh, ec2/ (bootstrap, deploy, CloudWatch agent), aws/ (IAM policies, SSM helper), DEPLOY_AWS.md
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
py scripts\eval_synthetic.py --heldout2 # OFFICIAL since 15 Oct: seeds 110-119 (--no-change-equivalence = ablation)
py scripts\eval_synthetic.py --heldout  # seeds 100-109 (official 10-14 Oct, now seen; --no-equivalence = ablation)
py scripts\eval_synthetic.py            # dev set "seeds 42-52" = match_001 + 43-52; --dev = old seeds 1000-1002
py scripts\tune_line_drop.py            # line_drop X/Y sweep on the dev set (no GT: false-alarm rate only)
py -m gaffer.tactics.timeline --match data\synthetic\match_001.json --out outputs\tactical_timeline.json
py scripts\plot_formation_windows.py --team home --start 1450 --end 1900 --out outputs\failures\<name>.png

# real video (TeamTrack)
py scripts\download_teamtrack.py --check              # verify the 26 TeamTrack files (size + SHA-256); no flag = download
py scripts\download_teamtrack.py --list               # other soccer clips on Kaggle (anonymous)
py scripts\teamtrack_to_matchstate.py --view top      # oracle MatchState from GT boxes (+ coverage)
py scripts\teamtrack_to_matchstate.py --view side --gt-inset   # labelled variant: GT foot moved up 2.5 px
py scripts\eval_drift.py                               # drone re-anchoring: none / per clip / per frame
py scripts\compare_detectors.py --view top             # classical vs tiled YOLOX; --dev = tuning clip only
py scripts\compare_detectors.py --view side            # MOG2 background vs tiled YOLOX, seq 2 fps, near/far halves
py scripts\coverage_check.py --view top                # detection-limited >= 8 outfield coverage
py scripts\calibrate.py --view top      # landmarks: data\calibration\top_points.json (--click to re-pick)
py scripts\calibrate.py --view side     # compares homography / sectioned / cv2.fisheye / cylindrical
py -m gaffer.perception.pipeline --source data\clips\teamtrack_top.clips.json --out outputs\match_state_top.json --debug-video outputs\debug_top.mp4
py -m gaffer.perception.pipeline --source data\teamtrack\soccer_top\videos\<clip>.mp4 --out outputs\match_state.json   # view from video size
py scripts\eval_tracking.py --view top --track-fps 4 --whole-source --save   # IDs, teams, detection vs GT; --dev = tuning
py scripts\eval_tracking.py --view side --track-fps 2 --whole-source --save  # (writes the MatchStates eval_real reads)
py scripts\eval_real.py --tag after      # pipeline vs oracle: formations, metric error, events, coverage (dev + eval)
py scripts\plot_line_levels.py --view top --out outputs\failures\<name>.png   # line level, pipeline vs oracle
py scripts\tune_teams.py                 # team-colour settings on the dev clips only (3-class crop accuracy)
py scripts\tune_officials.py             # officials (touchline) rule on the dev clips only
# second eval set (teamtrack.clip_sets.eval2; never tuned on, NOT independent of eval): outputs\run_second_set.sh
py scripts\teamtrack_to_matchstate.py --view top --set eval2          # oracle_top_eval2.json (+ side, side --gt-inset)
py scripts\eval_tracking.py --view top --set eval2 --track-fps 4 --whole-source --save   # eval_second_set_tracking_top.json
py scripts\eval_real.py --set eval2                                    # eval_second_set_real.json

# generalisation (23 Oct): unseen Zenodo ground + per-video self-calibration (perception.self_calibration)
py scripts\eval_zenodo.py --tag final --image 20.0          # P/R/F1, teams, coverage on Zenodo tune (0-10 s) + TEST (10-26.7 s); --cfg KEY=VALUE
py scripts\tune_selfcal.py --variant base: --variant x:perception.self_calibration.shadows=false   # dev-only sweeps (TeamTrack dev + Zenodo 0-10 s)
sh scripts/run_selfcal_regression.sh <tag> [KEY=VALUE ...]  # TeamTrack eval + eval2 tracking + eval_real, tagged outputs (Git Bash)
py scripts\upload_check.py --video data\sample_clips\teamtrack_top_0900_1260_4k.mp4 --out outputs\upload_check\x --compare-demo [--perception-only]   # normal upload path, Bedrock off
py scripts\eval_tracking.py --view top --dev --track-fps 4 --cfg perception.self_calibration.adaptive_gate=false --tag _x   # any switch off
node web\scripts\screenshot-upload.mjs <video.mp4> <out-dir>   # app UI upload + screenshots (needs serve_no_bedrock.py --port 8011)

# agent (docs/AGENT_DESIGN.md)
py scripts\eval_agent.py --set dev [--grid]   # one-shot vs rules arm, dev seeds 42-52 (thresholds set here only)
py scripts\eval_agent.py --set val            # validation seeds 100-109 (never tuned on)
py scripts\eval_agent.py --set final --final --arms oneshot,rules,llm --max-cost-usd 2   # DONE 17 Oct (run once); re-running only re-scores from cache + rows (resume, fingerprint guard)
py scripts\flip_experiment.py                 # Task A (OFF): 4-3-3/4-2-3-1 metric check, LOSO CV on 42-52 + 100-109
py scripts\return_leg_experiment.py           # R experiment (OFF): return leg rejected only if P fails, LOSO CV
py scripts\teamtrack_to_matchstate.py --view top --set full   # oracle 0-1800 s (60 clips, ~19 min)
py scripts\oracle_sustained.py --rules        # oracle candidates + sustained changes (>= 120 s, >= 60 % share)
py scripts\run_agent_video.py --out outputs\agent_video_final --sets eval2,eval,side_eval2 [--arm llm --max-cost-usd 0.5]
py scripts\run_agent_video.py --out outputs\agent_video_taskE --sets w900 --candidates evt_003,evt_007 [--arm llm]   # needs the 900-1260 s pipeline MatchState
py -m gaffer.agent.loop --synthetic-seed 45 --arm rules          # rules arm on one dev match (no LLM)
py -m gaffer.agent.loop --synthetic-seed 45 --arm llm --max-candidates 3 --max-calls 30   # spends Bedrock credits
py -m gaffer.agent.loop --match outputs\match_state_top_eval2_4fps.json --view top --arm rules   # video backend (OpenCV)
py scripts\run_agent_video.py                 # step 5: rules arm on real top candidates (eval2 + eval), resumable
py scripts\run_agent_video.py --sets "" --simulated-pan --bench --render-check eval2:evt_005
py scripts\spike_agent.py --seeds 45 --baseline outputs\spike\spike_20261015T120444.json   # spike, caps 100 calls / 1 USD (spends credits); --resume STAMP
py -m gaffer.agent.alerts --list | --approve <alert_id> [--note ..] | --reject <alert_id>
py scripts\explain_real.py --dev 45           # explanation prompt check on a dev seed (rules decide, Nova words; ~1 cent)
py scripts\explain_real.py                    # step 7: replay the 14 real candidates (no OpenCV), new explanations, decisions asserted
py scripts\explain_real.py --render           # evidence image + pending alert of the confirmed real candidate (step-7 panels)
py -m gaffer.agent.report --match outputs\match_state_top_w900_1260_4fps.json --view top --decided outputs\agent_video_step7\explanations.json --set w900 --alerts outputs\agent_video_step7\alerts_llm.jsonl --out outputs\agent_video_step7\report_w900_1260 [--no-llm]

# app (Phase 4, docs/API.md): one uvicorn serves the site + API
cd web; npm ci; $env:VITE_API_URL="/"; npm run build; cd ..   # "/" = API on this server; empty = static demo
uvicorn gaffer.api.main:app --reload    # http://localhost:8000/ and /app; /api/health, /docs
py scripts\serve_no_bedrock.py --port 8000 --out outputs\api_no_bedrock   # same app, Bedrock off (no AWS call; own events.sqlite3 under --out)
py scripts\make_sample_clip.py         # 30 s 1080p sample clip from a TeamTrack drone clip -> data\sample_clips\ (OpenCV only)
py scripts\analyze_event_posture.py --match-id teamtrack_top_w900_1260 --event-id evt_003   # one Bedrock posture call (spends credits)
py scripts\export_demo_seed.py         # real demo record(s) -> samples\w900_1260\demo_events_seed.json (imported once by a fresh server)
py scripts\rerender_suggestions.py samples\w900_1260\alerts_llm.jsonl   # alert suggestions: code check + template (presentation only)
node web\scripts\e2e-integrate.mjs <pitch-found.mp4> <pitch-unsure.mp4>  # Playwright walkthrough -> web\screenshots\integrate
curl.exe -F "video=@C:\path\match.mp4" http://localhost:8000/api/analyses        # -> needs_confirmation / needs_corners / queued
curl.exe -X POST -H "Content-Type: application/json" -d "{\"confirmed\": true}" http://localhost:8000/api/analyses/<id>/pitch
curl.exe http://localhost:8000/api/analyses/<id>                                   # poll; then /result
py scripts\eval_autodetect.py          # pitch auto-detect vs the 31-point calibration on 60 drone clips (run 17 Oct: 180 / 180 after the edge fix)
py scripts\eval_autodetect.py --synthetic 12   # same metrics on generated frames (no data needed)
docker build -f deploy/Dockerfile -t gaffer:latest . ; docker run --rm -p 8000:8000 -v "${PWD}/outputs:/app/outputs" gaffer:latest   # builds web/ itself

# AWS (N6a, deploy/DEPLOY_AWS.md): live http://13.210.196.109/ ; instance i-0ed7553a2ab9a1d16 ; bucket gaffer-demo-221039325928
py deploy\aws\make_iam_policies.py 221039325928 outputs\aws_iam   # GafferDeploy + gaffer-ec2-role policies (console)
git archive --format=tar.gz -o gaffer-<sha>.tar.gz <sha> ; aws s3 cp gaffer-<sha>.tar.gz s3://gaffer-demo-221039325928/src/   # redeploy step 1
py deploy\aws\ssm_run.py i-0ed7553a2ab9a1d16 3600 <script>   # run a script on the instance via SSM (redeploy step 2: deploy/ec2/deploy.sh)
aws ec2 stop-instances --region ap-southeast-2 --instance-ids i-0ed7553a2ab9a1d16   # ~$0.22/day stopped vs ~$3.10/day running

# checks
ruff check . ; pytest -q
```

---

## Key numbers to keep updated

These go into the technical report, README and video. Re-measure at the end of each relevant phase.

- OpenCV version: `5.0.0` (`opencv-contrib-python==5.0.0.93`)
- YOLOX-S (COCO) via `cv2.dnn`, laptop CPU: ~115–145 ms per 640×640 inference; side view 11 persons on a native crop, 0 on the full frame; top view ~1/12 recall (Phase 0 smoke test)
- Bedrock smoke test (Nova 2 Lite): plain call 2.1 s / 93 tokens; tool round trip 2 calls, ~2.1 s / 2,100 tokens
- **Official synthetic numbers since 15 Oct = held-out seeds 110–119** (first run 15 Oct, final config, engine unchanged since Phase 1 apart from two options that are off by default; `eval_synthetic.py --heldout2`):
  - Formation accuracy per 30 s window: **97.7 % when confident** (98.3 % family), coverage 79.3 %; full view 97.6 % / coverage 99.8 %; broadcast window 98.0 % / coverage 31.6 %; strict 77.4 %.
  - Shape changes (38 true, ±90 s): **34 hits / 4 misses (3 found late after low visibility) / 34 false positives / mean delay 42 s** (max 125 s), new formation right 31/34. FP causes: set piece 14, other 11 (18 of the 34 are 4-3-3 ↔ 4-2-3-1 flips, 16 in seed 111), partial view 8, counter 1. Timeline max **14.0 KB**, mean 6.3 KB.
  - **One-shot detector baseline for Phase 3 = 34 false positives, 34/38 hits on seeds 110–119** (replaces 52 FPs / 31 of 36 on 100–109). The self-verifying agent must beat this.
  - 4-3-3 = 4-2-3-1 as a change-only family (measured, **off**): 110–119 FPs 34 → 16 but hits 34 → 28 (all 6 lost are real 4-3-3 ↔ 4-2-3-1 switches); dev set (42–52) FPs 27 → 18, hits 39 → 36. Unlike 3-5-2 = 5-3-2 it is not free (FAILURE_LOG 2026-10-15).
  - `line_drop` (implemented, **off**): synthetic GT cannot label drops (contract v1.0); best dev setting 12 m / 180 s still gives 1.55 false alarms per match (dev), **1.70 per match on 110–119**; 0 events on the real clips.
  - Dev set check (match_001 + 43–52, `eval_synthetic.py`): reproduces 10 Oct exactly with the final config (96.4 % when confident, 39/43 hits, 27 FPs, 41 s, 7.9 KB).
- History: official synthetic numbers 10–14 Oct = held-out seeds 100–109 (now seen: the 4-3-3 ↔ 4-2-3-1 problem was found on them; see FAILURE_LOG 2026-10-10 held-out entry):
  - Formation accuracy per 30 s window: **97.0 % when confident** (97.5 % family), coverage 79.3 %; full view 96.8 % / coverage 99.9 %; broadcast window 98.6 % / coverage 29.3 %; strict (uncertain = wrong) 76.9 %. Upper bound: generator and engine share one model of a formation.
  - Shape changes (36 true, ±90 s): **31 hits / 5 misses (4 found late after low visibility) / 52 false positives (36 are 4-3-3 ↔ 4-2-3-1 flips, 33 of them in 2 matches) / mean delay 51 s** (max 105 s), new formation right 30/31. Timeline max **15.3 KB** (breaks the 8 KB target on 2 matches), mean 7.2 KB.
  - Without the 3-5-2 = 5-3-2 equivalence: same accuracy (97.0 %), same hits, **67** false positives, timeline max 16.4 KB → the equivalence (decided after seeing eval seeds) generalises.
  - Tuning-time eval set (seeds 42–52, superseded, kept for history): 96.4 % when confident, 39/43 hits, 27 FPs, 41 s delay, timeline max 7.9 KB. Tactics engine ~20–30 s per 90-min match on laptop CPU.
  - One-shot baseline until 14 Oct: 52 false positives (31/36 hits) on 100–109; superseded (see above).
  - Timeline size: worst case **16.4 KB** (held-out, no equivalence; 15.3 KB with it). Limit relaxed on 10 Oct from 8 KB to **"compact, under 20 KB"**: in Phase 3 the agent reads the timeline through tools, never as one blob. Do not tune the engine for size.
- TeamTrack detection, **top view (classical OpenCV detector)**, 8 eval clips / 48 frames (dev clip D_…_1530 excluded): **P 0.843 / R 0.978 / F1 0.906 at ≤ 1 m** (IoU ≥ 0.5: P 0.718 / R 0.832); recall on isolated players 0.991; position error 0.17 m; ~4.0 unmatched per frame = referee + assistant referee + staff, 3.0 of them outside the lines (GT has no referee labels). Tiled YOLOX (COCO, cv2.dnn) on the same view: R 0.06 (5.0 s/frame), conf 0.1 R 0.14, 2× upscaled tiles R 0.54 (18 s/frame) → rejected, no fine-tuning needed. **Side view (tiled YOLOX, cv2.dnn)**, 3 eval clips / 150 frames: F1 **0.49 at ≤ 1 m raw, 0.75 with the GT box margin removed, 0.78 at ≤ 2 m** (near half 0.91 / far half 0.66 at 2 m); 3.4 s/frame. MOG2 background baseline: 0.29 / 0.53 / 0.56, 0.16 s/frame → rejected (dev clip: YOLOX 0.72 / 0.73 / 0.87).
- **Pipeline output vs GT, final settings (15 Oct: top tracks at 4 fps, officials rule, dev-chosen team colours)** (eval [dev]): **top @1 m 0.858 / 0.974** [0.857 / 0.986], with referee-labelled detections removed **1.000 / 0.957** [0.999 / 0.982]; **side @2 m 0.794 / 0.771** [0.857 / 0.894], referee-labelled removed **0.888 / 0.744** (was 0.831 / 0.747) [0.950 / 0.888]. Unmatched detections labelled referee: top 99.8 % (was 98.9 %), side 53 % (was 24 %); side unmatched labelled "away" 47 % → 22 %.
- History, 14 Oct settings. **Pipeline output vs GT** (tracked detections, static objects removed; eval = top 1560–1800 s, side 1710–1800 s; dev in brackets), detection P / R: **top @1 m, 2 fps 0.852 / 0.955, 4 fps 0.858 / 0.974** [dev 0.856 / 0.974, 0.857 / 0.986]; with referee-labelled detections removed P 0.991 / 0.998. **Side @2 m, 2 fps 0.794 / 0.771** [dev 0.857 / 0.894]; 0.861 / 0.836 with the GT margin removed. At 2 fps 0.5–0.7 detections per frame never get a track id (0.07 at 4 fps).
- **Tracking** (ID switches per player-minute / IDF1): **top 2 fps 3.4 / 0.40, 4 fps 1.6 / 0.52** (4 min eval window; dev 30 s: 3.9 / 0.71, 2.2 / 0.80); **side 2 fps 8.8 / 0.39** (dev 3.8 / 0.64). Not a GT-margin artefact (side with margin removed: 9.7 / 0.42).
- Formation-engine coverage (≥ 8 of 10 outfield players): oracle 100 % both views (GT annotates everyone); **detection-limited, top: home 98.9 %, away 100 %** (before team-classification losses).
- **Team classification, final (15 Oct), settings re-chosen on dev clips only** (`l_weight 0.75`, `gate 2.0`, keeper zone 30 m re-checked: dev keepers at 24.5 m; `scripts/tune_teams.py`) (eval [dev]): **top 4 fps 98.6 %** (unknown 2.4 %, players labelled referee 1.8 %) [98.1 %, 4.0 %, 0.5 %]; **side 2 fps 92.1 %** (unknown 7.0 %, wrong 7.0 %, referee 3.4 %) [94.3 %]; keeper team right 100 % top, 98 % side. Before (14 Oct settings, chosen with eval data): top 98.5 % (unknown 1.3 %, referee 0.2 %), side 91.8 %. Cost of the tighter gate: more real players read as referee/unknown on the top eval clips (mid-pitch players, partly referee-track ID swaps), see formation coverage below. **Near assistant referee (side): "away" in 96 % of frames → "referee" in 173 of 178** near-touchline detections (officials rule: a track beyond a touchline for ≥ 75 % of its life; dev-chosen, no GT player flagged).
- History: TeamTrack team-classification accuracy (matched players with a settled home/away label; eval [dev]): **top 2 fps 95.9 % (unknown 2.8 %), 4 fps 98.5 % (unknown 1.3 %)** [96.2 %, 97.9 %]; **side 2 fps 91.8 % (unknown 6.2 %, wrong 7.5 %)** [94.0 %]; keeper team right 100 % top, 98 % side. Not fully held out: `l_weight`/`gate` were chosen on GT crops incl. eval clips, keeper zone 30 m on eval data. Side: the near assistant referee is labelled "away" in 96 % of frames (FAILURE_LOG, open).
- **Pipeline vs oracle (`scripts/eval_real.py`, final settings, 15 Oct; BEFORE = AFTER step 6: the two step-6 options are off, and switching them on changes nothing on these clips)**. Formation per 30 s window, agreement on windows where both are confident (exact = family here); uncertain share pipeline / oracle; coverage (frames with ≥ 8 outfield) pipeline / oracle; metric error per 30 s window, mean / p90 (m):

  | view, split | team | both conf. | exact | uncertain p / o | coverage p / o | def. line | width | compactness | centroid |
  |---|---|---|---|---|---|---|---|---|---|
  | **top eval** 1560–1800 s | home | 38 of 42 | **100 %** | 9.5 / 0 % | 91.2 / 100 % | 0.51 / 0.99 | 0.56 / 1.43 | 0.10 / 0.25 | 0.29 / 0.52 |
  | | away | 39 of 42 | **89.7 %** | 4.8 / 2.4 % | 99.6 / 100 % | 0.37 / 0.97 | 0.33 / 1.08 | 0.23 / 0.56 | 0.29 / 0.74 |
  | top dev 1530–1560 s | home / away (1 window each: cells are home / away) | 1 / 1 | 100 / 100 % | 0 / 0 % | 96.7 / 100 % | 0.14 / 0.16 | 0.23 / 0.22 | 0.57 / 0.15 | 0.44 / 0.06 |
  | side eval 1710–1800 s | home | 4 of 12 | 100 % | 66.7 / 0 % | 50.0 / 100 % | 2.25 / 4.91 | 5.51 / 8.96 | 0.72 / 1.72 | 2.74 / 4.27 |
  | | away | 4 of 12 | 50 % (75 % vs inset oracle) | 66.7 / 8.3 % | 51.1 / 100 % | 0.62 / 0.87 | 0.77 / 1.48 | 1.27 / 2.66 | 1.02 / 1.70 |
  | side dev 1680–1710 s | home / away (1 window each) | 1 / 1 | 100 / 100 % | 0 / 0 % | 93.3 / 86.7 % | 0.63 / 0.35 | 2.82 / 4.44 | 0.50 / 0.98 | 1.03 / 1.74 |

  Per frame (top eval, home / away): line 0.60 / 0.40 m mean (p90 2.15 / 0.70), width 0.83 / 0.59, centroid 0.71 / 0.66. Candidate events: **top eval oracle 3, pipeline 4, all 3 matched with the same new formation**, 1 pipeline-only (away 1650 s 4-4-2 → 3-5-2); side eval oracle 1 (home 1755 s 4-4-2 → 3-4-3), pipeline 0. Side vs the inset oracle (GT foot moved up 2.5 px, labelled variant; shifts GT positions 0.92 m median): errors are not smaller (home width 6.89 m), so the side error is mostly perception, not the annotation margin. Same comparison on the 14 Oct perception settings (top eval): home 100 % exact, uncertain 0 %, coverage 95.4 %, per-window line 0.22 / 0.48 m; away 87.5 %; i.e. the dev-chosen team colours cost the home side ~4 points of coverage and some metric accuracy. Pipeline line level vs oracle on the drone view: within ~1 m throughout (outputs/failures/2026-10-15_line_drop_levels_top.png).
- **Second eval set (15 Oct, `--set eval2`, no re-tuning, final config)**: drone 1260–1530 s (9 clips), side 1800–1980 s (6 clips). **Never tuned on, but NOT independent of the first eval set** (same match, cameras, teams; neighbouring minutes). dev / eval / **eval2**:

  | metric | drone dev | drone eval | **drone eval2** | side dev | side eval | **side eval2** |
  |---|---|---|---|---|---|---|
  | detection F1 raw (P / R) | 0.917 | 0.912 (0.858 / 0.974) | **0.922** (0.864 / 0.989) | 0.875 | 0.782 (0.794 / 0.771) | **0.846** (0.827 / 0.866) |
  | F1, referee-labelled removed | 0.990 | 0.978 | **0.989** | 0.918 | 0.810 | **0.885** |
  | team accuracy (unknown) | 98.1 % (4.0) | 98.6 % (2.4) | **99.0 %** (1.9) | 94.3 % (7.1) | 92.1 % (7.0) | **90.5 %** (9.0) |
  | ID switches / player-min, IDF1 | 2.18, 0.80 | 1.61, 0.52 | **1.31, 0.45** | 3.82, 0.64 | 8.79, 0.40 | **11.86, 0.23** |
  | formation exact agreement, home / away | 100 / 100 % (1 win) | 100 / 89.7 % | **89.1 / 88.1 %** (46 / 42 of 48) | 100 / 100 % | 100 / 50 % (4 / 4 of 12) | **82.6 / 57.9 %** (23 / 19 of 30) |
  | pipeline uncertain, home / away | 0 / 0 % | 9.5 / 4.8 % | **2.1 / 6.2 %** | 0 / 0 % | 66.7 / 66.7 % | **23.3 / 36.7 %** |
  | coverage pipeline, home / away | 96.7 / 96.7 % | 91.2 / 99.6 % | **97.8 / 99.6 %** | 93.3 / 86.7 % | 50.0 / 51.1 % | **73.9 / 70.6 %** |
  | 30 s line error mean, home / away (m) | 0.14 / 0.16 | 0.51 / 0.37 | **0.39 / 0.47** | 0.63 / 0.35 | 2.25 / 0.62 | **0.39 / 0.60** |
  | candidates oracle / pipeline / matched | 0 / 0 / 0 | 3 / 4 / 3 | **2 / 6 / 2** | 0 / 0 / 0 | 1 / 0 / 0 | **1 / 1 / 1 (opposite direction)** |
  | s of processing per s of video | 0.99 | 1.20 | 1.06 | 5.46 | 5.46 | 4.42 |

  Worse on eval2: drone home formation agreement (100 → 89 %) and 4 extra candidates (oracle itself hovers between 4-4-2 and 3-4-3 in these minutes: out-and-back pairs); drone IDF1 (66 → 84 tracks for 22 players); side team accuracy (more unknown) and ID switches 8.8 → 11.9 / IDF1 0.40 → 0.23 (longer window, more fragmented tracks). Not tuned. Files: `outputs/eval_second_set_*.json|log`.
- **Ball:** the drone pipeline outputs no ball (0 of 540 frames: the classical detector finds players only), so possession and pressing are null on real top-view output; side 10 of 240 frames (FAILURE_LOG 2026-10-15).
- Perception throughput, full pipeline, laptop CPU (s of processing per s of video, incl. debug video): **top 2 fps 0.73–1.00** (same code, two runs: ±30 % run-to-run on this laptop; geometry 38 %, decode 24 %, detection 23 %), **top 4 fps 1.42** (15 Oct rerun: 1.20; geometry 47 %, detection 28 %, decode 15 %); **side 2 fps 5.8** (15 Oct: 5.46; tiled YOLOX 94 % of the time, 2.7 s/frame). Tracking + teams < 2 % of the time. **EC2 m7i-flex.large (22 Oct, upload path, 4K drone, 360.4 s): detection 1.29 s/s (464 s), whole analysis incl. agent 1,888 s (31.5 min; OpenCV re-analysis 1,208 s = the 1,200 s budget); 30 s 1080p sample 12.7 s wall.**
- Pitch size fitted from IFAB markings (31 top-view landmarks): **105.9 × 68.2 m** → within 2 %, so config keeps 105 × 68.
- Calibration, held-out (leave-one-out) landmark error / line-alignment error: **top 0.11 m mean, 0.38 m max / 0.036 m median** (single homography, 31 landmarks); **side 0.53 m mean, 1.77 m max / 0.08 m median** (2 sectioned homographies, 29 landmarks; single homography 0.60 m, `cv2.fisheye` 0.86 m, cylindrical does not fit). Line-alignment error is measured to the painted line centres (bilinear, `cv2.ximgproc.thinning`): top 0.041 m.
- **Pitch auto-detect for uploads (`eval_autodetect.py`, 60 drone clips × 3 frames, reference = 31-point calibration, correct = every corner ≤ 1 m):** first run 17 Oct **0 / 180 correct, all accepted** (turf edge taken for a goal line, corner error median 6.75 m); after the candidate-edge fix (same clips, not held out) **180 / 180**, corner error median 0.19 m / worst 0.27 m, player positions 0.07 m median; tilted + cropped frames refused. 4-corner clicks (fallback): 5 / 10 / 20 px click noise → positions 0.16 / 0.33 / 0.69 m median. FAILURE_LOG 2026-10-17.
- **Unseen ground + per-video self-calibration (23 Oct, `perception.self_calibration`, `scripts/eval_zenodo.py`):** Zenodo 10.5281/zenodo.14867795 (CC BY 4.0) drone preview, 30 s 4K, low sun; settings chosen only on TeamTrack dev + Zenodo 0–10 s; **unseen test 10–26.7 s**, before → after (1 m): **P 0.396 → 0.765, R 0.999 → 0.970, F1 0.567 → 0.855** (2 m same); detections/frame 63.1 → 31.7 (25.0 annotated); on/just outside the lines 10.5 → 6.0 per frame (beyond 1.5 m: 0 → 0); players with a team **41 % → 95 %**, team accuracy 81 → 98 %; strict formation coverage (≥ 8 annotated outfield players matched with the right team) **0 / 10 % → 96 / 76 %**. Pitch auto-detect: accepted 0.987, line error 0.08 m, corners vs annotation-implied 0.27–1.74 m (one corner fails the ≤ 1 m rule). Leave-one-out (test; note: ablation numbers crop_exclude_lines on ke saath liye gaye the, final config mein off hai.): without shadows F1 0.709; without crop foreground strict coverage 58 / 39 %; without adaptive gate 5 / 61 %; pitch mask, local scale, static objects (83 removed) and grass model ~no change; `crop_exclude_lines` left **off** (Zenodo tune team accuracy 0.96 → 0.85 with it, TeamTrack dev neutral). TeamTrack (eval / eval2), before → final: F1 **0.912 → 0.918 / 0.922 → 0.930**, team accuracy 98.6 → 98.4 % / 99.0 → 98.8 % (unknown 2.4 → 1.0 % / 1.9 → 1.2 %), IDF1 0.515 → 0.526 / 0.448 → 0.457, ID switches 1.61 → 1.80 / 1.31 → 1.41 per player-min, formation exact White 100 → 100 % / 89.1 → 93.5 %, Blue 89.7 → 90.0 % / 88.1 → 88.1 %, White coverage 91.2 → 95.8 % / 97.8 → 99.3 %, candidates 4 → 5 / 6 → 6 (all oracle changes matched). Speed 0.99 → 1.17 s per video s (dev clip, idle laptop). 1080p version of the dev clip: F1 0.886 (all off) → 0.928 (local scale at full resolution, 0.65 s/s). **Upload consistency** (demo 6 min as one upload, rules arm, laptop): White 4-4-2 → 3-4-3 at 16:30 **found and confirmed** (read as 4-2-3-1 → 3-4-3, held 73 % of 11 windows), Blue 16:25 confirmed; 8 of 9 demo candidates have a same-team, same-new-shape counterpart; other 6 uncertain (1,200 s re-analysis budget spent on the first two). Step-0 cause: one 5 s window during a free kick (FAILURE_LOG 2026-10-23).
- Drone drift (top view, 36 frames): median line error **0.198 m uncorrected → 0.089 m anchored per clip → 0.040 m anchored every frame** (ECC on the line image, 142 ms/frame); max shift 13.8 px; the drone wobbles within clips, so the pipeline re-anchors every sampled frame.
- **Alerts, FINAL (seeds 110–119, run once 17 Oct, rules frozen, fingerprint `ca4ff9bbf7b01c6c`):** one-shot **34 / 38 alerted, 34 false alerts** (delay 42 s); rules arm **32 / 38, 9 false alerts**, 1 uncertain (2 %), 2 real changes rejected, delay 105 s; **agent (Nova 2 Lite) identical: 32 / 38, 9 FA** (68 / 68 decisions = rules, 0 guard blocks, 0 fallbacks). Bar (FA ≤ 16 AND ≥ 30 / 38, uncertain ≤ 30 %, delay ≤ 120 s) **met → "agent helped"**; **LLM adds to decisions: no**. LLM cost: 195 calls (2.9 / candidate), 552 k in / 18 k out tokens, **$0.21 total, $0.021 / match**, max 39 calls / match, p95 LLM 5.7 s / candidate, no throttling. 31 / 41 alert explanations say "held 20 s". `outputs/eval_agent_final.json`.
- **Rules arm (no LLM), thresholds frozen 15 Oct on dev** (`eval_agent.py`; synthetic backend, so no OpenCV in these numbers), one-shot → rules: **dev 42–52: false alerts 27 → 4, alerted true changes 39 → 39 of 43**, 0 real changes rejected, 0 % uncertain, mean alert delay 41 → 101 s (+60 s look-ahead); 20 of 27 FPs rejected as reverts, 3 by persistence. **Validation 100–109 (never tuned on): false alerts 52 → 19, alerted 31 → 28 of 36**, 0 rejected, 3 uncertain (4 %), delay 51 → 109 s; 14 of the 19 false alerts are 4-3-3 ↔ 4-2-3-1 flips (12 in seeds 104/105). Step-1 gate (dev ≤ 13 FA, ≥ 37 hits): passed with the design thresholds (37 / 4) and the frozen ones (39 / 4).
- **Bedrock spike (step 4, 15 Oct, Nova 2 Lite, dev seed 45, 10 candidates, synthetic backend):** 10 / 10 finished by the agent with a valid decision (no fallback), **10 / 10 agree with the rules arm**; 3.8 LLM calls per candidate (38 total); `tool_choice=any` works; 5 guard blocks (render before decide) + 1 invalid call (reason > 200 chars); **112 k tokens (108 k in / 3.4 k out), $0.041** (third-party prices) ≈ $0.004 per candidate, ~11 k tokens per candidate; LLM time 5 s per candidate, latency median 1.3 s per call; no throttling.
- **Bedrock spike re-run after fixes 1+2 (15 Oct, same seed 45, 10 candidates):** guard blocks **5 -> 1** (render-before-decide 0), invalid calls 1 -> 0, **3.1** LLM calls per candidate (was 3.8), 10 / 10 agree with rules, 10 / 10 finished by the agent, 89 k in / 2.9 k out tokens, **$0.034**; no throttling.
- **Video backend on real drone candidates (step 5, rules arm, laptop CPU):** `check_frame_quality` **8.0–12.6 s** per call (6 sample pairs, 4K decode + re-anchoring); static drone: lines fit 100 %, shift <= 2.4 px/s, zoom <= 0.1 %, no cut on all 11 windows. `reanalyse_window` at 4 fps: **104–178 s** per 90–145 s window (0.27–0.32 s per tracked frame; 1,545 s for 10 uncached runs). **Bench: 145 s at 4 fps = 171.6 s** (estimate 191 s; geometry 50 %, detection 30 %, decode 18 %); 140 s at 6 fps = 231 s. Decisions: 7 rejected / 4 uncertain / 0 confirmed, **0 of 11 changed vs the first pass**. Simulated pan/zoom: refused (190 px/s, zoom 30 %, line fit 33 %), 17.8 s.
- **Real footage, frozen rules (17 Oct):** drone eval + eval2 (11) + side eval2 (1): rules and Nova identical (12 / 12): 7 rejected, 5 uncertain (4 rule F at clip end, now without re-analysis; side: re-analysis over budget, est. 1,568 s), **0 confirmed, 0 changed by the second look**; Nova $0.037 / 35 calls, chose 6 fps every time (5 extra uncached re-analyses, 183–200 s each), wall 19 min; 6 / 12 explanations wrong (FAILURE_LOG). **Oracle 0–1800 s:** 43 candidates, 2 sustained moves away from 4-4-2 (16:30 home 130 s, 18:50 away 220 s); rules on oracle 6 confirmed / 32 rejected / 5 uncertain. **Demo window 900–1260 s (selected by the oracle):** pipeline 424 s (1.18 s/s), finds both; **evt_003 home 4-4-2 → 3-4-3 at 16:30 CONFIRMED** (both arms; re-analysis 6 fps 252 s, 91 % held) = the only confirmed real alert, evidence JPEG 1280 px; away 18:50 rejected by R (return leg). Evidence JPEG 1280 px (was 568 px PNG). F skip saves 455 of 1,444 s re-analysis on the 11 (31 %). Task A (CV): −4 FA / −1 hit → OFF; return-leg change: +25 FA / 0 hits → OFF.
- **Explanations (step 7, 17 Oct; `agent/explain.py`, presentation only):** real footage, 14 candidates, decisions asserted unchanged (trace replay, both arms): **wrong 7 / 14 → 0 / 14** (strict: also numbers or claims not in the cited result, 12 / 14 → 0 / 14); Nova texts accepted 12 / 14, template 2; 14 Nova calls, $0.0046 (~$0.0003 / explanation, ~700 input tokens). The automatic check flags 12 / 14 of the old texts. Dev seed 45: 0 / 10 explanations say "held 20 s" (final 110–119 run, old step: 31 / 41; not re-run).

---

## Current status

**Generalisation session (23 Oct):** per-video self-calibration of the drone perception (`perception/selfcal.py`, `perception.self_calibration`, every part a switch; results in Key numbers and FAILURE_LOG 2026-10-23); upload/demo mismatch cause isolated and the 16:30 change now confirmed through the upload path. Not deployed: EC2 still runs `34a4590` (redeploy steps in RECORD 23 Oct; waiting for the user). Fingerprint `ca4ff9bbf7b01c6c` unchanged; `verify.py`, `tactics/`, contracts untouched. New: `scripts/eval_zenodo.py`, `tune_selfcal.py`, `upload_check.py`, `run_selfcal_regression.sh`, `tests/test_selfcal.py` (7). Data: `data/zenodo/` (gitignored, CC BY 4.0). Laptop note: never read an analysis's `status.json` while it runs (Windows rename lock, it crashed one run). Generated upload test: cause measured (with `local_scale` the 960 px clip gives duplicate detections for ~70 % of White players; the adaptive gate labels them White, so the pre-switch shape reads 4-2-3-1); the agent still confirms White → 3-5-2 at 1:20, so the test now checks the confirmed change (team, new shape 3-5-2, ±30 s, exactly one confirmed) and not the pre-switch shape (FAILURE_LOG 2026-10-23; duplicates on low-res video open). pytest 284 passed; ruff clean.

**Phase (before 23 Oct):** N6a AWS deployment **done 22 Oct** (N6b submission package not started). Live at **http://13.210.196.109/** on EC2 **m7i-flex.large** (the Free plan refused t4g.large: Graviton types are not Free-plan eligible), IAM instance role (`credentials: iam-role`), S3 `gaffer-demo-221039325928` for assets + source tarballs, CloudWatch `/gaffer/app` (14 d) + metrics `Gaffer/AnalysesCompleted`, `Gaffer/BedrockCalls`. Observed live: health, replay E2E PASS, sample + 6-min 4K uploads (timings in Key numbers), grounded Bedrock chat, approved alert + event DB kept across an instance reboot, all log streams + metrics. Deployed revision `34a4590`; ~$3.10/day running. Open: budget still $10 (raise to $40, user, console); upload path confirms a different 16:30 change than the demo (FAILURE_LOG 22 Oct); posture `unclear` without citations fails validation. Details: `deploy/DEPLOY_AWS.md`, RECORD.md N6a. pytest 277 passed.

**Earlier phase line (history):** 4, integration (cloud session 17 Oct, branch **`phase4-integrate`** from main after both Phase 4 branches were merged; pushed, not merged; the user allowed commits for this session). Frontend and backend run as **one app**: build `web/` with `VITE_API_URL=/` (or `same-origin`; empty = static demo, not connected) and one `uvicorn gaffer.api.main:app` serves the site and the API. Rules fingerprint unchanged `ca4ff9bbf7b01c6c`; `src/gaffer/agent/`, `tactics/` and `config.yaml agent:` untouched. **210 Python tests pass (205 + 5 new), 25 web tests (+5), ruff, eslint and the build clean.**
- **Built:** web: `VITE_API_URL` modes (`api.ts`, credentials on every call); `validateStatus` accepts `needs_confirmation` / `needs_corners` and reads `pitch` / `video`; connected upload flow = upload first → "Is this your pitch?" on `pitch.preview_url` (Yes → `POST /pitch {confirmed}`, No → 4-point screen on the server's `/frame` preloaded with `pitch.corners`, `POST /pitch {pitch_points}`) or `needs_corners` → 4-point screen preloaded with `suggested_corners`; a video the browser cannot decode can still be uploaded; demo from `/api/demo/files/*` + `/api/demo/alerts`; approve / reject through the API (demo: "saved for you only"); upload results show their own report's shapes; trace kind `explanation` accepted (every real upload result failed validation before: FAILURE_LOG). API: `api/visitors.py` (anonymous cookie `gaffer_visitor`, demo decisions in memory per visitor, cap `api.visitors.max_visitors`, never written to `alerts.jsonl`), `GET /api/demo/alerts`, chat counts visitors by header → cookie → IP, CORS with credentials; uploads keep the shared alert store. `scripts/serve_no_bedrock.py` (same app, no Bedrock client: no AWS call), `web/scripts/e2e-integrate.mjs` (Playwright walkthrough). Tests: per-visitor decisions, cookie, cap, chat by cookie, built-site route; API tests no longer depend on `web/dist` being built (one failed once it was).
- **Checked here (generated videos, Bedrock off, rules arm):** demo loads from the API (no bundled file read); visitor A approves, visitor B still sees it pending, A still approved after reload; clean generated 3-min upload → needs_confirmation (95 %) → adjust screen → back → Yes → progress → result (3 candidates: 1 confirmed with evidence, 1 rejected, 1 uncertain) in pitch, timeline, alert card → approve (saved on the server); worn-markings upload → needs_corners (guess preloaded) → Reset → 4 clicks → analysis done, but **0 candidates** (team colours failed for White on that clip: FAILURE_LOG). 14 screenshots `web/screenshots/integrate/`, no console errors.
- **Not tested:** real Bedrock from the app (chat, Nova arm), real non-TeamTrack footage, `eval_autodetect.py` on TeamTrack, Docker image, EC2 / S3. PLAN Phase 4 acceptance: none of the six tickable yet (status note added).
- **Weak:** demo decisions are lost on a server restart (by design, in memory); the 4-point screen needs a scroll to "Start analysis" at 900 px height; Chromium cannot decode the generated mp4v clips, so uploaded generated videos do not play next to their analysis.

**Phase 4 part B (backend, history):**, built in a cloud session on 17 Oct on branch **`phase4-backend`** (pushed; never merged into main; the user decided git commits for this session). Part A (frontend) is on `phase4-frontend` (`web/`, not on main yet). Rules fingerprint unchanged `ca4ff9bbf7b01c6c`; `src/gaffer/agent/`, `tactics/` and `config.yaml agent:` untouched. **205 tests pass (154 old + 51 new), ruff clean.**
- **Built:** `src/gaffer/api/` (FastAPI: health, demo bundle + exact sample files, uploads with coach-readable refusals, pitch step, the frontend's `/start`, status, result, evidence, alert approve/reject through `agent.alerts`, read-only grounded chat with 3 caps), single worker running pipeline → tactics → Phase 3 agent (Nova arm when Bedrock is reachable, else rules) → explanations → report, progress/ETA from measured frame and candidate timings, local storage + `aws/s3.py` with the same interface; `perception/pitch.py` new functions only (`four_corner_homography`, `four_corner_calibration`, `detect_pitch_corners`, `draw_corner_overlay`, `render_pitch_view`); `scripts/eval_autodetect.py`; `deploy/Dockerfile`, `.dockerignore`, `deploy/README.md`; `docs/API.md`; config: new `api:` block and `calibration.four_corner` / `calibration.auto_detect` sub-blocks (existing keys unchanged); deps fastapi / uvicorn / python-multipart (+ httpx2 for tests), all MIT/BSD/Apache, locked.
- **Checked here (no AWS, no TeamTrack videos in the cloud):** generated videos only: auto-detect finds generated pitches to ~1 px and refuses tilted / cropped / no-pitch frames; a 3-min generated upload runs end to end (pipeline 15 s, agent confirms a 4-4-2 → 3-5-2 change with an OpenCV re-analysis, evidence JPEG, pending alert, approve); clean venv install from the lock + real uvicorn + curl, serving the built frontend.
- **Not tested / not measured:** `eval_autodetect.py` on TeamTrack (run on the laptop; no accuracy claim anywhere yet); real Bedrock from the API; real non-TeamTrack footage; S3; the Docker image (sandbox could not pull a base image). Limitation seen on generated 960 px video: line junctions detected as players (detector tuned at 4K, ~28 px/m).
- **Frontend changes:** done in the integration session (above).

**Phase 3 (history):** **build steps 1–7 done (step 7 on 17 Oct: presentation and explanation only, rules frozen at `ca4ff9bbf7b01c6c`); PLAN Phase 3 acceptance all ticked with caveats; step 7 not committed yet (user commits). Do not start Phase 4.** Design approved with answers (look-ahead 60 s yes; side capped at uncertain; real clips = decision tables + pipeline-vs-oracle agreement; quota unknown, no Service Quotas permission; rules arm published) and 3 doc changes (exact bar in §8: FA ≤ 16 AND ≥ 30 / 38; number matching cut from grounding; spike caps 100 calls / 1 USD). Built: `agent/verify.py` (rules: geometry, footage, revert/return leg, coverage = second-look trigger, persistence, second look on video, view cap), `agent/context.py` (MatchContext, evidence, synthetic/annotation re-analysis = tactics on a MatchState slice), `agent/tools.py` (10 tools, pydantic → Converse schemas, protocol + citation/clock guards, OpenCV-drawn before/after shape PNG), `agent/alerts.py` (append-only store + CLI), `agent/loop.py` (per-candidate Converse loop, `tool_choice=any`, guard: steps/vision/repeats/malformed/nudge, per-match + per-run budgets, 18 RPM limiter, rules fallback, trace, verified timeline), `scripts/eval_agent.py`, `scripts/spike_agent.py`, `agent:` block in config, autouse no-AWS-network test guard; 27 new tests (124 total), ruff clean. Seeds 110–119 untouched. Numbers: Key numbers (rules arm, spike). 3 failure entries dated 15 Oct. Phase 2 fully committed (`61ca59b`); Phase 3 not committed yet (user commits).
**Phase 3 resumed (15 Oct, later session) — fixes 1+2 DONE, build step 5 DONE; stopped before step 6 as instructed.**
- Problem 1 done: the code-written reason (`verify.decision_reason`) is the primary reason in `Outcome.reason`, the verified timeline (`Verification.reason`) and alerts; the model's text is `Outcome.explanation` / trace `explanation`. Alerts (contract unchanged): code-written title (`<team>: from -> to (mm:ss)`), `explanation` = `"Verified: <rules reason> [Rn]"` + `"\nExplanation (agent): <model text>"` (`alerts.compose_explanation` / `split_explanation`; CLI `--list` shows both). Test: `test_alert_never_shows_a_reason_that_contradicts_the_rules_verdict`.
- Problem 2 done: every rules block has `next_step` (`Toolbox.next_step`; also in the card, `record_decision` and `render_evidence` results). Spike re-run (seed 45, 10 cand., caps 100 calls / $1, `scripts/spike_agent.py` now has `--resume` + `--baseline`): first re-run exposed a wrong hint (said "record_decision" before the required vision check: 3 blocks), fixed (`CandidateState.looked`); **second re-run: guard blocks 5 -> 1** (render-before-decide 5 -> 0; 1 left = propose_alert without [Rn]), invalid calls 1 -> 0, LLM calls/candidate 3.8 -> 3.1, 10/10 agree with rules, $0.034 (`outputs/spike/spike_20261015T160103.json`; first re-run `..._155449.json`, $0.039).
- Step 5 done: `agent/vision.py` (VideoBackend: quality = drift re-anchoring line fit per sample + ORB/`estimateAffinePartial2D` motion on frame pairs 0.5 s apart + HSV-histogram cuts / unaligned samples = view change; re-analysis = `pipeline.run` on the window snapped to 5 s, track = output = fps, full-match team model + directions from `<match>.teams.json`, budget refusal (window x fps x `s_per_frame`, 360 s / call, 1200 s / match) with `max_window_s_at_this_fps`, disk cache `outputs/agent_cache/video/`; evidence frame = positions + formation lines projected through the frame's own homography, cropped, PNG <= 400 KB). `tools.py`: video branches of the 3 vision tools, `Toolbox(video=...)`, `evidence_image()`, problem 4 fixed (`shape_panels`: most confident window per shape, else a "LOW VISIBILITY" panel; evidence frame = best-fitting frame of the most confident new-shape window). `context.tactics_pass` shared by synthetic and video re-analysis. `loop.py`: rules policy re-analyses at the lowest fps (highest when first-pass coverage is low, stepping down on over_budget); `Outcome` gains `first_verdict/first_reason/quality/reanalysis/tool_ms`; CLI builds the video backend for `--match ... --view`. `scripts/run_agent_video.py` (rules arm on real top candidates, resumable via `outputs/agent_video/rows.jsonl` + cache; `--simulated-pan`, `--bench`, `--render-check SET:EVENT`). `tests/test_agent_vision.py`: 9 tests on generated frames (static ok, known shift/zoom recovered, pan/zoom refused, cut, budget refusal + cache hit, rules arm video confirm with frame PNG, pan refused without re-analysis, over_budget retryable, low-visibility panel). AGENT_DESIGN §2 "As built (step 5)" notes. 3 FAILURE_LOG entries (15 Oct). **136 tests, ruff clean.**
- **Step 5 results (real drone, rules arm, no LLM):** 11 pipeline candidates -> 7 rejected, 4 uncertain (clip ends < 60 s after them), 0 confirmed; **0 of 11 decisions changed by OpenCV** (1 changed evidence: eval evt_001 revert 55 s -> no revert, 17 % held). Simulated pan/zoom (real frames): refused, 190 px/s, zoom 30 %, lines fit 33 %, no re-analysis, uncertain where the first pass says reject = the only real-frame case of OpenCV changing next call + decision. Oracle: 0 of 5 confirmed. Evidence on a real frame only as a bannered render check (`outputs/agent_video/render_check/teamtrack_top_eval2_evt_005.png`); the confirmed-evidence PNG with a frame exists on generated frames (test). Acceptance: pan refused yes; 145 s top re-analysis at 4 fps **171.6 s** (< 4 min) yes; evidence PNG for a confirmed candidate: generated frames + synthetic only (no real candidate is confirmed); tests on generated frames yes.

**Phase 3 step 6 session (17 Oct), order set by the user: (1) design changes → (2) Task E part 1 → (3) Task A + FREEZE → (4) Task B final 110–119 once → (5) Task E part 2 + Task C → (6) Task D. Do not start build step 7. Do not touch `web/` (phase4-frontend branch, other session) or `data/teamtrack/get_train.py`.**
- **Step 1 DONE (design changes).** (a) Rule F skips the second look (`verify.evaluate`): rules arm re-run on the 11 real candidates (`outputs/agent_video_fskip/`, `run_agent_video.py --out`): 11/11 decisions unchanged, 4 re-analyses skipped = **455 s of 1,444 s** uncached OpenCV (31 %). (b) Evidence images are **JPEG q90, ≤ 1 MB** (`vision.write_image`, config `evidence_format/jpeg_quality/max_bytes`): real 4K render check now **1280 × 1372 px, 358 KB** (PNG was 568 px). (c) AGENT_DESIGN: camera check measured 8–13 s/call, JPEG, F exception (§2, §3 E, §4). 1 new test (137).
- **Step 2 DONE (Task E part 1).** 42 drone train clips (0–1260 s) checked: all decode first/last frame (4K, 900 frames), all CSVs parse; 6 CSVs have 903–906 annotated frames (extra rows never read; DATA_NOTES §11). Manifest: **140 files, 1,887 MB, all SHA-256 verified**, 84 new entries with the manual-download note (`download_teamtrack.py`: train split + note). Config `teamtrack.clip_sets.top.train: [0, 1260]`; defaults (dev + eval) unchanged (checked). Oracle `--set full` (new option): `outputs/oracle_top_full.json`, 3,601 frames, 0–1800 s, lines fit 100 %, 19 min. `scripts/oracle_sustained.py` (new): **43 oracle candidates over 0–1800 s** (home 21, away 22); **8 hold ≥ 120 s with ≥ 60 % of confident windows in the new shape, 6 of them returns to the usual 4-4-2; 2 move away from it: home evt_029 4-4-2 → 3-4-3 at 16:30 (990 s, held 130 s, 85 %) and away evt_033 4-4-2 → 4-2-3-1 at 18:50 (1130 s, held 220 s, 78 %)**. Nothing holds > 4.5 min. Rules arm on the oracle: 6 confirmed / 32 rejected / 5 uncertain; evt_029 confirmed, **evt_033 rejected by R as a return leg** (FAILURE_LOG 17 Oct). Picks for Task E part 2: window ~900–1260 s covers both.
- **Step 3 DONE (Task A) + FREEZE.** `scripts/flip_experiment.py`: rule (confirmed 4-3-3↔4-2-3-1 with D = max |Δ line, width, compactness| on the re-analysed pass ≤ T → uncertain), 1 threshold, leave-one-seed-out CV over 42–52 + 100–109 (100–109 = dev data for this experiment only). Pair: 14 false vs 4 real confirmations; D flips 0.98–38 m, real 1.1–25.6 m (no separation). **CV: false alerts 23 → 19, alerted 67 → 66 (1 real change lost)**, T = 7.5 m in 20/21 folds; in-sample at T = 7.5: 18 FA / 66. Pre-set criterion (−5 FA, ≤ 2 lost) **not met → OFF, not implemented** (FAILURE_LOG 17 Oct). **Added by the user: R experiment** (`scripts/return_leg_experiment.py`, switch `agent.verify.return_leg_needs_failed_persistence`, a return leg is rejected only if P fails): on 42–52 + 100–109 **alerted 67 → 67, false alerts 23 → 48** (dev 4 → 14, 100–109 19 → 34), CV picks off 21/21 → **OFF** (config `false`, code kept, 1 test); real oracle (info only): 7/43 decisions would flip to confirmed incl. evt_033, 6 of 7 returns to 4-4-2. Dry run of the new llm arm on dev with call cap 0: 66/66 rules fallbacks = offline rules arm exactly (outputs removed). **Rules FROZEN 17 Oct**, config fingerprint `ca4ff9bbf7b01c6c` (config.yaml comment, AGENT_DESIGN §8 incl. "110–119 agent-untouched, not unseen").
- **Step 4 DONE (Task B, final 110–119, run ONCE, 17 Oct 01:40–02:20, no crash/resume).** `outputs/eval_agent_final.json`, `outputs/eval_agent_final/` (llm rows, trace, alerts), log `outputs/eval_agent_final_run.log`. **one-shot 34/38 alerted, 34 FA; rules 32/38, 9 FA, uncertain 2 % (1/68), delay 105 s; agent (Nova 2 Lite) 32/38, 9 FA, 2 %, 105 s — identical to rules (68/68 agree, 0 guard blocks, 0 invalid, 0 fallbacks).** Bar (FA ≤ 16 AND ≥ 30/38, unc ≤ 30 %, delay ≤ 120 s): **met → "agent helped"**; LLM adds to decisions: **no** (decisions come from the rules; LLM = orchestration + text). Cost $0.21 total (552 k in / 18 k out tokens, 195 calls, 2.9/candidate), $0.021/match, max 39 calls/match, p95 LLM 5.7 s/candidate, no throttling → cost limits met. Rules lose 2 real changes (1 persistence, 1 revert). Text: 31/41 agent explanations say "held 20 s" (FAILURE_LOG).
- **Step 5 DONE (Task E part 2 + Task C).** Task E: pipeline on 900–1260 s (`outputs/match_state_top_w900_1260_4fps.json`, 424 s = 1.18 s/s; window chosen BECAUSE the oracle shows the 2 sustained changes there: a demonstration, not a sample, same match); pipeline finds both (w900 evt_003 home 4-4-2→3-4-3 16:30, evt_007 away 4-4-2→4-2-3-1 18:50) + 7 others; agent run on those 2 only (all 9 would exceed the frozen 1200 s/match OpenCV budget; `run_agent_video.py --sets w900 --candidates`). Rules and Nova (`outputs/agent_video_taskE/`): **evt_003 CONFIRMED** (quality ok, first-pass coverage before 52 % → re-analysis at 6 fps, 252 s, held 91 % of 11 windows) → evidence JPEG `outputs/agent_video_taskE/evidence/teamtrack_top_w900_1260/evt_003.jpg` + pending alert; caveat: the "before" panel (15:15–15:45, 30 frames) shows the team in its own box (likely set piece). **evt_007 rejected** (R: return of evt_005; Nova's 6 fps look: held 100 %); Nova's text contradicts it. Task E OpenCV ≈ 19 min (pipeline 424 s + re-analyses 252/174/229 s + quality checks). Task C (`outputs/agent_video_final/`, rules `report.json`, Nova `report_llm.json`): 12 / 12 identical decisions (see Key numbers); side evt_001 uncertain by budget refusal, not by the view cap. Step 5 compute total ≈ 40 min (Task E 19 + Task C Nova 19 + rules runs ~3). Bedrock spent this session: final $0.21 (195 calls) + Task E $0.009 (8 calls) + Task C $0.037 (35 calls) = **$0.256, 238 calls**.
- **Step 6 DONE (Task D, evidence status, written in AGENT_DESIGN §14 and FAILURE_LOG 17 Oct):** (1) OpenCV result changes the next call AND the decision on real frames: **only the simulated pan** (real frames, synthetic motion); no genuinely real case (14 real candidates, decision always = first pass alone); closest: demo evt_003, low coverage → 6 fps second look (call changed, decision not). (2) Re-analysis contradicts a first-pass finding on a real clip: **eval evt_001** (first pass "reverted after 55 s" → second look at 4 and 6 fps: no revert, held 17 %, still rejected; reason changed). (3) Confirmed alert with evidence image on real footage: **yes, one** (demo evt_003, oracle-selected window, set-piece caveat); none on eval / eval2; otherwise synthetic (41 alerts) and generated frames (tests).

**Phase 3 step 7 session (17 Oct): tasks 1–7 set by the user (presentation and explanation only, no decision changes; do not touch `web/` or `data/teamtrack/get_train.py`; no git).** New settings go in the top-level `presentation:` block, never under `agent:` (fingerprint stays `ca4ff9bbf7b01c6c`, checked after every change).
- **Task 1 DONE (explanations).** `agent/explain.py` (new): after a successful `record_decision` the loop asks Nova, in a separate conversation with its own budget, for 1–2 sentences from `facts` (decision, code reason, cause, rule in plain words, key numbers per ref; no engine evidence string, no label strip). `explain.check` (cause named, no contradiction, numbers/clocks only from the facts, no ball/possession/pressing/confidence, refs exist, ≤ 2 sentences / 300 chars) else `explain.template` (code; passes its own check for every cause). Alerts carry it as `Explanation (agent|template)` (`alerts.split_explanation_source`); the free text of `record_decision` / `propose_alert` is trace-only (`decision_text`). `Toolbox`: `st.results` per ref. Prompt worked on dev seed 45 only (4 runs, $0.012). `scripts/explain_real.py`: replays the step-6 traces of the 14 real candidates for both arms (stored camera checks, cached re-analyses, uncached = error), asserts every rules verdict + decision unchanged, then explains once: **wrong 7 / 14 → 0 / 14** (strict rubric 12 / 14 → 0 / 14; 1 vague), Nova texts kept 12, template 2 (1 false flag, "recorded", word added afterwards). First attempt: 8 of 14 calls could not reach Bedrock (template fallback), those 8 re-tried. 14 calls, **$0.0046**. `outputs/agent_video_step7/explanations.json`. 9 new tests.
- **Task 2 DONE (evidence "before" panel).** Measured: every confident 4-4-2 window in the 45 s before 16:30 had White in its own box (45–65 % of positions in its penalty area; open play 0–9 %). `Toolbox.shape_panels`: most confident window of the shape with ≤ 25 % of positions in the own box (`presentation.evidence.max_own_box_share`), "before" searches 120 s back (`before_search_s`); all packed → most confident + "ATYPICAL … deep defending or set piece?" note; second caption line on every panel. Re-rendered with `scripts/explain_real.py --render` (trace replay, cached re-analysis, one frame decoded, step-7 explanation, no LLM call): before = **15:05–15:35 (0.78, 20 % in own box)**, after unchanged (16:35–17:05, 12 %). New pending alert `outputs/agent_video_step7/alerts_llm.jsonl` + evidence `outputs/agent_video_step7/evidence/teamtrack_top_w900_1260/evt_003.jpg`; panel comparison `outputs/agent_video_step7/evt_003_w900_panels_before_after.jpg`. Threshold set on this one case (presentation only). 2 new tests; 1 vision test caption updated. Open (not asked): the alert's suggestion is still the model's free text and tactically wrong ("extra central midfielder": 4-4-2 → 3-4-3 adds a forward).
- **Task 3 DONE (side reason).** `Toolbox.recorded_reason`: on a capped view (side) an uncertain decision's recorded reason leads with the camera: side eval2 evt_001 now reads "uncertain: experimental camera (side view, never alerted); detail: second look refused, over budget (estimated 1568 s of OpenCV > 360 s for 140 s at 4 fps); first pass: new shape held in 57% of windows (inconclusive)" (was "no verdict after the evidence budget: …"). Verdict (`need_more`) and decision (uncertain) unchanged, asserted in the replay. Its explanation re-run once from the new reason (1 Nova call): Nova now names the camera and passes the check ("… marked uncertain because the side camera is experimental and we couldn't check the detail in time"). Totals after tasks 1 + 3: Nova texts 13 / 14, template 1 (the false flag), **15 calls, $0.0049**. 1 new test.
- **Task 4 DONE (coach report).** `agent/report.py` (new): `build_inputs` (decided events with code reason, explanation and before/after line/depth/width/own-box share of the evidence-panel windows; timeline segments; unchecked candidates listed, not citable), `check_report` (every number/time cited `[evt_…]` / `[seg a-b]` incl. segment runs, numbers in the cited items, valid sources only, each "may have fixed" + exactly 3 recommendations on a cited number/time, both teams in the story, no ball/possession/pressing/confidence), `template_report` (passes the same check), `Reporter` (1 call + 1 retry, else template), CLI `py -m gaffer.agent.report`. Config `presentation.report`. Prompt worked on dev seed 45 (5 runs, 3 prompt versions, 1 accepted, $0.038). **900–1260 s report, one run: Nova failed the check twice (2nd only on a `[match.note]` pseudo-citation; content grounded but tactically weak) → template published** (`outputs/agent_video_step7/report_w900_1260.md`, JSON with both attempts; $0.0035). 3 new tests. FAILURE_LOG entry.
- **Task 5 DONE (diagram).** `docs/agent_workflow.png` (1568 × 2376) rendered from the AGENT_DESIGN §10 Mermaid block with `npx @mermaid-js/mermaid-cli@11.17.0` (MIT) on the local Chrome (no browser download; command in §10). Diagram updated to the as-built flow first: `record_decision` before `render_evidence`, footage branch without a second look, checked explanation step feeding the alert.
- **Task 6 DONE (trace examples).** `docs/AGENT_TRACE_EXAMPLES.md`: (a) 16:30 low coverage → 6 fps second look → 91 % held → confirmed → evidence → pending alert (Nova trace; first pass alone would also confirm, said so), (b) eval evt_001 second look finds no revert (17 % held) → still rejected, (c) simulated pan refused (190 px/s, zoom 30 %, lines 33 %), one line on the missed 18:50 change, reproduce commands.
- **Task 7 DONE (PLAN acceptance).** `docs/PLAN.md` Phase 3: all 5 acceptance items ticked with their evidence, plus an honest caveat list (no real OpenCV-changed decision, only the simulated pan; LLM adds nothing to decisions; report published as template; the confirmed real alert is in an oracle-chosen window; 18:50 missed; real clip = decision tables; suggestions unchecked). AGENT_DESIGN §14 step-7 table. Step 7 Bedrock total **$0.058** (75 calls incl. 9 network failures; dev prompt work $0.050, real runs $0.008). **154 tests pass (18 new), ruff clean**; fingerprint `ca4ff9bbf7b01c6c` unchanged.

**Bedrock model + region:** `global.amazon.nova-2-lite-v1:0` (fallback `apac.amazon.nova-micro-v1:0`), ap-southeast-2. Real calls + tool calling work.
**Done:** Phase 0 + Phase 1: contract frozen at v1.0 (`schema.py`; nullable segment metrics, GT `noise_events`/`visibility`); synthetic 90-min generator (`gaffer/synthetic.py`, decoys, broadcast-window visibility, 2 fps, match file gitignored); tactics engine (template fit with Hungarian assignment, families `3-5-2`≈`5-3-2`, hysteresis detector, metrics, <8 KB timeline); 65 tests (47 new); eval numbers above; 5 failure cases logged with images.
**Phase 2 so far (10 Oct):** Step 0 held-out check recorded (official synthetic numbers above; `eval_synthetic.py --heldout`). `perception/pitch.py` (pitch model, top-hat line mask, landmark snapping, pitch-size fit, homography, leave-one-out + line-alignment error), `perception/undistort.py` (side-model comparison, bird's-eye rectification), `scripts/calibrate.py`, `data/calibration/*`, 8 new tests (73 total). Findings: the side panorama is near-rectilinear, not a fisheye; top and side clips are NOT simultaneous (no cross-view check possible); DATA_NOTES corrected. `supervision` 0.30.9 installed and locked. `*.clips.json` convention documented (DATA_CONTRACT, data/README.md).
**Day 1 (later, 10 Oct):** `gaffer/teamtrack.py` (clip discovery, NaN-safe GT loader), `perception/video.py` (video or `*.clips.json`, sequential decode), `perception/drift.py` (per-frame re-anchoring + per-frame quality), `perception/matchstate.py` (shared MatchState assembly: off-pitch drop, possession, attacking direction from keepers), `perception/tiling.py`, `perception/detector.py` (classical top-view detector + tiled YOLOX), `gaffer/evaluation.py`; scripts `teamtrack_to_matchstate.py` (oracle; tactics engine runs on it unchanged: top 3 candidates, side 1), `eval_drift.py`, `compare_detectors.py`, `coverage_check.py`; `data/clips/*.clips.json`; 12 more tests (85 total). Both views infer the same attacking directions independently (TeamID 0 = home attacks left).
**Day 2 (14 Oct):** (1) side detection: MOG2 background detector added to `detector.py` and `compare_detectors.py --view side` (near/far halves, 2 m column, `+inset` rows for the GT box margin) → tiled YOLOX stays the side detector, MOG2 kept as a 22× faster fallback; GT-margin finding in DATA_NOTES. (2) `perception/team_classifier.py`: torso Lab colour minus grass, `cv2.kmeans` k=2 with outlier gating + 3 "other" clusters, per-track vote, keepers by zone, else referee. (3) `perception/tracker.py`: supervision ByteTrack with matching boxes enlarged 1 + 12/fps, unit scores, centre-distance mapping back. (4) `perception/pipeline.py` (`run`, `run_window` for Phase 3, `write_outputs`, CLI, per-stage timing, static-object filter), `perception/render.py` (debug video + minimap), direction by rearmost-player vote in `matchstate.py`, `scripts/eval_tracking.py`; 8 tests (93 total). Eval runs on the final code: top 2 + 4 fps, top dev 2 + 4 fps, side 2 fps (eval + dev); side 6 fps not run (~30 min). 6 failure entries dated 14 Oct. Numbers: Key numbers above.
**Day 2, steps 5–7 (15 Oct):** user decisions applied first: `perception.track_fps` per view (top 4, side 2); officials rule (`perception.official`, `pipeline.official_tracks`, dev-tuned with `scripts/tune_officials.py`); team colours re-chosen on dev clips only (`scripts/tune_teams.py`, 3-class accuracy on dev detection crops after a GT-crop objective proved blind to officials) → `l_weight 0.75`, `gate 2.0`, keeper zone 30 m kept on dev evidence. Step 5: `scripts/eval_real.py` (pipeline vs oracle per team, dev/eval cut separately; side also vs `oracle_side_inset.json` from `teamtrack_to_matchstate.py --gt-inset`). Step 6: `formations.change_equivalent` (`TacticsConfig.change_family`, detector only) and `line_drop` events (`events.line_levels` / `detect_line_drops`, timeline lists them without splitting segments), both measured and **off by default** (trade-off / no benefit, FAILURE_LOG); seeds 110–119 added (`--heldout2`, `--no-change-equivalence`); `scripts/tune_line_drop.py`, `scripts/plot_line_levels.py`. Step 7: `scripts/download_teamtrack.py` + `data/teamtrack_manifest.json` (26 files, 290.7 MB, SHA-256; `--check` verified, `--list` works anonymously; the download path needs Kaggle credentials and is untested), `data/README.md` updated (other soccer clips on Kaggle); `camera_motion.py` cut, pan/zoom limitation logged with 3 hard-mode frames. `requests` declared in pyproject (already locked). 5 failure entries dated 15 Oct, the 14 Oct assistant-referee entry closed. 97 tests (5 new), ruff clean.
**Second eval set (15 Oct):** download check done — 9 drone clips 1260–1530 s (Kaggle val) + 6 side clips 1800–1980 s (Kaggle test), all open/parse, sizes = Kaggle listing, SHA-256 in `data/teamtrack_manifest.json` (56 files, note on the 30 new). Config `teamtrack.clip_sets` (dev / eval / eval2 by match time; `find_clips` defaults to dev + eval, so old results keep their meaning); `--set eval2` in `teamtrack_to_matchstate.py`, `eval_tracking.py`, `eval_real.py`. **eval2 is never-tuned but NOT independent of eval** (same match, cameras, teams, neighbouring minutes). `D_…_1620_1650.csv` is 2× size because its boxes are fractional (interpolated/smoothed), no measurable effect (DATA_NOTES §10). Hard-mode frames moved to gitignored `outputs/_peek/` (minors, original not held); FAILURE_LOG pan/zoom entry now words only. Runs done 10:10–10:30 (`outputs/run_second_set.sh`, 20 min; logs + JSON `outputs/eval_second_set_*`): results in Key numbers ("Second eval set"). 97 tests, ruff clean.
**Next (Phase 4):** on the laptop: `git fetch` + `git switch phase4-integrate`, install, build `web` with `VITE_API_URL=/`, run `uvicorn gaffer.api.main:app`, open http://localhost:8000/app, try an upload and a chat question (real Bedrock); run `py scripts\eval_autodetect.py` (report its numbers before any accuracy claim); then the AWS part (EC2 / S3 / CloudWatch / Budgets: needs the user's cost OK and IAM permissions). **Earlier (Phase 3):** user reviews the step 7 report and commits Phase 3 (step 7 files listed by `git status`) → Phase 4 in a new session. Open for the user: (a) rule R misses A→B→A→B real changes (evt_033 / w900 evt_007; the tested fix adds 25 FA on synthetic: left off); (b) the alert suggestion is still unchecked model text (16:30: "extra central midfielder", wrong); same check + template treatment as the explanation would fix it; (c) Nova's coach report fails the grounding check (template published); a `[match.note]` slip could be stripped as a format error; (d) `presentation.evidence.max_own_box_share` 0.25 was set on the one demo case.
**Later, if time (do not build unless asked):** a track-level dev objective for team colours (score settled per-track labels after voting on cached dev detections, not single crops; might win back the home coverage the tighter gate cost); ball detection on the drone view (possession, pressing, set pieces, a ball-aware line_drop); classify in- and out-of-possession shapes separately (the better fix for 4-3-3 ↔ 4-2-3-1, family stays OFF).
**Expanded coach-workflow phases (2026-10-21):** N1 event persistence, N2 recorded TeamTrack replay, N3 event-triggered Bedrock posture assessment, N4 conditional role-level advice are complete; N5 local integration and UX acceptance are complete; N6 AWS deployment/submission is not started. The rough phase-allocation estimate is 85% complete / 15% remaining; this is not a measured metric. See `RECORD.md` (N5 entry and the 21 Oct Audit / 22 Oct fix entries) for N5 checks and limitations; the planning notes moved to `docs/dev/` (`PLANNING.md`, `CODEX_PLANNING.md`, `PROJECT_MEMORY.md`, `codex_changes.md`; the last has no N5 entry). Event record schema 1.1 uses SQLite DB migration 4; frozen MatchState/TacticalTimeline v1.0 contracts remain unchanged. SQLite event DB defaults to `outputs/api/events.sqlite3`; configure `api.event_store.path`, and use persistent EBS for EC2. N4 advice remains deterministic and conditional, with coach suggestion responses separate from alert approvals. The user's existing `chatMatchId` edit in `web/src/pages/AppPage.tsx` was preserved.
**Fix session (2026-10-22, see RECORD.md; N6 not started):** fingerprint `ca4ff9bbf7b01c6c`, contracts v1.0, `verify.py` / `tactics/` untouched. **pytest 267 passed; ruff clean; web 32 tests, lint, build OK; replay E2E + integrate walkthrough PASS.** Posture: citable_metrics in the evidence, claim-only banned-signal check, fenced JSON parsed; real call on evt_003 now **completed / unclear** with 4 exact citations (code downgraded Nova's label: before-window confidence 0.30), shipped as `samples/w900_1260/demo_events_seed.json` (imported once by a fresh server). Chat re-test on Bedrock **not passed** (Nova guessed evt_018 twice; grounding check caught it; candidate-index fix untested live). Also: timeline clipped at the playhead in replay modes, legend, plain-word posture reasons, 4-point screen fits 1440x900 / 390 px, checked alert suggestion (demo re-rendered), N4 re-checks cited values, isolated `serve_no_bedrock.py` DB, off-topic chat in code, footage guide, sample clip (`scripts/make_sample_clip.py`, 218 MB H.264). Planning notes moved to `docs/dev/`. Bedrock this session: 7 calls, $0.0053. Earlier test counts in this file (210 / 25, 256 / 29) are history.
**UX fix (2026-10-22, see RECORD.md):** /app opens idle (decorative pitch, start panel, no data); Live analysis plays from 15:00 and reveals dots, chips, timeline and the 16:30 alert by playhead (verified only from 18:05); per-session coach decisions; review / upload labelled "Completed analysis". Web tests 42, replay E2E + integrate walkthrough pass. Demo-replay advice responses are no longer written to the shared event DB.
**Blockers:** none

<!-- Update the five lines above at the end of every session. Keep it short. -->
