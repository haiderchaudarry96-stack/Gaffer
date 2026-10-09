"""Formation classification: template fitting over a rolling window.

For every sampled frame and every template, the template is fitted onto the visible outfield
players by alternating (a) an optimal player-to-slot assignment (Hungarian, works with fewer
players than slots) and (b) a least-squares translation + per-axis stretch, clamped to
`scale_range`. The fit cost is the mean squared residual in m^2.

A trailing window (causal, so it also works in "live replay") averages the per-frame costs of
each template over its usable frames. A softmax over the averaged costs gives the best label;
its probability, scaled down when few players were visible, is the confidence. Below
`confidence_threshold` the label is `"uncertain"`.

Templates come from config (`formations`): the name "4-3-3" means lines of 4, 3 and 3 players
from back to front, so futsal ("2-2", "1-2-1", ...) needs only a config change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from gaffer.schema import MatchState, Side
from gaffer.tactics.common import SIDES, TacticsConfig, TeamFrame, extract_team_frames

UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Template:
    """A formation template: slot positions relative to the template centroid."""

    name: str
    lines: tuple[int, ...]  # players per line, back to front
    slots: np.ndarray  # (n, 2) [depth, lateral], centred on the mean
    slot_line: np.ndarray  # (n,) line index of each slot


def parse_formation(name: str) -> tuple[int, ...]:
    """'4-2-3-1' -> (4, 2, 3, 1). Zero-sized lines ('4-0' in futsal) are dropped."""
    try:
        lines = tuple(int(part) for part in name.split("-"))
    except ValueError as exc:
        raise ValueError(f"formation name {name!r} must look like '4-4-2'") from exc
    lines = tuple(n for n in lines if n > 0)
    if not lines:
        raise ValueError(f"formation {name!r} has no players")
    return lines


def build_template(name: str, cfg: TacticsConfig) -> Template:
    """Generate slot positions for `name` from config (or take explicit `slots_m`)."""
    lines = parse_formation(name)
    if sum(lines) != cfg.outfield_players:
        raise ValueError(
            f"formation {name!r} has {sum(lines)} players, config says "
            f"{cfg.outfield_players} outfield players"
        )
    override = cfg.overrides.get(name, {}) or {}
    slot_line = np.repeat(np.arange(len(lines)), lines)
    if "slots_m" in override:
        slots = np.asarray(override["slots_m"], dtype=float).reshape(-1, 2)
        if len(slots) != cfg.outfield_players:
            raise ValueError(f"override slots_m for {name!r} must have {cfg.outfield_players} rows")
    else:
        widths = override.get("line_widths_m") or [cfg.line_width_m.get(n, 0.0) for n in lines]
        if len(widths) != len(lines):
            raise ValueError(f"line_widths_m for {name!r} must have {len(lines)} entries")
        rows = []
        for i, (n, w) in enumerate(zip(lines, widths, strict=True)):
            depth = 0.0 if len(lines) == 1 else cfg.depth_m * i / (len(lines) - 1)
            lateral = np.linspace(-w / 2, w / 2, n) if n > 1 else np.zeros(1)
            rows.extend([depth, lat] for lat in lateral)
        slots = np.asarray(rows, dtype=float)
    slots = slots - slots.mean(axis=0)
    return Template(name=name, lines=lines, slots=slots, slot_line=slot_line)


def build_templates(cfg: TacticsConfig) -> list[Template]:
    """All configured templates."""
    return [build_template(n, cfg) for n in cfg.template_names]


@dataclass
class Fit:
    """Result of fitting one template to one frame."""

    cost: float  # mean squared residual, m^2
    assignment: np.ndarray  # (k,) slot index of each observed player
    scale: np.ndarray  # (2,) depth / width stretch
    offset: np.ndarray  # (2,) template centroid in normalised pitch coordinates


def fit_template(points: np.ndarray, template: Template, cfg: TacticsConfig) -> Fit:
    """Fit `template` to `points` (k <= n observed outfield players, normalised)."""
    slots = template.slots
    lo, hi = cfg.scale_range
    scale = np.ones(2)
    offset = points.mean(axis=0) - slots.mean(axis=0)
    rows = cols = np.arange(0)
    for _ in range(max(1, cfg.fit_iterations)):
        placed = slots * scale + offset
        d2 = ((points[:, None, :] - placed[None, :, :]) ** 2).sum(axis=-1)
        rows, cols = linear_sum_assignment(d2)
        a, b = slots[cols], points[rows]
        for ax in (0, 1):
            va = a[:, ax].var()
            if len(a) >= 3 and va > 1e-6:
                cov = ((a[:, ax] - a[:, ax].mean()) * (b[:, ax] - b[:, ax].mean())).mean()
                scale[ax] = float(np.clip(cov / va, lo, hi))
            offset[ax] = b[:, ax].mean() - scale[ax] * a[:, ax].mean()
    placed = slots * scale + offset
    d2 = ((points[:, None, :] - placed[None, :, :]) ** 2).sum(axis=-1)
    rows, cols = linear_sum_assignment(d2)
    assignment = np.empty(len(points), dtype=int)
    assignment[rows] = cols
    return Fit(cost=float(d2[rows, cols].mean()), assignment=assignment,
               scale=scale.copy(), offset=offset.copy())


def frame_costs(points: np.ndarray, templates: list[Template], cfg: TacticsConfig) -> np.ndarray:
    """Fit cost of every template for one frame, or NaN for all if too few players."""
    if len(points) < cfg.min_players:
        return np.full(len(templates), np.nan)
    pts = points[: cfg.outfield_players] if len(points) > cfg.outfield_players else points
    return np.array([fit_template(pts, t, cfg).cost for t in templates])


@dataclass
class WindowResult:
    """Formation of one team over one trailing window [t - window_s, t]."""

    t: float  # window end
    team: Side
    label: str  # template name or "uncertain"
    best: str | None  # best template even when uncertain (for diagnostics)
    confidence: float
    probs: dict[str, float]
    usable_frames: int
    total_frames: int
    mean_visible: float  # mean outfield players visible in usable frames
    window_s: float = 0.0

    @property
    def centre(self) -> float:
        """Midpoint of the window (used to compare with ground truth)."""
        return self.t - self.window_s / 2


def classify_window(costs: np.ndarray, visible: np.ndarray, templates: list[Template],
                    cfg: TacticsConfig) -> tuple[str, str | None, float, dict[str, float]]:
    """Label for one window from per-frame costs (frames x templates) and visible counts.

    Returns (label, best_template, confidence, probabilities).
    """
    names = [t.name for t in templates]
    usable = ~np.isnan(costs).any(axis=1) if costs.size else np.zeros(0, dtype=bool)
    n_total = len(costs)
    if n_total == 0 or usable.sum() == 0 or usable.mean() < cfg.min_usable_fraction:
        return UNCERTAIN, None, 0.0, {}
    w = visible[usable].astype(float)
    mean_cost = (costs[usable] * w[:, None]).sum(axis=0) / w.sum()
    z = -(mean_cost - mean_cost.min()) / cfg.softmax_temperature_m2
    p = np.exp(z)
    p /= p.sum()
    best = int(np.argmax(p))
    # Coverage = share of outfield players seen x share of frames usable.
    coverage = (visible[usable].mean() / cfg.outfield_players) * usable.mean()
    confidence = float(p[best] * min(1.0, coverage / cfg.coverage_full))
    probs = {n: round(float(v), 3) for n, v in zip(names, p, strict=True)}
    label = names[best] if confidence >= cfg.confidence_threshold else UNCERTAIN
    return label, names[best], confidence, probs


def classify_frames(frames: list[np.ndarray], cfg: TacticsConfig,
                    templates: list[Template] | None = None
                    ) -> tuple[str, str | None, float, dict[str, float]]:
    """Classify a list of normalised outfield point sets as one window (convenience/tests)."""
    templates = templates or build_templates(cfg)
    costs = np.array([frame_costs(p, templates, cfg) for p in frames]).reshape(-1, len(templates))
    visible = np.array([min(len(p), cfg.outfield_players) for p in frames])
    return classify_window(costs, visible, templates, cfg)


def team_cost_matrix(frames: list[TeamFrame], templates: list[Template], cfg: TacticsConfig
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-frame template costs for one team: (times, costs[frames, templates], visible)."""
    times = np.array([f.t for f in frames], dtype=float)
    costs = np.array([frame_costs(f.outfield, templates, cfg) for f in frames]).reshape(
        -1, len(templates))
    visible = np.array([min(len(f.outfield), cfg.outfield_players) for f in frames])
    return times, costs, visible


def window_ends(start: float, end: float, cfg: TacticsConfig) -> np.ndarray:
    """Window end times: one every `step_s`, the first once a full window has elapsed."""
    first = start + min(cfg.window_s, max(end - start, 0.0))
    return np.arange(first, end + 1e-9, cfg.step_s)


def analyse_formations(match: MatchState, cfg: TacticsConfig | None = None,
                       team_frames: dict[Side, list[TeamFrame]] | None = None
                       ) -> dict[Side, list[WindowResult]]:
    """Rolling-window formation labels for both teams over the whole match."""
    cfg = cfg or TacticsConfig.from_config()
    templates = build_templates(cfg)
    team_frames = team_frames or extract_team_frames(match, cfg)
    out: dict[Side, list[WindowResult]] = {}
    for side in SIDES:
        times, costs, visible = team_cost_matrix(team_frames[side], templates, cfg)
        results: list[WindowResult] = []
        if len(times):
            for t_end in window_ends(float(times[0]), float(times[-1]), cfg):
                sel = (times > t_end - cfg.window_s) & (times <= t_end)
                label, best, conf, probs = classify_window(costs[sel], visible[sel],
                                                           templates, cfg)
                usable = ~np.isnan(costs[sel]).any(axis=1)
                results.append(WindowResult(
                    t=float(t_end), team=side, label=label, best=best, confidence=conf,
                    probs=probs, usable_frames=int(usable.sum()), total_frames=int(sel.sum()),
                    mean_visible=float(visible[sel][usable].mean()) if usable.any() else 0.0,
                    window_s=cfg.window_s,
                ))
        out[side] = results
    return out
