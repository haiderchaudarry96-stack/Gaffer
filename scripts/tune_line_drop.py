"""Choose the `line_drop` thresholds (`tactics.line_drop`) on the synthetic dev set.

Synthetic ground truth cannot label line drops without changing the frozen contract
(`GTNoiseEvent.kind` is a closed list), and the generator never drops a line on purpose: its
back line follows the ball and possession only (`synthetic.movement.back_line_*`). So on
synthetic data every `line_drop` is a **false alarm for a tactical drop**: this sweep measures
how often ball-driven movement alone fires the rule, nothing about recall.

Rule chosen with that in mind (before seeing the sweep): the most sensitive setting (smallest
drop X, then shortest hold Y) firing at most `--budget` events per match (both teams, 90 min)
on the dev set (match_001 + seeds 43-52); if none does, the setting with the fewest. `--heldout2`
re-measures the configured setting on seeds 110-119.

Usage:
    py scripts\\tune_line_drop.py                 # dev set -> outputs/tune_line_drop_dev.json
    py scripts\\tune_line_drop.py --heldout2      # rate of the configured setting on 110-119
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.tactics.common import SIDES, TacticsConfig
from gaffer.tactics.events import detect_line_drops

DROPS_M = (4.0, 6.0, 8.0, 10.0, 12.0)
HOLDS_S = (30.0, 60.0, 90.0, 120.0, 180.0)


def main(argv: list[str] | None = None) -> int:
    import eval_synthetic as es  # noqa: PLC0415 (same folder; reuse its match runner)

    cfg = load_config()
    ev = cfg["eval"]["synthetic"]
    ap = argparse.ArgumentParser(description="line_drop thresholds on synthetic dev seeds")
    ap.add_argument("--budget", type=float, default=1.0, help="max events per match")
    ap.add_argument("--heldout2", action="store_true", help="seeds 110-119, configured setting")
    args = ap.parse_args(argv)
    if args.heldout2:
        jobs = [{"match_id": f"synthetic_heldout2_{s}", "seed": s, "scripted": False}
                for s in ev["heldout_seeds_2"]]
    else:
        jobs = [{"match_id": "synthetic_001", "seed": int(cfg["seed"]), "scripted": True,
                 "path": str(repo_path("data/synthetic/match_001.json")),
                 "gt_path": str(repo_path("data/synthetic/ground_truth.json"))}]
        jobs += [{"match_id": f"synthetic_r{s}", "seed": s, "scripted": False}
                 for s in range(int(ev["first_seed"]), int(ev["first_seed"])
                                + int(ev["extra_matches"]))]
    for j in jobs:
        j["levels"] = True
    with ProcessPoolExecutor(max_workers=int(ev["workers"])) as pool:
        runs = list(pool.map(es._run_one, jobs))
    tcfg = TacticsConfig.from_config(cfg)
    lv = {r["match_id"]: {s: [tuple(x) for x in r["line_levels"][s]] for s in SIDES}
          for r in runs}
    spread = [abs(a[1] - b[1]) for r in lv.values() for s in SIDES
              for a, b in zip(r[s][:-12], r[s][12:], strict=False)
              if a[1] is not None and b[1] is not None]  # 60 s apart
    print(f"{len(runs)} matches; |change of the 30 s line level over 60 s|: median "
          f"{np.median(spread):.1f} m, p90 {np.percentile(spread, 90):.1f} m, p99 "
          f"{np.percentile(spread, 99):.1f} m")

    def rate(x: float, y: float) -> tuple[float, list[dict[str, Any]]]:
        ev_ = [{"match": m, "team": s, "t": round(d.t, 1), "from_m": d.from_formation,
                "to_m": d.to_formation} for m, r in lv.items() for s in SIDES
               for d in detect_line_drops(r[s], s, tcfg, x, y)]
        return len(ev_) / len(runs), ev_

    if args.heldout2:
        x, y = tcfg.line_drop_m, tcfg.line_drop_hold_s
        per, evs = rate(x, y)
        print(f"configured X {x} m, Y {y} s: {per:.2f} events per match on seeds 110-119")
        out = {"setting": [x, y], "per_match": per, "events": evs}
        repo_path("outputs/tune_line_drop_heldout2.json").write_text(json.dumps(out, indent=2),
                                                                     encoding="utf-8")
        return 0
    grid = []
    print(f"events per match (dev set), rows X (m), columns Y (s): {HOLDS_S}")
    for x in DROPS_M:
        row = [rate(x, y)[0] for y in HOLDS_S]
        grid += [{"drop_m": x, "hold_s": y, "per_match": round(p, 2)}
                 for y, p in zip(HOLDS_S, row, strict=True)]
        print(f"  {x:5.1f} " + " ".join(f"{p:6.2f}" for p in row))
    ok = [g for g in grid if g["per_match"] <= args.budget]
    if ok:
        best = min(ok, key=lambda g: (g["drop_m"], g["hold_s"]))
        how = f"budget {args.budget:g}/match met; smallest X then Y"
    else:  # no setting meets the budget: the fewest false alarms (not a looser budget)
        best = min(grid, key=lambda g: (g["per_match"], g["drop_m"], g["hold_s"]))
        how = f"NO setting meets the {args.budget:g}/match budget; fewest false alarms"
    print(f"chosen ({how}): {best}")
    examples = rate(best["drop_m"], best["hold_s"])[1] if best else []
    repo_path("outputs/tune_line_drop_dev.json").write_text(json.dumps(
        {"budget_per_match": args.budget, "grid": grid, "chosen": best,
         "events_at_chosen": examples,
         "level_change_60s_m": {"median": float(np.median(spread)),
                                "p90": float(np.percentile(spread, 90))}}, indent=2),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(repo_path("scripts")))
    raise SystemExit(main())
