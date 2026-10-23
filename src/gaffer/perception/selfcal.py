"""Per-video self-calibration of the drone perception (generalisation session, 23 Oct).

The classical drone detector and the team classifier were tuned on one ground (TeamTrack: an
overcast day, one turf, one drone height). On an unseen ground (Zenodo record 14867795: low sun,
long shadows, light poles, a fence and a stand by the touchlines) they produced two to three
false detections per real player. Everything here is learnt from the video itself, with OpenCV
only, and every part is a switch in `perception.self_calibration` (measured on and off):

- **pitch mask** (`pitch_mask`): detections whose pitch position lies outside the confirmed
  pitch plus `pitch_mask_margin_m` are dropped before tracking, so nothing outside the pitch is
  tracked, labelled or drawn on the 2D pitch;
- **grass model** (`grass_model`, `GrassModel`): the grass colour of *this* video, from pixels
  inside the pitch (painted lines removed) on the first analysed frame: a hue band from robust
  percentiles around the `cv2.calcHist` hue peak (mowing stripes differ in brightness, not hue)
  and a saturation floor. Grass-coloured pixels are background in the detector's foreground and
  in the team-colour crops, instead of the fixed `teams.grass_hue` band;
- **shadows** (`shadows`): pixels with the grass hue and saturation but darker (the shadows of
  players, poles, goal frames and stands keep the turf's hue and saturation, only brightness
  drops) also count as grass; blobs thinner than `thin_width_m` and `max_elongation` times longer
  than wide (pole shadows, fence lines) are rejected; a player's position is therefore the
  centroid of its shirt-coloured pixels, not of player + shadow;
- **local scale** (`local_scale`): the expected size of a player at each blob, in pixels, from
  the homography (pixels per metre at that image point), and a working resolution chosen so a
  metre is `working_px_per_m` pixels whatever the drone height or video resolution;
- **static objects** (`static_objects`, `static_detections`): a background model of the clip in
  pitch coordinates (robust to drone drift): detections that recur within `radius_m` of the same
  pitch point in at least `min_share` of the sampled frames (poles, balls left on the grass, line
  junctions, stand edges) are not players;
- **crop lines** (`crop_exclude_lines`): pixels on the projected painted lines are left out of the
  team-colour crop (a white shirt on a white line read as "other", 15:45-16:30 of the demo);
- **crop foreground** (`crop_foreground`): the team colour is taken from the player's own pixels
  (the detector's foreground blob, shadows already removed), not from every non-grass pixel of
  the box (grass edges, shadow rims and shorts pulled the two Zenodo kits to 11 units apart);
- **adaptive gate** (`adaptive_gate`): see `team_classifier.fit_team_model`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from gaffer.perception.pitch import PitchMapper, PitchModel


@dataclass(frozen=True)
class SelfCalSettings:
    """From config `perception.self_calibration`; every switch False for views not listed."""

    pitch_mask: bool = False
    pitch_mask_margin_m: float = 1.5
    grass_model: bool = False
    grass: dict[str, Any] = field(default_factory=dict)
    shadows: bool = False
    shadow: dict[str, Any] = field(default_factory=dict)
    local_scale: bool = False
    working_px_per_m: float = 14.7
    static_objects: bool = False
    static: dict[str, Any] = field(default_factory=dict)
    crop_exclude_lines: bool = False
    crop_line_band_m: float = 0.3
    crop_foreground: bool = False
    adaptive_gate: bool = False
    gate: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], view: str) -> SelfCalSettings:
        c = (cfg.get("perception") or {}).get("self_calibration") or {}
        if not c or view not in c.get("views", []):
            return cls()
        return cls(bool(c.get("pitch_mask", False)), float(c.get("pitch_mask_margin_m", 1.5)),
                   bool(c.get("grass_model", False)), dict(c.get("grass") or {}),
                   bool(c.get("shadows", False)), dict(c.get("shadow") or {}),
                   bool(c.get("local_scale", False)), float(c.get("working_px_per_m", 14.7)),
                   bool(c.get("static_objects", False)), dict(c.get("static") or {}),
                   bool(c.get("crop_exclude_lines", False)),
                   float(c.get("crop_line_band_m", 0.3)),
                   bool(c.get("crop_foreground", False)),
                   bool(c.get("adaptive_gate", False)), dict(c.get("gate") or {}))

    @property
    def needs_grass(self) -> bool:
        return self.grass_model or self.shadows

    def summary(self) -> dict[str, bool]:
        return {k: getattr(self, k) for k in ("pitch_mask", "grass_model", "shadows",
                                              "local_scale", "static_objects",
                                              "crop_exclude_lines", "crop_foreground",
                                              "adaptive_gate")}


# --------------------------------------------------------------------------- pitch mask


def inside_pitch(xy: np.ndarray, length: float, width: float, margin_m: float) -> np.ndarray:
    """Boolean mask of pitch points within `margin_m` of the pitch rectangle."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    m = float(margin_m)
    return ((xy[:, 0] >= -m) & (xy[:, 0] <= length + m) & (xy[:, 1] >= -m)
            & (xy[:, 1] <= width + m) & np.isfinite(xy).all(axis=1))


# --------------------------------------------------------------------------- grass model


@dataclass(frozen=True)
class GrassModel:
    """This video's grass colour in OpenCV 8-bit HSV (H 0..180), and its shadows.

    Sunlit grass: hue in [hue_lo, hue_hi], saturation >= sat_min, brightness >= value_min.
    Shadowed grass (lit by the blue sky only): darker (shadow_value_min <= V < value_min), hue
    shifted towards cyan (up to shadow_hue_hi) and at least as saturated as grass
    (>= shadow_sat_min); dark clothing is the opposite (low saturation), navy shirts sit at a
    blue hue far beyond the band."""

    hue_lo: float
    hue_hi: float
    sat_min: float
    value_median: float
    value_min: float  # normal-brightness grass floor
    shadow_value_min: float
    shadow_hue_hi: float
    shadow_sat_min: float
    pixels: int

    def mask(self, hsv: np.ndarray, shadows: bool) -> np.ndarray:
        """Boolean mask of grass pixels (shadowed grass included when `shadows`)."""
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        m = (h >= self.hue_lo) & (h <= self.hue_hi) & (s >= self.sat_min) & (v >= self.value_min)
        if shadows:
            m |= ((v < self.value_min) & (v >= self.shadow_value_min) & (h >= self.hue_lo)
                  & (h <= self.shadow_hue_hi) & (s >= self.shadow_sat_min))
        return m

    def mask_bgr(self, bgr: np.ndarray, shadows: bool) -> np.ndarray:
        return self.mask(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV), shadows)

    def to_dict(self) -> dict[str, float]:
        return {k: round(float(getattr(self, k)), 2) for k in
                ("hue_lo", "hue_hi", "sat_min", "value_median", "value_min",
                 "shadow_value_min", "shadow_hue_hi", "shadow_sat_min", "pixels")}


class GrassModelError(RuntimeError):
    """Too few grass pixels inside the pitch to learn its colour."""


def estimate_grass(frame: np.ndarray, mapper: PitchMapper, model: PitchModel,
                   g: dict[str, Any], sh: dict[str, Any]) -> GrassModel:
    """Learn the grass colour from pixels inside the pitch on one frame (module docstring).

    The pitch is shrunk by `inset_m` (run-off turf and the boundary line stay out), the painted
    lines are removed (a band of `line_band_m` around the projected lines), and so are pixels
    without a usable hue (`min_saturation`, `min_value`). The hue band is the
    `hue_percentiles` of the pixels within `hue_window` of the histogram peak, widened by
    `hue_margin`; the saturation floor is `saturation_factor` x the low percentile of their
    saturation. Shadow settings (`sh`, config `shadow`): brightness from `value_frac` x the
    grass median, hue up to `hue_hi` + `hue_extra`, saturation >= `saturation_frac` x the grass
    median saturation.
    """
    from gaffer.perception.detector import painted_lines_mask, pitch_roi
    from gaffer.perception.drift import ScaledMapper

    k = min(1.0, float(g.get("analysis_width_px", 960)) / frame.shape[1])
    small = cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 \
        else frame
    sm = ScaledMapper(mapper, k)
    inset = -float(g.get("inset_m", 1.0))
    roi = pitch_roi(sm, model, inset, inset, small.shape[:2])
    xs = np.array([[model.length / 2 - 0.5, model.width / 2], [model.length / 2 + 0.5,
                                                               model.width / 2]])
    ppm = float(np.linalg.norm(np.diff(sm.to_image(xs), axis=0)))
    lines = painted_lines_mask(sm, model, small.shape[:2],
                               max(1, int(round(float(g.get("line_band_m", 1.0)) * ppm))))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    sel = ((roi > 0) & (lines == 0) & (hsv[..., 1] >= float(g.get("min_saturation", 20)))
           & (hsv[..., 2] >= float(g.get("min_value", 20))))
    px = hsv[sel].astype(np.float32)
    if len(px) < int(g.get("min_pixels", 5000)):
        raise GrassModelError(f"only {len(px)} usable grass pixels inside the pitch")
    hist = cv2.calcHist([hsv], [0], sel.astype(np.uint8), [180], [0, 180]).ravel()
    hist = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, mode="valid")
    peak = float(np.argmax(hist))
    win = float(g.get("hue_window", 20))
    near = np.abs(px[:, 0] - peak) <= win
    if near.sum() < 0.5 * len(px):
        raise GrassModelError("no dominant grass hue inside the pitch")
    p_lo, p_hi = (float(v) for v in g.get("hue_percentiles", [1, 99]))
    m_lo, m_hi = (float(v) for v in g.get("hue_margin", [3, 8]))
    h_lo, h_hi = np.percentile(px[near, 0], [p_lo, p_hi])
    s_lo = float(np.percentile(px[near, 1], p_lo))
    s_med = float(np.median(px[near, 1]))
    v_med = float(np.median(px[near, 2]))
    return GrassModel(float(h_lo - m_lo), float(h_hi + m_hi),
                      float(g.get("saturation_factor", 0.7)) * s_lo, v_med,
                      float(g.get("value_frac", 0.7)) * v_med,
                      max(float(g.get("min_value", 20)), float(sh.get("value_frac", 0.2)) * v_med),
                      float(h_hi + m_hi + float(sh.get("hue_extra", 0.0))),
                      float(sh.get("saturation_frac", 1.0)) * s_med,
                      int(near.sum()))


# --------------------------------------------------------------------------- local scale


def local_px_per_m(mapper: PitchMapper, uv: np.ndarray) -> np.ndarray:
    """Pixels per metre at each image point (square root of the local area scale of the
    pitch -> image mapping): the expected size of a player standing there, from geometry."""
    uv = np.asarray(uv, float).reshape(-1, 2)
    if not len(uv):
        return np.zeros(0)
    xy = mapper.to_pitch(uv)
    dx = mapper.to_image(xy + [0.5, 0.0]) - mapper.to_image(xy - [0.5, 0.0])
    dy = mapper.to_image(xy + [0.0, 0.5]) - mapper.to_image(xy - [0.0, 0.5])
    area = np.abs(dx[:, 0] * dy[:, 1] - dx[:, 1] * dy[:, 0])
    return np.sqrt(area)


def blob_axes(mask: np.ndarray) -> tuple[float, float]:
    """Length and width (pixels) of a binary blob from its second moments (`cv2.moments`):
    sqrt(12) standard deviations along each principal direction, the full extent of a uniform
    bar (a pole shadow 0.3 m wide measures 0.3 m)."""
    m = cv2.moments(mask, binaryImage=True)
    if m["m00"] <= 0:
        return 0.0, 0.0
    a, b, c = m["mu20"] / m["m00"], m["mu11"] / m["m00"], m["mu02"] / m["m00"]
    tr, det = a + c, a * c - b * b
    disc = max(0.0, tr * tr / 4 - det)
    l1, l2 = tr / 2 + np.sqrt(disc), max(0.0, tr / 2 - np.sqrt(disc))
    k = float(np.sqrt(12.0))
    return k * float(np.sqrt(l1)), k * float(np.sqrt(l2))


# --------------------------------------------------------------------------- static objects


def static_detections(points: list[np.ndarray], times: list[float], s: dict[str, Any]
                      ) -> list[np.ndarray]:
    """Per frame, a boolean mask of detections that are static objects (module docstring).

    `points[k]` are the pitch positions of frame k's detections. A detection is static when
    detections within `radius_m` of it occur in at least `min_share` of all frames. Runs shorter
    than `min_frames` frames or `min_span_s` seconds are left alone (too short to tell a
    player standing still from an object).
    """
    from scipy.spatial import cKDTree

    n = len(points)
    out = [np.zeros(len(p), bool) for p in points]
    if n < int(s.get("min_frames", 30)) or not times or \
            max(times) - min(times) < float(s.get("min_span_s", 20.0)):
        return out
    allp = np.concatenate([np.asarray(p, float).reshape(-1, 2) for p in points]) \
        if any(len(p) for p in points) else np.zeros((0, 2))
    if not len(allp):
        return out
    fid = np.concatenate([np.full(len(p), k) for k, p in enumerate(points)])
    tree = cKDTree(allp)
    r = float(s.get("radius_m", 0.5))
    need = float(s.get("min_share", 0.8)) * n
    nbrs = tree.query_ball_point(allp, r)
    flags = np.array([len(set(fid[j].tolist())) >= need for j in nbrs], bool)
    start = 0
    for k, p in enumerate(points):
        out[k] = flags[start:start + len(p)]
        start += len(p)
    return out
