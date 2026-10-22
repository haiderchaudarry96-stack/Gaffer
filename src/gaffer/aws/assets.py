"""Fetch the server's large, gitignored files from S3 before the app starts (EC2 deploy).

The container runs `python -m gaffer.aws.assets` at start (deploy/start.sh). Every object under
`s3://<bucket>/<prefix>/` is copied to the same path under the repo root, but only into the
allowed folders below (replay clips, sample clip, model weights), and only when the local file is
missing or has a different size. Credentials come from the default chain (on EC2: the instance
role); nothing is ever written to disk except the files themselves.

    GAFFER_ASSETS_BUCKET=gaffer-demo-<account> python -m gaffer.aws.assets

Without `GAFFER_ASSETS_BUCKET` (laptop, local Docker) it does nothing. Failures are reported in
one line and never stop the app: it then serves what is already on disk.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from gaffer.config import load_config, repo_path

ALLOWED_DIRS = ("data/teamtrack/soccer_top/videos/", "data/sample_clips/", "models/")
ALLOWED_SUFFIXES = (".mp4", ".onnx")


@dataclass
class FetchReport:
    downloaded: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    bytes: int = 0
    seconds: float = 0.0
    error: str | None = None

    def line(self) -> str:
        if self.error:
            return f"assets: not fetched ({self.error}); serving what is on disk"
        return (f"assets: {len(self.downloaded)} downloaded ({self.bytes / 1e6:.1f} MB, "
                f"{self.seconds:.1f} s), {len(self.kept)} already present, "
                f"{len(self.skipped)} skipped")


def local_target(key: str, prefix: str) -> str | None:
    """The repo-relative path for an S3 key, or None when it is outside the allowed folders."""
    if not key.startswith(prefix):
        return None
    rel = key[len(prefix):]
    parts = PurePosixPath(rel).parts
    if not rel or ".." in parts or rel.startswith("/"):
        return None
    if not rel.startswith(ALLOWED_DIRS) or not rel.lower().endswith(ALLOWED_SUFFIXES):
        return None
    return rel


def fetch(bucket: str, prefix: str = "assets/", *, region: str | None = None,
          client: Any | None = None, root: Path | None = None) -> FetchReport:
    """Copy missing / changed asset objects from S3 into the repo folders."""
    rep = FetchReport()
    t0 = time.perf_counter()
    prefix = prefix.strip("/") + "/"
    try:
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        objects = [o for page in pages for o in page.get("Contents", [])]
    except Exception as exc:  # no credentials, no bucket, no permission: say which, keep going
        rep.error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        return rep
    for obj in objects:
        rel = local_target(obj["Key"], prefix)
        if rel is None:
            rep.skipped.append(obj["Key"])
            continue
        dest = (root / rel) if root is not None else repo_path(rel)
        if dest.is_file() and dest.stat().st_size == int(obj["Size"]):
            rep.kept.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            client.download_file(bucket, obj["Key"], str(part))
            part.replace(dest)
        except Exception as exc:
            part.unlink(missing_ok=True)
            rep.error = f"{rel}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
            break
        rep.downloaded.append(rel)
        rep.bytes += int(obj["Size"])
    rep.seconds = time.perf_counter() - t0
    return rep


def main() -> int:
    bucket = os.environ.get("GAFFER_ASSETS_BUCKET", "").strip()
    if not bucket:
        print("assets: GAFFER_ASSETS_BUCKET not set; nothing to fetch", flush=True)
        return 0
    cfg = load_config()
    rep = fetch(bucket, os.environ.get("GAFFER_ASSETS_PREFIX", "assets/"),
                region=cfg["aws"]["region"])
    print(rep.line(), flush=True)
    return 0  # never block the app from starting


if __name__ == "__main__":
    sys.exit(main())
