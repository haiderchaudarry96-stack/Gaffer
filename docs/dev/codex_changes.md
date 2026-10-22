# Codex Changes Log

This is the append-only implementation report for the Gaffer N1-N6 phase plan. Every time Codex completes or attempts a phase, append one dated report here. Keep old entries unchanged; do not claim a phase is complete unless its acceptance criteria were actually met.

## Reporting rules

- Record the phase, date, status (complete / partial / blocked), intended scope, actual changes, files changed, exact checks/commands and results, acceptance outcome, known failures/risks, and remaining work.
- If a phase is blocked or only partly completed, still append an entry and say what remains.
- Keep this report consistent with PLANNING.md and RECORD.md.
- Never put AWS keys, tokens, passwords, full account IDs, or private credentials in this file. Use resource names/region only when useful.
- Do not commit or push Git changes. User manages Git manually.

## Phase status at file creation (2026-10-19)

- N1 — Not started
- N2 — Not started
- N3 — Not started
- N4 — Not started
- N5 — Not started
- N6 — Not started

No N1-N6 implementation phase had started when this log was created.

## Entry template

Copy this template to the end of the file for each attempted/completed phase:

### YYYY-MM-DD — N# — Status: complete / partial / blocked

**Goal and scope:**

**Changes made:**

**Files changed:**

**Checks run and exact results:**

**Acceptance criteria:** met / partly met / not met (evidence):

**Failures, risks, or blockers:**

**Remaining work / next phase state:**

### 2026-10-19 — N1 — Status: complete

**Goal and scope:** Persist OpenCV-produced candidate events in a durable, queryable store; keep onset, detection, verification, agent, recommendation and coach-decision lifecycle data separate; add safe list/detail API reads; preserve the frozen v1.0 contracts and existing UI. N2 and later were not started.

**Changes made:** Added a stdlib SQLite repository and separate persisted-event schema v1.0. Startup applies transactional migration 1 using `schema_migrations` and `PRAGMA user_version`. The API worker writes video-source event records idempotently after verification. Indexed reads support match order and optional analysis/team/status/time filters. Event detail hydrates append-only coach decision history. Upload alert decisions remain in `alerts.jsonl` and mirror into the event DB where the event exists. Added configurable `api.event_store.path`, defaulting to `outputs/api/events.sqlite3`; documented restart, migration and EBS behavior. No UI files changed.

**Files changed:** `config.yaml`; `deploy/README.md`; `docs/API.md`; `docs/DATA_CONTRACT.md`; `src/gaffer/api/event_store.py` (new); `src/gaffer/api/jobs.py`; `src/gaffer/api/main.py`; `tests/test_event_store.py` (new); `tests/test_api.py`; `PLANNING.md` (N1 only); `RECORD.md`; `codex_changes.md`; `CLAUDE.md`; `PROJECT_MEMORY.md`. Existing user edit `web/src/pages/AppPage.tsx` was inspected and preserved without edits.

**Checks run and exact results:**

- `py -m pytest tests/test_event_store.py -q` — failed to start: system Python 3.14 has no `pytest` installed.
- `.\.venv\Scripts\python.exe -m pytest tests/test_event_store.py -q` — passed (4 tests).
- `.\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_event_store.py -q` — passed before the final per-event timestamp addition; only three existing NumPy NaN warnings in `test_pipeline_failure_is_coach_readable` from `src/gaffer/perception/pitch.py`.
- `.\.venv\Scripts\python.exe -m pytest tests/test_event_store.py tests/test_api.py::test_upload_end_to_end_agent_confirms_a_real_change tests/test_api.py::test_alerts_approve_reject tests/test_api.py::test_rules_fingerprint_is_frozen -q` — passed after adding per-event agent completion timestamps.
- `.\.venv\Scripts\ruff.exe check src/gaffer/api/event_store.py src/gaffer/api/jobs.py src/gaffer/api/main.py tests/test_event_store.py tests/test_api.py` — passed.
- `git diff --check` — passed (tracked diffs have no whitespace errors).
- TeamTrack smoke check using `outputs/match_state_top_w900_1260_4fps.json` — input had `source=video`, 720 frames; 9 candidates were persisted to a temporary SQLite DB, then listed after reopening in match-time order. Passed.

**Acceptance criteria:** Met. TeamTrack OpenCV-produced events persisted and survived reopening; upload end-to-end tests fetched/listed events through a new app backed by the same database. Candidate and detection match times, verifier status/time, agent status/completion time, and coach decision/time are separate fields. The coach approval survived DB reopen. Existing upload/alert API tests and frozen rules fingerprint passed. `MatchState`/`TacticalTimeline` v1.0 files and types were not changed. The projector returns no rows for annotation-source matches.

**Failures, risks, or blockers:** No N1 blocker remains. The TeamTrack-specific smoke reused a previously processed OpenCV `MatchState`; it did not rerun a raw TeamTrack video through the API worker. Posture/role recommendation stay `not_requested` for N1. Existing JSON results are not automatically imported; reprocess a video to populate the new DB. SQLite requires the configured file path to be on persistent local storage; EC2 needs EBS because S3 artifact storage does not persist SQLite. Alert JSONL and SQLite are separate writes; if the DB mirror fails after the alert append, the alert itself remains saved, the API returns 503 and logs the inconsistency. Three non-failing pre-existing NaN warnings occurred in an unrelated pitch-refusal test.

**Remaining work / next phase state:** N1 complete; N2 (synchronized TeamTrack source-video replay and setup UX) remains not started. N3-N6 remain not started. No commit or push was performed; Git changes remain for the user to review.

### 2026-10-19 — N2 — Status: complete

**Goal and scope:** Add the synchronized recorded TeamTrack simulation, retrieve persisted N1 events, reveal provisional and final states using match-clock evidence time, and add the Live analysis setup UX. N3 and later were not started.

**Changes made:** Added `/api/replay/teamtrack` plus an allowlisted clip route with HTTP Range responses, limited to the configured 12 top-view clips from 900–1260 seconds. The frontend uses one playlist video element and one match clock for the real source video, tactical map, seeking, play/pause and 1×/2×/4×. Added the Live analysis dialog with camera placement, whole-pitch and distinct-shirt requirements, coach-side selection, optional objective, recorded-simulation wording and an explicit no-camera-connected statement. Persisted N1 events now appear only at candidate time; `RecordedEventCard` stays provisional through the evidence window and changes to the stored verifier status only at the match-clock reveal boundary.

The event schema moved from 1.0 to 1.1 with DB migration 2 and nullable `verification_match_time_s`. This is an explicit match-clock point based on the end of a completed verifier reanalysis window, not a comparison against `verification_time_utc`. Frozen `MatchState` and `TacticalTimeline` v1.0 remain intact. No runtime annotation/ground-truth input or hard-coded demo event/status was introduced.

The live replay store contains authentic OpenCV event `evt_003` for White 4-4-2 → 3-4-3: onset 990s, detection 1025s, confirmed at match-time 1085s after the verifier window `[945,1085]`. The candidate came from an existing OpenCV-produced `MatchState`; the normal rules verifier reanalyzed the actual source footage and persisted the result. Full detector processing was not rerun over every raw clip in this phase.

**Files changed:** `config.yaml`; `docs/API.md`; `docs/DATA_CONTRACT.md`; `scripts/run_agent_video.py`; `src/gaffer/api/event_store.py`; `src/gaffer/api/main.py`; `src/gaffer/api/teamtrack_replay.py` (new); `tests/test_api.py`; `tests/test_event_store.py`; `tests/test_teamtrack_replay.py` (new); `web/README.md`; `web/scripts/e2e-teamtrack-replay.mjs` (new); `web/src/components/app/Stage.tsx`; `web/src/components/app/RecordedEventCard.tsx` (new); `web/src/components/app/teamTrackPlayer.ts` (new); `web/src/components/app/transport.ts`; `web/src/data/teamtrack.ts` (new); `web/src/data/teamtrack.test.ts` (new); `web/src/pages/AppPage.tsx`; `PLANNING.md` (N2 and progress snapshot only); `RECORD.md`; `codex_changes.md`. The user's existing `chatMatchId` edit was preserved.

**Checks run and exact results:**

- `.\.venv\Scripts\python.exe -m pytest tests/test_event_store.py tests/test_teamtrack_replay.py tests/test_api.py -q` — passed; 3 non-failing NumPy NaN warnings from `test_pipeline_failure_is_coach_readable`.
- `.\.venv\Scripts\ruff.exe check src/gaffer/api/event_store.py src/gaffer/api/main.py src/gaffer/api/teamtrack_replay.py scripts/run_agent_video.py tests/test_event_store.py tests/test_teamtrack_replay.py tests/test_api.py` — passed (`All checks passed!`).
- `npm test -- --reporter=dot` (in `web`) — 3 test files and 28 tests passed.
- `npm run lint` (in `web`) — passed after declaring the Playwright browser global.
- `$env:VITE_API_URL='/'; npm run build` (in `web`) — passed; production build completed.
- `$env:CHROMIUM_PATH='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'; $env:BASE_URL='http://127.0.0.1:8011'; node scripts/e2e-teamtrack-replay.mjs` (in `web`) — passed: setup copy, 12 source segments, 11 seek boundaries, 11 clip handoffs, shared map/video clock, speed rates and event reveal at 1085s.
- `.\.venv\Scripts\python.exe scripts/run_agent_video.py --sets w900 --arm rules --fresh --candidates evt_003 --out outputs/agent_video_teamtrack_replay --persist-teamtrack-events` — completed and persisted one confirmed event.
- `git diff --check` — passed.

**Acceptance criteria:** Met. The browser demonstrated source footage adjacent to the pitch map, synchronized playback and event gating. The candidate is not shown before 990s; it remains provisional until 1085s; confirmed state appears only at/after that evidence boundary. The video source is fixed to the configured allowlist and visibly identified as recorded simulation.

**Failures, risks, or blockers:** No N2 acceptance failure remains. The API suite emitted three existing NumPy all-NaN warnings from a pipeline-failure test. During rapid segment changes, Windows asyncio Proactor logged connection-reset callbacks for canceled Range reads; the Range responses completed and all replay checks passed. Bedrock posture classification (N3), role suggestions/coach decisions (N4), real camera integration, raw-video full detector rerun and EC2 deployment (N6) remain future work. The optional setup objective is stored only in UI state and does not yet affect advice.

**Remaining work / next phase state:** N2 complete. N3 (event-triggered Bedrock posture classification) is next and remains not started. N4–N6 remain not started. No commit or push was performed.
### 2026-10-21 — N3 — Status: complete

**Goal and scope:** Assess tactical posture from a persisted, deterministically confirmed OpenCV event. Keep posture advisory and separate from the verified formation event, verifier fields, and coach decisions. Do not add N4 role-level advice.

**Implementation:** Added Bedrock posture assessment over a bounded event snapshot with typed result schema 1.0, exact metric citations, unit/time-window validation, paired metric support, quality/conflict downgrade, and an explicit `bedrock` versus `deterministic_fallback` source. Only confirmed records are eligible. Bedrock never receives a full-match video or TeamTrack annotation/GT. One optional post-onset OpenCV reanalysis may run from the upload worker's live source context within existing cache/budget limits and no later than the verifier boundary; one second Bedrock request consumes its metrics. The persisted-event CLI safely declines a visual request because it has no video context. Idempotent retries are explicit; a stale pending result can be reclaimed after 900s only with `--retry`, and an old attempt cannot overwrite the new attempt. The API has no public posture-write endpoint.

**Schema/API/UI:** SQLite DB migration 3 creates indexed `posture_attempts` reservation/accounting rows. Event schema remains 1.1; frozen MatchState/TacticalTimeline v1.0 unchanged. No new HTTP route. Existing read-only event API returns posture fields. Replay UI displays separate citations/result only at `verification_match_time_s` and uses bounded read-only polling while pending. `web/src/pages/AppPage.tsx` retains the user's `chatMatchId = uploaded ? uploaded.result.id : DEFAULT_MATCH.id` edit.

**Files changed:** `CLAUDE.md`; `CODEX_PLANNING.md`; `PLANNING.md`; `PROJECT_MEMORY.md`; `config.yaml`; `docs/AGENT_DESIGN.md`; `docs/AGENT_TRACE_EXAMPLES.md`; `docs/API.md`; `docs/DATA_CONTRACT.md`; new `scripts/analyze_event_posture.py`; new `src/gaffer/agent/posture.py`; `src/gaffer/api/event_store.py`; `src/gaffer/api/jobs.py`; `tests/test_api.py`; `tests/test_event_store.py`; new `tests/test_posture.py`; `web/src/components/app/RecordedEventCard.tsx`; `web/src/data/teamtrack.ts`; `web/src/pages/AppPage.tsx`; this log and `RECORD.md`.

**Exact checks/results:**

- `\.venv\Scripts\python.exe -m ruff check` — passed for all repository Python files.
- `\.venv\Scripts\python.exe -m pytest tests\test_posture.py tests\test_event_store.py tests\test_teamtrack_replay.py -q` — 26 passed.
- `\.venv\Scripts\python.exe -m pytest tests\test_api.py::test_upload_end_to_end_agent_confirms_a_real_change -q -vv` — 1 passed in 105.30s. This covers OpenCV job completion, persisted event list/detail, restart reads, coach-decision history, and the no-client posture fallback.
- `npm test` (in `web`) — 3 test files, 29 passed.
- `npm run lint` (in `web`) — passed.
- `$env:VITE_API_URL='/'; npm run build` (in `web`) — passed.
- `BASE_URL=http://127.0.0.1:8011`, `CHROMIUM_PATH=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, `node scripts/e2e-teamtrack-replay.mjs` (in `web`, isolated no-Bedrock server) — passed: 12 clips, 11 seek boundaries, 11 playback handoffs, 1×/2×/4× rates, event reveal at 1085s.
- `\.venv\Scripts\python.exe scripts\analyze_event_posture.py --help` — passed.
- `git diff --check` — passed; Git printed only LF-to-CRLF normalization warnings for `docs/AGENT_DESIGN.md` and `docs/AGENT_TRACE_EXAMPLES.md`.

**Acceptance:** Met for local/fake Bedrock execution. Tests cover supported attacking/defensive/hybrid reads, weak/conflicting evidence, fabricated citations, unavailable ball/possession/pressure/pressing, missing credentials/throttle/timeout/malformed/budget failures, SQLite reopen/idempotency, stale retry ownership, unchanged verifier/coach history, and replay-time reveal. No live AWS request was made; real model access, credentials, quota, and billing remain unverified.

**Failures/risks:** The initial API end-to-end run failed on an N1-era assertion expecting `posture_status=not_requested`; N3 correctly stores `unavailable` with a labelled `unclear` fallback when no Bedrock client is configured. The test was updated and rerun successfully. Initial browser attempts used a static build without `VITE_API_URL=/`; rebuilding in documented same-origin mode made the isolated browser check pass. The isolated browser server also logged the known Windows Proactor reset callbacks for canceled Range reads; requests returned partial responses and replay checks passed. Top-view ball/possession/pressing evidence remains unavailable. The operator CLI has no source-video context, so it cannot satisfy a request for extra visual evidence. No EC2/deployment work was done.

**Remaining work / next phase:** N4 conditional role-level advice, N5 end-to-end integration/polish, and N6 AWS deployment/submission remain not started.

**Git:** Read-only `git status --short` inspected on `phase4-integrate`; pre-existing N1/N2 local changes remain alongside N3 files. No commit or push was performed.

## 2026-10-21 — N4 — Conditional role-level advice

**Implementation:** Added deterministic conditional recommendations based on confirmed events, completed N3 posture, validated metric citations, and coach side/objective/available roles. The policy does not call Bedrock. It withholds action when context, posture, source, citations, or verification-boundary constraints fail. The UI collects explicit coach context, reveals recommendations only after the event's stored match-time verification boundary, and allows accept/reject plus note. A separate migration-4 table records recommendation snapshots, and another append-only table records coach responses independently of alert approvals.

**API/data/UI:** Added recommendation creation and response endpoints. Event schema 1.1 and MatchState/TacticalTimeline v1.0 remain unchanged. Live Analysis setup supports context entry and replay updates; event cards show conditional options, evidence citations, withheld reasons, and persisted response state.

**Files changed:** new `src/gaffer/agent/recommendations.py`; `src/gaffer/api/event_store.py`; `src/gaffer/api/main.py`; new `tests/test_recommendations.py`; `tests/test_event_store.py`; `tests/test_api.py`; `web/src/data/teamtrack.ts`; `web/src/data/teamtrack.test.ts`; `web/src/components/app/RecordedEventCard.tsx`; `web/src/pages/AppPage.tsx`; `docs/API.md`; `docs/DATA_CONTRACT.md`; `web/README.md`; `PLANNING.md`; `RECORD.md`; this log; `CODEX_PLANNING.md`; `PROJECT_MEMORY.md`; `CLAUDE.md`.

**Checks/results:** `pytest tests/test_recommendations.py tests/test_event_store.py tests/test_api.py -q` passed, with three known NumPy all-NaN warnings from the existing pipeline failure test. Targeted Ruff passed. `npm test` passed (3 files, 29 tests), `npm run lint` passed, and same-origin `npm run build` passed. `git diff --check` passed. No real Bedrock/AWS request was made.

**Limitations and status:** This conservative deterministic policy is not a calibrated tactical model. The input evidence lacks ball, possession, pressing, and player-level availability; suggestions are role-level and conditional. N5 integration/UX acceptance and N6 AWS deployment/submission remain not started. `PLANNING.md` estimate revised to about 83% complete / 17% remaining (phase-allocation estimate only). Existing local changes remain uncommitted; no commit or push.
