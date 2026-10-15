"""The oracle: TeamTrack ground-truth boxes + TeamIDs -> MatchState (`source: "annotation"`).

Uses exactly the pipeline's geometry: the view's calibration, re-anchored on every sampled
frame for the drifting drone (`perception/drift.py`), and the shared MatchState rules
(`perception/matchstate.py`). Running the tactics engine on this file and on the pipeline's
output for the same clips shows how much accuracy perception loses.

Also reports the formation-engine coverage: the share of sampled frames in which a team has at
least `tactics.min_players` outfield players (keeper removed exactly as the engine does).

Usage:
    py scripts\\teamtrack_to_matchstate.py --view top       # -> outputs/oracle_top.json
    py scripts\\teamtrack_to_matchstate.py --view side
    py scripts\\teamtrack_to_matchstate.py --view top --no-video   # skip re-anchoring (fast)
    py scripts\\teamtrack_to_matchstate.py --view side --gt-inset  # -> oracle_side_inset.json

The official oracle uses the raw GT box bottom. `--gt-inset` moves the side-view foot point up
by `teamtrack.views.side.gt_foot_inset_px` (the measured annotation margin, FAILURE_LOG
2026-10-14): a second, clearly labelled reference, used only to report metric error both ways.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.perception.drift import GeometryProvider
from gaffer.perception.matchstate import (
    ObservedFrame,
    ObservedPlayer,
    assemble,
    infer_attacking_direction,
    on_pitch,
)
from gaffer.perception.pitch import Calibration, CalibrationError, PitchModel
from gaffer.perception.video import VideoError, VideoSource
from gaffer.schema import ContractError
from gaffer.tactics.common import SIDES, TacticsConfig, extract_team_frames
from gaffer.teamtrack import DatasetError, find_clips, foot_points, load_gt, write_clip_list


def coverage(match, tcfg: TacticsConfig) -> dict[str, float]:
    """Share of engine-sampled frames where each team has >= min_players outfield players."""
    tf = extract_team_frames(match, tcfg)
    return {s: round(float(np.mean([len(f.outfield) >= tcfg.min_players for f in tf[s]])), 4)
            for s in SIDES}


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="TeamTrack GT -> oracle MatchState")
    ap.add_argument("--view", choices=["top", "side"], required=True)
    ap.add_argument("--fps", type=float, default=float(cfg["perception"]["sample_fps"]))
    ap.add_argument("--no-video", action="store_true",
                    help="use the reference calibration without per-frame re-anchoring")
    ap.add_argument("--set", default=None, choices=["eval2"],
                    help="clip set (teamtrack.clip_sets); default dev + eval. eval2 -> "
                         "outputs/oracle_<view>_eval2[_inset].json")
    ap.add_argument("--gt-inset", action="store_true",
                    help="move the GT foot point up by gt_foot_inset_px (labelled variant)")
    ap.add_argument("--out", default=None,
                    help="default outputs/oracle_<view>.json (oracle_<view>_inset.json)")
    args = ap.parse_args(argv)

    timings: Counter = Counter()
    t_all = time.perf_counter()
    tt, view = cfg["teamtrack"], args.view
    vcfg = tt["views"][view]
    inset = float(vcfg.get("gt_foot_inset_px", 0.0)) if args.gt_inset else 0.0
    try:
        calib = Calibration.for_view(cfg, view)
        clips = find_clips(view, cfg, [args.set] if args.set else None)
        if any(c.half != 1 for c in clips):
            raise DatasetError("only first-half clips are supported (all ours are half 1)")
        match_id = f"teamtrack_{view}" + (f"_{args.set}" if args.set else "")
        clip_list = write_clip_list(clips, repo_path(tt["clip_lists"]) / f"{match_id}.clips.json")
        src = VideoSource(clip_list)
        gts = [load_gt(c.csv) for c in clips]
    except (CalibrationError, DatasetError, VideoError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    L, W = calib.length_m, calib.width_m
    model = PitchModel(L, W)
    team_side = {tid: t["side"] for tid, t in tt["teams"].items()}
    teams = {t["side"]: {"name": t["name"], "colour": t["colour"]} for t in tt["teams"].values()}
    times = src.sample_times(args.fps)
    geo = GeometryProvider(calib, cfg, view, model)

    def frame_iter():
        if args.no_video or not geo.anchor:
            for t in times:
                ci, fi = src.locate(t)  # type: ignore[misc]
                yield t, ci, fi, None
        else:
            yield from src.frames(times)

    frames: list[ObservedFrame] = []
    sampled_missing = Counter()
    dropped = 0
    t0 = time.perf_counter()
    for t, ci, fi, img in frame_iter():
        t1 = time.perf_counter()
        timings["decode"] += t1 - t0
        g = geo.for_frame(img) if img is not None else geo.for_frame_static()
        t2 = time.perf_counter()
        timings["geometry"] += t2 - t1
        rows = gts[ci].boxes[gts[ci].boxes["frame"] == fi]
        players_df = rows[rows["team"].isin(list(team_side))]
        n_expected = 2 * 11
        if len(players_df) < n_expected:
            sampled_missing["frames"] += 1
            sampled_missing["objects"] += n_expected - len(players_df)
        xy = g.mapper.to_pitch(foot_points(players_df, vcfg["foot_point"], inset))
        ok = on_pitch(xy, L, W)
        dropped += int((~ok).sum())
        players = [ObservedPlayer(int(tm) * 100 + int(pid), team_side[tm], float(p[0]),
                                  float(p[1]))
                   for (tm, pid, p) in zip(players_df["team"], players_df["player"], xy,
                                           strict=True)]
        ball_df = rows[rows["team"] == "BALL"]
        ball = None
        if len(ball_df):
            b = g.mapper.to_pitch(foot_points(ball_df.iloc[:1], "centre"))[0]
            ball = (float(b[0]), float(b[1]))
        frames.append(ObservedFrame(
            t=t, players=players, ball=ball, dropped_off_pitch=int((~ok).sum()),
            quality={"players_detected": len(players_df), "homography_ok": g.homography_ok,
                     "reprojection_error_m": g.reprojection_error_m, "camera_cut": False}))
        t0 = time.perf_counter()
        timings["ground_truth"] += t0 - t2

    t3 = time.perf_counter()
    directions = infer_attacking_direction(frames, L)
    if directions is None:
        print("ERROR: could not infer attacking directions (a team is never visible)",
              file=sys.stderr)
        return 2
    try:
        match = assemble(
            match_id, "annotation", args.fps, L, W, frames, teams, directions,
            {"uri": clip_list.relative_to(repo_path(".")).as_posix(),
             "native_fps": src.native_fps, "width": src.width, "height": src.height},
            "scripts/teamtrack_to_matchstate.py (oracle)",
            f"TeamTrack {view} GT boxes, foot point = box {vcfg['foot_point']}"
            + (f" moved up {inset:g} px (annotation margin removed)" if inset else "")
            + "; geometry "
            f"{'re-anchored per frame' if geo.anchor and not args.no_video else 'static'}",
            float(cfg["perception"]["possession_radius_m"]),
            duration_s=src.end_s)
    except ContractError as exc:
        print(f"ERROR: oracle MatchState invalid: {exc}", file=sys.stderr)
        return 2
    tag = (f"_{args.set}" if args.set else "") + ("_inset" if args.gt_inset else "")
    out = repo_path(args.out or f"outputs/oracle_{view}{tag}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(match.model_dump_json(by_alias=True), encoding="utf-8")
    timings["assemble"] += time.perf_counter() - t3

    tcfg = TacticsConfig.from_config(cfg)
    cov = coverage(match, tcfg)
    errs = [f.quality.reprojection_error_m for f in match.frames
            if f.quality and f.quality.reprojection_error_m is not None]
    total_missing = sum(g.missing_objects for g in gts)
    total_missing_frames = sum(g.frames_with_missing for g in gts)
    print(f"view {view}: {len(match.frames)} frames at {args.fps:g} fps "
          f"({match.frames[0].t:.1f}-{match.frames[-1].t:.1f} s), {len(clips)} clips")
    print(f"teams: {', '.join(f'TeamID {k} -> {v}' for k, v in team_side.items())}; inferred "
          f"attacking direction (first half): {directions}")
    print(f"empty CSV cells: {total_missing} object-frames in {total_missing_frames} video "
          f"frames skipped (all clips); in the sampled frames: {sampled_missing['objects']} "
          f"objects in {sampled_missing['frames']} frames")
    print(f"dropped as off-pitch (> 5 m outside): {dropped} player positions")
    if errs:
        print(f"per-frame line alignment error: median {np.median(errs):.3f} m, max "
              f"{max(errs):.3f} m; homography_ok in "
              f"{np.mean([f.quality.homography_ok for f in match.frames]):.1%} of frames")
    print(f"coverage (>= {tcfg.min_players} of {tcfg.outfield_players} outfield players, "
          f"engine sampling {tcfg.sample_fps:g} fps): home {cov['home']:.1%}, away "
          f"{cov['away']:.1%}")
    print("timing: " + ", ".join(f"{k} {v:.1f}s" for k, v in timings.items())
          + f" | total {time.perf_counter() - t_all:.1f}s")
    print(f"-> {out}\n-> {clip_list}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
