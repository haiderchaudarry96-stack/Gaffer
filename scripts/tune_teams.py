"""Re-choose the team classifier settings on the dev clips only (`detector.eval.dev_clips`).

On 14 Oct `teams.l_weight`, `teams.gate` and the keeper zone were chosen with eval-clip data.
This script redoes the choice on the two dev clips (top D_..._1530, side F_..._1680) and never
opens another clip.

1. **colour settings.** The view's detector runs on the dev clip (2 fps). Its boxes are matched
   to GT players (`tracking.eval.match_m`, pitch metres) to get the truth of every crop the
   pipeline would see: matched outfield player -> their team; matched goalkeeper and every
   unmatched detection (referee, assistant referees, staff, false positives: GT labels only
   the 22 players) -> "other". For every (l_weight, gate) on a small grid, `fit_team_model` is
   fitted on all crops of the clip, exactly as the pipeline does, and scored by **3-class
   per-crop accuracy**. Selection: the best mean over the two views; ties (within 0.1 %) go to
   the smaller gate. (A first version scored GT crops only and preferred wider gates, which
   then put officials into the teams: GT has no officials. Logged in FAILURE_LOG.)
2. **keeper zone.** Each team's goalkeeper (the GT player whose median position is nearest
   their own goal line) and their median distance from it, on each dev clip.

Usage:
    py scripts\\tune_teams.py            # -> outputs/tune_teams_dev.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from itertools import product
from typing import Any

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.evaluation import match_distance
from gaffer.perception.detector import DetectorError, make_detector
from gaffer.perception.drift import GeometryProvider
from gaffer.perception.pipeline import foot_xy
from gaffer.perception.pitch import Calibration, CalibrationError, PitchModel
from gaffer.perception.team_classifier import TeamSettings, fit_team_model, shirt_features
from gaffer.perception.video import VideoError, VideoSource
from gaffer.teamtrack import DatasetError, find_clips, foot_points, load_gt

L_WEIGHTS = (0.25, 0.5, 0.75, 1.0)
GATES = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0)


def collect(cfg: dict[str, Any], view: str, stem: str, fps: float) -> dict[str, Any]:
    """Unweighted shirt features (l_weight 1) of every detection on one dev clip, with its
    truth ('home' / 'away' / 'other') and kind ('outfield' / 'keeper' / 'unmatched'); plus the
    dev keepers' median distance from their own goal line (GT)."""
    clip = next(c for c in find_clips(view, cfg) if c.stem == stem)
    gt = load_gt(clip.csv).boxes
    side_of = {tid: t["side"] for tid, t in cfg["teamtrack"]["teams"].items()}
    gt = gt[gt["team"].isin(list(side_of))]
    ts = dataclasses.replace(TeamSettings.from_config(cfg, view), l_weight=1.0)
    calib = Calibration.for_view(cfg, view)
    model = PitchModel(calib.length_m, calib.width_m)
    geo = GeometryProvider(calib, cfg, view, model)
    det = make_detector(cfg, view, model)
    if hasattr(det, "reset"):
        det.reset(fps)
    foot = cfg["perception"]["foot_point"][view]
    match_m = float(cfg["tracking"]["eval"]["match_m"][view])
    src = VideoSource(clip.video, start_s=clip.start_s)
    frames = []  # per frame: features, ok, matched GT player id per detection ("" = none)
    gt_xy: dict[str, list[np.ndarray]] = {}
    gt_side: dict[str, str] = {}
    for _, _, fi, frame in src.frames(src.sample_times(fps)):
        g = geo.for_frame(frame)
        rows = gt[gt["frame"] == fi]
        gxy = g.mapper.to_pitch(foot_points(rows, foot)) if len(rows) else np.zeros((0, 2))
        pids = [f"{t}:{p}" for t, p in zip(rows["team"], rows["player"], strict=True)]
        for p, t, q in zip(pids, rows["team"], gxy, strict=True):
            gt_xy.setdefault(p, []).append(q)
            gt_side[p] = side_of[t]
        persons = det.detect(frame, g.mapper).persons()
        dxy = g.mapper.to_pitch(foot_xy(persons.boxes, foot)) if len(persons) \
            else np.zeros((0, 2))
        md = match_distance(gxy, dxy, match_m)
        who = [""] * len(persons)
        for i, j in md.pairs:
            who[j] = pids[i]
        f, ok = shirt_features(frame, persons.boxes, ts)
        frames.append((f, ok, who))
    # goalkeeper of each side: the player whose median x is nearest that side's own goal line.
    # TeamID 0 (home) defends the right goal on both views (oracle, DATA_NOTES).
    own_goal = {"home": calib.length_m, "away": 0.0}
    keepers, keeper_dist = set(), {}
    for side in ("home", "away"):
        meds = {p: np.median(np.array(v), axis=0) for p, v in gt_xy.items()
                if gt_side[p] == side}
        p = min(meds, key=lambda q: abs(meds[q][0] - own_goal[side]))
        keepers.add(p)
        keeper_dist[side] = {"player": p,
                             "median_depth_m": round(float(abs(meds[p][0] - own_goal[side])), 1),
                             "median_lateral_from_centre_m":
                                 round(float(abs(meds[p][1] - calib.width_m / 2)), 1)}
    feats = np.concatenate([f[ok] for f, ok, _ in frames])
    who = [w for f, ok, ws in frames for w, k in zip(ws, ok, strict=True) if k]
    kind = np.array(["unmatched" if not w else "keeper" if w in keepers else "outfield"
                     for w in who])
    truth = np.array([gt_side[w] if k == "outfield" else "other"
                      for w, k in zip(who, kind, strict=True)])
    return {"feats": feats, "truth": truth, "kind": kind, "keepers": keeper_dist,
            "crops": {k: int((kind == k).sum()) for k in ("outfield", "keeper", "unmatched")}}


def score(data: dict[str, Any], cfg: dict[str, Any], view: str, l_weight: float, gate: float,
          seed: int) -> dict[str, float]:
    """3-class per-crop accuracy of a team model fitted on all of this clip's crops."""
    s = dataclasses.replace(TeamSettings.from_config(cfg, view), l_weight=l_weight, gate=gate)
    X = data["feats"].copy()
    X[:, 0] *= l_weight
    hints = {k: cfg["perception"]["teams"][k]["shirt_hint"] for k in ("home", "away")}
    lab, _ = fit_team_model(X, hints, s, seed=seed).classify(X)
    pred = np.array(["home", "away", "other"])[lab]
    right = pred == data["truth"]
    k = data["kind"]
    return {"accuracy_3class": round(float(right.mean()), 4),
            "outfield_right_team": round(float(right[k == "outfield"].mean()), 4),
            "keeper_other": round(float(right[k == "keeper"].mean()), 4),
            "unmatched_other": round(float(right[k == "unmatched"].mean()), 4)}


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Team classifier settings on dev clips only")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--refresh", action="store_true", help="recompute the cached crops")
    args = ap.parse_args(argv)
    dev = cfg["detector"]["eval"]["dev_clips"]
    stems = {"top": next(s for s in dev if s.startswith("D_")),
             "side": next(s for s in dev if s.startswith("F_"))}
    cache = repo_path("outputs/_cache")
    cache.mkdir(parents=True, exist_ok=True)

    def cached(v: str, stem: str) -> dict[str, Any]:
        """Detection crops of a dev clip (the detector is slow on the side view)."""
        f = cache / f"tune_teams_{stem}_{args.fps:g}fps.json"
        if f.exists() and not args.refresh:
            d = json.loads(f.read_text(encoding="utf-8"))
            return {**d, "feats": np.array(d["feats"], np.float32), "truth": np.array(d["truth"]),
                    "kind": np.array(d["kind"])}
        d = collect(cfg, v, stem, args.fps)
        f.write_text(json.dumps({**d, "feats": d["feats"].tolist(), "truth": d["truth"].tolist(),
                                 "kind": d["kind"].tolist()}), encoding="utf-8")
        return d

    try:
        data = {v: cached(v, s) for v, s in stems.items()}
    except (DatasetError, VideoError, CalibrationError, DetectorError, StopIteration) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    seed = int(cfg.get("seed", 42))
    grid = []
    for lw, g in product(L_WEIGHTS, GATES):
        r = {v: score(data[v], cfg, v, lw, g, seed) for v in stems}
        mean = float(np.mean([r[v]["accuracy_3class"] for v in stems]))
        grid.append({"l_weight": lw, "gate": g, "mean_accuracy_3class": round(mean, 4), **r})
    # ties (to 0.1 %) go to the smaller gate
    grid.sort(key=lambda x: (-round(x["mean_accuracy_3class"], 3), x["gate"]))
    best = grid[0]
    print(f"dev clips {stems}; crops: {', '.join(f'{v} {data[v]['crops']}' for v in stems)}")
    print(f"{'l_weight':>8s} {'gate':>5s} {'mean':>7s} | per view: 3-class, outfield right team, "
          "keeper other, unmatched other")
    for x in grid:
        print(f"{x['l_weight']:8.2f} {x['gate']:5.1f} {x['mean_accuracy_3class']:7.4f} | " +
              " | ".join(f"{v}: {x[v]['accuracy_3class']:.3f} {x[v]['outfield_right_team']:.3f} "
                         f"{x[v]['keeper_other']:.2f} {x[v]['unmatched_other']:.2f}"
                         for v in stems))
    print(f"chosen: l_weight {best['l_weight']}, gate {best['gate']}")
    print("goalkeepers on the dev clips (median distance from own goal line):")
    for v in stems:
        print(f"  {v}: {data[v]['keepers']}")
    out = repo_path("outputs/tune_teams_dev.json")
    out.write_text(json.dumps({"dev_clips": stems, "chosen": {k: best[k] for k in
                                                              ("l_weight", "gate")},
                               "crops": {v: data[v]["crops"] for v in stems}, "grid": grid,
                               "keepers": {v: data[v]["keepers"] for v in stems}}, indent=2),
                   encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
