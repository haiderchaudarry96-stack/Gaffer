"""Persistent player ids with ByteTrack (`supervision` 0.30, MIT).

ByteTrack associates boxes between frames by IoU (after a Kalman prediction). At the 2 fps
sampling rate a sprinting player moves ~4 m between samples: ~120 px in the drone view, while
the box is ~35 px, so consecutive boxes of the same player often do not overlap at all. The
boxes handed to ByteTrack are therefore **enlarged around their centre for matching only**
(`match_scale`, larger at lower rates); each track is mapped back to its original detection,
so positions always come from the real detection, never from the enlarged box. The
enlargement is relative to the box size, which also suits the side view, where both box size
and on-screen speed shrink with distance.

`supervision.ByteTrack` is deprecated since 0.28 (removal planned in 0.31); the pinned 0.30.9
keeps it, and its FutureWarning is silenced here.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from gaffer.perception.detector import Detections


@dataclass(frozen=True)
class TrackerSettings:
    """From config `tracking`."""

    match_scale_hz: float
    min_match_scale: float
    activation_threshold: float
    matching_threshold: float
    lost_s: float
    min_consecutive_frames: int
    unit_scores: bool

    @classmethod
    def from_config(cls, cfg: dict[str, Any], view: str) -> TrackerSettings:
        t = {**cfg["tracking"], **(cfg["tracking"].get("views", {}).get(view) or {})}
        return cls(float(t["match_scale_hz"]), float(t["min_match_scale"]),
                   float(t["activation_threshold"]),
                   float(t["matching_threshold"]), float(t["lost_s"]),
                   int(t["min_consecutive_frames"]), bool(t.get("unit_scores", False)))


def enlarge(boxes_xywh: np.ndarray, scale: float) -> np.ndarray:
    """xyxy boxes scaled by `scale` around their centres."""
    b = np.asarray(boxes_xywh, float).reshape(-1, 4)
    c = b[:, :2] + b[:, 2:] / 2
    half = b[:, 2:] * scale / 2
    return np.concatenate([c - half, c + half], axis=1)


class PlayerTracker:
    """ByteTrack over sampled frames; `update` returns a track id per detection (-1 = not
    tracked this frame, e.g. a new track's first frame)."""

    def __init__(self, s: TrackerSettings, fps: float) -> None:
        self.s = s
        self.reset(fps)

    def match_scale(self) -> float:
        """Box enlargement for matching at this rate: it must cover the distance a player can
        move between two samples, which shrinks as 1 / fps (config 1 + 12 / fps: 7x at 2 fps,
        4x at 4 fps, 3x at 6 fps; dev-clip sweeps, FAILURE_LOG 2026-10-14)."""
        return max(self.s.min_match_scale, 1.0 + self.s.match_scale_hz / self.fps)

    def reset(self, fps: float) -> None:
        import supervision as sv

        self.fps = float(fps)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            # max_time_lost (frames) = frame_rate / 30 * lost_track_buffer = fps * lost_s
            self.bt = sv.ByteTrack(track_activation_threshold=self.s.activation_threshold,
                                   lost_track_buffer=max(1, int(round(30 * self.s.lost_s))),
                                   minimum_matching_threshold=self.s.matching_threshold,
                                   frame_rate=self.fps,
                                   minimum_consecutive_frames=self.s.min_consecutive_frames)
        self._sv = sv

    def update(self, det: Detections) -> np.ndarray:
        """Track ids for this frame's detections (-1 = not tracked).

        ByteTrack's own `update_with_detections` maps tracks back to detections by IoU of the
        Kalman-smoothed box, which becomes ambiguous when enlarged boxes of neighbours overlap
        (dev clip: 33 extra ID switches at any enlargement >= 7x). Tracks are therefore mapped
        back by **centre distance** (Hungarian, gated at one original box size): after the
        Kalman update a track's centre sits on the detection it was associated with.
        """
        ids = np.full(len(det), -1, dtype=int)
        big = enlarge(det.boxes, self.match_scale()) if len(det) else np.zeros((0, 4))
        conf = (np.ones(len(det)) if self.s.unit_scores else np.clip(det.scores, 0.0, 1.0))
        tensors = np.hstack([big, conf.reshape(-1, 1)]).astype(np.float32)
        tracks = self.bt.update_with_tensors(tensors=tensors)
        if not tracks or len(det) == 0:
            return ids
        tc = np.array([(t.tlbr[:2] + t.tlbr[2:]) / 2 for t in tracks], float)
        dc = det.boxes[:, :2] + det.boxes[:, 2:] / 2
        dist = np.linalg.norm(dc[:, None] - tc[None], axis=2)
        gate = det.boxes[:, 2:].max(axis=1, keepdims=True)
        cost = np.where(dist <= gate, dist, 1e9)
        r, c = linear_sum_assignment(cost)
        for i, j in zip(r, c, strict=True):
            if cost[i, j] < 1e9:
                ids[i] = int(tracks[j].external_track_id)
        return ids
