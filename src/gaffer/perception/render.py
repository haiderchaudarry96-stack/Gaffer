"""Drawing for the perception debug video: annotated frame + 2D minimap (OpenCV drawing only).

Boxes are coloured by team (config `perception.debug_video.colours_bgr`), labelled with the track
id (`GK` for goalkeepers); the minimap is the pitch model drawn to scale with one dot per player
at its projected position.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from gaffer.perception.pitch import PitchModel


def _colour(team: str, colours: dict[str, Any]) -> tuple[int, int, int]:
    c = colours.get(team, colours.get("unknown", [150, 150, 150]))
    return int(c[0]), int(c[1]), int(c[2])


def draw_minimap(model: PitchModel, players: list[dict[str, Any]], colours: dict[str, Any],
                 px_per_m: float, ball: tuple[float, float] | None = None,
                 title: str = "", rotate_180: bool = False) -> np.ndarray:
    """Top-down pitch (x right, y up as in the contract) with a dot per player.

    `rotate_180` turns the map to match a camera that sees the pitch the other way round (the
    TeamTrack drone image is rotated 180 degrees relative to the pitch frame), so the debug
    video can be checked by eye; positions themselves are unchanged.
    """
    m = 3.0  # margin in metres
    w = int(round((model.length + 2 * m) * px_per_m))
    h = int(round((model.width + 2 * m) * px_per_m))
    img = np.full((h, w, 3), (40, 110, 40), np.uint8)

    def to_px(xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, float).reshape(-1, 2)
        if rotate_180:
            xy = np.stack([model.length - xy[:, 0], model.width - xy[:, 1]], 1)
        return np.stack([(xy[:, 0] + m) * px_per_m, (model.width - xy[:, 1] + m) * px_per_m],
                        1).round().astype(np.int32)

    for poly in model.lines(0.5).values():
        cv2.polylines(img, [to_px(poly).reshape(-1, 1, 2)], False, (230, 230, 230), 1,
                      cv2.LINE_AA)
    r = max(3, int(round(0.9 * px_per_m)))
    for p in players:
        c = to_px(np.array([[p["x"], p["y"]]]))[0]
        col = _colour(p["team"], colours)
        cv2.circle(img, (int(c[0]), int(c[1])), r, col, -1, cv2.LINE_AA)
        cv2.circle(img, (int(c[0]), int(c[1])), r, (20, 20, 20), 1, cv2.LINE_AA)
        if p.get("role") == "goalkeeper":
            cv2.circle(img, (int(c[0]), int(c[1])), r + 2, (0, 0, 255), 1, cv2.LINE_AA)
    if ball is not None:
        c = to_px(np.array([ball]))[0]
        cv2.circle(img, (int(c[0]), int(c[1])), max(2, r // 2), (0, 255, 255), -1, cv2.LINE_AA)
    if title:
        cv2.putText(img, title, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
                    cv2.LINE_AA)
    return img


def annotate_frame(frame: np.ndarray, boxes: np.ndarray, teams: list[str], roles: list[str],
                   track_ids: np.ndarray, colours: dict[str, Any], thickness: int = 2
                   ) -> np.ndarray:
    """Copy of `frame` with team-coloured boxes and track ids."""
    out = frame.copy()
    fs = max(0.4, min(out.shape[:2]) / 1800)
    for b, team, role, tid in zip(boxes, teams, roles, track_ids, strict=True):
        x, y, w, h = (int(round(v)) for v in b)
        col = _colour(team, colours)
        cv2.rectangle(out, (x, y), (x + w, y + h), col, thickness)
        label = ("GK" if role == "goalkeeper" else "") + (str(int(tid)) if tid >= 0 else "?")
        cv2.putText(out, label, (x, max(10, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0),
                    thickness + 2, cv2.LINE_AA)
        cv2.putText(out, label, (x, max(10, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, fs, col,
                    max(1, thickness - 1), cv2.LINE_AA)
    return out


def compose(view_img: np.ndarray, minimap: np.ndarray, width: int, header: str) -> np.ndarray:
    """Frame scaled to `width`, minimap centred below it, a one-line header on top."""
    k = width / view_img.shape[1]
    top = cv2.resize(view_img, (width, int(round(view_img.shape[0] * k))),
                     interpolation=cv2.INTER_AREA)
    mm = minimap
    if mm.shape[1] > width:
        mm = cv2.resize(mm, (width, int(mm.shape[0] * width / mm.shape[1])))
    panel = np.full((mm.shape[0] + 8, width, 3), 25, np.uint8)
    x0 = (width - mm.shape[1]) // 2
    panel[4:4 + mm.shape[0], x0:x0 + mm.shape[1]] = mm
    bar = np.full((28, width, 3), 15, np.uint8)
    cv2.putText(bar, header, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                cv2.LINE_AA)
    out = np.vstack([bar, top, panel])
    return out[: out.shape[0] // 2 * 2, : out.shape[1] // 2 * 2]  # even size for codecs
