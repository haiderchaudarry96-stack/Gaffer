"""Shared pieces of the tactics engine: settings and per-team frame extraction.

The engine never assumes a full squad. A `TeamFrame` holds whatever was visible of one team in
one sampled frame, already **normalised to the team's attacking direction**: `x` is the depth
from the team's own goal line (0 = own goal, pitch length = opponent goal), `y` is lateral,
rotated by 180 degrees for a team attacking left so that its left-back stays on the same side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaffer.config import load_config
from gaffer.schema import MatchState, Side

SIDES: tuple[Side, Side] = ("home", "away")


@dataclass(frozen=True)
class TacticsConfig:
    """All tactics thresholds, read from the `formations`, `tactics` and `pitch` config blocks."""

    pitch_length_m: float
    pitch_width_m: float
    outfield_players: int
    template_names: tuple[str, ...]
    depth_m: float
    line_width_m: dict[int, float]
    overrides: dict[str, dict[str, Any]]
    families: dict[str, str]  # formation -> family name (first member of its group)
    change_families: dict[str, str]  # extra groups for change detection only
    sample_fps: float
    window_s: float
    step_s: float
    min_players: int
    min_usable_fraction: float
    coverage_full: float
    fit_iterations: int
    scale_range: tuple[float, float]
    softmax_temperature_m2: float
    confidence_threshold: float
    gk_max_depth_m: float
    gk_min_gap_m: float
    min_persist_s: float
    max_uncertain_gap_s: float
    back_line_default: int
    robust_percentiles: tuple[float, float]
    press_players: int
    press_near_m: float
    press_far_m: float
    max_segment_s: float
    snap_to_period_s: float
    low_visibility_players: float
    low_visibility_min_s: float
    line_drop_m: float | None = None  # None: no line_drop events
    line_drop_hold_s: float | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> TacticsConfig:
        """Build from a parsed config dict (defaults to `config.yaml`)."""
        cfg = cfg if cfg is not None else load_config()
        f, t, p = cfg["formations"], cfg["tactics"], cfg["pitch"]
        m, ch, tl, gk = t["metrics"], t["change"], t["timeline"], t["goalkeeper"]
        ld = t.get("line_drop")
        ld = ld if ld and ld.get("enabled", True) else None
        return cls(
            pitch_length_m=float(p["length_m"]),
            pitch_width_m=float(p["width_m"]),
            outfield_players=int(f["outfield_players"]),
            template_names=tuple(f["templates"]),
            depth_m=float(f["depth_m"]),
            line_width_m={int(k): float(v) for k, v in f["line_width_m"].items()},
            overrides=dict(f.get("overrides") or {}),
            families={name: group[0] for group in (f.get("equivalent") or [])
                      for name in group},
            change_families={name: group[0] for group in (f.get("change_equivalent") or [])
                             for name in group},
            sample_fps=float(t["sample_fps"]),
            window_s=float(t["window_s"]),
            step_s=float(t["step_s"]),
            min_players=int(t["min_players"]),
            min_usable_fraction=float(t["min_usable_fraction"]),
            coverage_full=float(t["coverage_full"]),
            fit_iterations=int(t["fit_iterations"]),
            scale_range=(float(t["scale_range"][0]), float(t["scale_range"][1])),
            softmax_temperature_m2=float(t["softmax_temperature_m2"]),
            confidence_threshold=float(t["confidence_threshold"]),
            gk_max_depth_m=float(gk["max_depth_m"]),
            gk_min_gap_m=float(gk["min_gap_m"]),
            min_persist_s=float(ch["min_persist_s"]),
            max_uncertain_gap_s=float(ch["max_uncertain_gap_s"]),
            back_line_default=int(m["back_line_default"]),
            robust_percentiles=(float(m["robust_percentiles"][0]),
                                float(m["robust_percentiles"][1])),
            press_players=int(m["press_players"]),
            press_near_m=float(m["press_near_m"]),
            press_far_m=float(m["press_far_m"]),
            max_segment_s=float(tl["max_segment_s"]),
            snap_to_period_s=float(tl["snap_to_period_s"]),
            low_visibility_players=float(tl["low_visibility_players"]),
            low_visibility_min_s=float(tl["low_visibility_min_s"]),
            line_drop_m=float(ld["min_drop_m"]) if ld else None,
            line_drop_hold_s=float(ld["min_hold_s"]) if ld else None,
        )


    def family(self, formation: str | None) -> str | None:
        """Family of a formation (itself unless listed in `formations.equivalent`)."""
        return None if formation is None else self.families.get(formation, formation)

    def change_family(self, formation: str | None) -> str | None:
        """Family used by the change detector: `formations.equivalent` plus
        `formations.change_equivalent` (labels and segments keep the narrower `family`)."""
        if formation is None:
            return None
        f = self.family(formation)
        return self.change_families.get(f, self.change_families.get(formation, f))


@dataclass
class TeamFrame:
    """One team in one sampled frame (normalised coordinates unless stated)."""

    t: float
    outfield: np.ndarray  # (k, 2) outfield players, attacking-direction normalised
    n_visible: int  # all visible players of this team, keeper included
    ball: np.ndarray | None  # (2,) normalised ball position, None if not visible
    possession: str | None
    raw_outfield: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))  # pitch metres


def attacks_right(match: MatchState, side: Side, t: float) -> bool:
    """Whether `side` attacks towards x = pitch length at time `t` (flips every period)."""
    first = match.teams.home if side == "home" else match.teams.away
    right = first.attacking_direction_first_half == "right"
    return right if match.period_at(t) % 2 == 0 else not right


def normalise(xy: np.ndarray, right: bool, length: float, width: float) -> np.ndarray:
    """Rotate pitch coordinates so the team attacks towards +x (180-degree turn if needed)."""
    if right or xy.size == 0:
        return xy.copy()
    out = np.empty_like(xy)
    out[..., 0] = length - xy[..., 0]
    out[..., 1] = width - xy[..., 1]
    return out


def _drop_unlabelled_keeper(xy: np.ndarray, raw: np.ndarray, cfg: TacticsConfig
                            ) -> tuple[np.ndarray, np.ndarray]:
    """Remove the goalkeeper by position when the producer did not label one.

    TeamTrack has no goalkeeper flag, so the deepest player is dropped when there are more
    players than outfield slots, or when he stands alone near his own goal line.
    """
    if len(xy) == 0:
        return xy, raw
    order = np.argsort(xy[:, 0])
    deepest = order[0]
    too_many = len(xy) > cfg.outfield_players
    alone = xy[deepest, 0] <= cfg.gk_max_depth_m and (
        len(xy) == 1 or xy[order[1], 0] - xy[deepest, 0] >= cfg.gk_min_gap_m
    )
    if too_many or alone:
        keep = np.ones(len(xy), dtype=bool)
        keep[deepest] = False
        return xy[keep], raw[keep]
    return xy, raw


def sample_frames(match: MatchState, sample_fps: float) -> list[int]:
    """Indices of frames kept when resampling `match.frames` down to `sample_fps`."""
    if sample_fps >= match.fps:
        return list(range(len(match.frames)))
    keep: list[int] = []
    last_bucket = None
    for i, f in enumerate(match.frames):
        bucket = int(np.floor(f.t * sample_fps + 1e-9))
        if bucket != last_bucket:
            keep.append(i)
            last_bucket = bucket
    return keep


def extract_team_frames(match: MatchState, cfg: TacticsConfig) -> dict[Side, list[TeamFrame]]:
    """Per team, the sampled frames as normalised arrays. Referees and unknowns are ignored."""
    L, W = match.pitch.length_m, match.pitch.width_m
    out: dict[Side, list[TeamFrame]] = {s: [] for s in SIDES}
    for i in sample_frames(match, cfg.sample_fps):
        f = match.frames[i]
        ball_raw = None
        if f.ball is not None and f.ball.visible and f.ball.x is not None and f.ball.y is not None:
            ball_raw = np.array([f.ball.x, f.ball.y], dtype=float)
        for side in SIDES:
            right = attacks_right(match, side, f.t)
            team = [p for p in f.players if p.team == side]
            outfield = [p for p in team if p.role == "outfield"]
            has_keeper = any(p.role == "goalkeeper" for p in team)
            raw = np.array([[p.x, p.y] for p in outfield], dtype=float).reshape(-1, 2)
            xy = normalise(raw, right, L, W)
            if not has_keeper:
                xy, raw = _drop_unlabelled_keeper(xy, raw, cfg)
            ball = None if ball_raw is None else normalise(ball_raw, right, L, W)
            out[side].append(TeamFrame(t=f.t, outfield=xy, n_visible=len(team), ball=ball,
                                       possession=f.possession, raw_outfield=raw))
    return out
