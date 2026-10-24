"""The demo server's honesty and safety (24 Oct): `GET /api/runtime` (EC2 metadata mocked: on AWS,
off AWS, timeout), the free-disk gate, raw-video retention, and the analysis queue. No network."""

from __future__ import annotations

import copy
import json
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from gaffer.api.retention import SERVER_FULL, Retention, disk_gate, parse_utc
from gaffer.api.runtime import Runtime, read_imds

sys.path.insert(0, str(Path(__file__).parent))  # pytest's importlib mode: tests/ is not on it
from test_api import STRAIGHT, make_client, upload  # noqa: E402
from videogen import write_video  # noqa: E402

from gaffer.config import load_config  # noqa: E402

GB = 1_000_000_000


@pytest.fixture(scope="module")
def base_cfg():
    return load_config()


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    return {"straight": write_video(tmp_path_factory.mktemp("videos") / "my match.mp4")}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Nothing here may open a network connection (the metadata service is faked)."""
    real = socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if (self.family == getattr(socket, "AF_UNIX", None)
                or host in ("127.0.0.1", "::1", "localhost")):
            return real(self, address)
        raise RuntimeError(f"network access is disabled in tests ({address})")

    monkeypatch.setattr(socket.socket, "connect", guard)


# --------------------------------------------------------------------------- EC2 metadata (IMDSv2)


class FakeImds:
    """A stand-in for `urlopen`: records every request, answers like IMDSv2."""

    def __init__(self, values: dict[str, str] | None = None, fail: set[str] | None = None,
                 token: str = "TOKEN123", tick: Any = None) -> None:
        self.values = values if values is not None else {
            "instance-type": "m7i-flex.large", "placement/availability-zone": "ap-southeast-2a",
            "placement/region": "ap-southeast-2"}
        self.fail, self.token, self.tick = fail or set(), token, tick
        self.requests: list[tuple[str, str, dict[str, str], float]] = []

    def __call__(self, req: Any, timeout: float = 0) -> Any:
        url = req.full_url
        self.requests.append((req.get_method(), url, {k.lower(): v for k, v in req.header_items()},
                              timeout))
        if self.tick:
            self.tick()
        path = url.split("169.254.169.254", 1)[1]
        if path == "/latest/api/token":
            if "token" in self.fail:
                raise TimeoutError("timed out")
            body = self.token
        else:
            key = path.removeprefix("/latest/meta-data/")
            if key in self.fail or key not in self.values:
                raise OSError("404")
            body = self.values[key]
        return _Resp(body)


class _Resp:
    def __init__(self, body: str) -> None:
        self.body = body.encode()

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_imds_is_read_with_a_token_and_only_three_fields() -> None:
    imds = FakeImds()
    got = read_imds(opener=imds)
    assert got == {"instance_type": "m7i-flex.large", "availability_zone": "ap-southeast-2a",
                   "region": "ap-southeast-2"}
    method, url, headers, _ = imds.requests[0]
    assert method == "PUT" and url.endswith("/latest/api/token")
    assert "x-aws-ec2-metadata-token-ttl-seconds" in headers
    asked = [u.split("/latest/meta-data/")[1] for _, u, _, _ in imds.requests[1:]]
    assert asked == ["instance-type", "placement/availability-zone", "placement/region"]
    # every metadata GET carries the token; nothing about instance id, address or credentials
    assert all(h.get("x-aws-ec2-metadata-token") == "TOKEN123" for _, _, h, _ in imds.requests[1:])
    assert not any(w in u for _, u, _, _ in imds.requests
                   for w in ("instance-id", "iam", "public-ipv4", "local-ipv4", "identity"))


def test_off_aws_gives_none_quickly() -> None:
    t0 = time.perf_counter()
    assert read_imds(opener=FakeImds(fail={"token"})) is None
    assert time.perf_counter() - t0 < 1.0
    # the real opener in a sandbox without a route (the test guard refuses the connection)
    t0 = time.perf_counter()
    assert read_imds() is None
    assert time.perf_counter() - t0 < 1.0


def test_a_slow_metadata_service_stops_at_the_total_budget() -> None:
    now = [0.0]

    def tick() -> None:
        now[0] += 0.5  # every request "takes" half a second

    imds = FakeImds(tick=tick)
    got = read_imds(opener=imds, total_s=0.9, timeout_s=0.4, clock=lambda: now[0])
    assert got is not None and got["instance_type"] == "m7i-flex.large"  # 2nd request still fits
    assert got["region"] is None and len(imds.requests) < 4         # then it gives up
    assert all(r[3] <= 0.4 for r in imds.requests)


def test_a_field_that_fails_or_looks_odd_is_none() -> None:
    got = read_imds(opener=FakeImds(fail={"placement/region"}, values={
        "instance-type": "m7i-flex.large", "placement/availability-zone": "<script>x</script>"}))
    assert got == {"instance_type": "m7i-flex.large", "availability_zone": None, "region": None}


def _runtime_client(tmp_path: Path, cfg: dict[str, Any], imds: Any):
    return make_client(tmp_path, cfg, imds=imds)


def test_runtime_endpoint_on_aws(tmp_path, base_cfg) -> None:
    c = _runtime_client(tmp_path, base_cfg, lambda: {
        "instance_type": "m7i-flex.large", "availability_zone": "ap-southeast-2a",
        "region": "ap-southeast-2"})
    usage = c.app.state.usage
    usage.add_bedrock(3, 0.01)
    r = c.get("/api/runtime")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    j = r.json()
    assert j["aws"] == {"running_on_aws": True, "platform": "Amazon EC2", "message": None,
                        "instance_type": "m7i-flex.large",
                        "availability_zone": "ap-southeast-2a", "region": "ap-southeast-2"}
    assert j["bedrock"]["model_id"] == "global.amazon.nova-2-lite-v1:0"
    assert j["bedrock"]["model_label"] == "Nova 2 Lite"
    assert j["bedrock"]["calls_today"] == 3 and j["bedrock"]["last_call_utc"].endswith("Z")
    assert j["bedrock"]["configured"] is False  # this test app has no Bedrock client
    assert j["app"]["opencv_version"].startswith("5.")
    assert j["app"]["rules_fingerprint"] == "ca4ff9bbf7b01c6c" and j["app"]["uptime_s"] >= 0
    # nothing sensitive: no id, address or key-like text anywhere in the answer
    text = json.dumps(j)
    for banned in ("i-0", "169.254", "AKIA", "arn:aws", "account", "secret", "token"):
        assert banned not in text
    # the same facts ride along in /api/health
    assert c.get("/api/health").json()["runtime"]["aws"]["instance_type"] == "m7i-flex.large"


def test_runtime_endpoint_off_aws_says_so(tmp_path, base_cfg) -> None:
    t0 = time.perf_counter()
    c = _runtime_client(tmp_path, base_cfg, lambda: None)
    j = c.get("/api/runtime").json()
    assert time.perf_counter() - t0 < 1.0
    assert j["aws"]["running_on_aws"] is False and j["aws"]["message"] == "not running on AWS"
    assert j["aws"]["instance_type"] is None and j["aws"]["availability_zone"] is None
    assert j["bedrock"]["calls_today"] == 0 and j["bedrock"]["last_call_utc"] is None


def test_runtime_default_probe_off_aws_is_fast(tmp_path, base_cfg) -> None:
    c = make_client(tmp_path, base_cfg)  # real probe; the test guard refuses the connection
    t0 = time.perf_counter()
    assert c.get("/api/runtime").json()["aws"]["running_on_aws"] is False
    assert time.perf_counter() - t0 < 1.0


def test_unreadable_fields_are_null_not_invented(tmp_path, base_cfg) -> None:
    c = _runtime_client(tmp_path, base_cfg, lambda: {"instance_type": None,
                                                     "availability_zone": "ap-southeast-2a",
                                                     "region": None})
    aws = c.get("/api/runtime").json()["aws"]
    assert aws["running_on_aws"] is True and aws["instance_type"] is None
    assert aws["availability_zone"] == "ap-southeast-2a" and aws["region"] is None


def test_metadata_answers_are_cached_hit_long_miss_short(base_cfg) -> None:
    now = [0.0]
    calls = []

    def probe():
        calls.append(1)
        return None if len(calls) == 1 else {"instance_type": "t3.micro",
                                              "availability_zone": "ap-southeast-2b",
                                              "region": "ap-southeast-2"}

    rt = Runtime(base_cfg, None, bedrock_configured=False, opencv_version="5.0.0",
                 fingerprint="x", imds=probe, clock=lambda: now[0])
    assert rt.snapshot()["aws"]["running_on_aws"] is False
    now[0] = 10
    rt.snapshot()
    assert len(calls) == 1                    # a miss is remembered for imds_miss_cache_s (30 s)
    now[0] = 31
    assert rt.snapshot()["aws"]["instance_type"] == "t3.micro" and len(calls) == 2
    now[0] = 3000
    rt.snapshot()
    assert len(calls) == 2                    # a hit is remembered for an hour
    assert rt.snapshot()["app"]["uptime_s"] == 3000


def test_usage_records_the_time_of_the_last_call_not_the_content(tmp_path, base_cfg) -> None:
    from gaffer.api.usage import Usage

    u = Usage(base_cfg, str(tmp_path / "u.json"), now=lambda: "2026-10-24T10:00:00Z")
    assert u.snapshot()["last_call_utc"] is None
    u.add_bedrock(0, 0.0)
    assert u.snapshot()["last_call_utc"] is None   # no call, no timestamp
    u.add_bedrock(2, 0.003, 100, 20)
    assert u.snapshot()["last_call_utc"] == "2026-10-24T10:00:00Z"
    again = Usage(base_cfg, str(tmp_path / "u.json"))  # survives a restart within the day
    assert again.snapshot()["last_call_utc"] == "2026-10-24T10:00:00Z"


# --------------------------------------------------------------------------- free disk


def test_disk_gate_arithmetic() -> None:
    assert disk_gate(6 * GB, floor_gb=5.0) is None
    assert disk_gate(4 * GB, floor_gb=5.0) == SERVER_FULL
    # the upload counts twice (the spooled body + the saved file)
    assert disk_gate(int(5.7 * GB), floor_gb=5.0, incoming_bytes=400_000_000) == SERVER_FULL
    assert disk_gate(int(5.9 * GB), floor_gb=5.0, incoming_bytes=400_000_000) is None
    assert "try a sample clip" in SERVER_FULL


def test_upload_is_refused_when_the_disk_is_nearly_full(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg, disk_free=lambda: 3 * GB)
    r = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT))
    assert r.status_code == 507
    assert r.json()["detail"] == "The demo server is full right now, please try a sample clip."
    assert not any((tmp_path / "api").glob("*/upload.*"))  # nothing was written
    ok = make_client(tmp_path / "ok", base_cfg, disk_free=lambda: 20 * GB)
    assert upload(ok, videos["straight"], pitch_points=json.dumps(STRAIGHT)).status_code == 201


def test_a_big_request_needs_room_for_both_copies(tmp_path, base_cfg) -> None:
    c = make_client(tmp_path, base_cfg, disk_free=lambda: int(5.5 * GB))
    r = c.post("/api/analyses", content=b"x", headers={
        "content-length": "400000000", "content-type": "multipart/form-data; boundary=b"})
    assert r.status_code == 507  # 5 GB floor + 2 x 0.4 GB > 5.5 GB


def test_samples_still_work_when_the_disk_is_low_but_not_empty(tmp_path, base_cfg,
                                                               videos) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["more_sample_clips"] = []
    cfg["api"]["sample_clip"] = {"path": str(videos["straight"]), "label": "Generated clip"}
    low = make_client(tmp_path / "low", cfg, disk_free=lambda: 3 * GB)
    assert low.post("/api/analyses/sample").status_code == 201    # floor for samples is 0.5 GB
    empty = make_client(tmp_path / "empty", cfg, disk_free=lambda: 100_000_000)
    r = empty.post("/api/analyses/sample")
    assert r.status_code == 507 and r.json()["detail"] == SERVER_FULL


def test_real_free_space_is_read_when_not_injected(tmp_path, base_cfg) -> None:
    import shutil

    if shutil.disk_usage(tmp_path).free < 8 * GB:
        pytest.skip("this machine has less than 8 GB free")
    c = make_client(tmp_path, base_cfg)
    r = c.post("/api/analyses", files={"video": ("x.avi", b"x", "video/x")})
    assert r.status_code == 415  # this disk has room (>= 5 GB): the gate let it reach the checks


# --------------------------------------------------------------------------- retention


def _fake_analysis(c: Any, aid: str, status: str, finished: datetime | None,
                   *, with_results: bool = True) -> Path:
    """An analysis folder as the worker leaves it: raw upload, results, first frame."""
    jobs, storage = c.app.state.jobs, c.app.state.storage
    d = storage.local_dir(aid)
    (d / "upload.mp4").write_bytes(b"v" * 4096)
    (d / "first_frame.jpg").write_bytes(b"jpg")
    if with_results:
        (d / "match_state.json").write_text("{}", encoding="utf-8")
        (d / "timeline.json").write_text("{}", encoding="utf-8")
    stamp = finished.strftime("%Y-%m-%dT%H:%M:%SZ") if finished else None
    jobs.create(aid, status=status, stage="done" if status == "done" else "uploading",
                **({"finished_utc": stamp} if stamp and status == "done" else {}))
    jobs._statuses[aid]["updated_utc"] = stamp or jobs._statuses[aid]["updated_utc"]
    return d


def test_retention_deletes_only_expired_raw_videos_and_keeps_the_results(tmp_path,
                                                                         base_cfg) -> None:
    c = make_client(tmp_path, base_cfg)
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    old = now - timedelta(hours=25)
    young = now - timedelta(hours=23)
    d_old = _fake_analysis(c, "aaaaaa111111", "done", old)
    d_young = _fake_analysis(c, "bbbbbb222222", "done", young)
    d_failed = _fake_analysis(c, "cccccc333333", "failed", old, with_results=False)
    d_run = _fake_analysis(c, "dddddd444444", "running", old)
    d_queued = _fake_analysis(c, "eeeeee555555", "queued", old)
    ret = Retention(base_cfg, c.app.state.storage, c.app.state.jobs, now=lambda: now)
    out = ret.sweep()
    assert out["videos"] == 2 and out["bytes"] == 2 * 4096 and out["expired_waiting"] == 0
    assert not (d_old / "upload.mp4").exists() and not (d_failed / "upload.mp4").exists()
    assert (d_young / "upload.mp4").exists()                    # inside the retention
    assert (d_run / "upload.mp4").exists() and (d_queued / "upload.mp4").exists()  # never
    for kept in ("match_state.json", "timeline.json", "first_frame.jpg", "status.json"):
        assert (d_old / kept).exists(), kept                     # results stay
    st = c.get("/api/analyses/aaaaaa111111").json()
    assert st["status"] == "done" and st["video_deleted_utc"] == "2026-10-25T12:00:00Z"
    assert ret.sweep() == {"videos": 0, "bytes": 0, "expired_waiting": 0}   # idempotent
    later = Retention(base_cfg, c.app.state.storage, c.app.state.jobs,
                      now=lambda: now + timedelta(hours=2))
    assert later.sweep()["videos"] == 1 and not (d_young / "upload.mp4").exists()


def test_retention_closes_an_abandoned_pitch_step(tmp_path, base_cfg) -> None:
    c = make_client(tmp_path, base_cfg)
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    d = _fake_analysis(c, "ffffff666666", "needs_confirmation", now - timedelta(hours=30))
    out = Retention(base_cfg, c.app.state.storage, c.app.state.jobs, now=lambda: now).sweep()
    assert out["expired_waiting"] == 1 and not (d / "upload.mp4").exists()
    st = c.get("/api/analyses/ffffff666666").json()
    assert st["status"] == "failed" and "Upload it again" in st["error"]


def test_retention_also_removes_the_reanalysis_cache_of_that_upload(tmp_path, base_cfg) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["agent"]["vision"]["cache_dir"] = str(tmp_path / "cache")
    c = make_client(tmp_path, cfg)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "up_aaaaaa111111_100-200_4fps_x.json").write_text("{}", encoding="utf-8")
    (cache / "up_bbbbbb222222_100-200_4fps_x.json").write_text("{}", encoding="utf-8")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    _fake_analysis(c, "aaaaaa111111", "done", now - timedelta(hours=30))
    Retention(cfg, c.app.state.storage, c.app.state.jobs, now=lambda: now).sweep()
    assert not list(cache.glob("up_aaaaaa111111_*"))
    assert list(cache.glob("up_bbbbbb222222_*"))   # someone else's cache is untouched


def test_results_are_still_served_after_the_raw_video_is_deleted(tmp_path, base_cfg,
                                                                 videos) -> None:
    """The desk needs nothing from the raw file after the analysis: result, evidence and chat
    context come from the stored results; the video plays from the visitor's own browser."""
    c = make_client(tmp_path, base_cfg)
    aid = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).json()["id"]
    c.app.state.jobs.run_one(aid)
    assert c.get(f"/api/analyses/{aid}").json()["status"] == "done"
    before = c.get(f"/api/analyses/{aid}/result").json()
    d = c.app.state.storage.local_dir(aid)
    assert (d / "upload.mp4").exists()
    far = datetime.now(UTC) + timedelta(hours=25)
    out = Retention(base_cfg, c.app.state.storage, c.app.state.jobs, now=lambda: far).sweep()
    assert out["videos"] == 1 and not list(d.glob("upload.*"))
    after = c.get(f"/api/analyses/{aid}/result").json()
    assert after == before
    assert c.get(f"/api/analyses/{aid}/frame").status_code == 200
    assert c.get(f"/api/events?match_id=up_{aid}").status_code == 200
    # the pitch step is closed for a finished analysis anyway
    assert c.post(f"/api/analyses/{aid}/pitch", json={"confirmed": True}).status_code == 409


def test_retention_thread_runs_a_sweep_at_start(tmp_path, base_cfg) -> None:
    c = make_client(tmp_path, base_cfg)
    old = datetime.now(UTC) - timedelta(hours=40)
    d = _fake_analysis(c, "999999aaaaaa", "done", old)
    ret = Retention(base_cfg, c.app.state.storage, c.app.state.jobs)
    ret.start()
    for _ in range(100):
        if not (d / "upload.mp4").exists():
            break
        time.sleep(0.05)
    ret.stop()
    assert not (d / "upload.mp4").exists()


def test_parse_utc() -> None:
    assert parse_utc("2026-10-24T10:00:00Z") == datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
    assert parse_utc("nonsense") is None and parse_utc(None) is None


# --------------------------------------------------------------------------- the queue


def test_one_analysis_at_a_time_the_rest_wait_with_a_live_position(tmp_path, base_cfg,
                                                                   videos) -> None:
    ran: list[str] = []

    def runner(mgr: Any, aid: str) -> None:
        ran.append(aid)
        assert mgr.current == aid and not any(
            s.get("status") == "running" and s["id"] != aid for s in mgr._statuses.values())
        mgr.update(aid, status="done", stage="done", progress=1.0)

    c = make_client(tmp_path, base_cfg, runner=runner)   # worker off: we drive it by hand
    ids = [upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).json()["id"]
           for _ in range(3)]
    sts = [c.get(f"/api/analyses/{i}").json() for i in ids]
    assert [s["status"] for s in sts] == ["queued"] * 3
    assert [s["queue_position"] for s in sts] == [0, 1, 2]       # analyses ahead of each
    assert c.get("/api/health").json()["analyses"] == {"running": None, "queued": 3}
    jobs = c.app.state.jobs
    assert jobs._queue.get_nowait() == ids[0]                      # what the worker does
    jobs.run_one(ids[0])
    assert ran == [ids[0]]
    # the others moved up WITHOUT being touched: the position is computed when it is asked for
    after = [c.get(f"/api/analyses/{i}").json() for i in ids[1:]]
    assert [a["queue_position"] for a in after] == [0, 1]


def test_queue_position_counts_the_running_analysis(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg)
    a = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).json()["id"]
    b = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).json()["id"]
    jobs = c.app.state.jobs
    assert jobs.ahead_of(a) == 0 and jobs.ahead_of(b) == 1
    jobs.current = "someone-else"                                  # one is running right now
    assert jobs.ahead_of(a) == 1 and jobs.ahead_of(b) == 2
    jobs.current = None


def test_a_full_queue_refuses_with_a_busy_message(tmp_path, base_cfg, videos) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["jobs"]["max_queued"] = 2
    c = make_client(tmp_path, cfg)
    for _ in range(2):
        assert upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).status_code == 201
    r = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT))
    assert r.status_code == 503 and "busy" in r.json()["detail"]
