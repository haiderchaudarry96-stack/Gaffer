"""Real video -> contract-valid `MatchState` (`source: "video"`), with OpenCV 5.

Per sampled frame (each stage timed):

1. **decode** - `VideoSource` (a video or a `*.clips.json` list), sequential `cv2.VideoCapture`;
2. **geometry** - `GeometryProvider`: the view's calibration, re-anchored on every frame for the
   drifting drone (`cv2.phaseCorrelate` + `cv2.findTransformECC`), with the per-frame line
   alignment error that fills `quality.reprojection_error_m` / `homography_ok`;
3. **detection** - the view's detector (`detector.views.<view>.method`: classical blobs on the
   drone view, tiled YOLOX in `cv2.dnn` on the side view);
4. **tracking** - ByteTrack with enlarged matching boxes (`perception/tracker.py`), at
   `track_fps`, an integer multiple of the output rate;
5. **team features** - torso colour per box (`perception/team_classifier.py`).

After the pass: team colours are learnt with `cv2.kmeans` over all crops (or a given model is
reused), each track votes (unknown until settled), tracks in other colours become goalkeepers
(by the half they stand in) or referees, the attacking direction is inferred from the deepest
players, and `perception/matchstate.py` applies the shared contract rules (same as the oracle).

`run_window(source, start_s, end_s, fps)` is the entry point for Phase 3's `reanalyse_window`
vision tool: the same pipeline on a short window at a higher rate.

CLI:
    py -m gaffer.perception.pipeline --source data\\clips\\teamtrack_top.clips.json \\
        --out outputs\\match_state_top.json --debug-video outputs\\debug_top.mp4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from gaffer.config import load_config, repo_path
from gaffer.perception.detector import BALL, DetectorError, make_detector
from gaffer.perception.drift import GeometryProvider
from gaffer.perception.matchstate import (
    ObservedFrame,
    ObservedPlayer,
    assemble,
    infer_attacking_direction,
    on_pitch,
)
from gaffer.perception.pitch import Calibration, CalibrationError, PitchMapper, PitchModel
from gaffer.perception.render import annotate_frame, compose, draw_minimap
from gaffer.perception.team_classifier import (
    TeamClassifierError,
    TeamModel,
    TeamSettings,
    TrackVoter,
    fit_team_model,
    resolve_others_frame,
    shirt_features,
)
from gaffer.perception.tracker import PlayerTracker, TrackerSettings
from gaffer.perception.video import VideoError, VideoSource
from gaffer.schema import ContractError, MatchState

GENERATOR = "perception.pipeline v1.0"
STAGES = ("decode", "geometry", "detection", "tracking", "team_features", "team_fit",
          "labelling", "assemble", "debug_video")


class PipelineError(RuntimeError):
    """The pipeline cannot produce a MatchState for this input."""


class TooFewPlayersError(PipelineError):
    """Too few players were detected to say anything about the teams."""


@dataclass
class FrameRecord:
    """Everything the pipeline knows about one tracked frame (eval scripts read these)."""

    t: float
    output: bool  # on the output grid (written to the MatchState)
    boxes: np.ndarray  # (N, 4) xywh, native pixels
    scores: np.ndarray
    track_ids: np.ndarray  # -1 = not tracked in this frame
    xy: np.ndarray  # (N, 2) foot points in pitch metres
    feats: np.ndarray  # (N, 3) shirt features
    feat_ok: np.ndarray
    ball: tuple[float, float] | None
    quality: dict[str, Any]
    mapper: PitchMapper
    teams: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    conf: np.ndarray = field(default_factory=lambda: np.zeros(0))
    jpeg: bytes | None = None  # downscaled frame for the debug video


@dataclass
class PipelineResult:
    match: MatchState
    records: list[FrameRecord]
    team_model: TeamModel
    timing: dict[str, float]
    view: str
    video_seconds: float
    directions_inferred: bool

    def timing_table(self) -> str:
        """Per-stage timing summary (seconds, ms per tracked frame, share of the total)."""
        n = max(1, len(self.records))
        total = sum(self.timing.values())
        lines = [f"{'stage':14s} {'total s':>8s} {'ms/frame':>9s} {'share':>6s}"]
        for k in STAGES:
            v = self.timing.get(k, 0.0)
            lines.append(f"{k:14s} {v:8.1f} {1000 * v / n:9.1f} {v / max(total, 1e-9):6.1%}")
        lines.append(f"{'TOTAL':14s} {total:8.1f} {1000 * total / n:9.1f}")
        rt = total / max(self.video_seconds, 1e-9)
        lines.append(f"{n} tracked frames for {self.video_seconds:.1f} s of video "
                     f"({len(self.match.frames)} output frames at {self.match.fps:g} fps): "
                     f"{rt:.2f} s of processing per second of video")
        return "\n".join(lines)


# --------------------------------------------------------------------------- helpers


def view_for_size(cfg: dict[str, Any], width: int, height: int) -> str:
    """The configured view whose calibration matches the video size."""
    seen = []
    for view in cfg["detector"]["views"]:
        try:
            calib = Calibration.for_view(cfg, view)
        except CalibrationError:
            continue
        seen.append(f"{view} {calib.image_size[0]}x{calib.image_size[1]}")
        if tuple(calib.image_size) == (width, height):
            return view
    raise CalibrationError(
        f"No calibration matches a {width}x{height} video (have: {', '.join(seen) or 'none'}). "
        "Run `py scripts\\calibrate.py --view <view>` for this camera, or pass --view.")


def foot_xy(boxes: np.ndarray, mode: str) -> np.ndarray:
    """Ground contact point of xywh boxes: `centre` (drone) or `bottom` (side camera)."""
    b = np.asarray(boxes, float).reshape(-1, 4)
    if mode == "centre":
        return b[:, :2] + b[:, 2:] / 2
    return np.stack([b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3]], axis=1)


def _match_id(uri: str) -> str:
    name = Path(uri).name
    for suffix in (".clips.json", ".mp4", ".avi", ".mov", ".mkv"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return Path(uri).stem


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(repo_path(".").resolve()).as_posix()
    except ValueError:
        return p.as_posix()


# --------------------------------------------------------------------------- pipeline


def run(source: str | Path, *, view: str | None = None, start_s: float | None = None,
        end_s: float | None = None, fps: float | None = None, track_fps: float | None = None,
        cfg: dict[str, Any] | None = None, team_model: TeamModel | None = None,
        directions: dict[str, str] | None = None, debug_video: str | Path | None = None,
        match_id: str | None = None, video_start_s: float = 0.0, progress: bool = False
        ) -> PipelineResult:
    """Run the perception pipeline (see module docstring).

    Args:
        source: a video file or a `*.clips.json` clip list.
        view: calibration/detector view; default: the calibration matching the video size.
        start_s, end_s: match-time window (default: the whole source).
        fps: output sampling rate (default `perception.sample_fps`).
        track_fps: detection + tracking rate, an integer multiple of `fps` (default
            `perception.track_fps`, at least `fps`).
        team_model: reuse learnt team colours (e.g. from the full-match run) instead of
            fitting them on this run.
        directions: attacking direction per side; default: inferred from the deepest players.
        debug_video: write an annotated video with a 2D minimap here.
        video_start_s: match time of the first frame of a plain video file.

    Raises:
        VideoError, CalibrationError, DetectorError, TooFewPlayersError, ContractError.
    """
    cfg = cfg if cfg is not None else load_config()
    pcfg = cfg["perception"]
    timing: dict[str, float] = defaultdict(float)
    src = VideoSource(source, start_s=video_start_s)
    view = view or view_for_size(cfg, src.width, src.height)
    calib = Calibration.for_view(cfg, view)
    if tuple(calib.image_size) != (src.width, src.height):
        raise CalibrationError(f"the {view} calibration is for {calib.image_size[0]}x"
                               f"{calib.image_size[1]} frames, the video is {src.width}x"
                               f"{src.height}")
    model = PitchModel(calib.length_m, calib.width_m)
    detector = make_detector(cfg, view, model)
    geo = GeometryProvider(calib, cfg, view, model)
    ts = TeamSettings.from_config(cfg, view)
    foot_mode = pcfg["foot_point"][view]

    fps = float(fps or pcfg["sample_fps"])
    track_fps = float(track_fps or max(fps, float(pcfg["track_fps"])))
    mult = track_fps / fps
    if mult < 1 or abs(mult - round(mult)) > 1e-6:
        raise PipelineError(f"track_fps ({track_fps:g}) must be an integer multiple of the "
                            f"output fps ({fps:g}) so that output frames are tracked frames")
    mult = int(round(mult))
    a = src.start_s if start_s is None else max(float(start_s), src.start_s)
    b = src.end_s if end_s is None else min(float(end_s), src.end_s)
    if b <= a:
        raise VideoError(f"empty window {a:.2f}-{b:.2f} s (video covers "
                         f"{src.start_s:.2f}-{src.end_s:.2f} s)")
    times = src.sample_times(track_fps, a, b)
    if not times:
        raise VideoError(f"no frames in {a:.2f}-{b:.2f} s of {source}")
    is_out = {t: int(round((t - a) * track_fps)) % mult == 0 for t in times}

    tracker = PlayerTracker(TrackerSettings.from_config(cfg, view), track_fps)
    if hasattr(detector, "reset"):
        detector.reset(track_fps)  # stateful background model: learns at this rate
    dv = pcfg["debug_video"]
    want_video = debug_video is not None
    rows = dv["side_rows"] if view == "side" else [0, src.height]
    jscale = float(dv["width_px"]) / src.width

    records: list[FrameRecord] = []
    t0 = time.perf_counter()
    for k, (t, _, _, frame) in enumerate(src.frames(times)):
        t1 = time.perf_counter()
        timing["decode"] += t1 - t0
        g = geo.for_frame(frame)
        t2 = time.perf_counter()
        timing["geometry"] += t2 - t1
        det = detector.detect(frame, g.mapper)
        persons = det.persons()
        t3 = time.perf_counter()
        timing["detection"] += t3 - t2
        ids = tracker.update(persons)
        t4 = time.perf_counter()
        timing["tracking"] += t4 - t3
        feats, ok = shirt_features(frame, persons.boxes, ts)
        xy = g.mapper.to_pitch(foot_xy(persons.boxes, foot_mode)) if len(persons) \
            else np.zeros((0, 2))
        ball = None
        balls = det.select(det.classes == BALL)
        if len(balls):
            bxy = g.mapper.to_pitch(foot_xy(balls.boxes, foot_mode))
            good = on_pitch(bxy, model.length, model.width, 0.0)
            if good.any():
                j = int(np.argmax(np.where(good, balls.scores, -1)))
                ball = (float(bxy[j, 0]), float(bxy[j, 1]))
        jpeg = None
        if want_video and is_out[t]:
            tj = time.perf_counter()
            small = cv2.resize(frame[rows[0]:rows[1]], None, fx=jscale, fy=jscale,
                               interpolation=cv2.INTER_AREA)
            jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
            timing["debug_video"] += time.perf_counter() - tj
            t4 += time.perf_counter() - tj  # not a team-feature cost
        records.append(FrameRecord(
            t=t, output=is_out[t], boxes=persons.boxes, scores=persons.scores, track_ids=ids,
            xy=xy, feats=feats, feat_ok=ok, ball=ball,
            quality={"players_detected": int(len(persons)), "homography_ok": bool(g.homography_ok),
                     "reprojection_error_m": g.reprojection_error_m, "camera_cut": False},
            mapper=g.mapper, jpeg=jpeg))
        t0 = time.perf_counter()
        timing["team_features"] += t0 - t4
        if progress and (k + 1) % 20 == 0:
            print(f"  [{k + 1}/{len(times)}] t={t:.1f}s {len(persons)} players, "
                  f"{(t0 - t1) * 1000:.0f} ms", flush=True)

    out_recs = [r for r in records if r.output]
    med = float(np.median([len(r.boxes) for r in out_recs])) if out_recs else 0.0
    min_pf = float(pcfg["min_players_per_frame"])
    if med < min_pf:
        raise TooFewPlayersError(
            f"only {med:g} players detected per frame (median over {len(out_recs)} frames, "
            f"need >= {min_pf:g}): wrong view/calibration, camera not showing the pitch, or a "
            "close-up")

    # ---- team colours
    t5 = time.perf_counter()
    if team_model is None:
        feats_all = np.concatenate([r.feats[r.feat_ok] for r in records]) \
            if records else np.zeros((0, 3))
        hints = {s: pcfg["teams"][s]["shirt_hint"] for s in ("home", "away")}
        try:
            team_model = fit_team_model(feats_all, hints, ts, seed=int(cfg.get("seed", 42)))
        except TeamClassifierError as exc:
            raise TooFewPlayersError(str(exc)) from exc
    t6 = time.perf_counter()
    timing["team_fit"] += t6 - t5

    # ---- per-track votes (causal: unknown until settled), keepers and referees by position
    voter = TrackVoter(ts)
    track_pos: dict[int, list[np.ndarray]] = defaultdict(list)
    for r in records:
        lab, _ = team_model.classify(r.feats)
        r.teams, shares = [], []
        for i in range(len(r.boxes)):
            tid = int(r.track_ids[i])
            if tid < 0:
                r.teams.append("unknown")
                shares.append(0.0)
                continue
            lbl, share = voter.add(tid, int(lab[i]) if r.feat_ok[i] else None)
            r.teams.append(lbl)
            shares.append(share)
            track_pos[tid].append(r.xy[i])
        r.roles = ["outfield"] * len(r.boxes)
        r.conf = np.clip(r.scores, 0, 1) * np.array(shares) if len(r.boxes) else np.zeros(0)
    track_med = {tid: np.median(np.array(p), axis=0) for tid, p in track_pos.items()}
    track_len = {tid: len(p) for tid, p in track_pos.items()}
    # static objects: a track that never moves is not a person (spare balls behind a goal were
    # labelled "home" in 198 drone frames, FAILURE_LOG 2026-10-14). Dropped from the output.
    so = pcfg["static_object"]
    static = {tid for tid, p in track_pos.items()
              if len(p) / track_fps >= float(so["min_s"])
              and np.percentile(np.linalg.norm(np.array(p) - track_med[tid], axis=1), 95)
              <= float(so["max_spread_m"])}
    for r in records:
        for i in range(len(r.boxes)):
            if int(r.track_ids[i]) in static:
                r.teams[i] = "static"

    def observed(recs: list[FrameRecord], with_other: bool) -> list[ObservedFrame]:
        out = []
        for r in recs:
            players = [ObservedPlayer(int(r.track_ids[i]), r.teams[i], float(r.xy[i, 0]),
                                      float(r.xy[i, 1]), r.roles[i], float(r.conf[i]))
                       for i in range(len(r.boxes)) if r.track_ids[i] >= 0
                       and r.teams[i] != "static"
                       and (with_other or r.teams[i] in ("home", "away"))]
            out.append(ObservedFrame(t=r.t, players=players, ball=r.ball, quality=r.quality))
        return out

    inferred = directions is None
    if directions is None:
        directions = infer_attacking_direction(observed(out_recs, False), model.length)
    notes = []
    if directions is None:
        directions = {"home": "right", "away": "left"}
        notes.append("attacking direction could not be inferred (a team was never seen); "
                     "assumed home attacks right")
    defends_left = "home" if directions["home"] == "right" else "away"
    for r in records:
        items = [(i, r.xy[i], track_med[int(r.track_ids[i])], track_len[int(r.track_ids[i])])
                 for i in range(len(r.boxes)) if r.teams[i] == "other"]
        if items:
            for i, (team, role) in resolve_others_frame(items, model.length, model.width,
                                                        defends_left, ts).items():
                r.teams[i], r.roles[i] = team, role
    t7 = time.perf_counter()
    timing["labelling"] += t7 - t6

    # ---- MatchState (shared rules with the oracle)
    teams = {s: {"name": pcfg["teams"][s]["name"], "colour": pcfg["teams"][s]["colour"]}
             for s in ("home", "away")}
    src_path = repo_path(source)
    notes.append(f"view {view}, detector {detector.name}, tracking {track_fps:g} fps, output "
                 f"{fps:g} fps, window {a:.1f}-{b:.1f} s; camera_cut not evaluated (static "
                 "cameras)")
    match = assemble(  # validates against the contract (ContractError if anything is off)
        match_id or _match_id(str(source)), "video", fps, model.length, model.width,
        observed(out_recs, True), teams, directions,
        {"uri": _rel(src_path), "native_fps": src.native_fps, "width": src.width,
         "height": src.height},
        GENERATOR, "; ".join(notes), float(pcfg["possession_radius_m"]), duration_s=b)
    t8 = time.perf_counter()
    timing["assemble"] += t8 - t7

    if debug_video is not None:
        write_debug_video(debug_video, out_recs, model, cfg, view, jscale, rows, fps)
        timing["debug_video"] += time.perf_counter() - t8
    return PipelineResult(match, records, team_model, dict(timing), view, b - a, inferred)


def write_debug_video(path: str | Path, recs: list[FrameRecord], model: PitchModel,
                      cfg: dict[str, Any], view: str, jscale: float, rows: list[int],
                      fps: float) -> Path:
    """Annotated frames (team-coloured boxes, track ids) + 2D minimap, at the output rate."""
    dv = cfg["perception"]["debug_video"]
    colours = dv["colours_bgr"]
    p = repo_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    for r in recs:
        if r.jpeg is None:
            continue
        img = cv2.imdecode(np.frombuffer(r.jpeg, np.uint8), cv2.IMREAD_COLOR)
        boxes = r.boxes.copy()
        if len(boxes):
            boxes[:, 1] -= rows[0]
            boxes = boxes * jscale
        img = annotate_frame(img, boxes, r.teams, r.roles, r.track_ids, colours, thickness=2)
        players = [{"x": float(r.xy[i, 0]), "y": float(r.xy[i, 1]), "team": r.teams[i],
                    "role": r.roles[i]} for i in range(len(r.boxes)) if r.track_ids[i] >= 0
                   and r.teams[i] != "static"
                   and on_pitch(r.xy[i:i + 1], model.length, model.width)[0]]
        n_team = sum(1 for q in players if q["team"] in ("home", "away"))
        rot = view in dv.get("minimap_rotate_180", [])
        mm = draw_minimap(model, players, colours, float(dv["minimap_px_per_m"]), r.ball,
                          f"t={r.t:.1f}s  {n_team} team players"
                          + ("  (map rotated to match camera)" if rot else ""), rot)
        q = r.quality
        header = (f"Gaffer perception | {view} | t={r.t:.1f}s | detected "
                  f"{q['players_detected']} | homography_ok {q['homography_ok']} | "
                  f"line err {q['reprojection_error_m']} m")
        frame = compose(img, mm, int(dv["width_px"]), header)
        if writer is None:
            writer = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                     (frame.shape[1], frame.shape[0]))
            if not writer.isOpened():
                raise VideoError(f"OpenCV could not open a video writer for {p}")
        writer.write(frame)
    if writer is not None:
        writer.release()
    return p


def run_window(source: str | Path, start_s: float, end_s: float, fps: float,
               **kwargs: Any) -> MatchState:
    """Re-run perception on [start_s, end_s) at `fps` (Phase 3 `reanalyse_window`).

    Tracking runs at `fps` (or `track_fps` if given). Pass `team_model` / `directions` from the
    full-match run to keep team names consistent on short windows.
    """
    kwargs.setdefault("track_fps", fps)
    return run(source, start_s=start_s, end_s=end_s, fps=fps, **kwargs).match


def write_outputs(res: PipelineResult, path: str | Path) -> tuple[Path, Path]:
    """Write the MatchState and, next to it, `<name>.teams.json`: the learnt team colours and
    attacking directions, so a later `run_window` can reuse them."""
    out = repo_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(res.match.model_dump_json(by_alias=True), encoding="utf-8")
    side = out.with_name(out.name.removesuffix(".json") + ".teams.json")
    side.write_text(json.dumps({"view": res.view, "team_model": res.team_model.to_dict(),
                                "directions": {s: getattr(res.match.teams, s)
                                               .attacking_direction_first_half
                                               for s in ("home", "away")}}, indent=2),
                    encoding="utf-8")
    return out, side


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Video -> match_state.json (OpenCV 5 perception)")
    ap.add_argument("--source", required=True, help="video file or *.clips.json")
    ap.add_argument("--out", required=True, help="output match_state.json")
    ap.add_argument("--view", default=None, help="calibration view (default: by video size)")
    ap.add_argument("--start", type=float, default=None, help="window start (match seconds)")
    ap.add_argument("--end", type=float, default=None, help="window end (match seconds)")
    ap.add_argument("--fps", type=float, default=None, help="output fps (default config)")
    ap.add_argument("--track-fps", type=float, default=None,
                    help="tracking fps, integer multiple of --fps (default config)")
    ap.add_argument("--video-start-s", type=float, default=0.0,
                    help="match time of the first frame of a plain video file")
    ap.add_argument("--debug-video", default=None, help="write an annotated .mp4 here")
    ap.add_argument("--match-id", default=None)
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    try:
        res = run(args.source, view=args.view, start_s=args.start, end_s=args.end,
                  fps=args.fps, track_fps=args.track_fps, debug_video=args.debug_video,
                  match_id=args.match_id, video_start_s=args.video_start_s, progress=True)
    except (VideoError, CalibrationError, DetectorError, PipelineError, ContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    out, side = write_outputs(res, args.out)
    m = res.match
    labels = defaultdict(int)
    for f in m.frames:
        for p in f.players:
            labels[p.team if p.role == "outfield" else f"{p.team} GK"] += 1
    n = max(1, len(m.frames))
    print(f"\n{m.match_id}: {len(m.frames)} frames at {m.fps:g} fps "
          f"({m.frames[0].t:.1f}-{m.frames[-1].t:.1f} s), view {res.view}")
    print("players per frame by label: " + ", ".join(f"{k} {v / n:.1f}"
                                                     for k, v in sorted(labels.items())))
    print(f"team model: {res.team_model.fit_samples} crops, "
          f"{res.team_model.outlier_share:.1%} outside both team gates; attacking direction "
          f"{'inferred' if res.directions_inferred else 'given'}: home "
          f"{m.teams.home.attacking_direction_first_half}")
    print("\n" + res.timing_table())
    print(f"wall time {time.perf_counter() - t0:.1f} s\n-> {out}\n-> {side}"
          + (f"\n-> {repo_path(args.debug_video)}" if args.debug_video else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
