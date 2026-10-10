"""Compare player detectors on a TeamTrack view against the ground-truth boxes.

Methods (all OpenCV 5): `classical` (grass-background blobs + homography, top view),
`yolox` (YOLOX-S in cv2.dnn on native-resolution tiles), `yolox_low` (same, confidence 0.1),
`yolox_x2` (tiles upscaled 2x, confidence 0.1). Each frame uses the per-frame re-anchored
geometry, exactly as the pipeline will.

Scores: precision / recall / F1 at IoU >= 0.5 and at centre distance <= 1 m on the pitch,
recall on isolated GT players (GT keeps boxes for players hidden behind others), unmatched
detections per frame (includes referees and staff, which GT does not label; also split out:
how many of them stand outside the pitch lines), and ms per frame.
The dev clip (config `detector.eval.dev_clips`) is used only with `--dev` for tuning; results
are reported on the other clips.

Usage:
    py scripts\\compare_detectors.py --view top
    py scripts\\compare_detectors.py --view top --dev --methods classical   # tuning only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from typing import Any

import cv2
import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.evaluation import isolated, match_distance, match_iou, prf
from gaffer.perception.detector import DetectorError, make_detector
from gaffer.perception.drift import GeometryProvider
from gaffer.perception.pitch import Calibration, CalibrationError, PitchModel
from gaffer.perception.video import VideoError, VideoSource
from gaffer.teamtrack import DatasetError, find_clips, foot_points, load_gt

METHODS: dict[str, dict[str, Any]] = {
    "classical": {"method": "classical"},
    "yolox": {"method": "tiled_yolox"},
    "yolox_low": {"method": "tiled_yolox", "conf_threshold": 0.1},
    "yolox_x2": {"method": "tiled_yolox", "conf_threshold": 0.1, "upscale": 2.0},
}
COLOURS = {"gt": (0, 255, 0), "classical": (0, 0, 255), "yolox": (255, 0, 255),
           "yolox_low": (255, 128, 0), "yolox_x2": (0, 200, 255)}


def draw(frame: np.ndarray, gt: np.ndarray, dets: dict[str, np.ndarray], scale: float = 0.5
         ) -> np.ndarray:
    out = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    for x, y, w, h in gt * scale:
        cv2.rectangle(out, (int(x), int(y)), (int(x + w), int(y + h)), COLOURS["gt"], 2)
    for name, boxes in dets.items():
        for x, y, w, h in boxes * scale:
            cv2.circle(out, (int(x + w / 2), int(y + h / 2)), max(3, int(w / 3)),
                       COLOURS[name], 2)
    y = 24
    for name, col in COLOURS.items():
        if name == "gt" or name in dets:
            cv2.putText(out, "GT box" if name == "gt" else name, (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2, cv2.LINE_AA)
            y += 26
    return out


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Compare detectors against TeamTrack GT")
    ap.add_argument("--view", choices=["top", "side"], default="top")
    ap.add_argument("--methods", nargs="+", default=list(METHODS), choices=list(METHODS))
    ap.add_argument("--frames-per-clip", type=int, default=6)
    ap.add_argument("--yolox-max-frames", type=int, default=12,
                    help="YOLOX variants are slow on 4K: evaluate them on at most this many of "
                         "the sampled frames (spread over all clips)")
    ap.add_argument("--dev", action="store_true", help="evaluate on the dev clip(s) only")
    args = ap.parse_args(argv)

    ecfg = cfg["detector"]["eval"]
    vcfg = cfg["teamtrack"]["views"][args.view]
    try:
        calib = Calibration.for_view(cfg, args.view)
        clips = find_clips(args.view, cfg)
        model = PitchModel(calib.length_m, calib.width_m)
        dets_by = {m: make_detector(cfg, args.view, model, **METHODS[m]) for m in args.methods}
        geo = GeometryProvider(calib, cfg, args.view, model)
    except (CalibrationError, DatasetError, DetectorError, VideoError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    dev = set(ecfg["dev_clips"])
    clips = [c for c in clips if (c.stem in dev) == args.dev]
    if not clips:
        print("ERROR: no clips to evaluate", file=sys.stderr)
        return 2

    samples = []  # (clip, time)
    for c in clips:
        offs = np.linspace(0.5, 29.0, args.frames_per_clip)
        samples += [(c, c.start_s + float(o)) for o in offs]
    yolox_every = max(1, int(np.ceil(len(samples) / max(1, args.yolox_max_frames))))

    tally: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    timing: dict[str, list[float]] = defaultdict(list)
    img_dir = repo_path(f"outputs/detector_compare/{args.view}{'_dev' if args.dev else ''}")
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for k, (clip, t) in enumerate(samples):
        src = VideoSource(clip.video, start_s=clip.start_s)
        frame = src.read(t)
        t0 = time.perf_counter()
        g = geo.for_frame(frame)
        timing["geometry"].append(time.perf_counter() - t0)
        fi = src.locate(t)[1]  # type: ignore[index]
        gt_df = load_gt(clip.csv).boxes
        gt_df = gt_df[(gt_df["frame"] == fi) & gt_df["team"].isin(["0", "1"])]
        gt_box = gt_df[["bb_left", "bb_top", "bb_width", "bb_height"]].to_numpy(float)
        gt_xy = g.mapper.to_pitch(foot_points(gt_df, vcfg["foot_point"]))
        iso = isolated(gt_box)
        drawn: dict[str, np.ndarray] = {}
        for m, det in dets_by.items():
            if m != "classical" and k % yolox_every:
                continue
            t0 = time.perf_counter()
            d = det.detect(frame, g.mapper).persons()
            timing[m].append(time.perf_counter() - t0)
            if vcfg["foot_point"] == "centre":
                d_pts = d.boxes[:, :2] + d.boxes[:, 2:] / 2
            else:
                d_pts = np.stack([d.boxes[:, 0] + d.boxes[:, 2] / 2,
                                  d.boxes[:, 1] + d.boxes[:, 3]], 1)
            d_xy = g.mapper.to_pitch(d_pts) if len(d) else np.zeros((0, 2))
            mi = match_iou(gt_box, d.boxes, float(ecfg["iou_threshold"]))
            md = match_distance(gt_xy, d_xy, float(ecfg["distance_threshold_m"]))
            tl = tally[m]
            tl["frames"] += 1
            tl["gt"] += len(gt_box)
            tl["det"] += len(d)
            tl["tp_iou"] += mi.tp
            tl["tp_dist"] += md.tp
            tl["iso_gt"] += int(iso.sum())
            tl["iso_hit_dist"] += sum(1 for i, _ in md.pairs if iso[i])
            tl["err_m"] += sum(float(np.linalg.norm(gt_xy[i] - d_xy[j])) for i, j in md.pairs)
            ex = d_xy[md.extra] if md.extra else np.zeros((0, 2))
            tl["extra_off_pitch"] += int(((ex[:, 0] < 0) | (ex[:, 0] > model.length)
                                          | (ex[:, 1] < 0) | (ex[:, 1] > model.width)).sum())
            drawn[m] = d.boxes
        if saved < 3 and len(drawn) == len(dets_by):
            cv2.imwrite(str(img_dir / f"{clip.stem}_t{t - clip.start_s:04.1f}.jpg"),
                        draw(frame, gt_box, drawn), [cv2.IMWRITE_JPEG_QUALITY, 85])
            saved += 1
        print(f"[{k + 1}/{len(samples)}] {clip.stem} t={t:.1f}: " + ", ".join(
            f"{m} {int(tally[m]['tp_dist'])}/{int(tally[m]['gt'])}" for m in drawn))

    rows = {}
    for m, tl in tally.items():
        fp_d = tl["det"] - tl["tp_dist"]
        rows[m] = {
            "frames": int(tl["frames"]),
            "iou": prf(int(tl["tp_iou"]), int(tl["det"] - tl["tp_iou"]),
                       int(tl["gt"] - tl["tp_iou"])),
            "dist": prf(int(tl["tp_dist"]), int(fp_d), int(tl["gt"] - tl["tp_dist"])),
            "isolated_recall_dist": round(tl["iso_hit_dist"] / max(tl["iso_gt"], 1), 4),
            "mean_position_error_m": round(tl["err_m"] / max(tl["tp_dist"], 1), 3),
            "unmatched_per_frame": round(fp_d / tl["frames"], 2),
            "unmatched_outside_lines_per_frame": round(tl["extra_off_pitch"] / tl["frames"], 2),
            "detections_per_frame": round(tl["det"] / tl["frames"], 1),
            "ms_per_frame": round(1000 * float(np.mean(timing[m])), 1),
        }
    geo_ms = round(1000 * float(np.mean(timing["geometry"])), 1)
    print(f"\nview {args.view} ({'DEV clip' if args.dev else 'eval clips'}: "
          f"{len(clips)} clips, {len(samples)} frames; GT players/frame "
          f"{tally[args.methods[0]]['gt'] / tally[args.methods[0]]['frames']:.1f}; "
          f"geometry {geo_ms} ms/frame)")
    print(f"{'method':10s} {'frames':>6s} | {'P@IoU.5':>7s} {'R@IoU.5':>7s} | {'P@1m':>6s} "
          f"{'R@1m':>6s} {'F1@1m':>6s} {'R iso':>6s} {'err m':>6s} | {'extra/fr':>8s} "
          f"{'outside':>7s} {'ms/frame':>9s}")
    for m, r in rows.items():
        print(f"{m:10s} {r['frames']:>6d} | {r['iou']['precision']:>7.3f} "
              f"{r['iou']['recall']:>7.3f} | {r['dist']['precision']:>6.3f} "
              f"{r['dist']['recall']:>6.3f} {r['dist']['f1']:>6.3f} "
              f"{r['isolated_recall_dist']:>6.3f} {r['mean_position_error_m']:>6.2f} | "
              f"{r['unmatched_per_frame']:>8.2f} {r['unmatched_outside_lines_per_frame']:>7.2f} "
              f"{r['ms_per_frame']:>9.1f}")
    out = repo_path(f"outputs/compare_detectors_{args.view}{'_dev' if args.dev else ''}.json")
    if out.exists():  # keep earlier results of methods not re-run (YOLOX takes minutes)
        old = json.loads(out.read_text(encoding="utf-8")).get("results", {})
        rows = {**{m: r for m, r in old.items() if m not in rows}, **rows}
    out.write_text(json.dumps({"view": args.view, "dev": args.dev,
                               "clips": [c.stem for c in clips], "geometry_ms": geo_ms,
                               "results": rows}, indent=2), encoding="utf-8")
    print(f"-> {out}\n-> {img_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
