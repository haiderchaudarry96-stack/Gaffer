"""Step 3 addition (17 Oct): should strong persistence beat the return-leg rule?

Rule R rejects a candidate that returns to the shape held before an earlier candidate of the
same team ("return leg"). On the full real first half (oracle) it rejected away evt_033
(4-4-2 -> 4-2-3-1 at 18:50), which then held 220 s. Proposed principled change (user, 17 Oct):
a return leg is auto-rejected only when the new shape does NOT pass persistence over the
look-ahead (P >= persist_pass on >= min_confident_windows windows, no reverse change); a return
leg that persists is judged like any other candidate. Config switch:
`agent.verify.return_leg_needs_failed_persistence` (no threshold).

Evaluated on synthetic data only: dev seeds 42-52 + seeds 100-109 (development data since Task
A), the same evidence cache as `flip_experiment.py`; seeds 110-119 are never loaded. Leave-one-
seed-out cross-validation as in Task A: per fold, on / off chosen on the other 20 matches by
alerted hits - false alerts (ties -> off = unchanged), applied to the held-out match.
**Kept only if** (fixed in advance by the user) it adds at most +1 false alert per 10 matches
(<= +2 on 21) and loses no alerted real change; otherwise the rule stays as it is.
The effect on the real oracle candidates (0-1800 s) is printed as information only.

    py scripts\\return_leg_experiment.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from gaffer.agent.context import MatchContext
from gaffer.agent.tools import clock
from gaffer.agent.verify import VerifyConfig, rules_decision
from gaffer.config import load_config, repo_path
from gaffer.schema import load_match_state

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_agent import score  # noqa: E402

CACHE = "outputs/agent_cache/flip_metrics.json"  # 42-52 + 100-109 (flip_experiment.py)
ORACLE = "outputs/oracle_top_full.json"
OUT = "outputs/return_leg_experiment.json"


def summary(runs: list[dict[str, Any]], v: VerifyConfig, tol: float) -> dict[str, Any]:
    return score(runs, v, "rules", tol)["summary"]


def main() -> int:
    cfg = load_config()
    tol = float(cfg["eval"]["synthetic"]["tolerance_s"])
    off = VerifyConfig.from_config(cfg)
    if off.return_leg_needs_failed_persistence:
        print("ERROR: run with the switch off in config (it is the baseline)", file=sys.stderr)
        return 2
    on = replace(off, return_leg_needs_failed_persistence=True)
    runs = json.loads(repo_path(CACHE).read_text(encoding="utf-8"))
    assert not {r["seed"] for r in runs} & set(cfg["eval"]["synthetic"]["heldout_seeds_2"])
    print(f"{len(runs)} matches, seeds {[r['seed'] for r in runs]}")

    res = {}
    for name, v in (("off", off), ("on", on)):
        s = summary(runs, v, tol)
        res[name] = s
        print(f"in-sample {name:3s}: alerted {s['alerted_hits']}/{s['true_changes']}, false "
              f"alerts {s['false_alerts']}, uncertain {s['uncertain_share']:.1%}, rejected hits "
              f"{s['rejected_hits']}, mean delay {s['mean_alert_delay_s']} s")
    for part, sel in (("dev 42-52", lambda r: r["seed"] < 100),
                      ("seeds 100-109", lambda r: r["seed"] >= 100)):
        sub = [r for r in runs if sel(r)]
        a, b = summary(sub, off, tol), summary(sub, on, tol)
        res[part] = {"off": a, "on": b}
        print(f"  {part}: alerted {a['alerted_hits']} -> {b['alerted_hits']}, false alerts "
              f"{a['false_alerts']} -> {b['false_alerts']}")
    # which candidates change
    c_off = {(c["match"], c["id"]): c for c in score(runs, off, "rules", tol)["candidates"]}
    changed = [{"match": c["match"], "id": c["id"], "team": c["team"], "from": c["from"],
                "to": c["to"], "hit": c["hit"], "off": c_off[(c["match"], c["id"])]["decision"],
                "on": c["decision"], "reason_on": c["reason"]}
               for c in score(runs, on, "rules", tol)["candidates"]
               if c["decision"] != c_off[(c["match"], c["id"])]["decision"]]
    print(f"candidates whose decision changes: {len(changed)}")
    for c in changed:
        print(f"  {c['match']} {c['id']} {c['team']} {c['from']}->{c['to']} "
              f"[{'real' if c['hit'] else 'false'}] {c['off']} -> {c['on']}")

    # leave-one-seed-out CV (on / off chosen on the other 20 matches)
    folds, cv = [], {"alerted_hits": 0, "false_alerts": 0, "true_changes": 0}
    for i, run in enumerate(runs):
        train = runs[:i] + runs[i + 1:]
        so, sn = summary(train, off, tol), summary(train, on, tol)
        pick = "on" if (sn["alerted_hits"] - sn["false_alerts"]
                        > so["alerted_hits"] - so["false_alerts"]) else "off"
        s = summary([run], on if pick == "on" else off, tol)
        folds.append({"seed": run["seed"], "pick": pick, "alerted_hits": s["alerted_hits"],
                      "false_alerts": s["false_alerts"]})
        for k in cv:
            cv[k] += s[k]
    picks = {p: sum(f["pick"] == p for f in folds) for p in ("on", "off")}
    print(f"\nleave-one-seed-out CV: alerted {cv['alerted_hits']}/{cv['true_changes']} (off "
          f"{res['off']['alerted_hits']}), false alerts {cv['false_alerts']} (off "
          f"{res['off']['false_alerts']}); picked {picks}")
    d_fa = cv["false_alerts"] - res["off"]["false_alerts"]
    d_hits = cv["alerted_hits"] - res["off"]["alerted_hits"]
    max_extra = int(len(runs) / 10)  # +1 false alert per 10 matches
    keep = d_fa <= max_extra and d_hits >= 0 and picks["on"] > picks["off"]
    print(f"keep (CV extra false alerts {d_fa:+d} <= +{max_extra} AND hits {d_hits:+d} >= 0 AND "
          f"the change is what CV picks): {'YES' if keep else 'NO'}")

    # real oracle candidates: information only
    oracle = []
    p = repo_path(ORACLE)
    if p.exists():
        ctx = MatchContext(load_match_state(p), cfg, view="top")
        for c in ctx.candidates:
            a, b = ctx.required_span(c)
            first, re_ = ctx.evidence(c), ctx.evidence(c, ctx.reanalyse_tactics(a, b))
            d0, v0, _ = rules_decision(first, re_, off, backend=ctx.backend, view="top")
            d1, v1, _ = rules_decision(first, re_, on, backend=ctx.backend, view="top")
            if d0 != d1:
                oracle.append({"id": c.id, "team": c.team, "clock": clock(c.t),
                               "change": f"{c.from_}->{c.to}", "off": d0, "on": d1,
                               "reason_on": v1.reason})
        print(f"\nreal oracle 0-1800 s (information only): {len(oracle)} of "
              f"{len(ctx.candidates)} decisions change")
        for o in oracle:
            print(f"  {o['id']} {o['team']} {o['change']} @{o['clock']}: {o['off']} -> "
                  f"{o['on']} ({o['reason_on'][:80]})")
    repo_path(OUT).write_text(json.dumps({"in_sample": res, "changed": changed, "cv": cv,
                                          "folds": folds, "picks": picks, "keep": keep,
                                          "oracle_changes": oracle}, indent=2),
                              encoding="utf-8")
    print(f"-> {repo_path(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
