"""Compare player detectors on a TeamTrack view against the ground-truth boxes.

Methods (all OpenCV 5): `classical` (grass-background blobs + homography, top view),
`background` (MOG2 background subtraction for a static camera, side view), `yolox` (YOLOX-S in
cv2.dnn on native-resolution tiles over the pitch, cross-tile NMS), `yolox_low` (same,
confidence 0.1), `yolox_x2` (tiles upscaled 2x, confidence 0.1). Each frame uses the per-frame
geometry exactly as the pipeline will (re-anchored for the drone, static for the side camera).

Sampling: `--seq-fps F` reads every clip sequentially at F fps (needed by the stateful
`background` method, which learns over consecutive frames; the first `detector.eval.warmup_s`
seconds of each clip are not scored, for every method, so all methods are scored on the same
frames). Without it, `--frames-per-clip` frames are spread over each clip (top-view default).

Scores: precision / recall / F1 at IoU >= 0.5 and at foot-point distance <= 1 m (and <= 2 m)
on the pitch (side view: also against the GT foot point moved up by the measured annotation
margin, `teamtrack.views.side.gt_foot_inset_px`, rows labelled `+inset`), overall and split
into the **near half** (y < W/2, close to the side camera) and the **far half**; recall on
isolated GT players; unmatched detections per frame (includes referees and staff, which GT
does not label; also: how many stand outside the pitch lines);
ms per frame. The dev clips (config `detector.eval.dev_clips`) are used only with `--dev`.

Usage:
    py scripts\\compare_detectors.py --view top
    py scripts\\compare_detectors.py --view side                       # seq 2 fps, all scored
    py scripts\\compare_detectors.py --view side --dev --methods background   # tuning only
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
    "background": {"method": "background"},
    "yolox": {"method": "tiled_yolox"},
    "yolox_low": {"method": "tiled_yolox", "conf_threshold": 0.1},
    "yolox_x2": {"method": "tiled_yolox", "conf_threshold": 0.1, "upscale": 2.0},
}
DEFAULT_METHODS = {"top": ["classical", "yolox", "yolox_low", "yolox_x2"],
                   "side": ["background", "yolox"]}
STATEFUL = {"background"}
COLOURS = {"gt": (0, 255, 0), "classical": (0, 0, 255), "background": (0, 0, 255),
           "yolox": (255, 0, 255), "yolox_low": (255, 128, 0), "yolox_x2": (0, 200, 255)}
HALVES = ("near", "far")


def det_points(boxes: np.ndarray, foot: str) -> np.ndarray:
    """Ground contact point of each xywh box (`centre` top view, `bottom` side view)."""
    if foot == "centre":
        return boxes[:, :2] + boxes[:, 2:] / 2
    return np.stack([boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3]], 1)


def draw(frame: np.ndarray, gt: np.ndarray, dets: dict[str, np.ndarray], scale: float = 0.5,
         rows: tuple[int, int] | None = None) -> np.ndarray:
    out = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    for x, y, w, h in gt * scale:
        cv2.rectangle(out, (int(x), int(y)), (int(x + w), int(y + h)), COLOURS["gt"], 2)
    for k, (name, boxes) in enumerate(dets.items()):
        for x, y, w, h in boxes * scale:
            if rows is None:
                cv2.circle(out, (int(x + w / 2), int(y + h / 2)), max(3, int(w / 3)),
                           COLOURS[name], 2)
            else:  # side view: offset boxes so both methods stay visible
                o = 2 * (k + 1)
                cv2.rectangle(out, (int(x) - o, int(y) - o), (int(x + w) + o, int(y + h) + o),
                              COLOURS[name], 1)
    if rows is not None:
        out = out[int(rows[0] * scale):int(rows[1] * scale)]
    y = 24
    for name, col in COLOURS.items():
        if name == "gt" or name in dets:
            cv2.putText(out, "GT box" if name == "gt" else name, (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2, cv2.LINE_AA)
            y += 26
    return out


def tally_frame(tl: dict[str, float], gt_box: np.ndarray, gt_xy: np.ndarray, d_box: np.ndarray,
                d_xy: np.ndarray, iso: np.ndarray, ecfg: dict[str, Any], length: float,
                width: float) -> int:
    """Add one frame's matching results to the tally `tl`; returns distance-matched count."""
    mi = match_iou(gt_box, d_box, float(ecfg["iou_threshold"]))
    md = match_distance(gt_xy, d_xy, float(ecfg["distance_threshold_m"]))
    ml = match_distance(gt_xy, d_xy, float(ecfg["distance_loose_m"]))
    tl["frames"] += 1
    tl["gt"] += len(gt_box)
    tl["det"] += len(d_box)
    tl["tp_iou"] += mi.tp
    tl["tp_dist"] += md.tp
    tl["tp_loose"] += ml.tp
    tl["iso_gt"] += int(iso.sum())
    tl["iso_hit_dist"] += sum(1 for i, _ in md.pairs if iso[i])
    tl["err_m"] += sum(float(np.linalg.norm(gt_xy[i] - d_xy[j])) for i, j in md.pairs)
    ex = d_xy[md.extra] if md.extra else np.zeros((0, 2))
    tl["extra_off_pitch"] += int(((ex[:, 0] < 0) | (ex[:, 0] > length) | (ex[:, 1] < 0)
                                  | (ex[:, 1] > width)).sum())
    g_far = gt_xy[:, 1] >= width / 2
    d_far = d_xy[:, 1] >= width / 2 if len(d_xy) else np.zeros(0, bool)
    for tag, m in (("dist", md), ("loose", ml)):
        for half, is_far in (("near", False), ("far", True)):
            tl[f"{half}_gt"] += int((g_far == is_far).sum()) if tag == "dist" else 0
            tl[f"{half}_tp_{tag}"] += sum(1 for i, _ in m.pairs if g_far[i] == is_far)
            tl[f"{half}_fp_{tag}"] += sum(1 for j in m.extra if d_far[j] == is_far)
            if tag == "dist":
                tl[f"{half}_err_m"] += sum(float(np.linalg.norm(gt_xy[i] - d_xy[j]))
                                           for i, j in m.pairs if g_far[i] == is_far)
    return md.tp


def summarise(tl: dict[str, float], ms: list[float]) -> dict[str, Any]:
    fp_d = tl["det"] - tl["tp_dist"]
    row: dict[str, Any] = {
        "frames": int(tl["frames"]),
        "iou": prf(int(tl["tp_iou"]), int(tl["det"] - tl["tp_iou"]), int(tl["gt"] - tl["tp_iou"])),
        "dist": prf(int(tl["tp_dist"]), int(fp_d), int(tl["gt"] - tl["tp_dist"])),
        "dist_loose": prf(int(tl["tp_loose"]), int(tl["det"] - tl["tp_loose"]),
                          int(tl["gt"] - tl["tp_loose"])),
        "isolated_recall_dist": round(tl["iso_hit_dist"] / max(tl["iso_gt"], 1), 4),
        "mean_position_error_m": round(tl["err_m"] / max(tl["tp_dist"], 1), 3),
        "unmatched_per_frame": round(fp_d / tl["frames"], 2),
        "unmatched_outside_lines_per_frame": round(tl["extra_off_pitch"] / tl["frames"], 2),
        "detections_per_frame": round(tl["det"] / tl["frames"], 1),
        "ms_per_frame": round(1000 * float(np.mean(ms)), 1),
    }
    for half in HALVES:
        g = int(tl[f"{half}_gt"])
        row[half] = {
            "gt_per_frame": round(g / tl["frames"], 2),
            "dist": prf(int(tl[f"{half}_tp_dist"]), int(tl[f"{half}_fp_dist"]),
                        g - int(tl[f"{half}_tp_dist"])),
            "dist_loose": prf(int(tl[f"{half}_tp_loose"]), int(tl[f"{half}_fp_loose"]),
                              g - int(tl[f"{half}_tp_loose"])),
            "mean_position_error_m": round(tl[f"{half}_err_m"] / max(tl[f"{half}_tp_dist"], 1),
                                           3),
        }
    return row


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Compare detectors against TeamTrack GT")
    ap.add_argument("--view", choices=["top", "side"], default="top")
    ap.add_argument("--methods", nargs="+", default=None, choices=list(METHODS))
    ap.add_argument("--frames-per-clip", type=int, default=6)
    ap.add_argument("--seq-fps", type=float, default=None,
                    help="read clips sequentially at this fps (default: 2 for side, off for top)")
    ap.add_argument("--score-every", type=int, default=1,
                    help="sequential mode: score every k-th sampled frame after warm-up")
    ap.add_argument("--yolox-max-frames", type=int, default=12,
                    help="spread mode: evaluate YOLOX variants on at most this many frames")
    ap.add_argument("--dev", action="store_true", help="evaluate on the dev clip(s) only")
    ap.add_argument("--tag", default="", help="suffix for output names (tuning runs)")
    args = ap.parse_args(argv)
    methods = args.methods or DEFAULT_METHODS[args.view]
    seq_fps = args.seq_fps if args.seq_fps is not None else (2.0 if args.view == "side" else None)

    ecfg = cfg["detector"]["eval"]
    vcfg = cfg["teamtrack"]["views"][args.view]
    try:
        calib = Calibration.for_view(cfg, args.view)
        clips = find_clips(args.view, cfg)
        model = PitchModel(calib.length_m, calib.width_m)
        dets_by = {m: make_detector(cfg, args.view, model, **METHODS[m]) for m in methods}
        geo = GeometryProvider(calib, cfg, args.view, model)
    except (CalibrationError, DatasetError, DetectorError, VideoError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    dev = set(ecfg["dev_clips"])
    clips = [c for c in clips if (c.stem in dev) == args.dev]
    if not clips:
        print("ERROR: no clips to evaluate", file=sys.stderr)
        return 2

    # per clip: list of (time, scored)
    plan: list[tuple[Any, list[tuple[float, bool]]]] = []
    n_scored = 0
    for c in clips:
        if seq_fps:
            ts = np.round(np.arange(c.start_s, c.end_s - 1e-9, 1.0 / seq_fps), 3)
            warm = float(ecfg["warmup_s"])
            items = [(float(t), bool(t - c.start_s >= warm - 1e-9
                                     and k % args.score_every == 0))
                     for k, t in enumerate(ts)]
        else:
            items = [(c.start_s + float(o), True)
                     for o in np.linspace(0.5, 29.0, args.frames_per_clip)]
        n_scored += sum(s for _, s in items)
        plan.append((c, items))
    yolox_every = 1 if seq_fps else max(1, int(np.ceil(n_scored / max(1, args.yolox_max_frames))))

    tally: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    timing: dict[str, list[float]] = defaultdict(list)
    suffix = f"{'_dev' if args.dev else ''}{args.tag}"
    img_dir = repo_path(f"outputs/detector_compare/{args.view}{suffix}")
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = k_scored = 0
    inset = float(vcfg.get("gt_foot_inset_px", 0.0))
    rows_band = (380, 1000) if args.view == "side" else None
    for clip, items in plan:
        src = VideoSource(clip.video, start_s=clip.start_s)
        gt_all = load_gt(clip.csv).boxes
        for m, det in dets_by.items():
            if m in STATEFUL:
                det.reset(seq_fps or 2.0)  # type: ignore[union-attr]
        scored = {t for t, s in items if s}
        for t, _, fi, frame in src.frames([t for t, _ in items]):
            t0 = time.perf_counter()
            g = geo.for_frame(frame)
            timing["geometry"].append(time.perf_counter() - t0)
            is_scored = t in scored
            if not is_scored:  # warm-up: only stateful detectors see the frame
                for m, det in dets_by.items():
                    if m in STATEFUL:
                        det.detect(frame, g.mapper)
                continue
            gt_df = gt_all[(gt_all["frame"] == fi) & gt_all["team"].isin(["0", "1"])]
            gt_box = gt_df[["bb_left", "bb_top", "bb_width", "bb_height"]].to_numpy(float)
            gt_xy = g.mapper.to_pitch(foot_points(gt_df, vcfg["foot_point"]))
            gt_xy_in = (g.mapper.to_pitch(foot_points(gt_df, vcfg["foot_point"], inset))
                        if inset else None)
            iso = isolated(gt_box)
            drawn: dict[str, np.ndarray] = {}
            for m, det in dets_by.items():
                if m not in STATEFUL and m != "classical" and k_scored % yolox_every:
                    continue
                t0 = time.perf_counter()
                d = det.detect(frame, g.mapper).persons()
                timing[m].append(time.perf_counter() - t0)
                d_xy = g.mapper.to_pitch(det_points(d.boxes, vcfg["foot_point"])) if len(d) \
                    else np.zeros((0, 2))
                tally_frame(tally[m], gt_box, gt_xy, d.boxes, d_xy, iso, ecfg, model.length,
                            model.width)
                if gt_xy_in is not None:  # same detections, GT foot moved up by the box margin
                    tally_frame(tally[f"{m}+inset"], gt_box, gt_xy_in, d.boxes, d_xy, iso, ecfg,
                                model.length, model.width)
                drawn[m] = d.boxes
            k_scored += 1
            if saved < 3 and len(drawn) == len(dets_by) and k_scored % 7 == 1:
                cv2.imwrite(str(img_dir / f"{clip.stem}_t{t - clip.start_s:04.1f}.jpg"),
                            draw(frame, gt_box, drawn, rows=rows_band),
                            [cv2.IMWRITE_JPEG_QUALITY, 85])
                saved += 1
            print(f"[{k_scored}/{n_scored}] {clip.stem} t={t:.1f}: " + ", ".join(
                f"{m} {int(tally[m]['tp_dist'])}/{int(tally[m]['gt'])}" for m in drawn),
                flush=True)

    rows = {m: summarise(tl, timing[m.split("+")[0]]) for m, tl in tally.items()}
    geo_ms = round(1000 * float(np.mean(timing["geometry"])), 1)
    first = tally[methods[0]]
    print(f"\nview {args.view} ({'DEV clip' if args.dev else 'eval clips'}: {len(clips)} clips, "
          f"{int(first['frames'])} scored frames"
          f"{f' (sequential {seq_fps:g} fps)' if seq_fps else ''}; GT players/frame "
          f"{first['gt'] / max(first['frames'], 1):.1f}; geometry {geo_ms} ms/frame)")
    if inset:
        print(f"'+inset' rows: GT foot point moved up {inset:g} px (annotation margin below the "
              "feet); other rows: raw GT box bottom")
    print(f"{'method':16s} {'frames':>6s} | {'P@IoU.5':>7s} {'R@IoU.5':>7s} | {'P@1m':>6s} "
          f"{'R@1m':>6s} {'F1@1m':>6s} {'R iso':>6s} {'err m':>6s} | {'P@2m':>6s} {'R@2m':>6s} "
          f"| {'extra/fr':>8s} {'outside':>7s} {'ms/frame':>9s}")
    for m, r in rows.items():
        print(f"{m:16s} {r['frames']:>6d} | {r['iou']['precision']:>7.3f} "
              f"{r['iou']['recall']:>7.3f} | {r['dist']['precision']:>6.3f} "
              f"{r['dist']['recall']:>6.3f} {r['dist']['f1']:>6.3f} "
              f"{r['isolated_recall_dist']:>6.3f} {r['mean_position_error_m']:>6.2f} | "
              f"{r['dist_loose']['precision']:>6.3f} {r['dist_loose']['recall']:>6.3f} | "
              f"{r['unmatched_per_frame']:>8.2f} {r['unmatched_outside_lines_per_frame']:>7.2f} "
              f"{r['ms_per_frame']:>9.1f}")
    print(f"\n{'method':10s} {'half':5s} {'GT/fr':>6s} | {'P@1m':>6s} {'R@1m':>6s} {'F1@1m':>6s} "
          f"{'err m':>6s} | {'P@2m':>6s} {'R@2m':>6s} {'F1@2m':>6s}")
    for m, r in rows.items():
        for half in HALVES:
            h = r[half]
            print(f"{m:16s} {half:5s} {h['gt_per_frame']:>6.2f} | {h['dist']['precision']:>6.3f} "
                  f"{h['dist']['recall']:>6.3f} {h['dist']['f1']:>6.3f} "
                  f"{h['mean_position_error_m']:>6.2f} | {h['dist_loose']['precision']:>6.3f} "
                  f"{h['dist_loose']['recall']:>6.3f} {h['dist_loose']['f1']:>6.3f}")
    out = repo_path(f"outputs/compare_detectors_{args.view}{suffix}.json")
    if out.exists():  # keep earlier results of methods not re-run (YOLOX takes minutes)
        old = json.loads(out.read_text(encoding="utf-8")).get("results", {})
        rows = {**{m: r for m, r in old.items() if m not in rows}, **rows}
    out.write_text(json.dumps({"view": args.view, "dev": args.dev,
                               "clips": [c.stem for c in clips], "geometry_ms": geo_ms,
                               "sequential_fps": seq_fps, "results": rows}, indent=2),
                   encoding="utf-8")
    print(f"-> {out}\n-> {img_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
