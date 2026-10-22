"""Make the "Try it with a sample clip" video from one TeamTrack drone clip (OpenCV only).

Reads one 4K top-view clip, resizes every frame to 1920 x 1080 with `cv2.resize` (INTER_AREA)
and writes ~30 s of MP4 to `api.sample_clip.path` (gitignored). H.264 (`avc1`) is tried first so
browsers can preview it; if this OpenCV build has no H.264 encoder it falls back to `mp4v`
(the server still analyses it; the browser then shows no preview). The server treats the result
as an unknown upload (no saved calibration), so the full pitch check runs.

TeamTrack: Scott et al., 2024, arXiv 2404.13868, MIT licence (data/README.md).

    py scripts/make_sample_clip.py                     # D_20220220_1_1530_1560.mp4 (dev clip)
    py scripts/make_sample_clip.py --clip D_20220220_1_0990_1020.mp4 --seconds 30
"""

from __future__ import annotations

import argparse
import sys
import time
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clip", default="D_20220220_1_1530_1560.mp4",
                    help="TeamTrack top-view clip in data/teamtrack/soccer_top/videos")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--out", help="output path (default: api.sample_clip.path)")
    ap.add_argument("--codec", choices=("auto", "mp4v"), default="auto",
                    help="auto: H.264 if available (browser preview; ~220 MB on Windows Media "
                         "Foundation), else mp4v; mp4v: ~28 MB, no browser preview")
    args = ap.parse_args(argv)
    cfg = load_config()
    src = repo_path("data/teamtrack/soccer_top/videos") / args.clip
    out = repo_path(args.out or cfg["api"]["sample_clip"]["path"])
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"Cannot open {src}: download the TeamTrack clips first "
              "(py scripts/download_teamtrack.py).", file=sys.stderr)
        return 2
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out.parent.mkdir(parents=True, exist_ok=True)
    size = (args.width, args.height)
    writer, _ = open_writer(out, fps, size, ("avc1", "mp4v") if args.codec == "auto"
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
    check.release()
    print(f"wrote {out} ({n} frames, {n / fps:.1f} s, {size[0]}x{size[1]}, {fourcc}, "
          f"{out.stat().st_size / 1e6:.1f} MB) in {time.perf_counter() - t0:.1f} s; "
          f"OpenCV {cv2.__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
