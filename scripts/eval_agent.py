"""One-shot alerting vs the self-verifying agent (docs/AGENT_DESIGN.md §8).

Arms: `oneshot` (alert on every candidate), `rules` (deterministic verifier, no LLM) and `llm`
(the agent: Nova 2 Lite on Bedrock, same tools and guard; `--arms oneshot,rules,llm`).

Sets (synthetic, same match generation as `eval_synthetic.py`):
    --set dev     match_001 + seeds 43-52 ("seeds 42-52"): thresholds are set here only
    --set val     seeds 100-109: validation, reported, never tuned on
    --set final   seeds 110-119: the final eval, run ONCE (needs --final)

    py scripts\\eval_agent.py --set dev               # rules arm with the config thresholds
    py scripts\\eval_agent.py --set dev --grid        # threshold sweep (dev only)
    py scripts\\eval_agent.py --set val
    py scripts\\eval_agent.py --set final --final --arms oneshot,rules,llm --max-cost-usd 2

The `llm` arm spends Bedrock credits. It appends one row per candidate to
`outputs/eval_agent_<set>/llm_rows.jsonl` as it goes and **resumes** from there when re-run
(finished candidates are skipped, their calls and cost count towards the run cap). A resume
refuses to continue if the agent / tactics / Bedrock config changed since the run started
(fingerprint in `llm_run.json`): a crashed final run is resumed, never re-run with new rules.

Scoring: each candidate is labelled hit / false positive once, exactly as `eval_synthetic.py`
does (each true change takes the nearest same-team candidate within +-90 s). An arm's alerts are
its confirmed candidates: alerted hits, false alerts, uncertain, missed true changes (including
the changes the engine never emitted). Alert delay = (detection + look-ahead) - true change time.
Evidence per candidate is cached in `outputs/agent_cache/evidence_<set>.json`.
"""

from __future__ import annotations

import argparse
import hashlib
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

from gaffer.agent.alerts import AlertStore
from gaffer.agent.context import MatchContext
from gaffer.agent.loop import AgentRunner, TraceWriter, make_budget
from gaffer.agent.tools import Toolbox
from gaffer.agent.verify import PassEvidence, VerifyConfig, rules_decision
from gaffer.config import load_config, repo_path
from gaffer.schema import GroundTruth, load_ground_truth, load_match_state, parse_match_state
from gaffer.synthetic import generate_match, match_001_schedule, random_schedule

SETS = {"dev": None, "val": "heldout_seeds", "final": "heldout_seeds_2"}
GATE = {"max_false_alerts": 13, "min_alerted_hits": 37}  # step 1 go/no-go on dev (15 Oct)
# AGENT_DESIGN §8, fixed 15 Oct before any run on 110-119 (never moved)
BAR = {"max_false_alerts": 16, "min_alerted_hits": 30, "max_uncertain_share": 0.30,
       "max_mean_delay_s": 120.0, "fail_false_alerts": 25, "config_option": (16, 28),
       "llm_margin": 2, "max_cost_per_match": 0.10, "max_calls_per_match": 60,
       "max_p95_llm_s": 30.0}


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


def load_job(job: dict[str, Any], cfg: dict[str, Any]) -> tuple[Any, GroundTruth]:
    """The synthetic match and its ground truth for one job (generated, or match_001's file)."""
    if job.get("path") and Path(job["path"]).exists():
        return load_match_state(job["path"]), load_ground_truth(job["gt_path"])
    sched = (match_001_schedule(cfg) if job["scripted"]
             else random_schedule(np.random.default_rng(job["seed"] + 10_000), cfg))
    m, g = generate_match(job["seed"], cfg, sched, job["match_id"])
    return parse_match_state(m, job["match_id"]), GroundTruth.model_validate(g)


def collect(job: dict[str, Any]) -> dict[str, Any]:
    """Worker: generate the match, run the engine, compute first-pass and re-analysis
    evidence for every candidate (thresholds are applied later, so sweeps are cheap)."""
    cfg = load_config()
    match, gt = load_job(job, cfg)
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


def decide(run: dict[str, Any], vcfg: VerifyConfig, arm: str,
           llm_rows: dict[tuple[str, str], dict[str, Any]] | None = None
           ) -> list[dict[str, Any]]:
    out = []
    for c in run["candidates"]:
        if arm == "llm":
            r = (llm_rows or {}).get((run["match_id"], c["id"]))
            if r is None:
                raise KeyError(f"no llm row for {run['match_id']} {c['id']}: run not finished")
            out.append({"id": c["id"], "decision": r["decision"], "verdict": r["verdict"],
                        "failed": [], "reanalysed": "reanalyse_window" in r["tool_calls"],
                        "reason": r["reason"], "decided_by": r["decided_by"]})
            continue
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


def score(runs: list[dict[str, Any]], vcfg: VerifyConfig, arm: str, tol: float,
          llm_rows: dict[tuple[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    tot = Counter()
    delays, per_cand = [], []
    for run in runs:
        lab = label_candidates(run, tol)
        tot["true_changes"] += lab["true_changes"]
        by_id = {c["id"]: c for c in run["candidates"]}
        for d in decide(run, vcfg, arm, llm_rows):
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


# --------------------------------------------------------------------------- llm arm


def fingerprint(cfg: dict[str, Any]) -> str:
    """Hash of everything that decides the agent's behaviour (resume guard)."""
    keys = {k: cfg.get(k) for k in ("agent", "tactics", "bedrock", "synthetic", "formations")}
    return hashlib.sha256(json.dumps(keys, sort_keys=True, default=str).encode()).hexdigest()[:16]


def run_llm_arm(set_name: str, runs: list[dict[str, Any]], cfg: dict[str, Any],
                max_cost: float, max_calls: int | None) -> dict[tuple[str, str], dict[str, Any]]:
    """The agent arm (Nova on Bedrock) over every candidate, one row per candidate appended as
    it finishes; resumes from the rows file. Returns rows by (match, event id)."""
    from gaffer.agent.loop import RateLimiter
    from gaffer.llm.bedrock_client import BedrockClient, BedrockError

    out_dir = repo_path(f"outputs/eval_agent_{set_name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path, meta_path = out_dir / "llm_rows.jsonl", out_dir / "llm_run.json"
    fp = fingerprint(cfg)
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["fingerprint"] != fp:
            raise SystemExit(f"ERROR: config changed since this llm run started ({meta_path}: "
                             f"{meta['fingerprint']} != {fp}); a started run is resumed with "
                             "the same config, never re-run with new rules")
        print(f"resuming llm run started {meta['started_utc']}")
    else:
        meta = {"fingerprint": fp, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                time.gmtime()),
                "model_id": cfg["bedrock"]["model_id"], "max_cost_usd": max_cost,
                "max_calls": max_calls, "set": set_name}
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    rows = ([json.loads(x) for x in rows_path.read_text(encoding="utf-8").splitlines()
             if x.strip()] if rows_path.exists() else [])
    done = {(r["match"], r["event_id"]): r for r in rows}
    want = {(run["match_id"], c["id"]) for run in runs for c in run["candidates"]}
    if want <= set(done):
        return done
    try:
        llm = BedrockClient(cfg)
    except BedrockError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    budget = make_budget(cfg, max_calls, max_cost)
    budget.run_calls = sum(r["llm_calls"] for r in rows)
    budget.run_cost = sum(r["cost_usd"] for r in rows)
    limiter = RateLimiter(int(cfg["agent"]["llm"]["max_rpm"]))
    trace = TraceWriter(out_dir / "trace_llm.jsonl")
    store = AlertStore(out_dir / "alerts_llm.jsonl")
    llm_down: str | None = None
    jobs = {j["match_id"]: j for j in jobs_for(set_name, cfg)}
    for run in runs:
        todo = [c["id"] for c in run["candidates"] if (run["match_id"], c["id"]) not in done]
        if not todo:
            continue
        match, _ = load_job(jobs[run["match_id"]], cfg)
        ctx = MatchContext(match, cfg)
        if [c.id for c in ctx.candidates] != [c["id"] for c in run["candidates"]]:
            raise SystemExit(f"ERROR: {run['match_id']}: candidates differ from the evidence "
                             "cache (engine or config changed)")
        tb = Toolbox(ctx, store, out_dir / "evidence")
        r = AgentRunner(ctx, tb, arm="llm", llm=llm, budget=budget, limiter=limiter,
                        trace=trace, run_id=f"{set_name}_{meta['started_utc'][:10]}", cfg=cfg)
        r.llm_down = llm_down
        budget.new_match()
        prev = [x for x in rows if x["match"] == run["match_id"]]
        budget.calls = sum(x["llm_calls"] for x in prev)
        budget.cost = sum(x["cost_usd"] for x in prev)
        budget.tokens["total"] = sum(x["tokens_in"] + x["tokens_out"] for x in prev)
        max_llm = int(cfg["agent"]["limits"]["max_candidates_llm"])
        print(f"  {run['match_id']}: {len(todo)} of {len(run['candidates'])} candidates to do",
              flush=True)
        for i, c in enumerate(ctx.candidates):
            if c.id not in todo:
                continue
            o = r.verify(c, use_llm=r.llm_down is None and i < max_llm)
            row = {"match": run["match_id"], "seed": run["seed"], **asdict(o),
                   "throttled_so_far": r.throttled, "llm_down": r.llm_down}
            rows.append(row)
            done[(run["match_id"], c.id)] = row
            with rows_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            print(f"    {c.id} {c.team} {c.from_}->{c.to}: {o.decision} by {o.decided_by}, "
                  f"llm {o.llm_calls}, blocks {o.guard_blocks}, ${budget.run_cost:.3f} total",
                  flush=True)
        llm_down = r.llm_down
    return done


def llm_stats(rows: dict[tuple[str, str], dict[str, Any]], rules: dict[str, Any]
              ) -> dict[str, Any]:
    """Cost, calls, guard and agreement figures of the llm arm (AGENT_DESIGN §8 metrics)."""
    rs = list(rows.values())
    by_match: dict[str, list[dict[str, Any]]] = {}
    for x in rs:
        by_match.setdefault(x["match"], []).append(x)
    rules_dec = {(c["match"], c["id"]): c["decision"] for c in rules["candidates"]}
    llm_s = [x["llm_s"] for x in rs if x["llm_calls"]]
    agree = sum(x["decision"] == rules_dec.get((x["match"], x["event_id"])) for x in rs)
    return {
        "candidates": len(rs), "llm_calls": sum(x["llm_calls"] for x in rs),
        "tokens_in": sum(x["tokens_in"] for x in rs),
        "tokens_out": sum(x["tokens_out"] for x in rs),
        "cost_usd": round(sum(x["cost_usd"] for x in rs), 4),
        "mean_cost_per_match": round(float(np.mean([sum(x["cost_usd"] for x in v)
                                                    for v in by_match.values()])), 4),
        "max_calls_per_match": max(sum(x["llm_calls"] for x in v) for v in by_match.values()),
        "mean_calls_per_match": round(float(np.mean([sum(x["llm_calls"] for x in v)
                                                     for v in by_match.values()])), 1),
        "llm_calls_per_candidate": round(sum(x["llm_calls"] for x in rs) / max(1, len(rs)), 2),
        "p95_llm_s_per_candidate": round(float(np.percentile(llm_s, 95)), 1) if llm_s else None,
        "mean_llm_s_per_candidate": round(float(np.mean(llm_s)), 1) if llm_s else None,
        "mean_tool_s_per_candidate": round(float(np.mean([x["tool_s"] for x in rs])), 2),
        "guard_blocks": sum(x["guard_blocks"] for x in rs),
        "invalid_calls": sum(x["invalid_calls"] for x in rs),
        "decided_by": dict(Counter(x["decided_by"] for x in rs)),
        "fallbacks": dict(Counter(x["fallback"] for x in rs if x["fallback"])),
        "throttled": max((x.get("throttled_so_far", 0) for x in rs), default=0),
        "agreement_with_rules": agree,
        "disagreements": [{"match": x["match"], "id": x["event_id"], "llm": x["decision"],
                           "rules": rules_dec.get((x["match"], x["event_id"])),
                           "reason": x["reason"][:160], "explanation": x["explanation"][:200]}
                          for x in rs
                          if x["decision"] != rules_dec.get((x["match"], x["event_id"]))],
    }


def judge(s: dict[str, Any], stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """AGENT_DESIGN §8 as written (bar fixed 15 Oct)."""
    fa, hits = s["false_alerts"], s["alerted_hits"]
    bar = fa <= BAR["max_false_alerts"] and hits >= BAR["min_alerted_hits"]
    unc_ok = s["uncertain_share"] <= BAR["max_uncertain_share"]
    delay_ok = (s["mean_alert_delay_s"] is not None
                and s["mean_alert_delay_s"] <= BAR["max_mean_delay_s"])
    cfa, chits = BAR["config_option"]
    if bar and unc_ok and delay_ok:
        verdict = "helped"
    elif fa > BAR["fail_false_alerts"] or (fa > cfa and hits <= chits):
        verdict = "did not help"
    else:
        verdict = "partial"
    out = {"bar_met": bar, "uncertain_ok": unc_ok, "delay_ok": delay_ok, "verdict": verdict}
    if stats is not None:
        out["cost_ok"] = (stats["mean_cost_per_match"] <= BAR["max_cost_per_match"]
                          and stats["max_calls_per_match"] <= BAR["max_calls_per_match"]
                          and (stats["p95_llm_s_per_candidate"] or 0) <= BAR["max_p95_llm_s"])
    return out


def llm_adds(agent: dict[str, Any], rules: dict[str, Any]) -> bool:
    """The LLM adds to decisions: beats rules by >= 2 false alerts or >= 2 hits without losing
    on the other (§8)."""
    dfa = rules["false_alerts"] - agent["false_alerts"]
    dh = agent["alerted_hits"] - rules["alerted_hits"]
    m = BAR["llm_margin"]
    return (dfa >= m and dh >= 0) or (dh >= m and dfa >= 0)


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
    ap.add_argument("--arms", default="oneshot,rules",
                    help="comma-separated: oneshot, rules, llm (llm spends Bedrock credits)")
    ap.add_argument("--max-cost-usd", type=float, default=2.0, help="llm arm: run cost cap")
    ap.add_argument("--max-calls", type=int, default=None, help="llm arm: run call cap")
    args = ap.parse_args(argv)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if set(arms) - {"oneshot", "rules", "llm"}:
        print(f"ERROR: unknown arm in {args.arms}", file=sys.stderr)
        return 2
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
    llm_rows = None
    if "llm" in arms:
        if args.refresh:
            print("ERROR: --refresh with the llm arm would change the candidates under a "
                  "started run", file=sys.stderr)
            return 2
        llm_rows = run_llm_arm(args.set, runs, cfg, args.max_cost_usd, args.max_calls)
    print(f"\n=== {args.set}: {len(runs)} matches ===")
    for arm in [a for a in ("oneshot", "rules", "llm") if a in arms or a == "rules"]:
        res = score(runs, vcfg, arm, tol, llm_rows)
        report["arms"][arm] = res
        print_summary(res["summary"])
    s = report["arms"]["rules"]["summary"]
    print("  rules arm reasons:", json.dumps(s["reasons"]))
    if args.set == "final":
        report["bar"] = {k: list(v) if isinstance(v, tuple) else v for k, v in BAR.items()}
        report["judgement"] = {"rules": judge(s)}
        print(f"  rules arm vs the §8 bar: {report['judgement']['rules']}")
    if llm_rows is not None:
        st = llm_stats(llm_rows, report["arms"]["rules"])
        a = report["arms"]["llm"]["summary"]
        report["llm"] = st
        report["judgement"] = {**report.get("judgement", {}), "agent": judge(a, st),
                               "llm_adds_to_decisions": llm_adds(a, s)}
        print(f"  llm arm: {json.dumps({k: v for k, v in st.items() if k != 'disagreements'})}")
        for d in st["disagreements"]:
            print(f"    disagreement {d}")
        print(f"  agent vs the §8 bar: {report['judgement']['agent']}; LLM adds to decisions: "
              f"{report['judgement']['llm_adds_to_decisions']}")
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
