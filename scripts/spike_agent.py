"""Build step 4: Bedrock spike on dev candidates (docs/AGENT_DESIGN.md §11).

Runs the LLM arm (Nova 2 Lite) on the candidates of dev synthetic matches with **hard caps of
100 LLM calls and 1 USD** for the whole run (checked before every call), then the rules arm on
the same candidates, and reports: share finished with a valid decision without a fallback,
LLM calls per candidate, whether `tool_choice=any` works, guard blocks, tokens, cost,
throttling, and agreement with the rules arm. Dev seeds only (42-52); never 100-119.

    py scripts\\spike_agent.py --seeds 45 --max-candidates 10
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


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="45")
    ap.add_argument("--max-candidates", type=int, default=10)
    ap.add_argument("--max-calls", type=int, default=HARD_MAX_CALLS)
    ap.add_argument("--max-cost-usd", type=float, default=HARD_MAX_COST)
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
    stamp = time.strftime("%Y%m%dT%H%M%S")
    try:
        llm = BedrockClient(cfg)
    except BedrockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    budget = make_budget(cfg, max_calls, max_cost)
    trace = TraceWriter(out_dir / f"trace_{stamp}.jsonl")
    rows, t0 = [], time.perf_counter()
    runners = []
    left = args.max_candidates
    for seed in seeds:
        if left <= 0:
            break
        ctx = _synthetic_context(seed, cfg)
        cands = ctx.candidates[:left]
        left -= len(cands)
        tb = Toolbox(ctx, AlertStore(out_dir / f"alerts_llm_{stamp}.jsonl"),
                     out_dir / "evidence")
        r = AgentRunner(ctx, tb, arm="llm", llm=llm, budget=budget, trace=trace,
                        run_id=f"spike{stamp}")
        runners.append(r)
        llm_out = r.run(cands)
        tb_rules = Toolbox(ctx, AlertStore(out_dir / f"alerts_rules_{stamp}.jsonl"),
                           out_dir / "evidence_rules")
        rules_out = AgentRunner(ctx, tb_rules, arm="rules",
                                trace=TraceWriter(out_dir / f"trace_rules_{stamp}.jsonl"),
                                run_id=f"spike{stamp}").run(cands)
        for o, ro in zip(llm_out, rules_out, strict=True):
            rows.append({"match": ctx.match.match_id, **asdict(o),
                         "label": labels.get((ctx.match.match_id, o.event_id), "?"),
                         "rules_decision": ro.decision})
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
        "wall_s": round(wall, 1),
        "caps": {"max_calls": max_calls, "max_cost_usd": max_cost},
    }
    for x in rows:
        print(f"{x['match']} {x['event_id']} [{x['label']:3s}] {x['decision']:9s} "
              f"(rules {x['rules_decision']:9s}) by {x['decided_by']:28s} llm {x['llm_calls']} "
              f"blocks {x['guard_blocks']} tools {','.join(x['tool_calls'])}")
    print(json.dumps(summary, indent=2))
    out = out_dir / f"spike_{stamp}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str),
                   encoding="utf-8")
    print(f"-> {out}\n-> {trace.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
