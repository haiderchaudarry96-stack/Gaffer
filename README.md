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
- **YOLOX-S ONNX**: OpenCV Model Zoo (`opencv/opencv_zoo`, `models/object_detection_yolox`), Apache 2.0.

See `docs/DATA_SOURCES.md` for every source and licence.

## Licence

MIT, see `LICENSE`.
