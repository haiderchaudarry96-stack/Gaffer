"""S3 asset fetch at container start (gaffer.aws.assets): fake client, no AWS."""

from __future__ import annotations

from pathlib import Path

from gaffer.aws.assets import fetch, local_target


class FakeS3:
    def __init__(self, objects: dict[str, bytes], fail_list: bool = False) -> None:
        self.objects, self.fail_list, self.downloads = objects, fail_list, []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        fake = self

        class P:
            def paginate(self, Bucket: str, Prefix: str):  # noqa: N803 (boto3 names)
                if fake.fail_list:
                    raise PermissionError("AccessDenied: s3:ListBucket")
                yield {"Contents": [{"Key": k, "Size": len(v)} for k, v in fake.objects.items()
                                    if k.startswith(Prefix)]}

        return P()

    def download_file(self, bucket: str, key: str, path: str) -> None:
        self.downloads.append(key)
        Path(path).write_bytes(self.objects[key])


def test_local_target_only_allows_the_asset_folders() -> None:
    p = "assets/"
    assert local_target("assets/data/teamtrack/soccer_top/videos/D_1.mp4", p) == \
        "data/teamtrack/soccer_top/videos/D_1.mp4"
    assert local_target("assets/models/x.onnx", p) == "models/x.onnx"
    proxy = "data/teamtrack/soccer_top/playback_1080p/D_1.mp4"
    assert local_target(f"assets/{proxy}", p) == proxy
    assert local_target("assets/data/sample_clips/s.mp4", p) == "data/sample_clips/s.mp4"
    for bad in ("assets/config.yaml", "assets/models/../config.onnx", "assets/src/x.mp4",
                "assets/data/teamtrack/soccer_side/videos/F.mp4", "src/gaffer.tar.gz",
                "assets/models/notes.txt"):
        assert local_target(bad, p) is None, bad


def test_fetch_downloads_missing_and_keeps_same_size(tmp_path) -> None:
    objs = {"assets/models/m.onnx": b"abc", "assets/data/sample_clips/s.mp4": b"12345",
            "assets/evil.sh": b"x", "src/gaffer.tar.gz": b"t"}
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.onnx").write_bytes(b"xyz")  # same size: kept
    s3 = FakeS3(objs)
    rep = fetch("b", "assets", client=s3, root=tmp_path)
    assert rep.error is None
    assert rep.downloaded == ["data/sample_clips/s.mp4"] and rep.kept == ["models/m.onnx"]
    assert rep.skipped == ["assets/evil.sh"]
    assert (tmp_path / "data/sample_clips/s.mp4").read_bytes() == b"12345"
    assert not (tmp_path / "evil.sh").exists()
    again = fetch("b", "assets/", client=s3, root=tmp_path)
    assert again.downloaded == [] and len(again.kept) == 2


def test_fetch_reports_access_errors_without_raising(tmp_path) -> None:
    rep = fetch("b", client=FakeS3({}, fail_list=True), root=tmp_path)
    assert rep.error and "AccessDenied" in rep.error
    assert "serving what is on disk" in rep.line()
