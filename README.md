# Gaffer

**An AI tactical analyst for football coaches.** Gaffer watches match video with **OpenCV 5**, works out each team's formation over time, spots the moment a team changes shape, and **checks its own eyes before it speaks**: an Amazon Bedrock agent sends OpenCV back to re-analyse each candidate change, then asks the coach to approve an alert backed by visual evidence.

Built for the **OpenCV AI Competition 2026, powered by AWS**.

> Status: Phase 1 done (synthetic data + tactics engine; data contract frozen at v1.0). See `docs/PLAN.md`.

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

- **TeamTrack**: Scott et al., *TeamTrack: A Dataset for Multi-Sport Multi-Object Tracking in Full-pitch Videos*, 2024 (arXiv 2404.13868). Kaggle `atomscott/teamtrack`, MIT licence. *(TODO before submission: paste the dataset's MIT copyright notice here verbatim.)*
- **YOLOX-S ONNX**: OpenCV Model Zoo (`opencv/opencv_zoo`, `models/object_detection_yolox`), Apache 2.0.

See `docs/DATA_SOURCES.md` for every source and licence.

## Licence

MIT, see `LICENSE`.
