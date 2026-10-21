"""Run one bounded Bedrock posture assessment for an already-persisted verified event.

Examples (no full video reprocessing):
    py scripts/analyze_event_posture.py --record-id <record-id>
    py scripts/analyze_event_posture.py --match-id teamtrack_top_w900_1260 --event-id evt_003
    py scripts/analyze_event_posture.py --record-id <record-id> --retry
"""

from __future__ import annotations

import argparse
import json
import sys

from gaffer.agent.posture import PostureAnalyzer
from gaffer.api.event_store import EventStoreError, make_event_store
from gaffer.api.usage import Usage
from gaffer.config import load_config
from gaffer.llm.bedrock_client import BedrockClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--record-id", help="Persisted event record UUID")
    target.add_argument("--event-id", help="Event id, used with --match-id")
    parser.add_argument("--match-id", help="Required with --event-id")
    parser.add_argument("--analysis-id", help="Disambiguate repeated event ids")
    parser.add_argument("--retry", action="store_true",
                        help="Explicitly retry a previous posture attempt")
    args = parser.parse_args(argv)
    if args.event_id and not args.match_id:
        parser.error("--event-id requires --match-id")
    if args.record_id and (args.match_id or args.analysis_id):
        parser.error("--record-id cannot be combined with --match-id/--analysis-id")

    cfg = load_config()
    try:
        store = make_event_store(cfg)
        record = (store.get(args.record_id) if args.record_id else
                  store.get_by_match_event(args.match_id, args.event_id, args.analysis_id))
    except EventStoreError as exc:
        print(f"Event store error: {exc}", file=sys.stderr)
        return 2
    if record is None:
        print("No matching persisted event record was found.", file=sys.stderr)
        return 2

    analyzer = PostureAnalyzer(cfg, store, lambda: BedrockClient(cfg), Usage(cfg))
    status = analyzer.analyze(record.record_id, retry=args.retry)
    latest = store.get(record.record_id)
    result = latest.posture_result if latest else None
    print(json.dumps({"record_id": record.record_id, "event_id": record.event_id,
                      "verification_status": latest.status if latest else record.status,
                      "posture_status": latest.posture_status if latest else status,
                      "posture_result": result}, ensure_ascii=False, indent=2))
    return 0 if status not in {"event_not_found", "skipped_unverified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
