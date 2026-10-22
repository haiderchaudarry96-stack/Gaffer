# Codex Planning: Gaffer Coach Workflow

**Latest implementation status (2026-10-21):** N1 persisted events, N2 synchronized recorded
TeamTrack replay, N3 event-triggered Bedrock posture assessment, and N4 conditional role advice are
complete. N5 local integration and UX acceptance is complete; N6 AWS deployment/submission remains not started. The expanded workflow estimate is about 85% complete. This is a rough phase-allocation estimate, not a measured metric.
See `PLANNING.md`, `RECORD.md`, and `codex_changes.md` for phase evidence and limitations.

**Purpose:** preserve the product requirements and the before/after project flow for Codex and Claude Code. This extends the original engineering plan in `docs/PLAN.md`; it does not replace the frozen Phase 0–5 history.

## Project status before the new requirements

The earlier repo review estimated the original Gaffer scope at **about 70% complete**. This is a reasoned project estimate, not a code coverage or test metric. The revised coach workflow was estimated at **about 45% complete** because it adds substantial work to the original scope.

Existing foundations to build on:

- OpenCV 5 perception and tactics pipeline, formation timeline, candidate events, deterministic verification, evidence rendering, and coach approve/reject flow.
- FastAPI upload/analysis API, local/S3 file-storage interface, React analyst desk, recorded trace-based replay, reports, and a Bedrock client/agent framework.
- TeamTrack data and a confirmed demonstration event: White changes from 4-4-2 to 3-4-3 at 16:30.

Known gaps in the current project:

- Analysis artifacts are primarily files/JSONL. There is no queryable database for OpenCV event history and event-linked agent decisions.
- Bedrock helps orchestrate and explain the existing verification flow. It does not yet classify a team's tactical posture as attacking, defensive, hybrid, or unclear using persisted event metrics.
- Existing recommendation text is not reliably checked and has no coach context such as match objective or available bench roles. Do not present an unsupported suggestion as fact.
- The app has a live-replay mode driven by stored trace timing, but the selected TeamTrack demo does not yet show its source match video synchronized with the tactical map across the full clip sequence. Uploaded videos are analysed offline, not as a live camera stream.
- The current static/demo view can show a completed alert before playback reaches its event. The revised flow needs a visible provisional event at the event point, followed by a verified coach alert only after enough evidence exists.
- A real live camera feed is a later product phase. The hackathon target is a clearly labelled recorded TeamTrack simulation.

## Flow before the new requirements

```text
sample data or uploaded clip
  -> OpenCV creates MatchState and a tactical timeline
  -> candidate formation changes
  -> deterministic verifier / Bedrock orchestration checks candidates
  -> evidence image and pending coach alert
  -> coach approves or rejects
```

The primary data contract is frozen at `MatchState` v1.0. Do not silently change it. The API can save analysis files through local or S3 storage, and alerts use append-only JSONL; this is file persistence, not the requested queryable event database. Default TeamTrack demo output is a precomputed six-minute sample.

## Target flow after the new requirements

1. The coach selects **Live analysis**. A setup panel asks which demo side is their team, the match objective (for example, chase a goal, protect a lead, or balanced), and optionally which substitute roles are available. It explains the camera conditions: elevated, fixed, whole pitch in view, and clearly different shirt colours.
2. For this hackathon, starting the flow plays **recorded TeamTrack footage as a live-style simulation**, labelled clearly as recorded footage. It does not claim to be a live camera feed.
3. The original top-view match video and OpenCV tactical map share one clock, including seeks across consecutive TeamTrack clips. Runtime analysis uses Gaffer's OpenCV output, never TeamTrack ground-truth annotations.
4. When the detector produces a formation-change candidate, store the candidate and its compact OpenCV metrics in a queryable event store. Preserve the estimated event/onset time separately from detection and verification times.
5. At the candidate's match time, show **“Possible formation change — checking”** (or equivalent) with the before/after formations. Do not say “analysis started” as if that were the event, and do not call it verified yet.
6. The Bedrock agent queries the stored event and relevant pre/post windows. It may request a targeted OpenCV re-analysis. Deterministic verification remains the authority on whether the formation change is confirmed, rejected, or uncertain.
7. Only after the required verification evidence is available, present the coach-facing alert with the verified formation change, evidence, and a separately labelled posture read: **attacking / defensive / hybrid / unclear**. A formation change alone does not prove intent. Use measured shape metrics and persistence; when they do not support a posture, return **unclear**. The top-view pipeline currently lacks usable ball, possession, and pressing data.
8. Offer an optional **conditional role-level suggestion**, not a named-player instruction. Tie it to the coach's stated objective and available roles, for example: “If you are chasing a goal and an attacking substitute is available, consider replacing a defender with an attacker.” Cite the event evidence and explain the condition. If necessary context is missing, ask for it or withhold the suggestion.
9. The coach approves or rejects the alert/suggestion; save the decision and note against the event for later review.

## Requirements that must remain true

- A formation change is first reported as a formation change. Never label the confirmed White 4-4-2 → 3-4-3 demo as “the opponent became defensive” unless supporting metrics justify that separate interpretation.
- Keep candidate, verified decision, Bedrock posture assessment, recommendation, and coach decision as distinct fields/states. Bedrock must not overwrite the deterministic verification result.
- Every tactical claim points to a timestamp, metric, evidence image, or trace record. “Unclear” is a valid outcome.
- Store OpenCV-derived outputs and agent results; do not use the TeamTrack annotations as runtime analysis input.
- Keep `MatchState` v1.0 compatible. Add a separately versioned event/agent record or explicit migration if the new workflow requires new data.
- The TeamTrack top and side clips with similar filenames are not simultaneous. The demo should use the top view only.
- Preserve current license, AWS-secret, and no-commit constraints in `CLAUDE.md`.
- No real camera ingest is part of the recorded-TeamTrack milestone.

## Scope boundary

This planning pass changed documentation only. It did not modify application behavior or start a new implementation phase. The actual-camera setup, ball/possession tracking, and player-named substitutions remain future work unless separately planned.

