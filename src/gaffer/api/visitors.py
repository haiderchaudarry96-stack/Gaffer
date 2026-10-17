"""Anonymous visitors and their own decisions on the demo alert (docs/API.md, "Alerts").

The demo match is shared by everyone who opens the site, so a coach's approve / reject on its
alert must not change what other visitors see. Each browser gets a random visitor id in a cookie
(`api.visitors.cookie`, HttpOnly, SameSite=Lax; no personal data). Demo decisions are kept in
memory per visitor, with a cap on the number of visitors (oldest forgotten first), and are lost
on a server restart: the demo then shows its alert pending again, by design. Alerts of real
uploaded analyses keep the shared append-only store (`outputs/alerts.jsonl`).
"""

from __future__ import annotations

import re
import secrets
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request

_VALID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def new_visitor_id() -> str:
    return secrets.token_urlsafe(16)


def valid_visitor_id(v: str | None) -> bool:
    return bool(v) and bool(_VALID.match(v or ""))


def visitor_id(request: Request) -> str:
    """The id the visitor middleware put on this request (cookie, or a fresh one)."""
    return getattr(request.state, "visitor_id", None) or "anonymous"


class DecisionConflict(Exception):
    """The visitor already decided this alert."""


class VisitorDecisions:
    """`visitor id -> {alert id -> decided alert}` in memory, at most `max_visitors` visitors
    (least recently active forgotten first). Thread-safe (sync routes run in a thread pool)."""

    def __init__(self, max_visitors: int) -> None:
        self.max_visitors = max(1, int(max_visitors))
        self._data: OrderedDict[str, dict[str, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._data)

    def get(self, visitor: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            d = self._data.get(visitor)
            if d is None:
                return {}
            self._data.move_to_end(visitor)
            return dict(d)

    def decide(self, visitor: str, alert: dict[str, Any], approve: bool,
               note: str | None) -> dict[str, Any]:
        """This visitor's decision on `alert` (a pending sample alert); twice -> conflict."""
        with self._lock:
            d = self._data.get(visitor)
            prev = d.get(alert["alert_id"]) if d else None
            if prev is not None:
                raise DecisionConflict(f"alert {alert['alert_id']} was already {prev['status']} "
                                       f"at {prev['decided_utc']}")
            decided = {**alert, "status": "approved" if approve else "rejected",
                       "decided_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                       "coach_note": note}
            if d is None:
                d = self._data[visitor] = {}
            d[alert["alert_id"]] = decided
            self._data.move_to_end(visitor)
            while len(self._data) > self.max_visitors:
                self._data.popitem(last=False)
            return dict(decided)

    def apply(self, visitor: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """`alerts` as this visitor sees them (their decisions win; nobody else's count)."""
        mine = self.get(visitor)
        out = []
        for a in alerts:
            m = mine.get(a["alert_id"])
            out.append(a if m is None else {**a, "status": m["status"],
                                            "decided_utc": m["decided_utc"],
                                            "coach_note": m["coach_note"]})
        return out
