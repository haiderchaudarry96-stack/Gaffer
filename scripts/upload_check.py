"""Run one video through the normal upload path (in-process API, Bedrock off) and report it.

The same code the web app runs: `POST /api/analyses` (upload rules, pitch auto-detect), then
`POST /api/analyses/<id>/pitch {"confirmed": true}` (the coach confirms the detected outline),
then the analysis worker (`api.jobs.run_analysis`: OpenCV pipeline, tactics engine, agent with
the rules arm, explanations and report from the code templates). No AWS call is made.

`--perception-only` stops after the pipeline and the tactics engine (the candidate list, no
agent): the same MatchState the worker would make, in a fraction of the time.

`--compare-demo` prints the candidate list next to the Phase 3 demo record (`api.demo.dir`):
the demo MatchState through the same tactics engine, plus the agent decisions stored with it.
A demo candidate counts as found when the upload has a candidate of the same team and the same
from -> to within `eval.synthetic.tolerance_s`.

`--cfg a.b.c=value` overrides a config value for this run only (YAML-parsed), e.g.
`--cfg perception.self_calibration.pitch_mask=false`.

    py scripts/upload_check.py --video data/sample_clips/teamtrack_top_0900_1260_4k.mp4 \
        --out outputs/upload_check/demo_after --compare-demo
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

from gaffer.config import load_config, repo_path, with_overrides


def demo_candidates(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The demo MatchState's candidates (same tactics engine) with the stored agent decisions."""
    from gaffer.schema import load_match_state
    from gaffer.tactics.common import TacticsConfig
    from gaffer.tactics.timeline import build_timeline

    d = cfg["api"]["demo"]
    root = repo_path(d["dir"])
    match = load_match_state(root / d["files"]["match_state"])
    res = build_timeline(match, TacticsConfig.from_config(cfg))
    rows = json.loads((root / d["files"]["run_rows"]).read_text(encoding="utf-8"))
    rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
    dec = {r["event_id"]: r.get("decision") for r in rows if isinstance(r, dict)}
    return [{"event_id": e.id, "team": e.team, "t": float(e.t), "from": e.from_, "to": e.to,
             "decision": dec.get(e.id, "not checked")} for e in res.timeline.events]


def compare(demo: list[dict[str, Any]], up: list[dict[str, Any]], offset_s: float,
            tol_s: float) -> dict[str, Any]:
    """Match demo candidates to upload candidates (same team, from, to; |dt| <= tol_s)."""
    used: set[int] = set()
    pairs = []
    for c in demo:
        best = min((i for i, u in enumerate(up) if i not in used and u["team"] == c["team"]
                    and u["from"] == c["from"] and u["to"] == c["to"]
                    and abs(u["t"] + offset_s - c["t"]) <= tol_s),
                   key=lambda i: abs(up[i]["t"] + offset_s - c["t"]), default=None)
        if best is not None:
            used.add(best)
        pairs.append({"demo": c, "upload": None if best is None else up[best], "match": "exact"})
    for p in pairs:  # looser: same team and same new shape (the shape before read differently)
        if p["upload"] is not None:
            continue
        c = p["demo"]
        best = min((i for i, u in enumerate(up) if i not in used and u["team"] == c["team"]
                    and u["to"] == c["to"] and abs(u["t"] + offset_s - c["t"]) <= tol_s),
                   key=lambda i: abs(up[i]["t"] + offset_s - c["t"]), default=None)
        if best is not None:
            used.add(best)
            p["upload"], p["match"] = up[best], "same new shape"
    return {"pairs": pairs, "upload_only": [u for i, u in enumerate(up) if i not in used]}


def clock(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


class _TeamTrackUploadSource:
    """Map upload-relative time to the matching TeamTrack annotation frame."""

    def __init__(self, fps: float, clips: list[Any], offset_s: float) -> None:
        self.fps, self.clips, self.offset_s = float(fps), clips, float(offset_s)

    def locate(self, t: float) -> tuple[int, int] | None:
        """Return (clip index, frame index) for a time within the uploaded sequence."""
        match_t = self.offset_s + float(t)
        for index, clip in enumerate(self.clips):
            if clip.start_s <= match_t < clip.end_s:
                return index, int(round((match_t - clip.start_s) * self.fps))
        return None


def _formation_coverage(match: Any, cfg: dict[str, Any]) -> dict[str, float | None]:
    """Share of frames with enough outfield players for each team."""
    from gaffer.tactics.common import TacticsConfig, extract_team_frames

    tc = TacticsConfig.from_config(cfg)
    frames = extract_team_frames(match, tc)
    return {side: (sum(len(frame.outfield) >= tc.min_players for frame in frames[side])
                   / len(frames[side]) if frames[side] else None)
            for side in ("home", "away")}


def _white_change(result: Any, cfg: dict[str, Any], offset_s: float) -> bool:
    """Check whether the known White 16:30 change is present among candidates."""
    from gaffer.agent.context import MatchContext

    ctx = MatchContext(result.match, cfg, view="top")
    tolerance = float(cfg["eval"]["synthetic"]["tolerance_s"])
    return any(c.team == "home" and c.to == "3-4-3"
               and abs(float(c.t) + offset_s - 990.0) <= tolerance for c in ctx.candidates)


def _score_teamtrack_upload(result: Any, cfg: dict[str, Any], clips: list[Any], gts: list[Any],
                            fps: float, offset_s: float) -> dict[str, Any]:
    """Score detection, team labels, and formation coverage on the TeamTrack upload window."""
    from eval_tracking import score as tracking_score

    mapped = _TeamTrackUploadSource(fps, clips, offset_s)
    scored = tracking_score(result, cfg, "top", mapped, gts,
                            float(cfg["tracking"]["eval"]["match_m"]["top"]))
    return {"precision": scored["detection"]["raw"]["precision"],
            "recall": scored["detection"]["raw"]["recall"],
            "f1": scored["detection"]["raw"]["f1"],
            "team_accuracy": scored["teams"]["accuracy_settled"],
            "team_label_share": round(1 - scored["teams"]["unknown_share"], 4),
            "detections_per_frame": scored["detection"]["det_per_frame"],
            "formation_coverage": _formation_coverage(result.match, cfg),
            "white_16_30_change_found": _white_change(result, cfg, offset_s),
            "scoring_frames": scored["frames"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--video", required=True)
    ap.add_argument("--name", default=None, help="upload file name (default: the file's name)")
    ap.add_argument("--out", required=True, help="folder for everything this run writes")
    ap.add_argument("--cfg", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--perception-only", action="store_true")
    ap.add_argument("--compare-demo", action="store_true")
    ap.add_argument("--agentic-calibration", "--tier2", dest="tier2", action="store_true",
                    help="enable numeric-only Tier 2 after configured health checks")
    ap.add_argument("--tier1", action="store_true",
                    help="apply the Tier 1 low-pixels-per-metre rule")
    ap.add_argument("--start-s", type=float, default=None, help="analysis window start")
    ap.add_argument("--end-s", type=float, default=None, help="analysis window end")
    ap.add_argument("--demo-offset-s", type=float, default=900.0,
                    help="match time of the upload's first frame for --compare-demo")
    ap.add_argument("--corners", default=None,
                    help="JSON 4 points instead of confirming the auto-detected outline")
    args = ap.parse_args(argv)
    if args.tier2 and not args.perception_only:
        ap.error("--tier2 requires --perception-only")

    from fastapi.testclient import TestClient

    from gaffer.api.event_store import EventStore
    from gaffer.api.main import create_app
    from gaffer.api.storage import LocalStorage
    from gaffer.api.usage import Usage

    cfg = with_overrides(load_config(), args.cfg)
    out = repo_path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg["api"]["posture"]["trace_path"] = str(out / "posture_trace.jsonl")
    cfg["api"]["event_store"]["path"] = str(out / "events.sqlite3")
    app = create_app(cfg, storage=LocalStorage(out / "api"), llm_factory=None,
                     usage=Usage(cfg, str(out / "usage.json")),
                     event_store=EventStore(out / "events.sqlite3"),
                     alerts_path=out / "alerts.jsonl", chat_trace=out / "chat_trace.jsonl",
                     start_worker=False)
    client = TestClient(app)
    video = Path(args.video)
    name = args.name or video.name
    t0 = time.perf_counter()
    with video.open("rb") as fh:
        r = client.post("/api/analyses", files={"video": (name, fh, "video/mp4")})
    if r.status_code >= 300:
        print(f"ERROR: upload refused ({r.status_code}): {r.text}", file=sys.stderr)
        return 2
    st = r.json()
    aid = st["id"]
    pitch = st.get("pitch") or {}
    det = pitch.get("detection") or {}
    report: dict[str, Any] = {"video": str(video), "upload_name": name, "analysis_id": aid,
                              "overrides": args.cfg, "status_after_upload": st["status"],
                              "pitch_detection": det}
    print(f"upload {name}: {st['status']}; pitch auto-detect accepted={det.get('accepted')} "
          f"confidence={det.get('confidence')} line error {det.get('line_error_m')} m")
    if st["status"] in ("needs_confirmation", "needs_corners"):
        body = ({"pitch_points": json.loads(args.corners)} if args.corners else
                {"confirmed": True} if st["status"] == "needs_confirmation" else None)
        if body is None:
            print("ERROR: the pitch was not found; pass --corners", file=sys.stderr)
            (out / "upload_check.json").write_text(json.dumps(report, indent=2))
            return 3
        r = client.post(f"/api/analyses/{aid}/pitch", json=body)
        if r.status_code >= 300:
            print(f"ERROR: pitch step refused ({r.status_code}): {r.text}", file=sys.stderr)
            return 2
    jobs = app.state.jobs
    job_dir = app.state.storage.local_dir(aid)
    if args.perception_only:
        from gaffer.agent.context import MatchContext
        from gaffer.api.calib import CLIPS_NAME, job_config
        from gaffer.api.main import _bedrock_factory
        from gaffer.perception.calibration_loop import pixels_per_metre, tier1_config
        from gaffer.perception.pipeline import run, write_outputs
        from gaffer.perception.pitch import Calibration, image_corners

        jcfg = job_config(cfg, job_dir)
        start_s, end_s = args.start_s, args.end_s
        cal = Calibration.for_view(jcfg, cfg["api"]["jobs"]["view"])
        pitch = st.get("pitch") or {}
        detection = pitch.get("detection") or {}
        corners = detection.get("corners") or pitch.get("corners")
        if not corners:
            corners = image_corners(cal.mapper(), float(cfg["pitch"]["length_m"]),
                                    float(cfg["pitch"]["width_m"]))
        px_per_m = pixels_per_metre(corners, float(cfg["pitch"]["length_m"]),
                                    float(cfg["pitch"]["width_m"]))
        run_cfg = copy.deepcopy(jcfg)
        if args.tier1:
            run_cfg["perception"]["self_calibration"]["calibration_tiers"]["tier1"]\
                ["enabled"] = True
            run_cfg, _ = tier1_config(run_cfg, px_per_m)
        res = run(job_dir / CLIPS_NAME, view=cfg["api"]["jobs"]["view"], cfg=run_cfg,
                  start_s=start_s, end_s=end_s, match_id=f"up_{aid}")
        baseline = res
        calibration = None
        if args.tier1 or args.tier2:
            from gaffer.perception.calibration_loop import run_calibration_loop

            tier_cfg = copy.deepcopy(run_cfg)
            tiers = tier_cfg["perception"]["self_calibration"]["calibration_tiers"]
            tiers["tier1"]["enabled"] = bool(args.tier1)
            tiers["tier2"]["enabled"] = bool(args.tier2)
            calibration = run_calibration_loop(
                initial=baseline, cfg=tier_cfg,
                run=lambda trial_cfg, trial_start, trial_end: run(
                    job_dir / CLIPS_NAME, view=cfg["api"]["jobs"]["view"], cfg=trial_cfg,
                    start_s=trial_start, end_s=trial_end, match_id=f"up_{aid}_tier2"),
                full_run=lambda final_cfg: run(
                    job_dir / CLIPS_NAME, view=cfg["api"]["jobs"]["view"], cfg=final_cfg,
                    start_s=start_s, end_s=end_s, match_id=f"up_{aid}_tier2_full"),
                llm_factory=_bedrock_factory(tier_cfg) if args.tier2 else None,
                trace_path=repo_path(tier_cfg["agent"]["outputs"]["trace"]),
                usage=Usage(tier_cfg, str(out / "usage.json")), px_per_m=px_per_m)
            res = calibration["result"]
            report["calibration_tiers"] = {
                key: calibration[key] for key in
                ("tier1_rule_applied", "kept", "calls", "cost_usd", "elapsed_s", "message")}
        write_outputs(res, job_dir / "match_state.json")
        ctx = MatchContext(res.match, jcfg, view=cfg["api"]["jobs"]["view"])
        cands = [{"event_id": c.id, "team": c.team, "t": float(c.t), "from": c.from_,
                  "to": c.to, "decision": "not checked (perception only)"}
                 for c in ctx.candidates]
        report["perception"] = {"timing_s": {k: round(v, 1) for k, v in res.timing.items()},
                                "perception_seconds": round(sum(res.timing.values()), 1),
                                "s_per_video_s": round(sum(res.timing.values())
                                                       / res.video_seconds, 2),
                                "detections_per_frame": round(
                                    sum(len(record.boxes) for record in res.records
                                        if record.output)
                                    / max(sum(record.output for record in res.records), 1), 3),
                                "diagnostics": res.selfcal.get("diagnostics", {}),
                                "pixels_per_metre": round(px_per_m, 4),
                                "tier1_rule_applied": bool(args.tier1 and px_per_m < float(
                                    run_cfg["perception"]["self_calibration"]["calibration_tiers"]
                                    ["tier1"]["local_scale_min_px_per_m"]))}
        print("quick diagnostics: " + json.dumps(report["perception"], separators=(",", ":")))
        print(res.timing_table())
        if args.tier2 and args.compare_demo:
            from gaffer.perception.video import VideoSource
            from gaffer.teamtrack import find_clips, load_gt

            clips = find_clips("top", cfg, ["train"])
            gts = [load_gt(clip.csv).boxes for clip in clips]
            fps = VideoSource(job_dir / CLIPS_NAME).native_fps
            offset = float(args.demo_offset_s)
            before = _score_teamtrack_upload(baseline, cfg, clips, gts, fps, offset)
            after = _score_teamtrack_upload(res, cfg, clips, gts, fps, offset)
            report["calibration_comparison"] = {"deterministic_default": before,
                                                 "agentic": after}
            print("\nTeamTrack consistency upload comparison (perception only)")
            print("variant      P      R     F1   team acc  label share  det/frame  cov H/A  White")
            for label, metrics in (("default", before), ("agentic", after)):
                cov = metrics["formation_coverage"]
                print(f"{label:10s} {metrics['precision']:.3f} {metrics['recall']:.3f} "
                      f"{metrics['f1']:.3f} {metrics['team_accuracy']:.3f} "
                      f"{metrics['team_label_share']:.3f} {metrics['detections_per_frame']:.2f} "
                      f"{cov['home']:.3f}/{cov['away']:.3f} "
                      f"{metrics['white_16_30_change_found']}")
    else:
        jobs.run_one(aid)
        done = jobs.get(aid) or {}
        if done.get("status") != "done":
            print(f"ERROR: analysis {done.get('status')}: {done.get('error')}\n"
                  f"{done.get('error_detail', '')}", file=sys.stderr)
            report["status"] = done
            (out / "upload_check.json").write_text(json.dumps(report, indent=2))
            return 2
        rows = json.loads((job_dir / "run_rows.json").read_text(encoding="utf-8"))["rows"]
        cands = [{"event_id": x["event_id"], "team": x["team"], "t": float(x["t"]),
                  "from": x["from"], "to": x["to"], "decision": x["decision"],
                  "reason": x["reason"]} for x in rows]
        report["summary"] = done.get("summary")
        report["perception"] = done.get("perception")
    report["wall_s"] = round(time.perf_counter() - t0, 1)
    report["candidates"] = cands
    names = {s: cfg["perception"]["teams"][s]["name"] for s in ("home", "away")}
    print(f"\nupload candidates ({len(cands)}), match time = video time + "
          f"{args.demo_offset_s if args.compare_demo else 0:g} s:")
    off = args.demo_offset_s if args.compare_demo else 0.0
    for c in cands:
        print(f"  {c['event_id']} {names[c['team']]:5s} {c['from']} -> {c['to']} at "
              f"{clock(c['t'] + off)}  {c['decision']}")
    if args.compare_demo:
        demo = demo_candidates(cfg)
        cmp_ = compare(demo, cands, off, float(cfg["eval"]["synthetic"]["tolerance_s"]))
        report["demo_comparison"] = cmp_
        print(f"\n{'demo candidate':42s} | upload")
        for p in cmp_["pairs"]:
            d, u = p["demo"], p["upload"]
            left = (f"{d['event_id']} {names[d['team']]} {d['from']}->{d['to']} "
                    f"{clock(d['t'])} [{d['decision']}]")
            right = ("not a candidate" if u is None else
                     f"{u['event_id']} {clock(u['t'] + off)} [{u['decision']}]"
                     + ("" if p["match"] == "exact" else
                        f" (same new shape, read as {u['from']}->{u['to']})"))
            print(f"  {left:40s} | {right}")
        for u in cmp_["upload_only"]:
            print(f"  {'(not in demo)':40s} | {u['event_id']} {names[u['team']]} {u['from']}->"
                  f"{u['to']} {clock(u['t'] + off)} [{u['decision']}]")
    (out / "upload_check.json").write_text(json.dumps(report, indent=2, default=str),
                                           encoding="utf-8")
    print(f"\nwall {report['wall_s']} s -> {out / 'upload_check.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
