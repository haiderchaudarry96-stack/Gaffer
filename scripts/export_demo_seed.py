"""Export the real demo event record(s) from the configured event DB to the tracked seed file.

The seed (`api.teamtrack_replay.seed_file`) is what a fresh server (Docker / EC2, empty
`outputs/`) imports at startup, so the recorded replay shows the real 16:30 event and its stored
Bedrock posture instead of nothing. Only records of `seed_analysis_id` (written by
`run_agent_video.py --persist-teamtrack-events`) are exported; test fixtures never are. Coach
decisions and role advice are per deployment and are not exported.

    py scripts/export_demo_seed.py            # writes samples/w900_1260/demo_events_seed.json
"""

from __future__ import annotations

import argparse
import json
import sys

from gaffer.api.event_store import make_event_store
from gaffer.config import load_config, repo_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", help="seed path (default: api.teamtrack_replay.seed_file)")
    args = ap.parse_args(argv)
    cfg = load_config()
    replay = cfg["api"]["teamtrack_replay"]
    store = make_event_store(cfg)
    records, _ = store.list(match_id=replay["match_id"], analysis_id=replay["seed_analysis_id"])
    if not records:
        print("No real demo records in the event DB; run run_agent_video.py "
              "--persist-teamtrack-events first.", file=sys.stderr)
        return 1
    rows, traces = [], {}
    trace_path = repo_path(cfg["api"]["posture"]["trace_path"])
    trace_lines = (trace_path.read_text(encoding="utf-8").splitlines()
                   if trace_path.is_file() else [])
    for r in records:
        rows.append(r.model_copy(update={"coach_decisions": [], "recommendation": None,
                                         "recommendation_status": "not_requested"})
                    .model_dump(mode="json"))
        tid = (r.posture_result or {}).get("trace_id")
        if tid:  # provenance: the posture trace steps (no credentials or video in them)
            traces[tid] = [json.loads(line) for line in trace_lines
                           if f'"trace_id":"{tid}"' in line or f'"trace_id": "{tid}"' in line]
    out = repo_path(args.out or replay["seed_file"])
    out.write_text(json.dumps({
        "note": "Real OpenCV (TeamTrack drone, 900-1260 s) + Amazon Bedrock posture record(s) "
                "exported by scripts/export_demo_seed.py; imported once into an empty event DB.",
        "records": rows, "posture_traces": traces}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print(f"wrote {len(rows)} record(s) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
