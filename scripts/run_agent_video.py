"""Build step 5: the agent's video backend on the real TeamTrack drone candidates (rules arm).

No LLM, no Bedrock: the rules policy runs the same tools as the agent (quality check -> second
look on video -> decision -> evidence + pending alert for a confirmation). Per candidate it
records what OpenCV measured, how long each call took and whether the OpenCV result changed the
verdict the first pass alone would give.

    py scripts\\run_agent_video.py                  # eval2 + eval pipeline MatchStates
    py scripts\\run_agent_video.py --sets eval2     # one set
    py scripts\\run_agent_video.py --simulated-pan  # + a pan/zoom version of one window
    py scripts\\run_agent_video.py --bench          # + one 145 s re-analysis at 4 fps

Resumable: rows go to `outputs/agent_video/rows.jsonl` as each candidate finishes (finished
candidates are skipped on the next run) and re-analyses are cached on disk
(`outputs/agent_cache/video/`), so a cut-off run continues where it stopped. `--fresh` starts
the rows again (the cache is kept). Output: `outputs/agent_video/report.json` + a decision
table in the log. Seeds 110-119 are never touched here (real clips only).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from typing import Any

import cv2
import numpy as np

from gaffer.agent.alerts import AlertStore
from gaffer.agent.context import MatchContext
from gaffer.agent.loop import AgentRunner, TraceWriter
from gaffer.agent.tools import Toolbox, clock
from gaffer.agent.verify import DECISION_OF
from gaffer.agent.vision import VideoBackend, VisionError, write_png
from gaffer.config import load_config, repo_path
from gaffer.perception.video import VideoSource
from gaffer.schema import load_match_state

SETS = {"eval2": "outputs/match_state_top_eval2_4fps.json",
        "eval": "outputs/match_state_top_4fps.json"}
OUT = "outputs/agent_video"


def backend_for(path: str, cfg: dict[str, Any]) -> tuple[MatchContext, VideoBackend]:
    m = load_match_state(repo_path(path))
    return MatchContext(m, cfg, view="top"), VideoBackend.for_match_file(path, m, "top", cfg)


def row_of(set_name: str, ctx: MatchContext, o: Any) -> dict[str, Any]:
    c = ctx.candidate(o.event_id)
    q, r = o.quality or {}, o.reanalysis or {}
    vs = r.get("vs_event", {})
    first_dec = DECISION_OF[o.first_verdict]
    return {
        "set": set_name, "match": ctx.match.match_id, "event_id": c.id, "team": c.team,
        "t": c.t, "clock": clock(c.t), "detected_at_s": c.detected_at_s, "from": c.from_,
        "to": c.to, "required_span": list(ctx.required_span(c)),
        "first_pass": {"verdict": o.first_verdict, "reason": o.first_reason,
                       **ctx.evidence(c).summary()},
        "quality": {k: q.get(k) for k in ("homography_ok_share", "line_error_m_median",
                                         "camera_shift_px_per_s_max", "zoom_change_max",
                                         "camera_cut", "coverage", "problems", "opencv_ms")},
        "reanalysis": ({k: r.get(k) for k in ("window", "sample_fps", "frames", "processing_s",
                                              "cache", "coverage", "candidates_in_window")}
                       | {"vs_event": vs}) if r else None,
        "verdict": o.verdict, "decision": o.decision, "reason": o.reason,
        "decided_by": o.decided_by, "tool_calls": o.tool_calls, "tool_ms": o.tool_ms,
        "evidence_image": o.evidence_image, "alert_id": o.alert_id,
        "opencv_changed_decision": o.decision != first_dec,
        "first_pass_decision": first_dec,
    }


def run_set(set_name: str, cfg: dict[str, Any], done: set[tuple[str, str]],
            rows_path: Any) -> list[dict[str, Any]]:
    ctx, vb = backend_for(SETS[set_name], cfg)
    tb = Toolbox(ctx, AlertStore(f"{OUT}/alerts_rules.jsonl"), "outputs/evidence", video=vb)
    runner = AgentRunner(ctx, tb, arm="rules", trace=TraceWriter(f"{OUT}/trace_rules.jsonl"),
                         run_id=f"video_{set_name}")
    rows = []
    print(f"\n=== {set_name}: {ctx.match.match_id}, {len(ctx.candidates)} candidates, footage "
          f"{ctx.footage[0]:.0f}-{ctx.footage[1]:.0f} s ===", flush=True)
    for c in ctx.candidates:
        if (ctx.match.match_id, c.id) in done:
            print(f"  {c.id}: done earlier, skipped", flush=True)
            continue
        t0 = time.perf_counter()
        o = runner.run([c])[0]
        row = row_of(set_name, ctx, o) | {"wall_s": round(time.perf_counter() - t0, 1)}
        rows.append(row)
        with rows_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        print(f"  {c.id} {c.team} {c.from_}->{c.to} @{clock(c.t)}: first pass "
              f"{row['first_pass']['verdict']} -> {o.decision} ({o.verdict}) in {row['wall_s']} s"
              f" | {o.reason[:100]}", flush=True)
    return rows


# --------------------------------------------------------------------------- simulated pan


def make_simulated_pan(src_uri: str, lo: float, hi: float, out_dir: Any, fps: float = 2.0,
                       speed_px_s: float = 150.0, zoom_amp: float = 0.12) -> str:
    """A pan/zoom version of [lo, hi) of a drone clip: a crop that slides sideways at
    `speed_px_s` and zooms by +-`zoom_amp`, resized back to the native size (so the drone
    calibration applies as it would to a real moving camera). Returns a *.clips.json."""
    src = VideoSource(src_uri)
    times = [float(t) for t in np.arange(lo, hi, 1.0 / fps)]
    W, H = src.width, src.height
    travel = W - int(W * (0.75 + zoom_amp))  # fixed range: the largest crop still fits
    path = out_dir / f"simulated_pan_{lo:.0f}_{hi:.0f}.mp4"
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    if not writer.isOpened():
        raise VisionError(f"OpenCV could not open a writer for {path}")
    for t, _, _, frame in src.frames(times):
        u = t - lo
        z = 0.75 + zoom_amp * math.sin(2 * math.pi * u / 40.0)  # crop share of the frame
        cw, ch = int(W * z), int(H * z)
        x = int(abs((speed_px_s * u) % (2 * travel) - travel))  # back and forth, smooth
        y = (H - ch) // 2
        writer.write(cv2.resize(frame[y:y + ch, x:x + cw], (W, H),
                                interpolation=cv2.INTER_LINEAR))
    writer.release()
    clips = out_dir / f"simulated_pan_{lo:.0f}_{hi:.0f}.clips.json"
    clips.write_text(json.dumps({"clips": [{"path": path.name, "start_s": lo}]}),
                     encoding="utf-8")
    return str(clips.relative_to(repo_path(".")).as_posix())


def run_simulated_pan(cfg: dict[str, Any]) -> dict[str, Any]:
    """Rules arm on one eval2 candidate whose video is replaced by a simulated pan/zoom."""
    ctx, _ = backend_for(SETS["eval2"], cfg)
    c = ctx.candidates[0]
    a, b = ctx.required_span(c)
    uri = make_simulated_pan(ctx.match.source_video.uri, a, b + 1.0,
                             repo_path("outputs/agent_cache/sim"))
    sim = ctx.match.model_copy(update={"source_video": ctx.match.source_video.model_copy(
        update={"uri": uri}), "match_id": ctx.match.match_id + "_simpan"})
    sctx = MatchContext(sim, cfg, view="top")
    vb = VideoBackend(sim, "top", cfg, None)
    tb = Toolbox(sctx, AlertStore(f"{OUT}/alerts_simpan.jsonl"), "outputs/evidence", video=vb)
    runner = AgentRunner(sctx, tb, arm="rules", trace=TraceWriter(f"{OUT}/trace_simpan.jsonl"),
                         run_id="video_simpan")
    o = runner.run([sctx.candidate(c.id)])[0]
    row = row_of("simulated_pan", sctx, o) | {"video": uri}
    print(f"\n=== simulated pan/zoom of {c.id} window {a:.0f}-{b:.0f} s ({uri}) ===\n"
          f"  quality: {json.dumps(row['quality'])}\n  tools: {o.tool_calls} -> {o.decision} "
          f"({o.verdict}): {o.reason}", flush=True)
    return row


def render_check(cfg: dict[str, Any], set_name: str, event_id: str, decision: str
                 ) -> dict[str, Any]:
    """The video evidence renderer on a real 4K frame for a candidate that was NOT confirmed
    (no real candidate is), under a red banner saying so. Not an alert, not in the store; it
    uses the cached re-analysis of the rules run."""
    ctx, vb = backend_for(SETS[set_name], cfg)
    tb = Toolbox(ctx, AlertStore(f"{OUT}/alerts_render_check.jsonl"), f"{OUT}/render_check",
                 video=vb)
    c = ctx.candidate(event_id)
    st = tb.new_state(c)
    a, b = ctx.required_span(c)
    r = tb.run(st, "reanalyse_window", {"start_s": a, "end_s": b, "sample_fps": 4,
                                        "event_id": c.id, "why": "render check (cached)"})
    img, shows, frame_t = tb.evidence_image(
        c, st.data or ctx.first, note=f"RENDER CHECK ONLY: {c.id} was {decision} by the rules "
                                      "- not a confirmed change, not an alert")
    path = repo_path(f"{OUT}/render_check/{ctx.match.match_id}_{c.id}.png")
    size = write_png(path, img, int(cfg["agent"]["vision"]["evidence_max_bytes"]))
    out = {"set": set_name, "event_id": c.id, "decision": decision, "image": str(path),
           "bytes": size, "frame_t": frame_t, "shows": shows, "reanalysis_cache": r.get("cache")}
    print(f"\n=== render check {set_name} {c.id} ({decision}) -> {path} ({size} bytes), "
          f"frame {frame_t} ===", flush=True)
    return out


def run_bench(cfg: dict[str, Any]) -> dict[str, Any]:
    """One 145 s re-analysis at 4 fps (acceptance: < 4 min on the laptop), cached separately."""
    ctx, vb = backend_for(SETS["eval2"], cfg)
    lo = 1300.0
    vb.cache_dir = repo_path("outputs/agent_cache/video_bench")
    for p in vb.cache_dir.glob("*.json") if vb.cache_dir.exists() else []:
        p.unlink()  # always a fresh, uncached run
    r = vb.reanalyse(lo, lo + 145.0, 4.0)
    out = {"window": [lo, lo + 145.0], "fps": 4, "frames": len(r.match.frames),
           "processing_s": round(r.processing_s, 1), "estimate_s": round(r.estimate_s, 1),
           "s_per_s_video": round(r.processing_s / 145.0, 2),
           "timing": {k: round(v, 1) for k, v in r.timing.items()}}
    print(f"\n=== bench: 145 s at 4 fps -> {out['processing_s']} s (estimate "
          f"{out['estimate_s']} s), {out['frames']} frames; stages {out['timing']} ===",
          flush=True)
    return out


# --------------------------------------------------------------------------- report


def table(rows: list[dict[str, Any]]) -> str:
    lines = ["| set | event | team | change | onset | first pass | quality (h-ok, shift px/s, "
             "zoom, cut) | quality ms | re-analysis (window, fps, s, cache) | share new / "
             "revert s | verdict | decision | changed by OpenCV |",
             "|" + "---|" * 13]
    for x in rows:
        q, r = x["quality"], x["reanalysis"] or {}
        vs = r.get("vs_event", {})
        re_s = (f"{r['window'][0]:.0f}-{r['window'][1]:.0f}, {r['sample_fps']:g}, "
                f"{r['processing_s']}, {r['cache']}") if r else "not run"
        lines.append(
            f"| {x['set']} | {x['event_id']} | {x['team']} | {x['from']}->{x['to']} | "
            f"{x['clock']} | {x['first_pass']['verdict']} | {q.get('homography_ok_share')}, "
            f"{q.get('camera_shift_px_per_s_max')}, {q.get('zoom_change_max')}, "
            f"{q.get('camera_cut')} | {q.get('opencv_ms')} | {re_s} | "
            f"{vs.get('after_share_new')} / {vs.get('reverted_after_s')} | {x['verdict']} | "
            f"{x['decision']} | {'YES' if x['opencv_changed_decision'] else 'no'} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sets", default="eval2,eval")
    ap.add_argument("--simulated-pan", action="store_true")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--render-check", default=None, metavar="SET:EVENT",
                    help="evidence renderer on a real frame of a non-confirmed candidate")
    ap.add_argument("--fresh", action="store_true", help="start the rows again (cache kept)")
    args = ap.parse_args(argv)
    out_dir = repo_path(OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "rows.jsonl"
    if args.fresh and rows_path.exists():
        rows_path.unlink()
    rows = ([json.loads(x) for x in rows_path.read_text(encoding="utf-8").splitlines()
             if x.strip()] if rows_path.exists() else [])
    done = {(x["match"], x["event_id"]) for x in rows}
    report_path = out_dir / "report.json"
    report = (json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists()
              and not args.fresh else {})
    t0 = time.perf_counter()
    try:
        for s in filter(None, (x.strip() for x in args.sets.split(","))):
            rows += run_set(s, cfg, done, rows_path)
        if args.simulated_pan:
            report["simulated_pan"] = run_simulated_pan(cfg)
        if args.bench:
            report["bench_145s_4fps"] = run_bench(cfg)
        if args.render_check:
            set_name, eid = args.render_check.split(":")
            dec = next((x["decision"] for x in rows if x["set"] == set_name
                        and x["event_id"] == eid), "not decided")
            report["render_check"] = render_check(cfg, set_name, eid, dec)
    except VisionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report["rows"] = rows
    report["wall_s_this_invocation"] = round(time.perf_counter() - t0, 1)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n" + table(rows))
    print(f"\n-> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
