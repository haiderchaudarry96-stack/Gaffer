"""Build step 4: Bedrock spike on dev candidates (docs/AGENT_DESIGN.md §11).

Runs the LLM arm (Nova 2 Lite) on the candidates of dev synthetic matches with **hard caps of
100 LLM calls and 1 USD** for the whole run (checked before every call), then the rules arm on
the same candidates, and reports: share finished with a valid decision without a fallback,
LLM calls per candidate, whether `tool_choice=any` works, guard blocks, tokens, cost,
throttling, and agreement with the rules arm. Dev seeds only (42-52); never 100-119.

    py scripts\\spike_agent.py --seeds 45 --max-candidates 10
    py scripts\\spike_agent.py --seeds 45 --resume 20261016T090000   # continue a cut-off run
    py scripts\\spike_agent.py --seeds 45 --baseline outputs\\spike\\spike_20261015T120444.json

Rows are appended to `outputs/spike/rows_<stamp>.jsonl` as each candidate finishes, so a run
cut off midway resumes with `--resume <stamp>` (finished candidates are skipped; their calls
and cost count towards the hard caps). `--baseline` prints guard blocks / invalid calls / calls
per candidate of an earlier spike next to this one.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict

from gaffer.agent.alerts import AlertStore
from gaffer.agent.loop import AgentRunner, TraceWriter, _synthetic_context, make_budget
from gaffer.agent.tools import Toolbox
from gaffer.config import load_config, repo_path
from gaffer.llm.bedrock_client import BedrockClient, BedrockError

HARD_MAX_CALLS = 100
HARD_MAX_COST = 1.0
DEV_SEEDS = set(range(42, 53))
COMPARE = ("candidates", "guard_blocks", "invalid_calls", "llm_calls_per_candidate",
           "agreement_with_rules", "cost_usd")


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="45")
    ap.add_argument("--max-candidates", type=int, default=10)
    ap.add_argument("--max-calls", type=int, default=HARD_MAX_CALLS)
    ap.add_argument("--max-cost-usd", type=float, default=HARD_MAX_COST)
    ap.add_argument("--resume", default=None, metavar="STAMP", help="continue this run")
    ap.add_argument("--baseline", default=None, help="earlier spike_<stamp>.json to compare")
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",")]
    if not set(seeds) <= DEV_SEEDS:
        print("ERROR: the spike runs on dev seeds 42-52 only", file=sys.stderr)
        return 2
    max_calls = min(args.max_calls, HARD_MAX_CALLS)
    max_cost = min(args.max_cost_usd, HARD_MAX_COST)
    labels = {}
    dev = repo_path("outputs/eval_agent_dev.json")
    if dev.exists():
        for c in json.loads(dev.read_text())["arms"]["rules"]["candidates"]:
            labels[(c["match"], c["id"])] = "hit" if c["hit"] else "FP"

    out_dir = repo_path("outputs/spike")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = args.resume or time.strftime("%Y%m%dT%H%M%S")
    rows_path = out_dir / f"rows_{stamp}.jsonl"
    rows = ([json.loads(x) for x in rows_path.read_text(encoding="utf-8").splitlines()
             if x.strip()] if rows_path.exists() else [])
    done = {(x["match"], x["event_id"]) for x in rows}
    if rows:
        print(f"resuming {stamp}: {len(rows)} candidates already done")
    try:
        llm = BedrockClient(cfg)
    except BedrockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    budget = make_budget(cfg, max_calls, max_cost)
    budget.run_calls = sum(x["llm_calls"] for x in rows)  # the hard caps cover resumed parts
    budget.run_cost = sum(x["cost_usd"] for x in rows)
    for x in rows:
        budget.run_tokens["in"] += x["tokens_in"]
        budget.run_tokens["out"] += x["tokens_out"]
        budget.run_tokens["total"] += x["tokens_in"] + x["tokens_out"]
    trace = TraceWriter(out_dir / f"trace_{stamp}.jsonl")
    t0 = time.perf_counter()
    runners = []
    left = args.max_candidates
    for seed in seeds:
        if left <= 0:
            break
        ctx = _synthetic_context(seed, cfg)
        cands = ctx.candidates[:left]
        left -= len(cands)
        cands = [c for c in cands if (ctx.match.match_id, c.id) not in done]
        if not cands:
            continue
        tb = Toolbox(ctx, AlertStore(out_dir / f"alerts_llm_{stamp}.jsonl"),
                     out_dir / "evidence")
        r = AgentRunner(ctx, tb, arm="llm", llm=llm, budget=budget, trace=trace,
                        run_id=f"spike{stamp}")
        runners.append(r)
        tb_rules = Toolbox(ctx, AlertStore(out_dir / f"alerts_rules_{stamp}.jsonl"),
                           out_dir / "evidence_rules")
        rr = AgentRunner(ctx, tb_rules, arm="rules",
                         trace=TraceWriter(out_dir / f"trace_rules_{stamp}.jsonl"),
                         run_id=f"spike{stamp}")
        for c in cands:  # one candidate at a time, appended at once (resume support)
            o = r.run([c])[0]
            ro = rr.run([c])[0]
            row = {"match": ctx.match.match_id, **asdict(o),
                   "label": labels.get((ctx.match.match_id, o.event_id), "?"),
                   "rules_decision": ro.decision}
            rows.append(row)
            with rows_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            print(f"  {o.event_id}: {o.decision} by {o.decided_by}, llm {o.llm_calls}, "
                  f"blocks {o.guard_blocks}", flush=True)
    wall = time.perf_counter() - t0

    n = len(rows)
    agent_done = [x for x in rows if x["decided_by"] == "agent"]
    summary = {
        "candidates": n,
        "finished_by_agent_valid_decision": len(agent_done),
        "share_finished_by_agent": round(len(agent_done) / max(1, n), 3),
        "llm_calls_total": budget.run_calls,
        "llm_calls_per_candidate": round(budget.run_calls / max(1, n), 2),
        "tool_choice_any_ok": [r.tool_choice_any_ok for r in runners],
        "guard_blocks": sum(x["guard_blocks"] for x in rows),
        "invalid_calls": sum(x["invalid_calls"] for x in rows),
        "fallbacks": dict(Counter(x["fallback"] for x in rows if x["fallback"])),
        "tokens": dict(budget.run_tokens),
        "cost_usd": round(budget.run_cost, 4),
        "throttled": sum(r.throttled for r in runners),
        "llm_down": [r.llm_down for r in runners if r.llm_down],
        "agreement_with_rules": sum(x["decision"] == x["rules_decision"] for x in rows),
        "decisions": dict(Counter(f"{x['label']}:{x['decision']}" for x in rows)),
        "mean_llm_s_per_candidate": round(sum(x["llm_s"] for x in rows) / max(1, n), 1),
        "wall_s_this_invocation": round(wall, 1),
        "caps": {"max_calls": max_calls, "max_cost_usd": max_cost},
    }
    for x in rows:
        print(f"{x['match']} {x['event_id']} [{x['label']:3s}] {x['decision']:9s} "
              f"(rules {x['rules_decision']:9s}) by {x['decided_by']:28s} llm {x['llm_calls']} "
              f"blocks {x['guard_blocks']} tools {','.join(x['tool_calls'])}")
        if x.get("explanation"):
            print(f"      reason (code): {x['reason'][:110]}\n"
                  f"      explanation (agent): {x['explanation'][:110]}")
    if args.baseline:
        b = json.loads(repo_path(args.baseline).read_text(encoding="utf-8"))["summary"]
        summary["baseline"] = {k: b.get(k) for k in COMPARE}
    print(json.dumps(summary, indent=2))
    if args.baseline:
        print("before -> after: " + ", ".join(f"{k} {summary['baseline'][k]} -> {summary[k]}"
                                              for k in COMPARE))
    out = out_dir / f"spike_{stamp}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str),
                   encoding="utf-8")
    print(f"-> {out}\n-> {trace.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
