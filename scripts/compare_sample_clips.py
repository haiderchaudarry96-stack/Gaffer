"""Compare analyses of the same sample clip in different encodings (24 Oct).

Each `--run LABEL=DIR` is an `upload_check.py --perception-only` output directory; `--video
LABEL=PATH` gives that run's file (size, frame count). The first run is the reference. Writes
`outputs/sample_clip_reencode.json`: file size, pitch detection and pixels per metre, the
formation the tactics engine reads, players per frame, team-label counts, and the median
position difference to the reference (detections within 2 m).

    py scripts/compare_sample_clips.py \
        --run old=outputs/upload_check/sample_old --video old=data/sample_clips/old.mp4 \
        --run new=outputs/upload_check/sample_new --video new=data/sample_clips/new.mp4
"""

from __future__ import annotations

import argparse
import glob
import json

import cv2
import numpy as np
from scipy.spatial import cKDTree

from gaffer.config import load_config, repo_path
from gaffer.schema import load_match_state
from gaffer.tactics.common import TacticsConfig
from gaffer.tactics.timeline import build_timeline


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="append", required=True, metavar="LABEL=DIR")
    ap.add_argument("--video", action="append", required=True, metavar="LABEL=PATH")
    ap.add_argument("--out", default="outputs/sample_clip_reencode.json")
    a = ap.parse_args()
    cfg = load_config()
    videos = dict(v.split("=", 1) for v in a.video)
    rows: dict[str, dict] = {}
    states = {}
    for r in a.run:
        label, d = r.split("=", 1)
        check = json.loads((repo_path(d) / "upload_check.json").read_text(encoding="utf-8"))
        corners = np.array(check["pitch_detection"]["corners"])
        top, bottom = corners[1] - corners[0], corners[2] - corners[3]
        width_px = (np.linalg.norm(top) + np.linalg.norm(bottom)) / 2
        m = load_match_state(glob.glob(str(repo_path(d) / "api" / "*" / "match_state.json"))[0])
        seg = build_timeline(m, TacticsConfig.from_config(cfg)).timeline.segments[0]
        teams: dict[str, int] = {}
        for f in m.frames:
            for p in f.players:
                teams[p.team] = teams.get(p.team, 0) + 1
        cap = cv2.VideoCapture(str(repo_path(videos[label])))
        rows[label] = {
            "bytes": repo_path(videos[label]).stat().st_size,
            "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            "pitch_confidence": check["pitch_detection"]["confidence"],
            "pitch_line_error_m": check["pitch_detection"]["line_error_m"],
            "px_per_m": round(float(width_px) / cfg["pitch"]["length_m"], 2),
            "home": {"formation": seg.home.formation, "confidence": seg.home.confidence},
            "away": {"formation": seg.away.formation, "confidence": seg.away.confidence},
            "players_visible_mean": seg.players_visible_mean,
            "candidates": len(check["candidates"]),
            "label_counts": teams,
        }
        cap.release()
        states[label] = m
    ref = next(iter(states))
    for label, m in states.items():
        if label == ref:
            continue
        diffs, unmatched, total = [], 0, 0
        for fa, fb in zip(states[ref].frames, m.frames, strict=False):
            pa = np.array([[p.x, p.y] for p in fa.players])
            pb = np.array([[p.x, p.y] for p in fb.players])
            if len(pa) == 0 or len(pb) == 0:
                continue
            dd, _ = cKDTree(pb).query(pa)
            diffs += list(dd[dd < 2])
            unmatched += int((dd >= 2).sum())
            total += len(pa)
        rows[label]["vs_reference"] = {
            "reference": ref,
            "median_position_diff_m": round(float(np.median(diffs)), 3),
            "reference_detections_without_partner_share": round(unmatched / total, 3),
        }
    out = repo_path(a.out)
    out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
