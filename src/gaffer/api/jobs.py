"""Analyses: status, the single background worker, and the result files (docs/API.md).

One analysis runs at a time (a single worker thread; others wait in a queue). The worker runs
the existing code unchanged, in this order:

1. **detecting** - `perception.pipeline.run` on the upload (OpenCV 5: re-anchoring, classical
   drone detector, ByteTrack, shirt colours) with the analysis's calibration;
2. **teams** - team colours, labels and the MatchState (inside the pipeline), then the tactics
   engine (`agent.context.MatchContext`: formations and candidate changes);
3. **agent** - the Phase 3 agent on every candidate (`AgentRunner`, video backend: OpenCV
   quality check, re-analysis, evidence, pending alerts), explanations, the coach report.

Progress is never invented: `progress = elapsed / (elapsed + remaining)` where *remaining* comes
from the measured time per frame (detecting) and per checked candidate (agent); before the first
measurements it uses the priors in `api.jobs` (`eta_basis: "prior"`). Status is written to
`<analysis>/status.json` so a poll (or a restart) can read it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
import traceback
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gaffer.api.event_store import EventStore, persist_video_analysis
from gaffer.api.storage import Storage, read_json, write_json

STAGES = ("uploading", "detecting", "teams", "agent", "done")
STAGE_LABELS = {"uploading": "Uploading", "detecting": "Detecting players (OpenCV)",
                "teams": "Teams and formations", "agent": "Agent checking changes",
                "done": "Done"}
STATUSES = ("uploaded", "needs_confirmation", "needs_corners", "queued", "running", "done",
            "failed")
log = logging.getLogger("gaffer.api.jobs")
RESULT_FILES = ("status.json", "upload.json", "match_state.json", "match_state.teams.json",
                "timeline.json", "trace.jsonl", "explanations.json", "run_rows.json",
                "report.json", "report.md", "pitch_preview.jpg", "first_frame.jpg",
                "calibration/top.json")


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def rules_fingerprint(cfg: dict[str, Any]) -> str:
    """Same hash as `scripts/eval_agent.py fingerprint` (agent / tactics / bedrock / synthetic /
    formations): recorded with every analysis to show the frozen rules decided it."""
    import hashlib

    keys = {k: cfg.get(k) for k in ("agent", "tactics", "bedrock", "synthetic", "formations")}
    return hashlib.sha256(json.dumps(keys, sort_keys=True, default=str).encode()).hexdigest()[:16]


class AnalysisFailed(RuntimeError):
    """A foreseeable failure; `message` is coach-readable, `detail` technical."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


# --------------------------------------------------------------------------- progress


class Progress:
    """Stage timings -> progress and ETA (see module docstring)."""

    def __init__(self, cfg: dict[str, Any], duration_s: float,
                 write: Callable[[dict[str, Any]], None]) -> None:
        j = cfg["api"]["jobs"]
        self.prior_s_per_video_s = float(j["prior_s_per_video_s"])
        self.prior_s_per_candidate = float(j["prior_s_per_candidate"])
        self.frames_per_candidate = float(j["eta_frames_per_candidate"])
        self.prior_candidates_per_min = float(j["prior_candidates_per_min"])
        self.max_agent_opencv_s = float(cfg["agent"]["vision"]["max_opencv_s_per_match"])
        self.duration_s = float(duration_s)
        self.write = write
        self.t0 = time.perf_counter()
        self.stage = "detecting"
        self.stage_t0 = self.t0
        self.frames_total = 0
        self.frames_done = 0
        self.detect_s: float | None = None
        self.cands_total: int | None = None
        self.cands_done = 0
        self.cand_s: list[float] = []
        self.timings: dict[str, float] = {}
        self.last_progress = 0.0
        self._last_write = 0.0

    # ---- events
    def set_stage(self, stage: str) -> None:
        t = time.perf_counter()
        self.timings[self.stage] = round(t - self.stage_t0, 2)
        if self.stage == "detecting":
            self.detect_s = t - self.stage_t0
        self.stage, self.stage_t0 = stage, t
        self.emit(force=True)

    def frames_started(self, n: int) -> None:
        self.frames_total = n
        self.emit(force=True)

    def frame_done(self, k: int) -> None:
        self.frames_done = k
        self.emit()

    def candidates_started(self, n: int) -> None:
        self.cands_total = n
        self.emit(force=True)

    def candidate_done(self, seconds: float) -> None:
        self.cands_done += 1
        self.cand_s.append(seconds)
        self.emit(force=True)

    # ---- estimates
    def remaining(self) -> tuple[float, float, float, str]:
        now = time.perf_counter()
        basis = "prior"
        in_stage = now - self.stage_t0
        prior_detect = self.prior_s_per_video_s * self.duration_s
        if self.stage == "detecting":
            if self.frames_done >= 5 and self.frames_total:
                per = in_stage / self.frames_done
                detect_left = per * (self.frames_total - self.frames_done)
                basis = "measured"
            else:
                detect_left = max(0.0, prior_detect - in_stage)
            detect_total = in_stage + detect_left
        else:
            detect_left, detect_total = 0.0, self.detect_s or prior_detect
        teams_left = 0.0
        if self.stage in ("detecting", "teams"):
            teams_est = 0.05 * detect_total + 5.0  # team labels + tactics engine (Phase 2: < 5 %)
            teams_left = max(0.0, teams_est - (in_stage if self.stage == "teams" else 0.0))
        n = (self.cands_total if self.cands_total is not None
             else round(self.prior_candidates_per_min * self.duration_s / 60))
        # one agent check ~ `eta_frames_per_candidate` tracked frames of OpenCV (camera check +
        # a ~145 s re-analysis at 4-6 fps), timed at THIS video's measured s per frame
        s_per_frame = None
        if self.stage == "detecting" and self.frames_done >= 5:
            s_per_frame = in_stage / self.frames_done
        elif self.detect_s and self.frames_total:
            s_per_frame = self.detect_s / self.frames_total
        per_c = (sum(self.cand_s) / len(self.cand_s) if self.cand_s
                 else self.frames_per_candidate * s_per_frame if s_per_frame
                 else self.prior_s_per_candidate)
        if self.stage == "agent" and (self.cand_s or s_per_frame):
            basis = "measured"  # this video's own timings (frames, then checked candidates)
        left_c = max(0, n - self.cands_done)
        agent_left = min(left_c * per_c, self.max_agent_opencv_s + 20.0 * left_c)
        if self.stage == "agent" and not self.cand_s:
            agent_left = max(0.0, agent_left - in_stage)
        if self.stage == "done":
            return 0.0, 0.0, 0.0, "measured"
        server_left = detect_left + teams_left + (2.0 if self.stage != "agent" else 0.0)
        total_left = server_left + agent_left
        return total_left, server_left, agent_left, basis

    def snapshot(self) -> dict[str, Any]:
        elapsed = time.perf_counter() - self.t0
        left, server_left, agent_left, basis = self.remaining()
        p = 1.0 if self.stage == "done" else min(0.99, elapsed / max(elapsed + left, 1e-9))
        p = max(p, self.last_progress)  # never goes backwards
        self.last_progress = p
        detail = {"elapsed_s": round(elapsed, 1), "eta_basis": basis,
                  "stage_timings_s": dict(self.timings)}
        if self.frames_total:
            detail["frames"] = {"done": self.frames_done, "total": self.frames_total}
        if self.cands_total is not None:
            detail["candidates"] = {"done": self.cands_done, "total": self.cands_total}
        server_eta_ready = (self.stage not in ("done", "agent")
                            and (self.stage != "detecting" or self.frames_done >= 5))
        return {"stage": self.stage, "progress": round(p, 4),
                "eta_s": round(server_left, 1) if server_eta_ready else None,
                "agent_eta_s": None if self.stage == "done" else round(agent_left, 1),
                "progress_detail": detail}

    def emit(self, force: bool = False) -> None:
        t = time.perf_counter()
        if force or t - self._last_write >= 1.0:
            self._last_write = t
            self.write(self.snapshot())


@contextlib.contextmanager
def counting_frames(progress: Progress) -> Iterator[None]:
    """Count the frames the pipeline decodes (for progress) without changing the pipeline: its
    module-level `VideoSource` is swapped for a subclass for the duration of one run. Only one
    analysis runs at a time (single worker), and the agent's re-analyses run after this exits."""
    from gaffer.perception import pipeline
    from gaffer.perception.video import VideoSource

    class CountingSource(VideoSource):
        def frames(self, times):  # type: ignore[override]
            times = list(times)
            progress.frames_started(len(times))
            for k, item in enumerate(super().frames(times)):
                yield item
                progress.frame_done(k + 1)
            progress.set_stage("teams")  # decoding done: team colours, labels, MatchState

    orig = pipeline.VideoSource
    pipeline.VideoSource = CountingSource  # type: ignore[misc]
    try:
        yield
    finally:
        pipeline.VideoSource = orig  # type: ignore[misc]


# --------------------------------------------------------------------------- manager


class JobManager:
    """Status store + the single worker. `runner(manager, analysis_id)` does the work (tests
    may pass their own)."""

    def __init__(self, cfg: dict[str, Any], storage: Storage, *,
                 llm_factory: Callable[[], Any] | None = None, usage: Any = None,
                 alerts_path: str | Path | None = None,
                 event_store: EventStore | None = None,
                 runner: Callable[[JobManager, str], None] | None = None,
                 start_worker: bool = True) -> None:
        self.cfg, self.storage = cfg, storage
        self.llm_factory, self.usage = llm_factory, usage
        self.alerts_path = alerts_path or cfg["agent"]["outputs"]["alerts"]
        self.event_store = event_store
        self.runner = runner or run_analysis
        self._lock = threading.RLock()
        self._statuses: dict[str, dict[str, Any]] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self.current: str | None = None
        self._recover()
        self._thread: threading.Thread | None = None
        if start_worker:
            self.start()

    # ---- status
    def _recover(self) -> None:
        """After a restart: a running analysis cannot resume (failed, upload again); queued ones
        are queued again."""
        for aid in self.storage.list_ids():
            key = f"{aid}/status.json"
            if not self.storage.exists(key):
                continue
            try:
                st = read_json(self.storage, key)
            except (json.JSONDecodeError, OSError):
                continue
            if st.get("status") == "running":
                st.update(status="failed", error="The server restarted during this analysis. "
                          "Upload the video again.", updated_utc=now_utc())
                write_json(self.storage, key, st)
            elif st.get("status") == "queued":
                self._queue.put(aid)
            self._statuses[aid] = st

    def ahead_of(self, aid: str) -> int:
        """Analyses that run before `aid`: the one running now plus those queued earlier."""
        with self._queue.mutex:
            order = list(self._queue.queue)
        running = 1 if self.current and self.current != aid else 0
        return running + (order.index(aid) if aid in order else 0)

    def _live(self, st: dict[str, Any]) -> dict[str, Any]:
        """A queued analysis reports how many are ahead of it NOW, not when it was queued."""
        if st.get("status") == "queued":
            st["queue_position"] = self.ahead_of(st["id"])
        return st

    def get(self, aid: str) -> dict[str, Any] | None:
        with self._lock:
            if aid in self._statuses:
                return self._live(dict(self._statuses[aid]))
        key = f"{aid}/status.json"
        try:
            if self.storage.exists(key):
                st = read_json(self.storage, key)
                with self._lock:
                    self._statuses[aid] = st
                return self._live(dict(st))
        except Exception:  # invalid id / unreadable: unknown analysis
            return None
        return None

    def update(self, aid: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            st = self._statuses.setdefault(aid, {"id": aid})
            st.update(fields)
            if "stage" in fields:
                st["stage_label"] = STAGE_LABELS.get(st["stage"], st["stage"])
            st["updated_utc"] = now_utc()
            write_json(self.storage, f"{aid}/status.json", st)
            return dict(st)

    def create(self, aid: str, **fields: Any) -> dict[str, Any]:
        base = {"id": aid, "status": "uploaded", "stage": "uploading", "progress": 0.0,
                "eta_s": None, "error": None, "created_utc": now_utc()}
        return self.update(aid, **{**base, **fields})

    # ---- queue
    def queued_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._statuses.values() if s.get("status") == "queued")

    def enqueue(self, aid: str) -> dict[str, Any]:
        ahead = self.queued_count() + (1 if self.current else 0)
        st = self.update(aid, status="queued", stage="uploading", progress=0.0, eta_s=None,
                         error=None, queue_position=ahead)
        self._queue.put(aid)
        return st

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, name="gaffer-analysis",
                                            daemon=True)
            self._thread.start()

    def _work(self) -> None:
        while True:
            aid = self._queue.get()
            if aid is None:  # type: ignore[comparison-overlap]
                return
            self.run_one(aid)

    def run_one(self, aid: str) -> None:
        """Run one queued analysis now (the worker; tests call it directly)."""
        st = self.get(aid)
        if not st or st.get("status") != "queued":
            return
        self.current = aid
        self.update(aid, status="running", stage="detecting", progress=0.0, queue_position=0,
                    started_utc=now_utc())
        t0 = time.perf_counter()
        try:
            self.runner(self, aid)
            done = self.get(aid) or {}
            if done.get("status") == "done":  # one line per finished analysis (CloudWatch metric)
                summ = done.get("summary") or {}
                log.info("analysis_done id=%s wall_s=%.1f video_s=%s candidates=%s "
                         "bedrock_calls=%s", aid, time.perf_counter() - t0,
                         (done.get("video") or {}).get("duration_s"), summ.get("candidates"),
                         (summ.get("bedrock") or {}).get("calls"))
        except AnalysisFailed as exc:
            self.update(aid, status="failed", error=str(exc), error_detail=exc.detail[:2000],
                        eta_s=None)
        except Exception as exc:  # unforeseen: say so plainly, keep the trace for the log
            log.exception("analysis %s failed", aid)
            self.update(aid, status="failed", eta_s=None,
                        error="The analysis stopped because of an internal error. The details "
                              "are in the server log.",
                        error_detail=f"{type(exc).__name__}: {exc}\n"
                                     f"{traceback.format_exc(limit=8)}"[:4000])
        finally:
            self.current = None
            with contextlib.suppress(Exception):
                self.storage.publish(aid, list(RESULT_FILES))

    def stop(self) -> None:
        self._queue.put(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- the analysis


def _pipeline_error(exc: Exception) -> AnalysisFailed:
    from gaffer.perception.pipeline import TooFewPlayersError
    from gaffer.perception.pitch import CalibrationError
    from gaffer.perception.video import VideoError

    if isinstance(exc, TooFewPlayersError):
        return AnalysisFailed(
            "Gaffer could not find enough players in this video to read formations. Check "
            "that the camera looks straight down on the whole pitch and that the 4 pitch "
            "corners are right, then upload it again.", str(exc))
    if isinstance(exc, CalibrationError):
        return AnalysisFailed("The pitch calibration for this video could not be used. Mark "
                              "the 4 pitch corners again.", str(exc))
    if isinstance(exc, VideoError):
        return AnalysisFailed("OpenCV could not read part of this video. Re-export it as MP4 "
                              "(H.264) and upload it again.", str(exc))
    return AnalysisFailed("The player detection could not finish on this video.", str(exc))


def _choose_llm(mgr: JobManager) -> tuple[Any, str, float, int]:
    """(llm or None, arm, run cost cap, run call cap) from `api.jobs.arm` and the daily caps."""
    j = mgr.cfg["api"]["jobs"]
    arm = str(j.get("arm", "auto"))
    if arm == "rules" or mgr.llm_factory is None:
        return None, "rules", 0.0, 0
    calls_left, cost_left = mgr.usage.bedrock_left() if mgr.usage else (10**6, 10**6)
    if calls_left <= 0 or cost_left <= 0:
        return None, "rules", 0.0, 0
    try:
        llm = mgr.llm_factory()
    except Exception:  # no credentials / region: the rules arm, said in the result
        llm = None
    if llm is None:
        return None, "rules", 0.0, 0
    return llm, "llm", min(float(j["max_cost_usd_per_analysis"]), cost_left), calls_left


def _row(ctx: Any, o: Any) -> dict[str, Any]:
    """Per-candidate row, same fields as `scripts/run_agent_video.py` (`report_llm.json`)."""
    from gaffer.agent.tools import clock
    from gaffer.agent.verify import DECISION_OF

    c = ctx.candidate(o.event_id)
    q, r = o.quality or {}, o.reanalysis or {}
    first_dec = DECISION_OF[o.first_verdict]
    return {
        "match": ctx.match.match_id, "event_id": c.id, "team": c.team, "t": c.t,
        "clock": clock(c.t), "detected_at_s": c.detected_at_s, "from": c.from_, "to": c.to,
        "required_span": list(ctx.required_span(c)),
        "first_pass": {"verdict": o.first_verdict, "reason": o.first_reason,
                       **ctx.evidence(c).summary()},
        "quality": {k: q.get(k) for k in ("homography_ok_share", "line_error_m_median",
                                         "camera_shift_px_per_s_max", "zoom_change_max",
                                         "camera_cut", "coverage", "problems", "opencv_ms")},
        "reanalysis": ({k: r.get(k) for k in ("window", "sample_fps", "frames", "processing_s",
                                              "cache", "coverage")}
                       | {"vs_event": r.get("vs_event", {})}) if r else None,
        "verdict": o.verdict, "decision": o.decision, "reason": o.reason,
        "decided_by": o.decided_by, "tool_calls": o.tool_calls, "tool_ms": o.tool_ms,
        "evidence_image": o.evidence_image, "alert_id": o.alert_id,
        "opencv_changed_decision": o.decision != first_dec, "first_pass_decision": first_dec,
        "explanation": o.explanation, "explanation_source": o.explanation_source,
        "llm_calls": o.llm_calls, "guard_blocks": o.guard_blocks, "fallback": o.fallback,
        "tokens_in": o.tokens_in, "tokens_out": o.tokens_out, "cost_usd": round(o.cost_usd, 5),
        "llm_s": round(o.llm_s, 1), "tool_s": round(o.tool_s, 1), "trace_id": o.trace_id,
    }


def run_analysis(mgr: JobManager, aid: str) -> None:
    """The worker body for one analysis (see module docstring)."""
    from gaffer.agent.alerts import AlertStore
    from gaffer.agent.context import MatchContext
    from gaffer.agent.explain import Explainer
    from gaffer.agent.loop import AgentRunner, RateLimiter, TraceWriter, make_budget
    from gaffer.agent.report import Reporter, build_inputs, render_markdown
    from gaffer.agent.tools import Toolbox, clock
    from gaffer.agent.vision import VideoBackend, VisionError
    from gaffer.api.calib import CLIPS_NAME, job_config
    from gaffer.perception.detector import DetectorError
    from gaffer.perception.pipeline import PipelineError, run, write_outputs
    from gaffer.perception.pitch import Calibration, CalibrationError, image_corners
    from gaffer.perception.video import VideoError
    from gaffer.schema import ContractError

    st = mgr.get(aid) or {}
    job_dir = mgr.storage.local_dir(aid)
    cfg = job_config(mgr.cfg, job_dir)
    j = mgr.cfg["api"]["jobs"]
    view = j["view"]
    info = st.get("video", {})
    match_id = f"up_{aid}"
    prog = Progress(mgr.cfg, float(info.get("duration_s", 60.0)),
                    lambda snap: mgr.update(aid, **snap))
    prog.emit(force=True)

    # 1-2. perception (OpenCV) -> MatchState
    calibration = Calibration.for_view(cfg, view)
    pitch = st.get("pitch") or {}
    detection = pitch.get("detection") or {}
    corners = detection.get("corners") or pitch.get("corners")
    if not corners:
        corners = image_corners(calibration.mapper(), float(cfg["pitch"]["length_m"]),
                                float(cfg["pitch"]["width_m"]))
    from gaffer.perception.calibration_loop import pixels_per_metre, tier1_config

    px_per_m = pixels_per_metre(corners, float(cfg["pitch"]["length_m"]),
                                float(cfg["pitch"]["width_m"]))
    cfg, tier1_rule_applied = tier1_config(cfg, px_per_m)
    from gaffer.api.resolution import resolution_note

    resolution = resolution_note(px_per_m, mgr.cfg)  # a line in the result when low; no block
    mgr.update(aid, resolution=resolution)
    try:
        with counting_frames(prog):
            res = run(job_dir / CLIPS_NAME, view=view, cfg=cfg, match_id=match_id,
                      debug_video=(job_dir / "debug.mp4") if j.get("debug_video") else None)
    except (VideoError, CalibrationError, DetectorError, PipelineError, ContractError) as exc:
        raise _pipeline_error(exc) from exc
    if prog.stage == "detecting":
        prog.set_stage("teams")
    calibration_summary = {"enabled": False, "calls": 0, "cost_usd": 0.0,
                           "extra_s": 0.0, "kept": False,
                           "tier1_rule_applied": tier1_rule_applied}
    tiers = cfg["perception"]["self_calibration"]["calibration_tiers"]
    if tiers["tier1"]["enabled"] or tiers["tier2"]["enabled"]:
        from gaffer.config import repo_path
        from gaffer.perception.calibration_loop import run_calibration_loop

        outcome = run_calibration_loop(
            initial=res, cfg=cfg,
            run=lambda trial_cfg, start_s, end_s: run(
                job_dir / CLIPS_NAME, view=view, cfg=trial_cfg, start_s=start_s, end_s=end_s,
                match_id=f"{match_id}_tier2"),
            full_run=lambda final_cfg: run(job_dir / CLIPS_NAME, view=view, cfg=final_cfg,
                                           debug_video=(job_dir / "debug.mp4")
                                           if j.get("debug_video") else None,
                                           match_id=match_id),
            llm_factory=mgr.llm_factory,
            trace_path=repo_path(cfg["agent"]["outputs"]["trace"]), usage=mgr.usage,
            on_message=lambda msg: mgr.update(aid, calibration_message=msg),
            px_per_m=px_per_m)
        res, cfg = outcome["result"], outcome["config"]
        calibration_summary = {
            "enabled": True, "calls": outcome["calls"], "cost_usd": outcome["cost_usd"],
            "extra_s": outcome["elapsed_s"], "kept": outcome["kept"],
            "tier1_rule_applied": outcome["tier1_rule_applied"],
            "tokens_in": outcome["tokens_in"], "tokens_out": outcome["tokens_out"],
            "message": outcome["message"],
        }
    match_path, _ = write_outputs(res, job_dir / "match_state.json")
    perception = {"timing_s": {k: round(v, 2) for k, v in res.timing.items()},
                  "s_per_video_s": round(sum(res.timing.values()) / max(res.video_seconds, 1e-9),
                                         2),
                  "tracked_frames": len(res.records), "output_frames": len(res.match.frames)}
    mgr.update(aid, perception=perception)
    try:
        ctx = MatchContext(res.match, cfg, view=view)
    except ContractError as exc:
        raise AnalysisFailed("The tactics engine could not read the tracked positions.",
                             str(exc)) from exc

    # 3. agent on every candidate
    prog.set_stage("agent")
    llm, arm, cost_cap, calls_cap = _choose_llm(mgr)
    try:
        vb = VideoBackend.for_match_file(match_path, res.match, view, cfg)
    except VisionError as exc:
        raise AnalysisFailed("The agent could not open the video for its second look.",
                             str(exc)) from exc
    store = AlertStore(mgr.alerts_path)
    tb = Toolbox(ctx, store, job_dir / "evidence", video=vb)
    limiter = RateLimiter(int(cfg["agent"]["llm"]["max_rpm"]))
    budget = make_budget(cfg, calls_cap if arm == "llm" else None,
                         cost_cap if arm == "llm" else None)
    explainer = Explainer(cfg, llm=llm, limiter=limiter)
    runner = AgentRunner(ctx, tb, arm=arm, llm=llm, budget=budget, limiter=limiter,
                         trace=TraceWriter(job_dir / "trace.jsonl"), run_id=f"api_{aid}",
                         cfg=cfg, explainer=explainer)
    verify = runner.verify
    completion_times_utc: dict[str, str] = {}

    def timed_verify(c: Any, use_llm: bool = True) -> Any:
        t0 = time.perf_counter()
        out = verify(c, use_llm=use_llm)
        completion_times_utc[out.event_id] = now_utc()
        prog.candidate_done(time.perf_counter() - t0)
        return out

    runner.verify = timed_verify  # type: ignore[method-assign]
    prog.candidates_started(len(ctx.candidates))
    outcomes = runner.run()
    verified_timeline = runner.verified_timeline(outcomes)
    write_json(mgr.storage, f"{aid}/timeline.json", verified_timeline)
    if mgr.event_store is not None:
        # This projection uses only the video MatchState and OpenCV-derived candidates/results.
        # TeamTrack annotation files are never opened by this runtime path.
        persist_video_analysis(mgr.event_store, aid, ctx, outcomes,
                               completion_times_utc=completion_times_utc)
    rows = [_row(ctx, o) for o in outcomes]
    write_json(mgr.storage, f"{aid}/run_rows.json", {"rows": rows})
    names = {s: tb.team_name(s) for s in ("home", "away")}
    expl = [{"event_id": o.event_id, "team": names[ctx.candidate(o.event_id).team],
             "team_side": ctx.candidate(o.event_id).team,
             "change": f"{ctx.candidate(o.event_id).from_} -> {ctx.candidate(o.event_id).to}",
             "clock": clock(ctx.candidate(o.event_id).t), "decision": o.decision,
             "verdict": o.verdict, "reason": o.reason, "explanation": o.explanation,
             "explanation_source": o.explanation_source, "alert_id": o.alert_id,
             "evidence_image": o.evidence_image} for o in outcomes]
    write_json(mgr.storage, f"{aid}/explanations.json", {"candidates": expl})

    # coach report (one call, checked; else the code template)
    decided = [{"event_id": o.event_id, "decision": o.decision, "reason": o.reason,
                "explanation": o.explanation} for o in outcomes]
    alerts = {a.event_id: a for a in store.all().values()
              if a.alert_id.startswith(f"alr_{match_id}_")}
    inp = build_inputs(ctx, decided, alerts, "Uploaded by a coach through the Gaffer web app.")
    rep_llm = llm if arm == "llm" else None
    reporter = Reporter(cfg, rep_llm)
    rep = reporter.generate(inp)
    write_json(mgr.storage, f"{aid}/report.json",
               {"inputs": inp, **rep, "llm": {"calls": reporter.calls,
                                               "cost_usd": round(reporter.cost, 5)}})
    mgr.storage.write_bytes(f"{aid}/report.md",
                            render_markdown(rep["report"], inp, rep["source"]).encode("utf-8"))

    # Charge the verifier/explanation/report calls before the separate posture budget checks
    # remaining daily capacity. Posture has its own persisted per-event and per-match budget.
    ex = explainer.stats()
    base_calls = budget.run_calls + ex["calls"] + reporter.calls + calibration_summary["calls"]
    base_cost = (budget.run_cost + ex["cost_usd"] + reporter.cost
                 + calibration_summary["cost_usd"])
    if mgr.usage is not None and base_calls:
        # Calibration already charged its daily call/cost budget before the remaining Bedrock
        # arm was selected. Do not charge those same calls twice here.
        mgr.usage.add_bedrock(
            base_calls - calibration_summary["calls"],
            base_cost - calibration_summary["cost_usd"],
            budget.run_tokens.get("in", 0), budget.run_tokens.get("out", 0))

    posture_summary = {"eligible_events": 0, "calls": 0, "cost_usd": 0.0}
    if mgr.event_store is not None:
        try:
            from gaffer.agent.posture import PostureAnalyzer

            confirmed, _ = mgr.event_store.list(match_id=ctx.match.match_id, analysis_id=aid,
                                                status="confirmed", limit=500)
            posture_summary["eligible_events"] = len(confirmed)
            if confirmed:
                def posture_reanalysis(record: Any, request: Any) -> dict[str, Any]:
                    """Run one bounded second OpenCV pass against this upload's source video."""
                    if ctx.match.source != "video" or vb is None:
                        raise ValueError("original_video_context_unavailable")
                    start_s, end_s = float(request.start_s), float(request.end_s)
                    if start_s < record.candidate_time_s or end_s > float(
                            record.verification_match_time_s or -1):
                        raise ValueError("requested_window_outside_verified_match_boundary")
                    if end_s > ctx.footage[1] or start_s < ctx.footage[0]:
                        raise ValueError("requested_window_outside_source_video")
                    reanalysis = vb.reanalyse(start_s, end_s, float(request.sample_fps))
                    tactical = ctx.tactics_pass(reanalysis.match, reanalysis.fps,
                                                reanalysis.window)
                    from gaffer.tactics.metrics import span_metrics

                    team = record.team
                    metrics = span_metrics(tactical.frames[team], team, ctx.tcfg)
                    windows = [window for window in tactical.windows[team]
                               if start_s <= window.t <= end_s]
                    confidence_values = [float(window.confidence) for window in windows
                                         if window.label != "uncertain"]
                    total_windows = max(1, len(windows))
                    uncertain_fraction = sum(window.label == "uncertain" for window in windows) \
                        / total_windows
                    formations: dict[str, int] = {}
                    for window in windows:
                        if window.label != "uncertain":
                            formations[window.label] = formations.get(window.label, 0) + 1
                    formation = max(formations, key=formations.get) if formations else None
                    return {
                        "window_s": [float(reanalysis.window[0]), float(reanalysis.window[1])],
                        "sample_fps": float(reanalysis.fps),
                        "cache_hit": bool(reanalysis.cache_hit),
                        "processing_s": round(float(reanalysis.processing_s), 3),
                        "formation": formation,
                        "metrics": {
                            "defensive_line_m": metrics.defensive_line_m,
                            "compactness_m": metrics.compactness_m,
                            "width_m": metrics.width_m,
                            "centroid": ({"x": metrics.centroid[0], "y": metrics.centroid[1]}
                                         if metrics.centroid else None),
                            "pressing_index": metrics.pressing_index,
                            "confidence": (sum(confidence_values) / len(confidence_values)
                                           if confidence_values else None),
                        },
                        "quality": {
                            "coverage": ctx.coverage(team, start_s, end_s, tactical) or 0.0,
                            "mean_players_visible": float(metrics.players_visible_mean),
                            "uncertain_fraction": float(uncertain_fraction),
                            "confidence": (sum(confidence_values) / len(confidence_values)
                                           if confidence_values else 0.0),
                        },
                    }

                analyzer = PostureAnalyzer(cfg, mgr.event_store, mgr.llm_factory, mgr.usage,
                                           visual_reanalysis=posture_reanalysis)
                for event_record in confirmed:
                    is_new_posture = event_record.posture_status == "not_requested"
                    try:
                        analyzer.analyze(event_record.record_id)
                    except Exception:
                        # Tactical posture is advisory: preserve the completed OpenCV job and
                        # verifier decision if a Bedrock or event-store operation fails.
                        log.exception("posture analysis failed for event %s", event_record.event_id)
                    latest = mgr.event_store.get(event_record.record_id)
                    if is_new_posture and latest and isinstance(latest.posture_result, dict):
                        usage = latest.posture_result.get("usage", {})
                        posture_summary["calls"] += int(usage.get("calls", 0))
                        posture_summary["cost_usd"] += float(usage.get("cost_usd", 0.0))
        except Exception:
            log.exception("posture analysis step failed; OpenCV result remains authoritative")
    posture_summary["cost_usd"] = round(float(posture_summary["cost_usd"]), 8)
    calls = base_calls + int(posture_summary["calls"])
    cost = base_cost + float(posture_summary["cost_usd"])
    summary = {"candidates": len(outcomes),
               "decisions": dict(Counter(o.decision for o in outcomes)),
               "alerts": [o.alert_id for o in outcomes if o.alert_id],
               "arm": arm, "llm_down": runner.llm_down,
               "bedrock": {"calls": calls, "cost_usd": round(cost, 5)},
               "posture": posture_summary,
               "report_source": rep["source"], "rules_fingerprint": rules_fingerprint(cfg),
               "opencv_reanalysis_s": round(vb.spent_s, 1),
               "resolution": resolution,
               "self_calibration": calibration_summary}
    prog.set_stage("done")
    mgr.update(aid, status="done", stage="done", progress=1.0, eta_s=0.0, summary=summary,
               finished_utc=now_utc(), match_id=match_id)
