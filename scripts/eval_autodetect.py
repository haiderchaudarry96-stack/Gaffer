"""Measure the pitch auto-detect and the 4-corner fallback on the TeamTrack drone clips.

Runs on the laptop (needs `data/teamtrack/soccer_top`: the 60 drone clips 0-1800 s and the
31-point calibration's reference clip). No pipeline, no LLM: a few frames per clip.

For every sampled frame:
- **ground truth**: the 31-point calibration (`data/calibration/top.json`) re-anchored to that
  frame (`drift.GeometryProvider`, as the pipeline does: the drone drifts), which gives the true
  image position of the 4 pitch corners;
- **auto-detect** (`perception.pitch.detect_pitch_corners`): corner error in metres (each
  detected corner mapped to the pitch with the ground truth, distance to the true corner) and
  homography agreement on player positions (TeamTrack annotation boxes, else a 5 m grid):
  position from the detected 4-corner homography vs from the 31-point calibration;
- **confidence flag**: success = accepted and max corner error <= `--max-corner-m`; false
  accept = accepted but wrong; false reject = refused but right;
- **4-corner fallback cost**: a homography from the 4 true corners (perfect clicks) and with
  click noise (`--click-noise-px`, seed 42) vs the 31-point calibration, on player positions and
  on the painted lines (line-alignment error, metres).

Once per run, a frame is deliberately **tilted** (perspective warp: far side shortened) and
**cropped** (corners out of view): auto-detect must refuse both.

    py scripts\\eval_autodetect.py                       # all 60 clips, 3 frames each
    py scripts\\eval_autodetect.py --limit 5 --frames 2  # quick check
    py scripts\\eval_autodetect.py --synthetic 12        # generated frames (no data needed)

Writes `outputs/eval_autodetect.json`, `outputs/eval_autodetect.txt` and failure images
`outputs/failures/autodetect_<clip>_<t>.jpg` (green = detected, magenta = ground truth).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.perception.pitch import (
    CalibrationError,
    HomographyMapper,
    PitchMapper,
    PitchModel,
    detect_pitch_corners,
    four_corner_homography,
    image_corners,
    line_alignment_error,
    line_mask,
    render_pitch_view,
)


@dataclass
class Item:
    """One frame with its ground truth."""

    clip: str
    t: float
    frame: np.ndarray
    gt: PitchMapper  # image -> pitch, true for this frame
    players_px: np.ndarray | None  # (N, 2) image points of players (None: use a grid)


# --------------------------------------------------------------------------- metrics


def aligned_mapper(corners_px: np.ndarray, gt: PitchMapper, L: float, W: float
                   ) -> HomographyMapper:
    """4-corner homography whose pitch labels follow the ground truth (the 4-corner function
    labels TL as (0, W); TeamTrack's drone image is rotated: the true pitch corner of each
    image corner is used instead, so positions are comparable)."""
    true_xy = gt.to_pitch(corners_px)
    rect = np.array([[0, 0], [L, 0], [L, W], [0, W]], float)
    labels = np.array([rect[np.argmin(np.linalg.norm(rect - p, axis=1))] for p in true_xy])
    if len({tuple(x) for x in labels}) < 4:  # far off: fall back to the 4-corner convention
        return four_corner_homography(corners_px, (1e9, 1e9), L, W,
                                      {"min_area_frac": 0, "min_opposite_edge_ratio": 0,
                                       "max_outside_frac": 1e9}).mapper()
    H = cv2.getPerspectiveTransform(corners_px.astype(np.float32), labels.astype(np.float32))
    return HomographyMapper(H)


def corner_errors_m(det_px: np.ndarray, gt: PitchMapper, L: float, W: float) -> list[float]:
    """Distance (m) from each detected corner (mapped with the truth) to the nearest true
    pitch corner."""
    rect = np.array([[0, 0], [L, 0], [L, W], [0, W]], float)
    xy = gt.to_pitch(det_px)
    return [float(np.min(np.linalg.norm(rect - p, axis=1))) for p in xy]


def player_points(item: Item, L: float, W: float) -> np.ndarray:
    if item.players_px is not None and len(item.players_px):
        return item.players_px
    gx, gy = np.meshgrid(np.arange(5, L, 5.0), np.arange(4, W, 5.0))
    return item.gt.to_image(np.stack([gx.ravel(), gy.ravel()], axis=1))


def position_errors(mapper: PitchMapper, item: Item, L: float, W: float) -> dict[str, float]:
    uv = player_points(item, L, W)
    true = item.gt.to_pitch(uv)
    inside = (true[:, 0] >= -2) & (true[:, 0] <= L + 2) & (true[:, 1] >= -2) & (true[:, 1] <= W + 2)
    if not inside.any():
        return {"median_m": float("nan"), "p90_m": float("nan"), "max_m": float("nan"), "n": 0}
    e = np.linalg.norm(mapper.to_pitch(uv[inside]) - true[inside], axis=1)
    return {"median_m": round(float(np.median(e)), 3),
            "p90_m": round(float(np.percentile(e, 90)), 3),
            "max_m": round(float(e.max()), 3), "n": int(inside.sum())}


def lines_error(mapper: PitchMapper, frame: np.ndarray, cfg: dict[str, Any], L: float,
                W: float) -> float | None:
    """Median line-alignment error (m) at quarter resolution (as the drift re-anchoring)."""
    k = 0.25
    small = cv2.resize(frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    lmc = cfg["calibration"]["views"]["top"]["line_mask"]
    mask = line_mask(small, max(3, int(lmc["kernel_px"] * k) | 1), int(lmc["threshold"]),
                     int(lmc["max_saturation"]), int(lmc["min_component_px"] * k * k))

    class Scaled:
        def to_image(self, xy: np.ndarray) -> np.ndarray:
            return mapper.to_image(xy) * k

        def to_pitch(self, uv: np.ndarray) -> np.ndarray:
            return mapper.to_pitch(uv / k)

    r = line_alignment_error(Scaled(), mask, PitchModel(L, W), 1.0, 2.0)
    v = r["median_m"]
    return None if not np.isfinite(v) else round(float(v), 3)


def evaluate_item(item: Item, cfg: dict[str, Any], max_corner_m: float,
                  noise_px: list[float], rng: np.random.Generator, fail_dir: Path | None
                  ) -> dict[str, Any]:
    L, W = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])
    true_px = image_corners(item.gt, L, W)
    t0 = time.perf_counter()
    d = detect_pitch_corners(item.frame, cfg)
    row: dict[str, Any] = {"clip": item.clip, "t": item.t, "detect_ms": round(d.timing_ms, 1),
                           "accepted": d.accepted, "found": d.found,
                           "confidence": round(d.confidence, 3),
                           "parts": {k: round(v, 3) for k, v in d.parts.items()},
                           "problems": d.problems, "snapped_edges": d.snapped_edges}
    correct = False
    if d.corners is not None:
        ce = corner_errors_m(d.corners, item.gt, L, W)
        row["corner_error_m"] = [round(x, 3) for x in ce]
        row["corner_error_max_m"] = round(max(ce), 3)
        row["corner_px_error_max"] = round(float(np.abs(d.corners - true_px).max()), 1)
        row["positions"] = position_errors(aligned_mapper(d.corners, item.gt, L, W), item, L, W)
        correct = max(ce) <= max_corner_m
    row["correct"] = correct
    row["outcome"] = ("success" if d.accepted and correct else "false_accept" if d.accepted
                      else "false_reject" if correct else "correct_reject")
    # 4-corner fallback (perfect and noisy clicks) vs the 31-point calibration
    cost = {}
    for s in [0.0, *noise_px]:
        clicked = true_px + (rng.normal(0, s, true_px.shape) if s > 0 else 0.0)
        try:
            m = aligned_mapper(clicked, item.gt, L, W)
        except (CalibrationError, cv2.error):
            continue
        cost[f"noise_{s:g}px"] = {"positions": position_errors(m, item, L, W),
                                  "lines_median_m": lines_error(m, item.frame, cfg, L, W)}
    row["fallback_cost"] = cost
    row["gt_lines_median_m"] = lines_error(item.gt, item.frame, cfg, L, W)
    row["eval_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if fail_dir is not None and row["outcome"] in ("false_accept", "false_reject") or (
            fail_dir is not None and not d.found):
        save_failure(item, d.corners, true_px, row, fail_dir)
    return row


def save_failure(item: Item, det: np.ndarray | None, true_px: np.ndarray, row: dict[str, Any],
                 fail_dir: Path) -> None:
    k = min(1.0, 1600 / item.frame.shape[1])
    img = cv2.resize(item.frame, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    cv2.polylines(img, [np.round(true_px * k).astype(np.int32).reshape(-1, 1, 2)], True,
                  (255, 0, 255), 2, cv2.LINE_AA)
    if det is not None:
        cv2.polylines(img, [np.round(det * k).astype(np.int32).reshape(-1, 1, 2)], True,
                      (80, 255, 120), 2, cv2.LINE_AA)
    txt = (f"{item.clip} t={item.t:.0f}s {row['outcome']} conf {row['confidence']:.2f} "
           f"max corner err {row.get('corner_error_max_m', 'n/a')} m")
    cv2.rectangle(img, (0, 0), (img.shape[1], 30), (20, 20, 20), -1)
    cv2.putText(img, txt, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                cv2.LINE_AA)
    fail_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(fail_dir / f"autodetect_{item.clip}_{item.t:.0f}.jpg"), img,
                [cv2.IMWRITE_JPEG_QUALITY, 85])


def refusal_checks(item: Item, cfg: dict[str, Any]) -> dict[str, Any]:
    """A tilted and a cropped version of one frame: auto-detect must refuse both."""
    h, w = item.frame.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[0.3 * w, 0.25 * h], [0.7 * w, 0.25 * h], [w, h], [0, h]])
    tilted = cv2.warpPerspective(item.frame, cv2.getPerspectiveTransform(src, dst), (w, h))
    y0, x0 = int(0.2 * h), int(0.2 * w)
    cropped = cv2.resize(item.frame[y0:h - y0, x0:w - x0], (w, h), interpolation=cv2.INTER_LINEAR)
    out = {}
    for name, img in (("tilted", tilted), ("cropped", cropped)):
        d = detect_pitch_corners(img, cfg)
        out[name] = {"refused": not d.accepted, "confidence": round(d.confidence, 3),
                     "problems": d.problems, "source_frame": f"{item.clip} t={item.t:.0f}s"}
    return out


# --------------------------------------------------------------------------- sources


def teamtrack_items(cfg: dict[str, Any], frames_per_clip: int, limit: int | None
                    ) -> Iterator[Item]:
    from gaffer.perception.drift import GeometryProvider
    from gaffer.perception.pitch import Calibration
    from gaffer.perception.video import VideoSource
    from gaffer.teamtrack import find_clips, foot_points, load_gt

    clips = find_clips("top", cfg, sets=["train", "dev", "eval", "eval2"])
    if limit:
        clips = clips[:limit]
    calib = Calibration.for_view(cfg, "top")
    geo = GeometryProvider(calib, cfg, "top", PitchModel(calib.length_m, calib.width_m))
    for c in clips:
        src = VideoSource(c.video, start_s=c.start_s)
        span = src.end_s - src.start_s
        ts = [src.start_s + span * (i + 0.5) / frames_per_clip for i in range(frames_per_clip)]
        gt_df = load_gt(c.csv).boxes if c.csv.exists() else None
        for t in ts:
            try:
                frame = src.read(t)
            except Exception as exc:  # unreadable clip: reported, not fatal
                print(f"  {c.name} t={t:.1f}: cannot read ({exc})", file=sys.stderr)
                continue
            players = None
            if gt_df is not None:
                fi = int(round((t - src.start_s) * src.native_fps))
                rows = gt_df[(gt_df["frame"] == fi) & (gt_df["team"] != "BALL")]
                if len(rows):
                    players = foot_points(rows, "centre")
            yield Item(c.name, round(t, 2), frame, geo.for_frame(frame).mapper, players)


def synthetic_items(n: int, seed: int = 42, size: tuple[int, int] = (1920, 1080)
                    ) -> Iterator[Item]:
    """Generated top-down frames with small random perspective and placement (known truth)."""
    rng = np.random.default_rng(seed)
    w, h = size
    L, W = 105.0, 68.0
    for i in range(n):
        mx, my = rng.uniform(0.06, 0.14) * w, rng.uniform(0.08, 0.16) * h
        base = np.array([[mx, my], [w - mx, my], [w - mx, h - my], [mx, h - my]])
        corners = base + rng.normal(0, 0.01 * w, base.shape)
        players = [(rng.uniform(3, L - 3), rng.uniform(3, W - 3),
                    (235, 235, 235) if k % 2 else (170, 70, 25)) for k in range(22)]
        frame = render_pitch_view(size, corners, players=players, seed=seed + i,
                                  runoff_m=float(rng.uniform(2, 6)))
        targets = np.float32([[0, W], [L, W], [L, 0], [0, 0]])
        H = cv2.getPerspectiveTransform(corners.astype(np.float32), targets)
        gt = HomographyMapper(H)
        ppx = gt.to_image(np.array([[x, y] for x, y, _ in players]))
        yield Item(f"synthetic_{i:02d}", 0.0, frame, gt, ppx)


# --------------------------------------------------------------------------- report


def _q(vals: list[float]) -> dict[str, float | None]:
    v = [x for x in vals if x is not None and np.isfinite(x)]
    if not v:
        return {"median": None, "p90": None, "max": None, "n": 0}
    return {"median": round(float(np.median(v)), 3), "p90": round(float(np.percentile(v, 90)), 3),
            "max": round(float(np.max(v)), 3), "n": len(v)}


def summarise(rows: list[dict[str, Any]], refusals: dict[str, Any], args: argparse.Namespace,
              wall_s: float) -> dict[str, Any]:
    n = len(rows)
    outcomes = {k: sum(r["outcome"] == k for r in rows)
                for k in ("success", "false_accept", "false_reject", "correct_reject")}
    acc = [r for r in rows if r["accepted"]]
    cost: dict[str, Any] = {}
    for key in sorted({k for r in rows for k in r["fallback_cost"]},
                      key=lambda s: float(s.split("_")[1].rstrip("px"))):
        cost[key] = {"positions_median_m": _q([r["fallback_cost"][key]["positions"]["median_m"]
                                               for r in rows if key in r["fallback_cost"]]),
                     "positions_max_m": _q([r["fallback_cost"][key]["positions"]["max_m"]
                                            for r in rows if key in r["fallback_cost"]]),
                     "lines_median_m": _q([r["fallback_cost"][key]["lines_median_m"]
                                           for r in rows if key in r["fallback_cost"]])}
    return {
        "source": "synthetic" if args.synthetic else "teamtrack_top",
        "frames": n, "clips": len({r["clip"] for r in rows}),
        "max_corner_m": args.max_corner_m,
        "outcomes": outcomes,
        "success_rate": round(outcomes["success"] / n, 3) if n else None,
        "accepted_rate": round(len(acc) / n, 3) if n else None,
        "corner_error_max_m_all": _q([r.get("corner_error_max_m") for r in rows]),
        "corner_error_max_m_accepted": _q([r.get("corner_error_max_m") for r in acc]),
        "positions_vs_31_point_accepted": {
            "median_m": _q([r["positions"]["median_m"] for r in acc if "positions" in r]),
            "max_m": _q([r["positions"]["max_m"] for r in acc if "positions" in r])},
        "worst": sorted(({"clip": r["clip"], "t": r["t"], "outcome": r["outcome"],
                          "corner_error_max_m": r.get("corner_error_max_m"),
                          "confidence": r["confidence"], "problems": r["problems"]}
                         for r in rows), key=lambda x: -(x["corner_error_max_m"] or 1e9))[:5],
        "refusal_checks": refusals,
        "fallback_cost_vs_31_point": cost,
        "gt_lines_median_m": _q([r["gt_lines_median_m"] for r in rows]),
        "detect_ms": _q([r["detect_ms"] for r in rows]),
        "wall_s": round(wall_s, 1),
        "rows": rows,
    }


def text_summary(s: dict[str, Any]) -> str:
    o = s["outcomes"]
    ref = ("the 31-point calibration" if s["source"] == "teamtrack_top"
           else "the generator's exact homography")
    acc, every = s["corner_error_max_m_accepted"], s["corner_error_max_m_all"]
    pos = s["positions_vs_31_point_accepted"]
    lines = [f"Pitch auto-detect on {s['frames']} frames of {s['clips']} clips ({s['source']}); "
             f"correct = every corner within {s['max_corner_m']:g} m; reference = {ref}.",
             f"  success (accepted and correct): {o['success']} ({s['success_rate']:.0%})",
             f"  false accepts (accepted but wrong): {o['false_accept']}",
             f"  false rejects (refused but right): {o['false_reject']}",
             f"  correct rejects: {o['correct_reject']}",
             f"  max corner error per frame, accepted: median {acc['median']} m, worst "
             f"{acc['max']} m (all frames: median {every['median']}, worst {every['max']})",
             f"  player positions vs the reference, accepted: median of medians "
             f"{pos['median_m']['median']} m, worst {pos['max_m']['max']} m"]
    for name, r in s["refusal_checks"].items():
        lines.append(f"  {name} frame: {'refused' if r['refused'] else 'ACCEPTED (bad)'} "
                     f"(confidence {r['confidence']})")
    lines.append("4-corner fallback vs the reference (clicks on the true corners + noise):")
    for k, v in s["fallback_cost_vs_31_point"].items():
        lines.append(f"  {k}: positions median {v['positions_median_m']['median']} m (worst "
                     f"{v['positions_max_m']['max']} m); line error median "
                     f"{v['lines_median_m']['median']} m")
    lines.append(f"  the reference itself: line error median "
                 f"{s['gt_lines_median_m']['median']} m")
    lines.append(f"detect {s['detect_ms']['median']} ms per frame (median); wall {s['wall_s']} s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=3, help="frames per clip")
    ap.add_argument("--limit", type=int, default=None, help="first N clips only")
    ap.add_argument("--max-corner-m", type=float, default=1.0)
    ap.add_argument("--click-noise-px", default="5,10,20",
                    help="click noise (std, px of the full frame) for the fallback cost")
    ap.add_argument("--synthetic", type=int, default=0, help="N generated frames instead")
    ap.add_argument("--out", default="outputs/eval_autodetect.json")
    ap.add_argument("--failures", default="outputs/failures")
    args = ap.parse_args(argv)
    cfg = load_config()
    noise = [float(x) for x in args.click_noise_px.split(",") if x.strip()]
    rng = np.random.default_rng(int(cfg.get("seed", 42)))
    fail_dir = repo_path(args.failures)
    t0 = time.perf_counter()
    try:
        items = (synthetic_items(args.synthetic) if args.synthetic
                 else teamtrack_items(cfg, args.frames, args.limit))
        rows, refusals = [], {}
        for it in items:
            if not refusals:
                refusals = refusal_checks(it, cfg)
            r = evaluate_item(it, cfg, args.max_corner_m, noise, rng, fail_dir)
            rows.append(r)
            print(f"  {it.clip} t={it.t:.0f}: {r['outcome']:14s} conf {r['confidence']:.2f} "
                  f"max corner err {r.get('corner_error_max_m', 'n/a')} m "
                  f"({r['detect_ms']:.0f} ms)", flush=True)
    except Exception as exc:  # missing data / calibration: say what to do
        from gaffer.perception.pitch import CalibrationError as CE
        from gaffer.perception.video import VideoError
        from gaffer.teamtrack import DatasetError

        if isinstance(exc, DatasetError | CE | VideoError):
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        raise
    if not rows:
        print("ERROR: no frames evaluated", file=sys.stderr)
        return 2
    s = summarise(rows, refusals, args, time.perf_counter() - t0)
    out = repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    txt = text_summary(s)
    out.with_suffix(".txt").write_text(txt + "\n", encoding="utf-8")
    print("\n" + txt + f"\n-> {out}\n-> {out.with_suffix('.txt')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
