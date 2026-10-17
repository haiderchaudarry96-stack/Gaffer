"""FastAPI backend (Phase 4): TestClient, generated videos, mocked LLM, no network."""

from __future__ import annotations

import copy
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from gaffer.agent.alerts import AlertStore
from gaffer.api.chat import SAFE_ANSWER, check_answer
from gaffer.api.jobs import Progress, rules_fingerprint
from gaffer.api.main import create_app
from gaffer.api.storage import LocalStorage, StorageError
from gaffer.api.usage import Usage
from gaffer.aws.s3 import S3Storage
from gaffer.config import load_config
from gaffer.llm.bedrock_client import BedrockCallError, ChatResult, ToolUse
from gaffer.perception.pitch import render_pitch_view

sys.path.insert(0, str(Path(__file__).parent))  # pytest's importlib mode: tests/ is not on it
from videogen import write_switch_video, write_video  # noqa: E402

STRAIGHT = [[90, 70], [870, 72], [868, 540], [92, 538]]
DEMO_ALERT = "alr_teamtrack_top_w900_1260_evt_003"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may open a network connection (AF_UNIX sockets stay allowed)."""
    real = socket.socket.connect

    def guard(self, address):
        if self.family == socket.AF_UNIX:
            return real(self, address)
        raise RuntimeError(f"network access is disabled in tests ({address})")

    monkeypatch.setattr(socket.socket, "connect", guard)


# --------------------------------------------------------------------------- fakes / fixtures


class FakeLLM:
    """Scripted Converse client: each item is [(tool, args), ...], a text answer, or an
    exception."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, system=None, tools=None, tool_choice=None, model_id=None,
             max_tokens=None, temperature=None, purpose=""):
        self.calls.append({"messages": copy.deepcopy(messages), "purpose": purpose,
                           "tools": [t["toolSpec"]["name"] for t in tools or []]})
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        usage = {"input_tokens": 1500, "output_tokens": 60, "total_tokens": 1560}
        model = model_id or "global.amazon.nova-2-lite-v1:0"
        if isinstance(item, str):
            msg = {"role": "assistant", "content": [{"text": item}]}
            return ChatResult(item, [], "end_turn", msg, model, 1.0, 1, usage)
        uses = [ToolUse(f"tu{len(self.calls)}_{i}", n, a) for i, (n, a) in enumerate(item)]
        msg = {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": u.tool_use_id, "name": u.name, "input": u.input}}
            for u in uses]}
        return ChatResult("", uses, "tool_use", msg, model, 1.0, 1, usage)


@pytest.fixture(scope="module")
def base_cfg():
    return load_config()


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("videos")
    out = {"straight": write_video(d / "my match.mp4"),
           "cropped": write_video(d / "cropped.mp4",
                                  corners=[[-80, -50], [1040, -40], [1040, 650], [-80, 640]])}
    # a panorama-shaped clip and a non-video file
    w = cv2.VideoWriter(str(d / "pano.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 5, (1600, 400))
    for k in range(30):
        w.write(render_pitch_view((1600, 400), [[50, 20], [1550, 20], [1550, 380], [50, 380]],
                                  seed=k))
    w.release()
    out["pano"] = d / "pano.mp4"
    (d / "notes.mp4").write_bytes(b"this is not a video" * 100)
    out["broken"] = d / "notes.mp4"
    return out


def make_client(tmp_path: Path, cfg: dict[str, Any], llm: Any = None, **kw: Any
                ) -> TestClient:
    usage = Usage(cfg, str(tmp_path / "usage.json"))
    factory = (lambda: llm) if llm is not None else kw.pop("llm_factory", None)
    app = create_app(cfg, storage=LocalStorage(tmp_path / "api"), llm_factory=factory,
                     usage=usage, alerts_path=tmp_path / "alerts.jsonl",
                     start_worker=kw.pop("start_worker", False),
                     chat_trace=tmp_path / "chat_trace.jsonl", **kw)
    return TestClient(app)


@pytest.fixture
def client(tmp_path, base_cfg):
    return make_client(tmp_path, base_cfg)


def upload(c: TestClient, path: Path, name: str | None = None, **data: Any):
    return c.post("/api/analyses", files={"video": (name or path.name, path.read_bytes(),
                                                    "video/mp4")}, data=data)


# --------------------------------------------------------------------------- health / demo


def test_health(client) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok" and j["opencv_version"].startswith("5.")
    assert j["rules_fingerprint"] == "ca4ff9bbf7b01c6c"
    assert j["bedrock"] == "not configured" and j["demo_available"]


def test_rules_fingerprint_is_frozen(base_cfg) -> None:
    assert rules_fingerprint(base_cfg) == "ca4ff9bbf7b01c6c"


def test_demo_bundle_has_the_frontend_shapes(client) -> None:
    r = client.get("/api/demo")
    assert r.status_code == 200
    j = r.json()
    for k in ("id", "label", "match_state", "timeline", "alerts", "trace", "report",
              "explanations", "team_model", "run_rows", "report_markdown"):
        assert k in j
    assert j["match_state"]["contract_version"] == "1.0"
    assert j["timeline"]["contract_version"] == "1.0"
    ev = {e["id"]: e for e in j["timeline"]["events"]}
    assert ev["evt_003"]["status"] == "confirmed" and ev["evt_007"]["status"] == "rejected"
    assert ev["evt_003"]["verification"]["evidence_image"].endswith(
        "/api/demo/evidence/evt_003.jpg")
    assert j["alerts"][0]["alert_id"] == DEMO_ALERT
    assert j["alerts"][0]["evidence_image"].startswith("http://testserver/api/demo/")
    assert {s["kind"] for s in j["trace"]} >= {"card", "tool_call", "decision"}
    assert j["report"]["source"] and "inputs" in j["report"]
    assert all(c["set"] == "w900" for c in j["explanations"])
    assert client.get(j["files"]["match_state"].replace("http://testserver", "")
                      ).status_code == 200


def test_demo_files_are_whitelisted(client) -> None:
    assert client.get("/api/demo/files/evt_003.jpg").status_code == 200
    assert client.get("/api/demo/evidence/evt_003.jpg").headers["content-type"] == "image/jpeg"
    for bad in ("config.yaml", "..%2F..%2Fconfig.yaml", "explanations.json.bak"):
        assert client.get(f"/api/demo/files/{bad}").status_code == 404


# --------------------------------------------------------------------------- refusals


def test_refuses_other_file_types(client, videos) -> None:
    r = client.post("/api/analyses", files={"video": ("match.avi", b"x" * 100, "video/x")})
    assert r.status_code == 415 and "MP4" in r.json()["detail"]


def test_refuses_a_file_opencv_cannot_read(client, videos) -> None:
    r = upload(client, videos["broken"])
    assert r.status_code == 422 and "OpenCV could not" in r.json()["detail"]


def test_refuses_too_long_and_too_large(tmp_path, base_cfg, videos) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["uploads"]["max_duration_s"] = 6
    c = make_client(tmp_path / "a", cfg)
    r = upload(c, videos["straight"])
    assert r.status_code == 422
    assert "limit is 0.1 minutes" in r.json()["detail"] and "Trim" in r.json()["detail"]
    cfg["api"]["uploads"]["max_duration_s"] = 360
    cfg["api"]["uploads"]["max_bytes"] = 10_000
    cfg["api"]["uploads"]["chunk_bytes"] = 4096
    c = make_client(tmp_path / "b", cfg)
    r = upload(c, videos["straight"])
    assert r.status_code == 413 and "upload limit" in r.json()["detail"]
    assert not any((tmp_path / "b" / "api").glob("*/upload.mp4"))  # nothing left behind


def test_refuses_side_camera_and_panoramas(client, videos) -> None:
    r = upload(client, videos["straight"], name="F_20220220_1_1680_1710.mp4")
    assert r.status_code == 422 and "top-down" in r.json()["detail"]
    r = upload(client, videos["pano"])
    assert r.status_code == 422 and "panorama" in r.json()["detail"]


def test_known_source_flag_must_match_a_teamtrack_clip(client, videos) -> None:
    r = upload(client, videos["straight"], known_source="true")
    assert r.status_code == 422 and "TeamTrack" in r.json()["detail"]
    r = upload(client, videos["straight"], known_source="maybe")
    assert r.status_code == 422


def test_refuses_bad_pitch_points_at_upload(client, videos) -> None:
    tilted = json.dumps([[380, 250], [700, 250], [950, 590], [10, 590]])
    r = upload(client, videos["straight"], pitch_points=tilted)
    assert r.status_code == 422 and "steep" in r.json()["detail"]
    r = upload(client, videos["straight"], pitch_points="[[1, 2]]")
    assert r.status_code == 422 and "4" in r.json()["detail"]


# --------------------------------------------------------------------------- status flow


def test_flow_needs_confirmation_then_done(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg)
    r = upload(c, videos["straight"])
    assert r.status_code == 201
    st = r.json()
    assert st["status"] == "needs_confirmation" and st["stage"] == "uploading"
    corners = np.array(st["pitch"]["corners"])
    assert np.abs(corners - STRAIGHT).max() < 4.0
    assert st["pitch"]["detection"]["accepted"]
    pv = c.get(st["links"]["pitch_preview"].replace("http://testserver", ""))
    assert pv.status_code == 200 and pv.content[:2] == b"\xff\xd8"  # JPEG
    aid = st["id"]
    assert c.get(f"/api/analyses/{aid}/result").status_code == 409  # not analysed yet
    r = c.post(f"/api/analyses/{aid}/pitch", json={"confirmed": True})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert r.json()["pitch"]["method"] == "four_corner_auto_confirmed"
    # the pitch step is closed now
    assert c.post(f"/api/analyses/{aid}/pitch", json={"confirmed": True}).status_code == 409
    c.app.state.jobs.run_one(aid)
    st = c.get(f"/api/analyses/{aid}").json()
    assert st["status"] == "done" and st["stage"] == "done" and st["progress"] == 1.0
    assert st["summary"]["rules_fingerprint"] == "ca4ff9bbf7b01c6c"
    assert st["summary"]["arm"] == "rules"  # no Bedrock configured
    pd = st["progress_detail"]
    assert pd["frames"]["done"] == pd["frames"]["total"] > 0
    assert set(pd["stage_timings_s"]) >= {"detecting", "teams", "agent"}
    res = c.get(f"/api/analyses/{aid}/result").json()
    assert res["match_state"]["source"] == "video"
    assert res["match_state"]["meta"]["opencv_version"].startswith("5.")
    assert res["timeline"]["contract_version"] == "1.0"
    assert res["report"]["source"] == "code template" and res["report"]["inputs"]["match"]
    assert isinstance(res["alerts"], list) and isinstance(res["trace"], list)


def test_flow_needs_corners_then_coach_points(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg)
    st = upload(c, videos["cropped"]).json()
    assert st["status"] == "needs_corners"
    assert st["pitch"]["corners"] is None and "mark the 4" in st["pitch"]["message"]
    aid = st["id"]
    r = c.post(f"/api/analyses/{aid}/pitch", json={"confirmed": True})
    assert r.status_code == 409  # nothing to confirm: never analyse unconfirmed corners
    assert c.get(f"/api/analyses/{aid}").json()["status"] == "needs_corners"
    r = c.post(f"/api/analyses/{aid}/pitch", json={"pitch_points": [[1, 2], [3, 4]]})
    assert r.status_code == 422
    pts = [{"x": 20, "y": 20}, {"x": 940, "y": 20}, {"x": 940, "y": 580}, {"x": 20, "y": 580}]
    r = c.post(f"/api/analyses/{aid}/pitch", json={"pitch_points": pts})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert r.json()["pitch"]["method"] == "four_corner_coach"


def test_frontend_start_scales_points_and_straight_down(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg)
    aid = upload(c, videos["straight"]).json()["id"]
    # the browser showed the frame at half size: points are scaled to video pixels
    half = [{"x": x / 2, "y": y / 2} for x, y in STRAIGHT]
    r = c.post(f"/api/analyses/{aid}/start",
               json={"points": half, "frame": {"width": 480, "height": 300, "t_s": 0.5},
                     "straight_down": False})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert np.abs(np.array(r.json()["pitch"]["corners"]) - STRAIGHT).max() < 1.0
    assert r.json()["source"]["reference_frame"] == 5  # 0.5 s at 10 fps
    aid2 = upload(c, videos["straight"]).json()["id"]
    r = c.post(f"/api/analyses/{aid2}/start",
               json={"points": half, "frame": None, "straight_down": True})
    assert r.status_code == 200
    assert r.json()["pitch"]["corners"] == [[0.0, 0.0], [959.0, 0.0], [959.0, 599.0],
                                            [0.0, 599.0]]


def test_known_teamtrack_clip_skips_the_pitch_step(tmp_path, base_cfg) -> None:
    p = tmp_path / "D_20220220_1_1530_1560.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 2, (3840, 2160))
    frame = render_pitch_view((3840, 2160), [[474, 118], [3412, 116], [3410, 1994], [475, 1994]],
                              noise=0.0)
    for _ in range(12):
        w.write(frame)
    w.release()
    c = make_client(tmp_path, base_cfg)
    st = upload(c, p).json()
    assert st["status"] == "queued"
    assert st["source"]["kind"] == "teamtrack_top"
    assert st["pitch"]["method"].startswith("saved_31_point")
    clips = json.loads((tmp_path / "api" / st["id"] / "video.clips.json").read_text())
    assert clips["clips"][0]["start_s"] == 1530.0  # match time from the file name
    # the frontend's /start on an already calibrated clip changes nothing
    r = c.post(f"/api/analyses/{st['id']}/start",
               json={"points": [{"x": 0, "y": 0}] * 4, "straight_down": False})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    # known_source=false: treated as any other video (pitch step)
    st2 = upload(c, p, known_source="false").json()
    assert st2["status"] in ("needs_confirmation", "needs_corners")


def test_unknown_analysis_and_queue_limit(tmp_path, base_cfg, videos) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["jobs"]["max_queued"] = 1
    c = make_client(tmp_path, cfg)
    assert c.get("/api/analyses/abcdef123456").status_code == 404
    assert c.get("/api/analyses/../../etc").status_code == 404
    upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT))
    r = upload(c, videos["straight"])
    assert r.status_code == 503 and "busy" in r.json()["detail"]


def test_worker_thread_runs_queued_analyses(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg, start_worker=True)
    aid = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).json()["id"]
    seen = set()
    for _ in range(300):
        st = c.get(f"/api/analyses/{aid}").json()
        seen.add(st["status"])
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert st["status"] == "done", st.get("error")
    assert c.get(f"/api/analyses/{aid}/result").status_code == 200


def test_pipeline_failure_is_coach_readable(tmp_path, base_cfg) -> None:
    p = tmp_path / "car_park.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10, (960, 600))
    rng = np.random.default_rng(42)
    for _ in range(80):  # grey tarmac, no pitch, nobody on it
        w.write(np.clip(110 + rng.normal(0, 3, (600, 960, 3)), 0, 255).astype(np.uint8))
    w.release()
    c = make_client(tmp_path, base_cfg)
    aid = upload(c, p, pitch_points=json.dumps(STRAIGHT)).json()["id"]
    c.app.state.jobs.run_one(aid)
    st = c.get(f"/api/analyses/{aid}").json()
    assert st["status"] == "failed"
    assert "enough players" in st["error"] and "error_detail" not in st


@pytest.mark.slow
def test_upload_end_to_end_agent_confirms_a_real_change(tmp_path, base_cfg) -> None:
    """3 min generated match, White 4-4-2 -> 3-5-2 at 1:15: pipeline -> engine candidate ->
    agent (camera check, OpenCV re-analysis, evidence) -> pending alert -> coach approves."""
    p = write_switch_video(tmp_path / "switch.mp4")
    c = make_client(tmp_path, base_cfg)
    aid = upload(c, p, pitch_points=json.dumps(STRAIGHT)).json()["id"]
    c.app.state.jobs.run_one(aid)
    st = c.get(f"/api/analyses/{aid}").json()
    assert st["status"] == "done", st.get("error")
    res = c.get(f"/api/analyses/{aid}/result").json()
    ex = res["explanations"]
    hit = [e for e in ex if e["team_side"] == "home" and e["change"] == "4-4-2 -> 3-5-2"]
    assert hit and hit[0]["decision"] == "confirmed"
    assert hit[0]["evidence_image"].startswith("http://testserver/api/analyses/")
    calls = [s.get("tool") for s in res["trace"] if s.get("kind") == "tool_call"]
    assert "check_frame_quality" in calls and "reanalyse_window" in calls
    alert = res["alerts"][0]
    assert alert["status"] == "pending" and alert["alert_id"].startswith(f"alr_up_{aid}_")
    img = c.get(alert["evidence_image"].replace("http://testserver", ""))
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"
    r = c.post(f"/api/alerts/{alert['alert_id']}/approve", json={"note": "seen it"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert c.get(f"/api/analyses/{aid}/result").json()["alerts"][0]["status"] == "approved"


# --------------------------------------------------------------------------- alerts


def test_alerts_approve_reject(tmp_path, base_cfg) -> None:
    c = make_client(tmp_path, base_cfg)
    r = c.post(f"/api/alerts/{DEMO_ALERT}/approve", json={"note": "good spot"})
    assert r.status_code == 200
    a = r.json()
    assert a["status"] == "approved" and a["coach_note"] == "good spot"
    assert a["evidence_image"].endswith("/api/demo/evidence/evt_003.jpg")
    assert c.post(f"/api/alerts/{DEMO_ALERT}/reject").status_code == 409  # decided once
    assert c.get("/api/demo").json()["alerts"][0]["status"] == "approved"
    lines = (tmp_path / "alerts.jsonl").read_text().splitlines()
    assert len(lines) == 2  # appended: pending copy + decision (history never rewritten)
    assert c.post("/api/alerts/alr_nope_evt_001/approve").status_code == 404
    # an upload's alert (as the agent writes it) is rejected through the same store
    s = AlertStore(tmp_path / "alerts.jsonl")
    s.create("up_abcdef123456", "evt_002", 75.0, "White: 4-4-2 -> 3-5-2 (1:15)",
             "Verified: ...", "...", "outputs/api/abcdef123456/evidence/x/evt_002.jpg")
    r = c.post("/api/alerts/alr_up_abcdef123456_evt_002/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["evidence_image"].endswith("/api/analyses/abcdef123456/evidence/evt_002.jpg")


# --------------------------------------------------------------------------- chat


def ask(c: TestClient, q: str, visitor: str = "v1", match_id: str = "w900_1260"):
    return c.post("/api/chat", json={"match_id": match_id, "question": q, "history": []},
                  headers={"X-Visitor-Id": visitor})


def test_chat_grounded_answer_with_citations(tmp_path, base_cfg) -> None:
    llm = FakeLLM([[("get_decision", {"event_id": "evt_003"})],
                   "White switched from 4-4-2 to 3-4-3 at 16:30 and the agent confirmed it "
                   "[R1] [evt_003]."])
    c = make_client(tmp_path, base_cfg, llm=llm)
    r = ask(c, "What did White change at 16:30?")
    assert r.status_code == 200, r.json()
    j = r.json()
    assert j["grounded"] and j["citations"] == ["R1", "evt_003"]
    assert j["sources"]["R1"]["tool"] == "get_decision" and j["trace_id"].startswith("chat_")
    assert j["questions_left_today"] == 19
    tools = llm.calls[0]["tools"]
    assert "get_decision" in tools and "reanalyse_window" not in tools  # read-only
    assert "propose_alert" not in tools and "record_decision" not in tools
    # the tool result the model saw is the agent's real decision
    res = llm.calls[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["json"]
    assert res["decision"] == "confirmed" and res["clock"] == "16:30"
    log = [json.loads(x) for x in (tmp_path / "chat_trace.jsonl").read_text().splitlines()]
    assert log[0]["citations"] == ["R1", "evt_003"]


def test_chat_ungrounded_numbers_are_replaced(tmp_path, base_cfg) -> None:
    llm = FakeLLM([[("get_decision", {"event_id": "evt_003"})],
                   "White held 3-4-3 in 77% of windows [R1].",  # 77 is not in the result
                   "White held 3-4-3 for 12 minutes [R1]."])
    c = make_client(tmp_path, base_cfg, llm=llm)
    j = ask(c, "How long did White keep it?").json()
    assert j["answer"] == SAFE_ANSWER and not j["grounded"] and j["citations"] == []


def test_check_answer_rules() -> None:
    results = {"R1": {"ref": "R1", "clock": "16:30", "share": 0.91, "windows": 11,
                      "change": "4-4-2 -> 3-4-3"}}
    ev = {"evt_003"}
    assert check_answer("White went to 3-4-3 at 16:30, held in 91% of 11 windows [R1].",
                        results, ev) == []
    assert check_answer("No number here, see [evt_003].", results, ev) == []
    assert check_answer("Held 91% of windows.", results, ev)  # numbers need a citation
    assert check_answer("At 17:45 [R1].", results, ev)  # clock not in results
    assert check_answer("See [R7].", results, ev)  # unknown ref
    assert check_answer("See [evt_099].", results, ev)  # unknown candidate


def test_chat_visitor_limit(tmp_path, base_cfg) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["chat"]["max_questions_per_visitor_per_day"] = 1
    llm = FakeLLM(["Ask me about a time or a change [evt_003].",
                   "Ask me about a time or a change [evt_003]."])
    c = make_client(tmp_path, cfg, llm=llm)
    assert ask(c, "hello", visitor="a").status_code == 200
    r = ask(c, "hello again", visitor="a")
    assert r.status_code == 429 and "limit of 1 questions" in r.json()["detail"]
    assert ask(c, "hello", visitor="b").status_code == 200  # another visitor
    usage = json.loads((tmp_path / "usage.json").read_text())
    assert "a" not in usage["visitors"] and len(usage["visitors"]) == 2  # hashed ids


def test_chat_global_daily_cap(tmp_path, base_cfg) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["bedrock_daily"]["max_calls"] = 1
    llm = FakeLLM(["Nothing numeric [evt_003].", "never sent"])
    c = make_client(tmp_path, cfg, llm=llm)
    assert ask(c, "first").status_code == 200
    r = ask(c, "second", visitor="other")
    assert r.status_code == 429 and "daily limit" in r.json()["detail"]
    assert len(llm.calls) == 1


def test_chat_token_budget_per_question(tmp_path, base_cfg) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["api"]["chat"]["max_tokens_per_request"] = 3000  # room for one call (1560 tokens), not two
    llm = FakeLLM([[("get_match_overview", {})], "unused"])
    c = make_client(tmp_path, cfg, llm=llm)
    j = ask(c, "Tell me everything").json()
    assert "more look-ups" in j["answer"] and len(llm.calls) == 1


def test_chat_bedrock_unreachable(tmp_path, base_cfg) -> None:
    llm = FakeLLM([BedrockCallError("Could not connect to Bedrock.", "check the network",
                                    "Connection")])
    c = make_client(tmp_path, base_cfg, llm=llm)
    r = ask(c, "anything")
    assert r.status_code == 503 and "can't be reached" in r.json()["detail"]
    usage = json.loads((tmp_path / "usage.json").read_text())
    assert sum(usage["visitors"].values()) == 0  # the question was given back


def test_chat_without_bedrock_and_bad_targets(tmp_path, base_cfg, videos) -> None:
    c = make_client(tmp_path, base_cfg)
    r = ask(c, "anything")
    assert r.status_code == 503 and "not configured" in r.json()["detail"]
    assert ask(c, "x", match_id="abcdef123456").status_code == 404
    aid = upload(c, videos["straight"]).json()["id"]
    assert ask(c, "x", match_id=aid).status_code == 409  # not analysed yet


def test_chat_over_a_finished_upload(tmp_path, base_cfg, videos) -> None:
    llm = FakeLLM([[("get_timeline", {})], "White's shape is not settled yet [R1]."])
    c = make_client(tmp_path, base_cfg)
    aid = upload(c, videos["straight"], pitch_points=json.dumps(STRAIGHT)).json()["id"]
    c.app.state.jobs.run_one(aid)
    c.app.state.chat.llm_factory = lambda: llm
    r = ask(c, "What shape is White in?", match_id=aid)
    assert r.status_code == 200 and r.json()["citations"] == ["R1"]


# --------------------------------------------------------------------------- units


def test_progress_is_monotonic_and_measured(base_cfg) -> None:
    snaps: list[dict[str, Any]] = []
    p = Progress(base_cfg, 120.0, snaps.append)
    p.frames_started(480)
    first = p.snapshot()
    assert first["progress_detail"]["eta_basis"] == "prior" and first["eta_s"] > 0
    for k in range(1, 50):
        p.frame_done(k)
    mid = p.snapshot()
    assert mid["progress_detail"]["eta_basis"] == "measured"
    assert mid["progress"] >= first["progress"]
    p.set_stage("teams")
    p.set_stage("agent")
    p.candidates_started(2)
    p.candidate_done(1.0)
    p.set_stage("done")
    end = p.snapshot()
    assert end["progress"] == 1.0 and end["eta_s"] is None
    assert [s["progress"] for s in snaps] == sorted(s["progress"] for s in snaps)


def test_usage_persists_and_resets_daily(tmp_path, base_cfg) -> None:
    day = ["2026-10-17"]
    u = Usage(base_cfg, str(tmp_path / "u.json"), clock=lambda: day[0])
    u.add_bedrock(3, 0.01)
    assert u.take_question("x") == 19
    u2 = Usage(base_cfg, str(tmp_path / "u.json"), clock=lambda: day[0])
    assert u2.bedrock_left()[0] == 297
    day[0] = "2026-10-18"
    assert u2.bedrock_left() == (300, 1.0) and u2.take_question("x") == 19


def test_local_storage_rejects_bad_keys(tmp_path) -> None:
    s = LocalStorage(tmp_path)
    s.write_bytes("abcdef123456/a/b.json", b"{}")
    assert s.read_bytes("abcdef123456/a/b.json") == b"{}"
    for bad in ("../x/y", "abcdef123456/../../y", "ABC/x", "abcdef123456"):
        with pytest.raises(StorageError):
            s.read_bytes(bad)
    assert s.list_ids() == ["abcdef123456"]


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_file(self, path, bucket, key):
        self.objects[key] = Path(path).read_bytes()

    def get_object(self, Bucket, Key):  # noqa: N803 (boto3 names)
        if Key not in self.objects:
            raise KeyError(Key)

        class Body:
            def __init__(self, b):
                self.b = b

            def read(self):
                return self.b

        return {"Body": Body(self.objects[Key])}

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)

    def list_objects_v2(self, Bucket, Prefix, Delimiter):  # noqa: N803
        ids = {k[len(Prefix):].split("/")[0] for k in self.objects if k.startswith(Prefix)}
        return {"CommonPrefixes": [{"Prefix": f"{Prefix}{i}/"} for i in sorted(ids)]}


def test_s3_storage_publishes_and_reads_back(tmp_path) -> None:
    fake = FakeS3()
    s = S3Storage("bucket", "analyses", tmp_path / "a", client=fake)
    s.write_bytes("abcdef123456/status.json", b'{"ok": 1}')
    assert fake.objects == {}  # status writes stay local
    s.publish("abcdef123456", ["status.json", "missing.json"])
    assert fake.objects == {"analyses/abcdef123456/status.json": b'{"ok": 1}'}
    s2 = S3Storage("bucket", "analyses", tmp_path / "b", client=fake)  # fresh machine
    assert s2.exists("abcdef123456/status.json") and s2.list_ids() == ["abcdef123456"]
    assert s2.read_bytes("abcdef123456/status.json") == b'{"ok": 1}'
    with pytest.raises(StorageError):
        s2.read_bytes("abcdef123456/nope.json")
