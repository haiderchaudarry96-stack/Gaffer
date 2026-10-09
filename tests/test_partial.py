"""Partial visibility and junk frames never crash the engine; full-match timeline size."""

from __future__ import annotations

import pytest

from gaffer.schema import GroundTruth, TacticalTimeline, parse_match_state
from gaffer.synthetic import generate_match
from gaffer.tactics.common import TacticsConfig
from gaffer.tactics.formation import UNCERTAIN
from gaffer.tactics.timeline import build_timeline
from tests.conftest import build_match, player


def _junk_frames() -> list[dict]:
    frames = []
    for t in range(0, 240):
        kind = t % 6
        if kind == 0:
            players = []  # nothing detected
        elif kind == 1:
            players = [player(1, "home", 50, 30)]
        elif kind == 2:
            players = [player(i, "away", 40 + i, 20 + i) for i in range(3)]
        elif kind == 3:
            players = [player(0, "referee", 52, 34), player(7, "unknown", 60, 30)]
        elif kind == 4:
            players = [player(1, "home", 10, 34, role="goalkeeper")]  # keeper only
        else:
            players = [player(i, "home", 30 + 3 * i, 10 + 5 * i) for i in range(7)]
        frames.append({"t": float(t), "players": players,
                       "ball": {"x": None, "y": None, "visible": False} if t % 2 else None,
                       "possession": None})
    return frames


def test_junk_and_partial_frames_do_not_crash(cfg):
    match = build_match(_junk_frames(), duration=240.0, half=120.0)
    result = build_timeline(match, cfg)
    tl = TacticalTimeline.model_validate_json(result.timeline.to_json())
    assert tl.events == []
    for seg in tl.segments:
        for side in (seg.home, seg.away):
            assert side.formation == UNCERTAIN
    assert tl.quality.uncertain_fraction == 1.0


def test_empty_match_does_not_crash(cfg):
    match = build_match([{"t": 0.0, "players": []}], duration=10.0)
    tl = build_timeline(match, cfg).timeline
    assert tl.events == [] and tl.segments


def test_broadcast_window_match_runs(small_synth_cfg):
    small_synth_cfg["synthetic"]["camera"]["broadcast_fraction"] = 1.0
    m, g = generate_match(42, small_synth_cfg, None, "partial")
    match = parse_match_state(m)
    visible = [sum(p.team in ("home", "away") for p in f.players) for f in match.frames]
    assert min(visible) < 22
    tl = build_timeline(match, TacticsConfig.from_config(small_synth_cfg)).timeline
    assert tl.quality.mean_players_visible < 9.0
    GroundTruth.model_validate(g)


@pytest.mark.slow
def test_full_match_timeline_under_8kb():
    m, _ = generate_match(42, None, None, "synthetic_001")
    tl = build_timeline(parse_match_state(m)).timeline
    size = len(tl.to_json().encode())
    assert size < 8 * 1024, size
