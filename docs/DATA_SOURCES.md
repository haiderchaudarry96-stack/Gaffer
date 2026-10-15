# Data, Models and Licences

Use only footage and models whose terms permit this use, and record every one here and in `data/README.md`. **Verify every line yourself before submitting.**

---

## 1. Libraries and licences

| Need | Use | Licence |
|---|---|---|
| Computer vision, DNN inference, fisheye, homography, optical flow, clustering, drawing | **OpenCV 5** (`opencv-contrib-python`, headless on server) | Apache 2.0 |
| Tracking (ByteTrack) | **supervision** 0.30.9 (Roboflow) | MIT. Pulls in `av` (PyAV, BSD-3; its wheels ship **FFmpeg under LGPL**, dynamically linked, unmodified by us — compatible with an MIT repo), `requests` (Apache 2.0), `tqdm` (MPL-2.0 / MIT), `certifi` (MPL-2.0, unmodified), `defusedxml` (PSF), `pyDeprecate` (Apache 2.0). Checked 2026-10-10; no `opencv-python` dependency, so it does not clash with OpenCV 5 |
| Numerics, clustering, metrics, CSV | numpy, scipy, scikit-learn, pandas | BSD |
| AWS + Bedrock | boto3 | Apache 2.0 |
| API | FastAPI, pydantic, uvicorn | MIT / BSD |
| Dataset download (Phase 2) | kaggle / kagglehub | Apache 2.0 |
| Bird's-eye checks, homography, fisheye comparison | OpenCV 5 (`cv2.findHomography`, `cv2.fisheye`, `cv2.ximgproc.thinning`) | Apache 2.0 |
| Frontend | React, Vite, Tailwind CSS, Motion, Lenis, Lucide | MIT / ISC |
| Fonts | Space Grotesk, Inter, JetBrains Mono | SIL OFL |

**No Ultralytics YOLO** (AGPL-3.0) — neither the library nor weights trained with it. Many football models on Roboflow Universe were trained with Ultralytics; their weights carry the same problem.

---

## 2. Detector model (runs in `cv2.dnn`)

| Option | Where | Licence | Notes |
|---|---|---|---|
| **YOLOX (default)** — ONNX from the **OpenCV Model Zoo** | `github.com/opencv/opencv_zoo` → `models/object_detection_yolox` | Apache 2.0 (verified 2026-10-09: `LICENSE` in the model folder) | COCO `person` (+ `sports ball`). File `object_detection_yolox_2022nov.onnx` (YOLOX-S, 35.9 MB). Loads and runs in `cv2.dnn` under OpenCV 5.0.0. |
| YOLOX fine-tuned on TeamTrack (stretch) | Official YOLOX repo + TeamTrack train split, export ONNX | Apache 2.0 + MIT | Only if small/far players are badly missed. |
| RF-DETR (fallback) | Roboflow, ONNX export | Apache 2.0 | May need onnxruntime instead of `cv2.dnn`. |

---

## 3. Footage — decided

### ✅ Main: TeamTrack (MIT)

| | |
|---|---|
| Source | Kaggle `atomscott/teamtrack` (uploaded by the dataset's first author) |
| Paper | Scott et al., *TeamTrack: A Dataset for Multi-Sport Multi-Object Tracking in Full-pitch Videos*, 2024 (arXiv 2404.13868) |
| Licence | **MIT** — use, modify, redistribute, commercial use allowed; keep the copyright + licence notice |
| What we use | `teamtrack/teamtrack/soccer_top/test/` (drone, top-down) and `soccer_side/test/` (fixed fisheye side view): videos + annotation CSVs |
| Clip length | ~30 s per file, consecutive files = consecutive segments |
| Annotations | Per frame: bounding box (`bb_left`, `bb_top`, `bb_width`, `bb_height`) + `TeamID` + `PlayerID` for every player |
| Local path | `data/teamtrack/soccer_top/{videos,annotations}`, `data/teamtrack/soccer_side/{videos,annotations}` |
| Not used | basketball, handball, soccer train/val splits and side test clips 1800–1980 s (listed by `scripts/download_teamtrack.py --list`; not downloaded, see data/README.md) |

Why it fits: amateur university match, full pitch visible, a **fixed side camera any club could install** (real-world impact), and **ground truth** to measure detection, team classification and formations honestly.

### ⚙️ Hard mode (optional): Bil Kleb YouTube clip (CC BY)

| | |
|---|---|
| Title | 2019-11-10: U13 CCL VLSC vs SOCA |
| URL | `https://www.youtube.com/watch?v=3vxIlarKxjw` |
| Licence | Creative Commons Attribution (reuse allowed) — screenshot saved |
| Camera | Elevated, **pans and zooms** to follow the ball |
| Status | Original file requested from the owner. Do not use a ripped copy — YouTube's terms forbid third-party downloaders even for CC videos. |
| Care | U13 players: no identification, no face close-ups, anonymous dots only |
| Used so far | Looked at by eye at 0:05 / 0:40 / 1:30 for the pan/zoom limitation (FAILURE_LOG 2026-10-15, described in words only). A local copy downloaded by the user for this test lives in the gitignored `outputs/_peek/`: **never commit or redistribute frames** (minors; the original file is not held). |

### ❌ Considered and rejected

| Source | Why not |
|---|---|
| World Cup / league broadcasts, highlights | Copyright — never |
| DFL Bundesliga Data Shootout (Kaggle) | Broadcast footage under competition-specific rules |
| SoccerNet | Research-only agreement (NDA) |
| Alfheim (Simula) | Non-commercial research only; this competition has cash prizes |
| SoccerTrack v2 | Not publicly downloadable yet |
| Roboflow Universe | Mostly image datasets; many models Ultralytics-trained |

### Optional: own futsal footage
Unlikely, but supported: pitch size and formation templates live in `config.yaml`.

---

## 4. The record (goes into the report and README)

| Asset | Source | Licence | Date | Used for |
|---|---|---|---|---|
| TeamTrack soccer_top test clips + CSVs | Kaggle atomscott/teamtrack | MIT | 2026-10-09 | main demo, detection/team/formation eval |
| TeamTrack soccer_side test clips + CSVs | Kaggle atomscott/teamtrack | MIT | 2026-10-09 | fisheye side view, real-world camera |
| Bil Kleb U13 clip | YouTube 3vxIlarKxjw | CC BY | pending file | pan/zoom stress test |
| YOLOX-S ONNX (`object_detection_yolox_2022nov.onnx`) | OpenCV Model Zoo | Apache 2.0 (verified) | 2026-10-09 | `perception/detector.py` |
| Bedrock Amazon Nova 2 Lite (`global.amazon.nova-2-lite-v1:0`), fallback Nova Micro (`apac.amazon.nova-micro-v1:0`) | Amazon Bedrock, ap-southeast-2 | AWS service / model terms | 2026-10-09 | agent reasoning |
| Synthetic match data | generated by this repo | MIT (ours) | — | Phases 1–3, evaluation |
| Pitch calibration landmarks (`data/calibration/`) | picked on TeamTrack frames by this repo | MIT (ours) | 2026-10-10 | image → pitch mapping |

State plainly in the report which results come from TeamTrack, which from synthetic data, and which from the hard-mode clip.

---

## 5. Pre-submission check

- [ ] No AGPL library or Ultralytics-trained weights anywhere
- [ ] TeamTrack MIT notice + paper citation in README and report
- [ ] CC BY attribution for the Bil Kleb clip (if used)
- [ ] No broadcast footage anywhere, including the video
- [ ] Demo video music royalty-free or absent
- [ ] Videos and weights gitignored; `scripts/download_teamtrack.py` reproduces them; S3 holds the deployed copies
