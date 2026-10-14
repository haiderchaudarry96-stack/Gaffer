"""TeamTrack dataset helpers: clip discovery, ground-truth loading, clip lists.

Ground truth is read only by the oracle (`scripts/teamtrack_to_matchstate.py`) and the eval
scripts; the perception pipeline never touches it.

CSV layout (`docs/DATA_NOTES.md` section 3): three header rows (`TeamID`, `PlayerID`,
`Attributes`), one row per frame, 23 objects x 4 box attributes. Attributes are alphabetical
and PlayerIDs sort as strings, so columns are always addressed **by name**. CSV frame `k`
is video frame `k - 1`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gaffer.config import repo_path

NAME_RE = re.compile(r"^(?P<cam>[A-Z])_(?P<date>\d{8})_(?P<half>\d)_(?P<start>\d+)_(?P<end>\d+)$")
BOX_COLS = ["bb_left", "bb_top", "bb_width", "bb_height"]


class DatasetError(RuntimeError):
    """TeamTrack files are missing or malformed."""


@dataclass(frozen=True)
class Clip:
    """One ~30 s TeamTrack clip (video + annotation CSV)."""

    view: str
    stem: str
    video: Path
    csv: Path
    start_s: float
    end_s: float
    half: int


def find_clips(view: str, cfg: dict[str, Any]) -> list[Clip]:
    """All clips of a view (`top` | `side`), sorted by start time. Raises `DatasetError` with
    a download hint if the folder is missing or empty."""
    vcfg = cfg["teamtrack"]["views"][view]
    root = repo_path(cfg["paths"]["teamtrack"]) / vcfg["folder"]
    vids = sorted((root / "videos").glob("*.mp4"))
    if not vids:
        raise DatasetError(f"No TeamTrack videos in {root / 'videos'}. Download them with "
                           "`py scripts\\download_teamtrack.py` (see data/README.md).")
    clips = []
    for v in vids:
        m = NAME_RE.match(v.stem)
        if not m:
            continue
        csv = root / "annotations" / f"{v.stem}.csv"
        clips.append(Clip(view, v.stem, v, csv, float(m["start"]), float(m["end"]),
                          int(m["half"])))
    return sorted(clips, key=lambda c: c.start_s)


@dataclass
class GroundTruth:
    """Long-format boxes of one clip plus what was skipped."""

    boxes: pd.DataFrame  # frame (0-based video index), team ("0"/"1"/"BALL"), player, bb_*
    missing_objects: int  # object-frames with empty cells (skipped)
    frames_with_missing: int


def load_gt(csv: Path) -> GroundTruth:
    """Read a TeamTrack annotation CSV into long format (0-based `frame`).

    Empty cells (644 in our files, DATA_NOTES section 3) are skipped, not guessed; how many
    object-frames and frames were affected is returned so callers can report it.
    """
    if not csv.exists():
        raise DatasetError(f"Annotation CSV not found: {csv}")
    try:
        wide = pd.read_csv(csv, header=[0, 1, 2], index_col=0)
    except (ValueError, pd.errors.ParserError) as exc:
        raise DatasetError(f"{csv} is not a TeamTrack annotation CSV: {exc}") from exc
    long = wide.stack(level=[0, 1], future_stack=True)
    long.index.names = ["frame", "team", "player"]
    long = long.reset_index()
    missing_cols = [c for c in BOX_COLS if c not in long.columns]
    if missing_cols:
        raise DatasetError(f"{csv}: missing attribute columns {missing_cols}")
    bad = long[BOX_COLS].isna().any(axis=1)
    missing = long[bad]
    long = long[~bad].copy()
    long["frame"] = long["frame"].astype(int) - 1
    long["team"] = long["team"].astype(str)
    long["player"] = long["player"].astype(str)
    return GroundTruth(long.reset_index(drop=True), int(len(missing)),
                       int(missing["frame"].nunique()))


def foot_points(df: pd.DataFrame, mode: str, inset_px: float = 0.0) -> np.ndarray:
    """Image point that touches the ground for each box: `centre` (top-down view: the player is
    a blob seen from above) or `bottom` (side view: feet at the bottom edge).

    `inset_px` moves the bottom point up: TeamTrack side-view boxes are drawn with a margin of
    ~2-3 px below the feet (measured, FAILURE_LOG 2026-10-14), and on the far side one pixel
    row is 0.4-1 m of depth.
    """
    x = df["bb_left"].to_numpy() + df["bb_width"].to_numpy() / 2
    if mode == "centre":
        y = df["bb_top"].to_numpy() + df["bb_height"].to_numpy() / 2
    elif mode == "bottom":
        y = df["bb_top"].to_numpy() + df["bb_height"].to_numpy() - float(inset_px)
    else:
        raise ValueError(f"unknown foot point mode {mode!r}")
    return np.stack([x, y], axis=1)


def write_clip_list(clips: list[Clip], path: str | Path) -> Path:
    """Write a `*.clips.json` (DATA_CONTRACT convention) for consecutive clips; paths are
    relative to the list file."""
    p = repo_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rel = [Path(_relpath(c.video, p.parent)).as_posix() for c in clips]
    data = {"clips": [{"path": r, "start_s": c.start_s} for r, c in zip(rel, clips, strict=True)]}
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _relpath(target: Path, base: Path) -> str:
    import os

    return os.path.relpath(target.resolve(), base.resolve())
