"""Task E: does the real match contain a sustained formation change? (oracle, GT positions)

Runs the tactics engine with unchanged settings on an oracle MatchState (default: the full
0-1800 s drone oracle, `teamtrack_to_matchstate.py --view top --set full`) and lists, per team,
every candidate change with how long the new shape held: until the team's next candidate, or
the end of the footage. A change is **sustained** when the new shape holds >= `--min-hold-s`
(default 120 s) AND the new formation family carries >= `--min-share` of the engine's confident
30 s windows inside that hold (default `agent.verify.persist_pass`, 0.6: the engine's hysteresis
alone can "hold" a shape that the windows show only a third of the time). Also prints the
timeline segments per team.

Optionally (`--rules`) the rules arm (no LLM, annotation backend: re-analysis = tactics engine
on the MatchState slice) decides every oracle candidate, to show which would be alerted.

    py scripts\\oracle_sustained.py                       # -> outputs/oracle_top_full_changes.json
    py scripts\\oracle_sustained.py --rules
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any

from gaffer.agent.context import MatchContext
from gaffer.agent.tools import clock
from gaffer.agent.verify import rules_decision
from gaffer.config import load_config, repo_path
from gaffer.schema import ContractError, load_match_state
from gaffer.tactics.formation import UNCERTAIN


def holds(ctx: MatchContext, min_hold_s: float, min_share: float) -> list[dict[str, Any]]:
    """Every candidate with its hold (same-team next candidate or footage end)."""
    end = ctx.footage[1]
    out = []
    for team in ("home", "away"):
        cands = [c for c in ctx.candidates if c.team == team]
        for i, c in enumerate(cands):
            nxt = cands[i + 1] if i + 1 < len(cands) else None
            stop = nxt.t if nxt else end
            ws = [w for w in ctx.first.windows[team] if c.t <= w.t <= stop
                  and w.label != UNCERTAIN]
            share = (sum(ctx.fam(w.label) == ctx.fam(c.to) for w in ws) / len(ws)) if ws else None
            out.append({"team": team, "event_id": c.id, "t": c.t, "clock": clock(c.t),
                        "detected_at_s": c.detected_at_s, "from": c.from_, "to": c.to,
                        "confidence": round(c.confidence, 2), "held_s": round(stop - c.t, 1),
                        "held_until": "next change" if nxt else "end of footage",
                        "next": f"{nxt.id} {nxt.from_}->{nxt.to} @{clock(nxt.t)}" if nxt else None,
                        "confident_windows": len(ws),
                        "share_new_in_hold": None if share is None else round(share, 2),
                        "sustained": (stop - c.t >= min_hold_s and share is not None
                                      and share >= min_share)})
    return sorted(out, key=lambda x: (x["t"], x["team"]))


def segments(ctx: MatchContext) -> dict[str, list[dict[str, Any]]]:
    """Timeline segments per team, consecutive equal formations merged."""
    out: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for s in ctx.result.timeline.segments:
        for team in ("home", "away"):
            f = getattr(s, team).formation
            seg = out[team]
            if seg and seg[-1]["formation"] == f:
                seg[-1]["end_s"] = s.end_s
            else:
                seg.append({"formation": f, "start_s": s.start_s, "end_s": s.end_s})
    for seg in out.values():
        for x in seg:
            x["dur_s"] = round(x["end_s"] - x["start_s"], 1)
            x["span"] = f"{clock(x['start_s'])}-{clock(x['end_s'])}"
    return out


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--match", default="outputs/oracle_top_full.json")
    ap.add_argument("--min-hold-s", type=float, default=120.0)
    ap.add_argument("--min-share", type=float, default=None,
                    help="default agent.verify.persist_pass")
    ap.add_argument("--rules", action="store_true", help="rules arm decision per candidate")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    try:
        m = load_match_state(repo_path(args.match))
    except (ContractError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    ctx = MatchContext(m, cfg, view="top")
    min_share = (args.min_share if args.min_share is not None
                 else float(cfg["agent"]["verify"]["persist_pass"]))
    rows = holds(ctx, args.min_hold_s, min_share)
    if args.rules:
        for r in rows:
            c = ctx.candidate(r["event_id"])
            a, b = ctx.required_span(c)
            dec, v, used = rules_decision(ctx.evidence(c), ctx.evidence(
                c, ctx.reanalyse_tactics(a, b)), ctx.vcfg, backend=ctx.backend, view="top")
            r["rules"] = {"decision": dec, "verdict": v.verdict, "reason": v.reason,
                          "reanalysed": used}
    segs = segments(ctx)
    lo, hi = ctx.footage
    print(f"{m.match_id}: footage {lo:.0f}-{hi:.0f} s ({clock(lo)}-{clock(hi)}), "
          f"{len(ctx.candidates)} candidates "
          f"({dict(Counter(c.team for c in ctx.candidates))}); sustained = held >= "
          f"{args.min_hold_s:.0f} s with the new shape in >= {min_share:.0%} of confident "
          "windows")
    for team in ("home", "away"):
        print(f"\n{team} ({getattr(m.teams, team).name}) segments: " + " | ".join(
            f"{x['formation']} {x['span']} ({x['dur_s']:.0f} s)" for x in segs[team]))
    print("\n| event | team | onset | change | conf | held | until | conf. windows | share new "
          "| sustained |" + (" rules |" if args.rules else ""))
    for r in rows:
        print(f"| {r['event_id']} | {r['team']} | {r['clock']} | {r['from']}->{r['to']} | "
              f"{r['confidence']} | {r['held_s']:.0f} s | {r['held_until']} | "
              f"{r['confident_windows']} | {r['share_new_in_hold']} | "
              f"{'YES' if r['sustained'] else 'no'} |"
              + (f" {r['rules']['decision']} ({r['rules']['reason'][:60]}) |"
                 if args.rules else ""))
    sus = [r for r in rows if r["sustained"]]
    print(f"\nsustained changes (>= {args.min_hold_s:.0f} s): {len(sus)} of {len(rows)} "
          "candidates")
    for r in sus:
        print(f"  {r['team']} {r['from']} -> {r['to']} at {r['clock']} ({r['t']:.0f} s), held "
              f"{r['held_s']:.0f} s until {r['held_until']}, share new {r['share_new_in_hold']}")
    out = repo_path(args.out or args.match.replace(".json", "_changes.json"))
    out.write_text(json.dumps({"match": m.match_id, "footage_s": [lo, hi],
                               "candidates": len(rows), "min_hold_s": args.min_hold_s,
                               "min_share": min_share,
                               "sustained": len(sus), "rows": rows, "segments": segs},
                              indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
