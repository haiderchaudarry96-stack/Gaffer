"""Video backend of the agent's vision tools: OpenCV 5 on the source video (AGENT_DESIGN §2).

- **Quality** (`check_frame_quality`): `quality_frames` sample times spread over the window; at
  each one the frame at t and the frame `pair_dt_s` later are decoded.
  * geometry per sample: the drifting drone view is re-anchored to its calibration frame
    (`drift.GeometryProvider`: `cv2.phaseCorrelate` + `cv2.findTransformECC` on the line image)
    and its painted-line error decides `homography_ok`; a static view (side) must still align
    with its calibration frame (ORB + `cv2.estimateAffinePartial2D`, small shift, no zoom);
  * camera motion per pair: ORB matches + `cv2.estimateAffinePartial2D` (RANSAC, so moving
    players are outliers) give the shift of the image centre (px/s) and the scale (zoom);
  * cuts between consecutive samples: HSV histogram correlation (`cv2.compareHist`); two
    samples that no longer align at all count as a view change.
- **Re-analysis** (`reanalyse_window`): `perception.pipeline.run` on the window at the requested
  rate (tracking = output = `sample_fps`), reusing the full-match team colours and attacking
  directions (`<match>.teams.json`). Windows snap to a 5 s grid; the processing time is
  estimated first (window x fps x measured s/frame) and the call refused above
  `max_reanalysis_s` or the per-match OpenCV budget; results are cached on disk (a cut-off run
  resumes for free; cache hits cost nothing).
- **Evidence frame** (`render_evidence`): the decoded frame with the MatchState positions
  projected back through that frame's homography and the team's formation lines (from the
  template fit) drawn on it; saved as JPEG (`write_image`) so it keeps its 1280 px width.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gaffer.agent.verify import Geometry
from gaffer.config import repo_path
from gaffer.schema import MatchState, parse_match_state


class VisionError(RuntimeError):
    """A vision tool cannot run (no video, unreadable video, pipeline failure)."""


class OverBudget(VisionError):
    """A re-analysis would take longer than allowed; says what would fit."""

    def __init__(self, msg: str, max_window_s: float) -> None:
        super().__init__(msg)
        self.max_window_s = max_window_s


@dataclass(frozen=True)
class VisionConfig:
    """`agent.vision` from config.yaml."""

    quality_frames: int
    pair_dt_s: float
    analysis_width_px: int
    orb_features: int
    min_inliers: int
    cut_min_hist_corr: float
    static_max_shift_px: float
    max_zoom_change: float
    max_reanalysis_s: float
    max_opencv_s_per_match: float
    s_per_frame: dict[str, float]
    grid_s: float
    cache_dir: str
    evidence_width_px: int
    evidence_max_bytes: int
    evidence_format: str = "jpg"
    evidence_jpeg_quality: int = 90

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> VisionConfig:
        v = cfg["agent"]["vision"]
        return cls(int(v["quality_frames"]), float(v["pair_dt_s"]), int(v["analysis_width_px"]),
                   int(v["orb_features"]), int(v["min_inliers"]), float(v["cut_min_hist_corr"]),
                   float(v["static_max_shift_px"]),
                   float(cfg["agent"]["verify"]["geometry"]["max_zoom_change"]),
                   float(v["max_reanalysis_s"]), float(v["max_opencv_s_per_match"]),
                   {k: float(x) for k, x in v["s_per_frame"].items()}, float(v["grid_s"]),
                   str(v["cache_dir"]), int(v["evidence_width_px"]),
                   int(v["evidence_max_bytes"]), str(v.get("evidence_format", "jpg")),
                   int(v.get("evidence_jpeg_quality", 90)))


# --------------------------------------------------------------------------- frame measures


@dataclass
class Motion:
    """How frame `b` moved relative to frame `a` (native pixels)."""

    aligned: bool
    shift_px: float  # displacement of the image centre
    scale: float  # > 1: zoomed in
    inliers: int


def _small_gray(frame: np.ndarray, width: int) -> tuple[np.ndarray, float]:
    k = min(1.0, width / frame.shape[1])
    small = cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else frame
    g = small if small.ndim == 2 else cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return g, k


def estimate_motion(a: np.ndarray, b: np.ndarray, vc: VisionConfig) -> Motion:
    """Similarity transform a -> b from ORB matches (`cv2.estimateAffinePartial2D`, RANSAC)."""
    ga, k = _small_gray(a, vc.analysis_width_px)
    gb, _ = _small_gray(b, vc.analysis_width_px)
    orb = cv2.ORB_create(vc.orb_features)
    ka, da = orb.detectAndCompute(ga, None)
    kb, db = orb.detectAndCompute(gb, None)
    if da is None or db is None or len(ka) < vc.min_inliers or len(kb) < vc.min_inliers:
        return Motion(False, math.nan, 1.0, 0)
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(matches) < vc.min_inliers:
        return Motion(False, math.nan, 1.0, 0)
    src = np.float32([ka[m.queryIdx].pt for m in matches])
    dst = np.float32([kb[m.trainIdx].pt for m in matches])
    A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                         ransacReprojThreshold=2.0)
    n = int(inl.sum()) if inl is not None else 0
    if A is None or n < vc.min_inliers:
        return Motion(False, math.nan, 1.0, n)
    c = np.array([ga.shape[1] / 2, ga.shape[0] / 2, 1.0])
    shift = float(np.linalg.norm(A @ c - c[:2])) / k
    scale = float(math.sqrt(abs(np.linalg.det(A[:, :2]))))
    return Motion(True, shift, scale, n)


def hist_correlation(a: np.ndarray, b: np.ndarray, width: int = 320) -> float:
    """HSV hue-saturation histogram correlation (`cv2.compareHist`): ~1 same shot, low = cut."""
    hs = []
    for f in (a, b):
        k = min(1.0, width / f.shape[1])
        small = cv2.resize(f, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        hs.append(cv2.normalize(h, h).flatten())
    return float(cv2.compareHist(hs[0], hs[1], cv2.HISTCMP_CORREL))


#: geometry of one frame: (homography ok, line error in metres or None)
GeometryFn = Callable[[np.ndarray], tuple[bool, float | None]]


@dataclass
class QualityMeasure:
    """What `measure_quality` found (LLM-facing summary in `summary()`)."""

    times: list[float]
    homography_ok: list[bool]
    line_error_m: list[float | None]
    shift_px_per_s: list[float]  # per pair (nan = pair did not align)
    zoom: list[float]  # |scale - 1| per aligned comparison
    cuts: list[float]  # sample times where a cut / view change starts
    problems: list[str] = field(default_factory=list)
    opencv_ms: float = 0.0

    @property
    def geometry(self) -> Geometry:
        finite = [s for s in self.shift_px_per_s if np.isfinite(s)]
        unaligned_pairs = len(finite) < len(self.shift_px_per_s)
        return Geometry(
            homography_ok_share=float(np.mean(self.homography_ok)) if self.homography_ok else 0.0,
            # a pair of frames that does not align at all: the camera moved too fast
            shift_px_per_s_max=math.inf if unaligned_pairs else max(finite, default=0.0),
            zoom_change_max=max(self.zoom, default=0.0),
            camera_cut=bool(self.cuts))

    def summary(self) -> dict[str, Any]:
        g = self.geometry
        errs = [e for e in self.line_error_m if e is not None]
        return {"frames_checked": len(self.times),
                "homography_ok_share": round(g.homography_ok_share, 2),
                "line_error_m_median": round(float(np.median(errs)), 3) if errs else None,
                "camera_shift_px_per_s_max": (round(g.shift_px_per_s_max, 1)
                                              if math.isfinite(g.shift_px_per_s_max)
                                              else "frames do not align"),
                "zoom_change_max": round(g.zoom_change_max, 3),
                "camera_cut": g.camera_cut}


def measure_quality(samples: list[tuple[float, np.ndarray, np.ndarray]], pair_dt: float,
                    geometry: GeometryFn, vc: VisionConfig) -> QualityMeasure:
    """Camera checks on `samples` = [(t, frame at t, frame at t + pair_dt)] (module docstring)."""
    t0 = time.perf_counter()
    q = QualityMeasure([], [], [], [], [], [])
    prev: tuple[float, np.ndarray] | None = None
    for t, a, b in samples:
        ok, err = geometry(a)
        q.times.append(t)
        q.homography_ok.append(bool(ok))
        q.line_error_m.append(err)
        m = estimate_motion(a, b, vc)
        q.shift_px_per_s.append(m.shift_px / pair_dt if m.aligned else math.nan)
        if m.aligned:
            q.zoom.append(abs(m.scale - 1.0))
        if prev is not None:
            corr = hist_correlation(prev[1], a)
            mm = estimate_motion(prev[1], a, vc)
            if corr < vc.cut_min_hist_corr or not mm.aligned:
                q.cuts.append(prev[0])
            elif mm.aligned:
                q.zoom.append(abs(mm.scale - 1.0))
        prev = (t, a)
    q.opencv_ms = round((time.perf_counter() - t0) * 1000, 1)
    return q


def problems_of(q: QualityMeasure, cfg: dict[str, Any]) -> list[str]:
    """Plain-words problems for the LLM (thresholds: `agent.verify.geometry`)."""
    g, gc = q.geometry, cfg["agent"]["verify"]["geometry"]
    out = []
    if g.homography_ok_share < float(gc["min_homography_ok_share"]):
        out.append(f"pitch lines fit in only {g.homography_ok_share:.0%} of frames")
    if not math.isfinite(g.shift_px_per_s_max):
        out.append("frames 0.5 s apart do not align: camera moving fast")
    elif g.shift_px_per_s_max > float(gc["max_shift_px_per_s"]):
        out.append(f"camera moves {g.shift_px_per_s_max:.0f} px/s")
    if g.zoom_change_max > float(gc["max_zoom_change"]):
        out.append(f"zoom changes {g.zoom_change_max:.0%}")
    if q.cuts:
        out.append(f"cut or view change after t={q.cuts[0]:.0f} s")
    return out


# --------------------------------------------------------------------------- backend


@dataclass
class Reanalysis:
    match: MatchState
    window: tuple[float, float]
    fps: float
    processing_s: float  # OpenCV time of the run that produced it (cached: the original run)
    estimate_s: float
    cache_hit: bool
    timing: dict[str, float]


def snap(lo: float, hi: float, grid: float, bounds: tuple[float, float]) -> tuple[float, float]:
    """Window snapped outwards to the grid, inside the footage."""
    a = math.floor(lo / grid + 1e-9) * grid
    b = math.ceil(hi / grid - 1e-9) * grid
    return max(a, bounds[0]), min(b, bounds[1])


class VideoBackend:
    """OpenCV on one match's source video, for the agent's vision tools."""

    def __init__(self, match: MatchState, view: str, cfg: dict[str, Any],
                 teams: dict[str, Any] | None = None,
                 runner: Callable[..., Any] | None = None) -> None:
        if match.source_video is None:
            raise VisionError(f"{match.match_id} has no source_video: no video backend")
        self.match, self.view, self.cfg = match, view, cfg
        self.vc = VisionConfig.from_config(cfg)
        self.uri = match.source_video.uri
        self.teams = teams
        self._runner = runner
        self._source: Any = None
        self._geo: Any = None
        self.spent_s = 0.0  # OpenCV seconds spent on re-analyses for this match (not cached)
        self.cache_dir = repo_path(self.vc.cache_dir)

    @classmethod
    def for_match_file(cls, path: str | Path, match: MatchState, view: str,
                       cfg: dict[str, Any], **kw: Any) -> VideoBackend:
        """Backend for a pipeline MatchState saved with its `<name>.teams.json`."""
        p = repo_path(path)
        side = p.with_name(p.name.removesuffix(".json") + ".teams.json")
        teams = json.loads(side.read_text(encoding="utf-8")) if side.exists() else None
        return cls(match, view, cfg, teams, **kw)

    # ---------------------------------------------------------------- video access
    @property
    def source(self) -> Any:
        if self._source is None:
            from gaffer.perception.video import VideoError, VideoSource

            try:
                self._source = VideoSource(self.uri)
            except VideoError as exc:
                raise VisionError(str(exc)) from exc
        return self._source

    def geometry_provider(self) -> Any:
        if self._geo is None:
            from gaffer.perception.drift import GeometryProvider
            from gaffer.perception.pitch import Calibration, PitchModel

            calib = Calibration.for_view(self.cfg, self.view)
            self._geo = GeometryProvider(calib, self.cfg, self.view,
                                         PitchModel(calib.length_m, calib.width_m))
            if not self._geo.anchor:  # static view: align with the calibration frame instead
                from gaffer.perception.video import VideoSource

                src = VideoSource(calib.source)
                self._ref = src.read(src.start_s + calib.frame_index / src.native_fps)
        return self._geo

    def frame_geometry(self, frame: np.ndarray) -> tuple[bool, float | None]:
        geo = self.geometry_provider()
        if geo.anchor:
            g = geo.for_frame(frame)
            return bool(g.homography_ok), g.reprojection_error_m
        m = estimate_motion(self._ref, frame, self.vc)
        ok = (m.aligned and m.shift_px <= self.vc.static_max_shift_px
              and abs(m.scale - 1.0) <= self.vc.max_zoom_change)
        return ok, geo.static_err if ok else None

    def read(self, t: float) -> np.ndarray:
        from gaffer.perception.video import VideoError

        try:
            return self.source.read(t)
        except VideoError as exc:
            raise VisionError(str(exc)) from exc

    # ---------------------------------------------------------------- quality
    def quality(self, lo: float, hi: float) -> QualityMeasure:
        """Camera checks over [lo, hi] (decode + OpenCV time in `opencv_ms`)."""
        from gaffer.perception.video import VideoError

        t0 = time.perf_counter()
        n, dt = self.vc.quality_frames, self.vc.pair_dt_s
        ts = [lo + (i + 0.5) * (hi - lo) / n for i in range(n)]
        ts = [t for t in ts if t + dt < self.source.end_s]
        want = sorted({round(t, 3) for t in ts} | {round(t + dt, 3) for t in ts})
        try:
            frames = {round(t, 3): f for t, _, _, f in self.source.frames(want)}
        except VideoError as exc:
            raise VisionError(str(exc)) from exc
        samples = [(t, frames[round(t, 3)], frames[round(t + dt, 3)]) for t in ts
                   if round(t, 3) in frames and round(t + dt, 3) in frames]
        if not samples:
            raise VisionError(f"no decodable frames in {lo:.0f}-{hi:.0f} s")
        q = measure_quality(samples, dt, self.frame_geometry, self.vc)
        q.opencv_ms = round((time.perf_counter() - t0) * 1000, 1)
        return q

    # ---------------------------------------------------------------- re-analysis
    def estimate_s(self, lo: float, hi: float, fps: float) -> float:
        return (hi - lo) * fps * self.vc.s_per_frame.get(self.view, max(self.vc.s_per_frame
                                                                       .values()))

    def max_window_s(self, fps: float) -> float:
        per_s = fps * self.vc.s_per_frame.get(self.view, 1.0)
        fit = min(self.vc.max_reanalysis_s,
                  max(0.0, self.vc.max_opencv_s_per_match - self.spent_s)) / per_s
        return math.floor(fit / self.vc.grid_s) * self.vc.grid_s

    def cache_path(self, lo: float, hi: float, fps: float) -> Path:
        key = json.dumps({"uri": self.uri, "view": self.view, "w": [lo, hi], "fps": fps,
                          "teams": self.teams, "perception": self.cfg["perception"],
                          "detector": self.cfg["detector"], "tracker": self.cfg.get("tracker"),
                          "teams_cfg": self.cfg.get("teams")}, sort_keys=True, default=str)
        h = hashlib.sha1(key.encode()).hexdigest()[:10]
        return self.cache_dir / (f"{self.match.match_id}_{lo:.0f}-{hi:.0f}_{fps:g}fps_{h}.json")

    def reanalyse(self, lo: float, hi: float, fps: float) -> Reanalysis:
        """Perception on [lo, hi) at `fps` (snapped by the caller), cached; budget-checked."""
        est = self.estimate_s(lo, hi, fps)
        path = self.cache_path(lo, hi, fps)
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return Reanalysis(parse_match_state(d["match_state"]), (lo, hi), fps,
                              float(d["processing_s"]), est, True, d.get("timing", {}))
        if est > self.vc.max_reanalysis_s:
            raise OverBudget(f"estimated {est:.0f} s of OpenCV > {self.vc.max_reanalysis_s:.0f}"
                             f" s for {hi - lo:.0f} s at {fps:g} fps", self.max_window_s(fps))
        if self.spent_s + est > self.vc.max_opencv_s_per_match:
            raise OverBudget(f"match OpenCV budget: {self.spent_s:.0f} s spent + {est:.0f} s > "
                             f"{self.vc.max_opencv_s_per_match:.0f} s", self.max_window_s(fps))
        t0 = time.perf_counter()
        res = self._run(lo, hi, fps)
        dt = time.perf_counter() - t0
        self.spent_s += dt
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"match_state": json.loads(res.match.model_dump_json(
            by_alias=True)), "processing_s": round(dt, 1), "estimate_s": round(est, 1),
            "timing": {k: round(v, 2) for k, v in res.timing.items()}}), encoding="utf-8")
        return Reanalysis(res.match, (lo, hi), fps, dt, est, False, dict(res.timing))

    def _run(self, lo: float, hi: float, fps: float) -> Any:
        from gaffer.perception.detector import DetectorError
        from gaffer.perception.pipeline import PipelineError, run
        from gaffer.perception.pitch import CalibrationError
        from gaffer.perception.team_classifier import TeamModel
        from gaffer.perception.video import VideoError
        from gaffer.schema import ContractError

        kw: dict[str, Any] = {}
        if self.teams:
            kw["team_model"] = TeamModel.from_dict(self.teams["team_model"])
            kw["directions"] = dict(self.teams["directions"])
        runner = self._runner or run
        try:
            return runner(self.uri, view=self.view, start_s=lo, end_s=hi, fps=fps,
                          track_fps=fps, cfg=self.cfg,
                          match_id=f"{self.match.match_id}_re{lo:.0f}-{hi:.0f}", **kw)
        except (VideoError, CalibrationError, DetectorError, PipelineError,
                ContractError) as exc:
            raise VisionError(f"re-analysis failed: {exc}") from exc

    # ---------------------------------------------------------------- evidence frame
    def evidence_frame(self, t: float, players: dict[str, np.ndarray],
                       lines: list[np.ndarray], team: str, colours: dict[str, Any]
                       ) -> np.ndarray:
        """Frame at `t` with players (pitch metres, per team) projected back through this
        frame's geometry and the team's formation lines; cropped to the pitch."""
        frame = self.read(t)
        geo = self.geometry_provider()
        mapper = geo.for_frame(frame).mapper if geo.anchor else geo.base
        img = frame.copy()
        s = frame.shape[1] / 1280.0  # line widths for the downscaled result
        for line in lines:
            if len(line) > 1:
                uv = mapper.to_image(line).round().astype(np.int32)
                cv2.polylines(img, [uv.reshape(-1, 1, 2)], False, (0, 215, 255),
                              max(2, int(3 * s)), cv2.LINE_AA)
        for side, xy in players.items():
            if not len(xy):
                continue
            col = tuple(int(c) for c in colours.get(side, (200, 200, 200)))
            for u, v in mapper.to_image(xy).round().astype(int):
                r = int((9 if side == team else 6) * s)
                cv2.circle(img, (int(u), int(v)), r, col, max(2, int(2 * s)), cv2.LINE_AA)
        L, W = self.match.pitch.length_m, self.match.pitch.width_m
        corners = mapper.to_image(np.array([[-3, -3], [L + 3, -3], [L + 3, W + 3],
                                            [-3, W + 3]], float))
        x0, y0 = np.clip(corners.min(0), 0, None).astype(int)
        x1 = int(min(frame.shape[1], corners[:, 0].max()))
        y1 = int(min(frame.shape[0], corners[:, 1].max()))
        crop = img[y0:y1, x0:x1] if x1 > x0 + 50 and y1 > y0 + 50 else img
        k = self.vc.evidence_width_px / crop.shape[1]
        return cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)


def write_image(path: Path, img: np.ndarray, max_bytes: int, jpeg_quality: int = 90) -> int:
    """Evidence image (OpenCV encoder chosen by the suffix: .jpg or .png) no larger than
    `max_bytes`: downscaled in steps if needed. JPEG keeps a 4K evidence frame at its 1280 px
    width (a 400 KB PNG shrank it to ~570 px, step 5)."""
    ext = path.suffix.lower()
    params = ([cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)] if ext in (".jpg", ".jpeg")
              else [cv2.IMWRITE_PNG_COMPRESSION, 9])
    for _ in range(8):
        ok, buf = cv2.imencode(ext, img, params)
        if not ok:
            raise VisionError(f"OpenCV could not encode {path}")
        if len(buf) <= max_bytes:
            break
        img = cv2.resize(img, None, fx=0.85, fy=0.85, interpolation=cv2.INTER_AREA)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())
    return len(buf)
