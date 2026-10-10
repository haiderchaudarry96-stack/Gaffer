"""Perception building blocks on synthetic inputs (TeamTrack itself is gitignored)."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from gaffer.evaluation import isolated, match_distance, match_iou, prf
from gaffer.perception.detector import (
    ClassicalBlobDetector,
    ClassicalSettings,
    pitch_roi,
)
from gaffer.perception.drift import DriftSettings, alignment_image, estimate_alignment
from gaffer.perception.matchstate import (
    ObservedFrame,
    ObservedPlayer,
    assemble,
    infer_attacking_direction,
    possession,
)
from gaffer.perception.pitch import HomographyMapper, PitchModel
from gaffer.perception.tiling import nms, tile_grid
from gaffer.perception.video import VideoError, VideoSource
from gaffer.teamtrack import DatasetError, foot_points, load_gt, write_clip_list

# pitch metres -> pixels for a 1400 x 900 image, 12 px per metre, y up
PX_PER_M = 12.0
H_P2I = np.array([[PX_PER_M, 0, 70], [0, -PX_PER_M, 860], [0, 0, 1]], dtype=float)
MAPPER = HomographyMapper(np.linalg.inv(H_P2I))
MODEL = PitchModel(105, 68)


def grass(shape=(900, 1400)) -> np.ndarray:
    img = np.zeros((*shape, 3), np.uint8)
    img[:] = (50, 130, 60)
    for x in range(0, shape[1], 120):  # mowing stripes
        img[:, x:x + 60] = (45, 118, 55)
    return img


def draw_lines(img: np.ndarray) -> None:
    for poly in MODEL.lines(0.25).values():
        uv = np.round(MAPPER.to_image(poly)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [uv], False, (235, 235, 235), 2)


# --------------------------------------------------------------------------- teamtrack


def test_load_gt_skips_empty_cells(tmp_path) -> None:
    csv = tmp_path / "D_20220220_1_0_30.csv"
    csv.write_text(
        "TeamID,0,0,0,0,BALL,BALL,BALL,BALL\n"
        "PlayerID,10,10,10,10,BALL,BALL,BALL,BALL\n"
        "Attributes,bb_height,bb_left,bb_top,bb_width,bb_height,bb_left,bb_top,bb_width\n"
        "frame,,,,,,,,\n"
        "1,30,100,200,20,10,5,6,10\n"
        "2,30,101,201,20,,,,\n", encoding="utf-8")
    gt = load_gt(csv)
    assert gt.missing_objects == 1 and gt.frames_with_missing == 1
    row = gt.boxes[(gt.boxes.frame == 0) & (gt.boxes.team == "0")].iloc[0]
    # attributes are addressed by name, frames become 0-based, PlayerID stays a string
    assert (row.bb_left, row.bb_top, row.bb_width, row.bb_height, row.player) == \
        (100, 200, 20, 30, "10")
    fp = foot_points(gt.boxes[gt.boxes.team == "0"].iloc[:1], "bottom")
    np.testing.assert_allclose(fp, [[110, 230]])


def test_load_gt_missing_file(tmp_path) -> None:
    with pytest.raises(DatasetError):
        load_gt(tmp_path / "nope.csv")


# --------------------------------------------------------------------------- video


def _write_video(path, n: int, fps: float, value: int) -> None:
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    for i in range(n):
        frame = np.full((48, 64, 3), value, np.uint8)
        cv2.putText(frame, str(i), (2, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        vw.write(frame)
    vw.release()


def test_clip_list_maps_match_time(tmp_path) -> None:
    from gaffer.teamtrack import Clip

    a, b = tmp_path / "a.avi", tmp_path / "b.avi"
    _write_video(a, 20, 10.0, 40)
    _write_video(b, 20, 10.0, 200)
    clips = [Clip("top", "a", a, a, 100.0, 102.0, 1), Clip("top", "b", b, b, 102.0, 104.0, 1)]
    lst = write_clip_list(clips, tmp_path / "m.clips.json")
    assert json.loads(lst.read_text())["clips"][1]["start_s"] == 102.0
    src = VideoSource(lst)
    assert (src.start_s, src.end_s) == (100.0, 104.0)
    assert src.locate(101.0) == (0, 10) and src.locate(103.62) == (1, 16)
    assert src.locate(99.0) is None
    times = src.sample_times(2.0)
    assert times[0] == 100.0 and times[-1] == 103.5 and len(times) == 8
    got = [(ci, fi, int(f.mean() > 100)) for _, ci, fi, f in src.frames([100.5, 103.0])]
    assert got == [(0, 5, 0), (1, 10, 1)]


def test_video_errors(tmp_path) -> None:
    with pytest.raises(VideoError, match="not found"):
        VideoSource(tmp_path / "missing.mp4")
    bad = tmp_path / "x.clips.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(VideoError, match="not a valid clip list"):
        VideoSource(bad)


# --------------------------------------------------------------------------- tiling / matching


def test_tile_grid_covers_region_with_overlap() -> None:
    tiles = tile_grid(100, 50, 3000, 900, 640, 96, 3840, 2160)
    cover = np.zeros((2160, 3840), bool)
    for x, y, w, h in tiles:
        assert (w, h) == (640, 640)
        cover[y:y + h, x:x + w] = True
    assert cover[50:900, 100:3000].all()
    xs = sorted({t[0] for t in tiles})
    assert all(b - a <= 640 - 96 for a, b in zip(xs[:-1], xs[1:], strict=True))


def test_nms_merges_cross_tile_duplicates() -> None:
    boxes = np.array([[10, 10, 30, 60], [12, 11, 30, 60], [200, 10, 30, 60]], float)
    keep = nms(boxes, np.array([0.9, 0.8, 0.7]), np.zeros(3, int), 0.3, 0.45)
    assert sorted(keep.tolist()) == [0, 2]


def test_matching_iou_and_distance() -> None:
    gt = np.array([[0, 0, 10, 10], [100, 100, 10, 10], [200, 0, 10, 10]], float)
    det = np.array([[1, 1, 10, 10], [150, 150, 10, 10]], float)
    m = match_iou(gt, det, 0.5)
    assert m.pairs == [(0, 0)] and m.missed == [1, 2] and m.extra == [1]
    md = match_distance(np.array([[0, 0], [5, 0]]), np.array([[4.6, 0], [0.4, 0]]), 1.0)
    assert sorted(md.pairs) == [(0, 1), (1, 0)]
    assert prf(1, 1, 2) == {"precision": 0.5, "recall": pytest.approx(0.3333, abs=1e-4),
                            "f1": 0.4}
    assert isolated(np.array([[0, 0, 10, 10], [5, 5, 10, 10], [50, 50, 5, 5]], float)
                    ).tolist() == [False, False, True]


# --------------------------------------------------------------------------- matchstate rules


def test_possession_and_direction() -> None:
    pl = [ObservedPlayer(1, "home", 10, 10), ObservedPlayer(2, "away", 11.5, 10)]
    assert possession(pl, (10.5, 10), 2.0) == "contested"
    assert possession(pl, (8.5, 10), 2.0) == "home"
    assert possession(pl, (50, 50), 2.0) is None and possession(pl, None, 2.0) is None
    frames = []
    for t in range(5):  # home keeper near x = 103 (defends right), away keeper near x = 2
        home = [ObservedPlayer(i, "home", x, 30) for i, x in enumerate([103, 70, 60, 50])]
        away = [ObservedPlayer(10 + i, "away", x, 30) for i, x in enumerate([2, 40, 55, 65])]
        frames.append(ObservedFrame(float(t), home + away))
    assert infer_attacking_direction(frames, 105) == {"home": "left", "away": "right"}


def test_assemble_drops_off_pitch_points() -> None:
    f = ObservedFrame(10.0, [ObservedPlayer(1, "home", 50, 30), ObservedPlayer(2, "away", 120, 30)],
                      ball=(50.5, 30.0),
                      quality={"players_detected": 2, "homography_ok": True,
                               "reprojection_error_m": 0.1, "camera_cut": False})
    teams = {"home": {"name": "W", "colour": "#fff"}, "away": {"name": "B", "colour": "#00f"}}
    m = assemble("t", "annotation", 2.0, 105, 68, [f], teams, {"home": "left", "away": "right"},
                 None, "test", "", 2.0, duration_s=20.0)
    assert [p.track_id for p in m.frames[0].players] == [1]
    assert m.frames[0].possession == "home"


# --------------------------------------------------------------------------- detection / drift


ROI = {"margin_goal_m": 1.0, "margin_touch_m": 1.0, "corner_exclusion_m": 1.5,
       "goal_exclusion_m": 0.3}


def test_roi_excludes_corners_goals_and_outside() -> None:
    roi = pitch_roi(MAPPER, MODEL, shape=(900, 1400), **ROI)

    def at(x: float, y: float) -> int:
        u, v = MAPPER.to_image(np.array([[x, y]]))[0]
        return int(roi[int(round(v)), int(round(u))])

    assert at(50, 30) == 255 and at(50, -0.5) == 255
    assert at(50, -3) == 0 and at(0.5, 0.5) == 0 and at(0.1, 34) == 0 and at(3, 34) == 255


SETTINGS = ClassicalSettings(scale=1.0, bg_downscale=8, bg_median_k=5,
                             lab_weights=(0.5, 1.0, 1.0), diff_threshold=20.0, line_width_m=0.4,
                             line_open_m=0.4, max_inside_lines=0.97, open_px=3, close_px=5,
                             min_area_m2=0.12, max_area_m2=6.0,
                             single_area_m2=0.55, split_factor=1.7, box_size_m=1.2)


def test_classical_detector_finds_players_not_lines() -> None:
    img = grass()
    draw_lines(img)
    players = [(30, 20, (240, 240, 240)), (52.5, 34, (120, 40, 20)), (80, 50, (240, 240, 240)),
               (16.5, 34, (120, 40, 20)), (60, 10, (240, 240, 240)), (61.2, 10, (120, 40, 20))]
    for x, y, col in players:  # last two touch: a merged blob that must be split
        u, v = MAPPER.to_image(np.array([[x, y]]))[0]
        cv2.circle(img, (int(u), int(v)), 5, col, -1)
    det = ClassicalBlobDetector(SETTINGS, MODEL, ROI).detect(img, MAPPER)
    xy = MAPPER.to_pitch(det.boxes[:, :2] + det.boxes[:, 2:] / 2)
    m = match_distance(np.array([[x, y] for x, y, _ in players]), xy, 0.8)
    assert m.tp == len(players) and not m.extra


def test_drift_recovers_known_shift() -> None:
    ref = grass((1080, 1920))
    draw_lines(ref)
    A_true = np.array([[1, 0, 9.0], [0, 1, -6.0]])  # frame = ref shifted
    frame = cv2.warpAffine(ref, A_true, (1920, 1080), borderMode=cv2.BORDER_REPLICATE)
    # production scale (0.25): sub-pixel accurate; 0.5 on these 1-px synthetic lines is biased
    s = DriftSettings(scale=0.25, blur_sigma_px=2.0, motion="affine", iterations=100, eps=1e-5,
                      min_correlation=0.6, line_mask={"kernel_px": 15, "threshold": 30,
                                                      "max_saturation": 90})
    al = estimate_alignment(alignment_image(ref, s), alignment_image(frame, s), s, (1920, 1080))
    assert al.method == "ecc"
    # A maps frame pixels back to the reference: undoes the shift
    np.testing.assert_allclose(al.A @ np.array([500.0, 300.0, 1.0]), [491.0, 306.0], atol=0.5)
