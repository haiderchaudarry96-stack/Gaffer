"""One-shot alerting vs the self-verifying agent (docs/AGENT_DESIGN.md §8).

Arms: `oneshot` (alert on every candidate), `rules` (deterministic verifier, no LLM). The LLM
arm is added in build step 6.

Sets (synthetic, same match generation as `eval_synthetic.py`):
    --set dev     match_001 + seeds 43-52 ("seeds 42-52"): thresholds are set here only
    --set val     seeds 100-109: validation, reported, never tuned on
    --set final   seeds 110-119: the final eval, run ONCE (needs --final)

    py scripts\\eval_agent.py --set dev               # rules arm with the config thresholds
    py scripts\\eval_agent.py --set dev --grid        # threshold sweep (dev only)
    py scripts\\eval_agent.py --set val

Scoring: each candidate is labelled hit / false positive once, exactly as `eval_synthetic.py`
does (each true change takes the nearest same-team candidate within +-90 s). An arm's alerts are
its confirmed candidates: alerted hits, false alerts, uncertain, missed true changes (including
the changes the engine never emitted). Alert delay = (detection + look-ahead) - true change time.
Evidence per candidate is cached in `outputs/agent_cache/evidence_<set>.json`.
"""

from __future__ import annotations

import argparse
import itertools
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
from gaffer.agent.verify import PassEvidence, VerifyConfig, rules_decision
from gaffer.config import load_config, repo_path
from gaffer.schema import GroundTruth, load_ground_truth, load_match_state, parse_match_state
from gaffer.synthetic import generate_match, match_001_schedule, random_schedule

SETS = {"dev": None, "val": "heldout_seeds", "final": "heldout_seeds_2"}
GATE = {"max_false_alerts": 13, "min_alerted_hits": 37}  # step 1 go/no-go on dev (15 Oct)


def jobs_for(name: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    ev = cfg["eval"]["synthetic"]
    if name == "dev":
        jobs = [{"match_id": "synthetic_001", "seed": int(cfg["seed"]), "scripted": True,
                 "path": str(repo_path("data/synthetic/match_001.json")),
                 "gt_path": str(repo_path("data/synthetic/ground_truth.json"))}]
        return jobs + [{"match_id": f"synthetic_r{s}", "seed": s, "scripted": False}
                       for s in range(int(ev["first_seed"]),
                                      int(ev["first_seed"]) + int(ev["extra_matches"]))]
    prefix = "heldout2" if name == "final" else "heldout"
    return [{"match_id": f"synthetic_{prefix}_{s}", "seed": s, "scripted": False}
            for s in ev[SETS[name]]]


def collect(job: dict[str, Any]) -> dict[str, Any]:
    """Worker: generate the match, run the engine, compute first-pass and re-analysis
    evidence for every candidate (thresholds are applied later, so sweeps are cheap)."""
    cfg = load_config()
    if job.get("path") and Path(job["path"]).exists():
        match, gt = load_match_state(job["path"]), load_ground_truth(job["gt_path"])
    else:
        sched = (match_001_schedule(cfg) if job["scripted"]
                 else random_schedule(np.random.default_rng(job["seed"] + 10_000), cfg))
        m, g = generate_match(job["seed"], cfg, sched, job["match_id"])
        match, gt = parse_match_state(m, job["match_id"]), GroundTruth.model_validate(g)
    t0 = time.perf_counter()
    ctx = MatchContext(match, cfg)
    t_engine = time.perf_counter() - t0
    cands = []
    for c in ctx.candidates:
        a, b = ctx.required_span(c)
        first = ctx.evidence(c)
        re = ctx.evidence(c, ctx.reanalyse_tactics(a, b))
        cands.append({"id": c.id, "team": c.team, "t": c.t, "detected_at_s": c.detected_at_s,
                      "from": c.from_, "to": c.to, "confidence": c.confidence,
                      "first": asdict(first), "reanalysis": asdict(re)})
    return {"match_id": job["match_id"], "seed": job["seed"],
            "gt": gt.model_dump(by_alias=True), "candidates": cands,
            "timing_s": {"engine": round(t_engine, 1),
                         "evidence": round(time.perf_counter() - t0 - t_engine, 1)}}


def label_candidates(run: dict[str, Any], tol: float) -> dict[str, Any]:
    """Hit / FP per candidate id (same matching as eval_synthetic.score_changes)."""
    gt = GroundTruth.model_validate(run["gt"])
    used: dict[str, dict[str, Any]] = {}
    for change in gt.changes:
        best, best_d = None, None
        for c in run["candidates"]:
            if c["id"] in used or c["team"] != change.team:
                continue
            d = abs(c["t"] - change.t)
            if d <= tol and (best_d is None or d < best_d):
                best, best_d = c, d
        if best is not None:
            used[best["id"]] = {"gt_t": change.t, "gt_to": change.to}
    return {"hits": used, "true_changes": len(gt.changes)}


def decide(run: dict[str, Any], vcfg: VerifyConfig, arm: str) -> list[dict[str, Any]]:
    out = []
    for c in run["candidates"]:
        if arm == "oneshot":
            out.append({"id": c["id"], "decision": "confirmed", "verdict": "oneshot",
                        "failed": [], "reanalysed": False, "reason": "alert on every candidate"})
            continue
        first = PassEvidence(**c["first"])
        re = PassEvidence(**c["reanalysis"])
        dec, v, used = rules_decision(first, re, vcfg, backend="synthetic")
        out.append({"id": c["id"], "decision": dec, "verdict": v.verdict, "failed": v.failed,
                    "reanalysed": used, "reason": v.reason})
    return out


def score(runs: list[dict[str, Any]], vcfg: VerifyConfig, arm: str, tol: float
          ) -> dict[str, Any]:
    tot = Counter()
    delays, per_cand = [], []
    for run in runs:
        lab = label_candidates(run, tol)
        tot["true_changes"] += lab["true_changes"]
        by_id = {c["id"]: c for c in run["candidates"]}
        for d in decide(run, vcfg, arm):
            c = by_id[d["id"]]
            hit = d["id"] in lab["hits"]
            kind = "hit" if hit else "fp"
            tot[f"{kind}_{d['decision']}"] += 1
            tot["candidates"] += 1
            tot[f"reason_{kind}_{d['decision']}_{'+'.join(d['failed']) or 'pass'}"] += 1
            tot["reanalysed"] += d["reanalysed"]
            if hit and d["decision"] == "confirmed":
                delays.append(c["detected_at_s"] + (vcfg.lookahead_s if arm != "oneshot" else 0)
                              - lab["hits"][d["id"]]["gt_t"])
            per_cand.append({"match": run["match_id"], **{k: c[k] for k in
                             ("id", "team", "t", "from", "to")}, "hit": hit, **d})
    hits = tot["hit_confirmed"] + tot["hit_rejected"] + tot["hit_uncertain"]
    summary = {
        "arm": arm, "candidates": tot["candidates"], "true_changes": tot["true_changes"],
        "candidate_hits": hits, "candidate_fps": tot["candidates"] - hits,
        "alerted_hits": tot["hit_confirmed"], "false_alerts": tot["fp_confirmed"],
        "missed_true_changes": tot["true_changes"] - tot["hit_confirmed"],
        "rejected_hits": tot["hit_rejected"], "uncertain_hits": tot["hit_uncertain"],
        "rejected_fps": tot["fp_rejected"], "uncertain_fps": tot["fp_uncertain"],
        "uncertain_share": round((tot["hit_uncertain"] + tot["fp_uncertain"])
                                 / max(1, tot["candidates"]), 3),
        "reanalysed": tot["reanalysed"],
        "mean_alert_delay_s": round(float(np.mean(delays)), 1) if delays else None,
        "reasons": {k[7:]: v for k, v in sorted(tot.items()) if k.startswith("reason_")},
    }
    return {"summary": summary, "candidates": per_cand}


def print_summary(s: dict[str, Any]) -> None:
    print(f"  [{s['arm']}] candidates {s['candidates']} ({s['candidate_hits']} hits / "
          f"{s['candidate_fps']} FP) | alerted hits {s['alerted_hits']}/{s['true_changes']} | "
          f"false alerts {s['false_alerts']} | uncertain {s['uncertain_share']:.0%} "
          f"(hits {s['uncertain_hits']}, FP {s['uncertain_fps']}) | rejected hits "
          f"{s['rejected_hits']} | re-analysed {s['reanalysed']} | mean alert delay "
          f"{s['mean_alert_delay_s']} s")


def grid(runs: list[dict[str, Any]], base: VerifyConfig, tol: float) -> list[dict[str, Any]]:
    """Threshold sweep on the dev set (the look-ahead is fixed at the user's 60 s)."""
    rows = []
    for cov, pp, pf, mc in itertools.product((0.5, 0.6, 0.7), (0.6, 0.7, 0.8),
                                             (0.3, 0.4, 0.5), (3, 4, 6)):
        if pf >= pp:
            continue
        v = VerifyConfig(**{**asdict(base), "min_coverage": cov, "persist_pass": pp,
                            "persist_fail": pf, "min_confident_windows": mc})
        s = score(runs, v, "rules", tol)["summary"]
        rows.append({"min_coverage": cov, "persist_pass": pp, "persist_fail": pf,
                     "min_confident_windows": mc, "alerted_hits": s["alerted_hits"],
                     "false_alerts": s["false_alerts"], "uncertain_share": s["uncertain_share"]})
    return rows


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", choices=list(SETS), default="dev")
    ap.add_argument("--final", action="store_true",
                    help="required for --set final (seeds 110-119 are run once)")
    ap.add_argument("--grid", action="store_true", help="threshold sweep (dev set only)")
    ap.add_argument("--refresh", action="store_true", help="recompute the evidence cache")
    args = ap.parse_args(argv)
    if args.set == "final" and not args.final:
        print("ERROR: seeds 110-119 are the final eval and are run once; pass --final",
              file=sys.stderr)
        return 2
    if args.grid and args.set != "dev":
        print("ERROR: thresholds are tuned on the dev set only", file=sys.stderr)
        return 2

    cache = repo_path(f"outputs/agent_cache/evidence_{args.set}.json")
    t0 = time.perf_counter()
    if cache.exists() and not args.refresh:
        runs = json.loads(cache.read_text(encoding="utf-8"))
        print(f"evidence from cache {cache}")
    else:
        jobs = jobs_for(args.set, cfg)
        with ProcessPoolExecutor(max_workers=int(cfg["eval"]["synthetic"]["workers"])) as pool:
            runs = list(pool.map(collect, jobs))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(runs), encoding="utf-8")
        print(f"evidence for {len(runs)} matches in {time.perf_counter() - t0:.0f} s -> {cache}")

    tol = float(cfg["eval"]["synthetic"]["tolerance_s"])
    vcfg = VerifyConfig.from_config(cfg)
    report: dict[str, Any] = {"set": args.set, "matches": [r["match_id"] for r in runs],
                              "verify": asdict(vcfg), "arms": {}}
    print(f"\n=== {args.set}: {len(runs)} matches ===")
    for arm in ("oneshot", "rules"):
        res = score(runs, vcfg, arm, tol)
        report["arms"][arm] = res
        print_summary(res["summary"])
    s = report["arms"]["rules"]["summary"]
    print("  rules arm reasons:", json.dumps(s["reasons"]))
    if args.set == "dev":
        ok = (s["false_alerts"] <= GATE["max_false_alerts"]
              and s["alerted_hits"] >= GATE["min_alerted_hits"])
        report["gate"] = {**GATE, "passed": ok}
        print(f"  step 1 gate (false alerts <= {GATE['max_false_alerts']}, alerted hits >= "
              f"{GATE['min_alerted_hits']}): {'PASS' if ok else 'FAIL'}")
    if args.grid:
        rows = grid(runs, vcfg, tol)
        report["grid"] = rows
        good = sorted((r for r in rows if r["false_alerts"] <= GATE["max_false_alerts"]
                       and r["alerted_hits"] >= GATE["min_alerted_hits"]),
                      key=lambda r: (r["false_alerts"] - r["alerted_hits"], r["uncertain_share"]))
        print(f"\n  grid: {len(rows)} settings, {len(good)} pass the gate")
        for r in sorted(rows, key=lambda r: (-r["alerted_hits"], r["false_alerts"]))[:12]:
            print("   ", r)
    out = repo_path(f"outputs/eval_agent_{args.set}.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
