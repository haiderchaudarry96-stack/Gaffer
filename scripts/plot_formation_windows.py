"""Plot the engine's per-window formation labels against synthetic ground truth.

Used to make the failure-case images in `docs/FAILURE_LOG.md` reproducible.

Usage:
    py scripts\\plot_formation_windows.py --team home --start 1500 --end 1900 \\
        --out outputs\\failures\\partial_view.png
    py scripts\\plot_formation_windows.py --seed 43 --random-schedule --team away ...

Shows, for one team: true formation, window label (dots, coloured by confidence; uncertain in
grey), outfield players visible, broadcast-window stretches (shaded), decoy events and the
candidate changes the detector emitted.
"""

from __future__ import annotations

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gaffer.config import load_config, repo_path  # noqa: E402
from gaffer.schema import GroundTruth, parse_match_state  # noqa: E402
from gaffer.synthetic import generate_match, match_001_schedule, random_schedule  # noqa: E402
from gaffer.tactics.formation import UNCERTAIN  # noqa: E402
from gaffer.tactics.timeline import build_timeline  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Plot window labels vs ground truth")
    ap.add_argument("--seed", type=int, default=int(cfg["seed"]))
    ap.add_argument("--random-schedule", action="store_true")
    ap.add_argument("--team", choices=["home", "away"], required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    schedule = (random_schedule(np.random.default_rng(args.seed + 10_000), cfg)
                if args.random_schedule else match_001_schedule(cfg))
    m, g = generate_match(args.seed, cfg, schedule, f"seed_{args.seed}")
    match, gt = parse_match_state(m), GroundTruth.model_validate(g)
    result = build_timeline(match)
    end = args.end or match.duration_s
    names = list(cfg["formations"]["templates"])
    ylab = names + [UNCERTAIN]

    ws = [w for w in result.windows[args.team] if args.start <= w.t <= end]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    for v in gt.visibility:
        for a in (ax, ax2):
            a.axvspan(v.start_s, v.end_s, color="#f2d7a0", alpha=0.5, lw=0)
    for e in gt.noise_events:
        if e.end_s >= args.start and e.start_s <= end:
            ax.axvspan(e.start_s, e.end_s, color="#c9b3e6", alpha=0.6, lw=0)
            ax.text(e.start_s, len(ylab) - 0.4, e.kind.replace("_", " "), fontsize=7)
    for f in gt.formations:
        if f.team == args.team and f.to_s >= args.start and f.from_s <= end:
            y = ylab.index(f.formation)
            ax.plot([max(f.from_s, args.start), min(f.to_s, end)], [y, y], color="black",
                    lw=6, alpha=0.25, solid_capstyle="butt")
    xs = [w.t for w in ws]
    ys = [ylab.index(w.label) for w in ws]
    cs = [w.confidence for w in ws]
    sc = ax.scatter(xs, ys, c=cs, cmap="viridis", vmin=0, vmax=1, s=14, zorder=3)
    for c in result.changes:
        if c.team == args.team and args.start <= c.detected_at_s <= end:
            ax.axvline(c.detected_at_s, color="red", lw=1.2, ls="--")
            ax.text(c.detected_at_s, -0.8, f"candidate\n{c.from_formation}->{c.to_formation}",
                    color="red", fontsize=7, ha="center", va="top")
    for c in gt.changes:
        if c.team == args.team and args.start <= c.t <= end:
            ax.axvline(c.t, color="black", lw=1.2)
    ax.set_xlim(args.start, end)
    ax.set_yticks(range(len(ylab)), ylab)
    ax.set_ylim(-1.6, len(ylab))
    ax.set_title(args.title or f"{args.team}: window labels vs truth (seed {args.seed})")
    fig.colorbar(sc, ax=[ax, ax2], label="window confidence", pad=0.01)
    ax2.plot(xs, [w.mean_visible for w in ws], color="#1e5fbf")
    ax2.axhline(cfg["tactics"]["min_players"], color="grey", ls=":", lw=1)
    ax2.set_ylabel("outfield visible\n(0 = team off-screen)", fontsize=8)
    ax2.set_xlabel("match time (s) - shaded: broadcast window (tan), decoy (purple); "
                   "black line: true change; red dashed: candidate emitted")
    ax2.set_ylim(0, 10.5)
    out = repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=90)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
