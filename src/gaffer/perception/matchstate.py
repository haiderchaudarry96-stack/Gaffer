"""Assemble a contract-valid `MatchState` from per-frame pitch positions.

Shared by the OpenCV pipeline (`source: "video"`) and the TeamTrack oracle
(`source: "annotation"`), so both apply exactly the same rules:

- points more than `OFF_PITCH_TOLERANCE_M` outside the pitch are bad projections: dropped;
- possession = team of the nearest player within `possession_radius_m` of the visible ball
  (`contested` if both teams are that close, `null` when the ball is not visible);
- attacking direction is inferred from where each team's deepest player stands (keepers stay
  near their own goal), unless the config fixes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from gaffer.perception.pitch import utc_now
from gaffer.schema import OFF_PITCH_TOLERANCE_M, MatchState, parse_match_state


@dataclass
class ObservedPlayer:
    track_id: int
    team: str  # "home" | "away" | "referee" | "unknown"
    x: float
    y: float
    role: str = "outfield"
    confidence: float = 1.0


@dataclass
class ObservedFrame:
    t: float
    players: list[ObservedPlayer]
    ball: tuple[float, float] | None = None
    quality: dict[str, Any] | None = None
    dropped_off_pitch: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def on_pitch(xy: np.ndarray, length: float, width: float,
             tol: float = OFF_PITCH_TOLERANCE_M) -> np.ndarray:
    """Boolean mask of points within `tol` metres of the pitch (contract rule)."""
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    return ((xy[:, 0] >= -tol) & (xy[:, 0] <= length + tol) & (xy[:, 1] >= -tol)
            & (xy[:, 1] <= width + tol) & np.isfinite(xy).all(axis=1))


def possession(players: list[ObservedPlayer], ball: tuple[float, float] | None,
               radius_m: float) -> str | None:
    """Possession by proximity (see module docstring)."""
    if ball is None:
        return None
    near = {p.team for p in players if p.team in ("home", "away")
            and np.hypot(p.x - ball[0], p.y - ball[1]) <= radius_m}
    if len(near) == 2:
        return "contested"
    return near.pop() if near else None


def infer_attacking_direction(frames: list[ObservedFrame], length: float
                              ) -> dict[str, str] | None:
    """Direction each team attacks, by a per-frame vote on who stands deepest at each end.

    In a frame where both teams have 3+ players, the team whose rearmost player is nearer the
    left goal line gets a vote for "defends left", and the team whose rearmost player is
    nearer the right goal line a vote for "defends right". The offside rule keeps attackers
    behind the defenders' last outfield player, so this holds in most frames even without
    goalkeepers, which the pipeline only identifies after the direction is known. (A first
    version compared median gaps to the goal lines; without keepers it got the 270 s drone
    run backwards, FAILURE_LOG 2026-10-14.) Returns None if no frame shows both teams.
    """
    vote, seen = 0, False  # vote > 0: home defends left
    for f in frames:
        hx = [p.x for p in f.players if p.team == "home"]
        ax = [p.x for p in f.players if p.team == "away"]
        if len(hx) < 3 or len(ax) < 3:
            continue
        seen = True
        # home deeper at the left end, and away deeper at the right end -> home defends left
        vote += int(np.sign(min(ax) - min(hx))) + int(np.sign(max(ax) - max(hx)))
    if not seen:
        return None
    home_left = vote >= 0
    return {"home": "right" if home_left else "left", "away": "left" if home_left else "right"}


def assemble(match_id: str, source: str, fps: float, length: float, width: float,
             frames: list[ObservedFrame], teams: dict[str, dict[str, str]],
             directions: dict[str, str], source_video: dict[str, Any] | None,
             generator: str, notes: str, possession_radius_m: float,
             duration_s: float | None = None) -> MatchState:
    """Build and validate the MatchState (raises `ContractError` if anything is off)."""
    frames = sorted(frames, key=lambda f: f.t)
    out_frames = []
    for f in frames:
        keep = [p for p in f.players
                if on_pitch(np.array([[p.x, p.y]]), length, width)[0]]
        ball = f.ball if f.ball is not None and on_pitch(np.array([f.ball]), length, width)[0] \
            else None
        out_frames.append({
            "t": round(float(f.t), 3),
            "players": [{"track_id": int(p.track_id), "team": p.team, "role": p.role,
                         "x": round(float(p.x), 2), "y": round(float(p.y), 2),
                         "confidence": round(float(np.clip(p.confidence, 0, 1)), 3),
                         "interpolated": False} for p in keep],
            "ball": ({"x": round(float(ball[0]), 2), "y": round(float(ball[1]), 2),
                      "visible": True} if ball is not None else None),
            "possession": possession(keep, ball, possession_radius_m),
            "quality": f.quality,
        })
    end = duration_s if duration_s is not None else (frames[-1].t + 1.0 / fps if frames else 1)
    data = {
        "contract_version": "1.0", "match_id": match_id, "source": source, "fps": fps,
        "duration_s": round(float(end), 3),
        "pitch": {"length_m": length, "width_m": width},
        "source_video": source_video,
        "teams": {side: {"name": teams[side]["name"], "colour": teams[side]["colour"],
                         "attacking_direction_first_half": directions[side]}
                  for side in ("home", "away")},
        "periods": [{"name": "first_half", "start_s": 0.0, "end_s": round(float(end), 3)}],
        "frames": out_frames,
        "meta": {"generator": generator, "opencv_version": cv2.__version__,
                 "created_utc": utc_now(), "notes": notes},
    }
    return parse_match_state(data, match_id)
