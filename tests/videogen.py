"""Generated top-down match videos for the API tests (no real footage in the repo)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from gaffer.perception.pitch import render_pitch_view

HOME = (235, 235, 235)  # white shirts (BGR)
AWAY = (170, 70, 25)  # blue shirts
SHAPE_442 = [(0.15, 0.5), (0.3, 0.15), (0.3, 0.38), (0.3, 0.62), (0.3, 0.85), (0.5, 0.15),
             (0.5, 0.38), (0.5, 0.62), (0.5, 0.85), (0.68, 0.38), (0.68, 0.62)]


def players_at(t: float, length: float = 105.0, width: float = 68.0
               ) -> list[tuple[float, float, tuple[int, int, int]]]:
    """22 players in two 4-4-2 blocks (incl. keepers) drifting slowly with time."""
    out = []
    for i, (fx, fy) in enumerate(SHAPE_442):
        dx = 3.0 * np.sin(0.3 * t + i)
        dy = 2.0 * np.cos(0.25 * t + i)
        hx = fx * length * 0.5 + dx  # home in the left half
        out.append((hx, fy * width + dy, HOME))
        ax = length - fx * length * 0.5 - dx
        out.append((ax, (1 - fy) * width - dy, AWAY))
    return out


def write_video(path: Path, seconds: float = 8.0, fps: float = 10.0,
                size: tuple[int, int] = (960, 600),
                corners: list[list[float]] | None = None) -> Path:
    """An MP4 (mp4v) of a generated top-down match."""
    corners = corners or [[90, 70], [870, 72], [868, 540], [92, 538]]
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not w.isOpened():
        raise RuntimeError("OpenCV cannot write mp4v here")
    for k in range(int(seconds * fps)):
        t = k / fps
        w.write(render_pitch_view(size, corners, players=players_at(t), seed=k))
    w.release()
    return path
