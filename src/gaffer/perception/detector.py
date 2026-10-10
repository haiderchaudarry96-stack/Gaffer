"""Player detection, one interface for both views.

Two OpenCV detectors (chosen per view in config `detector.views`, by measured precision /
recall in `scripts/compare_detectors.py`):

- `ClassicalBlobDetector` (drone view): players seen from above are ~30 px blobs with no human
  shape (COCO YOLOX finds ~1 in 12, DATA_NOTES). Foreground = colour distance to a *spatial*
  grass background (`cv2.medianBlur` on a downscaled image: stripes and light cancel, players
  that stand still are kept), restricted to the pitch and with the painted lines removed using
  the per-frame homography (geometry, not thresholds, removes the lines); `cv2.morphologyEx`,
  `cv2.connectedComponentsWithStats`, and merged players split with `cv2.kmeans`.
- `TiledYoloxDetector` (side view, and the comparison baseline): YOLOX-S (OpenCV Model Zoo,
  Apache 2.0) in `cv2.dnn` on overlapping native-resolution tiles over the pitch region,
  with cross-tile NMS.

Both return `Detections` in native image pixels (xywh).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gaffer.config import repo_path
from gaffer.perception.pitch import PitchMapper, PitchModel
from gaffer.perception.tiling import nms, tile_grid

PERSON, BALL = 0, 1
COCO_TO_OURS = {0: PERSON, 32: BALL}


class DetectorError(RuntimeError):
    """The detector cannot run (missing weights, model not loadable)."""


@dataclass
class Detections:
    """Boxes in native image pixels."""

    boxes: np.ndarray  # (N, 4) x, y, w, h
    scores: np.ndarray  # (N,)
    classes: np.ndarray  # (N,) PERSON | BALL

    @classmethod
    def empty(cls) -> Detections:
        return cls(np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int))

    def __len__(self) -> int:
        return len(self.boxes)

    def select(self, keep: np.ndarray) -> Detections:
        return Detections(self.boxes[keep], self.scores[keep], self.classes[keep])

    def persons(self) -> Detections:
        return self.select(self.classes == PERSON)


# --------------------------------------------------------------------------- region of interest


def _fill_pitch_polygon(mask: np.ndarray, mapper: PitchMapper, corners: list[tuple[float, float]],
                        value: int, step_m: float) -> None:
    """Fill a polygon given in pitch metres; edges sampled densely so non-homography mappers
    (sectioned side view) give the right shape."""
    ring = [*corners, corners[0]]
    pts = []
    for (x0, y0), (x1, y1) in zip(ring[:-1], ring[1:], strict=True):
        n = max(2, int(np.hypot(x1 - x0, y1 - y0) / step_m))
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        pts.append(np.array([x0, y0]) * (1 - t) + np.array([x1, y1]) * t)
    uv = mapper.to_image(np.concatenate(pts))
    uv = uv[np.isfinite(uv).all(axis=1)]
    if len(uv) >= 3:
        cv2.fillPoly(mask, [np.round(uv).astype(np.int32)], value)


def pitch_roi(mapper: PitchMapper, model: PitchModel, margin_goal_m: float,
              margin_touch_m: float, shape: tuple[int, int], step_m: float = 1.0,
              corner_exclusion_m: float = 0.0, goal_exclusion_m: float = 0.0) -> np.ndarray:
    """uint8 mask, in image pixels, of where players can be: the pitch grown by margins, minus
    static furniture known from geometry: corner flags (a square of `corner_exclusion_m` around
    each corner) and goal frames (a strip `goal_exclusion_m` inside each goal line, goal width
    + 1 m each side, plus everything behind it)."""
    L, W = model.length, model.width
    a, b = margin_goal_m, margin_touch_m
    mask = np.zeros(shape, np.uint8)
    _fill_pitch_polygon(mask, mapper, [(-a, -b), (L + a, -b), (L + a, W + b), (-a, W + b)], 255,
                        step_m)
    c = corner_exclusion_m
    if c > 0:
        for cx, cy in ((0, 0), (L, 0), (L, W), (0, W)):
            _fill_pitch_polygon(mask, mapper, [(cx - c, cy - c), (cx + c, cy - c),
                                               (cx + c, cy + c), (cx - c, cy + c)], 0, 0.25)
    g = goal_exclusion_m
    if g > 0:
        half = 7.32 / 2 + 1.0
        for x_line, inward in ((0.0, 1.0), (L, -1.0)):
            x_in, x_out = x_line + inward * g, x_line - inward * (a + 1.0)
            _fill_pitch_polygon(mask, mapper, [(x_out, W / 2 - half), (x_in, W / 2 - half),
                                               (x_in, W / 2 + half), (x_out, W / 2 + half)],
                                0, 0.25)
    return mask


def painted_lines_mask(mapper: PitchMapper, model: PitchModel, shape: tuple[int, int],
                       width_px: int) -> np.ndarray:
    """The pitch model's lines drawn through the per-frame mapping: where paint should be."""
    mask = np.zeros(shape, np.uint8)
    for poly in model.lines(0.25).values():
        uv = mapper.to_image(poly)
        ok = np.isfinite(uv).all(axis=1)
        if ok.sum() >= 2:
            cv2.polylines(mask, [np.round(uv[ok]).astype(np.int32).reshape(-1, 1, 2)], False,
                          255, width_px, cv2.LINE_8)
    return mask


# --------------------------------------------------------------------------- classical (top view)


@dataclass(frozen=True)
class ClassicalSettings:
    scale: float
    bg_downscale: int
    bg_median_k: int
    lab_weights: tuple[float, float, float]
    diff_threshold: float
    line_width_m: float
    line_open_m: float
    max_inside_lines: float
    open_px: int
    close_px: int
    min_area_m2: float
    max_area_m2: float
    split_factor: float
    single_area_m2: float
    box_size_m: float

    @classmethod
    def from_config(cls, c: dict[str, Any]) -> ClassicalSettings:
        return cls(float(c["scale"]), int(c["bg_downscale"]), int(c["bg_median_k"]),
                   tuple(float(v) for v in c["lab_weights"]), float(c["diff_threshold"]),
                   float(c["line_width_m"]), float(c["line_open_m"]),
                   float(c["max_inside_lines"]), int(c["open_px"]), int(c["close_px"]),
                   float(c["min_area_m2"]), float(c["max_area_m2"]), float(c["split_factor"]),
                   float(c["single_area_m2"]), float(c["box_size_m"]))


class ClassicalBlobDetector:
    """Grass-background subtraction + geometry for a top-down view (see module docstring)."""

    name = "classical"

    def __init__(self, s: ClassicalSettings, model: PitchModel,
                 roi: dict[str, float]) -> None:
        self.s, self.model, self.roi = s, model, roi
        self.debug: dict[str, np.ndarray] = {}

    def foreground(self, frame: np.ndarray, mapper: PitchMapper) -> tuple[np.ndarray, float]:
        """Foreground mask at working scale and the local px-per-metre at that scale."""
        s = self.s
        small = cv2.resize(frame, None, fx=s.scale, fy=s.scale, interpolation=cv2.INTER_AREA)
        h, w = small.shape[:2]
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2Lab)
        # spatial background: median over a neighbourhood much larger than a player
        tiny = cv2.resize(lab, None, fx=1 / s.bg_downscale, fy=1 / s.bg_downscale,
                          interpolation=cv2.INTER_AREA)
        bg = cv2.resize(cv2.medianBlur(tiny, s.bg_median_k), (w, h),
                        interpolation=cv2.INTER_LINEAR)
        diff = cv2.absdiff(lab, bg).astype(np.float32)
        dist = np.sqrt((diff * np.array(s.lab_weights, np.float32)) ** 2 @ np.ones(3, np.float32))
        fg = (dist >= s.diff_threshold).astype(np.uint8) * 255

        from gaffer.perception.drift import ScaledMapper

        sm = ScaledMapper(mapper, s.scale)
        ppm = _px_per_m(sm, self.model)
        roi = pitch_roi(sm, self.model, shape=(h, w), **self.roi)
        lines = painted_lines_mask(sm, self.model, (h, w), max(1, int(round(s.line_width_m * ppm))))
        # Inside the projected line band keep only foreground that is wider than a painted line:
        # an opening with a disk wider than the paint removes lines and their crossings but
        # keeps a player standing on a line, whatever his shirt colour ("lines are thin,
        # players are wide"). Outside the band, paint-coloured pixels never occur on grass.
        fg = cv2.bitwise_and(fg, roi)
        disk = max(3, int(round(s.line_open_m * ppm)) | 1)
        wide = cv2.morphologyEx(fg, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (disk, disk)))
        fg = np.where(lines > 0, wide, fg).astype(np.uint8)
        if s.open_px > 1:
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (s.open_px,) * 2))
        if s.close_px > 1:
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (s.close_px,) * 2))
        self.debug = {"small": small, "dist": dist, "fg": fg, "roi": roi, "lines": lines}
        return fg, ppm

    def detect(self, frame: np.ndarray, mapper: PitchMapper) -> Detections:
        s = self.s
        fg, ppm = self.foreground(frame, mapper)
        a_min, a_max = s.min_area_m2 * ppm**2, s.max_area_m2 * ppm**2
        single = s.single_area_m2 * ppm**2
        n, labels, stats, cents = cv2.connectedComponentsWithStats(fg, connectivity=8)
        centres, areas = [], []
        band = self.debug["lines"] > 0
        inside = np.bincount(labels[band], minlength=n)  # pixels of each blob inside the band
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < a_min or area > a_max or inside[i] >= s.max_inside_lines * area:
                continue
            k = int(round(area / single)) if area >= s.split_factor * single else 1
            if k <= 1:
                centres.append(cents[i])
                areas.append(area)
                continue
            ys, xs = np.nonzero(labels == i)
            pts = np.stack([xs, ys], axis=1).astype(np.float32)
            crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
            cv2.setRNGSeed(42)
            _, lab_k, ctr = cv2.kmeans(pts, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
            for j in range(k):
                centres.append(ctr[j])
                areas.append(float((lab_k.ravel() == j).sum()))
        if not centres:
            return Detections.empty()
        c = np.array(centres, dtype=float) / s.scale
        side = s.box_size_m * ppm / s.scale
        boxes = np.stack([c[:, 0] - side / 2, c[:, 1] - side / 2,
                          np.full(len(c), side), np.full(len(c), side)], axis=1)
        scores = np.clip(np.array(areas) / single, 0.0, 1.0)
        return Detections(boxes, scores, np.full(len(c), PERSON, dtype=int))


def _px_per_m(mapper: PitchMapper, model: PitchModel) -> float:
    """Median image scale (px per metre) over the pitch, from the mapper."""
    xs = np.linspace(10, model.length - 10, 5)
    ys = np.linspace(10, model.width - 10, 4)
    gx, gy = np.meshgrid(xs, ys)
    p = np.stack([gx.ravel(), gy.ravel()], axis=1)
    a, b = mapper.to_image(p), mapper.to_image(p + [1.0, 0.0])
    return float(np.median(np.linalg.norm(b - a, axis=1)))


# --------------------------------------------------------------------------- YOLOX in cv2.dnn


def ensure_weights(dcfg: dict[str, Any]) -> Path:
    """Path of the ONNX weights, or a clear error telling how to get them."""
    p = repo_path(dcfg["file"])
    if not p.exists() or p.stat().st_size < 1_000_000:
        raise DetectorError(
            f"Missing detector weights {p}. Download them with `py scripts\\smoke_test_opencv.py` "
            f"(fetches {dcfg['url']}).")
    return p


class YoloxRunner:
    """YOLOX-S (OpenCV Model Zoo) in `cv2.dnn`: letterbox, forward, decode (as in the zoo)."""

    def __init__(self, weights: Path, input_size: int, strides: list[int]) -> None:
        try:
            self.net = cv2.dnn.readNet(str(weights))
        except cv2.error as exc:
            raise DetectorError(f"cv2.dnn could not load {weights}: {exc}") from exc
        # OpenCV 5's new dnn graph engine runs on the CPU and warns on setPreferableTarget
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.size = int(input_size)
        grids, strd = [], []
        for st in strides:
            n = self.size // st
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strd.append(np.full((n * n, 1), st))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(strd).astype(np.float32)

    def infer(self, img: np.ndarray, conf: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(xywh in `img` pixels, score, COCO class) for boxes above `conf` (before NMS)."""
        h, w = img.shape[:2]
        r = min(self.size / h, self.size / w)
        canvas = np.full((self.size, self.size, 3), 114, np.uint8)
        canvas[: int(h * r), : int(w * r)] = cv2.resize(img, (int(w * r), int(h * r)))
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 1.0, swapRB=True, ddepth=cv2.CV_32F))
        out = self.net.forward()
        d = out.reshape(-1, out.shape[-1]).copy()
        d[:, :2] = (d[:, :2] + self.grids) * self.strides
        d[:, 2:4] = np.exp(d[:, 2:4]) * self.strides
        sc = d[:, 4:5] * d[:, 5:]
        cls, score = sc.argmax(1), sc.max(1)
        m = (score >= conf) & np.isin(cls, list(COCO_TO_OURS))
        d = d[m]
        xywh = np.stack([d[:, 0] - d[:, 2] / 2, d[:, 1] - d[:, 3] / 2, d[:, 2], d[:, 3]], 1) / r
        return xywh, score[m], cls[m]


class TiledYoloxDetector:
    """YOLOX on overlapping native-resolution tiles over the pitch, cross-tile NMS.

    `upscale` > 1 feeds tiles of `tile_px / upscale` native pixels enlarged to the network
    input, for players too small even at native resolution.
    """

    name = "tiled_yolox"

    def __init__(self, runner: YoloxRunner, tile_px: int, overlap_px: int, upscale: float,
                 conf: float, nms_iou: float, model: PitchModel, roi: dict[str, float]) -> None:
        self.r, self.tile, self.overlap = runner, int(tile_px), int(overlap_px)
        self.upscale, self.conf, self.nms_iou = float(upscale), float(conf), float(nms_iou)
        self.model, self.roi = model, roi
        self.last_tiles = 0

    def detect(self, frame: np.ndarray, mapper: PitchMapper) -> Detections:
        h, w = frame.shape[:2]
        roi = pitch_roi(mapper, self.model, shape=(h, w), **self.roi)
        ys, xs = np.nonzero(roi)
        if len(xs) == 0:
            return Detections.empty()
        # players stand up to ~2 m above their foot point: extend the ROI box upwards
        pad = int(0.08 * h)
        native = int(round(self.tile / self.upscale))
        tiles = tile_grid(xs.min(), ys.min() - pad, xs.max() + 1, ys.max() + 1, native,
                          int(round(self.overlap / self.upscale)), w, h)
        self.last_tiles = len(tiles)
        B, S, C = [], [], []
        for tx, ty, tw, th in tiles:
            crop = frame[ty:ty + th, tx:tx + tw]
            if self.upscale != 1.0:
                crop = cv2.resize(crop, None, fx=self.upscale, fy=self.upscale,
                                  interpolation=cv2.INTER_LINEAR)
            xywh, sc, cl = self.r.infer(crop, self.conf)
            if len(xywh):
                xywh = xywh / self.upscale
                xywh[:, 0] += tx
                xywh[:, 1] += ty
                B.append(xywh)
                S.append(sc)
                C.append(np.array([COCO_TO_OURS[int(c)] for c in cl]))
        if not B:
            return Detections.empty()
        boxes, scores, classes = np.concatenate(B), np.concatenate(S), np.concatenate(C)
        keep = nms(boxes, scores, classes, self.conf, self.nms_iou)
        det = Detections(boxes[keep], scores[keep], classes[keep])
        # keep boxes whose foot point (bottom centre) lies on the pitch ROI
        foot = np.stack([det.boxes[:, 0] + det.boxes[:, 2] / 2,
                         det.boxes[:, 1] + det.boxes[:, 3]], 1).round().astype(int)
        fx, fy = np.clip(foot[:, 0], 0, w - 1), np.clip(foot[:, 1], 0, h - 1)
        return det.select(roi[fy, fx] > 0)


# --------------------------------------------------------------------------- factory


def make_detector(cfg: dict[str, Any], view: str, model: PitchModel, method: str | None = None,
                  **overrides: Any) -> ClassicalBlobDetector | TiledYoloxDetector:
    """The detector configured for a view (`detector.views.<view>.method`), or `method`."""
    d = cfg["detector"]
    vcfg = d["views"][view]
    roi = {"margin_goal_m": float(vcfg["roi_margin_goal_m"]),
           "margin_touch_m": float(vcfg["roi_margin_touch_m"]),
           "corner_exclusion_m": float(vcfg.get("corner_exclusion_m", 0.0)),
           "goal_exclusion_m": float(vcfg.get("goal_exclusion_m", 0.0))}
    m = method or vcfg["method"]
    if m == "classical":
        return ClassicalBlobDetector(ClassicalSettings.from_config({**d["classical"], **overrides}),
                                     model, roi)
    if m == "tiled_yolox":
        t = {**d["tiled_yolox"], **vcfg.get("tiled_yolox", {}), **overrides}
        runner = YoloxRunner(ensure_weights(d), int(d["input_size"]), list(d["strides"]))
        return TiledYoloxDetector(runner, int(t["tile_px"]), int(t["overlap_px"]),
                                  float(t["upscale"]), float(t["conf_threshold"]),
                                  float(t["nms_threshold"]), model, roi)
    raise DetectorError(f"unknown detector method {m!r}")
