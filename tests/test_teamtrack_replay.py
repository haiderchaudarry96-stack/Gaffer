"""The recorded demo source is fixed to a validated TeamTrack clip allowlist."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from gaffer.api.event_store import EventStore
from gaffer.api.main import create_app
from gaffer.api.storage import LocalStorage
from gaffer.api.teamtrack_replay import ReplaySourceError, TeamTrackReplay
from gaffer.api.usage import Usage
from gaffer.config import load_config


def replay_source(tmp_path: Path) -> tuple[dict, Path, Path]:
    manifest_dir = tmp_path / "clips"
    video_dir = tmp_path / "videos"
    manifest_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)
    rows = []
    for start in range(900, 1260, 30):
        end = start + 30
        name = f"D_20220220_1_{start:04d}_{end:04d}.mp4"
        (video_dir / name).write_bytes(b"0123456789abcdef")
        rows.append({"path": f"../videos/{name}", "start_s": float(start)})
    manifest = manifest_dir / "teamtrack_top_full.clips.json"
    manifest.write_text(json.dumps({"clips": rows}), encoding="utf-8")
    cfg = copy.deepcopy(load_config())
    cfg["api"]["teamtrack_replay"] = {
        "manifest": str(manifest),
        "video_root": str(video_dir),
        "match_id": "teamtrack_top_w900_1260",
        "start_s": 900,
        "end_s": 1260,
        "clip_duration_s": 30,
    }
    cfg["api"]["web_dist"] = str(tmp_path / "missing-web-dist")
    return cfg, manifest, video_dir


def test_manifest_is_consecutive_and_clip_serving_supports_byte_ranges(tmp_path) -> None:
    cfg, _, _ = replay_source(tmp_path)
    app = create_app(
        cfg,
        storage=LocalStorage(tmp_path / "api"),
        usage=Usage(cfg, str(tmp_path / "usage.json")),
        alerts_path=tmp_path / "alerts.jsonl",
        event_store=EventStore(tmp_path / "events.sqlite3"),
        start_worker=False,
        llm_factory=None,
        chat_trace=tmp_path / "chat_trace.jsonl",
    )
    with TestClient(app) as client:
        response = client.get("/api/replay/teamtrack")
        assert response.status_code == 200
        body = response.json()
        assert body["match_id"] == "teamtrack_top_w900_1260"
        assert body["start_s"] == 900 and body["end_s"] == 1260
        assert len(body["clips"]) == 12
        assert body["clips"][0]["id"] == "0900-0930"
        assert body["clips"][-1]["id"] == "1230-1260"

        clip = client.get(body["clips"][0]["url"], headers={"Range": "bytes=2-7"})
        assert clip.status_code == 206
        assert clip.content == b"234567"
        assert clip.headers["content-range"] == "bytes 2-7/16"
        assert clip.headers["accept-ranges"] == "bytes"
        assert client.get("/api/replay/teamtrack/clips/0000-0030").status_code == 404


def test_manifest_rejects_missing_files_and_paths_outside_video_root(tmp_path) -> None:
    cfg, manifest, video_dir = replay_source(tmp_path)
    replay = TeamTrackReplay(cfg["api"]["teamtrack_replay"])
    assert len(replay.clips()) == 12

    (video_dir / "D_20220220_1_1230_1260.mp4").unlink()
    try:
        replay.clips()
        raise AssertionError("missing clip was accepted")
    except ReplaySourceError as exc:
        assert "D_20220220_1_1230_1260.mp4" in str(exc)

    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["clips"][0]["path"] = "../../outside/D_20220220_1_0900_0930.mp4"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    try:
        replay.clips()
        raise AssertionError("outside path was accepted")
    except ReplaySourceError as exc:
        assert "outside" in str(exc)


def _app(cfg: dict, tmp_path: Path):
    return create_app(
        cfg, storage=LocalStorage(tmp_path / "api"), usage=Usage(cfg, str(tmp_path / "usage.json")),
        alerts_path=tmp_path / "alerts.jsonl", event_store=EventStore(tmp_path / "events.sqlite3"),
        start_worker=False, llm_factory=None, chat_trace=tmp_path / "chat_trace.jsonl")


def test_video_element_gets_the_playback_proxy_and_analysis_keeps_the_original(tmp_path) -> None:
    cfg, _, video_dir = replay_source(tmp_path)
    proxy_dir = tmp_path / "playback"
    proxy_dir.mkdir()
    cfg["api"]["teamtrack_replay"]["playback"] = {"enabled": True, "root": str(proxy_dir)}
    for name in [p.name for p in video_dir.iterdir()][:11]:
        (proxy_dir / name).write_bytes(b"PROXY")
    replay = TeamTrackReplay(cfg["api"]["teamtrack_replay"])
    clips = replay.clips()
    # analysis code reads `path`: always the 4K original
    assert all(c.path.parent == video_dir.resolve() for c in clips)
    assert replay.playback_status(clips) == \
        "1080p proxies for 11 of 12 clips, original 4K for the rest"
    with TestClient(_app(cfg, tmp_path)) as client:
        body = client.get("/api/replay/teamtrack").json()
        assert body["playback"].startswith("1080p proxies for 11")
        first = client.get(body["clips"][0]["url"])
        assert first.content == b"PROXY"
        assert first.headers["cache-control"] == "public, max-age=86400"
        # a missing proxy falls back to the original instead of failing
        assert client.get(body["clips"][-1]["url"]).content == b"0123456789abcdef"
        assert client.get("/api/health").json()["replay_playback"].startswith("1080p proxies")

    cfg["api"]["teamtrack_replay"]["playback"]["enabled"] = False
    with TestClient(_app(cfg, tmp_path)) as client:
        body = client.get("/api/replay/teamtrack").json()
        assert body["playback"] == "original 4K"
        assert client.get(body["clips"][0]["url"]).content == b"0123456789abcdef"
