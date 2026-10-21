# Gaffer New-Scope Plan

This roadmap adds the coach workflow described in [`CODEX_PLANNING.md`](CODEX_PLANNING.md). The original phase history remains in [`docs/PLAN.md`](docs/PLAN.md). **Do one numbered phase per Claude Code session. Do not start a phase until the user provides its prompt.**

## Progress snapshot

- Original project scope: approximately **70% complete** (earlier repo-review estimate).
- Expanded coach workflow: approximately **85% complete**, with approximately **15% remaining** (rough phase-allocation estimate revised after N1-N5).
- At the earlier 45% estimate, the remaining 55% included unfinished original Phase 4/5 work and the new coach-workflow requirements. The earlier phase breakdown did not list the AWS deployment and submission backlog explicitly; this revision adds it.
- These are planning estimates, not measured engineering metrics. The existing OpenCV, API, agent, UI, and TeamTrack work is reusable.
- Status for new phases: **N1-N5 complete; N6 not started**. This file tracks phase progress.

## Requirements sequence

```text
N1 Persist events -> N2 Replay real video at event time -> N3 Bedrock posture read
     -> N4 Conditional role suggestion + coach decision -> N5 Integrated QA / UX
     -> N6 EC2 deployment + submission package
```

| Phase | Work | Approx. share of the remaining work | Main outcome |
|---|---|---:|---|
| N1 | Queryable event persistence and event API | 15% | OpenCV candidates, verification, evidence references, and coach decisions can be saved and queried by match/time/team/status. |
| N2 | TeamTrack source-video replay, synchronized tactical map, event timing, and Live analysis setup | 20% | A judge sees the real recorded match and its synchronized analysis; the event appears as provisional at the correct match time. |
| N3 | Event-triggered Bedrock tactical-posture analysis | 20% | Stored evidence supports an attacking/defensive/hybrid/unclear read, with verification and citations kept separate. |
| N4 | Conditional role-level suggestions and coach feedback | 15% | Suggestions depend on coach context and available roles; approval/rejection is persisted. |
| N5 | End-to-end integration, existing Phase 4 UI/API acceptance, and reliability | 15% | The full flow works locally; current frontend, upload, Bedrock, accessibility, and stranger-test gaps are checked. |
| N6 | Actual AWS deployment and existing Phase 5 submission package | 15% | Public app runs on EC2 with AWS services verified, and judge-facing report/demo materials are ready. |

The percentages are a rough allocation of effort across the **remaining 55% of the expanded target**; they do not re-score the original project and are not exact completion points. Existing unfinished work is spread across N2, N5 and N6. Rough effort: about **5–8 focused working days** across N1–N6, with AWS permissions, EC2 setup and video synchronization as schedule risks. Keep scope lean enough to leave time to record the submission demo.

## N1 — Persist OpenCV events and query them

**Status:** Complete (2026-10-19).  
**Goal:** add durable, queryable event records without breaking the frozen `MatchState` v1.0 contract.

**Use what exists:** `MatchState`, `TacticalTimeline`, verification results, traces, evidence files, FastAPI jobs/results, and `api.storage` local/S3 artifact storage.

**Add:** a versioned event record and repository/database; persist candidate time, detected time, team, formations, compact pre/post metrics, quality/coverage, verification state/reason, evidence and trace references, Bedrock analysis status, recommendation status, and coach action. Add indexed reads by match, time, team, and state; add API endpoints or extend current endpoints for event history and event detail. Make writes idempotent and preserve decision history.

**Acceptance:**

- A processed TeamTrack match writes OpenCV-derived events to the database and the same event can be fetched by id and listed in match-time order after an app restart.
- Candidate, verified decision, AI analysis, and coach action have distinct state fields and timestamps.
- Existing demo/upload API and `MatchState` v1.0 readers remain compatible; a migration/version path is documented.
- No annotation CSV or ground-truth event is used by the runtime path.

**Implementation and acceptance result:** Added SQLite event persistence at the configurable
`api.event_store.path` (default `outputs/api/events.sqlite3`), separate event schema v1.0, explicit
startup migration, indexed match/time/team/status reads, detail lookup, and append-only coach
decisions. Existing OpenCV-produced TeamTrack `MatchState` data produced 9 persisted candidate
events and those rows remained queryable after reopening the DB. The upload-worker end-to-end test
also verifies event detail/list API reads after creating a new app against the same database, agent
and verification timestamps/status, and a persisted coach approval. Existing `MatchState` and
`TacticalTimeline` v1.0 were not changed; annotation sources are excluded by the persistence
projector. The TeamTrack smoke reused an already processed OpenCV `MatchState`; it did not rerun a
raw TeamTrack clip through the upload worker. Posture/recommendation remain `not_requested` for N1.
Checks and limitations are in
`RECORD.md` and `codex_changes.md`.

**Codex prompt (historical N1 task):**

```text
Work only on new-scope phase N1 in PLANNING.md. First read CLAUDE.md, PROJECT_MEMORY.md, CODEX_PLANNING.md, PLANNING.md, RECORD.md, docs/DATA_CONTRACT.md, docs/API.md, and the relevant storage/job/result code. Do not modify the user's existing change in web/src/pages/AppPage.tsx. Do not start N2 or later.

Implement durable, queryable event persistence for OpenCV-produced formation candidates and their later verification/coach decisions. Keep MatchState contract v1.0 unchanged; add a separate versioned event record and an explicit migration strategy. Inspect the existing local/S3 artifact storage and single-process API before choosing the smallest durable database design; keep the database path configurable and document how it persists across restart/deployment. Store candidate/onset, detection and verification times separately, compact OpenCV metrics, verification reason, trace/evidence references, analysis state, and coach decision history. Add match/time/team/status queries and safe API access. Do not use TeamTrack annotations as runtime input. Keep Bedrock out of this phase except for fields reserved in the event lifecycle. Preserve existing API behavior.

Before editing, report the files/modules you plan to change and any migration choice. Then implement only N1. At the end, summarize changes, commands/checks actually run and their results, known limits, and git status; do not commit. Update N1 status and progress in PLANNING.md and append one dated N1 entry to RECORD.md. If acceptance cannot be met, record the blocker and leave N2 not started.
```

## N2 — Synchronized recorded-match simulation

**Status:** Complete (2026-10-19).  
**Goal:** show source footage beside the tactical map and reveal event states in match time.

**Use what exists:** React analyst desk, timeline, `live` replay timing, upload/setup UI, TeamTrack top-view clips, and multi-clip source convention.

**Add:** a whitelisted TeamTrack video source for the 900–1260 s demo sequence; shared play/pause/seek/rate clock across clip boundaries; video plus map in adjacent panels; a **Live analysis** button and setup dialog (fixed elevated camera, whole pitch visible, distinct team shirts, choose the demo team coached, optional match objective/role context); an explicit “Recorded TeamTrack footage · live-style simulation” label. At event onset show a provisional “formation change — checking” state; transition to verified/rejected/uncertain only at the actual recorded verification point. Never preload the final alert before replay reaches it.

**Acceptance:**

- The 12 consecutive top-view clips play through without clock jumps, and pitch-map state, timeline cursor, and selected video stay synchronized while seeking and changing speed.
- The real match is visible beside the map; the UI clearly says the source is recorded simulation.
- White 4-4-2 → 3-4-3 is first shown as a formation-change candidate around 16:30, not as “opponent defensive”; verified status appears only when the recorded evidence/verification point is reached.
- Playback uses the event store/API from N1, not a hard-coded alert or ground-truth annotations. Clip paths are whitelisted.
- The setup dialog states camera placement and jersey requirements. It does not claim that a real camera is connected.

**Implementation and acceptance result (2026-10-19):** Added a manifest-backed allowlist for the 12 actual TeamTrack top-view clips from 900 to 1260 seconds, including byte-range responses for browser video seeking. The desk now plays the recorded footage beside the tactical map under one match clock, with play/pause, seeking and 1×/2×/4× controls; the setup dialog explains elevated camera placement, full-pitch framing and distinct jerseys, asks which team the coach represents, and says no camera is connected. The UI labels this as recorded live-style simulation.

The replay queries persisted N1 events. Authentic OpenCV candidate `evt_003` is a White 4-4-2 → 3-4-3 change at 990s (16:30); it appears as provisional/checking at candidate time and is shown as confirmed only from its stored match-clock evidence boundary at 1085s (18:05). That boundary is the completed verifier reanalysis-window end recorded in event schema 1.1 / DB migration 2; it is distinct from `verification_time_utc`. The event was verified against the actual TeamTrack footage and persisted through the OpenCV video workflow. No annotation/ground-truth data or hard-coded demo event/status is used at runtime. `MatchState` and `TacticalTimeline` v1.0 remain unchanged.

Browser acceptance exercised all 12 source segments, all 11 seek boundaries, and all 11 ended-to-next-clip handoffs through 1260s (each handoff was accelerated by seeking to the segment end). The shared clock stayed aligned; setup copy, playback rates and event timing were also checked. Backend and frontend checks are recorded in `RECORD.md` and `codex_changes.md`.

**Limits:** The initial detector result came from the already-generated OpenCV `MatchState`; this phase did not rerun full detection over the 12 raw clips. The verifier did reanalyze the selected event against the source video. Bedrock posture analysis and role-level advice remain N3/N4 work; the optional objective is collected but not used for advice. This is a recorded simulation, not a connected live camera. EC2 deployment remains N6.

**Claude Code prompt:**

```text
Work only on new-scope phase N2 in PLANNING.md. Read CLAUDE.md, PROJECT_MEMORY.md, CODEX_PLANNING.md, PLANNING.md, RECORD.md, web/README.md, docs/UI_DESIGN.md, docs/API.md, and the N1 event API/storage implementation. Preserve the existing user edit in web/src/pages/AppPage.tsx by inspecting it before any edit. Do not start N3 or later.

Build the recorded TeamTrack live-style simulation: show the actual whitelisted top-view source video beside the tactical map, synchronize both to one match clock across the consecutive 900–1260 s clips, and keep play/pause/seek/rate controls aligned. Add a “Live analysis” entry button and a concise setup dialog describing a fixed elevated camera, full pitch visibility, different team jerseys, which demo side is the coach's team, and optional match context. Starting it must say “Recorded TeamTrack footage · live-style simulation”; do not access a webcam or imply this is a live feed.

Drive event display from N1 records. At the event's match time, show the formation change as provisional/checking; transition only when its stored verification time/state is reached. Never display the final alert before replay reaches it. Keep “formation changed” distinct from any tactical-style interpretation, use OpenCV output for runtime, and whitelist clip serving. Do not alter detector or verifier decisions in this UI phase.

Implement only N2. At the end report changed files, actual checks and results, UI timing behavior, limitations, and git status; do not commit. Update N2 in PLANNING.md and append a dated N2 entry to RECORD.md. Leave N3+ not started.
```

## N3 — Bedrock reads tactical posture from persisted evidence

**Status:** Complete (2026-10-21).  
**Result:** Confirmed OpenCV events now receive a separate, typed Bedrock posture assessment after deterministic verification and SQLite persistence. Exact metric citations and posture claims are validated; one bounded source-video OpenCV reanalysis plus one follow-up call is available only when evidence is incomplete. The replay card keeps posture separate and withholds it until `verification_match_time_s`. Event schema 1.1 and frozen MatchState/TacticalTimeline v1.0 remain unchanged; DB migration 3 adds the call/cost attempt ledger. Fake-model/backend, API upload, UI, and browser replay checks passed. Live Bedrock/AWS was not called. See `RECORD.md` and `codex_changes.md` for commands, results, and limits.  
**Goal:** invoke Bedrock because a persisted formation event needs interpretation, not on every frame.

**Use what exists:** Bedrock Converse/tool calling, data and vision tools, deterministic `verify.py`, trace/citation checks, explanation grounding, daily and per-match budgets.

**Add:** an event-triggered agent step that queries the event store for bounded pre/post windows; evidence-based posture enum `attacking | defensive | hybrid | unclear`; cited metrics and confidence/uncertainty; bounded OpenCV re-analysis if it changes the next action; validated JSON output; explicit fallback to `unclear` or deterministic template when Bedrock is unavailable. Keep OpenCV verification authoritative and posture analysis advisory.

**Acceptance:**

- A saved event triggers one bounded Bedrock analysis using retrieved, compact OpenCV metrics and references; the raw full match is not sent as an unstructured prompt.
- The event `4-4-2 → 3-4-3` is stored and shown as a formation change first; it is called attacking/defensive/hybrid only if cited metrics support it, otherwise `unclear`.
- Posture claims cite the exact event metrics/time/evidence; absent ball/possession/pressing are never invented.
- Malformed output, timeouts, throttling, and no credentials produce a safe fallback and do not bypass deterministic verification.
- The trace demonstrates how an OpenCV result affected the next agent step; Bedrock is called per candidate event, not per video frame.

**Claude Code prompt:**

```text
Work only on new-scope phase N3 in PLANNING.md. Read CLAUDE.md, PROJECT_MEMORY.md, CODEX_PLANNING.md, PLANNING.md, RECORD.md, docs/AGENT_DESIGN.md, docs/AGENT_TRACE_EXAMPLES.md, docs/DATA_CONTRACT.md, docs/API.md, and the N1/N2 implementation. Do not start later phases N4–N6.

Add an event-triggered Bedrock agent step that retrieves the persisted event and bounded pre/post OpenCV metrics from the N1 store, can request a targeted OpenCV re-analysis when evidence is insufficient, and returns schema-validated posture: attacking, defensive, hybrid, or unclear. Include evidence references, clock, metrics, and uncertainty. The deterministic verifier remains the authority for whether a formation change is confirmed/rejected/uncertain; Bedrock posture is a separate advisory result and cannot rewrite that decision. Never infer posture solely from the formation name. The real top-view pipeline has no usable ball/possession/pressing, so do not cite or invent those; prefer unclear when available metrics do not support a reading. Keep prompts compact, enforce existing Bedrock budgets, and provide a clear fallback when Bedrock fails.

The OpenCV/tool result must affect what the agent does next, and the trace must make that causal step inspectable. Call Bedrock on candidate events only, never per frame. Use the White 4-4-2 to 3-4-3 event as a formation-change example, not a pre-labelled defensive event.

Implement only N3. Report files changed, actual checks/results, Bedrock fallback behavior, and remaining limits; do not commit. Update N3 in PLANNING.md and append a dated N3 entry to RECORD.md. Leave N4–N6 not started.
```

## N4 — Conditional role-level coach suggestions

**Status:** Complete (2026-10-21).  
**Result:** Added deterministic, optional role advice from confirmed persisted events, validated N3 posture, and explicit coach side/objective/available roles. Advice is conditional, cites only N3 evidence, and is withheld when context or evidence is insufficient. Coach accept/reject/note is stored in separate append-only recommendation history, distinct from alert approval. Advice appears only after the event's stored verification match-time boundary. No N4 Bedrock call was added. Migration 4 adds recommendation and response storage; N1–N3 contracts remain intact. Backend, frontend, lint, and production build checks passed; see `RECORD.md` and `codex_changes.md` for details and limits.  
**Goal:** convert supported posture evidence into an optional, context-aware role suggestion for the coach.

**Use what exists:** N3 posture/evidence, coach approve/reject UI, chat/report surfaces, alert append-only history.

**Add:** coach-side selection, objective (chase/protect/balanced), available substitute roles (attacker/midfielder/defender), and a recommendation object with condition, action at role level, why, cited event evidence, and confidence. The suggestion is optional and must be withheld when context or evidence is missing. Store coach accept/reject/note separately from the system's suggestion.

**Acceptance:**

- Advice is framed as a conditional option, never as an automatic substitution or a named-player decision.
- A defender-for-attacker suggestion appears only when the event evidence, coach objective, and available attacking role support it.
- If the coach is protecting a lead, no attacking-substitution suggestion is emitted merely because a formation changed; missing context yields “need coach context” or no suggestion.
- The alert keeps formation verification, posture assessment, suggestion, and coach decision visually and structurally distinct.
- Approve/reject and coach notes persist against the event and appear in its history.

**Implementation and acceptance result:** Coach side, match objective, and available substitute roles are collected in the existing Live Analysis setup. A deterministic policy emits conditional attacker/defender role options only when the confirmed event, supported persisted posture, cited metrics, and coach context align. Unsupported posture, missing context, own-team event, or weak/out-of-window citations produce a persisted withheld state without an action. The recorded-event card reveals advice only after `verification_match_time_s`; recommendation response controls and notes persist separately from alert decisions. Database migration 4 adds append-only recommendation snapshots and response history. No named players, automatic substitutions, new Bedrock calls, N5 work, or N6 deployment work were added.

Checks: targeted backend tests for recommendations, event store, and API passed; Ruff passed for changed backend/test files; web tests passed (29 tests across 3 files); web lint and same-origin production build passed; `git diff --check` passed. No live Bedrock/AWS call was made. Existing upload-pipeline NumPy all-NaN warnings remain non-failing. See `RECORD.md` and `codex_changes.md` for exact commands, scenarios, and limitations.

**Claude Code prompt:**

```text
Work only on new-scope phase N4 in PLANNING.md. Read CLAUDE.md, PROJECT_MEMORY.md, CODEX_PLANNING.md, PLANNING.md, RECORD.md, the N1 event model, N3 posture schema/trace, current alert API, and the relevant React alert/setup components. Preserve the user's uncommitted AppPage.tsx change. Do not start N5 or N6.

Add optional, conditional, role-level tactical suggestions. Collect the coach's team, objective (chase a goal, protect a lead, balanced), and available substitute roles; do not require player names. The suggestion must cite the persisted event/posture evidence and state its condition, e.g. “If you are chasing a goal and an attacking substitute is available, consider replacing a defender with an attacker.” Do not emit this when the objective, role availability, or supporting evidence is missing; provide a clear “not enough context/evidence” state instead. Never issue an automatic substitution, assert player availability that was not entered, or call a formation change defensive/attacking without the N3 supported posture assessment.

Keep formation verification, posture, suggestion, and coach response as separate records/states. Persist approve/reject and optional coach note in the event history. Implement only N4 and preserve existing alert behavior outside the new flow.

At the end report changed files, actual checks/results, example supported and withheld suggestions, and git status; do not commit. Update N4 in PLANNING.md and append a dated N4 entry to RECORD.md. Leave N5 and N6 not started.
```

## N5 — End-to-end integration and UX acceptance

**Status:** Complete (2026-10-21).  
**Goal:** make the full new flow work reliably on the local integrated app and close the unfinished original Phase 4 frontend/API acceptance items before deployment.

**Use what exists:** one-process FastAPI + worker + React app, offline upload/pitch flow, Bedrock client/fallback, stored demo API, UI quality bar in `docs/UI_DESIGN.md`, and existing Playwright walkthrough.

**Add/finish:** local end-to-end integration from Live analysis to coach decision; restart persistence; Bedrock-off fallback; real video sync checks; actual Bedrock call from the connected app if available; upload and error-state review; UI accessibility/performance/reduced-motion checks; a short stranger-understanding test. This phase closes the local/frontend/API portion of the original Phase 4. AWS resources are deployed in N6.

**Implementation and acceptance result (2026-10-21):** The documented one-process FastAPI + worker + React quickstart was run locally and exercised through the connected browser. TeamTrack replay passed the 12-clip/11-boundary synchronization and provisional-to-confirmed timing check. A real connected Bedrock posture request was made within the configured per-event/day budget ($0.001064); the guard rejected its unsupported ball/possession/pressure/intent claim, so persisted posture stayed `unclear`/failed and advice was withheld. The no-Bedrock path likewise stored `unavailable`/`unclear` with no action. Browser/API checks verified supported conditional role advice with persisted N3 citations, and that a coach rejection/note remained separate from alert decisions after stopping and restarting the local API against the same SQLite database. The supported-advice persistence fixture was synthetic and isolated from the TeamTrack demonstration. Upload, pitch correction, results, uploaded report, alert approve/reject, and coach-readable invalid-video errors passed in the connected browser. A Windows transient status-file replace lock found during polling was mitigated with bounded retries and a regression test. UX follow-up changed the replay label to explicitly say recorded footage/replay, and explains why role advice can be withheld. One unfamiliar person completed a five-minute walkthrough and, after the copy change, accurately identified the source as recorded TeamTrack footage rather than a live camera. Their advice click surfaced a saved-response HTTP 409 state; the UI now explains the persisted coach context, and the exact mismatch scenario passes the connected browser check. The person did not provide a further retest of that final message, which is recorded as a limitation. N5 local acceptance is complete; N6 remains not started and no AWS resources were deployed.

**Acceptance:**

- A fresh run follows Live analysis → recorded synchronized footage → provisional formation event → OpenCV verification + Bedrock posture → conditional role suggestion (if supported) → coach decision.
- Database and event history survive a local server restart; no final event or suggestion is fabricated when Bedrock is unavailable.
- The connected local frontend, real upload path, pitch confirmation, results, report, and approve/reject flow work with the backend; errors remain coach-readable.
- `docs/UI_DESIGN.md` quality items are checked: keyboard/focus, contrast, reduced motion, responsive layout, performance and accessibility. A stranger can explain the product after a brief look.
- Reports distinguish synthetic evaluation from TeamTrack demonstration; known misses, limited footage, missing ball/possession, and any unclear outputs are disclosed.
- Local quickstart and integration instructions match the implementation.
- The demo visibly states recorded footage; no claim of true live camera analysis.

**Claude Code prompt:**

```text
Work only on phase N5 in PLANNING.md. Read CLAUDE.md, PROJECT_MEMORY.md, CODEX_PLANNING.md, PLANNING.md, RECORD.md, docs/API.md, docs/UI_DESIGN.md, docs/FAILURE_LOG.md, and the completed N1–N4 code/docs. Do not start N6 or add unrelated features.

Complete local end-to-end integration and close original Phase 4 frontend/API acceptance gaps. Verify Live analysis setup, synchronized TeamTrack video/map, provisional-to-verified event timing, persistent event history after local restart, Bedrock-unavailable fallback, connected upload/pitch/results/report/coach decision flow, and coach-readable errors. Check the existing UI quality bar (keyboard access, focus, contrast, reduced motion, responsive behavior, performance/accessibility) and get a short stranger-understanding check. Keep synthetic metrics separate from the one-match TeamTrack demonstration and disclose known failures and missing ball/possession/pressing. Do not deploy AWS resources in N5.

Keep only fixes needed for N5. At the end give the end-to-end outcome, checks actually run and their results, unresolved issues, and git status; do not commit. Mark N5 complete only if its acceptance criteria are met, update PLANNING.md, and append a dated N5 record to RECORD.md. Leave N6 not started.
```

## N6 — AWS EC2 deployment and submission package

**Status:** Not started.  
**Goal:** complete the unfinished original Phase 4 cloud deployment and Phase 5 judge-facing submission work.

**Use what exists:** `deploy/Dockerfile`, one-process deployment design, `deploy/README.md`, S3 storage adapter, Bedrock configuration, existing AWS region/account setup, IAM role design, API health endpoint, and measured evaluation/failure records.

**Add/finish explicitly:** build and run the combined app on EC2 in `ap-southeast-2` using an IAM instance role (no static keys); configure durable output/database storage and S3 for the configured artifacts; verify an actual OpenCV vision call runs on EC2; verify Bedrock from the deployed app and its fallback; configure CloudWatch logs/metrics and an AWS Budget alarm; expose and smoke-check a public URL; document a clean redeploy and resource cleanup/costs. Then prepare the technical report, architecture diagram, agent workflow, README judge section, screenshots, <=5-minute demo script/video, and final license/failure/reproducibility audit. Do not submit on Devpost on the user's behalf.

**Acceptance:**

- The public app URL serves the combined frontend and API; `/api/health` reports the expected OpenCV/AWS configuration.
- A deployed analysis or vision-tool check demonstrates OpenCV execution on EC2. Bedrock event analysis works from the deployed app, or a specific account/permission/quota blocker and safe fallback are documented without claiming success.
- S3/file/database persistence survives the documented restart/redeploy path; IAM uses roles rather than credentials in files or images.
- CloudWatch receives useful application/analysis logs and the agreed basic metrics; the budget alarm is verified.
- A clean redeploy follows the written steps. Actual AWS resources and estimated/observed costs are listed; no unsupported free-tier claim is made.
- Technical report, architecture and agent diagrams, README, failure evidence, screenshots and <=5-minute demo materials agree with measured results and clearly label TeamTrack as one-match demonstration and recorded footage.

**Claude Code prompt:**

```text
Work only on phase N6 in PLANNING.md. Read CLAUDE.md, PROJECT_MEMORY.md, CODEX_PLANNING.md, PLANNING.md, RECORD.md, docs/PLAN.md, docs/FAILURE_LOG.md, docs/DATA_SOURCES.md, docs/API.md, deploy/README.md and completed N1–N5 work. The user has already authorized project work; do not repeatedly ask for permission. Preserve the user's existing AppPage.tsx edit. Do not commit or submit to Devpost.

Complete the original unfinished AWS/deployment scope as well as the submission package. Deploy the single-process Docker app to EC2 in the already configured Sydney region using an IAM instance role and no static keys. Configure/verify persistent event database and artifact storage, S3 where the existing storage backend requires it, a real OpenCV vision-tool execution on EC2, Bedrock from the deployed app and its safe fallback, CloudWatch application logs/metrics, an AWS Budget alarm, public URL and clean redeploy instructions. Use the existing account and current permissions; record exact blockers and actual resource costs if an AWS action cannot complete. Do not claim deployment or cloud checks succeeded unless they were actually observed.

Prepare the judge-facing technical report, architecture and agent-workflow diagrams, README OpenCV/AWS sections, failure evidence, screenshots, and a demo script/video capped at five minutes. Keep synthetic evaluation separate from the single-match TeamTrack demonstration; disclose limitations and state that the video is a recorded simulation, not a live camera. Do not create unrelated services or submit on Devpost.

At the end report the public URL (if deployed), AWS resources and observed/estimated costs, checks actually run and results, remaining external blockers, and git status. Update N6 and overall progress in PLANNING.md and append a dated N6 entry to RECORD.md. Mark N6 complete only when the acceptance criteria above are met.
```

## After each phase

The completing Claude Code session must:

1. Stop at the current phase and report what changed, what was actually checked, and what remains.
2. Update that phase's status, evidence, and revised overall estimate in this file.
3. Append a dated entry using the template in `RECORD.md`.
4. Never mark a phase complete if acceptance items remain unmet; leave the next phase not started.
5. Show `git status` and suggest a commit message, but do not add/commit/push.

