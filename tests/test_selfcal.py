"""Per-video self-calibration (perception/selfcal.py) on generated frames: grass and shadow model,
shadow-free detection, static objects, pitch mask, local scale, crops without painted lines."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from gaffer.config import ConfigError, load_config, with_overrides
from gaffer.evaluation import match_distance
from gaffer.perception.detector import ClassicalBlobDetector, ClassicalSettings, painted_lines_mask
from gaffer.perception.pitch import HomographyMapper, PitchModel
from gaffer.perception.selfcal import (
    SelfCalSettings,
    estimate_grass,
    inside_pitch,
    local_px_per_m,
    static_detections,
)
from gaffer.perception.team_classifier import TeamSettings, hex_to_feature, shirt_feature

PX_PER_M = 12.0
H_P2I = np.array([[PX_PER_M, 0, 70], [0, -PX_PER_M, 860], [0, 0, 1]], dtype=float)
MAPPER = HomographyMapper(np.linalg.inv(H_P2I))
MODEL = PitchModel(105, 68)
GRASS, GRASS_DARK = (50, 130, 60), (45, 118, 55)  # mowing stripes (BGR)
SHADOW = (20, 50, 15)  # sky-lit turf: darker, bluer, more saturated than sunlit grass
RED, WHITE, NAVY, BLACK = (40, 40, 220), (240, 240, 240), (120, 40, 20), (20, 20, 20)
ROI = {"margin_goal_m": 1.0, "margin_touch_m": 1.0, "corner_exclusion_m": 1.5,
       "goal_exclusion_m": 0.3}
SETTINGS = ClassicalSettings(scale=1.0, bg_downscale=8, bg_median_k=5,
                             lab_weights=(0.5, 1.0, 1.0), diff_threshold=20.0, line_width_m=0.4,
                             line_open_m=0.4, max_inside_lines=0.97, open_px=3, close_px=5,
                             min_area_m2=0.12, max_area_m2=6.0,
                             single_area_m2=0.55, split_factor=1.7, box_size_m=1.2)


def selfcal(**on: bool) -> SelfCalSettings:
    c = load_config()["perception"]["self_calibration"]
    return SelfCalSettings(grass=dict(c["grass"]), shadow=dict(c["shadow"]),
                           static=dict(c["static"]), **on)


def px(xy: tuple[float, float]) -> tuple[int, int]:
    u, v = MAPPER.to_image(np.array([xy], float))[0]
    return int(round(u)), int(round(v))


def pitch_frame() -> np.ndarray:
    img = np.zeros((900, 1400, 3), np.uint8)
    img[:] = GRASS
    for x in range(0, 1400, 120):
        img[:, x:x + 60] = GRASS_DARK
    for poly in MODEL.lines(0.25).values():
        uv = np.round(MAPPER.to_image(poly)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [uv], False, (235, 235, 235), 2)
    return img


def sunny_frame() -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Players with long shadows (feet towards +x) and a light-pole shadow across the pitch."""
    img = pitch_frame()
    cv2.line(img, px((20, 55)), px((32, 52)), SHADOW, 5)  # pole shadow, 0.4 m wide
    players = [(30.0, 20.0), (45.0, 40.0), (70.0, 25.0), (85.0, 50.0)]
    for i, (x, y) in enumerate(players):
        cv2.ellipse(img, px((x + 1.4, y)), (14, 4), 0, 0, 360, SHADOW, -1)  # 2.3 m shadow
        cv2.circle(img, px((x, y)), 5, RED if i % 2 else WHITE, -1)
    return img, players


def test_grass_model_learns_turf_and_its_shadows() -> None:
    img, _ = sunny_frame()
    sc = selfcal(grass_model=True, shadows=True)
    g = estimate_grass(img, MAPPER, MODEL, sc.grass, sc.shadow)
    hsv = cv2.cvtColor(np.array([[GRASS, GRASS_DARK, SHADOW, RED, WHITE, NAVY, BLACK]],
                                np.uint8), cv2.COLOR_BGR2HSV)
    assert g.mask(hsv, shadows=True)[0].tolist() == [True, True, True, False, False, False,
                                                       False]
    assert g.mask(hsv, shadows=False)[0].tolist()[:3] == [True, True, False]


def test_shadows_switch_removes_shadow_detections_and_centres_on_the_body() -> None:
    img, players = sunny_frame()
    gt = np.array(players)
    plain = ClassicalBlobDetector(SETTINGS, MODEL, ROI)
    d0 = plain.detect(img, MAPPER)
    xy0 = MAPPER.to_pitch(d0.boxes[:, :2] + d0.boxes[:, 2:] / 2)
    assert len(d0) > len(players)  # pole shadow and player shadows become "players"
    sc = selfcal(grass_model=True, shadows=True, local_scale=True)
    det = ClassicalBlobDetector(SETTINGS, MODEL, ROI)
    det.configure(sc, estimate_grass(img, MAPPER, MODEL, sc.grass, sc.shadow))
    d1 = det.detect(img, MAPPER)
    xy1 = MAPPER.to_pitch(d1.boxes[:, :2] + d1.boxes[:, 2:] / 2)
    m = match_distance(gt, xy1, 0.4)
    assert m.tp == len(players) and not m.extra  # one detection per player, on the body
    # without the shadow model, players' own shadows are extra detections next to them
    near = np.linalg.norm(xy0[:, None] - gt[None], axis=2).min(axis=1)
    assert ((near > 0.6) & (near < 3.0)).sum() >= 2


def test_thin_long_blobs_are_rejected_with_the_shadow_switch() -> None:
    img = pitch_frame()
    cv2.line(img, px((40, 30)), px((52, 30)), (10, 10, 10), 4)  # a fence pole lying on grass
    cv2.circle(img, px((60, 20)), 5, RED, -1)
    det = ClassicalBlobDetector(SETTINGS, MODEL, ROI)
    sc = selfcal(shadows=True)
    det.configure(sc, None)  # thin-blob test even without a grass model
    xy = MAPPER.to_pitch(det.detect(img, MAPPER).boxes[:, :2] + 7.2)
    assert len(xy) == 1 and np.linalg.norm(xy[0] - [60, 20]) < 0.5


def test_static_detections_flag_objects_not_players() -> None:
    rng = np.random.default_rng(42)
    n = 60
    times = list(np.arange(n) * 0.5)
    pts = []
    for k in range(n):
        p = [[10 + rng.normal(0, 0.05), 10 + rng.normal(0, 0.05)],  # a ball left on the grass
             [20 + 0.3 * k, 30.0]]  # a running player
        if k < 20:
            p.append([50.0, 40.0])  # a player standing still for a third of the run
        pts.append(np.array(p))
    flags = static_detections(pts, times, {"radius_m": 0.5, "min_share": 0.8,
                                           "min_frames": 30, "min_span_s": 20.0})
    assert all(f[0] for f in flags) and not any(f[1] for f in flags)
    assert not any(f[2] for f in flags[:20])
    short = static_detections(pts[:10], times[:10], {"min_frames": 30, "min_span_s": 20.0})
    assert not any(f.any() for f in short)


def test_pitch_mask_and_local_scale() -> None:
    xy = np.array([[50, 30], [-1.0, 30], [-2.0, 30], [50, 69.4], [50, 70.0]])
    assert inside_pitch(xy, 105, 68, 1.5).tolist() == [True, True, False, True, False]
    np.testing.assert_allclose(local_px_per_m(MAPPER, np.array([[300.0, 400.0]])), [12.0])
    tilted = HomographyMapper(np.linalg.inv(np.array([[12, 2, 70], [0, -8, 860],
                                                      [0, -0.002, 1]], float)))
    s = local_px_per_m(tilted, tilted.to_image(np.array([[50, 5], [50, 60]], float)))
    assert s[0] != pytest.approx(s[1], rel=0.05)  # the far side is smaller in the image


def test_shirt_crop_leaves_painted_lines_out() -> None:
    img = pitch_frame()
    u, v = px((30, 0.0))  # a navy shirt standing on the near touchline
    cv2.circle(img, (u, v), 6, NAVY, -1)
    cv2.line(img, (u - 8, v), (u + 8, v), (250, 250, 250), 3)  # the paint shows through
    ts = TeamSettings.from_config(load_config(), "top")
    box = np.array([u - 7, v - 7, 14, 14], float)
    lines = painted_lines_mask(MAPPER, MODEL, img.shape[:2], 4)
    navy = hex_to_feature("#{:02x}{:02x}{:02x}".format(*NAVY[::-1]), ts.l_weight)
    f0 = shirt_feature(img, box, ts)
    f1 = shirt_feature(img, box, ts, exclude=lines)
    assert np.linalg.norm(f1 - navy) < np.linalg.norm(f0 - navy) - 5


def test_config_overrides_are_typed_and_checked() -> None:
    cfg = load_config()
    c2 = with_overrides(cfg, ["perception.self_calibration.static_objects=true",
                              "perception.self_calibration.static.min_share=0.7"])
    sc = c2["perception"]["self_calibration"]
    assert sc["static_objects"] is True and sc["static"]["min_share"] == 0.7
    assert cfg["perception"]["self_calibration"]["static"]["min_share"] != 0.7 or \
        cfg is not c2  # the cached config is never changed
    with pytest.raises(ConfigError):
        with_overrides(cfg, ["perception.self_calibration.no_such_switch=true"])
    assert SelfCalSettings.from_config(c2, "side").static_objects is False  # top view only
