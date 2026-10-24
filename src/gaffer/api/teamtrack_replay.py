"""Whitelisted TeamTrack source clips for the recorded live-style replay."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastapi.responses import FileResponse, Response, StreamingResponse

from gaffer.config import repo_path

_CLIP_NAME = re.compile(r"^D_20220220_1_(\d{4})_(\d{4})\.mp4$")
_BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class ReplaySourceError(RuntimeError):
    """The configured replay manifest or one of its fixed clips is unavailable."""


@dataclass(frozen=True)
class ReplayClip:
    clip_id: str
    start_s: float
    end_s: float
    path: Path
    playback_path: Path | None = None

    @property
    def playback_file(self) -> Path:
        """What the browser's <video> gets: the 1080p proxy when present, else the original."""
        if self.playback_path is not None and self.playback_path.is_file():
            return self.playback_path
        return self.path

    def public(self, base_url: str) -> dict[str, object]:
        return {
            "id": self.clip_id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "url": f"{base_url}/api/replay/teamtrack/clips/{self.clip_id}",
        }


class TeamTrackReplay:
    """Resolve only the configured 900-1260 top-view clips, never request paths."""

    def __init__(self, settings: dict[str, object]) -> None:
        self.manifest_path = repo_path(str(settings.get(
            "manifest", "data/clips/teamtrack_top_full.clips.json"))).resolve()
        self.video_root = repo_path(str(settings.get(
            "video_root", "data/teamtrack/soccer_top/videos"))).resolve()
        self.match_id = str(settings.get("match_id", "teamtrack_top_w900_1260"))
        self.start_s = float(settings.get("start_s", 900))
        self.end_s = float(settings.get("end_s", 1260))
        self.clip_duration_s = float(settings.get("clip_duration_s", 30))
        playback = settings.get("playback") or {}
        if not isinstance(playback, dict):
            playback = {}
        self.playback_enabled = bool(playback.get("enabled", False))
        self.playback_root = repo_path(str(playback.get(
            "root", "data/teamtrack/soccer_top/playback_1080p"))).resolve()

    def playback_status(self, clips: tuple[ReplayClip, ...]) -> str:
        """"1080p proxies" when every clip has one, "original 4K" when off, else mixed."""
        if not self.playback_enabled:
            return "original 4K"
        proxies = sum(clip.playback_file != clip.path for clip in clips)
        if proxies == len(clips):
            return "1080p proxies"
        return f"1080p proxies for {proxies} of {len(clips)} clips, original 4K for the rest"

    def clips(self) -> tuple[ReplayClip, ...]:
        if not self.manifest_path.is_file():
            raise ReplaySourceError(f"clip manifest not found: {self.manifest_path}")
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            raw_clips = manifest["clips"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ReplaySourceError("clip manifest is unreadable or malformed") from exc

        selected: list[ReplayClip] = []
        for item in raw_clips:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            relative = item["path"]
            match = _CLIP_NAME.fullmatch(Path(relative).name)
            if not match:
                continue
            start, end = map(int, match.groups())
            manifest_start = item.get("start_s")
            if manifest_start is None or float(manifest_start) != float(start):
                continue
            if self.start_s <= start < self.end_s:
                path = (self.manifest_path.parent / relative).resolve()
                if path.parent != self.video_root or path.suffix.lower() != ".mp4":
                    raise ReplaySourceError(
                        "manifest clip resolves outside the TeamTrack top-view folder")
                # the proxy name comes from the validated clip, never from a request
                proxy = (self.playback_root / path.name) if self.playback_enabled else None
                if proxy is not None and proxy.resolve().parent != self.playback_root:
                    raise ReplaySourceError("playback proxy resolves outside its folder")
                selected.append(ReplayClip(f"{start:04d}-{end:04d}", float(start),
                                           float(end), path, proxy))

        selected.sort(key=lambda clip: clip.start_s)
        expected_count = round((self.end_s - self.start_s) / self.clip_duration_s)
        if (len(selected) != expected_count or not selected
                or selected[0].start_s != self.start_s or selected[-1].end_s != self.end_s):
            raise ReplaySourceError(
                f"expected {expected_count} consecutive top-view clips from "
                f"{self.start_s:g} to {self.end_s:g} seconds; found {len(selected)}")
        for previous, current in zip(selected, selected[1:], strict=False):
            if (current.start_s != previous.end_s
                    or previous.end_s - previous.start_s != self.clip_duration_s):
                raise ReplaySourceError(
                    "TeamTrack replay clips are not consecutive 30-second segments")

        missing = [clip.path.name for clip in selected if not clip.path.is_file()]
        if missing:
            raise ReplaySourceError("missing TeamTrack source clips: " + ", ".join(missing))
        last = selected[-1]
        if last.end_s - last.start_s != self.clip_duration_s:
            raise ReplaySourceError("the final TeamTrack clip is not a complete 30-second segment")
        return tuple(selected)

    def clip(self, clip_id: str) -> ReplayClip | None:
        return next((clip for clip in self.clips() if clip.clip_id == clip_id), None)


def clip_response(path: Path, range_header: str | None = None, *, cache_s: int = 0
                  ) -> FileResponse | Response | StreamingResponse:
    """Serve MP4 files with byte-range support for native browser seeking.

    `cache_s` > 0 lets the browser keep the file (the fixed replay clips never change)."""
    size = path.stat().st_size
    common = {"Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{path.name}"'}
    if cache_s > 0:
        common["Cache-Control"] = f"public, max-age={cache_s}"
    if not range_header:
        return FileResponse(path, media_type="video/mp4", headers=common)

    match = _BYTE_RANGE.fullmatch(range_header.strip())
    if not match or "," in range_header:
        return Response(status_code=416, headers={**common, "Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    if not first and not last:
        return Response(status_code=416, headers={**common, "Content-Range": f"bytes */{size}"})
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        suffix = int(last)
        if suffix <= 0:
            return Response(status_code=416, headers={**common, "Content-Range": f"bytes */{size}"})
        start, end = max(0, size - suffix), size - 1
    if start >= size or end < start:
        return Response(status_code=416, headers={**common, "Content-Range": f"bytes */{size}"})

    length = end - start + 1

    def chunks() -> Iterator[bytes]:
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                block = source.read(min(64 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    return StreamingResponse(chunks(), status_code=206, media_type="video/mp4",
                             headers={**common, "Content-Length": str(length),
                                       "Content-Range": f"bytes {start}-{end}/{size}"})
