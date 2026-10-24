"""Upload storage safety for the public demo server (`api.uploads`, docs/API.md).

Uploads live on the server's disk (EC2: 30 GB EBS under `/opt/gaffer/outputs/api`), so three rules
keep a visitor from filling it:

1. **Free-space check** before an upload is accepted (`disk_gate`): below `min_free_disk_gb`
   (plus twice the upload: the body is spooled once and saved once) the upload is refused with
   "The demo server is full right now, please try a sample clip". Samples (~30 MB) have their own,
   much lower floor.
2. **Retention**: the raw uploaded video is deleted `retention_hours` after its analysis finished
   (`done` or `failed`). The *results stay*: `match_state.json`, timeline, events, evidence images,
   the report and the first frame. Nothing in the app reads the raw video after the analysis: the
   desk plays the file from the visitor's own browser, and no endpoint serves it. A pitch step left
   open that long is closed (status `failed`, "upload it again") and its video deleted too.
3. **One analysis at a time** (`jobs.py`: a single worker; the rest wait with status `queued` and a
   live `queue_position`; more than `api.jobs.max_queued` waiting uploads are refused).
"""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from gaffer.api.storage import ID_RE
from gaffer.config import repo_path

log = logging.getLogger("gaffer.api.retention")

SERVER_FULL = "The demo server is full right now, please try a sample clip."
GB = 1_000_000_000
RAW_PREFIX = "upload."          # upload.mp4 / upload.mov in the analysis folder
WAITING = ("uploaded", "needs_confirmation", "needs_corners")
FINISHED = ("done", "failed")


def free_bytes(path: str | Path) -> int:
    """Free space of the disk holding `path` (the nearest existing parent)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def disk_gate(free: int, *, floor_gb: float, incoming_bytes: int = 0,
              copies: int = 2) -> str | None:
    """None when the upload fits, else the refusal for the coach. `incoming_bytes` is the request
    size (0 when unknown); it is counted `copies` times (spooled body + saved file)."""
    need = int(floor_gb * GB) + copies * max(0, int(incoming_bytes))
    return SERVER_FULL if free < need else None


def parse_utc(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def raw_files(job_dir: Path) -> list[Path]:
    return sorted(p for p in job_dir.glob(f"{RAW_PREFIX}*") if p.is_file())


class Retention:
    """Deletes expired raw videos. `sweep()` is cheap and idempotent: it is called once at start
    and then every `sweep_interval_s` by a daemon thread (`start()`); tests call it directly."""

    def __init__(self, cfg: dict[str, Any], storage: Any, jobs: Any, *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        u = cfg["api"]["uploads"]
        self.retention = timedelta(hours=float(u["retention_hours"]))
        self.interval_s = float(u["sweep_interval_s"])
        self.hours = float(u["retention_hours"])
        self.cache_dir = repo_path(cfg["agent"]["vision"]["cache_dir"])
        self.storage, self.jobs, self.now = storage, jobs, now
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _delete_cache(self, aid: str) -> int:
        """The agent's re-analysis cache of this upload (`up_<id>_*.json`): derived from the video
        that is going away, and its results are already in the analysis folder."""
        n = 0
        for p in self.cache_dir.glob(f"up_{aid}_*"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n

    def sweep(self) -> dict[str, int]:
        """Delete the raw video of every analysis older than the retention. Returns counts."""
        out = {"videos": 0, "bytes": 0, "expired_waiting": 0}
        now = self.now()
        for aid in self.storage.list_ids():
            if not ID_RE.match(aid) or aid == getattr(self.jobs, "current", None):
                continue
            st = self.jobs.get(aid)
            if not st or st.get("status") in ("queued", "running"):
                continue
            job_dir = self.storage.local_dir(aid)
            files = raw_files(job_dir)
            if not files:
                continue
            when = parse_utc(st.get("finished_utc")) or parse_utc(st.get("updated_utc"))
            if when is None or now - when < self.retention:
                continue
            waiting = st.get("status") in WAITING
            size = 0
            for f in files:
                try:
                    size += f.stat().st_size
                    f.unlink()
                except OSError:
                    log.warning("could not delete %s", f)
            self._delete_cache(aid)
            stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            if waiting:
                self.jobs.update(aid, status="failed", stage="uploading", eta_s=None,
                                 video_deleted_utc=stamp,
                                 error=f"This upload was not started within {self.hours:g} hours, "
                                       "so its video was deleted. Upload it again.")
                out["expired_waiting"] += 1
            else:
                self.jobs.update(aid, video_deleted_utc=stamp)
            out["videos"] += 1
            out["bytes"] += size
        if out["videos"]:
            log.info("retention_sweep videos=%d freed_mb=%.1f expired_waiting=%d", out["videos"],
                     out["bytes"] / 1e6, out["expired_waiting"])
        return out

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        def loop() -> None:
            while True:
                try:
                    self.sweep()
                except Exception:  # a clean-up problem must never stop the server
                    log.exception("retention sweep failed")
                if self._stop.wait(self.interval_s):
                    return

        self._thread = threading.Thread(target=loop, name="gaffer-retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
