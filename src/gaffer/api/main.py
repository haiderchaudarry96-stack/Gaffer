"""Gaffer FastAPI backend (Phase 4). Routes and payloads: docs/API.md.

One process serves the API, runs the analysis worker (one analysis at a time) and, when
`web/dist` exists, the built frontend at `/`. Errors are `{"detail": "<coach-readable message>"}`
(FastAPI default), which the frontend shows as is.

    uvicorn gaffer.api.main:app --reload            # dev (laptop)
    uvicorn gaffer.api.main:app --host 0.0.0.0      # server / Docker
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from gaffer.agent.alerts import AlertError, AlertStore
from gaffer.api import calib
from gaffer.api.chat import ChatRefused, ChatService, ChatSource
from gaffer.api.jobs import JobManager, new_id, rules_fingerprint
from gaffer.api.results import Demo, analysis_result, evidence_file, evidence_url
from gaffer.api.storage import Storage, StorageError, make_storage, read_json, write_json
from gaffer.api.uploads import (
    UploadRefused,
    VideoInfo,
    check_extension,
    check_rules,
    probe,
    read_frame,
    safe_name,
    save_stream,
)
from gaffer.api.usage import Usage
from gaffer.api.visitors import (
    DecisionConflict,
    VisitorDecisions,
    new_visitor_id,
    valid_visitor_id,
    visitor_id,
)
from gaffer.config import load_config, repo_path
from gaffer.perception.pitch import CalibrationError

log = logging.getLogger("gaffer.api")
DEFAULT = object()


class PixelPoint(BaseModel):
    x: float
    y: float


class FrameRef(BaseModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    t_s: float = Field(default=0.0, ge=0)


class StartRequest(BaseModel):
    """The frontend's pitch step (web/README.md): 4 points in pixels of the frame it showed."""

    points: list[PixelPoint] = Field(min_length=4, max_length=4)
    frame: FrameRef | None = None
    straight_down: bool = False


class PitchRequest(BaseModel):
    """`{"confirmed": true}` (auto-detected corners) or `{"pitch_points": [[x, y] x 4]}`."""

    model_config = ConfigDict(extra="forbid")
    confirmed: bool | None = None
    pitch_points: list[Any] | None = None


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ChatTurn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    match_id: str
    question: str
    history: list[ChatTurn] = Field(default_factory=list)


def _bedrock_factory(cfg: dict[str, Any]) -> Any:
    """Bedrock client factory. A configured profile that does not exist on this machine (EC2,
    Docker: no ~/.aws) falls back to the default credential chain, i.e. the IAM instance role;
    no keys are ever read from config or the image."""

    def make() -> Any:
        import boto3

        from gaffer.llm.bedrock_client import BedrockClient

        c = cfg
        prof = cfg["aws"].get("profile")
        if prof and prof not in boto3.session.Session().available_profiles:
            c = {**cfg, "aws": {**cfg["aws"], "profile": None}}
        return BedrockClient(c)

    return make


def create_app(cfg: dict[str, Any] | None = None, *, storage: Storage | None = None,
               llm_factory: Any = DEFAULT, usage: Usage | None = None,
               alerts_path: str | Path | None = None, runner: Any = None,
               start_worker: bool = True, chat_trace: str | Path | None = None) -> FastAPI:
    """The app. Tests inject `llm_factory` (a fake LLM; None = no Bedrock), `storage`,
    `usage`, `alerts_path`, and `start_worker=False` to run analyses by hand."""
    cfg = cfg or load_config()
    api = cfg["api"]
    storage = storage or make_storage(cfg)
    usage = usage or Usage(cfg)
    factory = _bedrock_factory(cfg) if llm_factory is DEFAULT else llm_factory
    alerts_path = repo_path(alerts_path or cfg["agent"]["outputs"]["alerts"])
    jobs = JobManager(cfg, storage, llm_factory=factory, usage=usage, alerts_path=alerts_path,
                      runner=runner, start_worker=start_worker)
    demo = Demo(cfg)
    chat = ChatService(cfg, usage, factory,
                       repo_path(chat_trace or Path(api["storage"].get("root", "outputs/api"))
                                 / "chat_trace.jsonl"))
    vis = api.get("visitors", {})
    cookie_name = str(vis.get("cookie", "gaffer_visitor"))
    cookie_age = int(float(vis.get("max_age_days", 365)) * 86400)
    demo_decisions = VisitorDecisions(int(vis.get("max_visitors", 10000)))
    ctx_cache: OrderedDict[str, Any] = OrderedDict()
    ctx_lock = threading.Lock()
    upload_lock = threading.Lock()

    app = FastAPI(title="Gaffer API", version="0.4.0",
                  description="AI football tactical analyst: OpenCV 5 perception, a "
                              "self-verifying agent on Amazon Bedrock. See docs/API.md.")

    @app.middleware("http")
    async def visitor_cookie(request: Request, call_next: Any) -> Any:
        """Every /api request carries an anonymous visitor id (random, in a cookie; no
        personal data). It keys the visitor's own demo decisions (api/visitors.py)."""
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        got = request.cookies.get(cookie_name)
        fresh = not valid_visitor_id(got)
        request.state.visitor_id = new_visitor_id() if fresh else got
        request.state.visitor_from_cookie = not fresh
        response = await call_next(request)
        if fresh:
            response.set_cookie(cookie_name, request.state.visitor_id, max_age=cookie_age,
                                httponly=True, samesite="lax", path="/",
                                secure=request.url.scheme == "https")
        return response

    # innermost first: the visitor middleware above runs inside gzip and CORS
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(CORSMiddleware, allow_origins=list(api.get("cors_origins", [])),
                       allow_methods=["GET", "POST"], allow_headers=["*"],
                       allow_credentials=True)  # the visitor cookie (dev: Vite on :5173)
    app.state.jobs, app.state.storage, app.state.usage = jobs, storage, usage
    app.state.demo, app.state.chat, app.state.cfg = demo, chat, cfg
    app.state.demo_decisions = demo_decisions

    def demo_alerts(request: Request) -> list[dict[str, Any]]:
        """The demo alerts as THIS visitor sees them (their own decisions only)."""
        return demo_decisions.apply(visitor_id(request), demo.alerts(base(request)))

    def store() -> AlertStore:
        return AlertStore(alerts_path)

    def base(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def public_status(st: dict[str, Any], request: Request) -> dict[str, Any]:
        out = {k: v for k, v in st.items() if k != "error_detail"}
        b = base(request)
        aid = st["id"]
        out["links"] = {"self": f"{b}/api/analyses/{aid}"}
        if st.get("status") == "done":
            out["links"]["result"] = f"{b}/api/analyses/{aid}/result"
        if (storage.local_dir(aid) / calib.PREVIEW_NAME).exists():
            out["links"]["pitch_preview"] = f"{b}/api/analyses/{aid}/pitch-preview"
            if isinstance(out.get("pitch"), dict):
                out["pitch"] = {**out["pitch"], "preview_url": out["links"]["pitch_preview"]}
        return out

    def status_or_404(aid: str) -> dict[str, Any]:
        st = jobs.get(aid)
        if st is None:
            raise HTTPException(404, f"No analysis with id {aid!r}.")
        return st

    def video_info(aid: str) -> VideoInfo:
        return VideoInfo(**read_json(storage, f"{aid}/upload.json")["video"])

    # ------------------------------------------------------------------ health
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "opencv_version": cv2.__version__,
                "rules_fingerprint": rules_fingerprint(cfg),
                "bedrock": "client available" if factory is not None else "not configured",
                "model_id": cfg["bedrock"]["model_id"], "region": cfg["aws"]["region"],
                "demo_available": demo.available(),
                "analyses": {"running": jobs.current, "queued": jobs.queued_count()},
                "usage_today": usage.snapshot(),
                "limits": {"max_upload_mb": round(api["uploads"]["max_bytes"] / 1e6),
                           "max_duration_s": api["uploads"]["max_duration_s"],
                           "views": ["top-down"]}}

    # ------------------------------------------------------------------ demo
    @app.get("/api/demo")
    def get_demo(request: Request) -> dict[str, Any]:
        if not demo.available():
            raise HTTPException(503, "The demo match files are missing on this server "
                                     f"({cfg['api']['demo']['dir']}).")
        return demo.bundle(base(request), demo_alerts(request))

    @app.get("/api/demo/alerts")
    def get_demo_alerts(request: Request) -> list[dict[str, Any]]:
        """The demo alerts with this visitor's own approve / reject (small; the desk reloads
        it instead of the whole bundle)."""
        if not demo.available():
            raise HTTPException(503, "The demo match files are missing on this server.")
        return demo_alerts(request)

    @app.get("/api/demo/files/{name}")
    def demo_file(name: str) -> FileResponse:
        p = demo.file_path(name)
        if p is None:
            raise HTTPException(404, f"No demo file {name!r}.")
        return FileResponse(p)

    @app.get("/api/demo/evidence/{event_id}.jpg")
    def demo_evidence(event_id: str) -> FileResponse:
        p = demo.file_path(f"{event_id}.jpg")
        if p is None:
            raise HTTPException(404, f"No evidence image for {event_id}.")
        return FileResponse(p, media_type="image/jpeg")

    # ------------------------------------------------------------------ analyses
    @app.post("/api/analyses", status_code=201)
    async def create_analysis(request: Request) -> dict[str, Any]:
        u = api["uploads"]
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > int(u["max_bytes"]) + 1_000_000:
            raise HTTPException(413, f"The video is larger than {u['max_bytes'] / 1e6:.0f} MB, "
                                     "the upload limit. Trim it to the part you want analysed.")
        if jobs.queued_count() >= int(api["jobs"]["max_queued"]):
            raise HTTPException(503, "Gaffer is busy with other analyses. Please try again in a "
                                     "few minutes.")
        form = await request.form()
        video = form.get("video") or form.get("file")
        if video is None or not hasattr(video, "filename"):
            raise HTTPException(422, "Attach the match video as the form field 'video'.")
        known_raw = str(form.get("known_source", "") or "").strip().lower()
        known = {"": None, "auto": None, "true": True, "1": True, "yes": True,
                 "false": False, "0": False, "no": False}.get(known_raw)
        if known_raw not in ("", "auto", "true", "1", "yes", "false", "0", "no"):
            raise HTTPException(422, "known_source must be true, false or auto.")
        points_raw = form.get("pitch_points")
        name = safe_name(video.filename)
        try:  # file copy and OpenCV off the event loop: status polls stay responsive
            return await run_in_threadpool(_create, request, video.file, name, known,
                                           str(points_raw) if points_raw else None)
        finally:
            await video.close()

    def _create(request: Request, src: Any, name: str, known: bool | None,
                points_raw: str | None) -> dict[str, Any]:
        aid = new_id()
        job_dir = storage.local_dir(aid)
        try:
            ext = check_extension(name, cfg)
            dest = job_dir / f"upload{ext}"
            with upload_lock:  # one copy at a time keeps disk use predictable
                nbytes = save_stream(src, dest, cfg)
            info = probe(dest, name, nbytes)
            ks = check_rules(name, info, cfg, known)
            points = calib.parse_points(points_raw) if points_raw else None
        except (UploadRefused, CalibrationError) as exc:
            _remove(job_dir)
            code = exc.status_code if isinstance(exc, UploadRefused) else 422
            raise HTTPException(code, str(exc)) from exc
        write_json(storage, f"{aid}/upload.json",
                   {"video": info.as_dict(), "upload_file": dest.name,
                    "known_source": None if ks is None else ks.__dict__})
        fields: dict[str, Any] = {"video": info.as_dict()}
        try:
            if ks is not None:
                clips = calib.write_clip_list(job_dir, dest.name, ks.match_start_s)
                pitch = calib.use_saved(cfg, job_dir, clips)
                fields["source"] = {"kind": ks.kind, "note": calib.known_note(ks)}
                jobs.create(aid, **fields, pitch=pitch)
                return public_status(jobs.enqueue(aid), request)
            calib.write_clip_list(job_dir, dest.name, 0.0)
            frame, idx = read_frame(dest, float(cfg["calibration"]["auto_detect"]["frame_t_s"]))
            calib.save_frame(job_dir, frame)
            fields["source"] = {"kind": "upload", "reference_frame": idx}
            if points is not None:
                pitch = calib.apply_corners(job_dir, frame, idx, info, points, cfg, "coach")
                jobs.create(aid, **fields, pitch={"state": "given", **pitch})
                return public_status(jobs.enqueue(aid), request)
            pitch = calib.autodetect(job_dir, frame, cfg)
            status = "needs_confirmation" if pitch["state"] == "detected" else "needs_corners"
            return public_status(jobs.create(aid, **fields, status=status, pitch=pitch),
                                 request)
        except CalibrationError as exc:
            _remove(job_dir)
            raise HTTPException(422, str(exc)) from exc
        except UploadRefused as exc:
            _remove(job_dir)
            raise HTTPException(exc.status_code, str(exc)) from exc

    def _apply(aid: str, points: Any, picked_by: str, t_s: float | None = None
               ) -> dict[str, Any]:
        info = video_info(aid)
        job_dir = storage.local_dir(aid)
        st = status_or_404(aid)
        idx = int((st.get("source") or {}).get("reference_frame", 0))
        if t_s is not None:  # the frame the coach clicked on becomes the reference frame
            frame, idx = read_frame(job_dir / read_json(storage, f"{aid}/upload.json")
                                    ["upload_file"], t_s)
            calib.save_frame(job_dir, frame)
        else:
            frame = calib.load_frame(job_dir)
        try:
            pitch = calib.apply_corners(job_dir, frame, idx, info, points, cfg, picked_by)
        except CalibrationError as exc:
            raise HTTPException(422, str(exc)) from exc
        prev = st.get("pitch") or {}
        jobs.update(aid, pitch={"state": "confirmed" if picked_by == "auto_confirmed"
                                else "given", "detection": prev.get("detection"), **pitch},
                    source={**(st.get("source") or {}), "reference_frame": idx})
        return jobs.enqueue(aid)

    def _check_pitch_step(st: dict[str, Any]) -> None:
        if st["status"] not in ("needs_confirmation", "needs_corners"):
            raise HTTPException(409, f"This analysis is {st['status']}: the pitch step is only "
                                     "open before the analysis starts.")

    @app.post("/api/analyses/{aid}/pitch")
    def set_pitch(aid: str, body: PitchRequest, request: Request) -> dict[str, Any]:
        st = status_or_404(aid)
        _check_pitch_step(st)
        if body.pitch_points is not None:
            try:
                pts = calib.parse_points(body.pitch_points)
            except CalibrationError as exc:
                raise HTTPException(422, str(exc)) from exc
            return public_status(_apply(aid, pts, "coach"), request)
        if body.confirmed:
            corners = (st.get("pitch") or {}).get("corners")
            if st["status"] != "needs_confirmation" or not corners:
                raise HTTPException(409, "There are no detected corners to confirm: please mark "
                                         "the 4 pitch corners (pitch_points).")
            return public_status(_apply(aid, corners, "auto_confirmed"), request)
        raise HTTPException(422, 'Send {"confirmed": true} or {"pitch_points": [[x, y], ...]} '
                                 "(top-left, top-right, bottom-right, bottom-left).")

    @app.post("/api/analyses/{aid}/start")
    def start(aid: str, body: StartRequest, request: Request) -> dict[str, Any]:
        """The frontend's pitch step: 4 points (or "straight down") start the analysis."""
        st = status_or_404(aid)
        if st["status"] in ("queued", "running", "done"):
            return public_status(st, request)  # known TeamTrack clip: already calibrated
        _check_pitch_step(st)
        info = video_info(aid)
        if body.straight_down:
            pts = calib.frame_edges(info)
        else:
            sx = info.width / body.frame.width if body.frame else 1.0
            sy = info.height / body.frame.height if body.frame else 1.0
            pts = [[p.x * sx, p.y * sy] for p in body.points]
        t_s = body.frame.t_s if body.frame and body.frame.t_s > 0 else None
        return public_status(_apply(aid, pts, "coach", t_s), request)

    @app.get("/api/analyses/{aid}/pitch-preview")
    def pitch_preview(aid: str) -> FileResponse:
        status_or_404(aid)
        p = storage.local_dir(aid) / calib.PREVIEW_NAME
        if not p.exists():
            raise HTTPException(404, "No pitch preview for this analysis.")
        return FileResponse(p, media_type="image/jpeg")

    @app.get("/api/analyses/{aid}/frame")
    def first_frame(aid: str) -> FileResponse:
        status_or_404(aid)
        p = storage.local_dir(aid) / calib.FRAME_NAME
        if not p.exists():
            raise HTTPException(404, "No reference frame for this analysis.")
        return FileResponse(p, media_type="image/jpeg")

    @app.get("/api/analyses/{aid}")
    def get_status(aid: str, request: Request) -> dict[str, Any]:
        return public_status(status_or_404(aid), request)

    @app.get("/api/analyses/{aid}/result")
    def get_result(aid: str, request: Request) -> dict[str, Any]:
        st = status_or_404(aid)
        if st.get("status") != "done":
            raise HTTPException(409, f"The analysis is not finished (status {st.get('status')}"
                                     f", stage {st.get('stage')}).")
        try:
            return analysis_result(storage, aid, st, store(), base(request))
        except StorageError as exc:
            raise HTTPException(500, f"A result file is missing: {exc}") from exc

    @app.get("/api/analyses/{aid}/evidence/{event_id}.jpg")
    def analysis_evidence(aid: str, event_id: str) -> FileResponse:
        status_or_404(aid)
        p = evidence_file(storage.local_dir(aid), event_id)
        if p is None:
            raise HTTPException(404, f"No evidence image for {event_id}.")
        return FileResponse(p, media_type="image/jpeg")

    # ------------------------------------------------------------------ alerts
    def _alert_url(a: dict[str, Any], request: Request) -> dict[str, Any]:
        if not a.get("evidence_image"):
            return a
        aid = a["alert_id"]  # uploads only: demo alerts already carry their URL
        if aid.startswith("alr_up_"):
            an = aid.removeprefix("alr_up_").rsplit("_evt_", 1)[0]
            return {**a, "evidence_image": evidence_url(base(request), f"/api/analyses/{an}",
                                                        a["event_id"])}
        return a

    def _decide(alert_id: str, approve: bool, body: DecisionRequest | None,
                request: Request) -> dict[str, Any]:
        note = body.note if body else None
        if demo.available() and demo.sample_alert(alert_id) is not None:
            # the demo is shared by every visitor: the decision is this visitor's only
            seed = next(a for a in demo.alerts(base(request)) if a["alert_id"] == alert_id)
            try:
                return demo_decisions.decide(visitor_id(request), seed, approve, note)
            except DecisionConflict as exc:
                raise HTTPException(409, str(exc)) from exc
        s = store()
        if alert_id not in s.all():
            raise HTTPException(404, f"No alert with id {alert_id!r}.")
        try:
            a = s.decide(alert_id, approve=approve, note=note)
        except AlertError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _alert_url(a.model_dump(), request)

    @app.post("/api/alerts/{alert_id}/approve")
    def approve(alert_id: str, request: Request, body: DecisionRequest | None = None
                ) -> dict[str, Any]:
        return _decide(alert_id, True, body, request)

    @app.post("/api/alerts/{alert_id}/reject")
    def reject(alert_id: str, request: Request, body: DecisionRequest | None = None
               ) -> dict[str, Any]:
        return _decide(alert_id, False, body, request)

    # ------------------------------------------------------------------ chat
    def chat_source(match_id: str, request: Request) -> ChatSource:
        if match_id == demo.id:
            if not demo.available():
                raise HTTPException(503, "The demo match files are missing on this server.")
            return ChatSource(demo.id, demo.context(), demo.decisions(), demo_alerts(request))
        st = jobs.get(match_id)
        if st is None:
            raise HTTPException(404, f"No analysis with id {match_id!r}.")
        if st.get("status") != "done":
            raise HTTPException(409, "Chat opens once the analysis is finished.")
        with ctx_lock:
            ctx = ctx_cache.get(match_id)
            if ctx is None:
                from gaffer.agent.context import MatchContext
                from gaffer.schema import parse_match_state

                m = parse_match_state(read_json(storage, f"{match_id}/match_state.json"))
                ctx = MatchContext(m, calib.job_config(cfg, storage.local_dir(match_id)),
                                   view=api["jobs"]["view"])
                ctx_cache[match_id] = ctx
                while len(ctx_cache) > 4:
                    ctx_cache.popitem(last=False)
        decided = read_json(storage, f"{match_id}/explanations.json")["candidates"]
        mid = st.get("match_id") or f"up_{match_id}"
        alerts = [a.model_dump() for a in store().all().values()
                  if a.alert_id.startswith(f"alr_{mid}_")]
        return ChatSource(match_id, ctx, decided, alerts)

    @app.post("/api/chat")
    def post_chat(body: ChatRequest, request: Request) -> dict[str, Any]:
        src = chat_source(body.match_id, request)
        # header, else the visitor cookie the browser sent back, else the client IP (a client
        # that drops cookies must not get a fresh daily allowance on every question)
        visitor = request.headers.get("x-visitor-id") or (
            visitor_id(request) if getattr(request.state, "visitor_from_cookie", False)
            else (request.client.host if request.client else "unknown"))
        try:
            return chat.ask(src, body.question, [t.model_dump() for t in body.history],
                            visitor)
        except ChatRefused as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    # ------------------------------------------------------------------ frontend
    dist = repo_path(api.get("web_dist", "web/dist"))
    if (dist / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "Not found.")
            p = (dist / path).resolve()
            if path and p.is_file() and dist.resolve() in p.parents:
                return FileResponse(p)
            return FileResponse(dist / "index.html")  # client-side routes (/app)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal server error. The details are in the server "
                                       "log."}, status_code=500)

    return app


def _remove(job_dir: Path) -> None:
    import shutil

    shutil.rmtree(job_dir, ignore_errors=True)


def __getattr__(name: str) -> Any:
    """`uvicorn gaffer.api.main:app` builds the app on first access (not at import, so tests
    and scripts can import this module without starting a worker)."""
    if name == "app":
        app_ = create_app()
        globals()["app"] = app_
        return app_
    raise AttributeError(name)
