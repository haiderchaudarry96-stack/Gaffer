"""Versioned, queryable persistence for OpenCV-produced tactical events.

This store is separate from the frozen MatchState/TacticalTimeline contracts and from the
artifact store. SQLite is used because the API has one worker process and already keeps local
working files; on EC2 the database file must live on a persistent EBS-backed path.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gaffer.config import repo_path
from gaffer.schema import EventStatus, EventType, Side

DATABASE_VERSION = 4
RECORD_VERSION = "1.0"
AgentStatus = Literal["not_run", "completed", "fallback"]
PostureStatus = Literal["not_requested", "pending", "completed", "unavailable", "failed"]
RecommendationStatus = Literal["not_requested", "pending", "ready", "withheld"]


class EventStoreError(RuntimeError):
    """The event database is unavailable, incompatible, or contains invalid data."""


class CoachDecisionRecord(BaseModel):
    """One append-only coach action associated with an event."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    alert_id: str
    decision: Literal["approved", "rejected"]
    decided_at_utc: str
    note: str | None = None


class RecommendationDecisionRecord(BaseModel):
    """Append-only coach response to one optional recommendation."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    recommendation_id: str
    decision: Literal["approved", "rejected"]
    decided_at_utc: str
    note: str | None = None


class EventRecordV1(BaseModel):
    """Persisted event schema v1; independent of contract MatchState/TacticalTimeline v1.0."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = RECORD_VERSION
    record_id: str
    analysis_id: str
    match_id: str
    event_id: str
    event_type: EventType
    team: Side
    team_name: str
    from_formation: str | None = None
    to_formation: str | None = None
    candidate_time_s: float = Field(ge=0)
    detection_time_s: float | None = Field(default=None, ge=0)
    status: EventStatus = "candidate"
    verification_time_utc: str | None = None
    verification: dict[str, Any] | None = None
    opencv_metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    agent_status: AgentStatus = "not_run"
    agent_completed_utc: str | None = None
    agent_result: dict[str, Any] | None = None
    posture_status: PostureStatus = "not_requested"
    posture_result: dict[str, Any] | None = None
    recommendation_status: RecommendationStatus = "not_requested"
    recommendation: dict[str, Any] | None = None
    coach_decisions: list[CoachDecisionRecord] = Field(default_factory=list)
    created_utc: str
    updated_utc: str


class EventRecordV1_1(EventRecordV1):
    """Event schema 1.1 adds a replay-time boundary for verifier evidence."""

    schema_version: Literal["1.1"] = "1.1"
    verification_match_time_s: float | None = Field(default=None, ge=0)


PersistedEventRecord = EventRecordV1 | EventRecordV1_1


def _verification_match_time(status: str, verification: dict[str, Any] | None,
                             metrics: dict[str, Any], candidate_time_s: float
                             ) -> float | None:
    """Return when stored verifier evidence is fully available on the match clock.

    This is a playback reveal boundary, not the UTC time at which the verifier ran. Only a
    completed verification whose re-analysis explicitly covers the required span can reveal.
    """
    if status not in {"confirmed", "rejected", "uncertain"} or verification is None:
        return None
    reanalysis = metrics.get("reanalysis")
    if not isinstance(reanalysis, dict):
        return None
    vs_event = reanalysis.get("vs_event")
    window = reanalysis.get("window")
    if not isinstance(vs_event, dict) or vs_event.get("covers_required_span") is not True:
        return None
    if not isinstance(window, list) or len(window) != 2:
        return None
    try:
        end_s = float(window[1])
    except (TypeError, ValueError):
        return None
    if end_s < candidate_time_s or end_s < 0:
        return None
    return end_s


def utc_now() -> str:
    """Return a stable UTC timestamp for persisted records."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stable_record_id(analysis_id: str, event_id: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"gaffer:event:{analysis_id}:{event_id}").hex


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                      default=str)


def _stats_for(segment: Any | None, team: Side) -> dict[str, Any] | None:
    if segment is None:
        return None
    stats = getattr(segment, team)
    centroid = stats.centroid
    return {
        "start_s": float(segment.start_s),
        "end_s": float(segment.end_s),
        "formation": stats.formation,
        "confidence": float(stats.confidence),
        "defensive_line_m": stats.defensive_line_m,
        "compactness_m": stats.compactness_m,
        "width_m": stats.width_m,
        "centroid": None if centroid is None else centroid.model_dump(mode="json"),
        "pressing_index": stats.pressing_index,
    }


def _event_metrics(ctx: Any, event: Any, candidate: Any | None,
                   outcome: Any | None) -> dict[str, Any]:
    """Build a compact, OpenCV/tactics-only evidence snapshot for one candidate."""
    t = float(event.t)
    segments = ctx.result.timeline.segments
    before_rows = [s for s in segments if float(s.end_s) <= t + 1e-6]
    after_rows = [s for s in segments if float(s.start_s) >= t - 1e-6]
    before = max(before_rows, key=lambda s: float(s.end_s), default=None)
    after = min(after_rows, key=lambda s: float(s.start_s), default=None)

    quality: dict[str, Any] = {
        "uncertain_fraction": float(ctx.result.timeline.quality.uncertain_fraction),
        "mean_players_visible": float(ctx.result.timeline.quality.mean_players_visible),
        "warnings": list(ctx.result.timeline.quality.warnings),
    }
    coverage = None
    reanalysis = None
    if candidate is not None:
        coverage = ctx.evidence(candidate).summary()
    if outcome is not None:
        q = outcome.quality or {}
        quality["verification_window"] = {
            key: q.get(key) for key in (
                "homography_ok_share", "line_error_m_median", "camera_shift_px_per_s_max",
                "zoom_change_max", "camera_cut", "coverage", "problems", "opencv_ms",
            ) if key in q
        }
        r = outcome.reanalysis or {}
        reanalysis = ({key: r.get(key) for key in (
            "window", "sample_fps", "frames", "processing_s", "cache", "coverage",
        ) if key in r} | {"vs_event": r.get("vs_event", {})}) if r else None

    return {
        "candidate_confidence": float(event.confidence),
        "candidate_evidence": event.evidence,
        "before": _stats_for(before, event.team),
        "after": _stats_for(after, event.team),
        "coverage": coverage,
        "quality": quality,
        "reanalysis": reanalysis,
    }


def build_video_event_records(analysis_id: str, ctx: Any, outcomes: list[Any],
                              *, now: str | None = None,
                              completion_times_utc: dict[str, str] | None = None
                              ) -> list[EventRecordV1]:
    """Project completed OpenCV video analysis into event records; never accepts GT sources."""
    if ctx.match.source != "video":
        return []

    created = now or utc_now()
    events = ctx.result.timeline.events
    internal = sorted([*ctx.result.changes, *ctx.result.line_drops],
                      key=lambda change: (change.t, change.team))
    if len(events) != len(internal):
        raise EventStoreError("timeline events do not align with internal OpenCV event timings")
    detected_at = {event.id: float(change.detected_at_s)
                   for event, change in zip(events, internal, strict=True)}
    candidates = {candidate.id: candidate for candidate in ctx.candidates}
    outcome_by_id = {outcome.event_id: outcome for outcome in outcomes}
    completion_times_utc = completion_times_utc or {}
    names = ctx.result.timeline.teams
    records: list[EventRecordV1] = []

    for event in events:
        candidate = candidates.get(event.id)
        outcome = outcome_by_id.get(event.id)
        status = outcome.decision if outcome is not None else event.status
        if status not in ("candidate", "confirmed", "rejected", "uncertain"):
            raise EventStoreError(f"unsupported event status {status!r} for {event.id}")
        verification = None
        agent_result = None
        verification_time = None
        agent_completed = None
        agent_status: AgentStatus = "not_run"
        if outcome is not None:
            verification_time = completion_times_utc.get(event.id, created)
            agent_completed = verification_time
            verification = {
                "decided_by": outcome.decided_by,
                "decision": outcome.decision,
                "verdict": outcome.verdict,
                "reason": outcome.reason,
                "tool_calls": list(outcome.tool_calls),
                "trace_id": outcome.trace_id,
                "fallback": outcome.fallback,
            }
            agent_result = {
                "decided_by": outcome.decided_by,
                "llm_calls": int(outcome.llm_calls),
                "tokens_in": int(outcome.tokens_in),
                "tokens_out": int(outcome.tokens_out),
                "cost_usd": round(float(outcome.cost_usd), 6),
                "explanation": outcome.explanation,
                "explanation_source": outcome.explanation_source,
            }
            agent_status = "fallback" if outcome.fallback else "completed"

        evidence_refs = ([f"/api/analyses/{analysis_id}/evidence/{event.id}.jpg"]
                         if outcome is not None and outcome.evidence_image else [])
        trace_refs = ([f"{analysis_id}/trace.jsonl#{outcome.trace_id}"]
                      if outcome is not None and outcome.trace_id else [])
        metrics = _event_metrics(ctx, event, candidate, outcome)
        records.append(EventRecordV1_1(
            record_id=_stable_record_id(analysis_id, event.id),
            analysis_id=analysis_id,
            match_id=ctx.match.match_id,
            event_id=event.id,
            event_type=event.type,
            team=event.team,
            team_name=names[event.team],
            from_formation=event.from_,
            to_formation=event.to,
            candidate_time_s=float(event.t),
            detection_time_s=detected_at[event.id],
            status=status,
            verification_time_utc=verification_time,
            verification=verification,
            opencv_metrics=metrics,
            verification_match_time_s=_verification_match_time(
                status, verification, metrics, float(event.t)),
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            agent_status=agent_status,
            agent_completed_utc=agent_completed,
            agent_result=agent_result,
            posture_status="not_requested",
            recommendation_status="not_requested",
            created_utc=created,
            updated_utc=created,
        ))
    return records


class EventStore:
    """SQLite event repository with explicit schema migrations and append-only decisions."""

    def __init__(self, path: str | Path) -> None:
        self.path = repo_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
        finally:
            conn.close()

    def _migrate(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )""")
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if version > DATABASE_VERSION:
                    raise EventStoreError(
                        f"event database schema {version} is newer than supported "
                        f"schema {DATABASE_VERSION}")
                if version < 1:
                    conn.execute("""CREATE TABLE event_records (
                        record_id TEXT PRIMARY KEY,
                        schema_version TEXT NOT NULL,
                        analysis_id TEXT NOT NULL,
                        match_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        team TEXT NOT NULL CHECK(team IN ('home', 'away')),
                        candidate_time_s REAL NOT NULL CHECK(candidate_time_s >= 0),
                        status TEXT NOT NULL CHECK(status IN
                            ('candidate', 'confirmed', 'rejected', 'uncertain')),
                        updated_utc TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        UNIQUE(analysis_id, event_id)
                    )""")
                    conn.execute("""CREATE TABLE coach_decisions (
                        decision_id TEXT PRIMARY KEY,
                        record_id TEXT NOT NULL REFERENCES event_records(record_id),
                        alert_id TEXT NOT NULL UNIQUE,
                        decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                        decided_at_utc TEXT NOT NULL,
                        note TEXT
                    )""")
                    conn.execute("CREATE INDEX idx_event_match_time ON "
                                 "event_records(match_id, candidate_time_s, record_id)")
                    conn.execute("CREATE INDEX idx_event_match_team_status_time ON "
                                 "event_records(match_id, team, status, candidate_time_s)")
                    conn.execute("CREATE INDEX idx_event_analysis_time ON "
                                 "event_records(analysis_id, candidate_time_s)")
                    conn.execute("""CREATE TRIGGER coach_decisions_no_update
                        BEFORE UPDATE ON coach_decisions BEGIN
                            SELECT RAISE(ABORT, 'coach decision history is append-only');
                        END""")
                    conn.execute("""CREATE TRIGGER coach_decisions_no_delete
                        BEFORE DELETE ON coach_decisions BEGIN
                            SELECT RAISE(ABORT, 'coach decision history is append-only');
                        END""")
                    conn.execute("INSERT INTO schema_migrations(version, applied_at_utc) "
                                 "VALUES (?, ?)", (1, utc_now()))
                    conn.execute("PRAGMA user_version=1")
                    version = 1
                if version < 2:
                    conn.execute("ALTER TABLE event_records ADD COLUMN "
                                 "verification_match_time_s REAL")
                    rows = conn.execute("SELECT record_id, payload_json FROM event_records")
                    for row in rows:
                        payload = json.loads(row["payload_json"])
                        match_time = _verification_match_time(
                            str(payload.get("status", "candidate")),
                            payload.get("verification"),
                            payload.get("opencv_metrics", {}),
                            float(payload.get("candidate_time_s", 0.0)))
                        payload["schema_version"] = "1.1"
                        payload["verification_match_time_s"] = match_time
                        conn.execute("""UPDATE event_records SET schema_version=?,
                            verification_match_time_s=?, payload_json=? WHERE record_id=?""",
                            ("1.1", match_time, _json(payload), row["record_id"]))
                    conn.execute("INSERT INTO schema_migrations(version, applied_at_utc) "
                                 "VALUES (?, ?)", (2, utc_now()))
                    conn.execute("PRAGMA user_version=2")
                    version = 2
                if version < 3:
                    conn.execute("""CREATE TABLE posture_attempts (
                        attempt_id TEXT PRIMARY KEY,
                        record_id TEXT NOT NULL REFERENCES event_records(record_id),
                        match_id TEXT NOT NULL,
                        model_id TEXT NOT NULL,
                        reserved_calls INTEGER NOT NULL CHECK(reserved_calls >= 0),
                        actual_calls INTEGER,
                        reserved_cost_usd REAL NOT NULL CHECK(reserved_cost_usd >= 0),
                        actual_cost_usd REAL,
                        status TEXT NOT NULL CHECK(status IN ('reserved', 'completed', 'failed')),
                        started_utc TEXT NOT NULL,
                        finished_utc TEXT
                    )""")
                    conn.execute("CREATE INDEX idx_posture_match_budget ON "
                                 "posture_attempts(match_id, status)")
                    conn.execute("CREATE INDEX idx_posture_event_attempts ON "
                                 "posture_attempts(record_id, started_utc)")
                    conn.execute("INSERT INTO schema_migrations(version, applied_at_utc) "
                                 "VALUES (?, ?)", (3, utc_now()))
                    conn.execute("PRAGMA user_version=3")
                    version = 3
                if version < 4:
                    conn.execute("""CREATE TABLE recommendations (
                        recommendation_id TEXT PRIMARY KEY,
                        record_id TEXT NOT NULL REFERENCES event_records(record_id),
                        request_key TEXT NOT NULL,
                        recommendation_json TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        UNIQUE(record_id, request_key)
                    )""")
                    conn.execute("""CREATE TABLE recommendation_decisions (
                        decision_id TEXT PRIMARY KEY,
                        record_id TEXT NOT NULL REFERENCES event_records(record_id),
                        recommendation_id TEXT NOT NULL UNIQUE REFERENCES
                            recommendations(recommendation_id),
                        decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                        decided_at_utc TEXT NOT NULL,
                        note TEXT
                    )""")
                    for table in ("recommendations", "recommendation_decisions"):
                        conn.execute(f"""CREATE TRIGGER {table}_no_update
                            BEFORE UPDATE ON {table} BEGIN
                                SELECT RAISE(ABORT, '{table} is append-only');
                            END""")
                        conn.execute(f"""CREATE TRIGGER {table}_no_delete
                            BEFORE DELETE ON {table} BEGIN
                                SELECT RAISE(ABORT, '{table} is append-only');
                            END""")
                    conn.execute("CREATE INDEX idx_recommendation_record ON "
                                 "recommendations(record_id, created_at_utc)")
                    conn.execute("INSERT INTO schema_migrations(version, applied_at_utc) "
                                 "VALUES (?, ?)", (4, utc_now()))
                    conn.execute("PRAGMA user_version=4")
                conn.commit()
        except EventStoreError:
            raise
        except sqlite3.Error as exc:
            raise EventStoreError(f"could not initialize event database: {exc}") from exc

    def upsert_analysis(self, records: list[PersistedEventRecord]) -> int:
        """Idempotently insert/update every event from one completed video analysis."""
        if not records:
            return 0
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                for record in records:
                    if record.schema_version not in (RECORD_VERSION, "1.1"):
                        raise EventStoreError(
                            f"unsupported event record version {record.schema_version!r}")
                    payload_data = record.model_copy(update={"coach_decisions": []}).model_dump(
                        mode="json")
                    existing = conn.execute("SELECT payload_json FROM event_records "
                                             "WHERE analysis_id=? AND event_id=?",
                                             (record.analysis_id, record.event_id)).fetchone()
                    if existing is not None:
                        old = json.loads(existing["payload_json"])
                        # Re-running the OpenCV worker may refresh verifier data, but it must not
                        # erase an already completed/failed posture lifecycle or its trace refs.
                        if old.get("posture_status") != "not_requested":
                            payload_data["posture_status"] = old.get("posture_status")
                            payload_data["posture_result"] = old.get("posture_result")
                        if old.get("recommendation_status") != "not_requested":
                            payload_data["recommendation_status"] = old.get(
                                "recommendation_status")
                            payload_data["recommendation"] = old.get("recommendation")
                        payload_data["trace_refs"] = list(dict.fromkeys(
                            [*payload_data.get("trace_refs", []), *old.get("trace_refs", [])]))
                    payload = _json(payload_data)
                    conn.execute("""INSERT INTO event_records (
                        record_id, schema_version, analysis_id, match_id, event_id, event_type,
                        team, candidate_time_s, status, updated_utc, payload_json
                        , verification_match_time_s
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(analysis_id, event_id) DO UPDATE SET
                        schema_version=excluded.schema_version,
                        match_id=excluded.match_id,
                        event_type=excluded.event_type,
                        team=excluded.team,
                        candidate_time_s=excluded.candidate_time_s,
                        status=excluded.status,
                        verification_match_time_s=excluded.verification_match_time_s,
                        updated_utc=excluded.updated_utc,
                        payload_json=excluded.payload_json""",
                        (record.record_id, record.schema_version, record.analysis_id,
                         record.match_id, record.event_id, record.event_type, record.team,
                         record.candidate_time_s, record.status, record.updated_utc, payload,
                         getattr(record, "verification_match_time_s", None)))
                conn.commit()
        except EventStoreError:
            raise
        except sqlite3.Error as exc:
            raise EventStoreError(f"could not persist event records: {exc}") from exc
        return len(records)

    def get_by_event(self, analysis_id: str, event_id: str) -> PersistedEventRecord | None:
        """Fetch one event using stable source identifiers for bounded operator workflows."""
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM event_records WHERE analysis_id=? AND event_id=?",
                                   (analysis_id, event_id)).fetchone()
                return self._hydrate(conn, [row])[0] if row else None
        except (sqlite3.Error, ValueError) as exc:
            raise EventStoreError(f"could not read event record: {exc}") from exc

    @staticmethod
    def _append_trace_ref(payload: dict[str, Any], trace_ref: str) -> None:
        refs = list(payload.get("trace_refs", []))
        if trace_ref not in refs:
            refs.append(trace_ref)
        payload["trace_refs"] = refs

    def get_by_match_event(self, match_id: str, event_id: str,
                           analysis_id: str | None = None) -> PersistedEventRecord | None:
        """Resolve a stable event id for an operator command without opening public writes."""
        clauses = ["match_id=?", "event_id=?"]
        args: list[Any] = [match_id, event_id]
        if analysis_id is not None:
            clauses.append("analysis_id=?")
            args.append(analysis_id)
        try:
            with self._connect() as conn:
                rows = conn.execute(f"SELECT * FROM event_records WHERE {' AND '.join(clauses)}",
                                    args).fetchall()
                if len(rows) > 1:
                    raise EventStoreError("event id is ambiguous; specify analysis_id")
                return self._hydrate(conn, rows)[0] if rows else None
        except EventStoreError:
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise EventStoreError(f"could not resolve event record: {exc}") from exc

    def reserve_posture_attempt(self, *, record_id: str, attempt_id: str, model_id: str,
                                trace_ref: str,
                                reserved_calls: int, reserved_cost_usd: float,
                                max_calls_per_event: int, max_calls_per_match: int,
                                max_cost_usd_per_event: float, max_cost_usd_per_match: float,
                                stale_pending_after_s: int = 900,
                                retry: bool = False, started_utc: str | None = None
                                ) -> tuple[bool, str]:
        """Atomically claim one confirmed event and reserve its bounded Bedrock budget."""
        now = started_utc or utc_now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM event_records WHERE record_id=?",
                                   (record_id,)).fetchone()
                if row is None:
                    conn.rollback()
                    return False, "event_not_found"
                payload = json.loads(row["payload_json"])
                if payload.get("status") != "confirmed":
                    conn.rollback()
                    return False, "event_not_confirmed"
                state = payload.get("posture_status", "not_requested")
                if state == "pending":
                    if not retry:
                        conn.rollback()
                        return False, "already_pending"
                    pending = conn.execute("""SELECT attempt_id, started_utc
                        FROM posture_attempts WHERE record_id=? AND status='reserved'""",
                                           (record_id,)).fetchall()
                    retry_before = (datetime.fromisoformat(now.replace("Z", "+00:00"))
                                    - timedelta(seconds=max(1, stale_pending_after_s)))
                    stale = [attempt for attempt in pending
                             if datetime.fromisoformat(
                                 attempt["started_utc"].replace("Z", "+00:00")) <= retry_before]
                    if not stale:
                        conn.rollback()
                        return False, "already_pending"
                    # An explicit retry may reclaim a crashed posture attempt after the
                    # configured grace period. The old worker cannot save over the new attempt.
                    for attempt in stale:
                        conn.execute("""UPDATE posture_attempts SET status='failed',
                            actual_calls=0, actual_cost_usd=0, finished_utc=?
                            WHERE attempt_id=?""", (now, attempt["attempt_id"]))
                    payload["posture_status"] = "failed"
                if state != "not_requested" and not retry:
                    conn.rollback()
                    return False, "already_processed"

                event_usage = conn.execute("""SELECT
                    COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_calls
                                      ELSE COALESCE(actual_calls, reserved_calls) END), 0) calls,
                    COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_cost_usd
                                      ELSE COALESCE(actual_cost_usd, reserved_cost_usd)
                                      END), 0) cost
                    FROM posture_attempts WHERE record_id=?""", (record_id,)).fetchone()
                match_usage = conn.execute("""SELECT
                    COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_calls
                                      ELSE COALESCE(actual_calls, reserved_calls) END), 0) calls,
                    COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_cost_usd
                                      ELSE COALESCE(actual_cost_usd, reserved_cost_usd)
                                      END), 0) cost
                    FROM posture_attempts WHERE match_id=?""", (row["match_id"],)).fetchone()
                if int(event_usage["calls"]) + reserved_calls > max_calls_per_event:
                    conn.rollback()
                    return False, "event_call_cap"
                if int(match_usage["calls"]) + reserved_calls > max_calls_per_match:
                    conn.rollback()
                    return False, "match_call_cap"
                if float(event_usage["cost"]) + reserved_cost_usd > max_cost_usd_per_event:
                    conn.rollback()
                    return False, "event_cost_cap"
                if float(match_usage["cost"]) + reserved_cost_usd > max_cost_usd_per_match:
                    conn.rollback()
                    return False, "match_cost_cap"

                conn.execute("""INSERT INTO posture_attempts
                    (attempt_id, record_id, match_id, model_id, reserved_calls,
                     reserved_cost_usd, status, started_utc)
                    VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?)""",
                    (attempt_id, record_id, row["match_id"], model_id, reserved_calls,
                     reserved_cost_usd, now))
                payload["posture_status"] = "pending"
                payload["posture_result"] = {
                    "schema_version": "1.0", "posture": "unclear",
                    "source": "deterministic_fallback", "analysis_time_utc": now,
                    "model_id": model_id, "trace_id": attempt_id,
                    "explanation": "Tactical posture analysis is pending.",
                    "evidence_strength": 0.0, "citations": [],
                    "limitations": ["The Bedrock assessment has not finished."],
                }
                self._append_trace_ref(payload, trace_ref)
                payload["updated_utc"] = now
                conn.execute("UPDATE event_records SET updated_utc=?, payload_json=? "
                             "WHERE record_id=?", (now, _json(payload), record_id))
                conn.commit()
                return True, "reserved"
        except EventStoreError:
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise EventStoreError(f"could not reserve posture analysis: {exc}") from exc

    def save_posture_result(self, *, record_id: str, status: PostureStatus,
                            result: dict[str, Any], trace_ref: str,
                            attempt_id: str | None = None, actual_calls: int | None = None,
                            actual_cost_usd: float | None = None,
                            finished_utc: str | None = None) -> bool:
        """Persist posture separately from verification and coach decisions."""
        if status not in {"completed", "unavailable", "failed"}:
            raise ValueError("posture result status must be completed, unavailable or failed")
        now = finished_utc or utc_now()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT payload_json FROM event_records WHERE record_id=?",
                                   (record_id,)).fetchone()
                if row is None:
                    conn.rollback()
                    return False
                payload = json.loads(row["payload_json"])
                if payload.get("status") != "confirmed":
                    conn.rollback()
                    return False
                if attempt_id is not None:
                    current_result = payload.get("posture_result")
                    if (payload.get("posture_status") != "pending"
                            or not isinstance(current_result, dict)
                            or current_result.get("trace_id") != attempt_id):
                        conn.rollback()
                        return False
                    attempt = conn.execute("SELECT status FROM posture_attempts "
                                           "WHERE attempt_id=? AND record_id=?",
                                           (attempt_id, record_id)).fetchone()
                    if attempt is None:
                        conn.rollback()
                        return False
                    conn.execute("""UPDATE posture_attempts SET status=?, actual_calls=?,
                        actual_cost_usd=?, finished_utc=? WHERE attempt_id=?""",
                        ("completed" if status == "completed" else "failed",
                         actual_calls, actual_cost_usd, now, attempt_id))
                payload["posture_status"] = status
                payload["posture_result"] = result
                self._append_trace_ref(payload, trace_ref)
                payload["updated_utc"] = now
                conn.execute("UPDATE event_records SET updated_utc=?, payload_json=? "
                             "WHERE record_id=?", (now, _json(payload), record_id))
                conn.commit()
                return True
        except (sqlite3.Error, ValueError) as exc:
            raise EventStoreError(f"could not persist posture result: {exc}") from exc

    def save_recommendation(self, *, record_id: str,
                            recommendation: dict[str, Any]) -> dict[str, Any]:
        """Append one recommendation per event/context and set it as the current result."""
        now = str(recommendation.get("created_at_utc") or utc_now())
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT payload_json FROM event_records WHERE record_id=?",
                                   (record_id,)).fetchone()
                if row is None:
                    conn.rollback()
                    raise EventStoreError("No persisted event exists for this recommendation.")
                payload = json.loads(row["payload_json"])
                if payload.get("status") != "confirmed":
                    conn.rollback()
                    raise EventStoreError("Recommendations require a confirmed formation event.")
                recommendation_id = str(recommendation["recommendation_id"])
                request_key = str(recommendation["request_key"])
                if recommendation.get("status") not in {"ready", "withheld"}:
                    conn.rollback()
                    raise EventStoreError("The recommendation status is invalid.")
                if recommendation.get("status") == "ready" and (
                        payload.get("posture_status") != "completed"
                        or not payload.get("posture_result")):
                    conn.rollback()
                    raise EventStoreError("Ready advice requires a completed posture assessment.")
                current = payload.get("recommendation")
                if (isinstance(current, dict)
                        and current.get("recommendation_id") != recommendation_id):
                    previous_id = str(current.get("recommendation_id", ""))
                    previous_decision = conn.execute(
                        "SELECT decision_id FROM recommendation_decisions "
                        "WHERE recommendation_id=?", (previous_id,)).fetchone()
                    if previous_decision is not None:
                        conn.rollback()
                        raise EventStoreError(
                            "Coach context cannot replace advice that already has a saved "
                            "response.")
                conn.execute("""INSERT OR IGNORE INTO recommendations
                    (recommendation_id, record_id, request_key, recommendation_json,
                     created_at_utc) VALUES (?, ?, ?, ?, ?)""",
                    (recommendation_id, record_id, request_key, _json(recommendation), now))
                stored = conn.execute("SELECT recommendation_json FROM recommendations "
                                      "WHERE record_id=? AND request_key=?",
                                      (record_id, request_key)).fetchone()
                if stored is None:
                    raise EventStoreError("Could not persist the recommendation snapshot.")
                saved = json.loads(stored["recommendation_json"])
                payload["recommendation_status"] = saved["status"]
                payload["recommendation"] = saved
                payload["updated_utc"] = utc_now()
                conn.execute("UPDATE event_records SET updated_utc=?, payload_json=? "
                             "WHERE record_id=?",
                             (payload["updated_utc"], _json(payload), record_id))
                conn.commit()
                return saved
        except EventStoreError:
            raise
        except (sqlite3.Error, KeyError, ValueError) as exc:
            raise EventStoreError(f"could not save recommendation: {exc}") from exc

    @staticmethod
    def _recommendation_decision_id(recommendation_id: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL,
                          f"gaffer:recommendation-decision:{recommendation_id}").hex

    def append_recommendation_decision(self, *, record_id: str, recommendation_id: str,
                                       decision: Literal["approved", "rejected"],
                                       note: str | None = None,
                                       decided_at_utc: str | None = None
                                       ) -> RecommendationDecisionRecord:
        """Persist one append-only response to one suggestion, separate from alert review."""
        now = decided_at_utc or utc_now()
        decision_id = self._recommendation_decision_id(recommendation_id)
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                rec = conn.execute("SELECT record_id FROM recommendations "
                                   "WHERE recommendation_id=?", (recommendation_id,)).fetchone()
                if rec is None or rec["record_id"] != record_id:
                    conn.rollback()
                    raise EventStoreError("That recommendation does not belong to this event.")
                existing = conn.execute("SELECT * FROM recommendation_decisions "
                                        "WHERE recommendation_id=?",
                                        (recommendation_id,)).fetchone()
                if existing is not None:
                    if existing["decision"] != decision or existing["note"] != note:
                        conn.rollback()
                        raise EventStoreError(
                            "A different coach response is already saved for this recommendation.")
                    conn.commit()
                    return RecommendationDecisionRecord(
                        decision_id=existing["decision_id"],
                        recommendation_id=existing["recommendation_id"],
                        decision=existing["decision"], decided_at_utc=existing["decided_at_utc"],
                        note=existing["note"])
                conn.execute("""INSERT INTO recommendation_decisions
                    (decision_id, record_id, recommendation_id, decision, decided_at_utc, note)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (decision_id, record_id, recommendation_id, decision, now, note))
                conn.commit()
                return RecommendationDecisionRecord(
                    decision_id=decision_id, recommendation_id=recommendation_id,
                    decision=decision, decided_at_utc=now, note=note)
        except EventStoreError:
            raise
        except sqlite3.Error as exc:
            raise EventStoreError(f"could not save recommendation response: {exc}") from exc

    def _recommendation_decisions_for(self, conn: sqlite3.Connection,
                                      recommendation_ids: list[str]
                                      ) -> dict[str, RecommendationDecisionRecord]:
        if not recommendation_ids:
            return {}
        placeholders = ",".join("?" for _ in recommendation_ids)
        rows = conn.execute(f"SELECT * FROM recommendation_decisions WHERE recommendation_id "
                            f"IN ({placeholders})", recommendation_ids).fetchall()
        return {row["recommendation_id"]: RecommendationDecisionRecord(
            decision_id=row["decision_id"], recommendation_id=row["recommendation_id"],
            decision=row["decision"], decided_at_utc=row["decided_at_utc"], note=row["note"])
                for row in rows}

    @staticmethod
    def _decision_id(alert_id: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"gaffer:coach-decision:{alert_id}").hex

    def append_coach_decision(self, *, match_id: str, event_id: str, alert_id: str,
                              decision: Literal["approved", "rejected"],
                              decided_at_utc: str, note: str | None = None) -> bool:
        """Append a decision for a stored event; return false for legacy alerts without a row."""
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                event = conn.execute("""SELECT record_id FROM event_records
                    WHERE match_id=? AND event_id=?""", (match_id, event_id)).fetchone()
                if event is None:
                    conn.rollback()
                    return False
                decision_id = self._decision_id(alert_id)
                existing = conn.execute("SELECT decision, note FROM coach_decisions "
                                         "WHERE alert_id=?", (alert_id,)).fetchone()
                if existing is not None:
                    if existing["decision"] != decision or existing["note"] != note:
                        raise EventStoreError(
                            f"alert {alert_id!r} already has a different recorded decision")
                    conn.commit()
                    return True
                conn.execute("""INSERT INTO coach_decisions
                    (decision_id, record_id, alert_id, decision, decided_at_utc, note)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (decision_id, event["record_id"], alert_id, decision, decided_at_utc, note))
                row = conn.execute("SELECT payload_json FROM event_records "
                                   "WHERE record_id=?", (event["record_id"],)).fetchone()
                payload = json.loads(row["payload_json"])
                payload["updated_utc"] = utc_now()
                conn.execute("UPDATE event_records SET updated_utc=?, payload_json=? "
                             "WHERE record_id=?",
                             (payload["updated_utc"], _json(payload), event["record_id"]))
                conn.commit()
                return True
        except EventStoreError:
            raise
        except sqlite3.Error as exc:
            raise EventStoreError(f"could not persist coach decision: {exc}") from exc

    def _decisions_for(self, conn: sqlite3.Connection, record_ids: list[str]
                       ) -> dict[str, list[CoachDecisionRecord]]:
        if not record_ids:
            return {}
        placeholders = ",".join("?" for _ in record_ids)
        rows = conn.execute(f"""SELECT record_id, decision_id, alert_id, decision,
            decided_at_utc, note FROM coach_decisions WHERE record_id IN ({placeholders})
            ORDER BY decided_at_utc, decision_id""", record_ids).fetchall()
        out: dict[str, list[CoachDecisionRecord]] = {record_id: [] for record_id in record_ids}
        for row in rows:
            out[row["record_id"]].append(CoachDecisionRecord(
                decision_id=row["decision_id"], alert_id=row["alert_id"],
                decision=row["decision"], decided_at_utc=row["decided_at_utc"],
                note=row["note"]))
        return out

    def _hydrate(self, conn: sqlite3.Connection, rows: list[sqlite3.Row]
                 ) -> list[PersistedEventRecord]:
        decisions = self._decisions_for(conn, [row["record_id"] for row in rows])
        out: list[PersistedEventRecord] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            recommendation = payload.get("recommendation")
            if isinstance(recommendation, dict):
                recommendation_id = str(recommendation.get("recommendation_id", ""))
                response = self._recommendation_decisions_for(
                    conn, [recommendation_id]).get(recommendation_id)
                if response is not None:
                    payload["recommendation"] = {
                        **recommendation,
                        "coach_response": response.model_dump(mode="json"),
                    }
            record_type = (EventRecordV1_1 if payload.get("schema_version") == "1.1"
                           else EventRecordV1)
            record = record_type.model_validate(payload).model_copy(
                update={"coach_decisions": decisions[row["record_id"]]})
            out.append(record)
        return out

    def get(self, record_id: str) -> PersistedEventRecord | None:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM event_records WHERE record_id=?",
                                   (record_id,)).fetchone()
                return self._hydrate(conn, [row])[0] if row else None
        except EventStoreError:
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise EventStoreError(f"could not read event record: {exc}") from exc

    def list(self, *, match_id: str, analysis_id: str | None = None,
             team: Side | None = None, status: EventStatus | None = None,
             start_s: float | None = None, end_s: float | None = None,
             limit: int = 100, offset: int = 0
             ) -> tuple[list[PersistedEventRecord], int]:
        """List one match's events in match-clock order, with indexed filters and pagination."""
        if start_s is not None and end_s is not None and end_s < start_s:
            raise ValueError("end_s must be greater than or equal to start_s")
        clauses = ["match_id=?"]
        args: list[Any] = [match_id]
        for column, value in (("analysis_id", analysis_id), ("team", team),
                              ("status", status)):
            if value is not None:
                clauses.append(f"{column}=?")
                args.append(value)
        if start_s is not None:
            clauses.append("candidate_time_s>=?")
            args.append(start_s)
        if end_s is not None:
            clauses.append("candidate_time_s<=?")
            args.append(end_s)
        where = " AND ".join(clauses)
        try:
            with self._connect() as conn:
                total = int(conn.execute(f"SELECT COUNT(*) FROM event_records WHERE {where}",
                                         args).fetchone()[0])
                rows = conn.execute(f"""SELECT * FROM event_records WHERE {where}
                    ORDER BY candidate_time_s, record_id LIMIT ? OFFSET ?""",
                    [*args, limit, offset]).fetchall()
                return self._hydrate(conn, rows), total
        except sqlite3.Error as exc:
            raise EventStoreError(f"could not list event records: {exc}") from exc


def make_event_store(cfg: dict[str, Any]) -> EventStore:
    """Create the configured SQLite store; the file must be on persistent local storage."""
    settings = cfg["api"].get("event_store", {})
    return EventStore(settings.get("path", "outputs/api/events.sqlite3"))


def seed_demo_events(store: EventStore, cfg: dict[str, Any]) -> int:
    """Import the tracked demo-event seed (`api.teamtrack_replay.seed_file`) once, only when the
    database has no row for the replay match. Every seeded record must belong to the configured
    real demo analysis (`seed_analysis_id`), so a test fixture can never be shipped this way."""
    replay = cfg["api"].get("teamtrack_replay", {})
    seed, match_id = replay.get("seed_file"), replay.get("match_id")
    if not seed or not match_id or not repo_path(seed).is_file():
        return 0
    if store.list(match_id=match_id, limit=1)[1]:
        return 0
    data = json.loads(repo_path(seed).read_text(encoding="utf-8"))
    records = [EventRecordV1_1.model_validate(r) for r in data.get("records", [])]
    if any(r.match_id != match_id or r.analysis_id != replay.get("seed_analysis_id")
           for r in records):
        raise EventStoreError(f"{seed}: a record is outside the configured demo analysis")
    return store.upsert_analysis(records)


def persist_video_analysis(store: EventStore, analysis_id: str, ctx: Any,
                           outcomes: list[Any], *,
                           completion_times_utc: dict[str, str] | None = None) -> int:
    """Persist only OpenCV video-source outputs after the verifier has handled candidates."""
    if ctx.match.source != "video":
        return 0
    records = build_video_event_records(analysis_id, ctx, outcomes,
                                        completion_times_utc=completion_times_utc)
    return store.upsert_analysis(records)
