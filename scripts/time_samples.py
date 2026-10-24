# ruff: noqa: E501
"""Time each sample clip end to end through the HTTP API of a running no-Bedrock server.

    py scripts/serve_no_bedrock.py --port 8012 --out outputs/api_no_bedrock_timing
    py scripts/time_samples.py --base http://127.0.0.1:8012 --out outputs/sample_timing.json

Per sample: POST /api/analyses/sample {id} -> wait for needs_confirmation (pitch auto-detect) ->
POST /pitch {confirmed: true} -> poll until done. Wall-clock seconds for the pitch check, the
analysis (confirm -> done) and the total; the server's own px-per-metre note and the result's
size. Nothing here touches AWS (the server has no Bedrock client). The UI shows no fixed time:
only the server's measured ETA.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests


def poll(base: str, aid: str, until: set[str], timeout_s: float) -> dict:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        st = requests.get(f"{base}/api/analyses/{aid}", timeout=30).json()
        if st["status"] in until or st["status"] == "failed":
            return st
        time.sleep(1.0)
    raise TimeoutError(f"analysis {aid} did not reach {until} in {timeout_s:.0f} s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8012")
    ap.add_argument("--out", default="outputs/sample_timing.json")
    ap.add_argument("--timeout-s", type=float, default=1800.0)
    args = ap.parse_args()
    samples = requests.get(f"{args.base}/api/samples", timeout=30).json()["samples"]
    rows = []
    for s in samples:
        t0 = time.perf_counter()
        st = requests.post(f"{args.base}/api/analyses/sample", json={"id": s["id"]}, timeout=600).json()
        aid = st["id"]
        t_posted = time.perf_counter()
        st = poll(args.base, aid, {"needs_confirmation", "needs_corners", "queued", "running", "done"},
                  args.timeout_s)
        t_pitch = time.perf_counter()
        if st["status"] == "needs_confirmation":
            requests.post(f"{args.base}/api/analyses/{aid}/pitch", json={"confirmed": True}, timeout=60)
        st = poll(args.base, aid, {"done"}, args.timeout_s)
        t_done = time.perf_counter()
        row = {"id": s["id"], "file_name": s["file_name"], "bytes": s["bytes"],
               "analysis_id": aid, "status": st["status"], "error": st.get("error"),
               "video": st.get("video"),
               "pitch_check_s": round(t_pitch - t0, 1), "analysis_s": round(t_done - t_pitch, 1),
               "total_s": round(t_done - t0, 1), "post_s": round(t_posted - t0, 1)}
        if st["status"] == "done":
            res = requests.get(f"{args.base}/api/analyses/{aid}/result", timeout=60).json()
            row["resolution"] = res.get("resolution")
            row["pitch"] = {k: (st.get("pitch") or {}).get(k) for k in ("state", "confidence")}
            summ = res.get("summary") or {}
            row["candidates"] = summ.get("candidates")
            row["decisions"] = summ.get("decisions")
            row["perception"] = st.get("perception")
            row["frames"] = len(res["match_state"]["frames"])
            teams = res["timeline"]["segments"]
            row["first_shapes"] = ({"home": teams[0]["home"]["formation"], "away": teams[0]["away"]["formation"]}
                                   if teams else None)
        rows.append(row)
        print(json.dumps(row))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"base": args.base, "samples": rows}, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
