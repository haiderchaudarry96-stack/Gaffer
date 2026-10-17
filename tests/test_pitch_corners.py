"""4-corner homography and OpenCV pitch auto-detect (Phase 4) on generated top-down views."""

from __future__ import annotations

import numpy as np
import pytest

from gaffer.config import load_config
from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    detect_pitch_corners,
    draw_corner_overlay,
    four_corner_calibration,
    four_corner_homography,
    image_corners,
    order_corners,
    render_pitch_view,
)

L, W = 105.0, 68.0
SIZE = (1280, 720)
STRAIGHT = [[140, 90], [1140, 92], [1138, 640], [142, 638]]


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_four_corner_maps_corners_onto_the_pitch() -> None:
    fc = four_corner_homography(STRAIGHT, SIZE, L, W)
    xy = fc.mapper().to_pitch(np.array(STRAIGHT, float))
    assert np.allclose(xy, [[0, W], [L, W], [L, 0], [0, 0]], atol=1e-6)
    assert not fc.rotated and fc.opposite_edge_ratio > 0.99
    # the centre of the quad is near the centre spot
    mid = fc.mapper().to_pitch(np.array([[640, 365]], float))[0]
    assert np.allclose(mid, [L / 2, W / 2], atol=1.0)


def test_four_corner_pitch_running_up_down_is_rotated() -> None:
    pts = [[400, 40], [840, 40], [840, 700], [400, 700]]  # long edges vertical
    fc = four_corner_homography(pts, SIZE, L, W)
    assert fc.rotated
    xy = fc.mapper().to_pitch(np.array(pts, float))
    # long image edge TL-BL maps along the pitch length
    assert abs(np.linalg.norm(xy[0] - xy[3]) - L) < 1e-6
    assert abs(np.linalg.norm(xy[0] - xy[1]) - W) < 1e-6


@pytest.mark.parametrize("pts, words", [
    ([[140, 90], [1140, 92], [1138, 640]], "Exactly 4"),
    ([[140, 90], [1138, 640], [1140, 92], [142, 638]], "cross"),
    ([[142, 638], [1138, 640], [1140, 92], [140, 90]], "wrong order"),
    ([[600, 300], [640, 300], [640, 330], [600, 330]], "covers only"),
    ([[380, 250], [900, 250], [1250, 700], [30, 700]], "too steep"),
    ([[140, 90], [5000, 92], [1138, 640], [142, 638]], "far outside"),
])
def test_four_corner_refusals_are_coach_readable(pts, words) -> None:
    with pytest.raises(CalibrationError, match=words):
        four_corner_homography(pts, SIZE, L, W)


def test_four_corner_calibration_round_trips(tmp_path) -> None:
    fc = four_corner_homography(STRAIGHT, SIZE, L, W)
    cal = four_corner_calibration(fc, SIZE, L, W, "upload.mp4", 30, "coach")
    p = cal.save(tmp_path / "top.json")
    back = Calibration.load(p)
    assert back.method == "homography" and back.frame_index == 30
    assert back.image_size == SIZE and len(back.landmarks) == 4
    assert np.allclose(back.mapper().to_pitch(np.array(STRAIGHT, float)),
                       fc.mapper().to_pitch(np.array(STRAIGHT, float)))


def test_image_corners_and_order() -> None:
    fc = four_corner_homography(STRAIGHT, SIZE, L, W)
    assert np.allclose(image_corners(fc.mapper(), L, W), STRAIGHT, atol=1e-6)
    shuffled = np.array(STRAIGHT)[[2, 0, 3, 1]]
    assert np.allclose(order_corners(shuffled), STRAIGHT)


@pytest.mark.parametrize("corners", [
    STRAIGHT,
    [[180, 110], [1100, 100], [1160, 650], [120, 640]],  # slight perspective
    [[250, 60], [1050, 60], [1050, 580], [250, 580]],
])
def test_autodetect_finds_the_corners_of_a_top_down_view(cfg, corners) -> None:
    players = [(20 + 6 * i, 10 + (i % 6) * 9, (240, 240, 240)) for i in range(11)]
    img = render_pitch_view(SIZE, corners, players=players)
    d = detect_pitch_corners(img, cfg)
    assert d.found and d.accepted, d.summary()
    assert np.abs(d.corners - order_corners(corners)).max() < 4.0
    assert d.snapped_edges == 4  # run-off grass -> moved onto the white boundary lines
    assert d.line_error_m is not None and d.line_error_m < 0.3


def test_autodetect_ignores_a_straight_line_outside_the_goal_line(cfg) -> None:
    """Real drone footage (TeamTrack, 17 Oct): the edge of the artificial turf 6-7 m behind one
    goal line is as straight and bright as the goal line itself. The outermost line used to
    win (all 180 test frames wrong by 6.8-14.7 m); the markings inside the pitch now decide."""
    import cv2

    img = render_pitch_view(SIZE, STRAIGHT, runoff_m=9.0)
    targets = np.array([[0.0, W], [L, W], [L, 0.0], [0.0, 0.0]], np.float32)
    H = cv2.getPerspectiveTransform(targets, np.array(STRAIGHT, np.float32))
    ends = cv2.perspectiveTransform(np.array([[[L + 6.5, -9.0]], [[L + 6.5, W + 9.0]]],
                                             np.float32), H).reshape(2, 2)
    cv2.line(img, tuple(int(v) for v in ends[0]), tuple(int(v) for v in ends[1]),
             (235, 240, 238), 2, cv2.LINE_AA)
    d = detect_pitch_corners(img, cfg)
    assert d.found and d.accepted, d.summary()
    assert np.abs(d.corners - order_corners(STRAIGHT)).max() < 4.0, d.summary()


def test_autodetect_refuses_a_tilted_view(cfg) -> None:
    img = render_pitch_view(SIZE, [[380, 250], [900, 250], [1250, 700], [30, 700]])
    d = detect_pitch_corners(img, cfg)
    assert not d.accepted and d.confidence == 0.0
    assert any("tilted" in p for p in d.problems)


def test_autodetect_refuses_a_cropped_view(cfg) -> None:
    img = render_pitch_view(SIZE, [[-100, -60], [1380, -50], [1380, 780], [-100, 770]])
    d = detect_pitch_corners(img, cfg)
    assert not d.accepted
    assert any("cut off" in p for p in d.problems)


def test_autodetect_fails_cleanly_without_a_pitch(cfg) -> None:
    rng = np.random.default_rng(42)
    img = rng.integers(0, 255, (SIZE[1], SIZE[0], 3), dtype=np.uint8)
    d = detect_pitch_corners(img, cfg)
    assert not d.accepted and d.confidence < 0.3 and d.problems


def test_overlay_is_drawn(cfg) -> None:
    img = render_pitch_view(SIZE, STRAIGHT)
    out = draw_corner_overlay(img, STRAIGHT, L, W, "Is this the pitch?", max_width_px=640)
    assert out.shape == (360, 640, 3)
    assert not np.array_equal(out[:20], img[:20:2, ::2][:20])  # title bar drawn
