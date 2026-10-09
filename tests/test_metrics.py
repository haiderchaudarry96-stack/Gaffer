"""Shape metrics on hand-made inputs with known answers."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from gaffer.tactics.common import TeamFrame, normalise
from gaffer.tactics.metrics import frame_metrics, possession_share, span_metrics


def _team(raw: np.ndarray, right: bool = True, ball=None, possession=None, t=0.0) -> TeamFrame:
    xy = normalise(raw, right, 105.0, 68.0)
    b = None if ball is None else normalise(np.asarray(ball, dtype=float), right, 105.0, 68.0)
    return TeamFrame(t=t, outfield=xy, n_visible=len(raw) + 1, ball=b, possession=possession,
                     raw_outfield=raw)


def _flat_442(back_x: float) -> np.ndarray:
    """Back four at depth back_x, midfield 15 m ahead, strikers 30 m ahead (attacking right)."""
    back = [[back_x, y] for y in (14.0, 28.0, 40.0, 54.0)]
    mid = [[back_x + 15, y] for y in (14.0, 28.0, 40.0, 54.0)]
    fwd = [[back_x + 30, y] for y in (28.0, 40.0)]
    return np.array(back + mid + fwd)


@pytest.fixture
def exact(cfg):
    """Full range instead of robust percentiles, so answers are exact."""
    return dataclasses.replace(cfg, robust_percentiles=(0.0, 100.0))


def test_defensive_line_width_compactness_centroid(exact):
    m = frame_metrics(_team(_flat_442(30.0)), exact)
    assert m.defensive_line_m == pytest.approx(30.0)
    assert m.compactness_m == pytest.approx(30.0)
    assert m.width_m == pytest.approx(40.0)
    assert m.centroid == pytest.approx((30.0 + (0 * 4 + 15 * 4 + 30 * 2) / 10, 34.0))


def test_metrics_mirror_for_a_team_attacking_left(exact):
    raw = normalise(_flat_442(30.0), False, 105.0, 68.0)  # same shape, other end
    m = frame_metrics(_team(raw, right=False), exact)
    assert m.defensive_line_m == pytest.approx(30.0)
    assert m.width_m == pytest.approx(40.0)
    assert m.centroid[0] == pytest.approx(105.0 - 42.0)  # centroid stays in raw pitch metres


def test_back_line_size_follows_formation(exact):
    raw = _flat_442(30.0)
    raw[3, 0] = 45.0  # one defender pushed into midfield -> a back three at 30 m
    assert frame_metrics(_team(raw), exact, back_line=3).defensive_line_m == pytest.approx(30.0)
    assert frame_metrics(_team(raw), exact, back_line=4).defensive_line_m == pytest.approx(33.75)


def test_pressing_index_bounds_and_linearity(cfg):
    raw = _flat_442(30.0)
    # Ball between the strikers (60, 28) and (60, 40): nearest three are 6, 6 and 16.16 m away.
    ball = [60.0, 34.0]
    mean_d = (6.0 + 6.0 + (15.0**2 + 6.0**2) ** 0.5) / 3
    expected = (cfg.press_far_m - mean_d) / (cfg.press_far_m - cfg.press_near_m)
    m = frame_metrics(_team(raw, ball=ball, possession="away"), cfg)
    assert m.pressing_index == pytest.approx(expected)
    on_top = raw[0].tolist()
    crowd = raw.copy()
    crowd[1:3] = raw[0]  # three players on the ball -> distance 0 -> clipped to 1
    assert frame_metrics(_team(crowd, ball=on_top, possession="away"), cfg).pressing_index == 1.0
    far_ball = [100.0, 66.0]
    assert frame_metrics(_team(raw, ball=far_ball, possession="away"), cfg).pressing_index == 0.0
    assert frame_metrics(_team(raw, ball=ball), cfg).pressing_index is None  # no possession
    assert frame_metrics(_team(raw, possession="away"), cfg).pressing_index is None  # no ball


def test_span_pressing_uses_only_defending_frames(cfg):
    raw = _flat_442(30.0)
    ball = raw[0] + [1.0, 0.0]
    frames = [_team(raw, ball=ball, possession="home", t=0.0),   # home has the ball
              _team(raw, ball=[100.0, 66.0], possession="away", t=1.0)]  # away has it, far
    s = span_metrics(frames, "home", cfg)
    assert s.pressing_index == 0.0
    assert s.frames == 2 and s.players_visible_mean == 11.0


def test_too_few_players_gives_none(cfg):
    m = frame_metrics(_team(_flat_442(30.0)[:3]), cfg)
    assert (m.defensive_line_m, m.compactness_m, m.width_m, m.centroid) == (None,) * 4
    assert span_metrics([], "home", cfg).defensive_line_m is None


def test_possession_share():
    f = [_team(_flat_442(30.0), possession=p) for p in ("home", "home", "away", "dead", None)]
    assert possession_share(f) == {"home": 67, "away": 33}
    assert possession_share(f[3:]) is None
