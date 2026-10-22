"""N4 role advice is deterministic, cited, persisted and independent of alert decisions."""

from __future__ import annotations

import sqlite3

import pytest

from gaffer.agent.recommendations import CoachContext, create_recommendation
from gaffer.api.event_store import EventRecordV1_1, EventStore, EventStoreError


def event(*, status: str = "confirmed", posture: str = "defensive",
          posture_status: str = "completed", source: str = "bedrock",
          shape: tuple[str, str] = ("4-4-2", "3-4-3")) -> EventRecordV1_1:
    return EventRecordV1_1(
        record_id="record_demo_evt_003", analysis_id="analysis_demo",
        match_id="teamtrack_top_w900_1260", event_id="evt_003", event_type="shape_change",
        team="home", team_name="White", from_formation=shape[0], to_formation=shape[1],
        candidate_time_s=990.0, detection_time_s=1025.0, status=status,
        verification_match_time_s=1085.0,
        verification={"decision": status, "reason": "OpenCV verifier result."},
        # the stored OpenCV metrics the posture citations below must match exactly
        opencv_metrics={
            "before": {"start_s": 840.0, "end_s": 990.0, "formation": "4-4-2",
                       "confidence": 0.8, "defensive_line_m": 48.0, "compactness_m": 30.0,
                       "width_m": 42.0},
            "after": {"start_s": 990.0, "end_s": 1085.0, "formation": "3-4-3",
                      "confidence": 0.8, "defensive_line_m": 42.0, "compactness_m": 26.0,
                      "width_m": 36.0}},
        posture_status=posture_status,
        posture_result={
            "schema_version": "1.0", "posture": posture, "source": source,
            "analysis_time_utc": "2026-10-21T08:00:00Z", "model_id": "test-model",
            "trace_id": "posture-trace", "evidence_strength": 0.78,
            "explanation": "The line moved back and width narrowed.",
            "citations": [
                {"metric_path": "opencv_metrics.before.defensive_line_m", "value": 48.0,
                 "unit": "m (attacking-direction-normalized)",
                 "match_time_window_s": [840.0, 990.0]},
                {"metric_path": "opencv_metrics.after.defensive_line_m", "value": 42.0,
                 "unit": "m (attacking-direction-normalized)",
                 "match_time_window_s": [990.0, 1085.0]},
                {"metric_path": "opencv_metrics.before.width_m", "value": 42.0,
                 "unit": "m (lateral spread)", "match_time_window_s": [840.0, 990.0]},
                {"metric_path": "opencv_metrics.after.width_m", "value": 36.0,
                 "unit": "m (lateral spread)", "match_time_window_s": [990.0, 1085.0]},
            ],
            "limitations": [],
        } if posture_status == "completed" else None,
        created_utc="2026-10-21T08:00:00Z", updated_utc="2026-10-21T08:00:00Z",
    )


def context(*, side="away", objective="chase", roles=None) -> CoachContext:
    return CoachContext(coach_side=side, objective=objective,
                        available_substitute_roles=["attacker"] if roles is None else roles)


def test_supported_advice_is_conditional_and_copies_exact_posture_citations():
    record = event()
    result = create_recommendation(record, context(), created_at_utc="2026-10-21T09:00:00Z")

    assert result["status"] == "ready"
    assert result["condition"].startswith("If the opponent's defensive posture continues")
    assert result["action"] == {"consider_replacing": "defender",
                                 "with_available_role": "attacker"}
    assert result["citations"] == record.posture_result["citations"]
    assert result["evidence_strength"] == 0.78
    assert "not a calibrated probability" in result["confidence_note"]
    assert result["record_id"] == record.record_id


@pytest.mark.parametrize("record,coach_context,reason", [
    (event(status="candidate"), context(), "not deterministically confirmed"),
    (event(posture="unclear", shape=("3-4-3", "4-4-2")), context(),
     "Supported tactical posture"),
    (event(posture_status="unavailable", shape=("3-4-3", "4-4-2")), context(),
     "Supported tactical posture"),
    (event(source="deterministic_fallback", shape=("3-4-3", "4-4-2")), context(),
     "validated evidence"),
    (event(), context(side="home"), "your team's change"),
    (event(posture="unclear"), context(side="home"), "your team's change"),
    (event(status="candidate", posture="unclear"), context(), "not deterministically"),
    (event(), context(objective="protect"), "No available defensive"),
    (event(), context(roles=["midfielder"]), "No available attacking"),
    (event(), context(objective="balanced"), "balanced-objective"),
    (event(), context(side=None), "Select which team"),
    (event(), context(objective=None), "Select a match objective"),
    (event(), context(roles=[]), "Enter at least one available"),
])
def test_unsupported_context_or_evidence_is_withheld(record, coach_context, reason):
    result = create_recommendation(record, coach_context)
    assert result["status"] == "withheld"
    assert result["action"] is None
    assert result["citations"] == []
    assert reason in result["withheld_reason"]


def test_protecting_lead_can_only_receive_supported_defensive_cover_option():
    record = event(posture="attacking")
    result = create_recommendation(record, context(objective="protect", roles=["defender"]))
    assert result["status"] == "ready"
    assert result["action"] == {"consider_replacing": "attacker",
                                 "with_available_role": "defender"}
    blocked = create_recommendation(event(posture="defensive"),
                                    context(objective="protect", roles=["attacker"]))
    assert blocked["status"] == "withheld" and blocked["action"] is None


def test_context_key_is_order_independent_and_duplicate_roles_are_rejected():
    first = context(roles=["attacker", "defender"])
    second = context(roles=["defender", "attacker"])
    assert create_recommendation(event(), first)["recommendation_id"] == \
        create_recommendation(event(), second)["recommendation_id"]
    with pytest.raises(ValueError, match="duplicates"):
        CoachContext(coach_side="away", objective="chase",
                     available_substitute_roles=["attacker", "attacker"])


def test_fabricated_or_out_of_boundary_posture_citation_withholds_advice():
    record = event(shape=("3-4-3", "4-4-2"))
    record.posture_result["citations"][0]["metric_path"] = "teamtrack.annotations.boxes"
    result = create_recommendation(record, context())
    assert result["status"] == "withheld"
    assert "validated evidence" in result["withheld_reason"]

    record = event(shape=("3-4-3", "4-4-2"))
    record.posture_result["citations"][0]["match_time_window_s"] = [1070.0, 1090.0]
    result = create_recommendation(record, context())
    assert result["status"] == "withheld"
    assert result["citations"] == []


def test_fabricated_posture_citations_are_never_shown_with_a_shape_option():
    record = event()  # 4-4-2 -> 3-4-3 opens a shape option; the posture is rejected
    record.posture_result["citations"][0]["metric_path"] = "teamtrack.annotations.boxes"
    result = create_recommendation(record, context())
    assert result["status"] == "ready" and result["basis"] == "shape_matchup"
    assert result["citations"] == [] and result["posture"] is None
    assert result["evidence_strength"] == 0.0


@pytest.mark.parametrize("objective,roles,action", [
    ("chase", ["attacker"],
     {"consider_replacing": "defender", "with_available_role": "attacker"}),
    ("protect", ["defender"],
     {"consider_replacing": "attacker", "with_available_role": "defender"}),
])
def test_unclear_posture_still_gets_a_shape_matchup_option(objective, roles, action):
    # the real demo event: White 4-4-2 -> 3-4-3 confirmed, Bedrock posture unclear
    result = create_recommendation(event(posture="unclear"),
                                   context(objective=objective, roles=roles))
    assert result["status"] == "ready" and result["basis"] == "shape_matchup"
    assert result["action"] == action
    assert result["condition"].startswith("If you are")
    assert "verified shape only" in result["rationale"]
    assert result["shape_evidence"] == {"team": "White", "from": "4-4-2", "to": "3-4-3",
                                        "event_time_s": 990.0}
    assert result["posture"] is None and result["citations"] == []


def test_shape_option_needs_an_opening_and_a_matching_role():
    flat = create_recommendation(event(posture="unclear", shape=("4-4-2", "4-2-3-1")),
                                 context())  # back line unchanged: nothing to exploit
    assert flat["status"] == "withheld" and flat["action"] is None
    balanced = create_recommendation(event(posture="unclear"), context(objective="balanced"))
    assert balanced["status"] == "withheld"


def test_advice_rechecks_cited_values_against_the_stored_opencv_metrics():
    """Fix session 21 Oct: a citation whose value is not the stored metric withholds advice."""
    record = event(shape=("3-4-3", "4-4-2"))  # no shape option to fall back on
    record.posture_result["citations"][1]["value"] = 20.1  # stored after-line is 42.0
    result = create_recommendation(record, context())
    assert result["status"] == "withheld" and result["action"] is None
    assert "validated evidence" in result["withheld_reason"]
    record = event(shape=("3-4-3", "4-4-2"))
    record.posture_result["citations"][3]["unit"] = "m"  # stored unit is "m (lateral spread)"
    assert create_recommendation(record, context())["status"] == "withheld"
    assert create_recommendation(event(), context())["status"] == "ready"  # exact copies pass


def test_recommendations_and_their_coach_responses_survive_restart_and_stay_separate(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    record = event()
    store.upsert_analysis([record])
    store.append_coach_decision(match_id=record.match_id, event_id=record.event_id,
                                alert_id="alert-formation", decision="approved",
                                decided_at_utc="2026-10-21T09:01:00Z", note="event confirmed")

    recommendation = create_recommendation(record, context(),
                                           created_at_utc="2026-10-21T09:00:00Z")
    saved = store.save_recommendation(record_id=record.record_id,
                                      recommendation=recommendation)
    repeated = create_recommendation(record, context(),
                                     created_at_utc="2026-10-21T10:00:00Z")
    assert store.save_recommendation(record_id=record.record_id,
                                     recommendation=repeated) == saved
    decision = store.append_recommendation_decision(
        record_id=record.record_id, recommendation_id=saved["recommendation_id"],
        decision="approved", note="useful option", decided_at_utc="2026-10-21T09:02:00Z")
    assert store.append_recommendation_decision(
        record_id=record.record_id, recommendation_id=saved["recommendation_id"],
        decision="approved", note="useful option",
        decided_at_utc="2026-10-21T10:00:00Z") == decision
    with pytest.raises(EventStoreError, match="different coach response"):
        store.append_recommendation_decision(record_id=record.record_id,
            recommendation_id=saved["recommendation_id"], decision="rejected")

    reopened = EventStore(path).get(record.record_id)
    assert reopened.recommendation["recommendation_id"] == saved["recommendation_id"]
    assert reopened.recommendation["coach_response"]["note"] == "useful option"
    assert len(reopened.coach_decisions) == 1
    assert reopened.coach_decisions[0].alert_id == "alert-formation"
    assert reopened.verification == record.verification
    assert reopened.posture_result == record.posture_result

    store.upsert_analysis([record])
    again = EventStore(path).get(record.record_id)
    assert again.recommendation_status == "ready"
    assert again.recommendation["coach_response"]["decision"] == "approved"
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE recommendation_decisions SET decision='rejected'")
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM recommendations")
