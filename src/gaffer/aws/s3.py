"""S3 result storage for the API (Phase 4 deploy; same interface as `api.storage.LocalStorage`).

Analyses still run on local files (OpenCV reads paths): `local_dir` is a local working folder;
`publish` copies the finished results to `s3://<bucket>/<prefix>/<id>/...`; `read_bytes` reads the
local copy and falls back to S3 (after an EC2 restart). On EC2 the client uses the instance role
(no keys on disk). Not exercised against AWS yet: tests inject a fake client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gaffer.api.storage import ID_RE, LocalStorage, StorageError, check_key


class S3Storage(LocalStorage):
    """Local working folder + S3 copy of the results."""

    def __init__(self, bucket: str, prefix: str = "analyses",
                 local_root: str | Path = "outputs/api", region: str | None = None,
                 client: Any | None = None) -> None:
        super().__init__(local_root)
        self.bucket, self.prefix, self.region = bucket, prefix.strip("/"), region
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3  # lazy: tests never create a real client

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def s3_key(self, key: str) -> str:
        return f"{self.prefix}/{check_key(key)}"

    def exists(self, key: str) -> bool:
        if super().exists(key):
            return True
        try:
            self.client.head_object(Bucket=self.bucket, Key=self.s3_key(key))
            return True
        except Exception:  # botocore ClientError 404 (any error: treat as missing)
            return False

    def read_bytes(self, key: str) -> bytes:
        if super().exists(key):
            return super().read_bytes(key)
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self.s3_key(key))
        except Exception as exc:
            raise StorageError(f"{key} not found locally or in s3://{self.bucket}") from exc
        data = obj["Body"].read()
        super().write_bytes(key, data)  # local cache
        return data

    # write_bytes: local only (status files change every second); `publish` uploads results

    def list_ids(self) -> list[str]:
        ids = set(super().list_ids())
        try:
            resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix + "/",
                                               Delimiter="/")
            for p in resp.get("CommonPrefixes", []):
                name = p["Prefix"].rstrip("/").split("/")[-1]
                if ID_RE.match(name):
                    ids.add(name)
        except Exception:  # S3 unreachable: the local folders still list
            pass
        return sorted(ids)

    def publish(self, analysis_id: str, names: list[str]) -> None:
        """Upload finished result files (paths relative to the analysis folder)."""
        base = self.local_dir(analysis_id)
        for name in names:
            p = base / name
            if p.is_file():
                self.client.upload_file(str(p), self.bucket, self.s3_key(f"{analysis_id}/{name}"))
