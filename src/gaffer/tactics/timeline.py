"""Build the compact `tactical_timeline.json` the agent reads.

Segments are split at period boundaries, at every candidate shape change and at least every
`max_segment_s`, so a segment never spans a formation change. `line_drop` events are listed
with the shape changes but do not split segments. Each segment carries, per team,
the majority formation of its windows (or "uncertain"), and averaged shape metrics.

CLI:
    py -m gaffer.tactics.timeline --match data/synthetic/match_001.json \
        --out outputs/tactical_timeline.json
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gaffer.config import load_config
from gaffer.schema import (
    ContractError,
    MatchState,
    Point,
    Segment,
    Side,
    TacticalTimeline,
    TeamSegmentStats,
    TimelineQuality,
    load_match_state,
)
from gaffer.tactics.common import SIDES, TacticsConfig, TeamFrame, extract_team_frames
from gaffer.tactics.events import DetectedChange, detect_changes, detect_line_drops, line_levels
from gaffer.tactics.formation import UNCERTAIN, WindowResult, analyse_formations, parse_formation
from gaffer.tactics.metrics import possession_share, span_metrics

MAX_WARNINGS = 8
MAX_CUTS_LISTED = 5
LOW_VIS_MERGE_GAP_S = 30.0


@dataclass
class TacticsResult:
    """Everything the engine computed; only `timeline` is part of the contract."""

    timeline: TacticalTimeline
    windows: dict[Side, list[WindowResult]]
    changes: list[DetectedChange]  # shape changes only
    timings_s: dict[str, float]
    line_drops: list[DetectedChange] = field(default_factory=list)


def _r(v: float | None, nd: int = 1) -> float | None:
    return None if v is None else round(float(v), nd)


def _segment_bounds(match: MatchState, changes: list[DetectedChange], cfg: TacticsConfig
                    ) -> list[tuple[float, float]]:
    start = match.frames[0].t if match.frames else 0.0
    end = match.duration_s
    cuts = {start, end}
    cuts.update(p.start_s for p in match.periods if start < p.start_s < end)
    cuts.update(round(c.t, 1) for c in changes if start < c.t < end)
    ordered = sorted(cuts)
    bounds: list[tuple[float, float]] = []
    for a, b in zip(ordered[:-1], ordered[1:], strict=True):
        if b - a < 1e-6:
            continue
        pieces = max(1, int(np.ceil((b - a) / cfg.max_segment_s - 1e-9)))
        edges = np.linspace(a, b, pieces + 1)
        bounds.extend((float(x), float(y)) for x, y in zip(edges[:-1], edges[1:], strict=True))
    return bounds


def _segment_formation(windows: list[WindowResult], a: float, b: float, cfg: TacticsConfig
                       ) -> tuple[str, float]:
    """Majority family of the confident windows (reported as its most common member);
    confidence = their mean x agreement.

    The segment is "uncertain" when too few of its windows were confident (low visibility):
    agreement among the windows we *could* read is the confidence, coverage is the gate.
    """
    inside = [w for w in windows if a <= w.centre < b]
    confident = [w for w in inside if w.label != UNCERTAIN]
    if not confident or len(confident) / len(inside) < cfg.min_usable_fraction:
        return UNCERTAIN, 0.0
    family, count = Counter(cfg.family(w.label) for w in confident).most_common(1)[0]
    in_family = [w for w in confident if cfg.family(w.label) == family]
    label = Counter(w.label for w in in_family).most_common(1)[0][0]
    agreement = count / len(confident)
    conf = float(np.mean([w.confidence for w in in_family])) * agreement
    return (label if conf >= cfg.confidence_threshold else UNCERTAIN), conf


def _team_stats(frames: list[TeamFrame], side: Side, label: str, conf: float,
                cfg: TacticsConfig) -> tuple[TeamSegmentStats, float]:
    back = parse_formation(label)[0] if label != UNCERTAIN else None
    m = span_metrics(frames, side, cfg, back_line=back)
    stats = TeamSegmentStats(
        formation=label, confidence=round(conf, 2),
        defensive_line_m=_r(m.defensive_line_m), compactness_m=_r(m.compactness_m),
        width_m=_r(m.width_m),
        centroid=None if m.centroid is None else Point(x=_r(m.centroid[0]), y=_r(m.centroid[1])),
        pressing_index=_r(m.pressing_index, 2),
    )
    return stats, m.players_visible_mean


def _warnings(match: MatchState, team_frames: dict[Side, list[TeamFrame]], cfg: TacticsConfig
              ) -> list[str]:
    warnings: list[str] = []
    cuts = [f.t for f in match.frames if f.quality is not None and f.quality.camera_cut]

    home, away = team_frames["home"], team_frames["away"]
    if home:
        t = np.array([f.t for f in home])
        total = np.array([h.n_visible + a.n_visible for h, a in zip(home, away, strict=True)],
                         dtype=float)
        k = min(len(total), max(1, int(round(30.0 * cfg.sample_fps))))  # 30 s moving average
        smooth = np.convolve(total, np.ones(k) / k, mode="same")
        low = smooth < cfg.low_visibility_players
        runs: list[list[int]] = []  # [first, last] frame index of each low-visibility run
        for i, flag in enumerate(low):
            if not flag:
                continue
            if runs and t[i] - t[runs[-1][1]] <= LOW_VIS_MERGE_GAP_S:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        for i0, i1 in runs:
            if t[i1] - t[i0] >= cfg.low_visibility_min_s:
                mean_vis = total[i0:i1 + 1].mean()
                warnings.append(f"low visibility {t[i0]:.0f}-{t[i1]:.0f}s "
                                f"({mean_vis:.0f} players)")
    if cuts:
        listed = ", ".join(f"{t:.0f}" for t in cuts[:MAX_CUTS_LISTED])
        more = f" (+{len(cuts) - MAX_CUTS_LISTED} more)" if len(cuts) > MAX_CUTS_LISTED else ""
        warnings.append(f"{len(cuts)} camera cuts at {listed}s{more}")
    if len(warnings) > MAX_WARNINGS:
        extra = len(warnings) - (MAX_WARNINGS - 1)
        warnings = warnings[: MAX_WARNINGS - 1] + [f"+{extra} more"]
    return warnings


def build_timeline(match: MatchState, cfg: TacticsConfig | None = None) -> TacticsResult:
    """Run the whole tactics engine on a `MatchState`."""
    cfg = cfg or TacticsConfig.from_config()
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    team_frames = extract_team_frames(match, cfg)
    timings["extract"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    windows = analyse_formations(match, cfg, team_frames)
    timings["formation"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    changes = sorted((c for s in SIDES for c in detect_changes(windows[s], cfg)),
                     key=lambda c: (c.t, c.team))
    for c in changes:  # a change detected just after the break was made at the break
        for period in match.periods[1:]:
            if 0.0 <= c.t - period.start_s <= cfg.snap_to_period_s:
                c.t = period.start_s
    drops = sorted((d for s in SIDES
                    for d in detect_line_drops(line_levels(team_frames[s], cfg), s, cfg)),
                   key=lambda d: (d.t, d.team))
    events = [c.to_event(f"evt_{i + 1:03d}") for i, c in
              enumerate(sorted(changes + drops, key=lambda c: (c.t, c.team)))]
    timings["events"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    segments: list[Segment] = []
    for a, b in _segment_bounds(match, changes, cfg):
        per_team: dict[str, TeamSegmentStats] = {}
        visible: dict[str, float] = {}
        poss = None
        for side in SIDES:
            frames = [f for f in team_frames[side] if a <= f.t < b]
            label, conf = _segment_formation(windows[side], a, b, cfg)
            per_team[side], visible[side] = _team_stats(frames, side, label, conf, cfg)
            if side == "home":
                poss = possession_share(frames)
        segments.append(Segment(
            start_s=round(a, 1), end_s=round(b, 1), home=per_team["home"],
            away=per_team["away"], possession_pct=poss,
            players_visible_mean={s: round(v, 1) for s, v in visible.items()},
        ))
    all_windows = [w for s in SIDES for w in windows[s]]
    uncertain = sum(w.label == UNCERTAIN for w in all_windows) / max(1, len(all_windows))
    vis = [f.n_visible for s in SIDES for f in team_frames[s]]
    quality = TimelineQuality(
        uncertain_fraction=round(uncertain, 2),
        mean_players_visible=round(float(np.mean(vis)) if vis else 0.0, 1),
        warnings=_warnings(match, team_frames, cfg),
    )
    timeline = TacticalTimeline(
        match_id=match.match_id,
        teams={"home": match.teams.home.name, "away": match.teams.away.name},
        segments=segments, events=events, quality=quality,
    )
    timings["timeline"] = time.perf_counter() - t0
    return TacticsResult(timeline=timeline, windows=windows, changes=changes, timings_s=timings,
                         line_drops=drops)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MatchState -> tactical_timeline.json")
    parser.add_argument("--match", required=True, help="path to a match_state JSON file")
    parser.add_argument("--out", default="outputs/tactical_timeline.json")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    try:
        match = load_match_state(args.match)
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    t_load = time.perf_counter() - t0

    result = build_timeline(match, TacticsConfig.from_config(load_config()))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = result.timeline.to_json()
    out.write_text(text, encoding="utf-8")

    tl = result.timeline
    print(f"{match.match_id}: {len(tl.segments)} segments, {len(tl.events)} candidate events, "
          f"{len(text.encode()) / 1024:.1f} KB -> {out}")
    for e in tl.events:
        what = f"{e.from_} -> {e.to}" if e.type == "shape_change" else e.evidence
        print(f"  {e.id} t={e.t:7.1f}s {e.team:4s} {e.type}: {what} (conf {e.confidence:.2f})")
    print("timing: " + ", ".join(f"{k} {v:.2f}s" for k, v in
                                 {"load": t_load, **result.timings_s}.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
