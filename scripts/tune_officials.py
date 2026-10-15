"""Choose the officials rule thresholds (`perception.official`) on the dev clips only.

Runs the pipeline once per dev clip (top D_..._1530 at the configured top rate, side F_..._1680)
with the rule switched off, then sweeps `outside_m` x `min_share` over the cached tracks:

- **players flagged**: output detections matched to a GT player (`tracking.eval.match_m`) whose
  track the rule would call an official (must stay ~0: GT contains only the 22 players);
- **unmatched caught**: unmatched detections of any label (GT has no officials, so these are
  officials, staff or false positives) whose track the rule calls an official. Any label,
  because the rule is geometric and must not depend on the colour settings (with the dev-chosen
  colours the officials are mostly "referee" already; an eval clip may differ);
- phantoms: unmatched detections labelled home/away, and how many the rule removes (context).

Selection: the settings that catch the most unmatched detections with no flagged player on
either clip;
among those, the `outside_m` with the widest plateau of tied `min_share` values and the middle
of that plateau (a first version took the largest tied values, which sat on a cliff edge).
Also prints where the referee-labelled tracks stand (median distance from the nearest goal
line), the other half of the keeper-zone decision (`scripts/tune_teams.py` gives the keepers).

Usage:
    py scripts\\tune_officials.py         # -> outputs/tune_officials_dev.json
"""

from __future__ import annotations

import copy
import json
import sys
from collections import defaultdict
from itertools import product
from typing import Any

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.evaluation import match_distance
from gaffer.perception.detector import DetectorError
from gaffer.perception.pipeline import PipelineError, official_tracks, run
from gaffer.perception.pitch import CalibrationError
from gaffer.perception.video import VideoError, VideoSource
from gaffer.schema import ContractError
from gaffer.teamtrack import DatasetError, find_clips, foot_points, load_gt

OUTSIDE_M = (0.0, 0.25, 0.5, 0.75)
MIN_SHARE = (0.5, 0.6, 0.75, 0.9)


def dev_run(cfg: dict[str, Any], view: str, stem: str) -> dict[str, Any]:
    """Pipeline on one dev clip (rule off) -> per output detection: track id, label, matched."""
    clips = find_clips(view, cfg)
    ci = next(i for i, c in enumerate(clips) if c.stem == stem)
    clip = clips[ci]
    src = VideoSource(repo_path(cfg["teamtrack"]["clip_lists"]) / f"teamtrack_{view}.clips.json")
    off = copy.deepcopy(cfg)
    off["perception"]["official"]["min_share"] = 2.0  # rule off
    res = run(src.uri, view=view, start_s=clip.start_s, end_s=clip.end_s, cfg=off, progress=True)
    gt = load_gt(clip.csv).boxes
    side_of = {tid: t["side"] for tid, t in cfg["teamtrack"]["teams"].items()}
    gt = gt[gt["team"].isin(list(side_of))]
    match_m = float(cfg["tracking"]["eval"]["match_m"][view])
    track_pos: dict[int, list[np.ndarray]] = defaultdict(list)
    rows = []  # (track id, label, matched)
    for r in res.records:
        for i, tid in enumerate(r.track_ids):
            if tid >= 0:
                track_pos[int(tid)].append(r.xy[i])
        if not r.output:
            continue
        loc = src.locate(r.t)
        g = gt[gt["frame"] == loc[1]] if loc else gt.iloc[:0]
        gxy = r.mapper.to_pitch(foot_points(g, cfg["perception"]["foot_point"][view])) \
            if len(g) else np.zeros((0, 2))
        idx = [j for j in range(len(r.boxes)) if r.track_ids[j] >= 0 and r.teams[j] != "static"]
        md = match_distance(gxy, r.xy[idx] if idx else np.zeros((0, 2)), match_m)
        matched = {j for _, j in md.pairs}
        rows += [(int(r.track_ids[j]), r.teams[j], k in matched) for k, j in enumerate(idx)]
    L = res.match.pitch.length_m
    ref_goal = [float(min(np.median(np.array(track_pos[t])[:, 0]),
                          L - np.median(np.array(track_pos[t])[:, 0])))
                for t in {t for t, lab, _ in rows if lab == "referee"}]
    return {"track_pos": track_pos, "rows": rows, "frames": sum(r.output for r in res.records),
            "width": res.match.pitch.width_m, "referee_goal_dist_m": sorted(ref_goal)}


def main() -> int:
    cfg = load_config()
    dev = cfg["detector"]["eval"]["dev_clips"]
    stems = {"top": next(s for s in dev if s.startswith("D_")),
             "side": next(s for s in dev if s.startswith("F_"))}
    try:
        runs = {v: dev_run(cfg, v, s) for v, s in stems.items()}
    except (DatasetError, VideoError, CalibrationError, DetectorError, PipelineError,
            ContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    grid = []
    for m, sh in product(OUTSIDE_M, MIN_SHARE):
        row: dict[str, Any] = {"outside_m": m, "min_share": sh}
        for v, d in runs.items():
            flagged = official_tracks(d["track_pos"], d["width"],
                                      {"outside_m": m, "min_share": sh})
            phantoms = [t for t, lab, ok in d["rows"] if not ok and lab in ("home", "away")]
            unmatched = [t for t, _, ok in d["rows"] if not ok]
            row[v] = {
                "unmatched_per_frame": round(len(unmatched) / d["frames"], 2),
                "unmatched_caught_per_frame": round(
                    sum(1 for t in unmatched if t in flagged) / d["frames"], 2),
                "players_flagged": sum(1 for t, _, ok in d["rows"] if ok and t in flagged),
                "phantoms_per_frame": round(len(phantoms) / d["frames"], 2),
                "phantoms_removed_per_frame": round(
                    sum(1 for t in phantoms if t in flagged) / d["frames"], 2),
                "tracks_flagged": len(flagged)}
        row["eligible"] = all(row[v]["players_flagged"] == 0 for v in runs)
        row["removed"] = round(sum(row[v]["unmatched_caught_per_frame"] for v in runs), 2)
        grid.append(row)
    grid.sort(key=lambda x: (not x["eligible"], -x["removed"], -x["outside_m"], -x["min_share"]))
    # robust pick among the equally good settings: the outside_m with the widest plateau of
    # tied min_share values, and the middle of that plateau (not its edge)
    top = [x for x in grid if x["eligible"] and x["removed"] == grid[0]["removed"]]
    plateau: dict[float, list[float]] = defaultdict(list)
    for x in top:
        plateau[x["outside_m"]].append(x["min_share"])
    m_best = max(plateau, key=lambda m: (len(plateau[m]), m))
    shares = sorted(plateau[m_best])
    pick = (m_best, shares[len(shares) // 2])
    best = next(x for x in grid if (x["outside_m"], x["min_share"]) == pick)
    print(f"dev clips {stems}")
    print(f"{'outside_m':>9s} {'share':>5s} | per view: players flagged, unmatched/frame, "
          "caught, phantoms/frame, removed")
    for x in grid:
        print(f"{x['outside_m']:9.2f} {x['min_share']:5.2f} | " + " | ".join(
            f"{v}: {x[v]['players_flagged']}, {x[v]['unmatched_per_frame']}, "
            f"{x[v]['unmatched_caught_per_frame']}, {x[v]['phantoms_per_frame']}, "
            f"{x[v]['phantoms_removed_per_frame']}" for v in runs)
            + ("" if x["eligible"] else "  (flags players)"))
    print(f"chosen: outside_m {best['outside_m']}, min_share {best['min_share']}")
    for v, d in runs.items():
        print(f"  {v}: referee-labelled track medians, distance from nearest goal line (m): "
              f"{[round(x, 1) for x in d['referee_goal_dist_m']]}")
    out = repo_path("outputs/tune_officials_dev.json")
    out.write_text(json.dumps({"dev_clips": stems, "chosen": {k: best[k] for k in
                                                              ("outside_m", "min_share")},
                               "grid": grid,
                               "referee_goal_dist_m": {v: d["referee_goal_dist_m"]
                                                       for v, d in runs.items()}}, indent=2),
                   encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
