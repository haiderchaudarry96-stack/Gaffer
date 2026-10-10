# Data

Every file Gaffer reads, where it comes from, and under which licence. Videos are large and
gitignored; `scripts/download_teamtrack.py` (Phase 2) re-downloads exactly the files listed here.

## TeamTrack (real footage) — MIT licence

> Scott et al., *TeamTrack: A Dataset for Multi-Sport Multi-Object Tracking in Full-pitch
> Videos*, 2024. arXiv:2404.13868. *(Before submission: copy the full author list and venue
> from the arXiv page.)*

- Source: Kaggle dataset `atomscott/teamtrack` (uploaded by the dataset's first author),
  folders `teamtrack/soccer_top/test/` and `teamtrack/soccer_side/test/`.
- Licence: **MIT**. Use, modification and redistribution are allowed provided the copyright
  and permission notice are kept. *Before submission: paste the exact MIT notice from the
  dataset's LICENSE file here verbatim (it is not included in the files we downloaded).*
- Downloaded: 2026-10-09. Used for: perception evaluation (detection, team colours, tracking,
  homography), the oracle `MatchState` from ground-truth boxes, and the demo.
- Annotation CSVs: per-frame bounding boxes + TeamID + PlayerID (format in `docs/DATA_NOTES.md`).

| view | file stem (`videos/<stem>.mp4`, `annotations/<stem>.csv`) | clip time in name (s) | video |
|---|---|---|---|
| soccer_top (drone) | `D_20220220_1_1530_1560` | 1530–1560 | 3840×2160, 29.97 fps, 900 frames |
| soccer_top | `D_20220220_1_1560_1590` | 1560–1590 | same |
| soccer_top | `D_20220220_1_1590_1620` | 1590–1620 | same |
| soccer_top | `D_20220220_1_1620_1650` | 1620–1650 | same |
| soccer_top | `D_20220220_1_1650_1680` | 1650–1680 | same |
| soccer_top | `D_20220220_1_1680_1710` | 1680–1710 | same |
| soccer_top | `D_20220220_1_1710_1740` | 1710–1740 | same |
| soccer_top | `D_20220220_1_1740_1770` | 1740–1770 | same |
| soccer_top | `D_20220220_1_1770_1800` | 1770–1800 | same |
| soccer_side (fixed panorama) | `F_20220220_1_1680_1710` | 1680–1710 | 6500×1000, 25 fps, 750 frames |
| soccer_side | `F_20220220_1_1710_1740` | 1710–1740 | same |
| soccer_side | `F_20220220_1_1740_1770` | 1740–1770 | same |
| soccer_side | `F_20220220_1_1770_1800` | 1770–1800 | same |

Local layout: `data/teamtrack/<view>/{videos,annotations}/` (gitignored, ~270 MB of video).

Notes measured in Phase 2 (details in `docs/DATA_NOTES.md` and `docs/FAILURE_LOG.md`):
- Consecutive clips of one view are consecutive in time (player IDs continue across them).
- The top and side clips whose names share a time range are **not** simultaneous; the two
  views are used as independent footage.

### Multi-clip matches: `*.clips.json`

A match made of consecutive clips is described by a clip list instead of a re-encoded video
(convention in `docs/DATA_CONTRACT.md`, no schema change); `MatchState.source_video.uri` then
points to the list:

```json
{ "clips": [ { "path": "videos/D_20220220_1_1530_1560.mp4", "start_s": 1530.0 },
             { "path": "videos/D_20220220_1_1560_1590.mp4", "start_s": 1560.0 } ] }
```

Paths are relative to the list file; `start_s` is the clip's start in match seconds.

## Calibration (`data/calibration/`, ours, MIT)

- `top_points.json`, `side_points.json`: hand-picked pitch landmarks (pixel positions on one
  reference frame per view). Checked by eye on the overlay images.
- `top.json`, `side.json`: fitted image → pitch mappings written by `scripts/calibrate.py`
  (homography for the top view; the side model is chosen by held-out error,
  `side_model_comparison.json`).

## Synthetic matches (`data/synthetic/`, ours, MIT)

- `match_001.json` (gitignored, reproducible: `py scripts\make_synthetic_match.py`, seed 42)
  and `ground_truth.json`. Other matches are generated on the fly from their seed by
  `scripts/eval_synthetic.py` (held-out seeds 100–109 are the official evaluation set).

## Not used

Broadcast footage of any kind, SoccerNet, Alfheim, DFL — see `docs/DATA_SOURCES.md` for why.
