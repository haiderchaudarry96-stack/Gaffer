"""Generate a synthetic 90-minute match (MatchState) and its ground truth.

Usage:
    py scripts\\make_synthetic_match.py --out data\\synthetic\\match_001.json
    py scripts\\make_synthetic_match.py --seed 7 --random-schedule --out <path>.json

The default is the scripted `synthetic.match_001` schedule from config.yaml with seed 42.
The match file is large (~25 MB) and gitignored; it is reproducible from the seed. Ground truth
goes to `data/synthetic/ground_truth.json` (read only by the eval scripts).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.schema import ContractError, GroundTruth, parse_match_state
from gaffer.synthetic import generate_match, match_001_schedule, random_schedule


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/synthetic/match_001.json")
    parser.add_argument("--gt-out", default="data/synthetic/ground_truth.json")
    parser.add_argument("--seed", type=int, default=int(cfg["seed"]))
    parser.add_argument("--random-schedule", action="store_true",
                        help="random formation changes instead of the scripted match_001")
    parser.add_argument("--match-id", default=None)
    args = parser.parse_args(argv)

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    if args.random_schedule:
        schedule = random_schedule(np.random.default_rng(args.seed + 10_000), cfg)
    else:
        schedule = match_001_schedule(cfg)
    match_id = args.match_id or Path(args.out).stem.replace("match_", "synthetic_")
    match, gt = generate_match(args.seed, cfg, schedule, match_id)
    timings["simulate"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    try:
        parse_match_state(match, match_id)
        GroundTruth.model_validate(gt)
    except (ContractError, ValueError) as exc:
        print(f"ERROR: generated data does not satisfy the contract:\n{exc}", file=sys.stderr)
        return 1
    timings["validate"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    out, gt_out = repo_path(args.out), repo_path(args.gt_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    gt_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(match, separators=(",", ":")), encoding="utf-8")
    gt_out.write_text(json.dumps(gt, indent=2), encoding="utf-8")
    timings["write"] = time.perf_counter() - t0

    frames = match["frames"]
    per_frame = np.array([sum(p["team"] in ("home", "away") for p in f["players"])
                          for f in frames])
    broadcast = np.zeros(len(frames), dtype=bool)
    for v in gt["visibility"]:
        broadcast |= np.array([v["start_s"] <= f["t"] < v["end_s"] for f in frames])
    noise = Counter(e["kind"] for e in gt["noise_events"])
    print(f"{match_id}: {len(frames)} frames @ {match['fps']} fps, "
          f"{out.stat().st_size / 1e6:.1f} MB -> {out}")
    print(f"  players visible per frame: full view mean {per_frame[~broadcast].mean():.1f}, "
          f"broadcast window mean {per_frame[broadcast].mean():.1f} "
          f"(p5-p95 {np.percentile(per_frame[broadcast], 5):.0f}-"
          f"{np.percentile(per_frame[broadcast], 95):.0f}), "
          f"broadcast share {broadcast.mean():.0%}")
    print(f"  formation changes: {len(gt['changes'])}; decoys: {dict(noise)}")
    for c in gt["changes"]:
        print(f"    t={c['t']:7.1f}s {c['team']:4s} {c['from']} -> {c['to']}")
    print(f"  ground truth -> {gt_out}")
    print("timing: " + ", ".join(f"{k} {v:.2f}s" for k, v in timings.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
