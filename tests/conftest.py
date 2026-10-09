"""Shared helpers for the tactics tests: tiny MatchState builders and small synthetic configs."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from gaffer.config import load_config
from gaffer.schema import MatchState, parse_match_state
from gaffer.tactics.common import TacticsConfig


def match_dict(frames: list[dict[str, Any]], duration: float = 600.0, fps: float = 1.0,
               half: float | None = None) -> dict[str, Any]:
    """A minimal contract-valid MatchState dict around `frames`."""
    half = duration / 2 if half is None else half
    return {
        "contract_version": "1.0",
        "match_id": "test",
        "source": "synthetic",
        "fps": fps,
        "duration_s": duration,
        "pitch": {"length_m": 105.0, "width_m": 68.0},
        "source_video": None,
        "teams": {
            "home": {"name": "Blue", "colour": "#1e5fbf",
                     "attacking_direction_first_half": "right"},
            "away": {"name": "Red", "colour": "#c0392b", "attacking_direction_first_half": "left"},
        },
        "periods": [{"name": "first_half", "start_s": 0.0, "end_s": half},
                    {"name": "second_half", "start_s": half, "end_s": duration}],
        "frames": frames,
        "meta": {"generator": "tests", "opencv_version": None,
                 "created_utc": "2026-10-10T00:00:00Z", "notes": ""},
    }


def player(track_id: int, team: str, x: float, y: float, role: str = "outfield"
           ) -> dict[str, Any]:
    return {"track_id": track_id, "team": team, "role": role, "x": float(x), "y": float(y),
            "confidence": 0.9, "interpolated": False}


def build_match(frames: list[dict[str, Any]], **kw: Any) -> MatchState:
    return parse_match_state(match_dict(frames, **kw))


def shape_points(slots: np.ndarray, centre: tuple[float, float], rng: np.random.Generator,
                 noise: float = 1.0, scale: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:
    """Template slots placed at `centre` (normalised coords) with stretch and noise."""
    return slots * np.asarray(scale) + np.asarray(centre) + rng.normal(0, noise, slots.shape)


@pytest.fixture
def cfg() -> TacticsConfig:
    return TacticsConfig.from_config()


@pytest.fixture
def small_synth_cfg() -> dict[str, Any]:
    """A 15-minute synthetic setup with no decoys and a full view (tests switch things on)."""
    c = copy.deepcopy(load_config())
    sc = c["synthetic"]
    sc["duration_s"] = 900.0
    sc["half_time_s"] = 450.0
    sc["noise_events"].update({"set_pieces": [0, 0], "counters": [0, 0], "flickers": [0, 0]})
    sc["camera"]["broadcast_fraction"] = 0.0
    return c
