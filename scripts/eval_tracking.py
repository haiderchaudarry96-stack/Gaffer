"""Tracking and team-classification accuracy of the perception pipeline against TeamTrack GT.

Runs `perception/pipeline.py` (in-process, exactly as the CLI) over a view's clips at one or more
tracking rates (output always at `perception.sample_fps`), then scores every output frame
against the ground-truth boxes projected with the same per-frame geometry:

- **detection** (what the pipeline outputs: tracked detections, static objects removed) at
  the GT <-> detection distance `tracking.eval.match_m` (1 m top, 2 m side:
  far-side positions are only good to ~1-2 m): precision raw, and precision with the
  detections the classifier calls `referee` removed (GT does not label referees, assistant
  referees or staff, so those are not detector errors);
- **teams** (matched players only; unmatched detections are referees/staff/false positives and
  are never team errors): accuracy of settled labels, unknown share, share called referee;
  how the unmatched detections were labelled;
- **identity**: ID switches (a GT player matched to a different track id than at their last
  match, CLEAR-MOT), per player-minute, IDF1 (one-to-one GT id <-> track id
  assignment maximising matched frames), distinct track ids per GT player;
- **speed**: the pipeline's per-stage timing.

The dev clip (`detector.eval.dev_clips`) is evaluated only with `--dev` (tuning); results come
from the other clips, which are consecutive and run as one window. `--set eval2` runs the
second eval set instead (`teamtrack.clip_sets`; never tuned on, but the same match and cameras
as eval): all its clips are run and scored as one window, outputs
`outputs/eval_second_set_tracking_<view>.json` and `match_state_<view>_eval2_<fps>fps.json`.

Usage:
    py scripts\\eval_tracking.py --view top --track-fps 2 4 6 --whole-source --save
    py scripts\\eval_tracking.py --view side --track-fps 2 6 --end 1740
    py scripts\\eval_tracking.py --view top --dev            # tuning only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from gaffer.config import load_config, repo_path, with_overrides
from gaffer.evaluation import match_distance, prf
from gaffer.perception.detector import DetectorError
from gaffer.perception.pipeline import PipelineError, PipelineResult, run, write_outputs
from gaffer.perception.pitch import CalibrationError
from gaffer.perception.video import VideoError, VideoSource
from gaffer.schema import ContractError
from gaffer.teamtrack import DatasetError, find_clips, foot_points, load_gt


def score(res: PipelineResult, cfg: dict[str, Any], view: str, src: VideoSource,
          gts: list[Any], match_m: float, scored: Callable[[float], bool] | None = None
          ) -> dict[str, Any]:
    """All metrics for one pipeline run (see module docstring); only output frames for which
    `scored(t)` is true count (default: all)."""
    side_of = {tid: t["side"] for tid, t in cfg["teamtrack"]["teams"].items()}
    foot = cfg["perception"]["foot_point"][view]
    c: Counter = Counter()
    matched_label: Counter = Counter()
    unmatched_label: Counter = Counter()
    last_track: dict[str, int] = {}
    cooc: Counter = Counter()  # (gt id, track id) -> frames matched
    gt_frames: Counter = Counter()
    trk_frames: Counter = Counter()
    tracks_per_gt: dict[str, set[int]] = defaultdict(set)
    n_frames = 0
    for r in res.records:
        if not r.output or (scored is not None and not scored(r.t)):
            continue
        loc = src.locate(r.t)
        if loc is None:
            continue
        ci, fi = loc
        g = gts[ci][(gts[ci]["frame"] == fi) & gts[ci]["team"].isin(list(side_of))]
        gxy = r.mapper.to_pitch(foot_points(g, foot)) if len(g) else np.zeros((0, 2))
        gid = [f"{t}:{p}" for t, p in zip(g["team"], g["player"], strict=True)]
        gside = [side_of[t] for t in g["team"]]
        # score what the pipeline outputs: tracked detections that are not static objects
        idx = [j for j in range(len(r.boxes)) if r.track_ids[j] >= 0 and r.teams[j] != "static"]
        c["static"] += sum(1 for t in r.teams if t == "static")
        c["untracked"] += int((r.track_ids < 0).sum())
        xy = r.xy[idx] if idx else np.zeros((0, 2))
        teams = [r.teams[j] for j in idx]
        roles = [r.roles[j] for j in idx]
        tids = [int(r.track_ids[j]) for j in idx]
        md = match_distance(gxy, xy, match_m)
        n_frames += 1
        c["gt"] += len(g)
        c["det"] += len(idx)
        c["tp"] += md.tp
        c["det_referee"] += sum(1 for t in teams if t == "referee")
        c["tp_referee"] += sum(1 for _, j in md.pairs if teams[j] == "referee")
        for gi in gid:
            gt_frames[gi] += 1
        for tid in tids:
            trk_frames[tid] += 1
        for i, j in md.pairs:
            lab = teams[j]
            truth = gside[i]
            if lab in ("home", "away"):
                c["team_labelled"] += 1
                c["team_correct"] += int(lab == truth)
                c["gk_labelled"] += int(roles[j] == "goalkeeper")
                c["gk_correct"] += int(roles[j] == "goalkeeper" and lab == truth)
            matched_label[lab if lab in ("unknown", "referee") else
                          ("right team" if lab == truth else "wrong team")] += 1
            key, tid = gid[i], tids[j]
            if key in last_track and last_track[key] != tid:
                c["idsw"] += 1
            last_track[key] = tid
            cooc[(key, tid)] += 1
            tracks_per_gt[key].add(tid)
        for j in md.extra:
            unmatched_label[teams[j]] += 1
    # IDF1: one-to-one GT id <-> track id assignment maximising co-occurrence
    gids = sorted(gt_frames)
    tids = sorted(trk_frames)
    idtp = 0
    if gids and tids:
        gi = {k: n for n, k in enumerate(gids)}
        ti = {k: n for n, k in enumerate(tids)}
        M = np.zeros((len(gids), len(tids)))
        for (g_, t_), v in cooc.items():
            M[gi[g_], ti[t_]] = v
        r_, c_ = linear_sum_assignment(-M)
        idtp = int(M[r_, c_].sum())
    idf1 = 2 * idtp / max(sum(gt_frames.values()) + sum(trk_frames.values()), 1)
    fps = res.match.fps
    player_min = sum(gt_frames.values()) / fps / 60.0
    lengths = np.array(list(trk_frames.values()), float) / fps
    m_tot = max(sum(matched_label.values()), 1)
    u_tot = max(sum(unmatched_label.values()), 1)
    return {
        "frames": n_frames,
        "match_m": match_m,
        "detection": {
            "raw": prf(c["tp"], c["det"] - c["tp"], c["gt"] - c["tp"]),
            "referee_removed": prf(c["tp"] - c["tp_referee"],
                                   (c["det"] - c["det_referee"]) - (c["tp"] - c["tp_referee"]),
                                   c["gt"] - (c["tp"] - c["tp_referee"])),
            "det_per_frame": round(c["det"] / max(n_frames, 1), 2),
            "referee_labelled_per_frame": round(c["det_referee"] / max(n_frames, 1), 2),
            "unmatched_per_frame": round(sum(unmatched_label.values()) / max(n_frames, 1), 2),
            "static_objects_removed_per_frame": round(c["static"] / max(n_frames, 1), 2),
            "untracked_per_frame": round(c["untracked"] / max(n_frames, 1), 2),
        },
        "teams": {
            "accuracy_settled": round(c["team_correct"] / max(c["team_labelled"], 1), 4),
            "matched_players_by_label": {k: round(v / m_tot, 4)
                                         for k, v in matched_label.most_common()},
            "unknown_share": round(matched_label["unknown"] / m_tot, 4),
            "unmatched_by_label": {k: round(v / u_tot, 4)
                                   for k, v in unmatched_label.most_common()},
            "goalkeeper_labels_per_frame": round(c["gk_labelled"] / max(n_frames, 1), 2),
            "goalkeeper_team_correct": round(c["gk_correct"] / max(c["gk_labelled"], 1), 4),
        },
        "identity": {
            "id_switches": c["idsw"],
            "id_switches_per_player_minute": round(c["idsw"] / max(player_min, 1e-9), 3),
            "idf1": round(idf1, 4),
            "distinct_tracks": len(tids),
            "gt_players": len(gids),
            "tracks_per_gt_player": round(float(np.mean([len(v) for v in tracks_per_gt.values()]))
                                          if tracks_per_gt else 0.0, 2),
            "mean_track_length_s": round(float(lengths.mean()) if len(lengths) else 0.0, 1),
        },
        "timing_s": {k: round(v, 2) for k, v in res.timing.items()},
        "seconds_per_video_second": round(sum(res.timing.values()) / res.video_seconds, 3),
        "ms_per_tracked_frame": round(1000 * sum(res.timing.values()) / len(res.records), 1),
    }


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Tracking + team accuracy vs TeamTrack GT")
    ap.add_argument("--view", choices=["top", "side"], required=True)
    ap.add_argument("--track-fps", type=float, nargs="+", default=[2.0])
    ap.add_argument("--dev", action="store_true", help="dev clip only (tuning)")
    ap.add_argument("--set", default=None, choices=["eval2"],
                    help="second eval set (teamtrack.clip_sets), scored as one window")
    ap.add_argument("--start", type=float, default=None, help="limit the window (match s)")
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--tag", default="", help="suffix of the output files (with --save also "
                    "of the MatchState, so tagged runs never overwrite the official ones)")
    ap.add_argument("--cfg", action="append", default=[], metavar="KEY=VALUE",
                    help="config override for this run, e.g. "
                         "perception.self_calibration.static_objects=true")
    ap.add_argument("--whole-source", action="store_true",
                    help="run the pipeline over every clip (tracks continue across the dev/eval "
                         "boundary) but score only the selected clips")
    ap.add_argument("--save", action="store_true",
                    help="also write outputs/match_state_<view>_<fps>fps.json (+ .teams.json) "
                         "and outputs/debug_<view>_<fps>fps.mp4 for every tracking rate")
    args = ap.parse_args(argv)
    cfg = with_overrides(cfg, args.cfg)
    view = args.view
    try:
        lists = repo_path(cfg["teamtrack"]["clip_lists"])
        if args.set:
            clips = use = find_clips(view, cfg, [args.set])
            src = VideoSource(lists / f"teamtrack_{view}_{args.set}.clips.json")
        else:
            clips = find_clips(view, cfg)
            dev = set(cfg["detector"]["eval"]["dev_clips"])
            use = [c for c in clips if (c.stem in dev) == args.dev]
            src = VideoSource(lists / f"teamtrack_{view}.clips.json")
        if not use:
            raise DatasetError("no clips selected")
        gts = [load_gt(c.csv).boxes for c in clips]
    except (DatasetError, VideoError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    a = max(use[0].start_s, args.start or -1e9)
    b = min(use[-1].end_s, args.end or 1e9)
    ra, rb = (clips[0].start_s, clips[-1].end_s) if args.whole_source else (a, b)

    def scored(t: float) -> bool:
        return a - 1e-6 <= t < b
    match_m = float(cfg["tracking"]["eval"]["match_m"][view])
    results: dict[str, Any] = {}
    for tf in args.track_fps:
        print(f"== {view}, tracking at {tf:g} fps, run {ra:.0f}-{rb:.0f} s, scored {a:.0f}-"
              f"{b:.0f} s ({args.set or ('DEV' if args.dev else 'eval')})", flush=True)
        stem = (f"{view}_{args.set}_{tf:g}fps" if args.set else f"{view}_{tf:g}fps") + args.tag
        try:
            res = run(src.uri, view=view, start_s=ra, end_s=rb, track_fps=tf, cfg=cfg,
                      progress=True,
                      debug_video=repo_path(f"outputs/debug_{stem}.mp4") if args.save else None)
        except (VideoError, CalibrationError, DetectorError, PipelineError, ContractError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        r = score(res, cfg, view, src, gts, match_m, scored)
        results[f"{tf:g}"] = r
        if args.save:
            for f in write_outputs(res, repo_path(f"outputs/match_state_{stem}.json")):
                print(f"  -> {f}")
        d, t, i = r["detection"], r["teams"], r["identity"]
        print(f"  detection @{match_m:g} m: raw P {d['raw']['precision']:.3f} R "
              f"{d['raw']['recall']:.3f} | referee-labelled removed: P "
              f"{d['referee_removed']['precision']:.3f} R {d['referee_removed']['recall']:.3f}"
              f" | det/frame {d['det_per_frame']}, labelled referee/frame "
              f"{d['referee_labelled_per_frame']}, unmatched/frame {d['unmatched_per_frame']}")
        print(f"  teams: settled accuracy {t['accuracy_settled']:.3f}; matched players by label "
              f"{t['matched_players_by_label']}; unmatched detections by label "
              f"{t['unmatched_by_label']}; GK labels/frame {t['goalkeeper_labels_per_frame']} "
              f"(team right {t['goalkeeper_team_correct']:.2f})")
        print(f"  identity: {i['id_switches']} ID switches "
              f"({i['id_switches_per_player_minute']}/player-min), IDF1 {i['idf1']:.3f}, "
              f"{i['distinct_tracks']} tracks for {i['gt_players']} GT players "
              f"({i['tracks_per_gt_player']} per player), mean track {i['mean_track_length_s']} s")
        print("  " + res.timing_table().replace("\n", "\n  "), flush=True)
    out = repo_path(f"outputs/eval_second_set_tracking_{view}{args.tag}.json" if args.set else
                    f"outputs/eval_tracking_{view}{'_dev' if args.dev else ''}{args.tag}.json")
    old = json.loads(out.read_text(encoding="utf-8")).get("results", {}) if out.exists() else {}
    note = ("second eval set: never used for tuning, but NOT independent of the first eval "
            "set (same match, same camera, neighbouring minutes)") if args.set else None
    out.write_text(json.dumps({"view": view, "dev": args.dev, "set": args.set or
                               ("dev" if args.dev else "eval"), "note": note, "overrides": args.cfg,
                               "window": [a, b],
                               "run_window": [ra, rb],
                               "results": {**old, **results}}, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
