"""Bedrock posture analysis is mocked and remains separate from deterministic verification."""

from __future__ import annotations

import copy
import json

import pytest

from gaffer.agent.posture import PostureAnalyzer, build_evidence, validate_assessment
from gaffer.api.event_store import EventRecordV1_1, EventStore
from gaffer.api.usage import Usage
from gaffer.config import load_config
from gaffer.llm.bedrock_client import (
    BedrockCredentialsError,
    BedrockThrottlingError,
    ChatResult,
)


def event(*, status: str = "confirmed", retreat: bool = False) -> EventRecordV1_1:
    before = {"start_s": 840.0, "end_s": 990.0, "formation": "4-4-2",
              "confidence": 0.82, "defensive_line_m": 48.0 if retreat else 42.0,
              "compactness_m": 28.0, "width_m": 42.0,
              "centroid": {"x": 50.0, "y": 34.0}, "pressing_index": None}
    after = {"start_s": 990.0, "end_s": 1085.0, "formation": "3-4-3",
             "confidence": 0.79, "defensive_line_m": 42.0 if retreat else 48.0,
             "compactness_m": 21.0 if retreat else 33.0,
             "width_m": 36.0 if retreat else 48.0,
             "centroid": {"x": 52.0, "y": 34.5}, "pressing_index": None}
    return EventRecordV1_1(
        record_id="record_demo_evt_003", analysis_id="analysis_demo",
        match_id="teamtrack_top_w900_1260", event_id="evt_003", event_type="shape_change",
        team="home", team_name="White", from_formation="4-4-2", to_formation="3-4-3",
        candidate_time_s=990.0, detection_time_s=1025.0, status=status,
        verification_match_time_s=1085.0,
        verification={"decision": status, "verdict": status,
                      "reason": "The verified shape held over the required OpenCV window."},
        opencv_metrics={
            "before": before, "after": after,
            "coverage": {"coverage_before": 0.88, "coverage_after": 0.91,
                         "footage_frac": 0.95},
            "quality": {"uncertain_fraction": 0.12, "mean_players_visible": 18.0,
                        "verification_window": {"homography_ok_share": 0.94}},
            "reanalysis": {"window": [945.0, 1085.0], "sample_fps": 5.0,
                           "frames": 700, "coverage": {"footage_frac": 0.95},
                           "vs_event": {"covers_required_span": True}},
        },
        created_utc="2026-10-21T08:00:00Z", updated_utc="2026-10-21T08:00:00Z",
    )


def valid_output(posture: str = "attacking") -> dict:
    return {
        "schema_version": "1.0", "posture": posture, "evidence_strength": 0.78,
        "explanation": "The team moved its defensive line forward and widened its shape.",
        "citations": [
            {"metric_path": "opencv_metrics.before.defensive_line_m", "value": 42.0,
             "unit": "m (attacking-direction-normalized)",
             "match_time_window_s": [840.0, 990.0]},
            {"metric_path": "opencv_metrics.after.defensive_line_m", "value": 48.0,
             "unit": "m (attacking-direction-normalized)",
             "match_time_window_s": [990.0, 1085.0]},
            {"metric_path": "opencv_metrics.before.width_m", "value": 42.0,
             "unit": "m (lateral spread)", "match_time_window_s": [840.0, 990.0]},
            {"metric_path": "opencv_metrics.after.width_m", "value": 48.0,
             "unit": "m (lateral spread)", "match_time_window_s": [990.0, 1085.0]},
        ],
        "limitations": [],
    }


class FakeLLM:
    def __init__(self, output: str | Exception):
        self.output = output
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        return ChatResult(self.output, [], "end_turn", {"role": "assistant"},
                          "global.amazon.nova-2-lite-v1:0", 1.0, 1,
                          {"input_tokens": 1200, "output_tokens": 70,
                           "total_tokens": 1270})


class SequenceLLM:
    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.calls = 0

    def chat(self, messages, **kwargs):
        output = self.outputs[self.calls]
        self.calls += 1
        return ChatResult(output, [], "end_turn", {"role": "assistant"},
                          "global.amazon.nova-2-lite-v1:0", 1.0, 1,
                          {"input_tokens": 1500, "output_tokens": 80,
                           "total_tokens": 1580})


def config_with_trace(tmp_path):
    cfg = copy.deepcopy(load_config())
    cfg["api"]["posture"]["trace_path"] = str(tmp_path / "posture_trace.jsonl")
    return cfg


def analyzer_for(tmp_path, llm, *, cfg=None, usage=None):
    settings = cfg or config_with_trace(tmp_path)
    store = EventStore(tmp_path / "events.sqlite3")
    store.upsert_analysis([event()])
    analyzer = PostureAnalyzer(settings, store, lambda: llm, usage,
                               trace_path=tmp_path / "posture_trace.jsonl")
    return analyzer, store


def test_supported_bedrock_posture_has_exact_paired_citations_and_is_idempotent(tmp_path):
    llm = FakeLLM(json.dumps(valid_output()))
    analyzer, store = analyzer_for(tmp_path, llm)
    original = store.get("record_demo_evt_003")
    store.append_coach_decision(match_id=original.match_id, event_id=original.event_id,
                                alert_id="alert_demo", decision="approved",
                                decided_at_utc="2026-10-21T08:05:00Z", note="looks right")

    assert analyzer.analyze(original.record_id) == "completed"
    assert analyzer.analyze(original.record_id) == "already_processed"
    reopened = EventStore(tmp_path / "events.sqlite3").get(original.record_id)
    assert llm.calls == 1
    assert reopened.posture_status == "completed"
    assert reopened.posture_result["posture"] == "attacking"
    assert reopened.posture_result["source"] == "bedrock"
    assert reopened.posture_result["schema_version"] == "1.0"
    assert reopened.posture_result["trace_id"]
    assert len(reopened.posture_result["citations"]) == 4
    assert any("posture_trace.jsonl#" in ref for ref in reopened.trace_refs)
    assert reopened.status == original.status
    assert reopened.verification == original.verification
    assert reopened.verification_match_time_s == original.verification_match_time_s
    assert reopened.coach_decisions[0].note == "looks right"
    assert reopened.coach_decisions[0].decision == "approved"

    # An OpenCV worker retry may refresh its event snapshot, but cannot erase posture or history.
    store.upsert_analysis([original])
    after_rerun = EventStore(tmp_path / "events.sqlite3").get(original.record_id)
    assert after_rerun.posture_status == "completed"
    assert after_rerun.posture_result["posture"] == "attacking"
    assert len(after_rerun.coach_decisions) == 1


def test_conflicting_shape_evidence_downgrades_attacking_claim_to_unclear():
    record = event()
    metrics = record.opencv_metrics
    metrics["after"]["defensive_line_m"] = 39.0
    metrics["after"]["width_m"] = 38.0
    record.opencv_metrics = metrics
    output = valid_output("attacking")
    output["citations"][1]["value"] = 39.0
    output["citations"][3]["value"] = 38.0
    evidence = build_evidence(record)

    assessment, reason = validate_assessment(json.dumps(output), evidence,
                                             load_config()["api"]["posture"])
    assert assessment is not None
    assert assessment.posture == "unclear"
    assert reason == "unsupported_attacking_label"


def test_hybrid_needs_two_cited_shape_dimensions_that_move_in_mixed_directions():
    record = event()
    output = valid_output("hybrid")
    output["citations"] = [
        {"metric_path": "opencv_metrics.before.compactness_m", "value": 28.0,
         "unit": "m (front-to-back depth)", "match_time_window_s": [840.0, 990.0]},
        {"metric_path": "opencv_metrics.after.compactness_m", "value": 33.0,
         "unit": "m (front-to-back depth)", "match_time_window_s": [990.0, 1085.0]},
        {"metric_path": "opencv_metrics.before.width_m", "value": 42.0,
         "unit": "m (lateral spread)", "match_time_window_s": [840.0, 990.0]},
        {"metric_path": "opencv_metrics.after.width_m", "value": 36.0,
         "unit": "m (lateral spread)", "match_time_window_s": [990.0, 1085.0]},
    ]
    metrics = record.opencv_metrics
    metrics["after"]["compactness_m"] = 33.0
    metrics["after"]["width_m"] = 36.0
    record.opencv_metrics = metrics
    assessment, reason = validate_assessment(json.dumps(output), build_evidence(record),
                                             load_config()["api"]["posture"])
    assert assessment is not None and assessment.posture == "hybrid"
    assert reason == "mixed_shape_signals_supported"


def test_supported_defensive_read_uses_retreat_and_a_paired_shape_contraction():
    record = event(retreat=True)
    output = valid_output("defensive")
    output["explanation"] = "The line moved back and the team's width narrowed."
    output["citations"] = [
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
    ]
    assessment, reason = validate_assessment(json.dumps(output), build_evidence(record),
                                             load_config()["api"]["posture"])
    assert assessment is not None and assessment.posture == "defensive"
    assert reason == "defensive_shape_signals_supported"


def test_weak_quality_downgrades_a_cited_directional_read_to_unclear():
    record = event()
    metrics = record.opencv_metrics
    metrics["quality"]["uncertain_fraction"] = 0.85
    record.opencv_metrics = metrics
    assessment, reason = validate_assessment(json.dumps(valid_output()), build_evidence(record),
                                             load_config()["api"]["posture"])
    assert assessment is not None and assessment.posture == "unclear"
    assert reason == "weak_quality_high_uncertainty"


def test_formation_name_alone_cannot_support_posture():
    record = event()
    metrics = record.opencv_metrics
    for side in ("before", "after"):
        metrics[side]["defensive_line_m"] = None
        metrics[side]["compactness_m"] = None
        metrics[side]["width_m"] = None
        metrics[side]["pressing_index"] = None
    record.opencv_metrics = metrics
    output = valid_output("attacking")
    output["citations"] = []
    assessment, reason = validate_assessment(json.dumps(output), build_evidence(record),
                                             load_config()["api"]["posture"])
    assert assessment is None
    assert reason == "directional_label_needs_two_paired_metric_types"


def test_null_ball_possession_and_pressing_are_not_added_to_evidence_or_citations():
    evidence = build_evidence(event())
    serialized = json.dumps(evidence)
    assert "ball_movement" not in serialized
    assert "possession" not in evidence
    assert evidence["shape_windows"]["before"]["metrics"]["pressing_index"] is None
    assert "opencv_metrics.before.pressing_index" not in {
        c.metric_path for c in validate_assessment(
            json.dumps({**valid_output("unclear"), "citations": []}), evidence,
            load_config()["api"]["posture"])[0].citations
    }


@pytest.mark.parametrize("citation_change,expected", [
    ({"value": 43.0}, "citation_mismatch:opencv_metrics.before.defensive_line_m"),
    ({"metric_path": "opencv_metrics.before.possession"},
     "missing_or_null_metric:opencv_metrics.before.possession"),
])
def test_fabricated_or_mismatched_citations_are_rejected(citation_change, expected):
    output = valid_output()
    output["citations"][0].update(citation_change)
    assessment, reason = validate_assessment(json.dumps(output), build_evidence(event()),
                                             load_config()["api"]["posture"])
    assert assessment is None
    assert reason == expected


@pytest.mark.parametrize("failure,expected_status", [
    (BedrockCredentialsError("missing"), "unavailable"),
    (BedrockThrottlingError("throttled", code="ThrottlingException"), "failed"),
    (TimeoutError("timeout"), "failed"),
])
def test_bedrock_failures_persist_unclear_fallback_and_do_not_change_verifier(
        tmp_path, failure, expected_status):
    llm = FakeLLM(failure)
    analyzer, store = analyzer_for(tmp_path, llm)
    assert analyzer.analyze("record_demo_evt_003") == expected_status
    saved = store.get("record_demo_evt_003")
    assert saved.posture_status == expected_status
    assert saved.posture_result["posture"] == "unclear"
    assert saved.posture_result["source"] == "deterministic_fallback"
    assert saved.status == "confirmed"
    assert saved.verification["decision"] == "confirmed"


def test_malformed_result_and_budget_exhaustion_use_labeled_fallback(tmp_path):
    llm = FakeLLM("not JSON")
    analyzer, store = analyzer_for(tmp_path, llm)
    assert analyzer.analyze("record_demo_evt_003") == "failed"
    assert store.get("record_demo_evt_003").posture_result["source"] == "deterministic_fallback"

    second_dir = tmp_path / "budget"
    second_dir.mkdir()
    cfg = config_with_trace(second_dir)
    cfg["api"]["posture"]["trace_path"] = str(second_dir / "posture_trace.jsonl")
    usage = Usage(cfg, str(second_dir / "usage.json"))
    usage.add_bedrock(usage.max_calls, usage.max_cost)
    blocked, blocked_store = analyzer_for(second_dir, FakeLLM(json.dumps(valid_output())),
                                          cfg=cfg, usage=usage)
    assert blocked.analyze("record_demo_evt_003") == "unavailable"
    assert blocked_store.get("record_demo_evt_003").posture_result["limitations"] == [
        "global_api_bedrock_budget_exhausted"]


def test_unavailable_pressure_claim_from_model_is_rejected(tmp_path):
    output = valid_output()
    output["explanation"] = "The team increased pressure after its shape change."
    analyzer, store = analyzer_for(tmp_path, FakeLLM(json.dumps(output)))
    assert analyzer.analyze("record_demo_evt_003") == "failed"
    saved = store.get("record_demo_evt_003")
    assert saved.posture_result["posture"] == "unclear"
    assert saved.posture_result["source"] == "deterministic_fallback"
    assert saved.posture_result["limitations"] == [
        "model_made_unsupported_ball_possession_pressure_or_intent_claim"]
    # Audit 2026-10-21: a rejected answer keeps its real token usage and output hash.
    assert saved.posture_result["usage"]["input_tokens"] == 1200
    assert saved.posture_result["usage"]["output_tokens"] == 70
    rows = [json.loads(line) for line in (tmp_path / "posture_trace.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert next(r for r in rows if r["step"] == "fallback")["model_output_sha256"]


def test_fenced_json_answer_is_parsed_and_still_fully_validated():
    """Audit 2026-10-21: the real Nova 2 Lite answer came wrapped in a ```json fence."""
    evidence = build_evidence(event())
    cfg = load_config()["api"]["posture"]
    plain = validate_assessment(json.dumps(valid_output()), evidence, cfg)
    fenced = validate_assessment("```json\n" + json.dumps(valid_output()) + "\n```", evidence, cfg)
    assert fenced == plain and fenced[0] is not None
    bad = valid_output()
    bad["citations"][0]["metric_path"] = "defensive_line_m"
    assert validate_assessment("```json\n" + json.dumps(bad) + "\n```", evidence, cfg)[0] is None


def test_evidence_lists_exactly_the_citations_the_validator_accepts():
    evidence = build_evidence(event())
    listed = {c["metric_path"]: c for c in evidence["citable_metrics"]}
    assert "opencv_metrics.after.defensive_line_m" in listed
    assert all("pressing_index" not in p and "confidence" not in p for p in listed)  # null / meta
    output = valid_output()
    output["citations"] = [listed[p] for p in (
        "opencv_metrics.before.defensive_line_m", "opencv_metrics.after.defensive_line_m",
        "opencv_metrics.before.width_m", "opencv_metrics.after.width_m")]
    assessment, reason = validate_assessment(json.dumps(output), evidence,
                                             load_config()["api"]["posture"])
    assert assessment is not None and reason == "attacking_shape_signals_supported"


def test_banned_signal_check_reads_the_claim_not_the_limitations():
    evidence, cfg = build_evidence(event()), load_config()["api"]["posture"]
    output = valid_output()
    output["limitations"] = ["No ball, possession or pressing_index data: pressing intensity "
                             "cannot be confirmed."]
    assessment, reason = validate_assessment(json.dumps(output), evidence, cfg)
    assert assessment is not None and reason == "attacking_shape_signals_supported"
    output["explanation"] = "The opponent pressed higher after the change."
    assert validate_assessment(json.dumps(output), evidence, cfg) == (
        None, "model_made_unsupported_ball_possession_pressure_or_intent_claim")
    assert validate_assessment(json.dumps(output), evidence, cfg, stage="reassessment")[1] \
        == "reassessment_made_unsupported_ball_possession_pressure_or_intent_claim"


def test_model_unclear_on_weak_evidence_is_kept_as_a_validated_bedrock_result(tmp_path):
    """Like the real evt_003: the before window is too uncertain (confidence below the floor)."""
    output = {"posture": "unclear", "evidence_strength": 0.6,
              "explanation": "The line moved up, but the shape before 16:30 was not clear.",
              "citations": [], "limitations": ["Ball and possession are not measured."]}
    store = EventStore(tmp_path / "events.sqlite3")
    record = event()
    metrics = record.opencv_metrics
    metrics["before"]["confidence"] = 0.30
    record.opencv_metrics = metrics
    store.upsert_analysis([record])
    analyzer = PostureAnalyzer(config_with_trace(tmp_path), store,
                               lambda: FakeLLM(json.dumps(output)), None,
                               trace_path=tmp_path / "posture_trace.jsonl")
    assert analyzer.analyze(record.record_id) == "completed"
    saved = store.get(record.record_id).posture_result
    assert saved["posture"] == "unclear" and saved["source"] == "bedrock"
    assert saved["evidence_strength"] == 0.35  # capped, never raised
    assert "weak_quality_low_segment_confidence" in saved["limitations"]
    assert saved["explanation"] == output["explanation"]


def test_nonconfirmed_event_is_skipped_without_bedrock_call(tmp_path):
    cfg = config_with_trace(tmp_path)
    store = EventStore(tmp_path / "events.sqlite3")
    rejected = event(status="rejected")
    store.upsert_analysis([rejected])
    llm = FakeLLM(json.dumps(valid_output()))
    analyzer = PostureAnalyzer(cfg, store, lambda: llm,
                               trace_path=tmp_path / "posture_trace.jsonl")
    assert analyzer.analyze(rejected.record_id) == "skipped_unverified"
    saved = store.get(rejected.record_id)
    assert saved.posture_status == "not_requested"
    assert saved.posture_result is None
    assert llm.calls == 0


def test_bounded_video_reanalysis_is_traced_then_used_by_second_assessment(tmp_path):
    record = event()
    metrics = record.opencv_metrics
    metrics["after"].update(defensive_line_m=None, compactness_m=None, width_m=None,
                            start_s=990.0, end_s=1000.0)
    metrics["coverage"]["coverage_after"] = 0.2
    metrics["quality"].update(uncertain_fraction=0.85, mean_players_visible=2.0)
    record.opencv_metrics = metrics
    request = {
        "schema_version": "1.0", "posture": "unclear", "evidence_strength": 0.2,
        "explanation": "The stored post-event interval is too short to classify shape.",
        "citations": [], "limitations": ["Need a longer post-event shape window."],
        "visual_reanalysis_request": {"start_s": 990.0, "end_s": 1035.0, "sample_fps": 5},
    }
    second = valid_output()
    second["citations"][1].update(
        metric_path="opencv_reanalysis.after.defensive_line_m", value=48.0,
        match_time_window_s=[990.0, 1035.0])
    second["citations"][3].update(
        metric_path="opencv_reanalysis.after.width_m", value=48.0,
        match_time_window_s=[990.0, 1035.0])
    llm = SequenceLLM([json.dumps(request), json.dumps(second)])
    analyzer, store = analyzer_for(tmp_path, llm)
    # Replace the full-window seeded event with the deliberately incomplete snapshot.
    store.upsert_analysis([record])
    seen = []

    def reanalyse(saved_record, requested):
        seen.append((saved_record.event_id, requested.start_s, requested.end_s,
                     requested.sample_fps))
        return {
            "window_s": [990.0, 1035.0],
            "metrics": {"defensive_line_m": 48.0, "compactness_m": 33.0,
                        "width_m": 48.0, "confidence": 0.8},
            "quality": {"coverage": 0.9, "mean_players_visible": 18.0,
                        "uncertain_fraction": 0.1},
        }

    analyzer.visual_reanalysis = reanalyse
    assert analyzer.analyze(record.record_id) == "completed"
    saved = store.get(record.record_id)
    assert seen == [(record.event_id, 990.0, 1035.0, 5)]
    assert llm.calls == 2
    assert saved.posture_result["posture"] == "attacking"
    assert {c["metric_path"] for c in saved.posture_result["citations"]} >= {
        "opencv_reanalysis.after.defensive_line_m", "opencv_reanalysis.after.width_m"}
    trace = (tmp_path / "posture_trace.jsonl").read_text(encoding="utf-8")
    assert '"step":"opencv_reanalysis"' in trace
    assert '"step":"reassessment_step"' in trace
    assert '"step":"model_decision"' in trace


def test_visual_reanalysis_is_not_used_when_event_window_is_already_sufficient(tmp_path):
    request = {
        "schema_version": "1.0", "posture": "unclear", "evidence_strength": 0.2,
        "explanation": "Requesting a redundant window.", "citations": [], "limitations": [],
        "visual_reanalysis_request": {"start_s": 990.0, "end_s": 1035.0, "sample_fps": 5},
    }
    llm = FakeLLM(json.dumps(request))
    analyzer, store = analyzer_for(tmp_path, llm)
    called = []
    analyzer.visual_reanalysis = lambda *args: called.append(args)
    assert analyzer.analyze("record_demo_evt_003") == "failed"
    saved = store.get("record_demo_evt_003")
    assert saved.posture_result["posture"] == "unclear"
    assert saved.posture_result["limitations"] == [
        "stored_post_event_metrics_are_already_sufficient"]
    assert called == []

