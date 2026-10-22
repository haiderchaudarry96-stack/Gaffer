# Gaffer Project Memory

This file is a durable summary for future Codex and Claude Code sessions. It is not a verbatim copy of the source Markdown. The sources listed below were reconciled with the current N3 work on 2026-10-21; consult the original file before changing an area it governs.

## Active planning documents

- [`CODEX_PLANNING.md`](CODEX_PLANNING.md): old flow, target flow, status, requirements, scope boundaries.
- [`PLANNING.md`](PLANNING.md): N1–N6 roadmap, including the original unfinished EC2/AWS deployment and submission work; acceptance criteria, paste-ready prompts, update rules.
- [`RECORD.md`](../../RECORD.md): append-only phase/session record; N1-N5 local implementation and acceptance are complete; N6 has not started. The stranger identified one saved-response UX issue that was fixed and browser-tested; see RECORD.md for the limit on its human retest.
- [`CLAUDE.md`](../../CLAUDE.md): project constraints and Claude Code working rules; read at every session.
- [`docs/PLAN.md`](../PLAN.md): original six phases and historical acceptance/status. It remains separate from N1–N6.

## Product and current state

- Gaffer is an OpenCV 5 football tactical-analysis project for an OpenCV + AWS hackathon. It analyses TeamTrack footage, estimates formations, detects candidate shape changes, verifies candidates with a deterministic policy and vision tools, renders evidence, and asks a coach to approve/reject alerts.
- Planning estimates: original scope about **70% complete**; expanded coach workflow about **85% complete** after N1-N5 (rough phase allocation). These are subjective repo-review/phase-allocation estimates, not code coverage or evaluation scores.
- The current app has a React/Vite analyst desk, FastAPI upload and results endpoints, offline clip analysis, a stored-data demo, trace-timed live replay, Bedrock integration, and a local/S3 artifact-storage interface. AWS public deployment is not recorded as complete.
- The project is on branch `phase4-integrate`; N3 remains uncommitted. `web/src/pages/AppPage.tsx` contains the user's existing `chatMatchId = uploaded ? uploaded.result.id : DEFAULT_MATCH.id` edit plus N2 replay and N3 bounded posture polling changes. Preserve the user's line and other local edits; inspect the working file before future edits.
- The standard demo event is White **4-4-2 → 3-4-3 at 16:30**. It is a confirmed formation change, not automatically a defensive or attacking posture. Blue's 18:50 change is a known miss/rejection under the return-leg rule.
- N2 Live analysis is a synchronized recorded TeamTrack live-style simulation, not a real camera stream. Upload analysis is offline/batch. N3 assesses stored confirmed events after verification; replay itself never triggers Bedrock.

## New coach-workflow requirements

1. Persist OpenCV-produced events and analysis in a queryable database; retrieve the evidence by match, team, time, and status.
2. Add a **Live analysis** entry with a camera/setup checklist. The hackathon demonstration plays real recorded TeamTrack footage as a clearly labelled **live-style simulation**; actual camera ingestion is later work.
3. Show the TeamTrack source video and tactical map side by side on one synchronized clock. Use only whitelisted consecutive top-view clips for the demo. Similar top/side filenames are not simultaneous.
4. At an event, show provisional formation-change status first. Do not show a preloaded final alert or label the event as “analysis started.” Store estimated event/onset time separately from detection and verification time.
5. Bedrock queries the persisted OpenCV metrics around a candidate and may call for further OpenCV analysis. It returns a separate, evidence-grounded attacking/defensive/hybrid/unclear posture assessment. Deterministic verification still decides whether the formation event is confirmed.
6. Add conditional, role-level advice only when event evidence, coach objective, and available bench roles support it. No invented player availability, named-player instructions, or automatic substitution. Coach approval/rejection and notes persist.

## Architecture and data constraints

- `MatchState` / `TacticalTimeline` v1.0 is explicitly frozen in `docs/DATA_CONTRACT.md`. Add a separately versioned event/analysis record or explicit migration; do not silently alter v1.0.
- Existing event detection and verifier are imperfect. Candidate onset, detection, verification, posture, recommendation, and coach decision must be separate state/time fields.
- Top-view drone output has no usable ball, possession, or pressing data. Do not claim these signals. Shape, line depth, width, compactness, centroid, player coverage, camera quality, and persistence may support cautious posture inference; use `unclear` otherwise.
- TeamTrack annotations are evaluation ground truth only. Runtime demo analysis must use the OpenCV pipeline's outputs.
- Keep OpenCV 5 substantive and AWS meaningful for the competition. Bedrock Nova 2 Lite (`global.amazon.nova-2-lite-v1:0`) in `ap-southeast-2` is the configured model, with Nova Micro fallback. Never put credentials in the repo or print `~/.aws` files.
- Preserve licenses and source credits. No broadcast footage, AGPL dependencies, or Ultralytics YOLO. TeamTrack is MIT-licensed; verify the exact notice before submission.
- Keep the one-process FastAPI + worker + web deployment constraint in mind. Existing S3 storage persists files; it is not a queryable database.
- Tests normally mock Bedrock; do not use live model calls in automated test runs.
- Do not commit, push, or modify the current user change without understanding it. The user commits manually per `CLAUDE.md`.

## N1 implementation status (2026-10-19)

- A stdlib SQLite event store is configured at `api.event_store.path` (default `outputs/api/events.sqlite3`), with event record schema 1.0 separate from the frozen contract v1.0.
- The upload worker persists OpenCV video events after verification. `/api/events` lists by match and optional analysis/team/status/time filters; `/api/events/{record_id}` returns event detail and coach-decision history.
- Migration 1 is transactional and versioned through `PRAGMA user_version` plus `schema_migrations`. Event decisions are append-only. Existing event artifacts are not imported automatically.
- N1 passed the API/store tests and Ruff in the local `.venv`; an existing OpenCV-produced TeamTrack `MatchState` yielded 9 stored and reopened rows (the raw TeamTrack upload worker was not rerun). See `RECORD.md` and `codex_changes.md` for exact commands/results and limitations.
- N1 did not add posture inference, conditional role advice, live video synchronization, UI work, or EC2 deployment; N2 supplied the replay UI, N3 supplied event posture, and N4 supplied deterministic conditional role advice with separately persisted coach responses. N5 local integration/UX acceptance is complete; AWS deployment/submission remains N6.

## N3 implementation status (2026-10-21)

- Confirmed video events trigger a separate Bedrock posture assessment after deterministic verification and persistence. Only `confirmed` rows are eligible; posture never changes verifier fields or coach-decision history.
- The typed posture result is schema 1.0 inside event record schema 1.1. SQLite migration 3 adds an indexed, bounded call/cost attempt ledger without changing frozen MatchState/TacticalTimeline v1.0.
- Exact metric path/value/unit/match-clock citations are validated against stored OpenCV metrics. Weak, conflicting, fabricated, low-quality, or unavailable evidence yields a clearly sourced `unclear` state. Ball, possession, pressing, intent, and opponent behavior are not invented.
- The upload worker can honor one short, post-onset OpenCV reanalysis request only with original video context, within the verification boundary and existing OpenCV cache/budget; one Bedrock follow-up consumes those metrics. The persisted-event CLI has no video context and stops safely if more visual evidence is requested.
- The replay card separates formation verification, posture, and coach decisions; result reveal uses `verification_match_time_s`, never `verification_time_utc`. Pending state uses bounded read-only polling. An explicit operator retry can reclaim a stale pending attempt only after the configured grace period.
- Local fake-Bedrock/backend and web tests pass; live Bedrock/AWS and EC2 were not tested. See `PLANNING.md`, `RECORD.md`, `codex_changes.md`, and the N3 trace example for exact checks/limits.

## Git instruction from the user

- Never push anything to Git for this project. The user explicitly requires all Git pushes to remain manual; preserve this instruction across every phase and chat.

## Markdown files reviewed (repository snapshot, 2026-10-19)

| File | Memory summary |
|---|---|
| `CLAUDE.md` | Core project facts, competition requirements, AWS/environment limits, coding rules, phase/session workflow, detailed measured results and current status. Governing Claude instructions. |
| `README.md` | Project pitch, quickstart, stack, credits/licensing TODO. Says original Phase 1 status in its older top-level status line; check against `docs/PLAN.md` before submission. |
| `START_HERE.md` | Old setup handoff for `C:\dev`; stale relative to current workspace path. Contains setup/history and instructions to use external `gaffer-prompts.md`, which is not in this repo inventory. |
| `docs/PLAN.md` | Original Phase 0–5 plan: phases 0–3 substantially done, Phase 4 app/backend integrated locally but AWS deploy and quality bar not completed, Phase 5 submission pending. |
| `docs/DATA_CONTRACT.md` | Frozen v1.0 MatchState/TacticalTimeline/Alert contracts plus a separate versioned persisted-event schema; coordinates, runtime vs ground-truth distinction, clip-list convention. |
| `docs/DATA_SOURCES.md` | Dependency/model/dataset licenses, TeamTrack source and credit, rejected broadcast sources, submission license checklist. |
| `docs/DATA_NOTES.md` | TeamTrack inventory/metadata/CSV details, camera geometry, view non-simultaneity, calibration/perception caveats and downloaded clip sets. |
| `data/README.md` | Dataset manifest, local layout, TeamTrack clip inventory, checksums/re-download instructions, calibration/synthetic sources. |
| `docs/AGENT_DESIGN.md` | Bedrock/OpenCV agent tools, deterministic verification policy, grounding, budgets/fallbacks, traces, eval method/results, known limits. |
| `docs/AGENT_TRACE_EXAMPLES.md` | Three real-footage trace examples: 16:30 White confirmation, contradictory second look, simulated pan refusal, plus the missed 18:50 event. |
| `docs/FAILURE_LOG.md` | Extensive dated failures and mitigations across detection, calibration, tracking, formations, verification, Bedrock text, report grounding, and UI integration. Update when new failures arise. |
| `docs/API.md` | FastAPI upload, pitch, status, results, event list/detail, alert, chat, SQLite migration/restart behavior, limits, storage, tests, and known limitations. |
| `docs/UI_DESIGN.md` | Original UX design brief and quality bar; later user decisions in `web/README.md` supersede selected visual choices. |
| `web/README.md` | Current frontend routes, VITE_API_URL modes, API hookup, upload/replay/chat behavior, later UI decisions and UI tests/scripts. |
| `deploy/README.md` | One-container local Docker/API/frontend operation, storage persistence notes, optional EC2 design, AWS IAM/cost/deploy constraints; image and live EC2 deployment were not proven there. |
| `samples/w900_1260/report_w900_1260.md` | Coach report for 15:00–21:00, one confirmed White event, known unalerted Blue event, three recommendations and limitations. |
| `outputs/agent_video_step7/report_w900_1260.md` | Same generated report artifact as the sample copy, with the source/template and same-match/oracle-window caveats. |
| `web/public/sample/w900_1260/report_w900_1260.md` | Bundled generated copy of the sample report for the static frontend. |
| `web/dist/sample/w900_1260/report_w900_1260.md` | Generated build copy of the same sample report; do not treat as the canonical source. |
| `.pytest_cache/README.md` | Generated pytest cache documentation; cache should not be committed. |

`outputs/agent_video_w900_1260/report_w900_1260.md` was referenced in an initial inventory probe but did not exist; the actual output report is under `outputs/agent_video_step7/`.

