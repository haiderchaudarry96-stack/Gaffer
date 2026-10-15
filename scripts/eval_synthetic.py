"""Evaluate the tactics engine against synthetic ground truth.

Usage:
    py scripts\\eval_synthetic.py --heldout2   # OFFICIAL since 15 Oct: seeds 110-119
    py scripts\\eval_synthetic.py --heldout2 --no-change-equivalence   # ablation: 4-3-3 != 4-2-3-1
    py scripts\\eval_synthetic.py --heldout    # seeds 100-109 (official 10-14 Oct, now seen)
    py scripts\\eval_synthetic.py --heldout --no-equivalence   # ablation: no formation families
    py scripts\\eval_synthetic.py            # match_001 + seeds 43-52 = the dev set "seeds 42-52"
    py scripts\\eval_synthetic.py --dev      # old tuning seeds 1000-1002 (never report these)

Seeds 43-52 were seen while deciding the 3-5-2 = 5-3-2 equivalence (10 Oct), seeds 100-109 while
deciding 4-3-3 = 4-2-3-1 for change detection (found there, 10 Oct). Everything changed on
15 Oct is tuned on match_001 + seeds 43-52 and reported on seeds 110-119.

Reports:
- formation accuracy per rolling window (strict: "uncertain" counts as wrong; confident-only;
  coverage), split by full view vs broadcast window, plus a confusion matrix;
- shape changes: hits / misses / false positives / mean detection delay, with every false
  positive attributed to what was happening (set piece, counter-attack, flicker, partial view).

Windows that straddle a true change are excluded from formation accuracy (the truth is mixed).
A change made while the camera showed only part of the pitch is often found minutes later, when
the full view returns: strictly that is a miss plus a false positive; it is also reported as a
"late detection after low visibility" so the number can be explained.
Results go to `outputs/eval_synthetic.json`.

Synthetic accuracy is an upper bound: generator and engine share one idea of what a formation
looks like. The honest real-data number is Phase 2's pipeline-vs-oracle comparison.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.schema import GroundTruth, load_ground_truth, load_match_state, parse_match_state
from gaffer.synthetic import generate_match, match_001_schedule, random_schedule
from gaffer.tactics.common import SIDES, TacticsConfig, extract_team_frames
from gaffer.tactics.events import line_levels
from gaffer.tactics.formation import UNCERTAIN
from gaffer.tactics.timeline import build_timeline

NOISE_PRIORITY = ("set_piece", "counter_attack", "flicker")


def _run_one(job: dict[str, Any]) -> dict[str, Any]:
    """Generate (or load) one match, run the engine, return a small summary."""
    cfg = _job_config(job)
    t0 = time.perf_counter()
    if job.get("path") and Path(job["path"]).exists() and job.get("gt_path"):
        match = load_match_state(job["path"])
        gt = load_ground_truth(job["gt_path"])
    else:
        if job["scripted"]:
            schedule = match_001_schedule(cfg)
        else:
            schedule = random_schedule(np.random.default_rng(job["seed"] + 10_000), cfg)
        m, g = generate_match(job["seed"], cfg, schedule, job["match_id"])
        match, gt = parse_match_state(m, job["match_id"]), GroundTruth.model_validate(g)
    t_gen = time.perf_counter() - t0
    tcfg = TacticsConfig.from_config(cfg)
    result = build_timeline(match, tcfg)
    tf = extract_team_frames(match, tcfg) if job.get("levels") else None
    return {
        "match_id": job["match_id"],
        "seed": job["seed"],
        "gt": gt.model_dump(by_alias=True),
        "windows": {s: [(w.t, w.centre, w.label, w.confidence) for w in result.windows[s]]
                    for s in SIDES},
        "changes": [{"team": c.team, "t": c.t, "detected_at_s": c.detected_at_s,
                     "from": c.from_formation, "to": c.to_formation,
                     "confidence": c.confidence} for c in result.changes],
        "line_drops": [{"team": d.team, "t": d.t, "detected_at_s": d.detected_at_s,
                        "from_m": float(d.from_formation), "to_m": float(d.to_formation)}
                       for d in result.line_drops],
        "line_levels": ({s: line_levels(tf[s], tcfg) for s in SIDES} if tf else None),
        "timeline_bytes": len(result.timeline.to_json().encode()),
        "timings_s": {"load_or_generate": t_gen, **result.timings_s},
    }


def _job_config(job: dict[str, Any]) -> dict[str, Any]:
    """The config for a job, with formation families switched off for the ablation."""
    cfg = load_config()
    if job.get("no_equivalence"):
        cfg = {**cfg, "formations": {**cfg["formations"], "equivalent": []}}
    if job.get("no_change_equivalence"):
        cfg = {**cfg, "formations": {**cfg["formations"], "change_equivalent": []}}
    return cfg


def _in_any(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= t < b for a, b in spans)


def score_formations(runs: list[dict[str, Any]], tcfg: TacticsConfig) -> dict[str, Any]:
    """Per-window formation accuracy against ground truth (exact label and family level)."""
    window_s = tcfg.window_s
    confusion: dict[str, Counter] = defaultdict(Counter)
    tally = {k: Counter() for k in ("all", "full_view", "broadcast")}
    for run in runs:
        gt = GroundTruth.model_validate(run["gt"])
        broadcast = [(v.start_s, v.end_s) for v in gt.visibility]
        for side in SIDES:
            intervals = [f for f in gt.formations if f.team == side]
            for t_end, centre, label, _conf in run["windows"][side]:
                start = t_end - window_s
                truth = next((f.formation for f in intervals
                              if f.from_s <= start and t_end <= f.to_s), None)
                if truth is None:
                    continue  # window straddles a true change
                confusion[truth][label] += 1
                view = "broadcast" if _in_any(centre, broadcast) else "full_view"
                for key in ("all", view):
                    tally[key]["total"] += 1
                    tally[key]["confident"] += label != UNCERTAIN
                    tally[key]["correct"] += label == truth
                    tally[key]["family_correct"] += (label != UNCERTAIN
                                                     and tcfg.family(label) == tcfg.family(truth))

    def summary(c: Counter) -> dict[str, float | int]:
        total, conf, correct = c["total"], c["confident"], c["correct"]
        return {"windows": total,
                "accuracy_strict": round(correct / total, 4) if total else 0.0,
                "accuracy_when_confident": round(correct / conf, 4) if conf else 0.0,
                "family_accuracy_when_confident": (round(c["family_correct"] / conf, 4)
                                                   if conf else 0.0),
                "coverage": round(conf / total, 4) if total else 0.0}

    return {"overall": summary(tally["all"]),
            "full_view": summary(tally["full_view"]),
            "broadcast": summary(tally["broadcast"]),
            "confusion": {k: dict(v) for k, v in sorted(confusion.items())}}


def score_changes(runs: list[dict[str, Any]], tolerance_s: float, window_s: float
                  ) -> dict[str, Any]:
    """Hits / misses / false positives / delays for detected shape changes."""
    hits = misses = fps = correct_to = 0
    delays, onset_errors = [], []
    fp_causes: Counter = Counter()
    fp_list, miss_list = [], []
    late = 0
    for run in runs:
        gt = GroundTruth.model_validate(run["gt"])
        broadcast = [(v.start_s, v.end_s) for v in gt.visibility]
        detected = list(run["changes"])
        used: set[int] = set()
        for change in gt.changes:
            best, best_d = None, None
            for i, d in enumerate(detected):
                if i in used or d["team"] != change.team:
                    continue
                dist = abs(d["t"] - change.t)
                if dist <= tolerance_s and (best_d is None or dist < best_d):
                    best, best_d = i, dist
            if best is None:
                misses += 1
                in_low_vis = next((b for a, b in broadcast if a <= change.t < b), None)
                late_hit = in_low_vis is not None and any(
                    d["team"] == change.team and d["to"] == change.to
                    and change.t < d["t"] <= in_low_vis + tolerance_s for d in detected)
                late += late_hit
                miss_list.append({"match": run["match_id"], "team": change.team, "t": change.t,
                                  "from": change.from_, "to": change.to,
                                  "late_detection_after_low_visibility": late_hit})
                continue
            used.add(best)
            d = detected[best]
            hits += 1
            correct_to += d["to"] == change.to
            delays.append(d["detected_at_s"] - change.t)
            onset_errors.append(d["t"] - change.t)
        for i, d in enumerate(detected):
            if i in used:
                continue
            fps += 1
            lo, hi = d["t"] - window_s / 2, d["detected_at_s"]
            kinds = {e.kind for e in gt.noise_events if e.start_s < hi and lo < e.end_s}
            cause = next((k for k in NOISE_PRIORITY if k in kinds), None)
            partial = any(a < hi and lo < b for a, b in broadcast)
            if cause is None:
                cause = "partial_visibility" if partial else "other"
            elif partial:
                cause += "+partial_visibility"
            fp_causes[cause] += 1
            fp_list.append({"match": run["match_id"], "team": d["team"], "t": round(d["t"], 1),
                            "from": d["from"], "to": d["to"], "cause": cause})
    return {
        "true_changes": hits + misses, "hits": hits, "misses": misses, "false_positives": fps,
        "late_detections_after_low_visibility": late,
        "hits_with_correct_new_formation": correct_to,
        "mean_detection_delay_s": round(float(np.mean(delays)), 1) if delays else None,
        "max_detection_delay_s": round(float(np.max(delays)), 1) if delays else None,
        "mean_abs_onset_error_s": (round(float(np.mean(np.abs(onset_errors))), 1)
                                   if onset_errors else None),
        "false_positive_causes": dict(fp_causes),
        "false_positive_list": fp_list,
        "missed_list": miss_list,
    }


def _print_report(name: str, form: dict[str, Any], ch: dict[str, Any]) -> None:
    o, f, b = form["overall"], form["full_view"], form["broadcast"]
    print(f"\n=== {name} ===")
    print("Formation accuracy (per 30 s window, windows straddling a true change excluded)")
    for label, s in (("overall", o), ("full view", f), ("broadcast window", b)):
        print(f"  {label:17s} strict {s['accuracy_strict']:6.1%} | when confident "
              f"{s['accuracy_when_confident']:6.1%} "
              f"(family {s['family_accuracy_when_confident']:6.1%}) | "
              f"coverage {s['coverage']:6.1%} ({s['windows']} windows)")
    print("Shape changes")
    print(f"  hits {ch['hits']}/{ch['true_changes']} | misses {ch['misses']} (of which "
          f"{ch['late_detections_after_low_visibility']} found late, after low visibility) | "
          f"false positives {ch['false_positives']} | correct new formation "
          f"{ch['hits_with_correct_new_formation']}/{ch['hits']}")
    print(f"  mean detection delay {ch['mean_detection_delay_s']} s (max "
          f"{ch['max_detection_delay_s']} s) | mean onset error {ch['mean_abs_onset_error_s']} s")
    if ch["false_positive_causes"]:
        print(f"  false-positive causes: {ch['false_positive_causes']}")


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ev = cfg["eval"]["synthetic"]
    parser = argparse.ArgumentParser(description="Evaluate the tactics engine on synthetic data")
    parser.add_argument("--dev", action="store_true", help="run on tuning seeds only")
    parser.add_argument("--heldout", action="store_true",
                        help="run on the held-out seeds (eval.synthetic.heldout_seeds): the "
                             "official synthetic numbers")
    parser.add_argument("--heldout2", action="store_true",
                        help="run on eval.synthetic.heldout_seeds_2 (110-119): official since 15 "
                             "Oct")
    parser.add_argument("--no-equivalence", action="store_true",
                        help="ablation: treat 3-5-2 and 5-3-2 (etc.) as different formations")
    parser.add_argument("--no-change-equivalence", action="store_true",
                        help="ablation: no change-detection-only families (4-3-3 = 4-2-3-1)")
    parser.add_argument("--extra", type=int, default=int(ev["extra_matches"]))
    parser.add_argument("--out", default=None,
                        help="default: outputs/eval_synthetic[_<mode>][_noeq].json")
    args = parser.parse_args(argv)

    if args.dev or args.heldout or args.heldout2:
        key, prefix = (("heldout_seeds_2", "heldout2") if args.heldout2 else
                       ("heldout_seeds", "heldout") if args.heldout else ("dev_seeds", "dev"))
        jobs = [{"match_id": f"synthetic_{prefix}_{s}", "seed": s, "scripted": False}
                for s in ev[key]]
    else:
        jobs = [{"match_id": "synthetic_001", "seed": int(cfg["seed"]), "scripted": True,
                 "path": str(repo_path("data/synthetic/match_001.json")),
                 "gt_path": str(repo_path("data/synthetic/ground_truth.json"))}]
        jobs += [{"match_id": f"synthetic_r{s}", "seed": s, "scripted": False}
                 for s in range(int(ev["first_seed"]), int(ev["first_seed"]) + args.extra)]

    for job in jobs:
        job["no_equivalence"] = args.no_equivalence
        job["no_change_equivalence"] = args.no_change_equivalence
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=int(ev["workers"])) as pool:
        runs = list(pool.map(_run_one, jobs))
    wall = time.perf_counter() - t0

    tcfg = TacticsConfig.from_config(_job_config(jobs[0]))
    tol = float(ev["tolerance_s"])
    mode = ("heldout2" if args.heldout2 else "heldout" if args.heldout else
            "dev" if args.dev else "eval")
    report: dict[str, Any] = {"mode": mode, "no_equivalence": args.no_equivalence,
                              "no_change_equivalence": args.no_change_equivalence,
                              "change_families": tcfg.change_families,
                              "matches": [r["match_id"] for r in runs],
                              "tolerance_s": tol, "window_s": tcfg.window_s,
                              "min_persist_s": tcfg.min_persist_s}
    if mode == "eval":
        first = [r for r in runs if r["match_id"] == "synthetic_001"]
        report["match_001"] = {"formation": score_formations(first, tcfg),
                               "changes": score_changes(first, tol, tcfg.window_s),
                               "timeline_bytes": first[0]["timeline_bytes"]}
        _print_report("match_001 (scripted)", report["match_001"]["formation"],
                      report["match_001"]["changes"])
    report["all"] = {"formation": score_formations(runs, tcfg),
                     "changes": score_changes(runs, tol, tcfg.window_s)}
    _print_report(f"all {len(runs)} matches", report["all"]["formation"],
                  report["all"]["changes"])

    conf = report["all"]["formation"]["confusion"]
    print("\nConfusion (rows = truth, columns = predicted, all matches)")
    labels = sorted({k for row in conf.values() for k in row} | set(conf))
    print("  " + " " * 9 + "".join(f"{lab:>10s}" for lab in labels))
    for truth in sorted(conf):
        print(f"  {truth:9s}" + "".join(f"{conf[truth].get(lab, 0):>10d}" for lab in labels))

    drops = [d for r in runs for d in r["line_drops"]]
    report["line_drops"] = {
        "per_match": round(len(drops) / len(runs), 2), "total": len(drops),
        "note": "synthetic GT has no line drops (contract v1.0): every event here is ball- or "
                "possession-driven line movement, i.e. a false alarm for a tactical drop",
        "list": [{"match": r["match_id"], **d} for r in runs for d in r["line_drops"]]}
    print(f"\nline_drop events: {len(drops)} in {len(runs)} matches "
          f"({len(drops) / len(runs):.2f} per match; no GT: all are false alarms by construction)")
    sizes = [r["timeline_bytes"] for r in runs]
    report["timeline_bytes"] = {"max": max(sizes), "mean": round(float(np.mean(sizes)))}
    per_match = np.mean([r["timings_s"]["formation"] for r in runs])
    report["timing_s"] = {"wall": round(wall, 1), "formation_per_match": round(per_match, 1)}
    print(f"\nTimeline size: max {max(sizes) / 1024:.1f} KB, mean {np.mean(sizes) / 1024:.1f} KB")
    print(f"timing: wall {wall:.1f}s for {len(runs)} matches "
          f"({ev['workers']} workers), formation stage {per_match:.1f}s per match")
    print("Note: synthetic accuracy is an upper bound (generator and engine share one model of "
          "a formation); real accuracy comes from Phase 2 pipeline vs oracle.")

    default_out = ("outputs/eval_synthetic" + ("" if mode == "eval" else f"_{mode}")
                   + ("_noeq" if args.no_equivalence else "")
                   + ("_nocheq" if args.no_change_equivalence else "") + ".json")
    out = repo_path(args.out or default_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
