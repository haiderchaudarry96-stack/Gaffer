# Data

Every file Gaffer reads, where it comes from, and under which licence. Videos are large and
gitignored; `scripts/download_teamtrack.py` re-downloads exactly the files listed here and
checks their size and SHA-256 against `data/teamtrack_manifest.json` (committed).

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

Local layout: `data/teamtrack/<view>/{videos,annotations}/` (gitignored; 140 files, 1,887 MB
including the CSVs).

**Second eval set (15 Oct):** the user downloaded 15 more clips **by hand** from the same Kaggle
dataset: drone `D_20220220_1_1260_1290` … `D_20220220_1_1500_1530` (`soccer_top/val`) and side
`F_20220220_1_1800_1830` … `F_20220220_1_1950_1980` (`soccer_side/test`). They are in the
manifest with a note, and form `teamtrack.clip_sets.<view>.eval2`: never used for tuning, but
**not independent** of the first eval set (same match, cameras and teams, neighbouring minutes;
`docs/DATA_NOTES.md` section 10). Same MIT licence and citation as above.

**Drone train clips (16 Oct):** the user downloaded the 42 drone clips `D_20220220_1_0000_0030`
… `D_20220220_1_1230_1260` (`soccer_top/train`) **by hand** from the same Kaggle dataset, so the
drone view now covers 0–1800 s of the first half (`teamtrack.clip_sets.top.train`, manifest
entries with a note; `docs/DATA_NOTES.md` section 11). Used only for the oracle search for
sustained formation changes and the Phase 3 real-footage demonstration windows, never for tuning.
Same MIT licence and citation.

### Re-downloading and verifying

```powershell
py scripts\download_teamtrack.py --check   # verify the local files (size + SHA-256), no network
py scripts\download_teamtrack.py           # download whatever is missing or wrong, then verify
py scripts\download_teamtrack.py --list    # what else the dataset has (anonymous)
```

Kaggle refuses anonymous downloads, so downloading needs a free Kaggle API token
(kaggle.com -> Settings -> API): environment variables `KAGGLE_USERNAME` / `KAGGLE_KEY`, or
`~/.kaggle/kaggle.json`. The token is only sent to kaggle.com. Files come from
`teamtrack/teamtrack/soccer_{top,side}/test/{videos,annotations}/` in the dataset; the manifest
lists every path, size and checksum (sizes match Kaggle's own listing, checked 15 Oct).

### Other soccer clips on Kaggle (not downloaded)

Listed with `--list` on 15 Oct 2026. All soccer clips come from one match day (20 Feb 2022,
first half), except 30 side-view train clips named `F_20200220_1_*`.

| view / split | clips | match time | size | local |
|---|---|---|---|---|
| soccer_top / test | 9 | 1530–1800 s | 254 MB | **all 9** |
| soccer_top / val | 9 | 1260–1530 s | 252 MB | **all 9** (by hand, 15 Oct) |
| soccer_top / train | 42 | 0–1260 s | 1,287 MB | **all 42** (by hand, 16 Oct) |
| soccer_side / test | 10 | 1680–1980 s | 94 MB | **all 10** (1800–1980 s by hand, 15 Oct) |
| soccer_side / val | 10 | 1380–1680 s | 94 MB | 0 |
| soccer_side / train | 46 | 0–1380 s (+ `F_20200220`) | 421 MB | 0 |

Not downloaded: the side train/val clips.

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
