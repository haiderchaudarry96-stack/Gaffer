"""Team shape metrics per frame and aggregated over a time span.

All depth metrics use attacking-direction-normalised coordinates (0 = own goal line):

- `defensive_line_m`: mean depth of the deepest `back_line` outfield players (line height).
- `compactness_m`: front-to-back depth of the team, robust percentile range.
- `width_m`: side-to-side spread, robust percentile range.
- `centroid`: mean position in **raw pitch metres** (what the UI minimap draws).
- `pressing_index`: 0..1 proxy, only when the opponent has the ball and it is visible: how
  close the `press_players` nearest players are to the ball (near -> 1, far -> 0).

A metric is `None` when too few players are visible to compute it honestly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gaffer.tactics.common import TacticsConfig, TeamFrame


@dataclass
class FrameMetrics:
    """Metrics for one team in one frame; `None` where not computable."""

    defensive_line_m: float | None
    compactness_m: float | None
    width_m: float | None
    centroid: tuple[float, float] | None
    pressing_index: float | None


def frame_metrics(tf: TeamFrame, cfg: TacticsConfig, back_line: int | None = None
                  ) -> FrameMetrics:
    """Compute metrics for one `TeamFrame`."""
    xy = tf.outfield
    if len(xy) < cfg.min_players:
        return FrameMetrics(None, None, None, None, _pressing(tf, cfg))
    n_back = back_line or cfg.back_line_default
    depth = np.sort(xy[:, 0])
    lo, hi = cfg.robust_percentiles
    line = float(depth[: min(n_back, len(depth))].mean())
    compact = float(np.percentile(xy[:, 0], hi) - np.percentile(xy[:, 0], lo))
    width = float(np.percentile(xy[:, 1], hi) - np.percentile(xy[:, 1], lo))
    c = tf.raw_outfield.mean(axis=0) if len(tf.raw_outfield) else xy.mean(axis=0)
    return FrameMetrics(line, compact, width, (float(c[0]), float(c[1])), _pressing(tf, cfg))


def _pressing(tf: TeamFrame, cfg: TacticsConfig) -> float | None:
    """Pressing proxy for one frame, or None if the team has the ball / ball not visible."""
    if tf.ball is None or tf.possession not in ("home", "away") or len(tf.outfield) == 0:
        return None
    # TeamFrame does not know its own side; the caller filters frames where the team defends.
    d = np.sort(np.linalg.norm(tf.outfield - tf.ball, axis=1))[: cfg.press_players]
    mean_d = float(d.mean())
    span = max(cfg.press_far_m - cfg.press_near_m, 1e-6)
    return float(np.clip((cfg.press_far_m - mean_d) / span, 0.0, 1.0))


@dataclass
class SpanMetrics:
    """Metrics aggregated over a time span for one team."""

    defensive_line_m: float | None
    compactness_m: float | None
    width_m: float | None
    centroid: tuple[float, float] | None
    pressing_index: float | None
    players_visible_mean: float
    frames: int


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def span_metrics(frames: list[TeamFrame], side: str, cfg: TacticsConfig,
                 back_line: int | None = None) -> SpanMetrics:
    """Average metrics of one team (`side`) over `frames`. Pressing uses defending frames only."""
    lines, comps, widths, cents, press, vis = [], [], [], [], [], []
    for tf in frames:
        m = frame_metrics(tf, cfg, back_line)
        vis.append(tf.n_visible)
        if m.defensive_line_m is not None:
            lines.append(m.defensive_line_m)
            comps.append(m.compactness_m)
            widths.append(m.width_m)
            cents.append(m.centroid)
        opponent_has_ball = tf.possession in ("home", "away") and tf.possession != side
        if opponent_has_ball and m.pressing_index is not None:
            press.append(m.pressing_index)
    centroid = None
    if cents:
        arr = np.asarray(cents)
        centroid = (float(arr[:, 0].mean()), float(arr[:, 1].mean()))
    return SpanMetrics(
        defensive_line_m=_mean(lines), compactness_m=_mean(comps), width_m=_mean(widths),
        centroid=centroid, pressing_index=_mean(press),
        players_visible_mean=float(np.mean(vis)) if vis else 0.0, frames=len(frames),
    )


def possession_share(frames: list[TeamFrame]) -> dict[str, int] | None:
    """Possession percentages from frames where one team has the ball, or None if unknown."""
    home = sum(1 for f in frames if f.possession == "home")
    away = sum(1 for f in frames if f.possession == "away")
    if home + away == 0:
        return None
    h = round(100 * home / (home + away))
    return {"home": h, "away": 100 - h}
