"""Matching detections to ground truth (eval scripts only; never used by the pipeline).

Two criteria, because TeamTrack drone boxes are tiny (~30 px): IoU >= threshold (the standard)
and centre distance on the pitch in metres (what matters for formations). Both use one-to-one
Hungarian assignment (`scipy.optimize.linear_sum_assignment`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU of xywh boxes a (N, 4) and b (M, 4)."""
    a, b = np.asarray(a, float).reshape(-1, 4), np.asarray(b, float).reshape(-1, 4)
    ax1, ay1, ax2, ay2 = a[:, 0], a[:, 1], a[:, 0] + a[:, 2], a[:, 1] + a[:, 3]
    bx1, by1, bx2, by2 = b[:, 0], b[:, 1], b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    iw = np.clip(np.minimum(ax2[:, None], bx2) - np.maximum(ax1[:, None], bx1), 0, None)
    ih = np.clip(np.minimum(ay2[:, None], by2) - np.maximum(ay1[:, None], by1), 0, None)
    inter = iw * ih
    union = (a[:, 2] * a[:, 3])[:, None] + b[:, 2] * b[:, 3] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


@dataclass
class Match:
    """One-to-one assignment result: index pairs (gt, det) and the unmatched indices."""

    pairs: list[tuple[int, int]]
    missed: list[int]  # ground truth without a detection (false negatives)
    extra: list[int]  # detections without ground truth (false positives)

    @property
    def tp(self) -> int:
        return len(self.pairs)


def _assign(score: np.ndarray, valid: np.ndarray, maximise: bool) -> Match:
    n, m = score.shape
    if n == 0 or m == 0:
        return Match([], list(range(n)), list(range(m)))
    big = 1e9
    cost = np.where(valid, -score if maximise else score, big)
    r, c = linear_sum_assignment(cost)
    pairs = [(int(i), int(j)) for i, j in zip(r, c, strict=True) if valid[i, j]]
    gi, dj = {i for i, _ in pairs}, {j for _, j in pairs}
    return Match(pairs, [i for i in range(n) if i not in gi], [j for j in range(m) if j not in dj])


def match_iou(gt: np.ndarray, det: np.ndarray, thr: float) -> Match:
    """Match boxes with IoU >= thr, maximising total IoU."""
    iou = iou_matrix(gt, det)
    return _assign(iou, iou >= thr, maximise=True)


def match_distance(gt_xy: np.ndarray, det_xy: np.ndarray, thr: float) -> Match:
    """Match points (e.g. pitch metres) closer than thr, minimising total distance."""
    g, d = np.asarray(gt_xy, float).reshape(-1, 2), np.asarray(det_xy, float).reshape(-1, 2)
    dist = np.linalg.norm(g[:, None] - d[None], axis=2) if len(g) and len(d) else \
        np.zeros((len(g), len(d)))
    return _assign(dist, dist <= thr, maximise=False)


def isolated(gt: np.ndarray, thr: float = 0.05) -> np.ndarray:
    """Boolean mask of GT boxes that overlap no other GT box (IoU < thr): players a detector
    can see separately. GT keeps boxes for players hidden behind others (DATA_NOTES)."""
    iou = iou_matrix(gt, gt)
    np.fill_diagonal(iou, 0.0)
    return (iou < thr).all(axis=1) if len(gt) else np.zeros(0, bool)


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    """Precision, recall, F1."""
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0}
