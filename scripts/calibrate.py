"""Calibrate a camera view onto the pitch (metres) from picked pitch landmarks.

Two steps:
1. Landmarks: `data/calibration/<view>_points.json` holds approximate pixel positions of named
   pitch landmarks (corners, penalty-area corners, centre circle, ...) on one reference frame.
   Pick them by hand with `--click` (OpenCV window: left-click = place the landmark shown in the
   title, `s` = skip it, `u` = undo, `q`/Esc = done), or edit the JSON.
2. Fit: every landmark is snapped onto the painted lines (local `cv2.fitLine` fits on a top-hat
   line mask, intersected), the pitch size is fitted from the fixed-size IFAB markings, and the
   image -> pitch mapping is fitted (`cv2.findHomography` for the top view). Reports the
   held-out (leave-one-out) landmark error and the line-alignment error in metres, writes
   `data/calibration/<view>.json` and an overlay image with every point and the projected lines.

Usage:
    py scripts\\calibrate.py --view top
    py scripts\\calibrate.py --view top --click          # re-pick the landmarks by hand
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    HomographyMapper,
    Markings,
    PitchModel,
    SnapSettings,
    draw_overlay,
    fit_homography,
    fit_pitch_size,
    leave_one_out,
    line_alignment_error,
    line_mask,
    snap_two_pass,
    utc_now,
)


def read_frame(source: str, index: int) -> np.ndarray:
    """One frame of a video, with a clear error if the file is missing or unreadable."""
    path = repo_path(source)
    if not path.exists():
        raise CalibrationError(f"Video not found: {path}")
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise CalibrationError(f"OpenCV could not open {path} (unreadable or unsupported codec)")
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise CalibrationError(f"Could not read frame {index} of {path}")
    return frame


def click_landmarks(frame: np.ndarray, names: list[str], existing: dict[str, list[float]],
                    max_width: int = 1800) -> dict[str, list[float]]:
    """Interactive picking in an OpenCV window. Returns {name: [u, v]} in native pixels."""
    scale = min(1.0, max_width / frame.shape[1])
    base = cv2.resize(frame, None, fx=scale, fy=scale)
    picked: dict[str, list[float]] = {}
    order = list(names)
    i = 0
    click: list[tuple[int, int]] = []

    def on_mouse(event: int, x: int, y: int, *_: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            click.append((x, y))

    win = "calibrate"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    while i < len(order):
        name = order[i]
        img = base.copy()
        for n, (u, v) in picked.items():
            cv2.drawMarker(img, (int(u * scale), int(v * scale)), (0, 0, 255),
                           cv2.MARKER_CROSS, 14, 2)
            cv2.putText(img, n, (int(u * scale) + 6, int(v * scale) - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        if name in existing:
            u, v = existing[name]
            cv2.circle(img, (int(u * scale), int(v * scale)), 8, (0, 255, 255), 1)
        cv2.setWindowTitle(win, f"[{i + 1}/{len(order)}] click: {name}   (s=skip, u=undo, q=done)")
        cv2.imshow(win, img)
        key = cv2.waitKey(30) & 0xFF
        if click:
            x, y = click.pop()
            picked[name] = [x / scale, y / scale]
            i += 1
        elif key == ord("s"):
            i += 1
        elif key == ord("u") and i > 0:
            i -= 1
            picked.pop(order[i], None)
        elif key in (ord("q"), 27):
            break
    cv2.destroyWindow(win)
    return picked


def masks_for(frame: np.ndarray, vcfg: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """(cleaned line mask, unfiltered mask for small spots) with the view's settings."""
    lm = dict(vcfg["line_mask"])
    raw = line_mask(frame, **{**lm, "min_component_px": 0})
    return line_mask(frame, **lm), raw


def snap_settings(vcfg: dict[str, Any]) -> SnapSettings:
    return SnapSettings(**{k: float(v) if k != "min_pixels" else int(v)
                           for k, v in vcfg["snap"].items()})


def calibrate_homography(frame: np.ndarray, points: dict[str, Any], cfg: dict[str, Any],
                         view: str) -> tuple[Calibration, np.ndarray, np.ndarray]:
    """Snap, fit the pitch size, fit the homography, measure errors. Returns the calibration,
    the overlay image and the line mask."""
    vcfg = cfg["calibration"]["views"][view]
    ccfg = cfg["calibration"]
    markings = Markings.from_config(cfg)
    mask, spot_mask = masks_for(frame, vcfg)
    snap = snap_settings(vcfg)
    L0, W0 = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])

    def fit(i: np.ndarray, w: np.ndarray) -> HomographyMapper:
        return HomographyMapper(fit_homography(i, w)[0])

    snapped = snap_two_pass(mask, spot_mask, points["landmarks"], points.get("hints") or {},
                            snap, PitchModel(L0, W0, markings), fit)
    names = [n for n, lm in snapped.items() if lm["image"] is not None]
    if len(names) < 4:
        raise CalibrationError(f"only {len(names)} landmarks usable; need at least 4")
    img = np.array([snapped[n]["image"] for n in names], dtype=float)

    fitted_L, fitted_W, _, fit_rms_px = fit_pitch_size(names, img, L0, W0, markings)
    tol = float(ccfg["keep_default_size_within"])
    agrees = abs(fitted_L / L0 - 1) <= tol and abs(fitted_W / W0 - 1) <= tol
    L, W = (L0, W0) if (agrees or not ccfg["fit_pitch_size"]) else (round(fitted_L, 1),
                                                                     round(fitted_W, 1))
    model = PitchModel(L, W, markings)
    lm_world = model.landmarks()
    world = np.array([lm_world[n] for n in names], dtype=float)

    H, inl = fit_homography(img, world)
    mapper = HomographyMapper(H)
    resid = np.linalg.norm(mapper.to_pitch(img) - world, axis=1)
    loo = leave_one_out(names, img, world, fit)
    le = ccfg["line_error"]
    line_err = line_alignment_error(mapper, mask, model, float(le["sample_step_m"]),
                                    float(le["max_search_m"]))
    loo_arr = np.array(list(loo.values()))
    errors = {
        "landmarks_used": len(names),
        "landmarks_not_snapped": [n for n, lm in snapped.items() if not lm["snapped"]],
        "fit_rms_m": round(float(np.sqrt(np.mean(resid**2))), 3),
        "held_out_mean_m": round(float(loo_arr.mean()), 3),
        "held_out_median_m": round(float(np.median(loo_arr)), 3),
        "held_out_max_m": round(float(loo_arr.max()), 3),
        "held_out_worst": max(loo, key=loo.get),
        "held_out_per_landmark_m": {k: round(v, 3) for k, v in loo.items()},
        "line_alignment": line_err,
    }
    for n, r in zip(names, resid, strict=True):
        snapped[n]["pitch"] = [round(v, 3) for v in lm_world[n]]
        snapped[n]["fit_residual_m"] = round(float(r), 3)
    calib = Calibration(
        view=view, method="homography", source=points["source"],
        frame_index=int(points["frame_index"]),
        image_size=(frame.shape[1], frame.shape[0]), length_m=L, width_m=W,
        params={"H_image_to_pitch": H / H[2, 2]},
        landmarks=snapped, errors=errors,
        meta={"created_utc": utc_now(), "opencv_version": cv2.__version__,
              "pitch_size_fit": {"fitted_length_m": round(fitted_L, 2),
                                 "fitted_width_m": round(fitted_W, 2),
                                 "fit_rms_px": round(fit_rms_px, 2),
                                 "default_length_m": L0, "default_width_m": W0,
                                 "agrees_within_tolerance": bool(agrees), "tolerance": tol},
              "picked_by": points.get("picked_by", ""),
              "orientation": points.get("orientation", "")})
    title = (f"{view}: {len(names)} landmarks | pitch {L:g} x {W:g} m (fit {fitted_L:.1f} x "
             f"{fitted_W:.1f}) | held-out mean {errors['held_out_mean_m']:.2f} m, max "
             f"{errors['held_out_max_m']:.2f} m | line error median "
             f"{line_err['median_m']:.2f} m")
    overlay = draw_overlay(frame, mapper, model, snapped, loo, title)
    return calib, overlay, mask


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Calibrate a view onto the pitch")
    ap.add_argument("--view", choices=["top", "side"], required=True)
    ap.add_argument("--click", action="store_true", help="pick the landmarks by hand first")
    ap.add_argument("--points", default=None,
                    help="landmark file (default: <calibration dir>/<view>_points.json)")
    args = ap.parse_args(argv)

    cdir = Path(cfg["calibration"]["dir"])
    points_path = repo_path(args.points or cdir / f"{args.view}_points.json")
    try:
        if not points_path.exists():
            raise CalibrationError(f"No landmark file at {points_path}; run with --click first.")
        points = json.loads(points_path.read_text(encoding="utf-8"))
        frame = read_frame(points["source"], int(points["frame_index"]))
        if args.click:
            names = list(PitchModel(105, 68).landmarks())
            points["landmarks"] = click_landmarks(frame, names, points.get("landmarks", {}))
            points["picked_by"] = f"hand-picked with calibrate.py --click, {utc_now()}"
            points_path.write_text(json.dumps(points, indent=2), encoding="utf-8")
        if args.view != "top":
            from gaffer.perception.undistort import calibrate_side  # side-view models

            return calibrate_side(frame, points, cfg)
        calib, overlay, mask = calibrate_homography(frame, points, cfg, args.view)
    except CalibrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    out = calib.save(cdir / f"{args.view}.json")
    odir = repo_path(cfg["calibration"]["overlay_dir"])
    odir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(odir / f"{args.view}_overlay.jpg"), overlay, [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(odir / f"{args.view}_line_mask.png"), mask)
    e, m = calib.errors, calib.meta["pitch_size_fit"]
    print(f"cv2 {cv2.__version__} | view {args.view} | {e['landmarks_used']} landmarks "
          f"(not snapped: {e['landmarks_not_snapped'] or 'none'})")
    print(f"pitch size fit: {m['fitted_length_m']} x {m['fitted_width_m']} m (rms "
          f"{m['fit_rms_px']} px) -> using {calib.length_m:g} x {calib.width_m:g} m "
          f"({'agrees' if m['agrees_within_tolerance'] else 'differs'} within "
          f"{m['tolerance']:.0%} of {m['default_length_m']:g} x {m['default_width_m']:g})")
    print(f"fit rms {e['fit_rms_m']} m | held-out mean {e['held_out_mean_m']} m, median "
          f"{e['held_out_median_m']} m, max {e['held_out_max_m']} m ({e['held_out_worst']})")
    la = e["line_alignment"]
    print(f"line alignment: median {la['median_m']} m, p90 {la['p90_m']} m, "
          f"not found {la['not_found_fraction']:.1%} of {la['samples']} samples")
    print(f"-> {out}\n-> {odir / f'{args.view}_overlay.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
