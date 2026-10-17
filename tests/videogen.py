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


def _writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not w.isOpened():
        raise RuntimeError("OpenCV cannot write mp4v here")
    return w


def _frames(players_fn, seconds: float, fps: float, size: tuple[int, int],
            corners: list[list[float]]):
    """Frames: the pitch is rendered once; players are drawn through the same homography."""
    bg = render_pitch_view(size, corners, noise=0.0)
    W = 68.0
    H = cv2.getPerspectiveTransform(np.float32([[0, W], [105, W], [105, 0], [0, 0]]),
                                    np.float32(corners))
    px_per_m = np.linalg.norm(np.subtract(corners[1], corners[0])) / 105.0
    r = max(2, int(round(0.45 * px_per_m)))
    rng = np.random.default_rng(42)
    for k in range(int(seconds * fps)):
        t = k / fps
        img = bg.copy()
        pl = players_fn(t)
        uv = cv2.perspectiveTransform(np.float32([[x, y] for x, y, _ in pl]).reshape(-1, 1, 2),
                                      H).reshape(-1, 2)
        for (u, v), (_, _, col) in zip(uv, pl, strict=True):
            cv2.circle(img, (int(round(u)), int(round(v))), r, col, -1, cv2.LINE_AA)
        noise = rng.integers(-3, 4, img.shape, dtype=np.int16)
        yield np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def write_video(path: Path, seconds: float = 8.0, fps: float = 10.0,
                size: tuple[int, int] = (960, 600),
                corners: list[list[float]] | None = None) -> Path:
    """An MP4 (mp4v) of a generated top-down match."""
    corners = corners or [[90, 70], [870, 72], [868, 540], [92, 538]]
    w = _writer(path, fps, size)
    for f in _frames(players_at, seconds, fps, size, corners):
        w.write(f)
    w.release()
    return path

SHAPE_352 = [(0.15, 0.5), (0.3, 0.25), (0.3, 0.5), (0.3, 0.75), (0.5, 0.08), (0.5, 0.3),
             (0.5, 0.5), (0.5, 0.7), (0.5, 0.92), (0.68, 0.38), (0.68, 0.62)]


def players_switch(t: float, switch_s: float, length: float = 105.0, width: float = 68.0
                   ) -> list[tuple[float, float, tuple[int, int, int]]]:
    """Home plays 4-4-2 until `switch_s`, then 3-5-2; away stays 4-4-2."""
    out = []
    home = SHAPE_442 if t < switch_s else SHAPE_352
    for i in range(11):
        dx = 2.0 * np.sin(0.3 * t + i)
        dy = 1.5 * np.cos(0.25 * t + i)
        fx, fy = home[i]
        out.append((fx * length * 0.5 + 6 + dx, fy * width + dy, HOME))
        gx, gy = SHAPE_442[i]
        out.append((length - gx * length * 0.5 - 6 - dx, (1 - gy) * width - dy, AWAY))
    return out


def write_switch_video(path: Path, seconds: float = 180.0, fps: float = 8.0,
                       switch_s: float = 75.0, size: tuple[int, int] = (960, 600)) -> Path:
    """Home switches 4-4-2 -> 3-5-2 at `switch_s` (a real change the agent should confirm)."""
    corners = [[90, 70], [870, 72], [868, 540], [92, 538]]
    w = _writer(path, fps, size)
    for f in _frames(lambda t: players_switch(t, switch_s), seconds, fps, size, corners):
        w.write(f)
    w.release()
    return path
