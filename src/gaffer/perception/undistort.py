"""Side-view geometry: which model maps the TeamTrack side panorama onto the pitch best?

The side "fisheye" view is really a ~6500 x 1000 stitched panorama (DATA_NOTES section 6). We
do not assume a model; four candidates are fitted to the same picked landmarks and compared
by **held-out (leave-one-out) landmark error** and line-alignment error:

- `homography`: one `cv2.findHomography` for the whole panorama (a pinhole camera);
- `sectioned`: the panorama split into vertical sections at given image columns, one
  `cv2.findHomography` per section (landmarks near a boundary are shared);
- `fisheye`: `cv2.fisheye` camera model (K, D = k1..k4, pose of the pitch plane), fitted with
  `cv2.fisheye.calibrate` (single planar view) or, if that fails, by least squares on
  `cv2.fisheye.projectPoints`; image -> pitch via `cv2.fisheye.undistortPoints`;
- `cylindrical`: a camera on a vertical-axis cylinder (the usual panorama-stitching surface):
  column = f_u * azimuth, row = f_v * height / horizontal range.

The winner is written to `data/calibration/side.json`; `mapper_from_params` rebuilds it.
"""

from __future__ import annotations

import json
from typing import Any

import cv2
import numpy as np
from scipy.optimize import least_squares

from gaffer.config import repo_path
from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    HomographyMapper,
    Markings,
    PitchMapper,
    PitchModel,
    SnapSettings,
    draw_overlay,
    fit_homography,
    leave_one_out,
    line_alignment_error,
    line_mask,
    snap_two_pass,
    utc_now,
)

# --------------------------------------------------------------------------- mappers


class SectionedHomographyMapper:
    """One homography per vertical image section. `bounds_u` are the interior boundaries."""

    def __init__(self, bounds_u: list[float], Hs: list[np.ndarray]) -> None:
        if len(Hs) != len(bounds_u) + 1:
            raise CalibrationError("sectioned mapper needs len(Hs) == len(bounds_u) + 1")
        self.bounds = [float(b) for b in bounds_u]
        self.maps = [HomographyMapper(H) for H in Hs]

    def section(self, u: np.ndarray) -> np.ndarray:
        return np.searchsorted(self.bounds, np.asarray(u, dtype=float), side="right")

    def to_pitch(self, uv: np.ndarray) -> np.ndarray:
        uv = np.asarray(uv, dtype=float).reshape(-1, 2)
        out = np.zeros_like(uv)
        sec = self.section(uv[:, 0])
        for k, m in enumerate(self.maps):
            sel = sec == k
            if sel.any():
                out[sel] = m.to_pitch(uv[sel])
        return out

    def to_image(self, xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        cand = np.stack([m.to_image(xy) for m in self.maps])  # (K, N, 2)
        edges = [-np.inf, *self.bounds, np.inf]
        out = np.zeros_like(xy)
        for i in range(len(xy)):
            best, best_d = 0, np.inf
            for k in range(len(self.maps)):
                u = cand[k, i, 0]
                d = 0.0 if edges[k] <= u < edges[k + 1] else min(abs(u - edges[k]),
                                                                  abs(u - edges[k + 1]))
                if d < best_d:
                    best, best_d = k, d
            out[i] = cand[best, i]
        return out


def _ray_plane(C: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Intersect rays C + s d (d: (N, 3)) with the pitch plane z = 0. Rays that do not hit the
    plane in front of the camera give NaN."""
    with np.errstate(divide="ignore", invalid="ignore"):
        s = -C[2] / d[:, 2]
    p = C[None, :] + s[:, None] * d
    p[s <= 0] = np.nan
    return p[:, :2]


class FisheyeMapper:
    """`cv2.fisheye` camera: pitch (x, y, 0) -> image with `cv2.fisheye.projectPoints`, image
    -> pitch with `cv2.fisheye.undistortPoints` and a ray/plane intersection."""

    def __init__(self, K: np.ndarray, D: np.ndarray, rvec: np.ndarray, tvec: np.ndarray) -> None:
        self.K = np.asarray(K, dtype=float).reshape(3, 3)
        self.D = np.asarray(D, dtype=float).reshape(4, 1)
        self.rvec = np.asarray(rvec, dtype=float).reshape(3, 1)
        self.tvec = np.asarray(tvec, dtype=float).reshape(3, 1)
        self.R = cv2.Rodrigues(self.rvec)[0]
        self.C = (-self.R.T @ self.tvec).ravel()

    def to_image(self, xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        obj = np.concatenate([xy, np.zeros((len(xy), 1))], axis=1).reshape(-1, 1, 3)
        uv, _ = cv2.fisheye.projectPoints(obj, self.rvec, self.tvec, self.K, self.D)
        return uv.reshape(-1, 2)

    def to_pitch(self, uv: np.ndarray) -> np.ndarray:
        uv = np.asarray(uv, dtype=float).reshape(-1, 1, 2)
        n = cv2.fisheye.undistortPoints(uv, self.K, self.D).reshape(-1, 2)
        rays = np.concatenate([n, np.ones((len(n), 1))], axis=1) @ self.R  # R^T @ ray
        return _ray_plane(self.C, rays)

    def params(self) -> dict[str, Any]:
        return {"K": self.K, "D": self.D.ravel(), "rvec": self.rvec.ravel(),
                "tvec": self.tvec.ravel()}


class CylindricalMapper:
    """Camera on a vertical-axis cylinder: u = cu + f_u * azimuth, v = cv + f_v * Yc / rho,
    with (Xc, Yc, Zc) = R @ (P - C) and rho = sqrt(Xc^2 + Zc^2)."""

    def __init__(self, f_u: float, f_v: float, cu: float, c_v: float, rvec: np.ndarray,
                 C: np.ndarray) -> None:
        self.f_u, self.f_v, self.cu, self.cv = float(f_u), float(f_v), float(cu), float(c_v)
        self.rvec = np.asarray(rvec, dtype=float).reshape(3)
        self.C = np.asarray(C, dtype=float).reshape(3)
        self.R = cv2.Rodrigues(self.rvec)[0]

    def to_image(self, xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        P = np.concatenate([xy, np.zeros((len(xy), 1))], axis=1) - self.C
        Pc = P @ self.R.T
        rho = np.hypot(Pc[:, 0], Pc[:, 2])
        u = self.cu + self.f_u * np.arctan2(Pc[:, 0], Pc[:, 2])
        v = self.cv + self.f_v * Pc[:, 1] / np.maximum(rho, 1e-9)
        return np.stack([u, v], axis=1)

    def to_pitch(self, uv: np.ndarray) -> np.ndarray:
        uv = np.asarray(uv, dtype=float).reshape(-1, 2)
        phi = (uv[:, 0] - self.cu) / self.f_u
        h = (uv[:, 1] - self.cv) / self.f_v
        rays_c = np.stack([np.sin(phi), h, np.cos(phi)], axis=1)
        return _ray_plane(self.C, rays_c @ self.R)

    def params(self) -> dict[str, Any]:
        return {"f_u": self.f_u, "f_v": self.f_v, "cu": self.cu, "cv": self.cv,
                "rvec": self.rvec, "C": self.C}


def mapper_from_params(method: str, params: dict[str, Any]) -> PitchMapper:
    """Rebuild a saved side-view mapper (used by `Calibration.mapper`)."""
    if method == "homography":
        return HomographyMapper(np.array(params["H_image_to_pitch"]))
    if method == "sectioned":
        return SectionedHomographyMapper(params["bounds_u"],
                                         [np.array(H) for H in params["H_image_to_pitch"]])
    if method == "fisheye":
        return FisheyeMapper(np.array(params["K"]), np.array(params["D"]),
                             np.array(params["rvec"]), np.array(params["tvec"]))
    if method == "cylindrical":
        return CylindricalMapper(params["f_u"], params["f_v"], params["cu"], params["cv"],
                                 np.array(params["rvec"]), np.array(params["C"]))
    raise CalibrationError(f"unknown calibration method {method!r}")


# --------------------------------------------------------------------------- fitting


def _initial_pose(init: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """(rvec, camera centre) for a camera at `camera_m` looking across the pitch (+y), level.
    Camera axes: x right (= pitch x), y down (= -z), z forward (= pitch y)."""
    R0 = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
    return cv2.Rodrigues(R0)[0].ravel(), np.asarray(init["camera_m"], dtype=float)


def fit_sectioned(img: np.ndarray, world: np.ndarray, bounds_u: list[float], margin_px: float
                  ) -> SectionedHomographyMapper:
    """One homography per section; a landmark within `margin_px` of a boundary is used by both
    neighbouring sections."""
    edges = [-np.inf, *bounds_u, np.inf]
    Hs = []
    for k in range(len(edges) - 1):
        sel = (img[:, 0] >= edges[k] - margin_px) & (img[:, 0] < edges[k + 1] + margin_px)
        if sel.sum() < 4:
            raise CalibrationError(f"section {k} has only {int(sel.sum())} landmarks (need 4)")
        Hs.append(fit_homography(img[sel], world[sel])[0])
    return SectionedHomographyMapper(bounds_u, Hs)


def fit_fisheye(img: np.ndarray, world: np.ndarray, size: tuple[int, int],
                init: dict[str, Any], start: FisheyeMapper | None = None
                ) -> tuple[FisheyeMapper, str]:
    """Fit the `cv2.fisheye` model. Tries `cv2.fisheye.calibrate` first (single planar view,
    intrinsic guess, fixed skew); falls back to least squares on `cv2.fisheye.projectPoints`
    when OpenCV refuses (ill-conditioned single view). Returns (mapper, how)."""
    w, h = size
    obj = np.concatenate([world, np.zeros((len(world), 1))], axis=1).reshape(1, -1, 3)
    if start is None:
        f = float(init["fisheye_f_px"])
        K0 = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=float)
        rvec0, C0 = _initial_pose(init)
        R0 = cv2.Rodrigues(rvec0)[0]
        tvec0 = -R0 @ C0
        D0 = np.zeros(4)
    else:
        K0, D0, rvec0, tvec0 = start.K, start.D.ravel(), start.rvec.ravel(), start.tvec.ravel()
    try:
        # OpenCV 5 moved the fisheye flags into the unified cv2.CALIB_* namespace
        flags = cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_RECOMPUTE_EXTRINSIC | cv2.CALIB_FIX_SKEW
        crit = (cv2.TERM_CRITERIA_COUNT + cv2.TERM_CRITERIA_EPS, 200, 1e-9)
        rms, K, D, rv, tv = cv2.fisheye.calibrate(
            [obj.astype(np.float64)], [img.reshape(1, -1, 2).astype(np.float64)], (w, h),
            K0.copy(), D0.reshape(4, 1).copy(), flags=flags, criteria=crit)
        m = FisheyeMapper(K, D, rv[0], tv[0])
        if np.isfinite(rms) and rms < float(init.get("fisheye_max_rms_px", 50.0)):
            return m, f"cv2.fisheye.calibrate (rms {rms:.1f} px)"
    except cv2.error:
        pass

    def resid(p: np.ndarray) -> np.ndarray:
        K = np.array([[p[0], 0, p[2]], [0, p[1], p[3]], [0, 0, 1]])
        uv, _ = cv2.fisheye.projectPoints(obj.reshape(-1, 1, 3), p[8:11], p[11:14], K, p[4:8])
        return (uv.reshape(-1, 2) - img).ravel()

    x0 = np.concatenate([[K0[0, 0], K0[1, 1], K0[0, 2], K0[1, 2]], D0, rvec0, tvec0])
    sol = least_squares(resid, x0, method="trf", x_scale="jac", max_nfev=4000)
    p = sol.x
    K = np.array([[p[0], 0, p[2]], [0, p[1], p[3]], [0, 0, 1]])
    return FisheyeMapper(K, p[4:8], p[8:11], p[11:14]), "least squares on cv2.fisheye.projectPoints"


def fit_cylindrical(img: np.ndarray, world: np.ndarray, size: tuple[int, int],
                    init: dict[str, Any], start: CylindricalMapper | None = None
                    ) -> CylindricalMapper:
    """Least-squares fit of the cylindrical camera (focal lengths, centre, pose)."""
    if start is None:
        rvec0, C0 = _initial_pose(init)
        f = float(init["cylinder_f_px"])
        x0 = np.concatenate([[f, f, float(init["cylinder_cu_px"]), float(init["horizon_v_px"])],
                             rvec0, C0])
    else:
        x0 = np.concatenate([[start.f_u, start.f_v, start.cu, start.cv], start.rvec, start.C])

    def resid(p: np.ndarray) -> np.ndarray:
        return (CylindricalMapper(*p[:4], p[4:7], p[7:10]).to_image(world) - img).ravel()

    sol = least_squares(resid, x0, method="trf", x_scale="jac", max_nfev=4000)
    p = sol.x
    return CylindricalMapper(*p[:4], p[4:7], p[7:10])


# --------------------------------------------------------------------------- images


def birdseye(frame: np.ndarray, mapper: PitchMapper, model: PitchModel, px_per_m: float,
             margin_m: float = 3.0) -> np.ndarray:
    """Top-down rectification of the frame through any mapper (`cv2.remap`), with the model
    pitch lines drawn on top: straight, aligned lines = a good calibration."""
    L, W = model.length, model.width
    ow, oh = int((L + 2 * margin_m) * px_per_m), int((W + 2 * margin_m) * px_per_m)
    xs = (np.arange(ow) + 0.5) / px_per_m - margin_m
    ys = W + margin_m - (np.arange(oh) + 0.5) / px_per_m  # far touchline at the top
    gx, gy = np.meshgrid(xs, ys)
    uv = mapper.to_image(np.stack([gx.ravel(), gy.ravel()], axis=1))
    uv = np.nan_to_num(uv, nan=-1.0)
    map_x = uv[:, 0].reshape(oh, ow).astype(np.float32)
    map_y = uv[:, 1].reshape(oh, ow).astype(np.float32)
    out = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(40, 40, 40))
    for poly in model.lines(0.25).values():
        px = np.stack([(poly[:, 0] + margin_m) * px_per_m,
                       (W + margin_m - poly[:, 1]) * px_per_m], axis=1)
        cv2.polylines(out, [np.round(px).astype(np.int32).reshape(-1, 1, 2)], False,
                      (255, 255, 0), 1, cv2.LINE_AA)
    return out


# --------------------------------------------------------------------------- side calibration


def _fit_method(method: str, img: np.ndarray, world: np.ndarray, size: tuple[int, int],
                scfg: dict[str, Any], start: Any = None) -> tuple[PitchMapper, str]:
    if method == "homography":
        return HomographyMapper(fit_homography(img, world)[0]), "cv2.findHomography"
    if method.startswith("sectioned"):
        bounds = [float(b) for b in scfg["sections"][method]]
        return (fit_sectioned(img, world, bounds, float(scfg["section_margin_px"])),
                f"cv2.findHomography per section, bounds {bounds}")
    if method == "fisheye":
        return fit_fisheye(img, world, size, scfg["init"], start)
    if method == "cylindrical":
        return fit_cylindrical(img, world, size, scfg["init"], start), "least squares"
    raise CalibrationError(f"unknown method {method}")


def _params(method: str, mapper: PitchMapper) -> dict[str, Any]:
    if isinstance(mapper, HomographyMapper):
        return {"H_image_to_pitch": mapper.H / mapper.H[2, 2]}
    if isinstance(mapper, SectionedHomographyMapper):
        return {"bounds_u": mapper.bounds, "H_image_to_pitch": [m.H / m.H[2, 2]
                                                               for m in mapper.maps]}
    return mapper.params()  # type: ignore[attr-defined]


def calibrate_side(frame: np.ndarray, points: dict[str, Any], cfg: dict[str, Any]) -> int:
    """Fit every candidate model, compare by held-out error, save the winner and images."""
    ccfg = cfg["calibration"]
    vcfg = ccfg["views"]["side"]
    scfg = vcfg["models"]
    markings = Markings.from_config(cfg)
    model = PitchModel(float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"]), markings)
    lmw = model.landmarks()
    lm_opts = dict(vcfg["line_mask"])
    mask = line_mask(frame, **lm_opts)
    spot_mask = line_mask(frame, **{**lm_opts, "min_component_px": 0})
    snap = SnapSettings(**{k: float(v) if k != "min_pixels" else int(v)
                           for k, v in vcfg["snap"].items()})

    def fit_h(i: np.ndarray, w: np.ndarray) -> HomographyMapper:
        return HomographyMapper(fit_homography(i, w)[0])

    snapped = snap_two_pass(mask, spot_mask, points["landmarks"], points.get("hints") or {},
                            snap, model, fit_h)
    exclude = set(points.get("exclude") or [])
    names = [n for n, r in snapped.items() if r["image"] is not None and n not in exclude]
    img = np.array([snapped[n]["image"] for n in names], dtype=float)
    world = np.array([lmw[n] for n in names], dtype=float)
    size = (frame.shape[1], frame.shape[0])
    le = ccfg["line_error"]
    odir = repo_path(ccfg["overlay_dir"])
    odir.mkdir(parents=True, exist_ok=True)
    y0, y1 = (int(v) for v in vcfg["overlay_rows"])

    results: dict[str, dict[str, Any]] = {}
    mappers: dict[str, PitchMapper] = {}
    for method in scfg["candidates"]:
        try:
            mapper, how = _fit_method(method, img, world, size, scfg)
        except (CalibrationError, cv2.error, np.linalg.LinAlgError) as exc:
            results[method] = {"error": str(exc)}
            continue

        def refit(i: np.ndarray, w: np.ndarray, _m: str = method, _s: Any = mapper
                  ) -> PitchMapper:
            return _fit_method(_m, i, w, size, scfg, start=_s)[0]

        loo = leave_one_out(names, img, world, refit)
        fit_err = np.linalg.norm(mapper.to_pitch(img) - world, axis=1)
        line_err = line_alignment_error(mapper, mask, model, float(le["sample_step_m"]),
                                        float(le["max_search_m"]))
        vals = np.array([v for v in loo.values() if np.isfinite(v)])
        results[method] = {
            "how": how,
            "held_out_mean_m": round(float(vals.mean()), 3) if len(vals) else None,
            "held_out_median_m": round(float(np.median(vals)), 3) if len(vals) else None,
            "held_out_max_m": round(float(vals.max()), 3) if len(vals) else None,
            "held_out_failed": len(names) - len(vals),
            "fit_rms_m": round(float(np.sqrt(np.nanmean(fit_err**2))), 3),
            "line_alignment": line_err,
            "held_out_per_landmark_m": {k: round(v, 3) for k, v in loo.items()},
        }
        mappers[method] = mapper
        r = results[method]
        title = (f"side / {method}: held-out mean {r['held_out_mean_m']} m, max "
                 f"{r['held_out_max_m']} m | line error median {line_err['median_m']} m")
        ov = draw_overlay(frame, mapper, model, snapped, loo, title, thickness=1)
        cv2.imwrite(str(odir / f"side_overlay_{method}.jpg"), ov[y0:y1],
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
        cv2.imwrite(str(odir / f"side_birdseye_{method}.jpg"),
                    birdseye(frame, mapper, model, float(vcfg["birdseye_px_per_m"])))
        if isinstance(mapper, FisheyeMapper):
            _save_fisheye_undistorted(frame, mapper, odir)

    ok = {m: r for m, r in results.items() if r.get("held_out_mean_m") is not None}
    if not ok:
        raise CalibrationError(f"no side-view model could be fitted: {results}")
    best = min(ok, key=lambda m: (ok[m]["held_out_mean_m"], ok[m]["line_alignment"]["median_m"]))
    for n in names:
        snapped[n]["pitch"] = [round(v, 3) for v in lmw[n]]
    calib = Calibration(
        view="side", method="sectioned" if best.startswith("sectioned") else best,
        source=points["source"], frame_index=int(points["frame_index"]), image_size=size,
        length_m=model.length, width_m=model.width, params=_params(best, mappers[best]),
        landmarks=snapped, errors={"chosen": best, **results[best],
                                   "landmarks_used": len(names),
                                   "landmarks_not_snapped": [n for n, r in snapped.items()
                                                             if not r["snapped"]]},
        meta={"created_utc": utc_now(), "opencv_version": cv2.__version__,
              "picked_by": points.get("picked_by", ""),
              "orientation": points.get("orientation", ""),
              "excluded_landmarks": sorted(exclude)})
    out = calib.save(repo_path(ccfg["dir"]) / "side.json")
    cmp_path = repo_path(ccfg["dir"]) / "side_model_comparison.json"
    cmp_path.write_text(json.dumps({"chosen": best, "landmarks_used": len(names),
                                    "results": results}, indent=2, default=_np_json),
                        encoding="utf-8")
    cv2.imwrite(str(odir / "side_original.jpg"), frame[y0:y1])

    print(f"cv2 {cv2.__version__} | view side | {len(names)} landmarks "
          f"(not snapped: {calib.errors['landmarks_not_snapped'] or 'none'})")
    print(f"{'model':16s} {'held-out mean':>13s} {'median':>8s} {'max':>8s} {'fit rms':>8s} "
          f"{'line med':>9s} {'line p90':>9s} {'not found':>9s}")
    for m, r in results.items():
        if "error" in r:
            print(f"{m:16s} FAILED: {r['error']}")
            continue
        la = r["line_alignment"]
        print(f"{m:16s} {r['held_out_mean_m']:>11.3f} m {r['held_out_median_m']:>6.3f} m "
              f"{r['held_out_max_m']:>6.3f} m {r['fit_rms_m']:>6.3f} m {la['median_m']:>7.3f} m "
              f"{la['p90_m']:>7.3f} m {la['not_found_fraction']:>8.1%}   ({r['how']})")
    print(f"chosen: {best}\n-> {out}\n-> {cmp_path}\n-> {odir}/side_*.jpg")
    return 0


def _save_fisheye_undistorted(frame: np.ndarray, m: FisheyeMapper, odir: Any) -> None:
    """Before/after for the fisheye model: `cv2.fisheye.initUndistortRectifyMap` + `remap`."""
    h, w = frame.shape[:2]
    newK = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
        m.K, m.D, (w, h), np.eye(3), balance=0.0)
    m1, m2 = cv2.fisheye.initUndistortRectifyMap(m.K, m.D, np.eye(3), newK, (w, h),
                                                 cv2.CV_16SC2)
    cv2.imwrite(str(odir / "side_fisheye_undistorted.jpg"),
                cv2.remap(frame, m1, m2, cv2.INTER_LINEAR))


def _np_json(o: Any) -> Any:
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.floating | np.integer):
        return o.item()
    raise TypeError(type(o))
