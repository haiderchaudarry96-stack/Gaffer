"""720p check: the same drone window at 4K and at 720p, scored against TeamTrack ground truth.

One clip, TeamTrack train split (match 900-1260 s), NOT held out. Default config (both
calibration tiers must be off). Both copies are continuous files; they are addressed on the
original TeamTrack boundaries (12 x 900 frames = 30 s each) so every sampled frame has the same
match time and the same GT frame as the 4K clip list.

- GT boxes are in 4K pixels. For BOTH rows they are projected with the per-frame mapper of the
  4K run at the same time stamp (the 4K calibration plus its drift re-anchoring); the 720p run
  scores its own pitch positions against them. `eval_tracking.score` uses the mapper only for GT.
- The 720p run's calibration is the saved 4K homography scaled exactly by 3 (3840/1280); its
  drift reference is the 4K calibration frame resized to 1280 x 720.
- Formation agreement and candidate events are against `outputs/oracle_top_full.json`; the
  White 16:30 change = a home candidate to 3-4-3 within the event tolerance of 990 s.

Usage: py scripts\\eval_720p_check.py   (writes outputs/teamtrack_720p_check/)
"""

from __future__ import annotations

import copy
import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np

from gaffer.agent.context import MatchContext
from gaffer.config import load_config, repo_path
from gaffer.perception import pipeline as pipeline_module
from gaffer.perception.pitch import Calibration
from gaffer.perception.video import ClipInfo, VideoSource
from gaffer.schema import load_match_state
from gaffer.tactics.common import TacticsConfig
from gaffer.teamtrack import find_clips, load_gt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_real import compare, cut  # noqa: E402
from eval_tracking import score  # noqa: E402

START, END, FPS = 900.0, 1260.0, 4.0
CLIP_FRAMES, N_CLIPS = 900, 12
WHITE_CHANGE_S = 990.0
VIDEOS = {"4k": ("data/sample_clips/teamtrack_top_0900_1260_4k.mp4", (3840, 2160)),
          "720p": ("data/sample_clips/teamtrack_top_0900_1260_720p.mp4", (1280, 720))}
OUT_DIR = repo_path("outputs/teamtrack_720p_check")


class SegmentedSource:
    """A continuous copy of the window, addressed on TeamTrack's 900-frame clip boundaries."""

    def __init__(self, uri: str | Path, size: tuple[int, int]) -> None:
        base = VideoSource(uri)
        if (base.width, base.height) != size:
            raise RuntimeError(f"{uri}: expected {size}, found {(base.width, base.height)}")
        if base.clips[0].frames != CLIP_FRAMES * N_CLIPS:
            raise RuntimeError(f"{uri}: expected {CLIP_FRAMES * N_CLIPS} frames, "
                               f"found {base.clips[0].frames}")
        self.path = base.clips[0].path
        self.native_fps, self.width, self.height = base.native_fps, base.width, base.height
        self.clips = [ClipInfo(self.path, START + i * 30.0, CLIP_FRAMES, base.native_fps,
                               base.width, base.height) for i in range(N_CLIPS)]

    @property
    def start_s(self) -> float:
        return self.clips[0].start_s

    @property
    def end_s(self) -> float:
        return self.clips[-1].end_s

    def locate(self, t: float) -> tuple[int, int] | None:
        for i in range(len(self.clips) - 1, -1, -1):
            c = self.clips[i]
            if t >= c.start_s - 1e-6:
                f = int(round((t - c.start_s) * c.fps))
                return (i, f) if f < c.frames else None
        return None

    def sample_times(self, fps: float, start_s: float | None = None,
                     end_s: float | None = None) -> list[float]:
        a = self.start_s if start_s is None else max(float(start_s), self.start_s)
        b = self.end_s if end_s is None else min(float(end_s), self.end_s)
        return [float(t) for t in np.round(np.arange(a, b - 1e-9, 1.0 / fps), 3)
                if self.locate(float(t)) is not None]

    def frames(self, times: list[float]) -> Iterator[tuple[float, int, int, np.ndarray]]:
        cap = cv2.VideoCapture(str(self.path))
        pos = 0
        try:
            for t in sorted(times):
                loc = self.locate(t)
                if loc is None:
                    continue
                ci, fi = loc
                target = ci * CLIP_FRAMES + fi
                if target < pos:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                    pos = target
                while pos < target:
                    cap.grab()
                    pos += 1
                ok, frame = cap.read()
                pos += 1
                if not ok:
                    raise RuntimeError(f"could not read frame {target} (match time {t})")
                yield t, ci, fi, frame
        finally:
            cap.release()

    def read(self, t: float) -> np.ndarray:
        for _, _, _, frame in self.frames([t]):
            return frame
        raise RuntimeError(f"no frame at match time {t}")


@contextmanager
def segmented(size: tuple[int, int]) -> Iterator[None]:
    """Make `pipeline.run` open its video through `SegmentedSource` (this script only)."""
    real = pipeline_module.VideoSource
    pipeline_module.VideoSource = lambda uri, start_s=0.0: SegmentedSource(uri, size)
    try:
        yield
    finally:
        pipeline_module.VideoSource = real


def calibration_720p(cfg: dict[str, Any]) -> dict[str, Any]:
    """Config whose calibration dir holds the 4K homography scaled by 3 for 1280 x 720."""
    cal4 = Calibration.for_view(cfg, "top")
    if tuple(cal4.image_size) != (3840, 2160):
        raise RuntimeError(f"4K calibration expected, found {cal4.image_size}")
    cap = cv2.VideoCapture(str(repo_path(cal4.source)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, cal4.frame_index)
    ok, ref4 = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("could not read the 4K calibration reference frame")
    cal_dir = OUT_DIR / "calibration_720p"
    cal_dir.mkdir(parents=True, exist_ok=True)
    ref = cal_dir / "top_reference.avi"  # drift reads the reference through VideoSource
    writer = cv2.VideoWriter(str(ref), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (1280, 720))
    if not writer.isOpened():
        raise RuntimeError(f"could not write {ref}")
    writer.write(cv2.resize(ref4, (1280, 720), interpolation=cv2.INTER_AREA))
    writer.release()
    h4 = np.asarray(cal4.params["H_image_to_pitch"], dtype=float)
    cal = replace(cal4, image_size=(1280, 720), source=str(ref), frame_index=0,
                  params={**cal4.params,
                          "H_image_to_pitch": (h4 @ np.diag([3.0, 3.0, 1.0])).tolist()})
    cal.save(cal_dir / "top.json")
    out = copy.deepcopy(cfg)
    out["calibration"]["dir"] = str(cal_dir)
    return out


def white_change(match: Any, cfg: dict[str, Any], tol_s: float) -> dict[str, Any]:
    """Home candidates to 3-4-3 near 16:30 (the engine's candidates, as the agent sees them)."""
    ctx = MatchContext(match, cfg, view="top")
    near = [c for c in ctx.candidates if c.team == "home" and abs(float(c.t) - WHITE_CHANGE_S)
            <= tol_s]
    hits = [c for c in near if c.to == "3-4-3"]
    return {"found": bool(hits),
            "home_candidates_within_tol": [f"t={c.t:.0f}s {c.from_} -> {c.to}" for c in near],
            "all_candidates": [f"{c.team} t={c.t:.0f}s {c.from_} -> {c.to}"
                               for c in ctx.candidates]}


def main() -> int:
    cfg = load_config()
    tiers = cfg["perception"]["self_calibration"]["calibration_tiers"]
    if tiers["tier1"]["enabled"] or tiers["tier2"]["enabled"]:
        raise SystemExit("calibration tiers must both be off for this check")
    gt_src = VideoSource(repo_path("data/clips/teamtrack_top_full.clips.json"))
    gts = [load_gt(c.csv).boxes for c in find_clips("top", cfg, ["train", "eval2", "dev", "eval"])]
    oracle = cut(load_match_state(repo_path("outputs/oracle_top_full.json")), START, END)
    tcfg = TacticsConfig.from_config(cfg)
    tol = float(cfg["eval"]["synthetic"]["tolerance_s"])
    change_family = {n: g[0] for g in (cfg["formations"].get("change_equivalent") or [])
                     for n in g}
    run_cfg = {"4k": cfg, "720p": calibration_720p(cfg)}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: dict[str, Any] = {}
    gt_mappers: dict[float, Any] = {}
    for name in ("4k", "720p"):  # 4K first: its mappers project the GT for both rows
        rel, size = VIDEOS[name]
        print(f"[{name}] pipeline {START:.0f}-{END:.0f} s at {FPS:g} fps", flush=True)
        t0 = time.perf_counter()
        with segmented(size):
            res = pipeline_module.run(repo_path(rel), view="top", start_s=START, end_s=END,
                                      track_fps=FPS, cfg=run_cfg[name], progress=True,
                                      match_id=f"teamtrack_top_w900_1260_{name}_check")
        wall = time.perf_counter() - t0
        pipeline_module.write_outputs(res, OUT_DIR / f"match_state_{name}.json")
        if name == "4k":
            gt_mappers = {r.t: r.mapper for r in res.records if r.output}
            scored = res
        else:
            missing = [r.t for r in res.records if r.output and r.t not in gt_mappers]
            if missing:
                raise RuntimeError(f"no 4K mapper for {len(missing)} 720p frames, "
                                   f"e.g. t={missing[0]}")
            scored = SimpleNamespace(
                records=[replace(r, mapper=gt_mappers[r.t]) if r.output else r
                         for r in res.records],
                match=res.match, timing=res.timing, video_seconds=res.video_seconds)
        row = score(scored, cfg, "top", gt_src, gts, 1.0, lambda t: START <= t < END)
        out_dets = [(r.track_ids[i], r.teams[i]) for r in res.records if r.output
                    for i in range(len(r.teams))]
        n_all = sum(tid >= 0 and team != "static" for tid, team in out_dets)
        n_lab = sum(tid >= 0 and team in ("home", "away") for tid, team in out_dets)
        row["team_labelled_share_all_detections"] = round(n_lab / max(n_all, 1), 4)
        cmp = compare(cut(res.match, START, END), oracle, tcfg, tol, change_family)
        row["formation"] = {s: cmp[s]["formation"] for s in ("home", "away")}
        row["coverage"] = {s: cmp[s]["coverage"] for s in ("home", "away")}
        row["events_vs_oracle"] = cmp["events"]
        row["white_1630"] = white_change(res.match, cfg, tol)
        row["wall_s"] = round(wall, 1)
        rows[name] = row
        d = row["detection"]["raw"]
        print(f"[{name}] P {d['precision']} R {d['recall']} F1 {d['f1']} "
              f"team {row['teams']['accuracy_settled']} labelled "
              f"{row['team_labelled_share_all_detections']} IDF1 {row['identity']['idf1']} "
              f"form {row['formation']['home']['exact_agreement']} / "
              f"{row['formation']['away']['exact_agreement']} "
              f"16:30 {row['white_1630']['found']} s/s {row['seconds_per_video_second']} "
              f"wall {wall:.0f} s", flush=True)
        del res, scored

    report = {"description": "720p check (one clip, TeamTrack train split, not held out)",
              "window_match_s": [START, END], "track_fps": FPS, "match_m": 1.0,
              "calibration_tiers": {"tier1": False, "tier2": False},
              "gt_projection": "4K GT boxes through the 4K run's per-frame mappers, both rows",
              "rows": rows}
    path = OUT_DIR / "report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
