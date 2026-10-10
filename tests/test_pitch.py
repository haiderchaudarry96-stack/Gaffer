"""Pitch geometry and calibration: a synthetic pitch drawn with a known homography must be
recovered (landmarks, pitch size, mapping), and the side-view mappers must round-trip."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    HomographyMapper,
    PitchModel,
    SnapSettings,
    fit_homography,
    fit_pitch_size,
    leave_one_out,
    line_alignment_error,
    line_mask,
    snap_two_pass,
)
from gaffer.perception.undistort import FisheyeMapper, SectionedHomographyMapper, fit_sectioned

# A mild perspective view of the pitch: pitch metres -> pixels
H_PITCH_TO_IMG = np.array([[18.0, 1.2, 150.0], [0.4, -17.0, 1350.0], [0.0004, 0.0009, 1.0]])


def render(model: PitchModel, H: np.ndarray, size: tuple[int, int] = (2300, 1500)) -> np.ndarray:
    """Green image with the model's white lines (and penalty spots) drawn through H."""
    img = np.zeros((size[1], size[0], 3), np.uint8)
    img[:] = (40, 120, 50)
    m = HomographyMapper(np.linalg.inv(H))
    for poly in model.lines(0.2).values():
        uv = np.round(m.to_image(poly)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [uv], False, (235, 235, 235), 4, cv2.LINE_AA)
    lm = model.landmarks()
    for spot in ("centre_spot", "pen_L", "pen_R"):
        u, v = m.to_image(np.array([lm[spot]]))[0]
        cv2.circle(img, (int(round(u)), int(round(v))), 4, (235, 235, 235), -1)
    return img


@pytest.fixture(scope="module")
def scene() -> dict:
    model = PitchModel(100.0, 64.0)  # deliberately not 105 x 68
    img = render(model, H_PITCH_TO_IMG)
    truth = HomographyMapper(np.linalg.inv(H_PITCH_TO_IMG))
    lm = model.landmarks()
    rng = np.random.default_rng(42)
    exact = {n: truth.to_image(np.array([xy]))[0] for n, xy in lm.items()}
    approx = {n: (uv + rng.uniform(-6, 6, 2)).tolist() for n, uv in exact.items()}
    return {"model": model, "img": img, "truth": truth, "exact": exact, "approx": approx}


def test_landmark_lines_exist() -> None:
    model = PitchModel(105, 68)
    lines = set(model.lines())
    for name in model.landmarks():
        for ln in PitchModel.landmark_lines(name):
            assert ln in lines, (name, ln)


def test_fixed_markings_do_not_depend_on_pitch_size() -> None:
    for L, W in ((105, 68), (100, 64)):
        lm = PitchModel(L, W).landmarks()
        assert lm["pa_L_goal_far"][1] - lm["pa_L_goal_near"][1] == pytest.approx(40.32)
        assert lm["pa_L_front_near"][0] == pytest.approx(16.5)
        assert lm["pa_R_front_near"][0] == pytest.approx(L - 16.5)
        assert lm["pen_R"] == pytest.approx((L - 11.0, W / 2))


def test_line_mask_removes_speckle() -> None:
    img = np.zeros((200, 200, 3), np.uint8)
    img[:] = (40, 120, 50)
    cv2.line(img, (10, 100), (190, 100), (240, 240, 240), 3)
    img[30, 30] = img[60, 150] = (240, 240, 240)  # isolated bright pixels
    mask = line_mask(img, kernel_px=15, threshold=30, min_component_px=20)
    assert mask[100, 100] == 255
    assert mask[30, 30] == 0 and mask[60, 150] == 0


def test_snap_fit_and_size_recovery(scene: dict) -> None:
    model, img = scene["model"], scene["img"]
    mask = line_mask(img, kernel_px=21, threshold=30, min_component_px=100)
    raw = line_mask(img, kernel_px=21, threshold=30)
    s = SnapSettings(radius_px=40, band_px=10, inlier_px=3.0, min_pixels=20, spot_radius_px=10,
                     max_move_px=20)

    def fit(i: np.ndarray, w: np.ndarray) -> HomographyMapper:
        return HomographyMapper(fit_homography(i, w)[0])

    # first pass uses the wrong default size, as calibrate.py does
    snapped = snap_two_pass(mask, raw, scene["approx"], {}, s, PitchModel(105, 68), fit)
    errs = [np.linalg.norm(np.array(snapped[n]["image"]) - scene["exact"][n])
            for n in snapped if snapped[n]["snapped"]]
    assert sum(r["snapped"] for r in snapped.values()) >= 29
    assert np.median(errs) < 1.0

    names = [n for n, r in snapped.items() if r["snapped"]]
    uv = np.array([snapped[n]["image"] for n in names])
    L, W, _, rms = fit_pitch_size(names, uv, 105.0, 68.0, model.mk)
    assert L == pytest.approx(100.0, abs=0.3) and W == pytest.approx(64.0, abs=0.3)
    assert rms < 1.5

    world = np.array([model.landmarks()[n] for n in names])
    mapper = fit(uv, world)
    loo = leave_one_out(names, uv, world, fit)
    assert np.mean(list(loo.values())) < 0.1
    le = line_alignment_error(mapper, mask, model, step_m=1.0, max_search_m=2.0)
    assert le["median_m"] < 0.1 and le["not_found_fraction"] < 0.05


def test_fit_homography_needs_four_points() -> None:
    with pytest.raises(CalibrationError):
        fit_homography(np.zeros((3, 2)), np.zeros((3, 2)))


def test_sectioned_mapper_round_trip(scene: dict) -> None:
    lm = scene["model"].landmarks()
    names = list(lm)
    uv = np.array([scene["exact"][n] for n in names])
    world = np.array([lm[n] for n in names])
    m = fit_sectioned(uv, world, [float(np.median(uv[:, 0]))], margin_px=100)
    np.testing.assert_allclose(m.to_pitch(uv), world, atol=1e-3)
    np.testing.assert_allclose(m.to_image(world), uv, atol=1e-2)
    single = SectionedHomographyMapper([], [np.linalg.inv(np.linalg.inv(H_PITCH_TO_IMG))])
    assert single.to_pitch(uv).shape == uv.shape


def test_fisheye_mapper_round_trip() -> None:
    K = np.array([[900.0, 0, 3200], [0, 600.0, 500], [0, 0, 1]])
    R0 = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
    tilt = cv2.Rodrigues(np.array([0.25, 0.0, 0.0]))[0]
    R = tilt @ R0
    C = np.array([52.5, -15.0, 6.0])
    m = FisheyeMapper(K, np.array([0.05, -0.01, 0.0, 0.0]), cv2.Rodrigues(R)[0], -R @ C)
    xy = np.array([[30.0, 10.0], [52.5, 34.0], [80.0, 60.0], [10.0, 50.0]])
    np.testing.assert_allclose(m.to_pitch(m.to_image(xy)), xy, atol=1e-3)


def test_calibration_file_round_trip(tmp_path) -> None:
    c = Calibration(view="top", method="homography", source="x.mp4", frame_index=0,
                    image_size=(10, 10), length_m=105, width_m=68,
                    params={"H_image_to_pitch": np.eye(3)}, landmarks={}, errors={}, meta={})
    p = c.save(tmp_path / "top.json")
    back = Calibration.load(p)
    assert back.image_size == (10, 10)
    np.testing.assert_allclose(back.mapper().to_pitch(np.array([[3.0, 4.0]])), [[3.0, 4.0]])
    with pytest.raises(CalibrationError, match="No calibration file"):
        Calibration.load(tmp_path / "missing.json")
