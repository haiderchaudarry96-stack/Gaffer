"""How often do real frames reach the formation engine's bar (`tactics.min_players`)?

On the oracle the answer is trivially ~100 % (TeamTrack annotates all 22 players in every
frame, even hidden ones). The question that matters is how many players the *detector*
delivers. Before the team classifier exists, this script measures detection-limited coverage:
every GT player matched by a detection (centre distance <= 1 m on the pitch) counts as visible,
with its GT team. Team-classification losses come on top (measured in eval_real.py).

Usage:
    py scripts\\coverage_check.py --view top
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.evaluation import match_distance
from gaffer.perception.detector import DetectorError, make_detector
from gaffer.perception.drift import GeometryProvider
from gaffer.perception.matchstate import ObservedFrame, ObservedPlayer, assemble
from gaffer.perception.pitch import Calibration, CalibrationError, PitchModel
from gaffer.perception.video import VideoError, VideoSource
from gaffer.schema import load_match_state
from gaffer.tactics.common import SIDES, TacticsConfig, extract_team_frames
from gaffer.teamtrack import DatasetError, find_clips, foot_points, load_gt


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Detection-limited formation coverage")
    ap.add_argument("--view", choices=["top", "side"], default="top")
    args = ap.parse_args(argv)
    tt = cfg["teamtrack"]
    vcfg = tt["views"][args.view]
    try:
        calib = Calibration.for_view(cfg, args.view)
        model = PitchModel(calib.length_m, calib.width_m)
        det = make_detector(cfg, args.view, model)
        geo = GeometryProvider(calib, cfg, args.view, model)
        src = VideoSource(repo_path(tt["clip_lists"]) / f"teamtrack_{args.view}.clips.json")
        clips = find_clips(args.view, cfg)
        gts = [load_gt(c.csv).boxes for c in clips]
        oracle = load_match_state(repo_path(f"outputs/oracle_{args.view}.json"))
    except (CalibrationError, DatasetError, DetectorError, VideoError) as exc:
        print(f"ERROR: {exc} (run teamtrack_to_matchstate.py first)", file=sys.stderr)
        return 2
    side_of = {k: v["side"] for k, v in tt["teams"].items()}
    thr = float(cfg["detector"]["eval"]["distance_threshold_m"])
    frames, t0 = [], time.perf_counter()
    for t, ci, fi, img in src.frames(src.sample_times(float(cfg["perception"]["sample_fps"]))):
        g = geo.for_frame(img)
        d = det.detect(img, g.mapper).persons()
        pts = (d.boxes[:, :2] + d.boxes[:, 2:] / 2) if vcfg["foot_point"] == "centre" else \
            np.stack([d.boxes[:, 0] + d.boxes[:, 2] / 2, d.boxes[:, 1] + d.boxes[:, 3]], 1)
        dxy = g.mapper.to_pitch(pts) if len(d) else np.zeros((0, 2))
        gdf = gts[ci][(gts[ci]["frame"] == fi) & gts[ci]["team"].isin(list(side_of))]
        gxy = g.mapper.to_pitch(foot_points(gdf, vcfg["foot_point"]))
        m = match_distance(gxy, dxy, thr)
        teams, pids = gdf["team"].to_numpy(), gdf["player"].to_numpy()
        frames.append(ObservedFrame(t, [ObservedPlayer(int(teams[i]) * 100 + int(pids[i]),
                                                       side_of[teams[i]], *dxy[j])
                                        for i, j in m.pairs]))
    dirs = {s: getattr(oracle.teams, s).attacking_direction_first_half for s in SIDES}
    teams = {s: {"name": getattr(oracle.teams, s).name, "colour": getattr(oracle.teams, s).colour}
             for s in SIDES}
    match = assemble(f"coverage_{args.view}", "video", float(cfg["perception"]["sample_fps"]),
                     model.length, model.width, frames, teams, dirs, None, "coverage_check",
                     "", float(cfg["perception"]["possession_radius_m"]), duration_s=src.end_s)
    tcfg = TacticsConfig.from_config(cfg)
    tf = extract_team_frames(match, tcfg)
    print(f"view {args.view}: {len(frames)} frames at 2 fps, detector "
          f"{cfg['detector']['views'][args.view]['method']} ({time.perf_counter() - t0:.0f} s)")
    for s in SIDES:
        n = np.array([len(f.outfield) for f in tf[s]])
        print(f"  {s}: detected outfield players per engine frame: mean {n.mean():.1f}, "
              f"median {np.median(n):.0f}; >= {tcfg.min_players}: "
              f"{np.mean(n >= tcfg.min_players):.1%}; >= 7: {np.mean(n >= 7):.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
