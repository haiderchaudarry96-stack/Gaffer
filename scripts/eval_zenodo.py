"""Perception on unseen drone footage: the Zenodo preview clip against its annotations.

Footage: Synowiec, Nowak, Kamola, "Soccer pitch top-view: how it can help in player location
accuracy estimation and improvement", Zenodo, DOI 10.5281/zenodo.14867795, CC BY 4.0
(`top-view-preview.mp4` + `annotations-top-view.zip` -> `top-view-1.csv`). A different ground,
turf, drone height, kit colours, and low sun with long shadows: nothing in Gaffer was built on it.

1. **Pitch**: OpenCV auto-detect on the frame at 1 s (`perception.pitch.detect_pitch_corners`,
   exactly as an upload), the 4-corner calibration saved to `zenodo.calibration_dir`. It is
   scored independently of the pipeline: a homography fitted (RANSAC) from detected player
   positions in the image to the annotated pitch positions gives the pitch corners as the
   dataset's authors placed them; the auto-detected corners' error against those, in metres.
2. **Pipeline**: `perception.pipeline.run` on the whole clip (config tracking / output rates).
3. **Scores**, every tracked frame inside a split (`zenodo.tune_s` = the first third, the only
   Zenodo frames settings may be chosen on; `zenodo.test_s` = the unseen rest):
   - detection precision / recall / F1 at 1 m and 2 m: what the pipeline outputs (tracked, not
     static) vs every annotated person (players, keepers, referee, officials/staff);
   - detections per frame, and how many lie outside the pitch lines (and > 1.5 m outside);
   - teams (annotated players and keepers matched within 1 m): share with a team label, and
     accuracy with the left/right <-> home/away naming fixed on the tune split;
   - formation coverage: output frames with >= `tactics.min_players` outfield players per team.

Annotation frame = video frame + `zenodo.frame_offset`; the annotation's y axis runs from the
top of the image, so the contract y (from the bottom) is 68 - y.

    py scripts\\eval_zenodo.py --tag before
    py scripts\\eval_zenodo.py --tag after --cfg perception.self_calibration.static_objects=true
    py scripts\\eval_zenodo.py --tag after --image 20.0     # annotated frame + 2D pitch at 20 s
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd

from gaffer.config import load_config, repo_path, with_overrides
from gaffer.evaluation import match_distance, prf
from gaffer.perception.pipeline import PipelineError, PipelineResult, run, write_outputs
from gaffer.perception.pitch import (
    Calibration,
    CalibrationError,
    PitchModel,
    detect_pitch_corners,
    four_corner_calibration,
    four_corner_homography,
)
from gaffer.perception.render import annotate_frame, compose, draw_minimap
from gaffer.perception.video import VideoError, VideoSource
from gaffer.tactics.common import TacticsConfig, extract_team_frames

PEOPLE = ("player", "goalkeeper", "referee", "other")


def load_annotations(path: Path, width_m: float) -> pd.DataFrame:
    """Annotations with contract coordinates (x along the length, y from the bottom)."""
    a = pd.read_csv(path)
    a["x"] = a["x_pos"].astype(float)
    a["y"] = width_m - a["y_pos"].astype(float)
    return a


def calibrate(cfg: dict[str, Any], video: Path, out_dir: Path, recalibrate: bool
              ) -> tuple[Calibration, dict[str, Any]]:
    """Auto-detected 4-corner calibration (the upload path's pitch step, confirmed)."""
    p = out_dir / "top.json"
    info_p = out_dir / "autodetect.json"
    if p.exists() and info_p.exists() and not recalibrate:
        return Calibration.load(p), json.loads(info_p.read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    idx = int(round(float(cfg["calibration"]["auto_detect"]["frame_t_s"]) * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise VideoError(f"could not read frame {idx} of {video}")
    d = detect_pitch_corners(frame, cfg)
    if d.corners is None:
        raise CalibrationError(f"pitch not found: {d.problems}")
    L, W = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])
    size = (frame.shape[1], frame.shape[0])
    fc = four_corner_homography(d.corners, size, L, W, cfg["calibration"]["four_corner"])
    cal = four_corner_calibration(fc, size, L, W, str(video), idx, "auto_confirmed", "top")
    out_dir.mkdir(parents=True, exist_ok=True)
    cal.save(p)
    info = d.summary()
    info_p.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return cal, info


def corner_check(res: PipelineResult, ann: pd.DataFrame, offset: int, fps_native: float,
                 cal: Calibration, L: float, W: float, window: tuple[float, float]
                 ) -> dict[str, Any]:
    """Auto-detected corners vs the corners implied by the annotations (module docstring).

    Detected player centres are brought into the calibration frame (inverse of each frame's
    re-anchoring) and matched to annotated positions within 1.5 m; a RANSAC homography from
    those image points to the annotated pitch positions maps the auto-detected image corners
    to where the annotation puts them."""
    from gaffer.perception.pitch import HomographyMapper

    H_cal = np.array(cal.params["H_image_to_pitch"])
    src, dst = [], []
    for r in res.records:
        if not (window[0] <= r.t < window[1]) or not len(r.boxes):
            continue
        g = ann[ann.frame_id == int(round(r.t * fps_native)) + offset]
        if not len(g):
            continue
        G = g[["x", "y"]].to_numpy(float)
        md = match_distance(G, r.xy, 1.5)
        uv = r.boxes[:, :2] + r.boxes[:, 2:] / 2
        # frame pixel -> reference pixel: H_frame = H_cal @ A, so ref = H_cal^-1 H_frame frame
        Hf = np.asarray(r.mapper.H)
        T = np.linalg.inv(H_cal) @ Hf
        for i, j in md.pairs:
            p = T @ np.array([uv[j, 0], uv[j, 1], 1.0])
            src.append(p[:2] / p[2])
            dst.append(G[i])
    if len(src) < 20:
        return {"pairs": len(src), "max_corner_error_m": None}
    Hgt, inl = cv2.findHomography(np.array(src, np.float32), np.array(dst, np.float32),
                                  cv2.RANSAC, 0.5)
    corners_img = HomographyMapper(H_cal).to_image(
        np.array([[0, 0], [L, 0], [L, W], [0, W]], float))
    gt_xy = HomographyMapper(Hgt).to_pitch(corners_img)
    err = np.linalg.norm(gt_xy - np.array([[0, 0], [L, 0], [L, W], [0, W]], float), axis=1)
    return {"pairs": len(src), "inliers": int(inl.sum()) if inl is not None else None,
            "corner_errors_m": [round(float(e), 2) for e in err],
            "max_corner_error_m": round(float(err.max()), 2),
            "correct_within_1m": bool(err.max() <= 1.0)}


def score(res: PipelineResult, ann: pd.DataFrame, cfg: dict[str, Any], offset: int,
          fps_native: float, window: tuple[float, float],
          naming: dict[str, str] | None) -> dict[str, Any]:
    """All metrics on the tracked frames inside `window` (video seconds)."""
    L, W = res.match.pitch.length_m, res.match.pitch.width_m
    c: Counter = Counter()
    team_pairs: Counter = Counter()  # (annotated team, pipeline label)
    gk_role: Counter = Counter()
    ref_lab: Counter = Counter()
    per_frame_pairs: list[list[tuple[str, str, str]]] = []  # (annotated team, label, role)
    n = 0
    for r in res.records:
        if not (window[0] <= r.t < window[1]):
            continue
        g = ann[(ann.frame_id == int(round(r.t * fps_native)) + offset) & ann.role.isin(PEOPLE)]
        if not len(g):
            continue
        n += 1
        idx = [j for j in range(len(r.boxes)) if r.track_ids[j] >= 0 and r.teams[j] != "static"]
        xy = r.xy[idx] if idx else np.zeros((0, 2))
        G = g[["x", "y"]].to_numpy(float)
        c["gt"] += len(G)
        c["det"] += len(idx)
        out = ((xy[:, 0] < 0) | (xy[:, 0] > L) | (xy[:, 1] < 0) | (xy[:, 1] > W)) if len(xy) \
            else np.zeros(0, bool)
        far = ((xy[:, 0] < -1.5) | (xy[:, 0] > L + 1.5) | (xy[:, 1] < -1.5)
               | (xy[:, 1] > W + 1.5)) if len(xy) else np.zeros(0, bool)
        c["outside"] += int(out.sum())
        c["outside_far"] += int(far.sum())
        for thr, key in ((1.0, "1m"), (2.0, "2m")):
            md = match_distance(G, xy, thr)
            c[f"tp_{key}"] += md.tp
            if key == "1m":
                roles = g["role"].to_numpy()
                teams = g["team"].fillna("").to_numpy()
                per_frame_pairs.append([(teams[i], r.teams[idx[jj]], r.roles[idx[jj]])
                                        for i, jj in md.pairs if roles[i] == "player"])
                for i, jj in md.pairs:
                    j = idx[jj]
                    if roles[i] in ("player", "goalkeeper"):
                        team_pairs[(teams[i], r.teams[j])] += 1
                    if roles[i] == "goalkeeper":
                        gk_role[r.roles[j]] += 1
                    if roles[i] == "referee":
                        ref_lab[r.teams[j]] += 1
                pl = (roles == "player") | (roles == "goalkeeper")
                c["gt_players"] += int(pl.sum())
                c["tp_players"] += sum(1 for i, _ in md.pairs if pl[i])
    labelled = sum(v for (t, lab), v in team_pairs.items() if lab in ("home", "away"))
    matched_players = sum(team_pairs.values())
    if naming is None:  # naming from this split (majority)
        votes = Counter()
        for (t, lab), v in team_pairs.items():
            if lab in ("home", "away") and t in ("left", "right"):
                votes[(t, lab)] += v
        a = votes[("left", "home")] + votes[("right", "away")]
        b = votes[("left", "away")] + votes[("right", "home")]
        naming = {"left": "home", "right": "away"} if a >= b else \
            {"left": "away", "right": "home"}
    correct = sum(v for (t, lab), v in team_pairs.items()
                  if lab in ("home", "away") and naming.get(t) == lab)
    # formation coverage on the MatchState frames in the window (what the engine sees)
    tcfg = TacticsConfig.from_config(cfg)
    tf = extract_team_frames(res.match, tcfg)
    cov = {}
    for s in ("home", "away"):
        fr = [f for f in tf[s] if window[0] <= f.t < window[1]]
        cov[s] = {"coverage": round(float(np.mean([len(f.outfield) >= tcfg.min_players
                                                   for f in fr])), 3) if fr else None,
                  "outfield_mean": round(float(np.mean([len(f.outfield) for f in fr])), 2)
                  if fr else None}
    # strict coverage: frames where >= min_players annotated outfield players of the team are
    # matched (1 m) to a detection carrying that team's label (false positives cannot help)
    true_cov = {}
    for side_ann in ("left", "right"):
        side = naming.get(side_ann)
        hits = [sum(1 for t, lab, role in fp if t == side_ann and lab == side
                    and role == "outfield") for fp in per_frame_pairs]
        true_cov[side] = {"coverage": round(float(np.mean([h >= tcfg.min_players
                                                           for h in hits])), 3)
                          if hits else None,
                          "correct_outfield_mean": round(float(np.mean(hits)), 2)
                          if hits else None}
    lab_counts = Counter()
    for (_, lab), v in team_pairs.items():
        lab_counts[lab] += v
    return {
        "frames": n, "window_s": list(window),
        "detection": {"1m": prf(c["tp_1m"], c["det"] - c["tp_1m"], c["gt"] - c["tp_1m"]),
                      "2m": prf(c["tp_2m"], c["det"] - c["tp_2m"], c["gt"] - c["tp_2m"]),
                      "recall_players_1m": round(c["tp_players"] / max(c["gt_players"], 1), 4)},
        "per_frame": {"detections": round(c["det"] / max(n, 1), 2),
                      "annotated_people": round(c["gt"] / max(n, 1), 2),
                      "outside_lines": round(c["outside"] / max(n, 1), 2),
                      "outside_1p5m": round(c["outside_far"] / max(n, 1), 2)},
        "teams": {"matched_players": matched_players,
                  "share_with_team_label": round(labelled / max(matched_players, 1), 4),
                  "labels": {k: round(v / max(matched_players, 1), 4)
                             for k, v in lab_counts.most_common()},
                  "accuracy": round(correct / max(labelled, 1), 4), "naming": naming,
                  "goalkeeper_roles": dict(gk_role), "referee_labels": dict(ref_lab)},
        "formation_coverage": cov,
        "formation_coverage_strict": true_cov,
    }


def snapshot(path: Path, res: PipelineResult, src: VideoSource, t: float, cfg: dict[str, Any],
             ann: pd.DataFrame, offset: int, title: str) -> Path:
    """Annotated frame (team-coloured boxes) above the 2D pitch, at the tracked frame nearest
    to `t`; annotated people drawn as hollow grey rings on the 2D pitch."""
    r = min(res.records, key=lambda x: abs(x.t - t))
    frame = src.read(r.t)
    dv = cfg["perception"]["debug_video"]
    colours = dv["colours_bgr"]
    idx = [j for j in range(len(r.boxes)) if r.teams[j] != "static"]
    img = annotate_frame(frame, r.boxes[idx], [r.teams[j] for j in idx],
                         [r.roles[j] for j in idx], r.track_ids[idx], colours, thickness=4)
    L, W = res.match.pitch.length_m, res.match.pitch.width_m
    model = PitchModel(L, W)
    players = [{"x": float(r.xy[j, 0]), "y": float(r.xy[j, 1]), "team": r.teams[j],
                "role": r.roles[j]} for j in idx if r.track_ids[j] >= 0]
    ppm = 6.0
    mm = draw_minimap(model, players, colours, ppm, None,
                      f"{title}  t={r.t:.1f}s  {len(players)} tracked people")
    g = ann[ann.frame_id == int(round(r.t * src.native_fps)) + offset]
    for x, y in g[["x", "y"]].to_numpy(float):
        cx, cy = int(round((x + 3) * ppm)), int(round((W - y + 3) * ppm))
        cv2.circle(mm, (cx, cy), int(1.6 * ppm), (190, 190, 190), 1, cv2.LINE_AA)
    out = compose(img, mm, 1600, f"Gaffer perception on unseen footage (Zenodo 14867795, CC BY "
                                  f"4.0) | {title} | grey rings = annotated people")
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tag", default="run")
    ap.add_argument("--cfg", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--recalibrate", action="store_true")
    ap.add_argument("--image", type=float, default=None, help="save a snapshot at this second")
    ap.add_argument("--image-out", default=None)
    ap.add_argument("--save", action="store_true", help="write the MatchState too")
    args = ap.parse_args(argv)
    cfg = with_overrides(load_config(), args.cfg)
    z = cfg["zenodo"]
    video = repo_path(z["video"])
    if not video.exists() or not repo_path(z["annotations"]).exists():
        print(f"ERROR: {video} or {z['annotations']} missing (data/README.md: Zenodo)",
              file=sys.stderr)
        return 2
    L, W = float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"])
    ann = load_annotations(repo_path(z["annotations"]), W)
    t0 = time.perf_counter()
    cal_dir = repo_path(z["calibration_dir"])
    try:
        cal, auto = calibrate(cfg, video, cal_dir, args.recalibrate)
    except (CalibrationError, VideoError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"pitch auto-detect: accepted={auto['accepted']} confidence={auto['confidence']} "
          f"line error {auto['line_error_m']} m")
    rcfg = with_overrides(cfg, [f"calibration.dir={cal_dir.as_posix()}"])
    try:
        res = run(video, view="top", cfg=rcfg, match_id=f"zenodo_preview_{args.tag}")
    except (VideoError, CalibrationError, PipelineError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    src = VideoSource(video)
    off = int(z["frame_offset"])
    tune = score(res, ann, cfg, off, src.native_fps, tuple(z["tune_s"]), None)
    test = score(res, ann, cfg, off, src.native_fps, tuple(z["test_s"]),
                 tune["teams"]["naming"])
    corners = corner_check(res, ann, off, src.native_fps, cal, L, W, tuple(z["tune_s"]))
    report = {"tag": args.tag, "overrides": args.cfg, "autodetect": auto,
              "autodetect_vs_annotations": corners, "selfcal": res.selfcal,
              "team_model": res.team_model.to_dict(),
              "timing_s": {k: round(v, 2) for k, v in res.timing.items()},
              "s_per_video_s": round(sum(res.timing.values()) / res.video_seconds, 2),
              "tune": tune, "test": test, "wall_s": round(time.perf_counter() - t0, 1)}
    out = repo_path(f"outputs/eval_zenodo_{args.tag}.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.save:
        write_outputs(res, repo_path(f"outputs/zenodo/match_state_{args.tag}.json"))
    for name, s in (("tune", tune), ("TEST", test)):
        d, pf, tm, cv = s["detection"], s["per_frame"], s["teams"], s["formation_coverage"]
        print(f"[{name} {s['window_s'][0]:g}-{s['window_s'][1]:g} s, {s['frames']} frames] "
              f"P/R/F1 @1m {d['1m']['precision']:.3f}/{d['1m']['recall']:.3f}/"
              f"{d['1m']['f1']:.3f} @2m {d['2m']['precision']:.3f}/{d['2m']['recall']:.3f}/"
              f"{d['2m']['f1']:.3f} | det/frame {pf['detections']} (annotated "
              f"{pf['annotated_people']}), outside lines {pf['outside_lines']}, >1.5 m "
              f"{pf['outside_1p5m']} | team label {tm['share_with_team_label']:.3f}, accuracy "
              f"{tm['accuracy']:.3f} | coverage home {cv['home']['coverage']} away "
              f"{cv['away']['coverage']}")
    print(f"auto-detect vs annotations: {corners}")
    print(f"self-calibration: {res.selfcal}")
    if args.image is not None:
        p = Path(args.image_out) if args.image_out else repo_path(
            f"outputs/zenodo/snapshot_{args.tag}_{args.image:g}s.png")
        print(f"-> {snapshot(p, res, src, args.image, cfg, ann, off, args.tag)}")
    print(f"wall {report['wall_s']} s -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
