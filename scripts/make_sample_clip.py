"""Make a "Try it with a sample clip" video from one 4K top-view clip (OpenCV resize).

Reads one 4K top-view clip, resizes every frame to 1920 x 1080 with `cv2.resize` (INTER_AREA)
and writes ~30 s of MP4 (gitignored). Same content, only the resolution is reduced.

Two sources (both analysed by the server as an unknown upload: no saved calibration, so the
full pitch check runs):

* TeamTrack drone clip (default) -> `api.sample_clip.path`. Scott et al., 2024, arXiv 2404.13868,
  MIT licence (data/README.md). H.264 (`avc1`) is tried first so browsers can preview it; if this
  OpenCV build has no H.264 encoder it falls back to `mp4v` (no browser preview).
* `--source zenodo` -> `api.more_sample_clips[id=zenodo].path`, from `data/zenodo/top-view-preview.mp4`
  (Synowiec, Nowak, Kamola, DOI 10.5281/zenodo.14867795, CC BY 4.0). With `--codec x264` the
  resized frames are encoded with PyAV's libx264 (CRF 23): browser-playable and ~10x smaller than
  OpenCV's Windows Media Foundation H.264, which matters for the plain "Download" link.

    py scripts/make_sample_clip.py                     # D_20220220_1_1530_1560.mp4 (dev clip)
    py scripts/make_sample_clip.py --clip D_20220220_1_0990_1020.mp4 --seconds 30
    py scripts/make_sample_clip.py --source zenodo --codec x264
"""

from __future__ import annotations

import argparse
import sys
import time
from fractions import Fraction
from pathlib import Path

import cv2

from gaffer.config import load_config, repo_path


def open_writer(path: Path, fps: float, size: tuple[int, int],
                codecs: tuple[str, ...]) -> tuple[cv2.VideoWriter, str]:
    for fourcc in codecs:
        w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if w.isOpened():
            return w, fourcc
        w.release()
    raise RuntimeError("OpenCV could not open an MP4 writer (avc1 or mp4v)")


class X264Writer:
    """BGR frames -> H.264 MP4 through PyAV (libx264, yuv420p, faststart); same API as needed."""

    def __init__(self, path: Path, fps: float, size: tuple[int, int], crf: int = 23) -> None:
        import av

        self._av = av
        self._c = av.open(str(path), "w", options={"movflags": "faststart"})
        self._s = self._c.add_stream("libx264", rate=Fraction(fps).limit_denominator(1001))
        self._s.width, self._s.height = size
        self._s.pix_fmt = "yuv420p"
        self._s.options = {"crf": str(crf), "preset": "medium"}

    def write(self, frame_bgr) -> None:  # noqa: ANN001 - numpy array
        vf = self._av.VideoFrame.from_ndarray(frame_bgr, format="bgr24")
        for packet in self._s.encode(vf):
            self._c.mux(packet)

    def release(self) -> None:
        for packet in self._s.encode():
            self._c.mux(packet)
        self._c.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", choices=("teamtrack", "zenodo"), default="teamtrack")
    ap.add_argument("--clip", default="D_20220220_1_1530_1560.mp4",
                    help="TeamTrack top-view clip in data/teamtrack/soccer_top/videos")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--out", help="output path (default: the sample's path in config.yaml)")
    ap.add_argument("--codec", choices=("auto", "mp4v", "x264"), default=None,
                    help="auto: H.264 if available (browser preview; ~220 MB on Windows Media "
                         "Foundation), else mp4v; mp4v: ~28 MB, no browser preview; x264: PyAV "
                         "libx264 CRF 23 (default for --source zenodo)")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.source == "zenodo":
        src = repo_path(cfg["zenodo"]["video"])
        more = {c["id"]: c for c in cfg["api"].get("more_sample_clips", [])}
        out = repo_path(args.out or more["zenodo"]["path"])
        codec = args.codec or "x264"
    else:
        src = repo_path("data/teamtrack/soccer_top/videos") / args.clip
        out = repo_path(args.out or cfg["api"]["sample_clip"]["path"])
        codec = args.codec or "auto"
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"Cannot open {src}: download the clip first "
              "(py scripts/download_teamtrack.py; Zenodo: docs/DATA_SOURCES.md).", file=sys.stderr)
        return 2
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out.parent.mkdir(parents=True, exist_ok=True)
    size = (args.width, args.height)
    if codec == "x264":
        writer: X264Writer | cv2.VideoWriter = X264Writer(out, fps, size)
    else:
        writer, _ = open_writer(out, fps, size, ("avc1", "mp4v") if codec == "auto"
                                else ("mp4v",))
    t0, n, limit = time.perf_counter(), 0, int(round(args.seconds * fps))
    while n < limit:
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
        n += 1
    cap.release()
    writer.release()
    if n == 0:
        print(f"No frames read from {src}.", file=sys.stderr)
        return 2
    check = cv2.VideoCapture(str(out))  # what was really written (a backend may substitute)
    fourcc = int(check.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode("ascii", "replace")
    frames = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
    check.release()
    print(f"wrote {out} ({n} frames written, {frames} read back, {n / fps:.1f} s, "
          f"{size[0]}x{size[1]}, {fourcc}, {out.stat().st_size / 1e6:.1f} MB) in "
          f"{time.perf_counter() - t0:.1f} s; OpenCV {cv2.__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
