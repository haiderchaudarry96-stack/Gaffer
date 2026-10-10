"""Overlapping tiles for native-resolution inference, and cross-tile NMS.

Full-frame inference is useless on both TeamTrack views (players shrink to ~4 px when a 4K or
6500 px frame is letterboxed to 640; DATA_NOTES section 5), so detectors run on overlapping
native-resolution tiles that cover only the region of interest (the pitch), and duplicate boxes
from neighbouring tiles are merged with `cv2.dnn.NMSBoxesBatched`.
"""

from __future__ import annotations

import cv2
import numpy as np


def tile_grid(x0: int, y0: int, x1: int, y1: int, tile: int, overlap: int,
              img_w: int, img_h: int) -> list[tuple[int, int, int, int]]:
    """Tiles (x, y, w, h) of size `tile` covering [x0, x1) x [y0, y1) with at least `overlap`
    pixels shared by neighbours. Tiles are shifted inside the image rather than shrunk, so
    every tile keeps the full size when the image allows it."""
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(img_w, int(np.ceil(x1))), min(img_h, int(np.ceil(y1)))
    if x1 <= x0 or y1 <= y0:
        return []

    def starts(a: int, b: int, size: int) -> list[int]:
        if b - a <= tile:
            return [max(0, min(a, size - tile))]
        step = tile - overlap
        n = int(np.ceil((b - a - tile) / step)) + 1
        pos = np.linspace(a, b - tile, n).round().astype(int)
        return [int(max(0, min(p, size - tile))) for p in pos]

    tw, th = min(tile, img_w), min(tile, img_h)
    return [(x, y, tw, th) for y in starts(y0, y1, img_h) for x in starts(x0, x1, img_w)]


def nms(boxes: np.ndarray, scores: np.ndarray, classes: np.ndarray, score_thr: float,
        iou_thr: float) -> np.ndarray:
    """Indices kept by class-aware NMS (`cv2.dnn.NMSBoxesBatched`); boxes are (N, 4) xywh."""
    if len(boxes) == 0:
        return np.zeros(0, dtype=int)
    keep = cv2.dnn.NMSBoxesBatched(boxes.astype(float).tolist(), scores.astype(float).tolist(),
                                   classes.astype(int).tolist(), score_thr, iou_thr)
    return np.array(keep, dtype=int).reshape(-1)
