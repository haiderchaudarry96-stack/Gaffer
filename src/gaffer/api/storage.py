"""Where an analysis keeps its files (`api.storage`).

OpenCV always works on local files, so every analysis has a local working folder
(`local_dir`). The storage decides where results live afterwards: `LocalStorage` keeps them in
that folder (`outputs/api/<id>/`); `gaffer.aws.s3.S3Storage` has the same interface and also
copies them to S3 (`publish`) and reads them back when the local copy is gone (EC2 restarts).
Keys are `<analysis id>/<relative path>`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Protocol

from gaffer.config import repo_path

ID_RE = re.compile(r"^[a-z0-9]{6,32}$")


class StorageError(RuntimeError):
    """A key is invalid or a stored file is missing."""


def check_key(key: str) -> str:
    """`<id>/<path>` with a safe id and no `..` (keys come from URLs)."""
    parts = key.split("/")
    if len(parts) < 2 or not ID_RE.match(parts[0]) or any(p in ("", ".", "..") for p in parts):
        raise StorageError(f"invalid storage key {key!r}")
    return key


class Storage(Protocol):
    """Result storage. `local_dir` is always a local folder OpenCV can read and write."""

    def local_dir(self, analysis_id: str) -> Path: ...

    def exists(self, key: str) -> bool: ...

    def read_bytes(self, key: str) -> bytes: ...

    def write_bytes(self, key: str, data: bytes) -> None: ...

    def list_ids(self) -> list[str]: ...

    def publish(self, analysis_id: str, names: list[str]) -> None: ...


class LocalStorage:
    """Files under `root/<id>/` (default `outputs/api`)."""

    def __init__(self, root: str | Path) -> None:
        self.root = repo_path(root)

    def local_dir(self, analysis_id: str) -> Path:
        if not ID_RE.match(analysis_id):
            raise StorageError(f"invalid analysis id {analysis_id!r}")
        d = self.root / analysis_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def path(self, key: str) -> Path:
        return self.root / check_key(key)

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def read_bytes(self, key: str) -> bytes:
        p = self.path(key)
        if not p.exists():
            raise StorageError(f"{key} not found")
        return p.read_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        # Windows can briefly deny replacement while a status poll has the
        # destination open. Keep the atomic write, retry that transient lock.
        for attempt in range(6):
            try:
                tmp.replace(p)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.01 * (2 ** attempt))

    def list_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and ID_RE.match(p.name))

    def publish(self, analysis_id: str, names: list[str]) -> None:
        """Results already live in the local folder."""


def read_json(storage: Storage, key: str) -> Any:
    return json.loads(storage.read_bytes(key).decode("utf-8"))


def write_json(storage: Storage, key: str, obj: Any) -> None:
    storage.write_bytes(key, json.dumps(obj, indent=1, default=str).encode("utf-8"))


def make_storage(cfg: dict[str, Any]) -> Storage:
    """The storage named by `api.storage.backend` (`local` or `s3`)."""
    s = cfg["api"]["storage"]
    if s.get("backend", "local") == "s3":
        from gaffer.aws.s3 import S3Storage

        return S3Storage(bucket=s["bucket"], prefix=s.get("prefix", "analyses"),
                         local_root=s.get("root", "outputs/api"),
                         region=cfg["aws"]["region"])
    return LocalStorage(s.get("root", "outputs/api"))
