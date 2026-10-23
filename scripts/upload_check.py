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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--video", required=True)
    ap.add_argument("--name", default=None, help="upload file name (default: the file's name)")
    ap.add_argument("--out", required=True, help="folder for everything this run writes")
    ap.add_argument("--cfg", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--perception-only", action="store_true")
    ap.add_argument("--compare-demo", action="store_true")
    ap.add_argument("--demo-offset-s", type=float, default=900.0,
                    help="match time of the upload's first frame for --compare-demo")
    ap.add_argument("--corners", default=None,
                    help="JSON 4 points instead of confirming the auto-detected outline")
    args = ap.parse_args(argv)

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
        from gaffer.perception.pipeline import run, write_outputs

        jcfg = job_config(cfg, job_dir)
        res = run(job_dir / CLIPS_NAME, view=cfg["api"]["jobs"]["view"], cfg=jcfg,
                  match_id=f"up_{aid}")
        write_outputs(res, job_dir / "match_state.json")
        ctx = MatchContext(res.match, jcfg, view=cfg["api"]["jobs"]["view"])
        cands = [{"event_id": c.id, "team": c.team, "t": float(c.t), "from": c.from_,
                  "to": c.to, "decision": "not checked (perception only)"}
                 for c in ctx.candidates]
        report["perception"] = {"timing_s": {k: round(v, 1) for k, v in res.timing.items()},
                                "s_per_video_s": round(sum(res.timing.values())
                                                       / res.video_seconds, 2)}
        print(res.timing_table())
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
