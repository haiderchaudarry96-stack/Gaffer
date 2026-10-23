# Gaffer

**An AI tactical analyst for football coaches.** Gaffer watches match video with **OpenCV 5**, works out each team's formation over time, spots the moment a team changes shape, and **checks its own eyes before it speaks**: an Amazon Bedrock agent sends OpenCV back to re-analyse each candidate change, then asks the coach to approve an alert backed by visual evidence.

Built for the **OpenCV AI Competition 2026, powered by AWS**.

> Status (22 Oct 2026): Phases 0–3 done; Phase 4 runs locally as one app (FastAPI + React) with the coach workflow (recorded TeamTrack replay, Bedrock posture read, conditional role advice). **AWS deployment (EC2 / S3 / CloudWatch) is not done yet.** The real footage is one TeamTrack match; accuracy numbers come from synthetic matches. See `docs/PLAN.md`.

## Read next

- [`docs/PLAN.md`](docs/PLAN.md): phases, acceptance criteria and what is ticked (with evidence).
- [`docs/AGENT_DESIGN.md`](docs/AGENT_DESIGN.md): the self-verifying agent, its OpenCV tools, rules and measured results; [`docs/AGENT_TRACE_EXAMPLES.md`](docs/AGENT_TRACE_EXAMPLES.md): real traces.
- [`docs/FAILURE_LOG.md`](docs/FAILURE_LOG.md): every failure case and limitation found, as it happened.
- [`docs/API.md`](docs/API.md), [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md), [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).
- Session notes for the build (not needed to judge): [`docs/dev/`](docs/dev/) and [`RECORD.md`](RECORD.md).

## Quickstart (Windows, CPU only)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.lock
pip install -e . --no-deps
copy .env.example .env               # profile + region only; never keys

py scripts\smoke_test_opencv.py      # prints cv2.__version__ (5.x), runs YOLOX via cv2.dnn
py scripts\inspect_data.py           # TeamTrack EDA -> docs\DATA_NOTES.md, outputs\eda\
py scripts\smoke_test_bedrock.py     # Bedrock Converse: plain call + tool calling
py scripts\make_synthetic_match.py  # synthetic 90-min match + ground truth (seed 42)
py scripts\eval_synthetic.py        # formation accuracy + shape-change hits/misses/FPs
pytest -q ; ruff check .

# the app: one server for the site + API (http://localhost:8000/app)
cd web; npm ci; $env:VITE_API_URL="/"; npm run build; cd ..   # PowerShell (Git Bash rewrites "/")
uvicorn gaffer.api.main:app
py scripts\make_sample_clip.py       # optional: the "Try it with a sample clip" video
```

AWS credentials come from `aws configure` (laptop) or the IAM instance role (EC2). Region `ap-southeast-2`, model `global.amazon.nova-2-lite-v1:0` (fallback `apac.amazon.nova-micro-v1:0`), both set in `config.yaml`.

## Stack so far

| Piece | Where |
|---|---|
| OpenCV 5.0.0 (`opencv-contrib-python`) | `cv2.dnn` YOLOX inference, video I/O, EDA (phase correlation, line masks, heat-maps) |
| Amazon Bedrock (Converse API, Nova 2 Lite) | `src/gaffer/llm/bedrock_client.py` |
| Tactics engine (numpy, SciPy Hungarian assignment) | `src/gaffer/tactics/`: formation templates, change detector, metrics, timeline |
| Config | `config.yaml` (every threshold, model id, region) |

## Known limitations (measured)

- **Top-down footage only.** The drone/overhead view is the supported camera; pan/zoom broadcast-style cameras are refused, the fixed side camera is experimental (its alerts are capped at "uncertain").
- **Generalisation beyond TeamTrack is measured on one 30 s clip of one other ground.** On the unseen Zenodo drone clip (low sun, long shadows, light poles, staff by the touchlines) the per-video self-calibration lifts detection F1 from 0.57 to 0.86 (precision 0.40 → 0.77, recall 1.00 → 0.97, at 1 m) and players given a team from 41 % to 95 % (team accuracy 98 %), with settings chosen only on TeamTrack dev frames and the clip's first 10 s. Still about 6 false detections per frame remain, mostly staff within 1 m of the touchline and painted-line junctions; one pitch corner is 1.7 m off against the annotation-implied corners. TeamTrack holds (detection F1 0.912 → 0.918 / 0.922 → 0.930 on the two eval sets, team accuracy 98.4 % / 98.8 %), at ~18 % more processing time (0.99 → 1.17 s per video second on the laptop).
- **Set pieces blur formations.** During free kicks and corners players crowd into walls; the detector sees 6–8 of a team's 10 outfield players and the shape read in those 30 s windows can flip. The demo's 16:30 change (White 4-4-2 → 3-4-3) follows a free kick: the 6-minute upload now finds and confirms it too, but reads the shape before it as 4-2-3-1 (`docs/FAILURE_LOG.md`, 23 Oct).
- **No ball on the drone view**, so no possession or pressing metrics there.

## Data and credits

- **TeamTrack** (all real footage, and the ground truth used for evaluation only): Scott et al., *TeamTrack: A Dataset for Multi-Sport Multi-Object Tracking in Full-pitch Videos*, 2024, [arXiv:2404.13868](https://arxiv.org/abs/2404.13868). Kaggle `atomscott/teamtrack`, MIT licence. Notice, verbatim from the TeamTrack repository's `LICENSE` (github.com/AtomScott/TeamTrack):

  > MIT License
  >
  > Copyright (c) 2023 Atom Scott
  >
  > Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
  >
  > The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
  >
  > THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
- **Unseen-ground test footage**: Kamil Synowiec, Michał Nowak, Mariusz Kamola, *Soccer pitch top-view: how it can help in player location accuracy estimation and improvement*, Zenodo, 2025, [DOI 10.5281/zenodo.14867795](https://doi.org/10.5281/zenodo.14867795), CC BY 4.0 (preview clip and its annotations, evaluation only; not redistributed).
- **YOLOX-S ONNX**: OpenCV Model Zoo (`opencv/opencv_zoo`, `models/object_detection_yolox`), Apache 2.0.

See `docs/DATA_SOURCES.md` for every source and licence.

## Licence

MIT, see `LICENSE`.
