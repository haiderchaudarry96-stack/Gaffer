"""Versioned SQLite event persistence, migration and query behavior."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from gaffer.api.event_store import (
    EventRecordV1,
    EventStore,
    EventStoreError,
    build_video_event_records,
)


def record(record_id: str, event_id: str, t: float, *, status: str = "candidate",
           team: str = "home") -> EventRecordV1:
    return EventRecordV1(
        record_id=record_id,
        analysis_id="analysis_a1b2c3",
        match_id="up_analysis_a1b2c3",
        event_id=event_id,
        event_type="shape_change",
        team=team,
        team_name="White" if team == "home" else "Blue",
        from_formation="4-4-2",
        to_formation="3-4-3",
        candidate_time_s=t,
        detection_time_s=t + 10,
        status=status,
        created_utc="2026-10-19T10:00:00Z",
        updated_utc="2026-10-19T10:00:00Z",
    )


def test_sqlite_migration_and_versioned_idempotent_event_queries(tmp_path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    first = record("record_1", "evt_001", 150.0)
    second = record("record_2", "evt_002", 90.0, team="away")

    assert store.upsert_analysis([first, second]) == 2
    assert store.upsert_analysis([first, second]) == 2
    rows, total = store.list(match_id=first.match_id)
    assert total == 2
    assert [row.event_id for row in rows] == ["evt_002", "evt_001"]
    assert rows[0].schema_version == "1.0"
    assert store.list(match_id=first.match_id, team="home", status="candidate")[1] == 1
    ranged, ranged_total = store.list(match_id=first.match_id, start_s=120, end_s=180)
    assert ranged_total == 1 and ranged[0].event_id == "evt_001"
    assert store.get(first.record_id).candidate_time_s == 150.0
    assert store.get("missing") is None

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        migrations = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version").fetchall()
        assert migrations == [(1,), (2,), (3,), (4,)]


def test_coach_decisions_are_append_only_and_survive_reopen(tmp_path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    event = record("record_1", "evt_001", 150.0, status="confirmed")
    store.upsert_analysis([event])

    assert store.append_coach_decision(
        match_id=event.match_id,
        event_id=event.event_id,
        alert_id="alr_up_analysis_a1b2c3_evt_001",
        decision="approved",
        decided_at_utc="2026-10-19T10:03:00Z",
        note="useful evidence",
    )
    assert store.upsert_analysis([event]) == 1  # retry must keep the append-only history
    reopened = EventStore(path).get(event.record_id)
    assert reopened.coach_decisions[0].decision == "approved"
    assert reopened.coach_decisions[0].note == "useful evidence"
    assert reopened.coach_decisions[0].decided_at_utc == "2026-10-19T10:03:00Z"

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE coach_decisions SET decision='rejected'")
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM coach_decisions")


def test_schema_refuses_newer_database_and_invalid_time_range(tmp_path) -> None:
    path = tmp_path / "events.sqlite3"
    EventStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(EventStoreError, match="newer than supported"):
        EventStore(path)

    store = EventStore(tmp_path / "another.sqlite3")
    with pytest.raises(ValueError, match="end_s"):
        store.list(match_id="m", start_s=20, end_s=10)


def test_non_video_sources_never_become_runtime_events() -> None:
    context = SimpleNamespace(match=SimpleNamespace(source="annotation"))
    assert build_video_event_records("analysis", context, []) == []


def test_v1_database_migration_adds_truthful_optional_match_reveal_time(tmp_path) -> None:
    path = tmp_path / "old_events.sqlite3"
    event = record("record_1", "evt_001", 990.0, status="confirmed")
    event.verification = {"decision": "confirmed"}
    event.opencv_metrics = {"reanalysis": {
        "window": [960.0, 1020.0],
        "vs_event": {"covers_required_span": True},
    }}
    incomplete = record("record_2", "evt_002", 1080.0, status="confirmed")
    incomplete.verification = {"decision": "confirmed"}
    incomplete.opencv_metrics = {"reanalysis": {
        "window": [1050.0, 1110.0],
        "vs_event": {"covers_required_span": False},
    }}
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL);
            INSERT INTO schema_migrations VALUES (1, '2026-10-19T00:00:00Z');
            CREATE TABLE event_records(
                record_id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, analysis_id TEXT NOT NULL,
                match_id TEXT NOT NULL, event_id TEXT NOT NULL, event_type TEXT NOT NULL,
                team TEXT NOT NULL, candidate_time_s REAL NOT NULL, status TEXT NOT NULL,
                updated_utc TEXT NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(analysis_id, event_id));
            CREATE TABLE coach_decisions(
                decision_id TEXT PRIMARY KEY, record_id TEXT NOT NULL, alert_id TEXT NOT NULL,
                decision TEXT NOT NULL, decided_at_utc TEXT NOT NULL, note TEXT);
            PRAGMA user_version=1;
        """)
        for row in (event, incomplete):
            conn.execute("""INSERT INTO event_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (row.record_id, row.schema_version, row.analysis_id, row.match_id,
                          row.event_id, row.event_type, row.team, row.candidate_time_s,
                          row.status, row.updated_utc, row.model_dump_json()))

    migrated = EventStore(path)
    revealed = migrated.get("record_1")
    pending = migrated.get("record_2")
    assert revealed.schema_version == "1.1"
    assert revealed.verification_match_time_s == 1020.0
    assert pending.verification_match_time_s is None
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4


def test_posture_attempt_reservation_is_idempotent_bounded_and_survives_reopen(tmp_path) -> None:
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    event = record("record_1", "evt_001", 150.0, status="confirmed")
    event.verification = {"decision": "confirmed"}
    store.upsert_analysis([event])

    args = {"record_id": event.record_id, "model_id": "test-model", "trace_ref": "trace#one",
            "reserved_calls": 1, "reserved_cost_usd": 0.01,
            "max_calls_per_event": 2, "max_calls_per_match": 2,
            "max_cost_usd_per_event": 0.02, "max_cost_usd_per_match": 0.03}
    assert store.reserve_posture_attempt(attempt_id="attempt_1", **args) == (True, "reserved")
    assert store.reserve_posture_attempt(attempt_id="attempt_2", **args) == (
        False, "already_pending")
    assert store.get(event.record_id).posture_status == "pending"

    result = {"schema_version": "1.0", "posture": "unclear", "source": "bedrock",
              "analysis_time_utc": "2026-10-19T10:00:00Z", "model_id": "test-model",
              "trace_id": "attempt_1", "evidence_strength": 0.1,
              "explanation": "Not enough evidence.", "citations": [], "limitations": []}
    assert store.save_posture_result(record_id=event.record_id, status="completed",
                                     result=result, trace_ref="trace#one",
                                     attempt_id="attempt_1", actual_calls=1,
                                     actual_cost_usd=0.001)
    reopened = EventStore(path).get(event.record_id)
    assert reopened.posture_status == "completed"
    assert reopened.posture_result["posture"] == "unclear"
    assert reopened.verification["decision"] == "confirmed"
    assert "trace#one" in reopened.trace_refs

    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT status, actual_calls, actual_cost_usd FROM posture_attempts")
        assert row.fetchone() == ("completed", 1, 0.001)


def test_explicit_retry_can_reclaim_stale_pending_without_old_attempt_overwriting(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    event = record("record_retry", "evt_retry", 150.0, status="confirmed")
    event.verification = {"decision": "confirmed"}
    store.upsert_analysis([event])
    args = {"record_id": event.record_id, "model_id": "test-model",
            "trace_ref": "trace#old", "reserved_calls": 1,
            "reserved_cost_usd": 0.01, "max_calls_per_event": 4,
            "max_calls_per_match": 4, "max_cost_usd_per_event": 0.04,
            "max_cost_usd_per_match": 0.04}
    assert store.reserve_posture_attempt(
        attempt_id="attempt_old", started_utc="2020-01-01T00:00:00Z", **args
    ) == (True, "reserved")
    assert store.reserve_posture_attempt(
        attempt_id="attempt_live", retry=True, **args
    ) == (True, "reserved")

    old_result = {"schema_version": "1.0", "posture": "unclear",
                  "source": "deterministic_fallback", "trace_id": "attempt_old"}
    assert not store.save_posture_result(
        record_id=event.record_id, status="failed", result=old_result,
        trace_ref="trace#old", attempt_id="attempt_old", actual_calls=0,
        actual_cost_usd=0.0)
    new_result = {**old_result, "trace_id": "attempt_live", "source": "bedrock"}
    assert store.save_posture_result(
        record_id=event.record_id, status="completed", result=new_result,
        trace_ref="trace#live", attempt_id="attempt_live", actual_calls=1,
        actual_cost_usd=0.001)
    assert EventStore(store.path).get(event.record_id).posture_result["trace_id"] == "attempt_live"


def test_demo_seed_is_imported_once_into_an_empty_db_and_rejects_fixtures(tmp_path):
    """A fresh server (empty outputs/) gets the real 16:30 record and its stored posture."""
    import copy
    import json

    from gaffer.api.event_store import seed_demo_events
    from gaffer.config import load_config, repo_path

    cfg = copy.deepcopy(load_config())
    replay = cfg["api"]["teamtrack_replay"]
    store = EventStore(tmp_path / "events.sqlite3")
    assert seed_demo_events(store, cfg) == 1
    assert seed_demo_events(store, cfg) == 0  # never twice, never over existing rows
    events, total = store.list(match_id=replay["match_id"])
    assert total == 1 and events[0].event_id == "evt_003" and events[0].status == "confirmed"
    assert events[0].analysis_id == "teamtrack_demo_w900_1260"
    assert events[0].posture_status == "completed" and events[0].posture_result["citations"]
    assert events[0].recommendation_status == "not_requested" and not events[0].coach_decisions

    data = json.loads(repo_path(replay["seed_file"]).read_text(encoding="utf-8"))
    data["records"][0]["analysis_id"] = "analysis_n5_ui_fixture"
    bad = tmp_path / "bad_seed.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    replay["seed_file"] = str(bad)
    with pytest.raises(EventStoreError, match="outside the configured demo analysis"):
        seed_demo_events(EventStore(tmp_path / "other.sqlite3"), cfg)
