"""Alert store: `outputs/alerts.jsonl`, append-only, last line per `alert_id` wins.

`propose_alert` creates a **pending** alert; the coach approves or rejects it (Phase 3: this CLI;
Phase 4: buttons in the app, same store). Every change appends the full alert again with its
new status, so the history is never rewritten and every coach decision is logged. Fields are
exactly the contract's `Alert` (docs/DATA_CONTRACT.md); `alert_id = alr_<match_id>_<event_id>`
keeps ids unique across matches without a new field.

CLI:
    py -m gaffer.agent.alerts --list
    py -m gaffer.agent.alerts --approve alr_top_eval2_evt_004 --note "seen it"
    py -m gaffer.agent.alerts --reject alr_top_eval2_evt_004
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from gaffer.config import load_config, repo_path
from gaffer.schema import Alert

#: `Alert.explanation` = the code-written verdict reason first, then (if any) the coach-facing
#: explanation, labelled by who wrote it: the model (checked against the results by
#: agent/explain.py) or the code template. The contract has one `explanation` field and stays
#: unchanged.
RULES_PREFIX = "Verified: "
AGENT_SEP = "\nExplanation (agent): "
TEMPLATE_SEP = "\nExplanation (template): "


class AlertError(ValueError):
    """An alert operation that is not allowed (unknown id, duplicate, decided twice)."""


def compose_explanation(rules_reason: str, text: str | None, source: str = "agent") -> str:
    """`Alert.explanation`: the rules reason (primary, always true), then the explanation."""
    out = RULES_PREFIX + rules_reason
    if not text:
        return out
    return out + (TEMPLATE_SEP if source == "template" else AGENT_SEP) + text


def split_explanation_source(explanation: str) -> tuple[str, str | None, str | None]:
    """(rules reason, explanation or None, "agent" | "template" | None) of a stored alert."""
    for sep, source in ((AGENT_SEP, "agent"), (TEMPLATE_SEP, "template")):
        head, found, text = explanation.partition(sep)
        if found:
            return head.removeprefix(RULES_PREFIX), text, source
    return explanation.removeprefix(RULES_PREFIX), None, None


def split_explanation(explanation: str) -> tuple[str, str | None]:
    """(rules reason, explanation or None) of a stored `Alert.explanation`."""
    rules, text, _ = split_explanation_source(explanation)
    return rules, text


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def alert_id(match_id: str, event_id: str) -> str:
    return f"alr_{match_id}_{event_id}"


class AlertStore:
    """Append-only JSONL store of contract `Alert`s."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = load_config()["agent"]["outputs"]["alerts"]
        self.path = repo_path(path)

    def all(self) -> dict[str, Alert]:
        """Latest state of every alert (last line per id wins), in creation order."""
        out: dict[str, Alert] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = Alert.model_validate_json(line)
                out[a.alert_id] = a
        return out

    def get(self, aid: str) -> Alert:
        alerts = self.all()
        if aid not in alerts:
            raise AlertError(f"unknown alert id {aid!r}")
        return alerts[aid]

    def _append(self, alert: Alert) -> Alert:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(alert.model_dump_json() + "\n")
        return alert

    def create(self, match_id: str, event_id: str, match_time_s: float, title: str,
               explanation: str, suggestion: str, evidence_image: str | None) -> Alert:
        """A new **pending** alert. A pending or decided alert with the same id is an error."""
        aid = alert_id(match_id, event_id)
        if aid in self.all():
            raise AlertError(f"alert {aid} already exists")
        return self._append(Alert(alert_id=aid, event_id=event_id, created_utc=_now(),
                                  match_time_s=round(float(match_time_s), 1), title=title,
                                  explanation=explanation, suggestion=suggestion,
                                  evidence_image=evidence_image, status="pending"))

    def decide(self, aid: str, approve: bool, note: str | None = None) -> Alert:
        """The coach's decision on a pending alert (deciding twice is an error)."""
        a = self.get(aid)
        if a.status != "pending":
            raise AlertError(f"alert {aid} was already {a.status} at {a.decided_utc}")
        return self._append(a.model_copy(update={"status": "approved" if approve else "rejected",
                                                 "decided_utc": _now(), "coach_note": note}))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Coach decisions on Gaffer alerts")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--approve", metavar="ALERT_ID")
    g.add_argument("--reject", metavar="ALERT_ID")
    ap.add_argument("--note", default=None)
    ap.add_argument("--store", default=None, help="alerts.jsonl (default: config)")
    args = ap.parse_args(argv)
    store = AlertStore(args.store)
    try:
        if args.list:
            for a in store.all().values():
                rules, text, source = split_explanation_source(a.explanation)
                print(f"{a.alert_id:40s} {a.status:9s} t={a.match_time_s:7.1f}s  {a.title}\n"
                      f"    verified: {rules}"
                      + (f"\n    explanation ({source}): {text}" if text else ""))
            return 0
        a = store.decide(args.approve or args.reject, approve=bool(args.approve), note=args.note)
    except AlertError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(a.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
