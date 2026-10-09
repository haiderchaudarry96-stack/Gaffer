"""Phase 0 smoke test: prove OpenCV 5 + cv2.dnn can run YOLOX on a TeamTrack frame.

Steps:
1. Print `cv2.__version__` and fail clearly if it is not 5.x.
2. Download the YOLOX-S ONNX model from the OpenCV Model Zoo into `models/` (once).
3. Read one frame from a TeamTrack video with `cv2.VideoCapture`.
4. Run YOLOX through `cv2.dnn` twice: on the whole frame letterboxed to 640x640, and on a
   native-resolution 640x640 crop (players are tiny in 4K / 6500 px frames, so the two
   numbers show how much input resolution matters for Phase 2).
5. Apply NMS (`cv2.dnn.NMSBoxesBatched`), draw boxes, save to `outputs/`, print timings.

Usage:
    py scripts\\smoke_test_opencv.py [--source VIDEO] [--frame N] [--crop-center X Y]
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gaffer.config import load_config, repo_path  # noqa: E402

COCO_NAMES = {0: "person", 32: "ball"}


def check_opencv_version() -> None:
    """Exit with a clear message unless OpenCV 5.x is installed."""
    print(f"cv2.__version__ = {cv2.__version__}")
    if not cv2.__version__.startswith("5."):
        sys.exit(
            f"ERROR: OpenCV 5.x required, found {cv2.__version__}. "
            'Run: pip install "opencv-contrib-python>=5.0,<6"'
        )


def ensure_model(url: str, path: Path) -> Path:
    """Download the ONNX model if it is not already present."""
    if path.exists() and path.stat().st_size > 1_000_000:
        print(f"model: {path} ({path.stat().st_size / 1e6:.1f} MB, cached)")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading model from {url} ...")
    tmp = path.with_suffix(".part")
    try:
        urllib.request.urlretrieve(url, tmp)
    except OSError as exc:
        sys.exit(f"ERROR: could not download the YOLOX model ({exc}). Check your connection.")
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink()
        sys.exit("ERROR: downloaded model is too small — probably a Git LFS pointer, not weights.")
    tmp.replace(path)
    print(f"model: {path} ({path.stat().st_size / 1e6:.1f} MB, downloaded)")
    return path


class YoloxDnn:
    """Minimal YOLOX-S runner on cv2.dnn (pre/post-processing as in the OpenCV Model Zoo)."""

    def __init__(self, model_path: Path, input_size: int, strides: list[int]) -> None:
        try:
            self.net = cv2.dnn.readNet(str(model_path))
        except cv2.error as exc:
            sys.exit(f"ERROR: cv2.dnn could not load {model_path} under OpenCV "
                     f"{cv2.__version__}:\n{exc}")
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.size = input_size
        grids, exp_strides = [], []
        for s in strides:
            n = input_size // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            exp_strides.append(np.full((n * n, 1), s))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(exp_strides).astype(np.float32)

    def detect(self, bgr: np.ndarray, conf: float, nms: float, keep_classes: set[int]
               ) -> tuple[list[tuple[int, int, int, int, float, int]], float]:
        """Return (detections as (x, y, w, h, score, class_id) in image pixels, inference ms)."""
        h, w = bgr.shape[:2]
        ratio = min(self.size / h, self.size / w)
        resized = cv2.resize(bgr, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        # Model Zoo YOLOX expects RGB, 0-255 float, NCHW, no normalisation.
        blob = cv2.dnn.blobFromImage(canvas, 1.0, swapRB=True, ddepth=cv2.CV_32F)
        self.net.setInput(blob)
        t0 = time.perf_counter()
        out = self.net.forward()
        infer_ms = (time.perf_counter() - t0) * 1000

        dets = out.reshape(-1, out.shape[-1]).copy()
        dets[:, :2] = (dets[:, :2] + self.grids) * self.strides
        dets[:, 2:4] = np.exp(dets[:, 2:4]) * self.strides
        scores_all = dets[:, 4:5] * dets[:, 5:]
        cls = scores_all.argmax(1)
        score = scores_all.max(1)
        mask = (score >= conf) & np.isin(cls, list(keep_classes))
        if not mask.any():
            return [], infer_ms
        d, cls, score = dets[mask], cls[mask], score[mask]
        xywh = np.stack([d[:, 0] - d[:, 2] / 2, d[:, 1] - d[:, 3] / 2, d[:, 2], d[:, 3]], 1)
        keep = cv2.dnn.NMSBoxesBatched(xywh.tolist(), score.tolist(), cls.tolist(), conf, nms)
        results = []
        for i in np.array(keep).flatten():
            x, y, bw, bh = (xywh[i] / ratio).tolist()
            results.append((int(x), int(y), int(bw), int(bh), float(score[i]), int(cls[i])))
        return results, infer_ms


def draw(img: np.ndarray, dets: list, thickness: int) -> np.ndarray:
    """Draw detection boxes with class and score labels."""
    out = img.copy()
    for x, y, w, h, s, c in dets:
        colour = (0, 255, 0) if c == 0 else (0, 220, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), colour, thickness)
        cv2.putText(out, f"{COCO_NAMES.get(c, c)} {s:.2f}", (x, max(12, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4 * thickness, colour, max(1, thickness // 2))
    return out


def read_frame(video: Path, index: int) -> np.ndarray:
    """Read one frame from a video, with a clear error if it cannot be read."""
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"ERROR: OpenCV cannot open {video}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"ERROR: could not read frame {index} of {video}")
    return frame


def time_runs(model: YoloxDnn, img: np.ndarray, conf: float, nms: float, keep: set[int],
              runs: int = 3) -> tuple[list, float]:
    """Warm up once, then return detections and mean inference time over `runs`."""
    model.detect(img, conf, nms, keep)
    times = []
    for _ in range(runs):
        dets, ms = model.detect(img, conf, nms, keep)
        times.append(ms)
    return dets, float(np.mean(times))


def run_on_frame(model: YoloxDnn, frame: np.ndarray, tag: str, cfg: dict,
                 crop_center: tuple[int, int] | None) -> int:
    """Detect on the full frame and on a native crop; save images; return persons found."""
    dcfg = cfg["detector"]
    keep = set(dcfg["classes_of_interest"].values())
    conf, nms, s = dcfg["conf_threshold"], dcfg["nms_threshold"], dcfg["input_size"]
    h, w = frame.shape[:2]
    out_dir = repo_path(cfg["paths"]["outputs"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) whole frame, letterboxed to 640
    dets_full, ms_full = time_runs(model, frame, conf, nms, keep)
    n_full = sum(1 for d in dets_full if d[5] == 0)
    full_path = out_dir / f"smoke_opencv_{tag}_full.jpg"
    cv2.imwrite(str(full_path), draw(frame, dets_full, thickness=max(2, w // 800)))

    # 2) native-resolution crop
    cx, cy = crop_center or (w // 2, h // 2)
    x0 = int(np.clip(cx - s // 2, 0, w - s))
    y0 = int(np.clip(cy - s // 2, 0, h - s))
    crop = frame[y0:y0 + s, x0:x0 + s]
    dets_crop, ms_crop = time_runs(model, crop, conf, nms, keep)
    n_crop = sum(1 for d in dets_crop if d[5] == 0)
    crop_path = out_dir / f"smoke_opencv_{tag}_crop.jpg"
    cv2.imwrite(str(crop_path), draw(crop, dets_crop, thickness=1))

    print(f"{tag:<6}{f'full {w}x{h} -> {s}x{s}':<32}{n_full:>8}"
          f"{len(dets_full) - n_full:>7}{ms_full:>10.1f}")
    print(f"{tag:<6}{f'native crop {s}x{s} @({x0},{y0})':<32}{n_crop:>8}"
          f"{len(dets_crop) - n_crop:>7}{ms_crop:>10.1f}")
    return n_full + n_crop


def main() -> None:
    """Run the smoke test on one frame of each TeamTrack view (or on --source)."""
    cfg = load_config()
    dcfg = cfg["detector"]
    tt = repo_path(cfg["paths"]["teamtrack"])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, help="video to test (default: one top + one side clip)")
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--crop-center", type=int, nargs=2, metavar=("X", "Y"),
                    help="centre of the native-resolution crop (default: frame centre)")
    args = ap.parse_args()

    check_opencv_version()
    model_path = ensure_model(dcfg["url"], repo_path(dcfg["file"]))
    model = YoloxDnn(model_path, dcfg["input_size"], dcfg["strides"])

    sources = {"custom": args.source} if args.source else {
        "top": tt / "soccer_top/videos/D_20220220_1_1530_1560.mp4",
        "side": tt / "soccer_side/videos/F_20220220_1_1680_1710.mp4",
    }
    print(f"\n{'view':<6}{'input':<32}{'persons':>8}{'balls':>7}{'infer ms':>10}")
    total = 0
    for tag, video in sources.items():
        frame = read_frame(video, args.frame)
        total += run_on_frame(model, frame, tag, cfg, args.crop_center)
    print(f"\nannotated images saved to {repo_path(cfg['paths']['outputs'])}\\smoke_opencv_*.jpg")

    if total == 0:
        sys.exit("FAIL: cv2.dnn ran but found no person boxes.")
    print("PASS: OpenCV 5 cv2.dnn produced person boxes.")


if __name__ == "__main__":
    main()
