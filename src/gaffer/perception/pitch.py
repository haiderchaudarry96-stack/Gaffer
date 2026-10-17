"""Pitch geometry: the pitch model in metres, line masks, landmark snapping, homography fitting.

Coordinate frame (`docs/DATA_CONTRACT.md`): metres on the real pitch, origin at the corner that
is **bottom-left as seen from the side camera** (near touchline, left goal line), `x` along the
length (0..L), `y` across (0..W, far touchline at W). Both TeamTrack views are mapped into this
one frame, so top-view and side-view positions can be compared directly. The drone image is
rotated ~180 degrees relative to the side camera; the landmark names absorb that (a drone pixel
is simply labelled with the pitch landmark it shows).

OpenCV does the work here: a white-line mask by morphological top-hat (`cv2.morphologyEx`),
landmark refinement by robust local line fits (`cv2.fitLine`), `cv2.findHomography`,
`cv2.perspectiveTransform`, and a line-alignment error from `cv2.distanceTransform`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
from scipy.optimize import least_squares

from gaffer.config import repo_path

# --------------------------------------------------------------------------- errors


class CalibrationError(RuntimeError):
    """A calibration file is missing, invalid, or too few landmarks could be used."""


# --------------------------------------------------------------------------- pitch model


@dataclass(frozen=True)
class Markings:
    """IFAB fixed-size markings (metres). These do not depend on the pitch length or width,
    which is what lets calibration fit the pitch size."""

    penalty_area_depth_m: float = 16.5
    penalty_area_width_m: float = 40.32
    goal_area_depth_m: float = 5.5
    goal_area_width_m: float = 18.32
    penalty_spot_m: float = 11.0
    centre_circle_radius_m: float = 9.15

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> Markings:
        """Read `pitch.markings` (missing keys keep the IFAB defaults)."""
        return cls(**{k: float(v) for k, v in (cfg.get("pitch", {}).get("markings") or {}).items()})


class PitchModel:
    """Landmarks and line polylines of a pitch of a given size, in pitch metres."""

    def __init__(self, length_m: float, width_m: float, markings: Markings | None = None) -> None:
        self.length = float(length_m)
        self.width = float(width_m)
        self.mk = markings or Markings()

    # ---- landmarks -------------------------------------------------------------------------

    def landmarks(self) -> dict[str, tuple[float, float]]:
        """Every named landmark with its pitch coordinates."""
        L, W, m = self.length, self.width, self.mk
        cy = W / 2
        r = m.centre_circle_radius_m
        pts: dict[str, tuple[float, float]] = {
            "corner_L_near": (0.0, 0.0), "corner_L_far": (0.0, W),
            "corner_R_near": (L, 0.0), "corner_R_far": (L, W),
            "half_near": (L / 2, 0.0), "half_far": (L / 2, W),
            "circle_near": (L / 2, cy - r), "circle_far": (L / 2, cy + r),
            "centre_spot": (L / 2, cy),
        }
        arc_dy = float(np.sqrt(max(r**2 - (m.penalty_area_depth_m - m.penalty_spot_m) ** 2, 0.0)))
        for side, x0, s in (("L", 0.0, 1.0), ("R", L, -1.0)):
            pa, ga = m.penalty_area_width_m / 2, m.goal_area_width_m / 2
            xpa, xga = x0 + s * m.penalty_area_depth_m, x0 + s * m.goal_area_depth_m
            pts.update({
                f"pa_{side}_goal_near": (x0, cy - pa), f"pa_{side}_goal_far": (x0, cy + pa),
                f"pa_{side}_front_near": (xpa, cy - pa), f"pa_{side}_front_far": (xpa, cy + pa),
                f"ga_{side}_goal_near": (x0, cy - ga), f"ga_{side}_goal_far": (x0, cy + ga),
                f"ga_{side}_front_near": (xga, cy - ga), f"ga_{side}_front_far": (xga, cy + ga),
                f"pen_{side}": (x0 + s * m.penalty_spot_m, cy),
                f"arc_{side}_near": (xpa, cy - arc_dy), f"arc_{side}_far": (xpa, cy + arc_dy),
            })
        return pts

    @staticmethod
    def landmark_lines(name: str) -> tuple[str, ...]:
        """The pitch lines a landmark lies on (empty for spots)."""
        if name in ("centre_spot", "pen_L", "pen_R"):
            return ()
        if name.startswith("corner_"):
            _, side, end = name.split("_")
            return (f"goal_{side}", f"touch_{end}")
        if name.startswith("half_"):
            return ("halfway", f"touch_{name.split('_')[1]}")
        if name.startswith("circle_"):
            return ("halfway", "centre_circle")
        if name.startswith("arc_"):
            side = name.split("_")[1]
            return (f"pa_{side}_front", f"arc_{side}")
        box, side, where, end = name.split("_")  # e.g. pa_L_goal_near
        first = f"goal_{side}" if where == "goal" else f"{box}_{side}_front"
        return (first, f"{box}_{side}_{end}")

    # ---- lines -----------------------------------------------------------------------------

    def lines(self, step_m: float = 1.0) -> dict[str, np.ndarray]:
        """Every pitch line as a densely sampled polyline (N, 2) in metres."""
        L, W, m = self.length, self.width, self.mk
        cy = W / 2

        def seg(a: tuple[float, float], b: tuple[float, float]) -> np.ndarray:
            n = max(2, int(np.ceil(np.hypot(b[0] - a[0], b[1] - a[1]) / step_m)) + 1)
            t = np.linspace(0.0, 1.0, n)[:, None]
            return np.asarray(a) * (1 - t) + np.asarray(b) * t

        def arc(cx: float, c_y: float, r: float, a0: float, a1: float) -> np.ndarray:
            n = max(8, int(np.ceil(abs(a1 - a0) * r / step_m)) + 1)
            a = np.linspace(a0, a1, n)
            return np.stack([cx + r * np.cos(a), c_y + r * np.sin(a)], axis=1)

        r = m.centre_circle_radius_m
        out = {
            "touch_near": seg((0, 0), (L, 0)), "touch_far": seg((0, W), (L, W)),
            "goal_L": seg((0, 0), (0, W)), "goal_R": seg((L, 0), (L, W)),
            "halfway": seg((L / 2, 0), (L / 2, W)),
            "centre_circle": arc(L / 2, cy, r, 0.0, 2 * np.pi),
        }
        half_open = float(np.arccos(min(1.0, (m.penalty_area_depth_m - m.penalty_spot_m) / r)))
        for side, x0, s in (("L", 0.0, 1.0), ("R", L, -1.0)):
            for box, depth, width in (("pa", m.penalty_area_depth_m, m.penalty_area_width_m),
                                      ("ga", m.goal_area_depth_m, m.goal_area_width_m)):
                xf, hw = x0 + s * depth, width / 2
                out[f"{box}_{side}_near"] = seg((x0, cy - hw), (xf, cy - hw))
                out[f"{box}_{side}_far"] = seg((x0, cy + hw), (xf, cy + hw))
                out[f"{box}_{side}_front"] = seg((xf, cy - hw), (xf, cy + hw))
            px = x0 + s * m.penalty_spot_m
            base = 0.0 if s > 0 else np.pi
            out[f"arc_{side}"] = arc(px, cy, r, base - half_open, base + half_open)
        return out

    def polygon(self, margin_m: float = 0.0) -> np.ndarray:
        """Pitch outline (4, 2), optionally grown by `margin_m` on every side."""
        L, W, d = self.length, self.width, margin_m
        return np.array([[-d, -d], [L + d, -d], [L + d, W + d], [-d, W + d]], dtype=float)


# --------------------------------------------------------------------------- mappers


class PitchMapper(Protocol):
    """Image pixels <-> pitch metres. Homography for the top view; the side view may use a
    non-planar model (`perception/undistort.py`)."""

    def to_pitch(self, uv: np.ndarray) -> np.ndarray: ...

    def to_image(self, xy: np.ndarray) -> np.ndarray: ...


class HomographyMapper:
    """A single plane-to-plane homography (`cv2.perspectiveTransform`)."""

    def __init__(self, H_image_to_pitch: np.ndarray) -> None:
        self.H = np.asarray(H_image_to_pitch, dtype=float)
        self.H_inv = np.linalg.inv(self.H)

    @staticmethod
    def _apply(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
        if len(pts) == 0:
            return np.zeros((0, 2))
        return cv2.perspectiveTransform(pts, H).reshape(-1, 2)

    def to_pitch(self, uv: np.ndarray) -> np.ndarray:
        """Pixels (N, 2) -> pitch metres (N, 2)."""
        return self._apply(self.H, uv)

    def to_image(self, xy: np.ndarray) -> np.ndarray:
        """Pitch metres (N, 2) -> pixels (N, 2)."""
        return self._apply(self.H_inv, xy)

    def warped(self, A: np.ndarray) -> HomographyMapper:
        """Mapper for a frame whose pixels relate to this reference frame by `ref = A @ frame`
        (A is 2x3 affine or 3x3), as estimated by drift re-anchoring."""
        A3 = np.vstack([A, [0, 0, 1]]) if A.shape == (2, 3) else np.asarray(A, dtype=float)
        return HomographyMapper(self.H @ A3)


# --------------------------------------------------------------------------- line mask


def line_mask(frame: np.ndarray, kernel_px: int, threshold: int, max_saturation: int = 90,
              min_component_px: int = 0, close_px: int = 0) -> np.ndarray:
    """Binary mask of painted pitch lines.

    White top-hat on the grey image (`cv2.morphologyEx(MORPH_TOPHAT)`) keeps thin structures
    brighter than their surroundings, which is robust to the grass stripes and overcast light;
    a saturation cap removes coloured shirts and advertising. A small closing (`close_px`)
    rejoins far, near-horizontal lines that the threshold breaks into staircase dashes; then
    connected components smaller than `min_component_px` (grass-texture speckle, player
    highlights) are removed with `cv2.connectedComponentsWithStats`: painted lines form long
    connected structures.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_px, kernel_px))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    sat = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 1]
    mask = ((tophat >= threshold) & (sat <= max_saturation)).astype(np.uint8) * 255
    if close_px > 1:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (close_px, close_px)))
    if min_component_px > 0:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        keep = np.zeros(n, dtype=bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_component_px
        mask = np.where(keep[labels], 255, 0).astype(np.uint8)
    return mask


def line_distance_map(mask: np.ndarray) -> np.ndarray:
    """Distance (px) from every pixel to the nearest line centre (`cv2.distanceTransform` on
    `line_centres`): the map `line_alignment_error` reads."""
    centre = line_centres(mask)
    return cv2.distanceTransform((centre == 0).astype(np.uint8), cv2.DIST_L2, 5)


def line_centres(mask: np.ndarray) -> np.ndarray:
    """One-pixel centreline of the line mask (`cv2.ximgproc.thinning`, Zhang-Suen), so that
    alignment errors are measured to the middle of a painted line, not its edge."""
    return cv2.ximgproc.thinning(mask, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN)


# --------------------------------------------------------------------------- snapping


@dataclass
class SnapSettings:
    """Landmark refinement settings (per view, from `calibration.views.<view>`)."""

    radius_px: float
    band_px: float
    inlier_px: float
    min_pixels: int
    spot_radius_px: float
    max_move_px: float = float("inf")  # a snap moving a pick further than this is rejected


def _fit_line(pts: np.ndarray, inlier_px: float, rounds: int = 3
              ) -> tuple[np.ndarray, np.ndarray] | None:
    """Robust 2D line fit: `cv2.fitLine` (Huber) with inlier re-selection. Returns (point, dir)."""
    if len(pts) < 2:
        return None
    sel = pts.astype(np.float32)
    for _ in range(rounds):
        vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        d = np.array([vx, vy], dtype=float)
        p = np.array([x0, y0], dtype=float)
        n = np.array([-d[1], d[0]])
        dist = np.abs((pts - p) @ n)
        keep = pts[dist <= inlier_px]
        if len(keep) < 2 or len(keep) == len(sel):
            break
        sel = keep.astype(np.float32)
    return p, d


def _intersect(l1: tuple[np.ndarray, np.ndarray], l2: tuple[np.ndarray, np.ndarray]
               ) -> np.ndarray | None:
    (p1, d1), (p2, d2) = l1, l2
    A = np.array([d1, -d2]).T
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    t = np.linalg.solve(A, p2 - p1)
    return p1 + t[0] * d1


def _dist_to_polyline(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Distance of each point (N, 2) to a polyline (M, 2), M >= 2."""
    best = np.full(len(pts), np.inf)
    for a, b in zip(poly[:-1], poly[1:], strict=True):
        ab = b - a
        t = np.clip(((pts - a) @ ab) / max(ab @ ab, 1e-9), 0.0, 1.0)
        best = np.minimum(best, np.linalg.norm(pts - (a + t[:, None] * ab), axis=1))
    return best


def _spot_centre(dt: np.ndarray, p0: np.ndarray, radius: float) -> np.ndarray | None:
    """Centre of a painted spot near `p0`: the maximum of the distance transform (a spot is the
    thickest white blob, even when it sits on a line), refined as the dt-weighted centroid of
    the pixels close to that maximum."""
    h, w = dt.shape
    x0, y0 = max(int(p0[0] - radius), 0), max(int(p0[1] - radius), 0)
    x1, y1 = min(int(p0[0] + radius) + 1, w), min(int(p0[1] + radius) + 1, h)
    win = dt[y0:y1, x0:x1]
    if win.size == 0 or win.max() < 1.0:
        return None
    ys, xs = np.nonzero(win >= 0.8 * win.max())
    wts = win[ys, xs]
    return np.array([x0 + np.average(xs, weights=wts), y0 + np.average(ys, weights=wts)])


def snap_landmarks(mask: np.ndarray, approx: dict[str, list[float]],
                   hints: dict[str, list[list[float]]], s: SnapSettings,
                   spot_mask: np.ndarray | None = None,
                   predicted: dict[str, np.ndarray] | None = None
                   ) -> dict[str, dict[str, Any]]:
    """Refine hand-picked landmark positions onto the painted lines.

    For a landmark where lines A and B cross, each line is fitted locally (white pixels within
    `radius_px` of the landmark) with `cv2.fitLine`. A line's local course is taken from the
    other picked landmarks on it (plus optional `hints`), or, for curves (centre circle,
    penalty arcs), from `predicted`: the model line projected with a first-pass calibration.
    Spots snap to the centroid of the white pixels near them in `spot_mask` (the unfiltered
    mask: a penalty spot is smaller than the speckle filter). A landmark that cannot be refined
    keeps its picked position and is flagged `snapped: false`.
    """
    ys, xs = np.nonzero(mask)
    white = np.stack([xs, ys], axis=1).astype(float)
    spot_dt = cv2.distanceTransform(((spot_mask if spot_mask is not None else mask) > 0)
                                    .astype(np.uint8), cv2.DIST_L2, 5)
    predicted = predicted or {}
    course: dict[str, list[np.ndarray]] = {}
    for name, uv in approx.items():
        for ln in PitchModel.landmark_lines(name):
            course.setdefault(ln, []).append(np.asarray(uv, dtype=float))
    for ln, pts in hints.items():
        course.setdefault(ln, []).extend(np.asarray(p, dtype=float) for p in pts)

    out: dict[str, dict[str, Any]] = {}
    for name, uv in approx.items():
        p0 = np.asarray(uv, dtype=float)
        local = white[np.linalg.norm(white - p0, axis=1) <= s.radius_px]
        lines = PitchModel.landmark_lines(name)
        result: dict[str, Any] = {"approx": [float(p0[0]), float(p0[1])], "image": None,
                                  "snapped": False, "note": ""}
        if not lines:
            c = _spot_centre(spot_dt, p0, s.spot_radius_px)
            if c is not None and np.linalg.norm(c - p0) <= s.max_move_px:
                result.update(image=[float(c[0]), float(c[1])], snapped=True)
            else:
                result.update(image=result["approx"], note="no white blob near the spot")
            out[name] = result
            continue

        def with_course(ln: str) -> np.ndarray | None:
            if ln in predicted:
                return predicted[ln]
            pts = course.get(ln, [])
            if len(pts) < 2:
                return None
            pts_arr = np.array(pts)
            # order along the dominant direction so the polyline is not zig-zagging
            axis = int(np.argmax(np.ptp(pts_arr, axis=0)))
            return pts_arr[np.argsort(pts_arr[:, axis])]

        ordered = sorted(lines, key=lambda ln: with_course(ln) is None)
        fits: list[tuple[np.ndarray, np.ndarray]] = []
        used = np.zeros(len(local), dtype=bool)
        for ln in ordered:
            poly = with_course(ln)
            if poly is not None:
                cand = local[_dist_to_polyline(local, poly) <= s.band_px] if len(local) else local
            else:
                cand = local[~used]
            if len(cand) < s.min_pixels:
                break
            fit = _fit_line(cand, s.inlier_px)
            if fit is None:
                break
            fits.append(fit)
            p, d = fit
            n = np.array([-d[1], d[0]])
            used |= np.abs((local - p) @ n) <= s.band_px
        if len(fits) == 2:
            x = _intersect(fits[0], fits[1])
            if x is not None and np.linalg.norm(x - p0) <= min(s.radius_px, s.max_move_px):
                result.update(image=[float(x[0]), float(x[1])], snapped=True)
                out[name] = result
                continue
            if x is not None:
                result.update(image=result["approx"], note=(
                    f"snap moved {np.linalg.norm(x - p0):.0f} px (> {s.max_move_px:g}); "
                    "kept the picked position"))
                out[name] = result
                continue
        result.update(image=result["approx"], note="line fit failed; kept the picked position")
        out[name] = result
    return out


CURVED_LINES = frozenset({"centre_circle", "arc_L", "arc_R"})


def snap_two_pass(mask: np.ndarray, spot_mask: np.ndarray, approx: dict[str, list[float]],
                  hints: dict[str, list[list[float]]], s: SnapSettings, model: PitchModel,
                  fit_mapper: Callable[[np.ndarray, np.ndarray], PitchMapper]
                  ) -> dict[str, dict[str, Any]]:
    """Snap straight-line landmarks first and fit a first-pass mapper on the ones that snapped.
    Then re-snap, guided by the model lines projected with that mapper: landmarks on curves
    (centre circle, penalty arcs; curves only), and landmarks the first pass could not snap
    (all their lines: far lines are a few pixels apart, picks alone are too coarse)."""
    first = snap_landmarks(mask, approx, hints, s, spot_mask)
    lm = model.landmarks()
    straight = [n for n, r in first.items()
                if r["snapped"] and not set(PitchModel.landmark_lines(n)) & CURVED_LINES]
    curved = {n: approx[n] for n in approx if set(PitchModel.landmark_lines(n)) & CURVED_LINES}
    failed = {n: approx[n] for n, r in first.items()
              if not r["snapped"] and n not in curved and PitchModel.landmark_lines(n)}
    if (not curved and not failed) or len(straight) < 4:
        return first
    uv = np.array([first[n]["image"] for n in straight], dtype=float)
    try:  # guide with the fitted pitch size, not the default one
        L, W, _, _ = fit_pitch_size(straight, uv, model.length, model.width, model.mk)
        if abs(L / model.length - 1) < 0.15 and abs(W / model.width - 1) < 0.15:
            model = PitchModel(L, W, model.mk)
            lm = model.landmarks()
    except (CalibrationError, ValueError, np.linalg.LinAlgError):
        pass
    mapper = fit_mapper(uv, np.array([lm[n] for n in straight], dtype=float))
    projected = {ln: mapper.to_image(poly) for ln, poly in model.lines(0.25).items()}
    if curved:
        first.update(snap_landmarks(mask, curved, hints, s, spot_mask,
                                    {ln: p for ln, p in projected.items() if ln in CURVED_LINES}))
    if failed:
        second = snap_landmarks(mask, failed, {}, s, spot_mask, projected)
        for r in second.values():
            if r["snapped"]:
                r["note"] = "snapped in the guided second pass"
        first.update(second)
    return first


# --------------------------------------------------------------------------- fitting


def fit_homography(img: np.ndarray, world: np.ndarray, ransac_px: float | None = None
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Image -> pitch homography with `cv2.findHomography` (least squares + LM refinement, or
    RANSAC when `ransac_px` is given). Returns (H, inlier mask)."""
    if len(img) < 4:
        raise CalibrationError(f"need at least 4 landmarks for a homography, got {len(img)}")
    method, thr = (cv2.RANSAC, float(ransac_px)) if ransac_px else (0, 3.0)
    H, inl = cv2.findHomography(img.astype(np.float64), world.astype(np.float64), method, thr)
    if H is None:
        raise CalibrationError("cv2.findHomography failed (degenerate landmark layout?)")
    inl = np.ones(len(img), bool) if inl is None else inl.ravel().astype(bool)
    return H, inl


def fit_pitch_size(names: list[str], img: np.ndarray, length0: float, width0: float,
                   markings: Markings) -> tuple[float, float, np.ndarray, float]:
    """Jointly fit the pitch size (L, W) and the pitch -> image homography.

    The fixed-size IFAB markings (penalty area 40.32 x 16.5 m, goal area, centre circle) fix the
    metric scale, so L and W become observable. Minimises reprojection error in pixels with
    `scipy.optimize.least_squares`, initialised from `cv2.findHomography` at (length0, width0).
    Returns (L, W, H_pitch_to_image, rms_px).
    """

    def world(L: float, W: float) -> np.ndarray:
        lm = PitchModel(L, W, markings).landmarks()
        return np.array([lm[n] for n in names], dtype=float)

    H0, _ = cv2.findHomography(world(length0, width0), img.astype(np.float64), 0)
    if H0 is None:
        raise CalibrationError("initial homography failed")
    H0 = H0 / H0[2, 2]
    x0 = np.concatenate([H0.ravel()[:8], [length0, width0]])

    def resid(p: np.ndarray) -> np.ndarray:
        H = np.append(p[:8], 1.0).reshape(3, 3)
        w = world(p[8], p[9])
        proj = cv2.perspectiveTransform(w.reshape(-1, 1, 2), H).reshape(-1, 2)
        return (proj - img).ravel()

    sol = least_squares(resid, x0, method="lm", x_scale="jac")
    H = np.append(sol.x[:8], 1.0).reshape(3, 3)
    rms = float(np.sqrt(np.mean(sol.fun.reshape(-1, 2) ** 2) * 2))
    return float(sol.x[8]), float(sol.x[9]), H, rms


def leave_one_out(names: list[str], img: np.ndarray, world: np.ndarray,
                  fit: Callable[[np.ndarray, np.ndarray], PitchMapper]) -> dict[str, float]:
    """Held-out landmark error (metres): refit without each landmark, map it to the pitch, and
    measure its distance to where it really is. `fit(img, world)` builds a mapper."""
    errs: dict[str, float] = {}
    for i, name in enumerate(names):
        keep = np.arange(len(names)) != i
        try:
            mapper = fit(img[keep], world[keep])
        except (CalibrationError, cv2.error, np.linalg.LinAlgError, ValueError):
            continue
        xy = mapper.to_pitch(img[i:i + 1])[0]
        errs[name] = float(np.linalg.norm(xy - world[i]))
    return errs


def line_alignment_error(mapper: PitchMapper, mask: np.ndarray, model: PitchModel,
                         step_m: float, max_search_m: float, include: Iterable[str] | None = None,
                         dist: np.ndarray | None = None) -> dict[str, Any]:
    """How far the projected pitch lines sit from the painted lines, in metres.

    Model lines are sampled every `step_m`, projected into the image, and the distance to the
    nearest line-centre pixel (`line_centres`) is read from `cv2.distanceTransform`. Pixels are
    converted to metres with the local scale perpendicular to the line. Samples with no painted
    line within `max_search_m` (occluded, out of view, faded) are counted as `not_found`
    rather than errors. `dist` (from `line_distance_map(mask)`) can be passed in when many
    candidate mappers are checked against the same mask.
    """
    h, w = mask.shape
    if dist is None:
        dist = line_distance_map(mask)
    errs: list[float] = []
    per_line: dict[str, float] = {}
    total = not_found = 0
    for name, poly in model.lines(step_m).items():
        if include is not None and name not in include:
            continue
        tang = np.gradient(poly, axis=0)
        tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-12
        normal = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
        uv = mapper.to_image(poly)
        uv_n = mapper.to_image(poly + 0.25 * normal)
        scale = np.linalg.norm(uv_n - uv, axis=1) / 0.25  # px per metre across the line
        inside = ((uv[:, 0] >= 0) & (uv[:, 0] <= w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] <= h - 1)
                  & (scale > 1e-6) & np.isfinite(uv).all(axis=1))
        if not inside.any():
            continue
        # bilinear read of the distance map at the sub-pixel projected point (cv2.remap), so
        # errors below one pixel are not rounded away on downscaled images
        pts = uv[inside].astype(np.float32)
        d = cv2.remap(dist, pts[:, 0].reshape(-1, 1), pts[:, 1].reshape(-1, 1),
                      cv2.INTER_LINEAR).ravel()
        e_all = d / scale[inside]
        total += int(inside.sum())
        not_found += int((e_all > max_search_m).sum())
        line_errs = [float(e) for e in e_all if e <= max_search_m]
        errs.extend(line_errs)
        if line_errs:
            per_line[name] = round(float(np.median(line_errs)), 3)
    arr = np.array(errs) if errs else np.array([np.nan])
    return {"median_m": round(float(np.nanmedian(arr)), 3),
            "mean_m": round(float(np.nanmean(arr)), 3),
            "p90_m": round(float(np.nanpercentile(arr, 90)), 3),
            "samples": total, "not_found_fraction": round(not_found / max(total, 1), 3),
            "per_line_median_m": per_line}


# --------------------------------------------------------------------------- calibration file


@dataclass
class Calibration:
    """A saved calibration: how to map one camera's reference frame onto the pitch."""

    view: str
    method: str
    source: str
    frame_index: int
    image_size: tuple[int, int]
    length_m: float
    width_m: float
    params: dict[str, Any]
    landmarks: dict[str, dict[str, Any]]
    errors: dict[str, Any]
    meta: dict[str, Any]

    def mapper(self) -> PitchMapper:
        """Build the image <-> pitch mapper this calibration describes."""
        if self.method == "homography":
            return HomographyMapper(np.array(self.params["H_image_to_pitch"]))
        from gaffer.perception.undistort import mapper_from_params  # side-view models

        return mapper_from_params(self.method, self.params)

    def save(self, path: str | Path) -> Path:
        p = repo_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.__dict__, indent=2, default=_json_default), encoding="utf-8")
        return p

    @classmethod
    def for_view(cls, cfg: dict[str, Any], view: str) -> Calibration:
        """The saved calibration of a TeamTrack view (`teamtrack.views.<view>.calibration`)."""
        name = cfg["teamtrack"]["views"][view]["calibration"]
        return cls.load(repo_path(cfg["calibration"]["dir"]) / f"{name}.json")

    @classmethod
    def load(cls, path: str | Path) -> Calibration:
        p = repo_path(path)
        if not p.exists():
            raise CalibrationError(
                f"No calibration file at {p}. Run `py scripts\\calibrate.py --view <top|side>` "
                "first (see README, 'Calibration').")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["image_size"] = tuple(data["image_size"])
            return cls(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise CalibrationError(f"{p} is not a valid calibration file: {exc}") from exc


def _json_default(o: Any) -> Any:
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.floating | np.integer):
        return o.item()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- drawing


def draw_overlay(frame: np.ndarray, mapper: PitchMapper, model: PitchModel,
                 landmarks: dict[str, dict[str, Any]], held_out: dict[str, float],
                 title: str, line_colour: tuple[int, int, int] = (255, 255, 0),
                 thickness: int = 2) -> np.ndarray:
    """Frame with the projected pitch lines, every landmark (picked = yellow ring, snapped =
    red cross) and its held-out error in metres."""
    out = frame.copy()
    h, w = out.shape[:2]
    for poly in model.lines(0.25).values():
        uv = mapper.to_image(poly)
        ok = (np.abs(uv) < 4 * max(h, w)).all(axis=1)
        if ok.sum() >= 2:
            cv2.polylines(out, [np.round(uv[ok]).astype(np.int32).reshape(-1, 1, 2)], False,
                          line_colour, thickness, cv2.LINE_AA)
    fs = max(0.4, min(w, h) / 2200)  # the side panorama is 6500 x 1000: scale by the short side
    for name, lm in landmarks.items():
        a = tuple(int(round(v)) for v in lm["approx"])
        cv2.circle(out, a, int(10 * fs), (0, 255, 255), max(1, thickness - 1), cv2.LINE_AA)
        if lm.get("image") is not None:
            c = tuple(int(round(v)) for v in lm["image"])
            cv2.drawMarker(out, c, (0, 0, 255), cv2.MARKER_CROSS, int(22 * fs), thickness)
        label = name + (f" {held_out[name]:.2f}m" if name in held_out else "")
        cv2.putText(out, label, (a[0] + int(12 * fs), a[1] - int(12 * fs)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * fs, (0, 0, 0), int(4 * fs) + 1, cv2.LINE_AA)
        cv2.putText(out, label, (a[0] + int(12 * fs), a[1] - int(12 * fs)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * fs, (255, 255, 255), max(1, int(fs)),
                    cv2.LINE_AA)
    bar = int(50 * fs)
    cv2.rectangle(out, (0, 0), (w, bar), (20, 20, 20), -1)
    cv2.putText(out, title, (10, int(bar * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, 0.9 * fs,
                (255, 255, 255), max(1, int(2 * fs)), cv2.LINE_AA)
    return out


# --------------------------------------------------------------------------- 4-corner calibration
# Phase 4: uploads that are not TeamTrack clips. The coach clicks (or confirms auto-detected)
# the 4 pitch corners in the order top-left, top-right, bottom-right, bottom-left as seen in the
# frame; a single homography maps them onto a pitch of the configured size. Only top-down views
# are supported: a strongly tilted camera is refused (opposite edges too different).

CORNER_ORDER = ("top_left", "top_right", "bottom_right", "bottom_left")


@dataclass
class FourCorners:
    """A 4-corner pitch homography and the checks made on the clicked quad."""

    H_image_to_pitch: np.ndarray
    corners_px: np.ndarray  # (4, 2) as given: TL, TR, BR, BL in the frame
    pitch_targets: np.ndarray  # (4, 2) pitch metres each corner maps to
    opposite_edge_ratio: float  # min over both pairs of shorter / longer edge
    aspect_px: float  # mean long edge / mean short edge in pixels (top-down: ~ L / W)
    area_frac: float
    rotated: bool  # the pitch length runs up-down in the frame

    def mapper(self) -> HomographyMapper:
        return HomographyMapper(self.H_image_to_pitch)


def _quad_checks(pts: np.ndarray) -> tuple[float, float, float, float]:
    """Signed area (> 0 = TL, TR, BR, BL order on screen), horizontal and vertical edge
    means, and the opposite-edge ratio of a quad (4, 2)."""
    x, y = pts[:, 0], pts[:, 1]
    signed = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    e = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)  # TL-TR, TR-BR, BR-BL, BL-TL
    horiz, vert = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2
    ratio = min(min(e[0], e[2]) / max(e[0], e[2], 1e-9), min(e[1], e[3]) / max(e[1], e[3], 1e-9))
    return signed, horiz, vert, float(ratio)


def four_corner_homography(points: Any, image_size: tuple[int, int], length_m: float,
                           width_m: float, settings: dict[str, Any] | None = None
                           ) -> FourCorners:
    """Homography from 4 pitch corners clicked in the frame (order TL, TR, BR, BL).

    The longer pair of image edges is taken as the pitch length (`long_side: auto`), so a pitch
    filmed with its length running up-down works too; with the length across the frame,
    TL -> (0, W), TR -> (L, W), BR -> (L, 0), BL -> (0, 0) (origin bottom-left, as in the data
    contract). `cv2.getPerspectiveTransform` gives the exact 4-point homography.

    Raises CalibrationError with a coach-readable message for: not 4 points, points far
    outside the frame, a crossed or mirrored order, a tiny quad, or a camera so tilted that
    the view is not top-down (opposite edges differ by more than `min_opposite_edge_ratio`).
    """
    s = {"max_outside_frac": 0.25, "min_area_frac": 0.05, "min_opposite_edge_ratio": 0.6,
         "long_side": "auto", **(settings or {})}
    try:
        pts = np.asarray(points, dtype=float).reshape(4, 2)
    except (ValueError, TypeError) as exc:
        raise CalibrationError("Exactly 4 pitch corners are needed (top-left, top-right, "
                               "bottom-right, bottom-left).") from exc
    if not np.isfinite(pts).all():
        raise CalibrationError("The pitch corners must be numbers.")
    w, h = float(image_size[0]), float(image_size[1])
    m = float(s["max_outside_frac"])
    if ((pts[:, 0] < -m * w) | (pts[:, 0] > (1 + m) * w) | (pts[:, 1] < -m * h)
            | (pts[:, 1] > (1 + m) * h)).any():
        raise CalibrationError("A pitch corner lies far outside the video frame. Place each "
                               "corner where the pitch lines meet.")
    if not cv2.isContourConvex(pts.astype(np.float32).reshape(-1, 1, 2)):
        raise CalibrationError("The 4 corners cross over each other. Click them in order: "
                               "top-left, top-right, bottom-right, bottom-left.")
    signed, horiz, vert, ratio = _quad_checks(pts)
    if signed <= 0:
        raise CalibrationError("The corners are in the wrong order. Click them in order: "
                               "top-left, top-right, bottom-right, bottom-left.")
    area_frac = signed / (w * h)
    if area_frac < float(s["min_area_frac"]):
        raise CalibrationError(f"The marked pitch covers only {area_frac:.0%} of the frame. "
                               "Gaffer needs a view of the whole pitch from above.")
    if ratio < float(s["min_opposite_edge_ratio"]):
        raise CalibrationError("The camera looks at the pitch at too steep an angle (the far "
                               "side is much shorter than the near side). Gaffer only analyses "
                               "top-down views, such as a drone straight above the pitch.")
    rotated = (s["long_side"] == "auto" and vert > horiz) or s["long_side"] == "vertical"
    # rotating the frame 90 deg clockwise makes the old bottom-left the new top-left
    src = np.roll(pts, 1, axis=0) if rotated else pts
    L, W = float(length_m), float(width_m)
    targets = np.array([[0.0, W], [L, W], [L, 0.0], [0.0, 0.0]])
    H = cv2.getPerspectiveTransform(src.astype(np.float32), targets.astype(np.float32))
    per_corner = np.roll(targets, -1, axis=0) if rotated else targets
    aspect = max(horiz, vert) / max(min(horiz, vert), 1e-9)
    return FourCorners(H.astype(float), pts, per_corner, round(ratio, 3), round(aspect, 3),
                       round(area_frac, 4), bool(rotated))


def four_corner_calibration(fc: FourCorners, image_size: tuple[int, int], length_m: float,
                            width_m: float, source: str, frame_index: int, picked_by: str,
                            view: str = "top") -> Calibration:
    """A `Calibration` (method homography) from 4 corners, saved like the 31-point ones, so the
    pipeline and the agent use it unchanged. `source` + `frame_index` name the reference frame
    the drift re-anchoring aligns every other frame to."""
    lm = {}
    for name, uv, xy in zip(CORNER_ORDER, fc.corners_px, fc.pitch_targets, strict=True):
        lm[f"corner_{name}"] = {"approx": [float(uv[0]), float(uv[1])],
                                "image": [float(uv[0]), float(uv[1])], "snapped": False,
                                "note": picked_by, "pitch": [float(xy[0]), float(xy[1])],
                                "fit_residual_m": 0.0}
    return Calibration(
        view=view, method="homography", source=source, frame_index=int(frame_index),
        image_size=(int(image_size[0]), int(image_size[1])), length_m=float(length_m),
        width_m=float(width_m), params={"H_image_to_pitch": fc.H_image_to_pitch.tolist()},
        landmarks=lm,
        errors={"landmarks_used": 4, "landmarks_not_snapped": 4, "fit_rms_m": 0.0,
                "held_out_mean_m": None, "held_out_median_m": None, "held_out_max_m": None,
                "note": "4-corner homography: exact fit, no held-out error"},
        meta={"created_utc": utc_now(), "opencv_version": cv2.__version__,
              "method": "four_corner", "picked_by": picked_by,
              "opposite_edge_ratio": fc.opposite_edge_ratio, "aspect_px": fc.aspect_px,
              "rotated": fc.rotated})


def image_corners(mapper: PitchMapper, length_m: float, width_m: float) -> np.ndarray:
    """The 4 pitch corners in the image, ordered TL, TR, BR, BL by their position on screen
    (whatever pitch corner each one is): the corners a coach would click."""
    xy = np.array([[0, 0], [length_m, 0], [length_m, width_m], [0, width_m]], dtype=float)
    return order_corners(mapper.to_image(xy))


def order_corners(pts: Any) -> np.ndarray:
    """4 points sorted TL, TR, BR, BL on screen (by angle around their centroid)."""
    p = np.asarray(pts, dtype=float).reshape(4, 2)
    c = p.mean(axis=0)
    ang = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])  # TL ~ -135 deg, TR ~ -45, BR 45, BL 135
    return p[np.argsort(ang)]


# --------------------------------------------------------------------------- auto-detect


@dataclass
class CornerDetection:
    """Result of `detect_pitch_corners` (all pixel values at full frame resolution)."""

    found: bool  # a quadrilateral was found at all
    corners: np.ndarray | None  # (4, 2) TL, TR, BR, BL
    confidence: float  # 0..1, geometric mean of `parts` (0 when a hard check fails)
    accepted: bool  # confidence >= accept and no hard failure: ask the coach to confirm
    parts: dict[str, float]
    problems: list[str]  # coach-readable reasons for a low confidence
    method: str  # "approx_poly" | "min_area_rect" | "none"
    snapped_edges: int  # edges moved onto a painted boundary line
    line_error_m: float | None  # projected markings vs painted lines (median)
    timing_ms: float

    def summary(self) -> dict[str, Any]:
        return {"found": self.found, "accepted": self.accepted,
                "confidence": round(self.confidence, 3),
                "corners": None if self.corners is None else
                [[round(float(x), 1), round(float(y), 1)] for x, y in self.corners],
                "parts": {k: round(v, 3) for k, v in self.parts.items()},
                "problems": self.problems, "method": self.method,
                "snapped_edges": self.snapped_edges, "line_error_m": self.line_error_m,
                "timing_ms": round(self.timing_ms, 1)}


def grass_mask(frame: np.ndarray, hue: tuple[float, float], min_saturation: float,
               min_value: float) -> np.ndarray:
    """Grass pixels: the HSV hue/saturation band the team classifier uses to strip grass from
    shirt crops (`teams.grass_hue`, `teams.grass_min_saturation`), plus a brightness floor."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return (((hsv[..., 0] >= hue[0]) & (hsv[..., 0] <= hue[1]) & (hsv[..., 1] >= min_saturation)
             & (hsv[..., 2] >= min_value)).astype(np.uint8) * 255)


def _largest_component(mask: np.ndarray) -> tuple[np.ndarray, float]:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return np.zeros_like(mask), 0.0
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    comp = np.where(labels == i, 255, 0).astype(np.uint8)
    return comp, float(stats[i, cv2.CC_STAT_AREA]) / mask.size


def _quad_from_hull(hull: np.ndarray, eps_range: tuple[float, float]
                    ) -> tuple[np.ndarray | None, str]:
    """4 vertices from a convex hull: `cv2.approxPolyDP` with the smallest epsilon that gives
    exactly 4, else the `cv2.minAreaRect` box."""
    peri = cv2.arcLength(hull, True)
    for f in np.geomspace(eps_range[0], eps_range[1], 24):
        ap = cv2.approxPolyDP(hull, float(f) * peri, True)
        if len(ap) == 4:
            return order_corners(ap.reshape(4, 2)), "approx_poly"
        if len(ap) < 4:
            break
    box = cv2.boxPoints(cv2.minAreaRect(hull))
    return order_corners(box), "min_area_rect"


def _line_from(p: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = q - p
    return p, d / (np.linalg.norm(d) + 1e-12)


def _edge_candidates(quad: np.ndarray, lines: np.ndarray, s: dict[str, Any]
                     ) -> list[list[tuple[tuple[np.ndarray, np.ndarray], float]]]:
    """Candidate positions of each quad edge on a painted line.

    Per edge, a 2D search over the offsets of its two end points along the inward normal
    (from `outward_frac` outside to `inward_frac` inside) scores the share of sampled points
    that fall on the (slightly dilated) line mask. The best offset pairs with at least
    `min_support` that lie more than `candidate_sep_frac` of the quad's depth apart become
    candidates (up to `max_candidates`), each refined with `cv2.fitLine` on the line pixels
    near it. The grass edge itself is always the last candidate (no painted line).

    Several candidates matter: next to the boundary line there is often another straight
    feature (the edge of the artificial turf, a fence base, a run-off line) with as much
    support. Which one is the pitch boundary is decided by the markings inside the pitch
    (`_choose_edges`), not by the edge alone. Returns, per edge, [((point, point), support)].
    """
    h, w = lines.shape
    hit = cv2.dilate(lines, np.ones((3, 3), np.uint8)) > 0
    centre = quad.mean(axis=0)
    t = np.linspace(0.1, 0.9, int(s["samples"]))
    ys_all, xs_all = np.nonzero(lines)
    pix = np.stack([xs_all, ys_all], axis=1).astype(np.float64)
    out: list[list[tuple[tuple[np.ndarray, np.ndarray], float]]] = []
    for i in range(4):
        p, q = quad[i], quad[(i + 1) % 4]
        o, d = _line_from(p, q)
        n = np.array([-d[1], d[0]])
        if np.dot(centre - p, n) < 0:
            n = -n
        opp = 0.5 * (quad[(i + 2) % 4] + quad[(i + 3) % 4])
        depth = abs(float(np.dot(opp - p, n)))
        offs = np.arange(-round(float(s["outward_frac"]) * depth),
                         round(float(s["inward_frac"]) * depth) + 1, 1.0)
        a, b = np.meshgrid(offs, offs, indexing="ij")  # offset at p, offset at q
        base = p[None, :] * (1 - t[:, None]) + q[None, :] * t[:, None]  # (S, 2)
        off = a[..., None] * (1 - t) + b[..., None] * t  # (A, B, S)
        pts = base[None, None] + off[..., None] * n  # (A, B, S, 2)
        u = np.round(pts[..., 0]).astype(int)
        v = np.round(pts[..., 1]).astype(int)
        inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
        hits = np.zeros(u.shape, bool)
        hits[inside] = hit[v[inside], u[inside]]
        score = hits.mean(axis=-1).ravel()
        mean_off = ((a + b) / 2).ravel()
        sep = float(s["candidate_sep_frac"]) * depth
        cands: list[tuple[tuple[np.ndarray, np.ndarray], float]] = []
        taken: list[float] = []
        for j in np.argsort(-score, kind="stable"):
            if score[j] < float(s["min_support"]) or len(cands) >= int(s["max_candidates"]):
                break
            if any(abs(mean_off[j] - m) < sep for m in taken):
                continue
            taken.append(float(mean_off[j]))
            ja, jb = np.unravel_index(j, a.shape)
            p2, q2 = p + a[ja, jb] * n, q + b[ja, jb] * n
            o2, d2 = _line_from(p2, q2)
            rel = pix - o2
            along = rel @ d2
            dist = np.abs(rel @ np.array([-d2[1], d2[0]]))
            ln = np.linalg.norm(q2 - p2)
            near = (dist <= float(s["band_px"])) & (along >= 0.05 * ln) & (along <= 0.95 * ln)
            if near.sum() >= 10:
                vx, vy, x0, y0 = cv2.fitLine(pix[near].astype(np.float32), cv2.DIST_HUBER,
                                             0, 0.01, 0.01).ravel()
                o2, d2 = np.array([x0, y0], float), np.array([vx, vy], float)
            cands.append(((o2, o2 + d2), float(score[j])))
        cands.append(((p, q), 0.0))  # the grass edge: no painted line found or chosen
        out.append(cands)
    return out


def _corners_from_edges(edges: list[tuple[np.ndarray, np.ndarray]], quad: np.ndarray
                        ) -> np.ndarray:
    """Corners as intersections of adjacent edge lines (corner i = edge i-1 x edge i)."""
    corners = []
    for i in range(4):
        (p1, q1), (p2, q2) = edges[(i - 1) % 4], edges[i]
        x = _intersect((p1, q1 - p1), (p2, q2 - p2))
        corners.append(quad[i] if x is None else x)
    return np.array(corners, dtype=float)


def _choose_edges(quad: np.ndarray,
                  cands: list[list[tuple[tuple[np.ndarray, np.ndarray], float]]],
                  check: Any, max_shift_frac: float) -> tuple[np.ndarray, int, dict[str, Any]]:
    """Try every combination of edge candidates and keep the one whose projected pitch
    markings land on painted lines best: fewest marking samples with no painted line nearby
    (`not_found_fraction`), then the smallest median distance. `check(corners)` returns
    `line_alignment_error`'s result or None (impossible quad). Combinations that move a corner
    more than `max_shift_frac` of the quad's size (runaway snaps) are skipped. Returns the
    corners, the number of edges on a painted line, and the winning check."""
    import itertools

    size = max(np.ptp(quad[:, 0]), np.ptp(quad[:, 1]))
    best: tuple[float, float, int] | None = None
    best_out: tuple[np.ndarray, int, dict[str, Any]] = (quad, 0, {})
    for combo in itertools.product(*[range(len(c)) for c in cands]):
        edges = [cands[i][j][0] for i, j in enumerate(combo)]
        corners = _corners_from_edges(edges, quad)
        if not np.isfinite(corners).all() or np.abs(corners - quad).max() > max_shift_frac * size:
            continue
        res = check(order_corners(corners))
        if res is None or not np.isfinite(res["median_m"]):
            continue
        snapped = sum(1 for i, j in enumerate(combo) if cands[i][j][1] > 0)
        key = (float(res["not_found_fraction"]), float(res["median_m"]), -snapped)
        if best is None or key < best:
            best, best_out = key, (order_corners(corners), snapped, res)
    return best_out


def _edge_support(corners: np.ndarray, lines: np.ndarray, samples: int) -> list[float]:
    """Share of points along each edge (middle 80 %) that lie on a painted line."""
    h, w = lines.shape
    hit = cv2.dilate(lines, np.ones((3, 3), np.uint8)) > 0
    t = np.linspace(0.1, 0.9, samples)[:, None]
    out = []
    for i in range(4):
        p, q = corners[i], corners[(i + 1) % 4]
        pts = np.round(p * (1 - t) + q * t).astype(int)
        ok = (pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)
        out.append(float(hit[pts[ok, 1], pts[ok, 0]].sum()) / samples)
    return out


def detect_pitch_corners(frame: np.ndarray, cfg: dict[str, Any]) -> CornerDetection:
    """Find the 4 pitch corners of a top-down frame with OpenCV only (no learnt model).

    1. grass mask (`grass_mask`, the team classifier's HSV grass band) on a frame downscaled to
       `analysis_width_px`, closed (players, painted lines) and opened (specks);
    2. the largest connected component (`cv2.connectedComponentsWithStats`), its convex hull
       (`cv2.convexHull`) and a quadrilateral (`cv2.approxPolyDP`, else `cv2.minAreaRect`);
    3. each edge snapped onto the painted boundary line where visible (`line_mask` top-hat,
       `_snap_edges`, `cv2.fitLine`);
    4. confidence parts: quad area share, aspect vs L / W, boundary-line pixels on the edges,
       projected markings vs painted lines (`line_alignment_error` through the 4-corner
       homography: a wrong quad puts the halfway line and boxes off the paint), corners inside
       the frame, and the top-down check (opposite edges). Settings: `calibration.auto_detect`.

    The result is only a proposal: the API never analyses on unconfirmed corners.
    """
    import time as _time

    t0 = _time.perf_counter()
    ad = cfg["calibration"]["auto_detect"]
    cc = ad["confidence"]
    four = cfg["calibration"].get("four_corner", {})
    tcfg = cfg["teams"]
    L, W = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])
    h0, w0 = frame.shape[:2]
    k = min(1.0, float(ad["analysis_width_px"]) / w0)
    small = cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else frame
    h, w = small.shape[:2]

    def fail(msg: str, method: str = "none") -> CornerDetection:
        return CornerDetection(False, None, 0.0, False, {}, [msg], method, 0, None,
                               (_time.perf_counter() - t0) * 1000)

    g = grass_mask(small, (float(tcfg["grass_hue"][0]), float(tcfg["grass_hue"][1])),
                   float(tcfg["grass_min_saturation"]), float(ad["grass_min_value"]))
    cp, op = int(ad["close_px"]), int(ad["open_px"])
    g = cv2.morphologyEx(g, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cp, cp)))
    g = cv2.morphologyEx(g, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (op, op)))
    comp, comp_frac = _largest_component(g)
    if comp_frac < 0.5 * float(cc["min_area_frac"]):
        return fail("No large grass area found: is this a football pitch seen from above?")
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    quad, method = _quad_from_hull(hull, (float(ad["approx_eps"][0]), float(ad["approx_eps"][1])))
    if quad is None:
        return fail("Could not find the outline of the pitch.")
    lm = ad["line_mask"]
    lines = line_mask(small, int(lm["kernel_px"]), int(lm["threshold"]),
                      int(lm["max_saturation"]), int(lm["min_component_px"]))
    model = PitchModel(L, W, Markings.from_config(cfg))
    dist = line_distance_map(lines)
    four_loose = {**four, "min_area_frac": 0.0, "min_opposite_edge_ratio": 0.0}

    def check(c: np.ndarray) -> dict[str, Any] | None:
        try:
            fc_ = four_corner_homography(c, (w, h), L, W, four_loose)
        except CalibrationError:
            return None
        return line_alignment_error(fc_.mapper(), lines, model, 1.0, 2.0, dist=dist)

    cands = _edge_candidates(quad, lines, ad["snap"])
    corners, snapped, _ = _choose_edges(quad, cands, check,
                                        float(ad["snap"]["max_shift_frac"]))
    corners = order_corners(corners)
    support = _edge_support(corners, lines, int(ad["snap"]["samples"]))

    problems: list[str] = []
    parts: dict[str, float] = {}
    signed, horiz, vert, ratio = _quad_checks(corners)
    area_frac = abs(signed) / (w * h)
    lo, hi = float(cc["min_area_frac"]), float(cc["good_area_frac"])
    parts["area"] = float(np.clip((area_frac - lo) / max(hi - lo, 1e-9), 0, 1))
    if parts["area"] < 0.5:
        problems.append(f"the pitch fills only {area_frac:.0%} of the frame")
    aspect = max(horiz, vert) / max(min(horiz, vert), 1e-9)
    dev = abs(float(np.log(aspect / (L / W))))
    parts["aspect"] = float(np.clip(1 - dev / float(cc["aspect_tolerance"]), 0, 1))
    if parts["aspect"] < 0.5:
        problems.append(f"its shape ({aspect:.2f}:1) is far from a {L:g} x {W:g} m pitch")
    parts["boundary_lines"] = float(np.clip(np.mean(support) / float(cc["good_line_support"]),
                                            0, 1))
    if parts["boundary_lines"] < 0.5:
        problems.append("the painted boundary lines are hard to see along the outline")
    m = float(cc["corner_margin_px"])
    inside = ((corners[:, 0] > m) & (corners[:, 0] < w - 1 - m) & (corners[:, 1] > m)
              & (corners[:, 1] < h - 1 - m))
    parts["corners_in_view"] = float(inside.mean())
    if not inside.all():
        problems.append(f"{int((~inside).sum())} corner(s) are cut off by the edge of the frame")
    line_err = None
    hard = False
    try:
        fc = four_corner_homography(corners, (w, h), L, W, four_loose)
        le = line_alignment_error(fc.mapper(), lines, model, 1.0, 2.0, dist=dist)
        nf = float(le["not_found_fraction"])
        med = float(le["median_m"]) if np.isfinite(le["median_m"]) else float("inf")
        line_err = None if not np.isfinite(med) else round(med, 3)
        # markings with no painted line near them (> 2 m off) are what a wrong outline looks
        # like: the matched ones still sit close, so the median alone stays small
        found = float(np.clip(1 - nf / float(cc["max_markings_not_found"]), 0, 1))
        parts["markings"] = float(np.clip(1 - med / float(cc["max_line_error_m"]), 0, 1)) * found
        quad_mask = np.zeros_like(lines)
        cv2.fillConvexPoly(quad_mask, np.round(corners).astype(np.int32), 255)
        density = float((lines[quad_mask > 0] > 0).mean()) if (quad_mask > 0).any() else 1.0
        if density > float(cc["max_line_density"]):  # clutter / texture, not painted lines
            parts["markings"] = 0.0
            problems.append(f"{density:.0%} of the area looks like painted lines: too cluttered "
                            "to find the pitch markings")
        elif parts["markings"] < 0.5:
            problems.append(f"{nf:.0%} of the pitch markings do not line up with this outline")
    except CalibrationError as exc:
        hard = True
        problems.append(str(exc))
        parts["markings"] = 0.0
    min_ratio = float(four.get("min_opposite_edge_ratio", 0.6))
    if ratio < min_ratio:
        hard = True
        problems.append("the view is tilted, not top-down (the far side looks much shorter)")
    vals = np.array(list(parts.values()), dtype=float)
    conf = 0.0 if hard or (vals <= 0).any() else float(np.exp(np.mean(np.log(vals))))
    accepted = conf >= float(cc["accept"]) and not hard
    return CornerDetection(True, corners / k, conf, accepted, parts, problems, method, snapped,
                           line_err, (_time.perf_counter() - t0) * 1000)


def draw_corner_overlay(frame: np.ndarray, corners: Any, length_m: float, width_m: float,
                        title: str, max_width_px: int = 1280,
                        colour: tuple[int, int, int] = (80, 255, 200)) -> np.ndarray:
    """The frame (downscaled to `max_width_px`) with the pitch outline through the 4 corners,
    numbered 1-4 (TL, TR, BR, BL) and the markings a 4-corner homography would put there, so
    a coach can see at a glance whether the outline sits on the pitch."""
    k = min(1.0, max_width_px / frame.shape[1])
    img = cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 \
        else frame.copy()
    pts = np.asarray(corners, dtype=float).reshape(4, 2) * k
    h, w = img.shape[:2]
    try:
        fc = four_corner_homography(pts, (w, h), length_m, width_m,
                                    {"min_area_frac": 0.0, "min_opposite_edge_ratio": 0.0,
                                     "max_outside_frac": 1.0})
        mapper = fc.mapper()
        for name, poly in PitchModel(length_m, width_m).lines(0.5).items():
            if name.startswith(("touch_", "goal_")):
                continue
            uv = mapper.to_image(poly)
            cv2.polylines(img, [np.round(uv).astype(np.int32).reshape(-1, 1, 2)], False,
                          (255, 255, 255), 1, cv2.LINE_AA)
    except CalibrationError:
        pass
    th = max(2, int(round(w / 400)))
    cv2.polylines(img, [np.round(pts).astype(np.int32).reshape(-1, 1, 2)], True, colour, th,
                  cv2.LINE_AA)
    fs = max(0.5, w / 1600)
    for i, (x, y) in enumerate(pts):
        c = (int(round(x)), int(round(y)))
        cv2.circle(img, c, int(14 * fs), (20, 20, 20), -1, cv2.LINE_AA)
        cv2.circle(img, c, int(14 * fs), colour, th, cv2.LINE_AA)
        cv2.putText(img, str(i + 1), (c[0] - int(6 * fs), c[1] + int(6 * fs)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * fs, (255, 255, 255), max(1, th - 1),
                    cv2.LINE_AA)
    bar = int(36 * fs)
    cv2.rectangle(img, (0, 0), (w, bar), (20, 20, 20), -1)
    cv2.putText(img, title, (10, int(bar * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * fs,
                (255, 255, 255), max(1, int(1.5 * fs)), cv2.LINE_AA)
    return img


def render_pitch_view(size: tuple[int, int], corners_px: Any, length_m: float = 105.0,
                      width_m: float = 68.0, runoff_m: float = 4.0,
                      players: list[tuple[float, float, tuple[int, int, int]]] | None = None,
                      seed: int = 42, line_m: float = 0.15, noise: float = 4.0) -> np.ndarray:
    """A generated top-down frame (tests and `scripts/eval_autodetect.py --synthetic`): mown
    grass with stripes, white IFAB markings, `runoff_m` of grass outside the lines, a grey
    surround, optional players (pitch x, y, BGR colour) and pixel noise. `corners_px` are the
    image positions of the pitch corners (0, W), (L, W), (L, 0), (0, 0), i.e. TL, TR, BR, BL
    for an untilted view; any 4 points give a perspective (tilted) view."""
    w, h = int(size[0]), int(size[1])
    L, W, r = float(length_m), float(width_m), float(runoff_m)
    ppm = 12.0
    tw, th = int((L + 2 * r) * ppm), int((W + 2 * r) * ppm)
    tex = np.zeros((th, tw, 3), np.uint8)
    for i, x0 in enumerate(np.arange(-r, L + r, 5.0)):  # mowing stripes every 5 m
        u0, u1 = int((x0 + r) * ppm), int((x0 + 5.0 + r) * ppm)
        tex[:, u0:u1] = (52, 128, 46) if i % 2 else (60, 146, 54)

    def tx(xy: np.ndarray) -> np.ndarray:  # pitch metres -> texture pixels (y up)
        xy = np.asarray(xy, float).reshape(-1, 2)
        return np.stack([(xy[:, 0] + r) * ppm, (W + r - xy[:, 1]) * ppm], axis=1)

    thick = max(1, int(round(line_m * ppm)))
    for poly in PitchModel(L, W).lines(0.25).values():
        cv2.polylines(tex, [np.round(tx(poly)).astype(np.int32).reshape(-1, 1, 2)], False,
                      (235, 240, 238), thick, cv2.LINE_AA)
    for x, y, col in players or []:
        c = np.round(tx([[x, y]])[0]).astype(int)
        cv2.circle(tex, (int(c[0]), int(c[1])), int(0.45 * ppm), col, -1, cv2.LINE_AA)
    targets = np.array([[0.0, W], [L, W], [L, 0.0], [0.0, 0.0]])
    H_p2i = cv2.getPerspectiveTransform(targets.astype(np.float32),
                                        np.asarray(corners_px, np.float32).reshape(4, 2))
    A = np.array([[1 / ppm, 0, -r], [0, -1 / ppm, W + r], [0, 0, 1]])  # texture -> pitch
    out = cv2.warpPerspective(tex, H_p2i @ A, (w, h), flags=cv2.INTER_AREA,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(96, 104, 112))
    rng = np.random.default_rng(seed)
    out = np.clip(out.astype(np.float32) + rng.normal(0, noise, out.shape), 0, 255)
    return out.astype(np.uint8)
