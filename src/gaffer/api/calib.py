"""Pitch calibration for an upload (docs/API.md, "Pitch step").

- **Known TeamTrack drone clip**: the saved 31-point calibration (`data/calibration/top.json`) is
  used unchanged. If its reference clip is not on this machine, the same homography is re-anchored
  to the upload's first frame instead (the drone drifts up to ~14 px between clips, Phase 2).
- **Any other top-down video**: OpenCV auto-detects the pitch corners on one frame
  (`perception.pitch.detect_pitch_corners`). High confidence -> `needs_confirmation` (corners +
  an overlay JPEG); low confidence or no pitch found -> `needs_corners`. **Gaffer never analyses
  on auto-detected corners the coach has not confirmed.** The coach's 4 points (TL, TR, BR, BL)
  or a confirmation give a 4-corner homography (`four_corner_homography`).

The calibration is written to `<analysis>/calibration/top.json`; the pipeline and the agent get a
copy of the config whose `calibration.dir` points there, so they run unchanged.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gaffer.api.uploads import KnownSource, VideoInfo
from gaffer.config import repo_path
from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    detect_pitch_corners,
    draw_corner_overlay,
    four_corner_calibration,
    four_corner_homography,
)

CLIPS_NAME = "video.clips.json"
FRAME_NAME = "first_frame.jpg"
PREVIEW_NAME = "pitch_preview.jpg"


def rel(p: Path) -> str:
    """Repo-relative path when inside the repo (how MatchState URIs are written), else absolute."""
    try:
        return p.resolve().relative_to(repo_path(".").resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def write_clip_list(job_dir: Path, video_name: str, start_s: float) -> Path:
    """A one-clip `*.clips.json` (DATA_CONTRACT convention): match time `start_s` = first frame,
    so the pipeline and the agent's video backend address the upload by match time."""
    p = job_dir / CLIPS_NAME
    p.write_text(json.dumps({"clips": [{"path": video_name, "start_s": float(start_s)}]}),
                 encoding="utf-8")
    return p


def job_config(cfg: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    """The config for this analysis: identical except `calibration.dir` (outside the frozen
    agent fingerprint, which covers agent / tactics / bedrock / synthetic / formations)."""
    c = copy.deepcopy(cfg)
    c["calibration"]["dir"] = rel(job_dir / "calibration")
    return c


def calibration_path(cfg: dict[str, Any], job_dir: Path) -> Path:
    name = cfg["teamtrack"]["views"][cfg["api"]["jobs"]["view"]]["calibration"]
    return job_dir / "calibration" / f"{name}.json"


def use_saved(cfg: dict[str, Any], job_dir: Path, clips: Path) -> dict[str, Any]:
    """Known TeamTrack clip: copy the saved calibration (or re-anchor it, see module doc)."""
    view = cfg["api"]["jobs"]["view"]
    saved = Calibration.for_view(cfg, view)
    dest = calibration_path(cfg, job_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if repo_path(saved.source).exists():
        shutil.copyfile(repo_path(cfg["calibration"]["dir"]) / dest.name, dest)
        return {"state": "saved", "method": "saved_31_point",
                "note": "TeamTrack drone clip: the saved 31-point calibration is used."}
    saved.source, saved.frame_index = rel(clips), 0
    saved.meta = {**saved.meta, "reanchored_to_upload": True}
    saved.save(dest)
    return {"state": "saved", "method": "saved_31_point_reanchored",
            "note": "TeamTrack drone clip: the saved 31-point calibration, re-anchored to this "
                    "clip's first frame (its reference clip is not on this server; the drone "
                    "drifts up to ~14 px between clips)."}


def save_frame(job_dir: Path, frame: np.ndarray) -> None:
    cv2.imwrite(str(job_dir / FRAME_NAME), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])


def load_frame(job_dir: Path) -> np.ndarray:
    img = cv2.imread(str(job_dir / FRAME_NAME))
    if img is None:
        raise CalibrationError("the reference frame of this analysis is missing")
    return img


def write_preview(job_dir: Path, frame: np.ndarray, corners: Any, cfg: dict[str, Any],
                  title: str) -> None:
    L, W = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])
    img = draw_corner_overlay(frame, corners, L, W, title)
    cv2.imwrite(str(job_dir / PREVIEW_NAME), img, [cv2.IMWRITE_JPEG_QUALITY, 85])


def autodetect(job_dir: Path, frame: np.ndarray, cfg: dict[str, Any]) -> dict[str, Any]:
    """Auto-detect on the reference frame; returns the `pitch` block of the status."""
    d = detect_pitch_corners(frame, cfg)
    s = d.summary()
    if d.accepted and d.corners is not None:
        write_preview(job_dir, frame, d.corners, cfg,
                      f"Is this the pitch? Gaffer found the outline ({d.confidence:.0%} sure)")
        return {"state": "detected", "detection": s, "corners": s["corners"],
                "message": "Gaffer found the pitch outline. Check that the green line sits on "
                           "the pitch boundary, then confirm it or adjust the 4 corners."}
    if d.corners is not None:  # a guess the coach can start from, never used unconfirmed
        write_preview(job_dir, frame, d.corners, cfg, "Not sure where the pitch is: please mark "
                                                      "the 4 corners")
    why = "; ".join(d.problems[:3]) or "no pitch outline found"
    return {"state": "needs_corners", "detection": s, "corners": None,
            "suggested_corners": s["corners"],
            "message": f"Gaffer could not find the pitch reliably ({why}). Please mark the 4 "
                       "corners of the pitch: top-left, top-right, bottom-right, bottom-left."}


def parse_points(raw: Any) -> list[list[float]]:
    """4 points as [[x, y], ...] or [{"x":, "y":}, ...] (JSON string or object)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CalibrationError("pitch_points must be JSON: 4 points [[x, y], ...] in the "
                                   "order top-left, top-right, bottom-right, bottom-left") from exc
    if not isinstance(raw, list | tuple) or len(raw) != 4:
        raise CalibrationError("Exactly 4 pitch corners are needed (top-left, top-right, "
                               "bottom-right, bottom-left).")
    out = []
    for p in raw:
        if isinstance(p, dict) and "x" in p and "y" in p:
            out.append([float(p["x"]), float(p["y"])])
        elif isinstance(p, list | tuple) and len(p) == 2:
            out.append([float(p[0]), float(p[1])])
        else:
            raise CalibrationError("Each pitch corner must be [x, y] or {\"x\": .., \"y\": ..} "
                                   "in video pixels.")
    return out


def apply_corners(job_dir: Path, frame: np.ndarray, frame_index: int, info: VideoInfo,
                  corners: Any, cfg: dict[str, Any], picked_by: str) -> dict[str, Any]:
    """4-corner calibration from given / confirmed corners (raises CalibrationError)."""
    L, W = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])
    fc = four_corner_homography(corners, (info.width, info.height), L, W,
                                cfg["calibration"]["four_corner"])
    cal = four_corner_calibration(fc, (info.width, info.height), L, W,
                                  rel(job_dir / CLIPS_NAME), frame_index, picked_by,
                                  cfg["api"]["jobs"]["view"])
    cal.save(calibration_path(cfg, job_dir))
    who = {"coach": "marked by the coach", "auto_confirmed": "found by Gaffer, confirmed by the "
           "coach"}.get(picked_by, picked_by)
    write_preview(job_dir, frame, corners, cfg, f"Pitch corners ({who})")
    return {"method": f"four_corner_{picked_by}",
            "corners": [[round(x, 1), round(y, 1)] for x, y in fc.corners_px.tolist()],
            "checks": {"opposite_edge_ratio": fc.opposite_edge_ratio,
                       "aspect_px": fc.aspect_px, "area_frac": fc.area_frac,
                       "rotated": fc.rotated}}


def frame_edges(info: VideoInfo) -> list[list[float]]:
    """'My video already looks straight down on the full pitch': the frame edges."""
    w, h = info.width - 1, info.height - 1
    return [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]]


def known_note(ks: KnownSource) -> str:
    return (f"TeamTrack drone clip, match time {ks.match_start_s:.0f}-{ks.match_end_s:.0f} s")
