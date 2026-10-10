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
                         step_m: float, max_search_m: float, include: Iterable[str] | None = None
                         ) -> dict[str, Any]:
    """How far the projected pitch lines sit from the painted lines, in metres.

    Model lines are sampled every `step_m`, projected into the image, and the distance to the
    nearest line-centre pixel (`line_centres`) is read from `cv2.distanceTransform`. Pixels are
    converted to metres with the local scale perpendicular to the line. Samples with no painted
    line within `max_search_m` (occluded, out of view, faded) are counted as `not_found`
    rather than errors.
    """
    h, w = mask.shape
    centre = line_centres(mask)
    dist = cv2.distanceTransform((centre == 0).astype(np.uint8), cv2.DIST_L2, 5)
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
        line_errs = []
        for (u, v), sc in zip(uv, scale, strict=True):
            if not (0 <= u < w and 0 <= v < h) or sc <= 1e-6:
                continue
            total += 1
            e = float(dist[int(v), int(u)]) / sc
            if e > max_search_m:
                not_found += 1
                continue
            line_errs.append(e)
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
