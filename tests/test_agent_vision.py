"""Video backend of the agent's vision tools (build step 5) on generated frames: no TeamTrack
files, no Bedrock. The pipeline run, the video source and the drone geometry are stubbed where
they would need real footage; the OpenCV measurements themselves run for real."""

from __future__ import annotations

import copy
import dataclasses
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest

from gaffer.agent.alerts import AlertStore
from gaffer.agent.context import MatchContext
from gaffer.agent.loop import AgentRunner, RateLimiter, TraceWriter, make_budget
from gaffer.agent.tools import Toolbox
from gaffer.agent.verify import PassEvidence, VerifyConfig, evaluate
from gaffer.agent.vision import (
    OverBudget,
    VideoBackend,
    VisionConfig,
    estimate_motion,
    measure_quality,
)
from gaffer.config import load_config
from gaffer.perception.drift import FrameGeometry
from gaffer.perception.pitch import HomographyMapper, PitchModel
from gaffer.schema import SourceVideo, parse_match_state
from gaffer.synthetic import Change, Schedule, generate_match
from gaffer.tactics.formation import UNCERTAIN

CW, CH = 1600, 900  # canvas the frames are cut from
FW, FH = 960, 540  # frame size
S = 13.0  # canvas px per metre


# --------------------------------------------------------------------------- generated frames


def _pitch_to_canvas() -> np.ndarray:
    """3x3 homography pitch metres -> canvas pixels (y up on the pitch, down in the image)."""
    ox, oy = (CW - 105 * S) / 2, (CH - 68 * S) / 2
    return np.array([[S, 0, ox], [0, -S, oy + 68 * S], [0, 0, 1]], float)


def _canvas() -> np.ndarray:
    rng = np.random.default_rng(42)
    img = np.full((CH, CW, 3), (45, 120, 45), np.uint8)
    img = cv2.add(img, rng.integers(0, 25, (CH, CW, 1), dtype=np.uint8).repeat(3, 2))
    H = _pitch_to_canvas()
    mapper = HomographyMapper(np.linalg.inv(H))
    for poly in PitchModel(105.0, 68.0).lines(0.5).values():
        uv = mapper.to_image(poly).round().astype(np.int32)
        cv2.polylines(img, [uv.reshape(-1, 1, 2)], False, (235, 235, 235), 3, cv2.LINE_AA)
    for i in range(40):  # "advertising boards" around the pitch: corners for ORB
        x = int(rng.integers(0, CW - 60))
        y = int(rng.choice([rng.integers(0, 25), rng.integers(CH - 30, CH - 5)]))
        col = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(img, (x, y), (x + 55, y + 22), col, -1)
        cv2.putText(img, f"AD{i}", (x + 4, y + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 2)
    return img


CANVAS = _canvas()


def _players(img: np.ndarray, t: float, k: float) -> np.ndarray:
    """22 moving dots (players move; the camera does not)."""
    out = img.copy()
    rng = np.random.default_rng(7)
    base = rng.uniform([200, 150], [1400, 750], (22, 2))
    vel = rng.uniform(-40, 40, (22, 2))
    for p in base + vel * (t % 20):
        cv2.circle(out, (int(p[0] * k), int(p[1] * k)), max(3, int(8 * k)), (30, 30, 200), -1)
    return out


def static_frame(t: float) -> np.ndarray:
    return _players(cv2.resize(CANVAS, (FW, FH), interpolation=cv2.INTER_AREA), t, FW / CW)


def pan_frame(t: float) -> np.ndarray:
    """A crop that slides 150 canvas px/s and zooms (crop share 0.70 +- 0.10)."""
    z = 0.70 + 0.10 * math.sin(2 * math.pi * t / 20.0)
    cw, ch = int(CW * z), int(CH * z)
    x = int(abs((150.0 * t) % (2 * (CW - cw)) - (CW - cw)))
    y = (CH - ch) // 2
    return cv2.resize(_players(CANVAS, t, 1.0)[y:y + ch, x:x + cw], (FW, FH),
                      interpolation=cv2.INTER_AREA)


def cut_frame(t: float) -> np.ndarray:
    """Drone view until t = 170 s, then a different shot (a crowd / stand)."""
    if t < 170:
        return static_frame(t)
    rng = np.random.default_rng(int(t))
    img = np.full((FH, FW, 3), (90, 60, 140), np.uint8)
    for _ in range(300):
        x, y = int(rng.integers(0, FW)), int(rng.integers(0, FH))
        cv2.circle(img, (x, y), int(rng.integers(4, 12)),
                   tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


def frame_mapper() -> HomographyMapper:
    """Image (frame) pixels -> pitch metres for `static_frame`."""
    k = FW / CW
    return HomographyMapper(np.linalg.inv(np.diag([k, k, 1.0]) @ _pitch_to_canvas()))


def samples(fn, lo: float = 100.0, hi: float = 245.0, n: int = 6, dt: float = 0.5):
    ts = [lo + (i + 0.5) * (hi - lo) / n for i in range(n)]
    return [(t, fn(t), fn(t + dt)) for t in ts]


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    c = copy.deepcopy(load_config())
    sc = c["synthetic"]
    sc["duration_s"], sc["half_time_s"] = 900.0, 450.0
    sc["noise_events"].update({"set_pieces": [0, 0], "counters": [0, 0], "flickers": [0, 0]})
    sc["camera"]["broadcast_fraction"] = 0.0
    return c


@pytest.fixture(scope="module")
def vc(cfg) -> VisionConfig:
    return VisionConfig.from_config(cfg)


def ok_geometry(frame: np.ndarray) -> tuple[bool, float | None]:
    return True, 0.05


def ev(**kw: Any) -> PassEvidence:
    base = dict(source="reanalysis", coverage_before=0.9, coverage_after=0.9, share_new=1.0,
                confident_after=12, windows_after=13, reverted_after_s=None, return_of=None,
                footage_frac=1.0)
    return PassEvidence(**{**base, **kw})


# --------------------------------------------------------------------------- measurements


def test_static_drawn_pitch_is_ok(vc, cfg):
    q = measure_quality(samples(static_frame), 0.5, ok_geometry, vc)
    g = q.geometry
    assert g.shift_px_per_s_max < 5.0 and g.zoom_change_max < 0.01 and not g.camera_cut
    v = evaluate(ev(), VerifyConfig.from_config(cfg), backend="video", view="top", geometry=g,
                 second_look=True)
    assert v.verdict == "confirm"
    assert len(json.dumps(q.summary())) < 300


def test_motion_estimate_recovers_a_known_shift_and_zoom(vc):
    a = static_frame(0.0)
    M = cv2.getRotationMatrix2D((FW / 2, FH / 2), 0.0, 1.06)
    M[0, 2] += 30.0
    b = cv2.warpAffine(a, M, (FW, FH))
    m = estimate_motion(a, b, vc)
    assert m.aligned and abs(m.scale - 1.06) < 0.01 and abs(m.shift_px - 30.0) < 3.0


def test_simulated_pan_and_zoom_is_refused(vc, cfg):
    q = measure_quality(samples(pan_frame), 0.5, ok_geometry, vc)
    g = q.geometry
    assert g.shift_px_per_s_max > 25.0 or g.zoom_change_max > 0.03
    v = evaluate(ev(), VerifyConfig.from_config(cfg), backend="video", view="top", geometry=g)
    assert v.verdict == "refuse" and v.failed == ["geometry"]


def test_hard_switch_to_another_shot_is_a_cut(vc, cfg):
    q = measure_quality(samples(cut_frame), 0.5, ok_geometry, vc)
    assert q.geometry.camera_cut and q.cuts and q.cuts[0] < 170
    v = evaluate(ev(), VerifyConfig.from_config(cfg), backend="video", geometry=q.geometry)
    assert v.verdict == "refuse"


# --------------------------------------------------------------------------- backend + tools


class FakeSource:
    def __init__(self, fn, end_s: float) -> None:
        self.fn, self.start_s, self.end_s = fn, 0.0, end_s

    def frames(self, times):
        for t in sorted(times):
            yield t, 0, 0, self.fn(t)

    def read(self, t: float) -> np.ndarray:
        return self.fn(t)


class FakeGeo:
    anchor = True
    static_err = 0.05

    def __init__(self) -> None:
        self.base = frame_mapper()

    def for_frame(self, frame: np.ndarray) -> FrameGeometry:
        return FrameGeometry(self.base, True, 0.05, None)


@pytest.fixture(scope="module")
def video_match(cfg):
    sched = Schedule(start={"home": "4-4-2", "away": "5-3-2"},
                     changes=[Change("home", 300.0, "3-5-2")])
    m, _ = generate_match(7, cfg, sched, "synthetic_video_test")
    m = parse_match_state(m)
    return m.model_copy(update={"source_video": SourceVideo(uri="generated.mp4", native_fps=10,
                                                             width=FW, height=FH)})


def make_backend(match, cfg, tmp_path: Path, fn=static_frame, s_per_frame: float | None = None):
    c = copy.deepcopy(cfg)
    c["agent"]["vision"]["cache_dir"] = str(tmp_path / "cache")
    if s_per_frame is not None:
        c["agent"]["vision"]["s_per_frame"]["top"] = s_per_frame
    calls: list[tuple[float, float, float]] = []

    def runner(uri, *, view, start_s, end_s, fps, track_fps, cfg, match_id, **kw):
        calls.append((start_s, end_s, fps))
        frames = [f for f in match.frames if start_s <= f.t < end_s]
        return SimpleNamespace(match=match.model_copy(update={"frames": frames,
                                                              "match_id": match_id}),
                               timing={"detection": 1.0})

    vb = VideoBackend(match, "top", c, None, runner=runner)
    vb._source, vb._geo = FakeSource(fn, float(match.duration_s)), FakeGeo()
    return vb, calls, c


def test_reanalysis_budget_refusal_then_cache_hit(video_match, cfg, tmp_path):
    vb, calls, _ = make_backend(video_match, cfg, tmp_path, s_per_frame=10.0)
    with pytest.raises(OverBudget) as exc:
        vb.reanalyse(100.0, 245.0, 4.0)  # 145 s x 4 fps x 10 s = 5800 s > 360 s
    assert exc.value.max_window_s == 5.0 and calls == []
    vb, calls, _ = make_backend(video_match, cfg, tmp_path)
    r1 = vb.reanalyse(100.0, 245.0, 4.0)
    r2 = vb.reanalyse(100.0, 245.0, 4.0)
    assert (r1.cache_hit, r2.cache_hit, len(calls)) == (False, True, 1)
    assert len(r2.match.frames) == len(r1.match.frames) > 0


def _runner(ctx, tb, tmp_path) -> AgentRunner:
    return AgentRunner(ctx, tb, arm="rules", budget=make_budget(ctx.cfg),
                       limiter=RateLimiter(1000, sleep=lambda s: None),
                       trace=TraceWriter(tmp_path / "trace.jsonl"), run_id="test")


def _video_toolbox(video_match, cfg, tmp_path, fn=static_frame, s_per_frame=None):
    vb, calls, c = make_backend(video_match, cfg, tmp_path, fn, s_per_frame)
    ctx = MatchContext(video_match, c, backend="video", view="top")
    assert len(ctx.candidates) == 1
    return ctx, Toolbox(ctx, AlertStore(tmp_path / "alerts.jsonl"), tmp_path / "evidence",
                        video=vb), calls


def test_rules_arm_on_video_confirms_with_a_frame_in_the_evidence(video_match, cfg, tmp_path):
    ctx, tb, calls = _video_toolbox(video_match, cfg, tmp_path)
    out = _runner(ctx, tb, tmp_path).run()[0]
    assert out.tool_calls[:2] == ["check_frame_quality", "reanalyse_window"] and calls
    assert out.decision == "confirmed" and out.alert_id
    assert out.quality["homography_ok_share"] == 1.0 and out.quality["opencv_ms"] > 0
    assert out.reanalysis["cache"] == "miss" and out.reanalysis["sample_fps"] == 4.0
    png = tb.evidence_dir / ctx.match.match_id / f"{out.event_id}.png"
    img = cv2.imread(str(png))
    assert img is not None and png.stat().st_size <= 400_000
    assert img.shape[0] > 600  # video frame panel on top of the two shape panels


def test_rules_arm_refuses_a_panning_camera_without_reanalysis(video_match, cfg, tmp_path):
    ctx, tb, calls = _video_toolbox(video_match, cfg, tmp_path, fn=pan_frame)
    out = _runner(ctx, tb, tmp_path).run()[0]
    assert out.tool_calls == ["check_frame_quality", "record_decision"] and calls == []
    assert (out.decision, out.verdict) == ("uncertain", "refuse")
    assert "camera geometry not valid" in out.reason and out.alert_id is None


def test_over_budget_is_a_retryable_tool_error(video_match, cfg, tmp_path):
    ctx, tb, calls = _video_toolbox(video_match, cfg, tmp_path, s_per_frame=10.0)
    c = ctx.candidates[0]
    st = tb.new_state(c)
    a, b = ctx.required_span(c)
    r = tb.run(st, "reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4,
                                        "event_id": c.id, "why": "x"})
    assert r["error"] == "over_budget" and r["max_window_s_at_this_fps"] == 5.0
    assert r["retryable"] is True and st.reanalyses == 0 and calls == []
    r = tb.run(st, "reanalyse_window", {"start_s": a, "end_s": a + 5, "sample_fps": 4,
                                        "why": "fits"})
    assert "error" not in r and r["cache"] == "miss" and len(json.dumps(r)) <= 1024


def test_low_visibility_before_panel_is_labelled(video_match, cfg, tmp_path):
    """Problem 4: no confident window in the old shape -> say so, do not average the mess."""
    ctx, tb, _ = _video_toolbox(video_match, cfg, tmp_path)
    c = ctx.candidates[0]
    blind = dataclasses.replace(ctx.first, windows={
        s: [dataclasses.replace(w, label=UNCERTAIN) if w.t <= c.t else w for w in ws]
        for s, ws in ctx.first.windows.items()})
    ctx.first = blind
    before, after = tb.shape_panels(c, blind)
    assert before["low_visibility"] and "low visibility" in before["caption"]
    assert not after["low_visibility"] and "most confident window" in after["caption"]
    assert tb.render_shapes(c, [before, after]).shape[1] > 1000
