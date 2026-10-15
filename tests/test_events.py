"""Change detector: fires once at the right time, ignores flickers, handles uncertainty."""

from __future__ import annotations

import pytest

from gaffer.schema import GroundTruth, parse_match_state
from gaffer.synthetic import Change, Schedule, generate_match
from gaffer.tactics.common import TacticsConfig
from gaffer.tactics.events import describe_lines, detect_changes
from gaffer.tactics.formation import UNCERTAIN, WindowResult
from gaffer.tactics.timeline import build_timeline


def windows(labels: list[str], step: float = 5.0, t0: float = 30.0) -> list[WindowResult]:
    return [WindowResult(t=t0 + i * step, team="home", label=lab,
                         best=None if lab == UNCERTAIN else lab,
                         confidence=0.0 if lab == UNCERTAIN else 0.9, probs={},
                         usable_frames=30, total_frames=30, mean_visible=9.5, window_s=30.0)
            for i, lab in enumerate(labels)]


def test_change_fires_once_at_the_right_time(cfg):
    ws = windows(["4-4-2"] * 20 + ["3-5-2"] * 20)
    changes = detect_changes(ws, cfg)
    assert len(changes) == 1
    c = changes[0]
    first_new = ws[20].t
    assert (c.from_formation, c.to_formation) == ("4-4-2", "3-5-2")
    assert c.detected_at_s == pytest.approx(first_new + cfg.min_persist_s)
    assert c.t == pytest.approx(first_new - cfg.window_s / 2)
    event = c.to_event("evt_001")
    assert event.status == "candidate" and event.verification is None
    assert "back line 4->3" in event.evidence and "midfield 4->5" in event.evidence


def test_first_formation_is_a_silent_baseline(cfg):
    assert detect_changes(windows(["4-3-3"] * 30), cfg) == []


def test_three_second_flicker_is_ignored(cfg):
    ws = windows(["4-4-2"] * 60 + ["3-5-2"] * 3 + ["4-4-2"] * 60, step=1.0)
    assert detect_changes(ws, cfg) == []


def test_flicker_just_under_persistence_is_ignored(cfg):
    n = int(cfg.min_persist_s / cfg.step_s)  # held time = (n - 1) * step < min_persist_s
    ws = windows(["4-4-2"] * 20 + ["3-5-2"] * n + ["4-4-2"] * 20)
    assert detect_changes(ws, cfg) == []


def test_uncertain_windows_pause_but_do_not_reset(cfg):
    ws = windows(["4-4-2"] * 20 + ["3-5-2"] * 3 + [UNCERTAIN] * 2 + ["3-5-2"] * 3
                 + ["3-5-2"] * 5)
    changes = detect_changes(ws, cfg)
    assert len(changes) == 1 and changes[0].to_formation == "3-5-2"


def test_long_uncertain_gap_resets_challenger(cfg):
    gap = int(cfg.max_uncertain_gap_s / cfg.step_s) + 2
    ws = windows(["4-4-2"] * 20 + ["3-5-2"] * 4 + [UNCERTAIN] * gap + ["4-4-2"] * 10)
    assert detect_changes(ws, cfg) == []


def test_alternating_challengers_do_not_fire(cfg):
    ws = windows(["4-4-2"] * 20 + ["3-5-2", "4-3-3"] * 10 + ["4-4-2"] * 10)
    assert detect_changes(ws, cfg) == []


def test_switching_inside_a_formation_family_is_not_a_change(cfg):
    assert cfg.family("5-3-2") == cfg.family("3-5-2")  # config: formations.equivalent
    flip = (["3-5-2"] * 6 + ["5-3-2"] * 6) * 5
    assert detect_changes(windows(["3-5-2"] * 20 + flip), cfg) == []
    changes = detect_changes(windows(["4-4-2"] * 20 + ["5-3-2"] * 8 + ["3-5-2"] * 3), cfg)
    assert [(c.from_formation, c.to_formation) for c in changes] == [("4-4-2", "5-3-2")]


def test_describe_lines():
    assert describe_lines("4-4-2", "3-5-2") == "back line 4->3, midfield 4->5"
    assert describe_lines("4-4-2", "4-2-3-1") == "3 lines -> 4 lines, back line kept at 4"


def _run(cfg_dict, schedule, seed=42):
    m, g = generate_match(seed, cfg_dict, schedule, "test")
    match, gt = parse_match_state(m), GroundTruth.model_validate(g)
    return build_timeline(match, TacticsConfig.from_config(cfg_dict)), gt


# The end-to-end tests use shapes the engine separates cleanly; the known 4-3-3 / 4-2-3-1
# ambiguity is measured by scripts/eval_synthetic.py and logged in docs/FAILURE_LOG.md.


def test_end_to_end_single_change_detected_once(small_synth_cfg):
    schedule = Schedule(start={"home": "4-4-2", "away": "5-3-2"},
                        changes=[Change("home", 600.0, "3-5-2")])
    result, _ = _run(small_synth_cfg, schedule)
    events = result.timeline.events
    assert len(events) == 1
    e, c = events[0], result.changes[0]
    assert (e.team, e.from_, e.to, e.status) == ("home", "4-4-2", "3-5-2", "candidate")
    assert abs(e.t - 600.0) <= 30.0
    assert 0.0 < c.detected_at_s - 600.0 <= 90.0


def test_end_to_end_flickers_produce_no_event(small_synth_cfg):
    small_synth_cfg["synthetic"]["noise_events"]["flickers"] = [3, 3]
    schedule = Schedule(start={"home": "4-4-2", "away": "3-5-2"}, changes=[])
    result, gt = _run(small_synth_cfg, schedule)
    assert sum(e.kind == "flicker" for e in gt.noise_events) == 3
    assert result.timeline.events == []


def test_change_family_hides_433_4231_but_keeps_the_label(cfg):
    from dataclasses import replace

    fam = replace(cfg, change_families={"4-3-3": "4-3-3", "4-2-3-1": "4-3-3"})
    ws = windows(["4-4-2"] * 20 + ["4-3-3"] * 10 + ["4-2-3-1"] * 6 + ["4-3-3"] * 10
                 + ["4-2-3-1"] * 10)
    assert len(detect_changes(ws, cfg)) >= 2  # without the family: flip-flop candidates
    changes = detect_changes(ws, fam)
    assert len(changes) == 1  # 4-4-2 -> (4-3-3 family) only
    assert (changes[0].from_formation, changes[0].to_formation) == ("4-4-2", "4-3-3")
    assert fam.family("4-2-3-1") == "4-2-3-1"  # segments / labels keep the exact formation
    assert fam.change_family("4-2-3-1") == "4-3-3"
    assert fam.change_family("5-3-2") == cfg.family("5-3-2")  # 3-5-2 = 5-3-2 still applies


def _levels(values: list[float | None], step: float = 5.0) -> list[tuple[float, float | None,
                                                                         float]]:
    return [(30.0 + i * step, v, 0.0 if v is None else 0.9) for i, v in enumerate(values)]


def test_line_drop_fires_once_after_the_hold_and_reports_both_heights(cfg):
    from gaffer.tactics.events import detect_line_drops

    lv = _levels([35.0] * 20 + [25.0] * 30)
    out = detect_line_drops(lv, "home", cfg, drop_m=8.0, hold_s=60.0)
    assert len(out) == 1
    d = out[0]
    first_low = lv[20][0]
    assert d.detected_at_s == pytest.approx(first_low + 60.0)
    assert d.t == pytest.approx(first_low - cfg.window_s / 2)
    e = d.to_event("evt_001")
    assert e.type == "line_drop" and e.from_ is None and e.to is None
    assert "35.0 m -> 25.0 m" in e.evidence


def test_line_drop_ignores_short_dips_push_ups_and_disabled_config(cfg):
    from gaffer.tactics.events import detect_line_drops

    dip = _levels([35.0] * 20 + [25.0] * 11 + [35.0] * 20)  # held 50 s < 60 s
    assert detect_line_drops(dip, "home", cfg, drop_m=8.0, hold_s=60.0) == []
    up_then_back = _levels([25.0] * 20 + [35.0] * 30 + [25.0] * 30)  # push up re-baselines
    out = detect_line_drops(up_then_back, "home", cfg, drop_m=8.0, hold_s=60.0)
    assert len(out) == 1 and out[0].from_formation == "35.0"  # the drop from the new level
    gap = _levels([35.0] * 20 + [25.0] * 5 + [None] * 10 + [25.0] * 20)  # 50 s gap > 30 s
    assert all(d.detected_at_s > gap[35][0] for d in
               detect_line_drops(gap, "home", cfg, drop_m=8.0, hold_s=60.0))
    from dataclasses import replace

    assert detect_line_drops(dip, "home", replace(cfg, line_drop_m=None)) == []
