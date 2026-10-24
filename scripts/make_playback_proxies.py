"""Make 1080p playback proxies of the Live-analysis replay clips (browser playback only).

The Live analysis replay streams the 4K TeamTrack clips into a `<video>` element; on a slow link or
a weak laptop that stutters. This script writes a 1920 x 1080 H.264 copy of every clip the replay
uses (`api.teamtrack_replay`, 900-1260 s of `data/clips/teamtrack_top_full.clips.json`) into
`api.teamtrack_replay.playback.root`. Nothing that analyses frames reads these files: the pipeline,
the agent and the evaluation keep the 4K originals.

Same content and timing: every frame is decoded with PyAV, resized with `cv2.resize` (INTER_AREA,
as `scripts/make_sample_clip.py`) and re-encoded with its original timestamp and time base
(libx264 through PyAV, the tool `make_sample_clip.py` already uses; yuv420p, faststart, no
audio). CRF 23 with a bitrate cap keeps a clip small enough to stream ahead of playback.
After writing, each proxy is checked against its original: frame count, fps, duration, first and
last frame timestamps (exits 1 on any mismatch).

    py scripts/make_playback_proxies.py            # all replay clips (skips proxies that pass)
    py scripts/make_playback_proxies.py --check    # only compare existing proxies
    py scripts/make_playback_proxies.py --force    # re-encode every clip
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from gaffer.api.teamtrack_replay import ReplaySourceError, TeamTrackReplay
from gaffer.config import load_config

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_sample_clip import X264Writer  # noqa: E402  (same encoder as the sample clip)

SIZE = (1920, 1080)
X264_OPTIONS = {"maxrate": "3500k", "bufsize": "7000k", "g": "60"}  # cap ~3.5 Mbit/s, key 2 s


def probe(path: Path) -> dict[str, object]:
    """Frame count, fps, duration and first/last frame timestamps (s) from the container."""
    import av

    with av.open(str(path)) as c:
        v = c.streams.video[0]
        pts = sorted(p.pts for p in c.demux(v) if p.pts is not None and p.size)
        tb = v.time_base
        return {
            "frames": len(pts),
            "fps": float(v.average_rate) if v.average_rate else None,
            "first_s": round(float(pts[0] * tb), 6) if pts else None,
            "last_s": round(float(pts[-1] * tb), 6) if pts else None,
            "duration_s": round(float(c.duration / 1e6), 3) if c.duration else None,
            "size": (v.codec_context.width, v.codec_context.height),
            "audio": len(c.streams.audio),
        }


def compare(orig: dict[str, object], proxy: dict[str, object]) -> list[str]:
    """Differences that matter for timing; an empty list means the proxy matches."""
    bad = []
    for key in ("frames", "first_s", "last_s"):
        if orig[key] != proxy[key]:
            bad.append(f"{key} {orig[key]} != {proxy[key]}")
    if abs(float(orig["fps"]) - float(proxy["fps"])) > 1e-3:
        bad.append(f"fps {orig['fps']} != {proxy['fps']}")
    if abs(float(orig["duration_s"]) - float(proxy["duration_s"])) > 0.05:
        bad.append(f"duration {orig['duration_s']} != {proxy['duration_s']}")
    if tuple(proxy["size"]) != SIZE:
        bad.append(f"size {proxy['size']}")
    if proxy["audio"]:
        bad.append("has audio")
    return bad


def encode(src: Path, dest: Path, crf: int) -> int:
    """Decode every frame of `src`, resize, re-encode with the same pts; returns frames written."""
    import av

    part = dest.with_name(dest.stem + ".part.mp4")
    with av.open(str(src)) as c:
        v = c.streams.video[0]
        writer = X264Writer(part, v.average_rate, SIZE, crf=crf, time_base=v.time_base,
                            options=X264_OPTIONS)
        n = 0
        try:
            for frame in c.decode(v):
                img = cv2.resize(frame.to_ndarray(format="bgr24"), SIZE,
                                 interpolation=cv2.INTER_AREA)
                writer.write(img, pts=frame.pts)
                n += 1
        finally:
            writer.release()
    part.replace(dest)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="only compare existing proxies")
    ap.add_argument("--force", action="store_true", help="re-encode even when a proxy passes")
    ap.add_argument("--crf", type=int, default=23)
    args = ap.parse_args(argv)
    replay = TeamTrackReplay(load_config()["api"]["teamtrack_replay"])
    try:
        clips = replay.clips()
    except ReplaySourceError as exc:
        print(f"Replay clips unavailable: {exc}", file=sys.stderr)
        return 2
    root = replay.playback_root
    root.mkdir(parents=True, exist_ok=True)
    failed, total_orig, total_proxy, t_all = 0, 0, 0, time.perf_counter()
    print(f"{'clip':<28} {'orig MB':>8} {'proxy MB':>9} {'frames':>7} {'fps':>7} "
          f"{'first s':>8} {'last s':>9} {'dur s':>7}  result")
    for clip in clips:
        dest = root / clip.path.name
        orig = probe(clip.path)
        status = ""
        if not args.check and (args.force or not dest.is_file()
                               or compare(orig, probe(dest))):
            t0 = time.perf_counter()
            encode(clip.path, dest, args.crf)
            status = f"encoded {time.perf_counter() - t0:.0f} s; "
        if not dest.is_file():
            print(f"{clip.path.name:<28} missing proxy")
            failed += 1
            continue
        proxy = probe(dest)
        bad = compare(orig, proxy)
        failed += bool(bad)
        o_mb, p_mb = clip.path.stat().st_size / 1e6, dest.stat().st_size / 1e6
        total_orig += clip.path.stat().st_size
        total_proxy += dest.stat().st_size
        print(f"{clip.path.name:<28} {o_mb:8.1f} {p_mb:9.1f} {proxy['frames']:>7} "
              f"{proxy['fps']:7.3f} {proxy['first_s']:8.3f} {proxy['last_s']:9.3f} "
              f"{proxy['duration_s']:7.2f}  {status}{'; '.join(bad) or 'matches original'}")
    print(f"total: originals {total_orig / 1e6:.1f} MB, proxies {total_proxy / 1e6:.1f} MB "
          f"({total_proxy / max(total_orig, 1):.0%}); {len(clips)} clips, {failed} failed; "
          f"{time.perf_counter() - t_all:.0f} s; OpenCV {cv2.__version__}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
