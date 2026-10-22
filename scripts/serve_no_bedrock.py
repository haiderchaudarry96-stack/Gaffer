"""Run the Gaffer API + built site with Amazon Bedrock switched off: no AWS call at all.

Same app as `uvicorn gaffer.api.main:app` (one process: API, analysis worker, `web/dist` at /),
except that no Bedrock client is ever made: analyses use the rules arm (decisions are the rules'
either way) with template explanations and report, and chat answers 503 "not configured".
Everything it writes goes to `--out` (analyses, alerts, usage, chat trace, the event DB
`events.sqlite3` seeded with the real demo event, the posture trace), not `outputs/`.

Used for the end-to-end browser check without AWS (`web/scripts/e2e-integrate.mjs`):

    cd web && VITE_API_URL=/ npm run build && cd ..
    python scripts/serve_no_bedrock.py --port 8000 --out outputs/api_no_bedrock

On the laptop with Bedrock, run the real app instead: `uvicorn gaffer.api.main:app`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from gaffer.api.event_store import EventStore, seed_demo_events
from gaffer.api.main import create_app
from gaffer.api.storage import LocalStorage
from gaffer.api.usage import Usage
from gaffer.config import load_config, repo_path


def build_app(out: Path, cfg: dict | None = None):
    """The app with Bedrock off and every write (event DB included) under `out`."""
    out.mkdir(parents=True, exist_ok=True)
    cfg = cfg or load_config()
    cfg["api"]["posture"]["trace_path"] = str(out / "posture_trace.jsonl")
    cfg["api"]["event_store"]["path"] = str(out / "events.sqlite3")
    events = EventStore(out / "events.sqlite3")   # never the real outputs/api/events.sqlite3
    seed_demo_events(events, cfg)
    return create_app(cfg, storage=LocalStorage(out / "api"), llm_factory=None,
                      usage=Usage(cfg, str(out / "usage.json")), event_store=events,
                      alerts_path=out / "alerts.jsonl", chat_trace=out / "chat_trace.jsonl")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--out", default="outputs/api_no_bedrock",
                    help="folder for analyses, alerts.jsonl, usage.json, chat_trace.jsonl, "
                         "events.sqlite3")
    args = ap.parse_args(argv)
    cfg = load_config()
    if not (repo_path(cfg["api"].get("web_dist", "web/dist")) / "index.html").exists():
        print("Note: web/dist is not built; only the API is served (cd web; npm run build).")
    app = build_app(Path(repo_path(args.out)), cfg)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
