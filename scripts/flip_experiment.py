"""Task A (Phase 3, step 6): can shape metrics tell a real 4-3-3 <-> 4-2-3-1 change from a flip?

On validation seeds 100-109, 14 of the rules arm's 19 false alerts are 4-3-3 <-> 4-2-3-1 flips
that hold for over a minute (FAILURE_LOG 2026-10-15). Idea: a candidate the rules would confirm
whose from / to shapes are both in that pair becomes **uncertain ("same shape family, no metric
change")** when the team's shape metrics do not move between before and after.

Fixed before looking at any data (one new threshold, the user allowed at most two):
- D = max(|d line|, |d width|, |d compactness|) in metres, `tactics.metrics.span_metrics` of the
  team on the **re-analysed** pass, before = [onset - before_s, onset], after = [detection,
  detection + look-ahead] (the windows the rules already use for coverage);
- rule: rules decision confirmed AND {from, to} = {4-3-3, 4-2-3-1} AND D <= T -> uncertain;
- T from the grid {off, 0.5, 1.0, ..., 8.0} m, chosen by **leave-one-seed-out cross-validation**
  over dev seeds 42-52 (match_001 + 43-52) **plus seeds 100-109, which become development data
  for this experiment only**. Per fold: T maximising alerted hits - false alerts on the other 20
  matches (the step-1 rule), ties -> the smaller intervention (off first); applied to the
  held-out match. Seeds 110-119 are never loaded here.
- "Clearly helps" (fixed in advance): cross-validated false alerts fall by >= 5 (of 23) with
  <= 2 alerted real changes lost (of 67). Otherwise the rule stays OFF.

    py scripts\\flip_experiment.py            # evidence + metrics cached in outputs/agent_cache/
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from gaffer.agent.context import MatchContext
from gaffer.agent.verify import VerifyConfig
from gaffer.config import load_config, repo_path
from gaffer.schema import GroundTruth, load_ground_truth, load_match_state, parse_match_state
from gaffer.synthetic import generate_match, match_001_schedule, random_schedule
from gaffer.tactics.metrics import span_metrics

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_agent import decide, jobs_for, label_candidates  # noqa: E402

PAIR = frozenset({"4-3-3", "4-2-3-1"})
METRICS = ("defensive_line_m", "width_m", "compactness_m")
GRID = [None] + [round(x, 1) for x in np.arange(0.5, 8.01, 0.5)]  # None = rule off
CACHE = "outputs/agent_cache/flip_metrics.json"
OUT = "outputs/flip_experiment.json"


def collect(job: dict[str, Any]) -> dict[str, Any]:
    """Worker: like `eval_agent.collect`, plus before/after metrics on the re-analysed pass."""
    cfg = load_config()
    if job.get("path") and Path(job["path"]).exists():
        match, gt = load_match_state(job["path"]), load_ground_truth(job["gt_path"])
    else:
        sched = (match_001_schedule(cfg) if job["scripted"]
                 else random_schedule(np.random.default_rng(job["seed"] + 10_000), cfg))
        m, g = generate_match(job["seed"], cfg, sched, job["match_id"])
        match, gt = parse_match_state(m, job["match_id"]), GroundTruth.model_validate(g)
    ctx = MatchContext(match, cfg)
    v = ctx.vcfg
    cands = []
    for c in ctx.candidates:
        a, b = ctx.required_span(c)
        data = ctx.reanalyse_tactics(a, b)
        met = {}
        for name, data_ in (("re", data), ("first", ctx.first)):
            spans = {"before": (c.t - v.before_s, c.t),
                     "after": (c.detected_at_s, c.detected_at_s + v.lookahead_s)}
            vals = {}
            for k, (lo, hi) in spans.items():
                fr = [f for f in data_.frames[c.team] if lo <= f.t <= hi]
                sm = span_metrics(fr, c.team, ctx.tcfg)
                vals[k] = {m_: getattr(sm, m_) for m_ in METRICS}
            met[name] = vals
        cands.append({"id": c.id, "team": c.team, "t": c.t, "detected_at_s": c.detected_at_s,
                      "from": c.from_, "to": c.to, "confidence": c.confidence,
                      "first": asdict(ctx.evidence(c)), "reanalysis": asdict(ctx.evidence(c, data)),
                      "metrics": met})
    return {"match_id": job["match_id"], "seed": job["seed"],
            "gt": gt.model_dump(by_alias=True), "candidates": cands}


def _jsonable(o: Any) -> Any:
    """numpy scalars (counts of numpy bools) -> Python numbers for json."""
    return o.item() if hasattr(o, "item") else str(o)


def delta(c: dict[str, Any], src: str = "re") -> float | None:
    """D: largest absolute before -> after change of the three metrics (None if missing)."""
    m = c["metrics"][src]
    ds = [abs(m["after"][k] - m["before"][k]) for k in METRICS
          if m["after"][k] is not None and m["before"][k] is not None]
    return max(ds) if len(ds) == len(METRICS) else None


def score(runs: list[dict[str, Any]], vcfg: VerifyConfig, T: float | None, tol: float
          ) -> dict[str, Any]:
    """Rules arm with the flip rule at threshold T (None = off) on `runs`."""
    tot = Counter()
    rows = []
    for run in runs:
        lab = label_candidates(run, tol)
        tot["true_changes"] += lab["true_changes"]
        by_id = {c["id"]: c for c in run["candidates"]}
        for d in decide(run, vcfg, "rules"):
            c = by_id[d["id"]]
            hit = d["id"] in lab["hits"]
            dec = d["decision"]
            pair = frozenset({c["from"], c["to"]}) == PAIR
            D = delta(c)
            flipped = (T is not None and dec == "confirmed" and pair and D is not None
                       and D <= T)
            if flipped:
                dec = "uncertain"
            kind = "hit" if hit else "fp"
            tot[f"{kind}_{dec}"] += 1
            tot["candidates"] += 1
            tot["rule_fired"] += flipped
            tot[f"rule_fired_{kind}"] += flipped
            if pair and d["decision"] == "confirmed":
                tot[f"pair_confirmed_{kind}"] += 1
            rows.append({"match": run["match_id"], "seed": run["seed"], "id": c["id"],
                         "team": c["team"], "from": c["from"], "to": c["to"], "hit": hit,
                         "pair": pair, "rules_decision": d["decision"], "decision": dec,
                         "D_re": None if D is None else round(D, 2),
                         "D_first": (None if delta(c, "first") is None
                                     else round(delta(c, "first"), 2)),
                         "rule_fired": flipped})
    s = {"T": T, "alerted_hits": tot["hit_confirmed"], "false_alerts": tot["fp_confirmed"],
         "true_changes": tot["true_changes"], "candidates": tot["candidates"],
         "uncertain": tot["hit_uncertain"] + tot["fp_uncertain"],
         "uncertain_share": round((tot["hit_uncertain"] + tot["fp_uncertain"])
                                  / max(1, tot["candidates"]), 3),
         "rule_fired": tot["rule_fired"], "lost_hits": tot["rule_fired_hit"],
         "removed_false_alerts": tot["rule_fired_fp"],
         "pair_confirmed_hits": tot["pair_confirmed_hit"],
         "pair_confirmed_fps": tot["pair_confirmed_fp"]}
    return {"summary": s, "rows": rows}


def choose(runs: list[dict[str, Any]], vcfg: VerifyConfig, tol: float) -> float | None:
    """T maximising alerted hits - false alerts; ties -> smallest intervention (off first)."""
    best, best_v = None, None
    for T in GRID:
        s = score(runs, vcfg, T, tol)["summary"]
        v = s["alerted_hits"] - s["false_alerts"]
        if best_v is None or v > best_v:
            best, best_v = T, v
    return best


def main() -> int:
    cfg = load_config()
    tol = float(cfg["eval"]["synthetic"]["tolerance_s"])
    vcfg = VerifyConfig.from_config(cfg)
    cache = repo_path(CACHE)
    t0 = time.perf_counter()
    if cache.exists():
        runs = json.loads(cache.read_text(encoding="utf-8"))
        print(f"evidence + metrics from cache {cache}")
    else:
        jobs = jobs_for("dev", cfg) + jobs_for("val", cfg)
        assert not {j["seed"] for j in jobs} & set(cfg["eval"]["synthetic"]["heldout_seeds_2"])
        with ProcessPoolExecutor(max_workers=int(cfg["eval"]["synthetic"]["workers"])) as pool:
            runs = list(pool.map(collect, jobs))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(runs), encoding="utf-8")
        print(f"{len(runs)} matches in {time.perf_counter() - t0:.0f} s -> {cache}")
    seeds = [r["seed"] for r in runs]
    print(f"matches: {len(runs)} (seeds {seeds})")

    base = score(runs, vcfg, None, tol)
    b = base["summary"]
    print(f"\nrules arm, rule off (all 21): alerted {b['alerted_hits']}/{b['true_changes']}, "
          f"false alerts {b['false_alerts']}; confirmed 4-3-3<->4-2-3-1: "
          f"{b['pair_confirmed_hits']} real, {b['pair_confirmed_fps']} false")
    pair_rows = [r for r in base["rows"] if r["pair"] and r["rules_decision"] == "confirmed"]
    for kind in (True, False):
        ds = sorted(r["D_re"] for r in pair_rows if r["hit"] is kind and r["D_re"] is not None)
        print(f"  D (re-analysed) for confirmed pair candidates, {'real' if kind else 'false'}: "
              f"{ds}")

    # in-sample curve (all 21 matches)
    curve = [score(runs, vcfg, T, tol)["summary"] for T in GRID]
    print("\nin-sample (21 matches): T -> alerted / false alerts / lost hits / removed FA")
    for s in curve:
        print(f"  T={s['T']}: {s['alerted_hits']} / {s['false_alerts']} / {s['lost_hits']} / "
              f"{s['removed_false_alerts']}")

    # leave-one-seed-out cross-validation
    folds = []
    cv = Counter()
    for i, run in enumerate(runs):
        train = runs[:i] + runs[i + 1:]
        T = choose(train, vcfg, tol)
        s = score([run], vcfg, T, tol)["summary"]
        s0 = score([run], vcfg, None, tol)["summary"]
        folds.append({"held_out": run["match_id"], "seed": run["seed"], "T": T,
                      "alerted_hits": s["alerted_hits"], "false_alerts": s["false_alerts"],
                      "lost_hits": s["lost_hits"],
                      "removed_false_alerts": s["removed_false_alerts"],
                      "off_alerted_hits": s0["alerted_hits"],
                      "off_false_alerts": s0["false_alerts"]})
        for k in ("alerted_hits", "false_alerts", "lost_hits", "removed_false_alerts",
                  "uncertain", "candidates", "true_changes"):
            cv[k] += s[k]
    cvs = {k: cv[k] for k in cv}
    cvs["T_chosen"] = dict(Counter(str(f["T"]) for f in folds))
    print(f"\nleave-one-seed-out CV (21 folds): alerted {cvs['alerted_hits']}/"
          f"{cvs['true_changes']} (off: {b['alerted_hits']}), false alerts "
          f"{cvs['false_alerts']} (off: {b['false_alerts']}), lost real changes "
          f"{cvs['lost_hits']}, removed false alerts {cvs['removed_false_alerts']}; T chosen "
          f"per fold {cvs['T_chosen']}")
    for part, ids in (("dev 42-52", lambda s: s < 100), ("seeds 100-109", lambda s: s >= 100)):
        fs = [f for f in folds if ids(f["seed"])]
        print(f"  {part}: alerted {sum(f['alerted_hits'] for f in fs)} (off "
              f"{sum(f['off_alerted_hits'] for f in fs)}), false alerts "
              f"{sum(f['false_alerts'] for f in fs)} "
              f"(off {sum(f['off_false_alerts'] for f in fs)})")
    fa_drop = b["false_alerts"] - cvs["false_alerts"]
    helps = fa_drop >= 5 and cvs["lost_hits"] <= 2
    print(f"\nclearly helps (CV false alerts -{fa_drop} >= 5 AND lost real changes "
          f"{cvs['lost_hits']} <= 2): {'YES' if helps else 'NO'}")
    T_all = choose(runs, vcfg, tol)
    print(f"threshold chosen on all 21 matches (what would be frozen): T = {T_all}")
    repo_path(OUT).write_text(json.dumps({
        "rule": "confirmed AND {from,to} = {4-3-3, 4-2-3-1} AND D <= T -> uncertain; D = max "
                "|d line|, |d width|, |d compactness| (m), re-analysed pass",
        "grid": GRID, "baseline_off": b, "in_sample_curve": curve, "cv": cvs, "folds": folds,
        "clearly_helps": helps, "T_all": T_all,
        "pair_rows": pair_rows}, indent=2, default=_jsonable), encoding="utf-8")
    print(f"-> {repo_path(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
