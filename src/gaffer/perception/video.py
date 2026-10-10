"""Read frames at chosen match times from a video or a `*.clips.json` clip list.

`MatchState.source_video.uri` is either a plain video file or a clip list of consecutive files
(convention in `docs/DATA_CONTRACT.md`). `VideoSource` hides the difference: callers ask for
match times, it decodes the right clip and frame. Decoding is sequential (`cv2.VideoCapture.grab`
to skip frames), which is much faster than seeking in 4K H.264.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from gaffer.config import repo_path

#: Seek with CAP_PROP_POS_FRAMES instead of grabbing when the gap is larger than this.
SEEK_GAP_FRAMES = 300


class VideoError(RuntimeError):
    """A video is missing, unreadable, or the clips of a list do not match."""


@dataclass(frozen=True)
class ClipInfo:
    path: Path
    start_s: float
    frames: int
    fps: float
    width: int
    height: int

    @property
    def end_s(self) -> float:
        return self.start_s + self.frames / self.fps


def _probe(path: Path, start_s: float) -> ClipInfo:
    if not path.exists():
        raise VideoError(f"Video not found: {path}")
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VideoError(f"OpenCV could not open {path} (unreadable or unsupported codec)")
    info = ClipInfo(path, float(start_s), int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                    float(cap.get(cv2.CAP_PROP_FPS)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    if info.fps <= 0 or info.frames <= 0:
        raise VideoError(f"{path}: OpenCV reports fps={info.fps}, frames={info.frames}")
    return info


class VideoSource:
    """A video (or a list of consecutive clips) addressed by match time in seconds."""

    def __init__(self, uri: str | Path, start_s: float = 0.0) -> None:
        self.uri = str(uri)
        p = repo_path(uri)
        if p.name.endswith(".clips.json"):
            if not p.exists():
                raise VideoError(f"Clip list not found: {p}")
            try:
                items = json.loads(p.read_text(encoding="utf-8"))["clips"]
                self.clips = [_probe((p.parent / c["path"]).resolve(), float(c["start_s"]))
                              for c in items]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise VideoError(f"{p} is not a valid clip list: {exc}") from exc
        else:
            self.clips = [_probe(p, start_s)]
        if not self.clips:
            raise VideoError(f"{p}: no clips")
        self.clips.sort(key=lambda c: c.start_s)
        first = self.clips[0]
        for c in self.clips[1:]:
            if (c.width, c.height) != (first.width, first.height) or abs(c.fps - first.fps) > 0.01:
                raise VideoError(f"clip {c.path.name} differs from {first.path.name} in size/fps")
        self.native_fps, self.width, self.height = first.fps, first.width, first.height

    @property
    def start_s(self) -> float:
        return self.clips[0].start_s

    @property
    def end_s(self) -> float:
        return self.clips[-1].end_s

    def locate(self, t: float) -> tuple[int, int] | None:
        """(clip index, frame index) showing match time `t`, or None if outside every clip."""
        for i in range(len(self.clips) - 1, -1, -1):
            c = self.clips[i]
            if t >= c.start_s - 1e-6:
                f = int(round((t - c.start_s) * c.fps))
                return (i, f) if f < c.frames else None
        return None

    def sample_times(self, fps: float, start_s: float | None = None,
                     end_s: float | None = None) -> list[float]:
        """Match times at `fps` inside [start_s, end_s) that some clip covers."""
        a = self.start_s if start_s is None else max(start_s, self.start_s)
        b = self.end_s if end_s is None else min(end_s, self.end_s)
        ts = np.round(np.arange(a, b - 1e-9, 1.0 / fps), 3)
        return [float(t) for t in ts if self.locate(float(t)) is not None]

    def frames(self, times: Iterable[float]) -> Iterator[tuple[float, int, int, np.ndarray]]:
        """Yield (t, clip index, frame index, BGR frame) for each requested time, in order.
        Times no clip covers are skipped; unreadable frames raise `VideoError`."""
        cap: cv2.VideoCapture | None = None
        cur_clip, pos = -1, 0
        for t in sorted(times):
            loc = self.locate(t)
            if loc is None:
                continue
            ci, fi = loc
            if ci != cur_clip:
                if cap is not None:
                    cap.release()
                cap = cv2.VideoCapture(str(self.clips[ci].path))
                if not cap.isOpened():
                    raise VideoError(f"OpenCV could not open {self.clips[ci].path}")
                cur_clip, pos = ci, 0
            assert cap is not None
            if fi < pos or fi - pos > SEEK_GAP_FRAMES:
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                pos = fi
            while pos < fi:
                cap.grab()
                pos += 1
            ok, frame = cap.read()
            pos += 1
            if not ok:
                raise VideoError(f"could not read frame {fi} of {self.clips[ci].path}")
            yield t, ci, fi, frame
        if cap is not None:
            cap.release()

    def read(self, t: float) -> np.ndarray:
        """One frame at match time `t`."""
        for _, _, _, frame in self.frames([t]):
            return frame
        raise VideoError(f"no clip covers t={t:.2f} s in {self.uri}")
