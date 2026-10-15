"""Real-footage evaluation: the OpenCV pipeline's MatchState vs the oracle's (TeamTrack GT boxes).

Both files go through the **same, unchanged** tactics engine. Per view, the dev clip
(`detector.eval.dev_clips`) and the eval clips are scored separately: each MatchState is cut
to the window first, so no 30 s formation window mixes dev and eval frames. Per team:

- **formation agreement** per 30 s window (the engine's rolling windows): exact label and
  family, on windows where both are confident; how often each side says "uncertain"; and
  against every window the oracle reads confidently (pipeline same / different / uncertain);
- **metric error** per engine frame (1 fps; both sides with >= `tactics.min_players` outfield
  players) and per 30 s window (mean of those frames): defensive line, width, compactness
  (attacking-direction normalised, back line = `tactics.metrics.back_line_default`, so the
  formation label does not leak into the metric) and centroid distance. Mean, p90 (absolute)
  and bias (pipeline - oracle), metres;
- **candidate events** from both timelines, matched per team and type within
  `eval.synthetic.tolerance_s`;
- **coverage**: share of engine frames with >= `tactics.min_players` outfield players.

Formation "truth" for a real clip is the engine's output on the oracle (DATA_CONTRACT), so this
measures what perception loses, not whether the engine's labels are right.

Side view: the official oracle uses the raw GT box bottom (`outputs/oracle_side.json`); the
same comparison is also reported against `oracle_side_inset.json` (GT foot point moved up by
the 2.5 px annotation margin), clearly labelled.

Inputs (produce them first):
    py scripts\\teamtrack_to_matchstate.py --view top        # outputs/oracle_top.json
    py scripts\\teamtrack_to_matchstate.py --view side [--gt-inset]
    py scripts\\eval_tracking.py --view top --track-fps 4 --whole-source --save
    py scripts\\eval_tracking.py --view side --track-fps 2 --whole-source --save

`--set eval2` compares the second eval set (`teamtrack.clip_sets`: never tuned on, but the
same match and cameras as eval, so NOT independent of it) -> outputs/eval_second_set_real.json;
inputs `match_state_<view>_eval2_<fps>fps.json`, `oracle_<view>_eval2.json` (+ side inset).

Usage:
    py scripts\\eval_real.py --tag before       # both views -> outputs/eval_real_<tag>.json
    py scripts\\eval_real.py --set eval2        # second eval set
    py scripts\\eval_real.py --view top --tag after
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.schema import ContractError, MatchState, load_match_state
from gaffer.tactics.common import SIDES, TacticsConfig, extract_team_frames
from gaffer.tactics.formation import UNCERTAIN
from gaffer.tactics.metrics import frame_metrics
from gaffer.tactics.timeline import TacticsResult, build_timeline
from gaffer.teamtrack import DatasetError, find_clips

METRICS = ("defensive_line_m", "width_m", "compactness_m")


def cut(match: MatchState, a: float, b: float) -> MatchState:
    """The match restricted to frames with a <= t < b."""
    frames = [f for f in match.frames if a - 1e-6 <= f.t < b - 1e-6]
    return match.model_copy(update={"frames": frames, "duration_s": b})


def _err(d: list[float]) -> dict[str, float | int | None]:
    if not d:
        return {"n": 0, "mean_abs": None, "p90_abs": None, "bias": None}
    x = np.asarray(d, float)
    return {"n": int(len(x)), "mean_abs": round(float(np.abs(x).mean()), 2),
            "p90_abs": round(float(np.percentile(np.abs(x), 90)), 2),
            "bias": round(float(x.mean()), 2)}


def per_frame_metrics(match: MatchState, tcfg: TacticsConfig
                      ) -> tuple[dict[str, dict[float, Any]], dict[str, dict[float, int]]]:
    """Per team: engine-frame time -> FrameMetrics (fields None with too few players), and
    engine-frame time -> outfield players seen."""
    tf = extract_team_frames(match, tcfg)
    return {s: {round(f.t, 2): frame_metrics(f, tcfg) for f in tf[s]} for s in SIDES}, \
        {s: {round(f.t, 2): len(f.outfield) for f in tf[s]} for s in SIDES}


def compare(pipe: MatchState, orac: MatchState, tcfg: TacticsConfig, tol_s: float,
            change_family: dict[str, str]) -> dict[str, Any]:
    """All comparisons for one window (see module docstring)."""
    rp, ro = build_timeline(pipe, tcfg), build_timeline(orac, tcfg)
    mp, np_ = per_frame_metrics(pipe, tcfg)
    mo, no = per_frame_metrics(orac, tcfg)
    out: dict[str, Any] = {"directions": {
        "pipeline": pipe.teams.home.attacking_direction_first_half,
        "oracle": orac.teams.home.attacking_direction_first_half}}

    def cfam(label: str) -> str:
        f = tcfg.family(label) or label
        return change_family.get(f, change_family.get(label, f))

    for s in SIDES:
        wp = {round(w.t, 1): w for w in rp.windows[s]}
        wo = {round(w.t, 1): w for w in ro.windows[s]}
        common = sorted(set(wp) & set(wo))
        both = [t for t in common if wp[t].label != UNCERTAIN and wo[t].label != UNCERTAIN]
        oconf = [t for t in common if wo[t].label != UNCERTAIN]
        vs_oracle = Counter("uncertain" if wp[t].label == UNCERTAIN else
                            "same" if wp[t].label == wo[t].label else "different"
                            for t in oconf)
        pairs = Counter(f"{wo[t].label} -> {wp[t].label}" for t in common
                        if wo[t].label != wp[t].label)
        form = {
            "windows": len(common),
            "both_confident": len(both),
            "exact_agreement": round(sum(wp[t].label == wo[t].label for t in both)
                                     / len(both), 4) if both else None,
            "family_agreement": round(sum(tcfg.family(wp[t].label) == tcfg.family(wo[t].label)
                                          for t in both) / len(both), 4) if both else None,
            "change_family_agreement": round(sum(cfam(wp[t].label) == cfam(wo[t].label)
                                                 for t in both) / len(both), 4)
            if both else None,
            "uncertain_pipeline": round(sum(wp[t].label == UNCERTAIN for t in common)
                                        / len(common), 4) if common else None,
            "uncertain_oracle": round(sum(wo[t].label == UNCERTAIN for t in common)
                                      / len(common), 4) if common else None,
            "oracle_confident_windows": len(oconf),
            "pipeline_vs_confident_oracle": {k: round(v / len(oconf), 4)
                                             for k, v in vs_oracle.items()} if oconf else {},
            "label_counts": {"pipeline": dict(Counter(wp[t].label for t in common)),
                             "oracle": dict(Counter(wo[t].label for t in common))},
            "disagreements": dict(pairs.most_common(6)),
        }
        # metrics per frame and per 30 s window (trailing, same ends as the formation windows)
        ts = sorted(set(mp[s]) & set(mo[s]))
        ok = [t for t in ts if mp[s][t].defensive_line_m is not None
              and mo[s][t].defensive_line_m is not None]
        frame_err = {k: _err([getattr(mp[s][t], k) - getattr(mo[s][t], k) for t in ok])
                     for k in METRICS}
        frame_err["centroid_m"] = _err([float(np.hypot(*(np.subtract(mp[s][t].centroid,
                                                                    mo[s][t].centroid))))
                                        for t in ok])
        win_err: dict[str, list[float]] = {k: [] for k in (*METRICS, "centroid_m")}
        for t_end in common:
            sel = [t for t in ok if t_end - tcfg.window_s < t <= t_end]
            if not sel:
                continue
            for k in METRICS:
                win_err[k].append(float(np.mean([getattr(mp[s][t], k) for t in sel])
                                        - np.mean([getattr(mo[s][t], k) for t in sel])))
            cp = np.mean([mp[s][t].centroid for t in sel], axis=0)
            co = np.mean([mo[s][t].centroid for t in sel], axis=0)
            win_err["centroid_m"].append(float(np.hypot(*(cp - co))))
        cov = {"pipeline": round(float(np.mean([n >= tcfg.min_players for n in np_[s].values()])),
                                 4) if np_[s] else None,
               "oracle": round(float(np.mean([n >= tcfg.min_players for n in no[s].values()])),
                               4) if no[s] else None,
               "frames": len(np_[s])}
        out[s] = {"formation": form, "metric_error_per_frame": frame_err,
                  "metric_error_per_window": {k: _err(v) for k, v in win_err.items()},
                  "coverage": cov}
    out["events"] = match_events(rp, ro, tol_s)
    return out


def match_events(rp: TacticsResult, ro: TacticsResult, tol_s: float) -> dict[str, Any]:
    """Pipeline vs oracle candidate events, matched per team + type within tol_s."""
    ep = [e for e in rp.timeline.events]
    eo = [e for e in ro.timeline.events]
    used: set[int] = set()
    pairs = []
    for o in eo:
        best = min((i for i, p in enumerate(ep) if i not in used and p.team == o.team
                    and p.type == o.type and abs(p.t - o.t) <= tol_s),
                   key=lambda i: abs(ep[i].t - o.t), default=None)
        if best is not None:
            used.add(best)
            pairs.append((o, ep[best]))

    def brief(e: Any) -> str:
        what = f"{e.from_} -> {e.to}" if e.type == "shape_change" else e.type
        return f"{e.team} t={e.t:.0f}s {what} (conf {e.confidence:.2f})"
    matched_o = {id(o) for o, _ in pairs}
    return {"oracle": [brief(e) for e in eo], "pipeline": [brief(e) for e in ep],
            "matched": len(pairs),
            "matched_same_to": sum(o.to == p.to for o, p in pairs),
            "oracle_only": [brief(o) for o in eo if id(o) not in matched_o],
            "pipeline_only": [brief(p) for i, p in enumerate(ep) if i not in used]}


def windows_for(view: str, cfg: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """dev = the view's dev clip; eval = the (consecutive) other clips."""
    clips = find_clips(view, cfg)
    dev = set(cfg["detector"]["eval"]["dev_clips"])
    d = [c for c in clips if c.stem in dev]
    e = [c for c in clips if c.stem not in dev]
    return {"dev": (d[0].start_s, d[-1].end_s), "eval": (e[0].start_s, e[-1].end_s)}


def pipeline_file(view: str, cfg: dict[str, Any], set_name: str | None = None) -> str:
    tf = cfg["perception"]["track_fps"]
    tf = tf[view] if isinstance(tf, dict) else tf
    mid = f"_{set_name}" if set_name else ""
    return f"outputs/match_state_{view}{mid}_{float(tf):g}fps.json"


def _row(name: str, r: dict[str, Any]) -> list[str]:
    lines = []
    for s in SIDES:
        f, m, w, c = (r[s]["formation"], r[s]["metric_error_per_frame"],
                      r[s]["metric_error_per_window"], r[s]["coverage"])

        def pct(v: float | None) -> str:
            return "  n/a" if v is None else f"{100 * v:5.1f}"

        def e(d: dict[str, Any]) -> str:
            return "n/a" if d["mean_abs"] is None else f"{d['mean_abs']:.2f}/{d['p90_abs']:.2f}"
        lines.append(
            f"  {name:6s} {s:4s} win {f['windows']:3d} both-conf {f['both_confident']:3d} | "
            f"exact {pct(f['exact_agreement'])} fam {pct(f['family_agreement'])} chfam "
            f"{pct(f['change_family_agreement'])} | unc pipe {pct(f['uncertain_pipeline'])} "
            f"orac {pct(f['uncertain_oracle'])} | cov pipe {pct(c['pipeline'])} orac "
            f"{pct(c['oracle'])}")
        lines.append(
            f"  {'':6s} {'':4s} frame err mean/p90 m: line {e(m['defensive_line_m'])} width "
            f"{e(m['width_m'])} compact {e(m['compactness_m'])} centroid {e(m['centroid_m'])}"
            f" | 30 s window: line {e(w['defensive_line_m'])} width {e(w['width_m'])} "
            f"compact {e(w['compactness_m'])} centroid {e(w['centroid_m'])}")
    ev = r["events"]
    lines.append(f"  {name:6s} events: oracle {len(ev['oracle'])}, pipeline {len(ev['pipeline'])},"
                 f" matched {ev['matched']} (same new formation {ev['matched_same_to']}); "
                 f"oracle only {ev['oracle_only']}; pipeline only {ev['pipeline_only']}")
    return lines


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Pipeline vs oracle on TeamTrack")
    ap.add_argument("--view", choices=["top", "side", "both"], default="both")
    ap.add_argument("--tag", default="", help="suffix of the output file (e.g. before, after)")
    ap.add_argument("--pipeline", default=None, help="pipeline MatchState (one view only)")
    ap.add_argument("--set", default=None, choices=["eval2"], help="second eval set")
    args = ap.parse_args(argv)
    tcfg = TacticsConfig.from_config(cfg)
    tol = float(cfg["eval"]["synthetic"]["tolerance_s"])
    change_family = {n: g[0] for g in (cfg["formations"].get("change_equivalent") or [])
                     for n in g}
    views = ["top", "side"] if args.view == "both" else [args.view]
    report: dict[str, Any] = {"tag": args.tag, "set": args.set or "dev+eval",
                              "note": ("second eval set: never used for tuning, but NOT "
                                       "independent of the first eval set (same match, same "
                                       "cameras, neighbouring minutes)") if args.set else None,
                              "tolerance_s": tol,
                              "families": cfg["formations"].get("equivalent"),
                              "change_families": cfg["formations"].get("change_equivalent")}
    for view in views:
        mid = f"_{args.set}" if args.set else ""
        refs = {"oracle": f"outputs/oracle_{view}{mid}.json"}
        if view == "side":
            refs["oracle_inset"] = f"outputs/oracle_side{mid}_inset.json"
        pf = args.pipeline or pipeline_file(view, cfg, args.set)
        try:
            pipe = load_match_state(repo_path(pf))
            oracles = {k: load_match_state(repo_path(v)) for k, v in refs.items()}
            if args.set:
                cs = cfg["teamtrack"]["clip_sets"][view][args.set]
                wins = {args.set: (float(cs[0]), float(cs[1]))}
            else:
                wins = windows_for(view, cfg)
        except (ContractError, DatasetError, FileNotFoundError, OSError) as exc:
            print(f"ERROR ({view}): {exc}\nProduce the inputs first (see the module docstring).",
                  file=sys.stderr)
            return 2
        report[view] = {"pipeline_file": pf, "oracles": refs, "windows": wins}
        print(f"\n=== {view}: {pf} vs {', '.join(refs.values())} ===")
        for split, (a, b) in wins.items():
            for ref, orac in oracles.items():
                r = compare(cut(pipe, a, b), cut(orac, a, b), tcfg, tol, change_family)
                report[view].setdefault(split, {})[ref] = r
                label = split if ref == "oracle" else f"{split}*"
                note = " (GT margin removed)" if ref != "oracle" else ""
                print(f" [{split} {a:.0f}-{b:.0f} s vs {ref}{note}]")
                print("\n".join(_row(label, r)))
                if r["directions"]["pipeline"] != r["directions"]["oracle"]:
                    print(f"  WARNING: attacking direction differs {r['directions']}")
    out = repo_path(f"outputs/eval_second_set_real{'_' + args.tag if args.tag else ''}.json"
                    if args.set else f"outputs/eval_real{'_' + args.tag if args.tag else ''}.json")
    if args.view != "both" and out.exists():
        old = json.loads(out.read_text(encoding="utf-8"))
        report = {**old, **report}
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
