"""Upload checks (`api.uploads`): what Gaffer accepts, and coach-readable refusals.

Accepted: an MP4 or MOV that OpenCV can decode, at most `max_bytes` and `max_duration_s`
(6 min), from a top-down camera. TeamTrack drone clips (file name `D_<date>_<n>_<start>_<end>.mp4`
at 3840 x 2160) are recognised and keep the saved 31-point calibration; TeamTrack side-camera
clips and panoramas are refused (only top-down views are supported).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

import cv2
import numpy as np


class UploadRefused(ValueError):
    """The upload breaks a rule; the message is shown to the coach as is."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class VideoInfo:
    filename: str
    bytes: int
    width: int
    height: int
    fps: float
    frames: int
    duration_s: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnownSource:
    """A recognised TeamTrack drone clip."""

    kind: str  # "teamtrack_top"
    match_start_s: float
    match_end_s: float


def safe_name(name: str | None) -> str:
    base = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120] or "upload"


def check_extension(name: str, cfg: dict[str, Any]) -> str:
    ext = Path(name).suffix.lower()
    allowed = [e.lower() for e in cfg["api"]["uploads"]["extensions"]]
    if ext not in allowed:
        kinds = " or ".join(e.strip(".").upper() for e in allowed)
        got = ext.strip(".").upper() or "a file without an extension"
        raise UploadRefused(f"Gaffer accepts {kinds} videos; this file is {got}. Export the "
                            "match as MP4 and try again.", 415)
    return ext


def save_stream(src: BinaryIO, dest: Path, cfg: dict[str, Any]) -> int:
    """Copy the upload to `dest` in chunks, stopping (and deleting it) past `max_bytes`."""
    u = cfg["api"]["uploads"]
    limit, chunk = int(u["max_bytes"]), int(u["chunk_bytes"])
    n = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while True:
            block = src.read(chunk)
            if not block:
                break
            n += len(block)
            if n > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise UploadRefused(f"The video is larger than {limit / 1e6:.0f} MB, the upload "
                                    "limit. Trim it to the part you want analysed (at most "
                                    f"{int(u['max_duration_s']) // 60} minutes) or export it at a "
                                    "lower bitrate.", 413)
            out.write(block)
    if n == 0:
        dest.unlink(missing_ok=True)
        raise UploadRefused("The uploaded file is empty.")
    return n


def probe(path: Path, filename: str, nbytes: int) -> VideoInfo:
    """Size, frame rate and duration as OpenCV reads them (`cv2.VideoCapture`)."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise UploadRefused("OpenCV could not open this video. Please upload an MP4 (H.264) "
                                "or MOV file.")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None or w <= 0 or h <= 0:
        raise UploadRefused("OpenCV could not decode the first frame of this video. Please "
                            "upload an MP4 (H.264) or MOV file.")
    if not np.isfinite(fps) or fps <= 0 or frames <= 0:
        raise UploadRefused("This video has no readable frame rate or length. Re-export it as "
                            "MP4 and try again.")
    return VideoInfo(filename, nbytes, w, h, round(fps, 3), frames, round(frames / fps, 2))


def known_source(name: str, info: VideoInfo, cfg: dict[str, Any]) -> KnownSource | None:
    tt = cfg["api"]["uploads"]["teamtrack"]
    m = re.match(tt["top_pattern"], name)
    if m and [info.width, info.height] == [int(v) for v in tt["top_size"]]:
        return KnownSource("teamtrack_top", float(m.group(1)), float(m.group(2)))
    return None


def check_rules(name: str, info: VideoInfo, cfg: dict[str, Any],
                known_flag: bool | None) -> KnownSource | None:
    """Apply the upload rules; returns the recognised TeamTrack source (None = other video).

    `known_flag`: None = recognise TeamTrack clips by name and size; True = the uploader says it
    is one (refused if it is not); False = treat it as any other video (calibration step)."""
    u = cfg["api"]["uploads"]
    if re.match(u["teamtrack"]["side_pattern"], name):
        raise UploadRefused("This is a TeamTrack side-camera clip. Gaffer analyses top-down "
                            "(drone) views only; upload a soccer_top clip instead.")
    if info.duration_s > float(u["max_duration_s"]):
        lim = float(u["max_duration_s"])
        raise UploadRefused(f"This video is {info.duration_s / 60:.1f} minutes long; the limit is "
                            f"{lim / 60:g} minutes. Trim it to the part of the match you want "
                            "analysed and upload it again.")
    if info.duration_s < float(u["min_duration_s"]):
        raise UploadRefused(f"This video is only {info.duration_s:.1f} s long. Gaffer needs at "
                            f"least {float(u['min_duration_s']):g} s of play to read a formation.")
    if info.width < int(u["min_width_px"]):
        raise UploadRefused(f"This video is {info.width} x {info.height} pixels; Gaffer needs at "
                            f"least {int(u['min_width_px'])} pixels across to see the players.")
    aspect = info.width / info.height
    if aspect > float(u["max_aspect"]) or aspect < 1 / float(u["max_aspect"]):
        raise UploadRefused(f"This video is {info.width} x {info.height} pixels: a panorama or "
                            "side-camera shape. Gaffer analyses top-down views only, such as a "
                            "drone straight above the pitch.")
    ks = known_source(name, info, cfg) if known_flag is not False else None
    if known_flag is True and ks is None:
        size = "x".join(str(v) for v in u["teamtrack"]["top_size"])
        raise UploadRefused(f"known_source is only for TeamTrack drone clips (a file name like "
                            f"D_20220220_1_1530_1560.mp4 at {size}); this file is {name} at "
                            f"{info.width}x{info.height}. Upload it without known_source and mark "
                            "the pitch corners instead.")
    return ks


def read_frame(path: Path, t_s: float) -> tuple[np.ndarray, int]:
    """The frame at `t_s` (or the first one) and its index."""
    cap = cv2.VideoCapture(str(path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        idx = int(min(max(0, round(t_s * fps)), max(0, n - 1)))
        if idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok and idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            idx = 0
            ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise UploadRefused("OpenCV could not decode a frame of this video.")
    return frame, idx
