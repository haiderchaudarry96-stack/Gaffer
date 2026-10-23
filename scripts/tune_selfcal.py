"""Detection-only sweep of the per-video self-calibration settings (`perception/selfcal.py`).

Tuning data only (the rule of the generalisation session, 23 Oct): the TeamTrack dev clip
(`detector.eval.dev_clips`, 1530-1560 s) and the first third of the Zenodo preview clip
(`zenodo.tune_s`, 0-10 s). Never the Zenodo test part, TeamTrack eval / eval2, or the demo
window. Frames are decoded and re-anchored once; each variant re-runs the classical detector
(with its own grass model learnt on the first frame) and the pitch mask, then scores detections
against the annotations at 1 m: precision, recall, F1, detections per frame. TeamTrack GT has
no referee / staff boxes (~4 real people per frame count as false positives there), so its
precision is compared between variants, not read as absolute.

    py scripts\\tune_selfcal.py --variant base: \\
        --variant sh:perception.self_calibration.shadows=true
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import numpy as np
import pandas as pd

from gaffer.config import load_config, repo_path, with_overrides
from gaffer.evaluation import match_distance, prf
from gaffer.perception.detector import _px_per_m, make_detector, painted_lines_mask
from gaffer.perception.drift import GeometryProvider
from gaffer.perception.pipeline import foot_xy
from gaffer.perception.pitch import Calibration, PitchModel
from gaffer.perception.selfcal import (
    GrassModelError,
    SelfCalSettings,
    estimate_grass,
    inside_pitch,
)
from gaffer.perception.team_classifier import (
    TeamClassifierError,
    TeamSettings,
    fit_team_model,
    shirt_features,
)
from gaffer.perception.video import VideoSource
from gaffer.teamtrack import find_clips, foot_points, load_gt


def _keepers(gt: np.ndarray, team: np.ndarray, length: float) -> np.ndarray:
    """TeamTrack GT has no keeper flag: per team, the player deepest at either end when inside
    a penalty area (they wear their own colours, so their crops count as 'other')."""
    k = np.zeros(len(gt), bool)
    for t in np.unique(team):
        idx = np.nonzero(team == t)[0]
        if not len(idx):
            continue
        for j in (idx[np.argmin(gt[idx, 0])], idx[np.argmax(gt[idx, 0])]):
            if gt[j, 0] < 16.5 or gt[j, 0] > length - 16.5:
                k[j] = True
    return k


def zenodo_frames(cfg: dict[str, Any], n: int) -> list[dict[str, Any]]:
    z = cfg["zenodo"]
    W = float(cfg["pitch"]["width_m"])
    zcfg = with_overrides(cfg, [f"calibration.dir={repo_path(z['calibration_dir']).as_posix()}"])
    cal = Calibration.load(repo_path(z["calibration_dir"]) / "top.json")
    geo = GeometryProvider(cal, zcfg, "top", PitchModel(cal.length_m, cal.width_m))
    ann = pd.read_csv(repo_path(z["annotations"]))
    src = VideoSource(repo_path(z["video"]))
    a, b = (float(v) for v in z["tune_s"])
    assert b <= float(z["test_s"][0]), "tuning frames must stay before the test part"
    out = []
    for t, _, fi, frame in src.frames(np.linspace(a, b - 0.5, n).round(3).tolist()):
        g = ann[ann.frame_id == fi + int(z["frame_offset"])]
        gt = np.stack([g.x_pos.to_numpy(float), W - g.y_pos.to_numpy(float)], 1)
        team = np.where(g.role.to_numpy() == "player", g.team.fillna("").to_numpy(), "other")
        out.append({"frame": frame, "mapper": geo.for_frame(frame).mapper, "gt": gt, "t": t,
                    "team": team})
    return out


def teamtrack_dev_frames(cfg: dict[str, Any], n: int) -> list[dict[str, Any]]:
    dev = set(cfg["detector"]["eval"]["dev_clips"])
    clip = [c for c in find_clips("top", cfg) if c.stem in dev][0]
    gt = load_gt(clip.csv).boxes
    cal = Calibration.for_view(cfg, "top")
    geo = GeometryProvider(cal, cfg, "top", PitchModel(cal.length_m, cal.width_m))
    src = VideoSource(clip.video, start_s=clip.start_s)
    out = []
    times = np.linspace(clip.start_s, clip.end_s - 0.5, n).round(3).tolist()
    for t, _, fi, frame in src.frames(times):
        m = geo.for_frame(frame).mapper
        g = gt[(gt["frame"] == fi) & gt["team"].isin(["0", "1"])]
        xy = m.to_pitch(foot_points(g, "centre"))
        team = g["team"].to_numpy().astype(object)
        team[_keepers(xy, team, cal.length_m)] = "other"
        out.append({"frame": frame, "mapper": m, "gt": xy, "t": t, "team": team})
    return out


def run_variant(cfg: dict[str, Any], frames: list[dict[str, Any]]) -> dict[str, Any]:
    model = PitchModel(float(cfg["pitch"]["length_m"]), float(cfg["pitch"]["width_m"]))
    det = make_detector(cfg, "top", model)
    sc = SelfCalSettings.from_config(cfg, "top")
    grass = None
    if sc.needs_grass:
        try:
            grass = estimate_grass(frames[0]["frame"], frames[0]["mapper"], model, sc.grass,
                                   sc.shadow)
        except GrassModelError:
            grass = None
    det.configure(sc, grass)
    ts = TeamSettings.from_config(cfg, "top")
    tp = nd = ng = 0
    feats, oks, truth = [], [], []
    for f in frames:
        d = det.detect(f["frame"], f["mapper"]).persons()
        xy = f["mapper"].to_pitch(foot_xy(d.boxes, "centre")) if len(d) else np.zeros((0, 2))
        boxes, ids = d.boxes, np.arange(len(d))
        if sc.pitch_mask and len(xy):
            keep = inside_pitch(xy, model.length, model.width, sc.pitch_mask_margin_m)
            xy, boxes, ids = xy[keep], boxes[keep], ids[keep]
        md = match_distance(f["gt"], xy, 1.0)
        tp, nd, ng = tp + md.tp, nd + len(xy), ng + len(f["gt"])
        exclude = None
        if sc.crop_exclude_lines and len(boxes):
            band = max(1, int(round(sc.crop_line_band_m * _px_per_m(f["mapper"], model))))
            exclude = painted_lines_mask(f["mapper"], model, f["frame"].shape[:2], band)
        include = (det.debug["owner"], det.scale) \
            if sc.crop_foreground and "owner" in det.debug else None
        fe, ok = shirt_features(f["frame"], boxes, ts, grass if sc.grass_model else None,
                                sc.shadows, exclude, include,
                                ids if include is not None else None)
        tr = np.full(len(boxes), "other", dtype=object)
        for i, j in md.pairs:
            tr[j] = f["team"][i]
        feats.append(fe)
        oks.append(ok)
        truth.append(tr)
    r = prf(tp, nd - tp, ng - tp)
    r["det_per_frame"] = round(nd / len(frames), 2)
    r["grass"] = grass.to_dict() if grass else None
    r["teams"] = team_score(np.concatenate(feats), np.concatenate(oks),
                            np.concatenate(truth), ts, cfg, sc)
    return r


def team_score(feats: np.ndarray, ok: np.ndarray, truth: np.ndarray, ts: TeamSettings,
               cfg: dict[str, Any], sc: SelfCalSettings) -> dict[str, Any]:
    """Fit the team model on every crop (as the pipeline does) and score it per crop: 3-class
    accuracy (team A / team B / other, best naming), share of player crops given a team, and
    accuracy among those."""
    hints = {s: cfg["perception"]["teams"][s]["shirt_hint"] for s in ("home", "away")}
    try:
        tm = fit_team_model(feats[ok], hints, ts, seed=42,
                            adaptive=sc.gate if sc.adaptive_gate else None)
    except TeamClassifierError:
        return {"error": "too few crops"}
    lab = np.full(len(feats), 2)
    lab[ok], _ = tm.classify(feats[ok])
    names = sorted({t for t in truth if t != "other"})
    best = None
    for perm in ((0, 1), (1, 0)):  # naming: which cluster is which annotated team
        m = {names[i]: perm[i] for i in range(min(2, len(names)))}
        want = np.array([m.get(t, 2) for t in truth])
        acc = float(np.mean(want == lab))
        if best is None or acc > best[0]:
            best = (acc, want)
    acc3, want = best
    pl = want < 2
    labelled = pl & (lab < 2)
    return {"acc3": round(acc3, 4), "player_team_share": round(float(labelled.sum())
                                                                / max(pl.sum(), 1), 4),
            "player_team_acc": round(float((lab[labelled] == want[labelled]).mean())
                                     if labelled.any() else 0.0, 4),
            "other_kept_out": round(float((lab[~pl] == 2).mean()) if (~pl).any() else 0.0, 4),
            "gates": tm.gates.round(2).tolist()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--variant", action="append", required=True,
                    help="name:KEY=VALUE,KEY=VALUE (empty after ':' = config as is)")
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--out", default="outputs/tune_selfcal.json")
    args = ap.parse_args(argv)
    base = load_config()
    print("decoding tuning frames ...", flush=True)
    data = {"teamtrack_dev": teamtrack_dev_frames(base, args.frames),
            "zenodo_tune": zenodo_frames(base, args.frames)}
    out = {}
    for v in args.variant:
        name, _, rest = v.partition(":")
        sets = [s for s in rest.split(",") if s]
        cfg = with_overrides(base, sets)
        res = {k: run_variant(cfg, fr) for k, fr in data.items()}
        out[name] = {"overrides": sets, **res}
        print(f"{name:24s} " + " | ".join(
            f"{k}: P {r['precision']:.3f} R {r['recall']:.3f} F1 {r['f1']:.3f} "
            f"det/f {r['det_per_frame']} team acc3 {r['teams'].get('acc3')} pl-share "
            f"{r['teams'].get('player_team_share')} pl-acc {r['teams'].get('player_team_acc')}"
            f" other-out {r['teams'].get('other_kept_out')}" for k, r in res.items()),
              flush=True)
    p = repo_path(args.out)
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    p.write_text(json.dumps({**old, **out}, indent=2), encoding="utf-8")
    print(f"-> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
