"""Join consecutive TeamTrack top-view clips into one demo upload, without re-encoding (PyAV).

The default is the 12 clips of match time 900-1260 s (15:00-21:00): the window with the one
confirmed real change (White 4-4-2 -> 3-4-3 at 16:30), the rejected Blue return leg (18:50) and
seven unchecked candidates. 6 minutes = the upload limit (`api.uploads.max_duration_s`, 370 s).
Packets are copied with shifted timestamps, so the 4K picture is bit-identical to the source and
the run takes seconds. The output is a NEW file to the server (not a recognised TeamTrack
source), so an upload runs the full flow: pitch check, OpenCV pipeline, agent, report.

TeamTrack: Scott et al., 2024, arXiv 2404.13868, MIT licence (data/README.md). The output is
gitignored (data/sample_clips/); never commit it.

    py scripts/make_demo_clip.py                          # 900-1260 s -> data/sample_clips/
    py scripts/make_demo_clip.py --start 900 --end 960    # a 60 s test file
"""

from __future__ import annotations

import argparse
import sys
import time
from fractions import Fraction
from pathlib import Path

import av

from gaffer.config import load_config, repo_path


def clip_names(start: int, end: int, step: int = 30) -> list[str]:
    """TeamTrack top-view file names covering [start, end) seconds (30 s clips)."""
    if start % step or end % step or end <= start:
        raise ValueError(f"--start/--end must be multiples of {step} s with end > start")
    return [f"D_20220220_1_{t:04d}_{t + step:04d}.mp4" for t in range(start, end, step)]


def join(paths: list[Path], out: Path) -> tuple[int, float]:
    """Remux the video streams of `paths` back to back into `out`. Returns (packets, seconds)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    first = av.open(str(paths[0]))
    src0 = first.streams.video[0]
    dst = av.open(str(out), "w")
    ost = dst.add_stream_from_template(src0)
    tb = src0.time_base
    first.close()
    offset = 0  # in the stream time base
    n = 0
    for p in paths:
        inp = av.open(str(p))
        ist = inp.streams.video[0]
        if (ist.codec_context.width, ist.codec_context.height) != (
                src0.codec_context.width, src0.codec_context.height) or ist.time_base != tb:
            raise RuntimeError(f"{p.name}: different size or time base; cannot join without "
                               "re-encoding")
        last = offset
        dur = 0
        for pkt in inp.demux(ist):
            if pkt.dts is None:
                continue
            pkt.dts += offset
            if pkt.pts is not None:
                pkt.pts += offset
            last = max(last, (pkt.pts if pkt.pts is not None else pkt.dts))
            dur = pkt.duration or dur
            pkt.stream = ost
            dst.mux(pkt)
            n += 1
        offset = last + (dur or 1)
        inp.close()
    dst.close()
    return n, float(Fraction(offset) * tb)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", type=int, default=900, help="match seconds (multiple of 30)")
    ap.add_argument("--end", type=int, default=1260)
    ap.add_argument("--out", help="default: data/sample_clips/teamtrack_top_<start>_<end>_4k.mp4")
    args = ap.parse_args(argv)
    cfg = load_config()
    vids = repo_path(cfg["paths"]["teamtrack"]) / "soccer_top" / "videos"
    try:
        paths = [vids / n for n in clip_names(args.start, args.end)]
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        print(f"ERROR: missing TeamTrack clips: {', '.join(missing)} "
              "(py scripts/download_teamtrack.py --check)", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else repo_path(
        f"data/sample_clips/teamtrack_top_{args.start:04d}_{args.end:04d}_4k.mp4")
    t0 = time.perf_counter()
    n, secs = join(paths, out)
    mb = out.stat().st_size / 1e6
    print(f"{len(paths)} clips -> {out} ({secs:.1f} s, {n} packets, {mb:.1f} MB, "
          f"{time.perf_counter() - t0:.1f} s)")
    limit = float(cfg.get("api", {}).get("uploads", {}).get("max_duration_s", 360))
    if secs > limit + 1:
        print(f"WARNING: {secs:.0f} s is over the upload limit ({limit:.0f} s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
