"""Qualitative check of `line_drop` on real footage: pipeline vs oracle defensive-line levels.

Synthetic GT cannot label line drops (contract v1.0), so the real-clip check is qualitative:
does perception preserve the line signal well enough that the rule fires at the same moments
on the pipeline's MatchState as on the oracle's? Plots the 30 s trailing defensive line per
team (both sources) and lists the events at the configured thresholds and at looser ones.

Usage:
    py scripts\\plot_line_levels.py --view top --out outputs\\failures\\<name>.png
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from gaffer.config import load_config, repo_path  # noqa: E402
from gaffer.schema import load_match_state  # noqa: E402
from gaffer.tactics.common import SIDES, TacticsConfig, extract_team_frames  # noqa: E402
from gaffer.tactics.events import detect_line_drops, line_levels  # noqa: E402

LOOSE = ((8.0, 60.0), (6.0, 60.0), (4.0, 30.0))  # qualitative only, never configured


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Defensive-line levels, pipeline vs oracle")
    ap.add_argument("--view", choices=["top", "side"], default="top")
    ap.add_argument("--pipeline", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    tf = cfg["perception"]["track_fps"]
    tf = tf[args.view] if isinstance(tf, dict) else tf
    files = {"pipeline": args.pipeline or f"outputs/match_state_{args.view}_{float(tf):g}fps.json",
             "oracle": f"outputs/oracle_{args.view}.json"}
    tcfg = TacticsConfig.from_config(cfg)
    levels = {k: {s: line_levels(extract_team_frames(load_match_state(repo_path(f)), tcfg)[s],
                                 tcfg) for s in SIDES} for k, f in files.items()}
    settings = [(tcfg.line_drop_m, tcfg.line_drop_hold_s), *LOOSE]
    events: dict[str, Any] = {}
    for x, y in settings:
        key = f"{x:g} m / {y:g} s" + (" (config)" if (x, y) == settings[0] else "")
        events[key] = {k: [f"{s} t={d.t:.0f}s {d.from_formation}->{d.to_formation} m"
                           for s in SIDES for d in detect_line_drops(levels[k][s], s, tcfg, x, y)]
                       for k in files}
        print(f"{key:22s} pipeline {events[key]['pipeline']} | oracle {events[key]['oracle']}")
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for ax, s in zip(axes, SIDES, strict=True):
        for k, style in (("oracle", "-"), ("pipeline", "--")):
            pts = [(t, v) for t, v, _ in levels[k][s] if v is not None]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], style, label=k)
        ax.set_ylabel(f"{s}: line (m from own goal)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right")
    axes[-1].set_xlabel("match time (s)")
    fig.suptitle(f"TeamTrack {args.view}: 30 s defensive-line level, OpenCV pipeline vs GT oracle"
                 f"\nconfigured line_drop: >= {settings[0][0]:g} m deeper for >= "
                 f"{settings[0][1]:g} s")
    fig.tight_layout()
    out = repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    out.with_suffix(".json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
