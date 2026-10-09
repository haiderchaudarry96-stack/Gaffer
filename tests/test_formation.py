"""Template generation and matching, attacking-direction normalisation, futsal config."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from gaffer.config import load_config
from gaffer.tactics.common import TacticsConfig, extract_team_frames, normalise
from gaffer.tactics.formation import (
    UNCERTAIN,
    build_template,
    build_templates,
    classify_frames,
    parse_formation,
)
from tests.conftest import build_match, player, shape_points


def test_parse_formation():
    assert parse_formation("4-2-3-1") == (4, 2, 3, 1)
    assert parse_formation("4-0") == (4,)
    with pytest.raises(ValueError):
        parse_formation("four-four-two")


def test_template_shape_and_player_count(cfg):
    t = build_template("4-3-3", cfg)
    assert t.slots.shape == (10, 2)
    assert np.allclose(t.slots.mean(axis=0), 0.0)
    assert list(np.bincount(t.slot_line)) == [4, 3, 3]
    with pytest.raises(ValueError, match="11 players"):
        build_template("4-4-3", cfg)


@pytest.mark.parametrize("name", load_config()["formations"]["templates"])
def test_each_template_recognised_with_noise(cfg, name):
    rng = np.random.default_rng(42)
    slots = build_template(name, cfg).slots
    frames = [shape_points(slots, (50.0, 34.0), rng, noise=1.5, scale=(1.1, 0.9))
              for _ in range(20)]
    label, best, conf, _ = classify_frames(frames, cfg)
    assert label == name, (best, conf)
    assert conf > 0.8


@pytest.mark.parametrize("name", load_config()["formations"]["templates"])
def test_partial_team_is_correct_or_uncertain(cfg, name):
    rng = np.random.default_rng(42)
    slots = build_template(name, cfg).slots
    frames = []
    for _ in range(20):
        pts = shape_points(slots, (50.0, 34.0), rng, noise=1.0)
        frames.append(pts[rng.choice(10, size=8, replace=False)])
    label, _, _, _ = classify_frames(frames, cfg)
    assert label in (name, UNCERTAIN)


def test_too_few_players_is_uncertain(cfg):
    rng = np.random.default_rng(42)
    slots = build_template("4-4-2", cfg).slots
    frames = [shape_points(slots, (50.0, 34.0), rng)[:5] for _ in range(20)]
    label, best, conf, _ = classify_frames(frames, cfg)
    assert (label, best, conf) == (UNCERTAIN, None, 0.0)


def test_normalise_is_a_180_degree_turn():
    xy = np.array([[10.0, 5.0], [100.0, 60.0]])
    assert np.allclose(normalise(xy, True, 105, 68), xy)
    assert np.allclose(normalise(xy, False, 105, 68), [[95.0, 63.0], [5.0, 8.0]])


def test_second_half_mirroring_gives_same_label(cfg):
    """Home attacks right in the first half, left in the second: same shape, same label."""
    rng = np.random.default_rng(42)
    slots = build_template("3-5-2", cfg).slots
    frames = []
    for t in range(0, 120):
        right = t < 60
        pts = shape_points(slots, (45.0, 30.0), rng, noise=1.0)  # normalised coordinates
        raw = normalise(pts, right, 105.0, 68.0)  # normalise is its own inverse
        frames.append({"t": float(t),
                       "players": [player(i, "home", x, y) for i, (x, y) in enumerate(raw)]})
    match = build_match(frames, duration=120.0, half=60.0)
    tf = extract_team_frames(match, cfg)["home"]
    first = [f.outfield for f in tf if f.t < 60]
    second = [f.outfield for f in tf if f.t >= 60]
    assert classify_frames(first, cfg)[0] == "3-5-2"
    assert classify_frames(second, cfg)[0] == "3-5-2"
    # the normalised block sits at the same depth in both halves
    assert abs(np.mean([f[:, 0].mean() for f in first])
               - np.mean([f[:, 0].mean() for f in second])) < 1.0


def test_unlabelled_keeper_dropped_by_position(cfg):
    rng = np.random.default_rng(42)
    slots = build_template("4-4-2", cfg).slots
    pts = shape_points(slots, (50.0, 34.0), rng, noise=0.5)
    players = [player(i, "home", x, y) for i, (x, y) in enumerate(pts)]
    players.append(player(99, "home", 4.0, 34.0))  # keeper, no role label (like TeamTrack)
    match = build_match([{"t": 0.0, "players": players}], duration=10.0)
    tf = extract_team_frames(match, cfg)["home"][0]
    assert len(tf.outfield) == 10
    assert tf.outfield[:, 0].min() > 20.0


def test_futsal_config_needs_no_code_change():
    c = copy.deepcopy(load_config())
    c["pitch"] = {"length_m": 40.0, "width_m": 20.0}
    c["formations"].update({
        "outfield_players": 4, "templates": ["2-2", "1-2-1", "3-1", "4-0"], "depth_m": 12.0,
        "line_width_m": {1: 0.0, 2: 10.0, 3: 14.0, 4: 16.0}, "overrides": {},
    })
    c["tactics"]["min_players"] = 3
    fcfg = TacticsConfig.from_config(c)
    rng = np.random.default_rng(42)
    for t in build_templates(fcfg):
        frames = [shape_points(t.slots, (18.0, 10.0), rng, noise=0.5) for _ in range(20)]
        assert classify_frames(frames, fcfg)[0] == t.name
