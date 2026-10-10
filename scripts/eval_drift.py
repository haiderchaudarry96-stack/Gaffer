"""Measure how much per-clip / per-keyframe re-anchoring improves the top-view homography.

For frames sampled inside every top-view clip, the pitch-line alignment error (metres, see
`pitch.line_alignment_error`) is measured three ways:

- `none`: the reference calibration homography as-is;
- `per_clip`: one alignment (`perception/drift.py`) at the clip's first frame, reused for the
  whole clip;
- `per_frame`: an alignment at that very frame (what keyframing converges to).

Usage:
    py scripts\\eval_drift.py [--view top] [--offsets 0 10 20 29.5]
Writes outputs/eval_drift_<view>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import cv2
import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.perception.drift import DriftSettings, alignment_image, estimate_alignment
from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    PitchModel,
    line_alignment_error,
    line_mask,
)
from gaffer.perception.video import VideoError, VideoSource
from gaffer.teamtrack import DatasetError, find_clips


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Evaluate drift re-anchoring")
    ap.add_argument("--view", default="top", choices=["top", "side"])
    ap.add_argument("--offsets", type=float, nargs="+", default=[0.0, 10.0, 20.0, 29.5])
    args = ap.parse_args(argv)
    try:
        calib = Calibration.load(repo_path(cfg["calibration"]["dir"]) / f"{args.view}.json")
        clips = find_clips(args.view, cfg)
    except (CalibrationError, DatasetError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    s = DriftSettings.from_config(cfg, args.view)
    lm_cfg = cfg["calibration"]["views"][args.view]["line_mask"]
    le = cfg["calibration"]["line_error"]
    model = PitchModel(calib.length_m, calib.width_m)
    ref_mapper = calib.mapper()
    ref_frame = VideoSource(calib.source).read(calib.frame_index / VideoSource(calib.source)
                                               .native_fps)
    ref_img = alignment_image(ref_frame, s)
    ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
    size = (ref_frame.shape[1], ref_frame.shape[0])

    def err(mapper, mask) -> float:
        return line_alignment_error(mapper, mask, model, float(le["sample_step_m"]),
                                    float(le["max_search_m"]))["median_m"]

    rows, t_align = [], []
    for clip in clips:
        try:
            src = VideoSource(clip.video, start_s=clip.start_s)
        except VideoError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        times = [clip.start_s + o for o in args.offsets]
        clip_A = None
        for t, _, fi, frame in src.frames(times):
            mask = line_mask(frame, **lm_cfg)
            t0 = time.perf_counter()
            al = estimate_alignment(ref_img, alignment_image(frame, s), s, size, ref_gray,
                                    cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            t_align.append(time.perf_counter() - t0)
            if clip_A is None:
                clip_A = al
            rows.append({"clip": clip.stem, "t": t, "frame": fi,
                         "shift_px": round(al.shift_px, 1), "method": al.method,
                         "correlation": round(al.correlation, 3),
                         "err_none_m": err(ref_mapper, mask),
                         "err_per_clip_m": err(ref_mapper.warped(clip_A.A), mask),
                         "err_per_frame_m": err(ref_mapper.warped(al.A), mask)})
            r = rows[-1]
            print(f"{clip.stem} t={t:7.1f} shift {r['shift_px']:6.1f}px ({r['method']}, "
                  f"cc {r['correlation']:.2f}) | line error none {r['err_none_m']:.3f} m, "
                  f"per clip {r['err_per_clip_m']:.3f} m, per frame {r['err_per_frame_m']:.3f} m")

    summary = {k: round(float(np.median([r[k] for r in rows])), 3)
               for k in ("err_none_m", "err_per_clip_m", "err_per_frame_m")}
    summary.update({f"p90_{k}": round(float(np.percentile([r[k] for r in rows], 90)), 3)
                    for k in ("err_none_m", "err_per_clip_m", "err_per_frame_m")})
    summary["max_shift_px"] = max(r["shift_px"] for r in rows)
    summary["align_ms_mean"] = round(1000 * float(np.mean(t_align)), 1)
    print(f"\nmedian line error: none {summary['err_none_m']} m | per clip "
          f"{summary['err_per_clip_m']} m | per frame {summary['err_per_frame_m']} m "
          f"(p90 {summary['p90_err_none_m']} / {summary['p90_err_per_clip_m']} / "
          f"{summary['p90_err_per_frame_m']}); max shift {summary['max_shift_px']} px; "
          f"alignment {summary['align_ms_mean']} ms/frame")
    out = repo_path(f"outputs/eval_drift_{args.view}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
