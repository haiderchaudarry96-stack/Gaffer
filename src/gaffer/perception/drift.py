"""Re-anchor a nearly static camera to its calibration frame (top-view drone drift).

The drone hovers rather than being locked: ~5 px drift within a 30 s clip and more between
clips (DATA_NOTES section 2). The calibration homography is valid for one reference frame, so
every other frame is aligned to it on the **pitch-line image** (players and grass texture
excluded):

1. alignment image: line mask (`pitch.line_mask`), downscaled, Gaussian-blurred so ECC has a
   smooth basin;
2. initial translation from `cv2.phaseCorrelate`;
3. refinement with `cv2.findTransformECC` (affine by default);
4. fallback: ORB features (`cv2.ORB_create`) + `cv2.estimateAffinePartial2D` (RANSAC).

The result `A` maps frame pixels to reference pixels, so the frame's mapper is
`reference_mapper.warped(A)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from gaffer.perception.pitch import (
    Calibration,
    PitchMapper,
    PitchModel,
    line_alignment_error,
    line_mask,
)

MOTIONS = {"translation": cv2.MOTION_TRANSLATION, "euclidean": cv2.MOTION_EUCLIDEAN,
           "affine": cv2.MOTION_AFFINE}


@dataclass(frozen=True)
class DriftSettings:
    """From config `drift`."""

    scale: float
    blur_sigma_px: float
    motion: str
    iterations: int
    eps: float
    min_correlation: float
    line_mask: dict[str, Any]
    coarse_factor: float = 0.0  # > 0: ECC first on a copy at this fraction of `scale`, then refine

    @classmethod
    def from_config(cls, cfg: dict[str, Any], view: str) -> DriftSettings:
        d = cfg["drift"]
        c2f = d.get("coarse_to_fine") or {}
        return cls(float(d["scale"]), float(d["blur_sigma_px"]), str(d["motion"]),
                   int(d["iterations"]), float(d["eps"]), float(d["min_correlation"]),
                   dict(cfg["calibration"]["views"][view]["line_mask"]),
                   float(c2f.get("factor", 0.5)) if c2f.get("enabled") else 0.0)


@dataclass
class Alignment:
    """Frame -> reference transform and how it was obtained."""

    A: np.ndarray  # 2x3, full-resolution pixels, frame -> reference
    method: str  # "ecc" | "orb" | "identity"
    correlation: float  # ECC correlation (or ORB inlier ratio)
    shift_px: float  # displacement of the image centre

    @property
    def ok(self) -> bool:
        return self.method != "identity"


def _scaled_line_params(s: DriftSettings) -> dict[str, Any]:
    lm = dict(s.line_mask)
    lm["kernel_px"] = max(3, int(round(lm["kernel_px"] * s.scale)) | 1)
    lm["min_component_px"] = int(lm.get("min_component_px", 0) * s.scale * s.scale)
    lm["close_px"] = 0
    return lm


def downscale(frame: np.ndarray, s: DriftSettings) -> np.ndarray:
    return cv2.resize(frame, None, fx=s.scale, fy=s.scale, interpolation=cv2.INTER_AREA)


def small_line_mask(frame: np.ndarray, s: DriftSettings, small: np.ndarray | None = None
                    ) -> np.ndarray:
    """Binary line mask at `s.scale` resolution: the frame is downscaled first and the mask
    computed with proportionally scaled kernels (~16x cheaper than masking the 4K frame)."""
    return line_mask(downscale(frame, s) if small is None else small, **_scaled_line_params(s))


def alignment_image(frame: np.ndarray, s: DriftSettings, mask: np.ndarray | None = None,
                    small: np.ndarray | None = None) -> np.ndarray:
    """Smoothed pitch-line image (float32, 0..1) at `s.scale` resolution.

    Uses the continuous top-hat response, gated by the cleaned binary line mask: binarising
    after downscaling throws away sub-pixel edge positions and biased the alignment by ~0.9 px
    (synthetic test), while the gate still suppresses grass speckle and players.
    """
    small = downscale(frame, s) if small is None else small
    lm = _scaled_line_params(s)
    m = line_mask(small, **lm) if mask is None else mask
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (lm["kernel_px"], lm["kernel_px"]))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k).astype(np.float32)
    gate = cv2.dilate(m, np.ones((5, 5), np.uint8)) > 0
    img = np.clip(th / (2.0 * float(lm["threshold"])), 0.0, 1.0) * gate
    return cv2.GaussianBlur(img.astype(np.float32), (0, 0), s.blur_sigma_px)


def _to_full(W_small: np.ndarray, scale: float) -> np.ndarray:
    """Rescale a 2x3 transform estimated on downscaled images to full resolution."""
    S = np.diag([scale, scale, 1.0])
    W3 = np.vstack([W_small, [0, 0, 1]])
    return (np.linalg.inv(S) @ W3 @ S)[:2]


def _shift(A: np.ndarray, size: tuple[int, int]) -> float:
    c = np.array([size[0] / 2, size[1] / 2, 1.0])
    return float(np.linalg.norm(A @ c - c[:2]))


def _coarse_start(ref_img: np.ndarray, img: np.ndarray, warp: np.ndarray, s: DriftSettings,
                  crit: tuple[int, int, float]) -> np.ndarray:
    """Coarse-to-fine start: ECC on copies at `coarse_factor` of the working scale (a wider basin
    and ~16x fewer pixels at 0.25), its warp rescaled as the start of the normal ECC. If the coarse
    pass fails or correlates worse than `min_correlation`, the phase-correlation start is kept."""
    f = s.coarse_factor
    rc = cv2.resize(ref_img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ic = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    (dxc, dyc), _ = cv2.phaseCorrelate(rc, ic)
    wc = np.array([[1, 0, dxc], [0, 1, dyc]], dtype=np.float32)
    try:
        cc, wc = cv2.findTransformECC(rc, ic, wc, MOTIONS[s.motion], crit, None, 5)
    except cv2.error:
        return warp
    if cc < s.min_correlation:
        return warp
    out = wc.astype(np.float32).copy()
    out[:, 2] /= f  # translation in the finer image's pixels; the linear part is scale-free
    return out


def estimate_alignment(ref_img: np.ndarray, img: np.ndarray, s: DriftSettings,
                       size: tuple[int, int], ref_gray: np.ndarray | None = None,
                       gray: np.ndarray | None = None) -> Alignment:
    """Transform taking frame pixels to reference pixels (see module docstring).

    `ref_img`/`img` come from `alignment_image`; `ref_gray`/`gray` (full-resolution grey
    frames) enable the ORB fallback.
    """
    # phaseCorrelate returns the shift of `img` relative to `ref_img`
    (dx, dy), _ = cv2.phaseCorrelate(ref_img, img)
    # ECC warp maps template (reference) coordinates to input (frame) coordinates
    warp = np.array([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, s.iterations, s.eps)
    if 0.0 < s.coarse_factor < 1.0:
        warp = _coarse_start(ref_img, img, warp, s, crit)
    try:
        cc, warp = cv2.findTransformECC(ref_img, img, warp, MOTIONS[s.motion], crit, None, 5)
        if cc >= s.min_correlation:
            ref_to_frame = _to_full(warp.astype(np.float64), s.scale)
            A = cv2.invertAffineTransform(ref_to_frame)
            return Alignment(A, "ecc", float(cc), _shift(A, size))
    except cv2.error:
        cc = 0.0
    if ref_gray is not None and gray is not None:
        orb = cv2.ORB_create(4000)
        k1, d1 = orb.detectAndCompute(gray, None)
        k2, d2 = orb.detectAndCompute(ref_gray, None)
        if d1 is not None and d2 is not None:
            matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
            if len(matches) >= 12:
                src = np.float32([k1[m.queryIdx].pt for m in matches])
                dst = np.float32([k2[m.trainIdx].pt for m in matches])
                A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                     ransacReprojThreshold=3.0)
                if A is not None and inl is not None and inl.mean() > 0.3:
                    return Alignment(A, "orb", float(inl.mean()), _shift(A, size))
    return Alignment(np.array([[1.0, 0, 0], [0, 1.0, 0]]), "identity", float(cc), 0.0)


# --------------------------------------------------------------------------- per-frame geometry


class ScaledMapper:
    """A mapper for a resized copy of the image (pixels multiplied by `k`)."""

    def __init__(self, mapper: PitchMapper, k: float) -> None:
        self.mapper, self.k = mapper, float(k)

    def to_image(self, xy: np.ndarray) -> np.ndarray:
        return self.mapper.to_image(xy) * self.k

    def to_pitch(self, uv: np.ndarray) -> np.ndarray:
        return self.mapper.to_pitch(np.asarray(uv, dtype=float) / self.k)


@dataclass
class FrameGeometry:
    """Image -> pitch mapping for one frame, plus the `quality` facts the contract wants."""

    mapper: PitchMapper
    homography_ok: bool
    reprojection_error_m: float | None
    alignment: Alignment | None


class GeometryProvider:
    """Per-frame geometry for one view: the calibration mapper, re-anchored to every frame for
    a drifting camera (`drift.views`), with a per-frame line-alignment error.

    For a camera that does not drift (side view: 0.3 px per clip, DATA_NOTES) the calibration
    mapper is used as-is and `reprojection_error_m` is the calibration's held-out error.
    """

    def __init__(self, calib: Calibration, cfg: dict[str, Any], view: str,
                 model: PitchModel) -> None:
        self.calib, self.model, self.view = calib, model, view
        self.base = calib.mapper()
        self.anchor = view in cfg["drift"]["views"]
        self.max_err = float(cfg["drift"]["homography_ok_max_error_m"])
        le = cfg["calibration"]["line_error"]
        self.step, self.search = float(le["sample_step_m"]) * 2, float(le["max_search_m"])
        self.static_err = float(calib.errors.get("held_out_mean_m") or 0.0)
        if self.anchor:
            from gaffer.perception.video import VideoSource

            self.s = DriftSettings.from_config(cfg, view)
            src = VideoSource(calib.source)
            ref = src.read(src.start_s + calib.frame_index / src.native_fps)
            self.ref_img = alignment_image(ref, self.s)
            self.ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
            self.size = (ref.shape[1], ref.shape[0])

    def for_frame(self, frame: np.ndarray) -> FrameGeometry:
        """Geometry of this frame (re-anchored if the view drifts)."""
        if not self.anchor:
            return FrameGeometry(self.base, True, round(self.static_err, 3), None)
        sm_img = downscale(frame, self.s)
        small = small_line_mask(frame, self.s, sm_img)
        al = estimate_alignment(self.ref_img, alignment_image(frame, self.s, small, sm_img), self.s,
                                self.size, self.ref_gray, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        mapper = self.base.warped(al.A)  # type: ignore[attr-defined]
        err = line_alignment_error(ScaledMapper(mapper, self.s.scale), small, self.model,
                                   self.step, self.search)["median_m"]
        err_v = None if not np.isfinite(err) else round(float(err), 3)
        ok = al.ok and err_v is not None and err_v <= self.max_err
        return FrameGeometry(mapper, ok, err_v, al)

    def for_frame_static(self) -> FrameGeometry:
        """The reference calibration without re-anchoring (no frame needed)."""
        return FrameGeometry(self.base, True, round(self.static_err, 3), None)
