"""Team classifier, tracker, background detector and the perception pipeline on synthetic video
(TeamTrack itself is gitignored, so these never need the real footage)."""

from __future__ import annotations

import copy
import json

import cv2
import numpy as np
import pytest

from gaffer.config import load_config
from gaffer.perception.detector import (
    BackgroundDetector,
    BackgroundSettings,
    Detections,
    DetectorError,
)
from gaffer.perception.pipeline import PipelineError, TooFewPlayersError, run, run_window
from gaffer.perception.pitch import CalibrationError, HomographyMapper, PitchModel
from gaffer.perception.team_classifier import (
    TeamSettings,
    TrackVoter,
    fit_team_model,
    hex_to_feature,
    resolve_others_frame,
    shirt_feature,
)
from gaffer.perception.tracker import PlayerTracker, TrackerSettings
from gaffer.perception.video import VideoError

PX_PER_M = 12.0
H_P2I = np.array([[PX_PER_M, 0, 70], [0, -PX_PER_M, 860], [0, 0, 1]], dtype=float)
MAPPER = HomographyMapper(np.linalg.inv(H_P2I))
MODEL = PitchModel(105, 68)
GRASS = (50, 130, 60)
WHITE, BLUE, BLACK, YELLOW = (240, 240, 240), (120, 40, 20), (25, 25, 25), (0, 220, 240)


def team_settings(view: str = "top") -> TeamSettings:
    return TeamSettings.from_config(load_config(), view)


# --------------------------------------------------------------------------- team classifier


def test_shirt_feature_ignores_grass() -> None:
    img = np.full((60, 60, 3), GRASS, np.uint8)
    cv2.circle(img, (30, 30), 6, WHITE, -1)
    s = team_settings()
    f = shirt_feature(img, np.array([15, 15, 30, 30]), s)
    np.testing.assert_allclose(f, hex_to_feature("#f0f0f0", s.l_weight), atol=1.5)
    assert shirt_feature(np.full((60, 60, 3), GRASS, np.uint8), np.array([15, 15, 30, 30]),
                         s) is None


def test_fit_team_model_names_teams_and_isolates_others() -> None:
    s = team_settings()
    rng = np.random.default_rng(42)
    white = hex_to_feature("#e6e6e6", s.l_weight) + rng.normal(0, 1.5, (200, 3))
    blue = hex_to_feature("#203c90", s.l_weight) + rng.normal(0, 1.5, (180, 3))
    ref = hex_to_feature("#202020", s.l_weight) + rng.normal(0, 1.0, (20, 3))
    keeper = hex_to_feature("#f0dc10", s.l_weight) + rng.normal(0, 1.0, (10, 3))
    m = fit_team_model(np.concatenate([blue, ref, white, keeper]),
                       {"home": "#f0f0f0", "away": "#2848a0"}, s)
    lab, _ = m.classify(np.concatenate([white[:20], blue[:20], ref[:10], keeper[:10]]))
    # teams named by their hints (a few noisy team crops fall outside the gate: the per-track
    # vote absorbs those), other colours always isolated
    assert (lab[:20] == 0).mean() >= 0.9 and (lab[20:40] == 1).mean() >= 0.9
    assert not (lab[:40] == 1 - np.repeat([0, 1], 20)).any()  # never the wrong team
    assert (lab[40:] == 2).all()
    assert 0.05 < m.outlier_share < 0.15


def test_track_voter_is_unknown_until_settled() -> None:
    v = TrackVoter(team_settings())
    assert v.add(7, 0) == ("unknown", 0.0)
    assert v.add(7, None)[0] == "unknown"  # no usable crop: no vote
    assert v.add(7, 0)[0] == "unknown"  # 2 votes < min_votes 3
    assert v.add(7, 1) == ("home", pytest.approx(2 / 3))  # 2 of 3 >= 0.6: settled
    assert v.add(7, 0) == ("home", pytest.approx(0.75))
    for _ in range(3):
        v.add(8, 0)
        v.add(8, 1)
    assert v.add(8, 2)[0] == "unknown"  # no label holds 60 %


def test_keepers_go_to_the_team_defending_their_half() -> None:
    s = team_settings()
    items = [(0, np.array([3.0, 34.0]), np.array([4.0, 33.0]), 400),  # left goal, long track
             (1, np.array([2.0, 30.0]), np.array([2.5, 31.0]), 12),   # left, short: not him
             (4, np.array([-0.8, 39.0]), np.array([-0.9, 39.0]), 900),  # behind the goal line
             (2, np.array([100.0, 36.0]), np.array([101.0, 35.0]), 50),  # right goal
             (3, np.array([50.0, 34.0]), np.array([52.0, 30.0]), 500)]  # midfield: referee
    out = resolve_others_frame(items, 105, 68, "away", s)
    assert out[0] == ("away", "goalkeeper") and out[1] == ("referee", "outfield")
    assert out[4] == ("referee", "outfield")  # spare balls / staff behind the goal
    assert out[2] == ("home", "goalkeeper") and out[3] == ("referee", "outfield")


# --------------------------------------------------------------------------- tracker


def test_enlarged_matching_keeps_ids_through_large_motion() -> None:
    cfg = load_config()
    s = TrackerSettings.from_config(cfg, "top")
    tight = TrackerSettings(**{**s.__dict__, "match_scale_hz": 0.0, "min_match_scale": 1.0})

    def ids_over_time(settings: TrackerSettings) -> set[tuple[int, int]]:
        trk = PlayerTracker(settings, 2.0)
        seen = set()
        for k in range(8):  # two players running 90 px (3 box widths) per sample
            boxes = np.array([[100 + 90 * k, 100, 30, 30], [100 + 90 * k, 500, 30, 30]], float)
            ids = trk.update(Detections(boxes, np.ones(2), np.zeros(2, int)))
            if k >= 1:
                seen |= {(i, int(t)) for i, t in enumerate(ids)}
        return seen

    stable = ids_over_time(s)
    assert len(stable) == 2  # one id per player for the whole run
    # unenlarged boxes never overlap between samples: no track is ever confirmed
    assert all(t < 0 for _, t in ids_over_time(tight))


# --------------------------------------------------------------------------- background detector


def test_background_detector_finds_a_moving_person() -> None:
    s = BackgroundSettings(history_s=15, var_threshold=16, detect_shadows=True, open_px=3,
                           close_w_px=3, close_h_px=9, player_height_m=1.75,
                           player_width_m=0.6, min_height_frac=0.55, max_height_frac=2.2,
                           min_fill=0.15, split_factor=1.7, pad_top_m=2.5)
    roi = {"margin_goal_m": 1.0, "margin_touch_m": 1.0, "corner_exclusion_m": 0.0,
           "goal_exclusion_m": 0.0}
    det = BackgroundDetector(s, MODEL, roi, fps=2.0)
    for k in range(12):
        img = np.full((900, 1400, 3), GRASS, np.uint8)
        x = 400 + 25 * k
        cv2.rectangle(img, (x, 400), (x + 8, 421), WHITE, -1)  # ~0.7 x 1.75 m at 12 px/m
        d = det.detect(img, MAPPER)
    assert len(d) == 1
    bx, by, bw, bh = d.boxes[0]
    assert abs(bx + bw / 2 - (x + 4)) < 3 and abs(by + bh - 422) < 3


# --------------------------------------------------------------------------- pipeline


@pytest.fixture
def synthetic_match(tmp_path):
    """A 6 s top-down video (10 white + 10 blue players, a black referee, a yellow keeper in
    front of the left goal, a static white object behind it) with its own calibration, and a
    config pointing at it."""
    cfg = copy.deepcopy(load_config())
    cal = {"view": "side", "method": "homography", "source": "synthetic", "frame_index": 0,
           "image_size": [1400, 900], "length_m": 105.0, "width_m": 68.0,
           "params": {"H_image_to_pitch": np.linalg.inv(H_P2I).tolist()}, "landmarks": {},
           "errors": {"held_out_mean_m": 0.1}, "meta": {}}
    (tmp_path / "synth.json").write_text(json.dumps(cal), encoding="utf-8")
    cfg["calibration"]["dir"] = str(tmp_path)
    cfg["teamtrack"]["views"]["side"]["calibration"] = "synth"
    cfg["detector"]["views"]["side"]["method"] = "classical"  # top-down synthetic blobs
    cfg["detector"]["classical"]["scale"] = 1.0
    cfg["perception"]["foot_point"]["side"] = "centre"
    cfg["perception"]["static_object"]["min_s"] = 3.0  # the clip is only 6 s long
    rng = np.random.default_rng(42)
    home = np.c_[rng.uniform(15, 48, 10), rng.uniform(8, 60, 10)]
    away = np.c_[rng.uniform(57, 90, 10), rng.uniform(8, 60, 10)]
    path = tmp_path / "match.avi"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (1400, 900))
    for k in range(60):
        img = np.full((900, 1400, 3), GRASS, np.uint8)
        drift = np.array([0.1 * k, 0.05 * k])
        people = [(p + drift, WHITE) for p in home] + [(p - drift, BLUE) for p in away]
        sway = 0.5 * np.array([np.sin(k / 3), np.cos(k / 3)])  # a keeper is never still
        people += [(np.array([52.0, 30.0]) + drift, BLACK), (np.array([4.0, 34.0]) + sway, YELLOW),
                   (np.array([-0.6, 39.0]), WHITE)]  # spare balls behind the goal: static
        for xy, col in people:
            u, v = MAPPER.to_image(xy[None])[0]
            cv2.circle(img, (int(round(u)), int(round(v))), 6, col, -1)
        vw.write(img)
    vw.release()
    return cfg, path


def test_pipeline_end_to_end_on_synthetic_video(synthetic_match, tmp_path) -> None:
    cfg, path = synthetic_match
    res = run(path, cfg=cfg, debug_video=tmp_path / "debug.mp4")
    m = res.match
    assert res.view == "side" and m.source == "video" and m.fps == 2.0
    assert len(m.frames) == 12 and m.frames[0].quality.players_detected >= 20
    last = m.frames[-1].players
    teams = [p.team for p in last if p.role == "outfield"]
    assert teams.count("home") == 10 and teams.count("away") == 10
    gk = [p for p in last if p.role == "goalkeeper"]
    assert len(gk) == 1 and gk[0].team == "home" and gk[0].x < 8  # home defends the left goal
    assert teams.count("referee") == 1
    assert all(p.x > -0.3 for p in last)  # the static object behind the goal is dropped
    assert m.teams.home.attacking_direction_first_half == "right"
    assert (tmp_path / "debug.mp4").stat().st_size > 10_000
    # Phase 3 entry point: a window at a higher rate, reusing the learnt team colours
    w = run_window(path, 2.0, 4.0, 5.0, cfg=cfg, team_model=res.team_model,
                   directions={"home": "right", "away": "left"})
    assert w.fps == 5.0 and len(w.frames) == 10 and 2.0 <= w.frames[0].t < w.frames[-1].t < 4.0


def test_pipeline_errors(synthetic_match, tmp_path) -> None:
    cfg, path = synthetic_match
    with pytest.raises(VideoError):
        run(tmp_path / "missing.mp4", cfg=cfg)
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video" * 100)
    with pytest.raises(VideoError, match="could not open"):
        run(junk, cfg=cfg)
    no_weights = copy.deepcopy(cfg)
    no_weights["detector"]["views"]["side"]["method"] = "tiled_yolox"
    no_weights["detector"]["file"] = str(tmp_path / "missing.onnx")
    with pytest.raises(DetectorError, match="Missing detector weights"):
        run(path, cfg=no_weights)
    with pytest.raises(PipelineError, match="integer multiple"):
        run(path, cfg=cfg, fps=2.0, track_fps=5.0)
    small = tmp_path / "small.avi"
    vw = cv2.VideoWriter(str(small), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (320, 240))
    for _ in range(10):
        vw.write(np.full((240, 320, 3), GRASS, np.uint8))
    vw.release()
    with pytest.raises(CalibrationError, match="No calibration matches"):
        run(small, cfg=cfg)
    empty = tmp_path / "empty.avi"
    vw = cv2.VideoWriter(str(empty), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (1400, 900))
    for _ in range(10):
        vw.write(np.full((900, 1400, 3), GRASS, np.uint8))
    vw.release()
    with pytest.raises(TooFewPlayersError):
        run(empty, cfg=cfg)


def test_tracks_living_beyond_a_touchline_are_officials() -> None:
    from gaffer.perception.pipeline import official_tracks

    rule = {"outside_m": 0.0, "min_share": 0.75}
    rng = np.random.default_rng(42)
    linesman = [np.array([x, -0.6 + rng.normal(0, 0.1)]) for x in np.linspace(10, 50, 80)]
    throw_in = [np.array([30.0, 20.0])] * 70 + [np.array([30.0, -0.5])] * 10  # 12 % outside
    far_side = [np.array([x, 68.7]) for x in np.linspace(60, 90, 40)]
    out = official_tracks({1: linesman, 2: throw_in, 3: far_side}, 68.0, rule)
    assert out == {1, 3}
    assert official_tracks({1: linesman}, 68.0, {"outside_m": 0.0, "min_share": 2.0}) == set()
