"""Daily usage caps for the public API (`api.bedrock_daily`, `api.chat`).

Per UTC day: Bedrock calls and cost for everything the API sends to Bedrock (chat and
analyses), and questions per visitor. Persisted to a small JSON file so a restart does not reset
the caps; only today's counters are kept. Visitors are stored as a salted hash, never the raw IP.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from gaffer.config import repo_path


def utc_day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class Usage:
    """Thread-safe daily counters. `clock()` returns the UTC day string (tests pass a fake)."""

    def __init__(self, cfg: dict[str, Any], path: str | None = None,
                 clock: Callable[[], str] = utc_day) -> None:
        d = cfg["api"]["bedrock_daily"]
        self.max_calls = int(d["max_calls"])
        self.max_cost = float(d["max_cost_usd"])
        self.max_questions = int(cfg["api"]["chat"]["max_questions_per_visitor_per_day"])
        self.path = repo_path(path or d["usage_file"])
        self.clock = clock
        self._lock = threading.Lock()
        self._data = self._load()

    def _blank(self) -> dict[str, Any]:
        return {"day": self.clock(), "calls": 0, "cost_usd": 0.0, "tokens_in": 0,
                "tokens_out": 0, "visitors": {}}

    def _load(self) -> dict[str, Any]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if d.get("day") == self.clock():
                return d
        except (OSError, json.JSONDecodeError):
            pass
        return self._blank()

    def _today(self) -> dict[str, Any]:
        if self._data.get("day") != self.clock():
            self._data = self._blank()
        return self._data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def visitor_key(raw: str) -> str:
        return hashlib.sha256(("gaffer-visitor:" + raw).encode()).hexdigest()[:16]

    # ---------------------------------------------------------------- bedrock (global)
    def bedrock_left(self) -> tuple[int, float]:
        """(calls, USD) left today across the whole API."""
        with self._lock:
            d = self._today()
            return max(0, self.max_calls - d["calls"]), max(0.0, self.max_cost - d["cost_usd"])

    def add_bedrock(self, calls: int, cost_usd: float, tokens_in: int = 0,
                    tokens_out: int = 0) -> None:
        with self._lock:
            d = self._today()
            d["calls"] += int(calls)
            d["cost_usd"] = round(d["cost_usd"] + float(cost_usd), 6)
            d["tokens_in"] += int(tokens_in)
            d["tokens_out"] += int(tokens_out)
            self._save()

    # ---------------------------------------------------------------- visitors
    def take_question(self, visitor: str) -> int | None:
        """Count one question; None when the visitor's daily limit is already reached, else the
        number of questions left after this one."""
        key = self.visitor_key(visitor)
        with self._lock:
            d = self._today()
            n = int(d["visitors"].get(key, 0))
            if n >= self.max_questions:
                return None
            d["visitors"][key] = n + 1
            self._save()
            return self.max_questions - n - 1

    def refund_question(self, visitor: str) -> None:
        """Give a question back (Bedrock could not be reached: the visitor got no answer)."""
        key = self.visitor_key(visitor)
        with self._lock:
            d = self._today()
            if d["visitors"].get(key, 0) > 0:
                d["visitors"][key] -= 1
                self._save()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            d = self._today()
            return {"day": d["day"], "bedrock_calls": d["calls"],
                    "bedrock_calls_cap": self.max_calls, "cost_usd": round(d["cost_usd"], 4),
                    "cost_usd_cap": self.max_cost, "visitors": len(d["visitors"])}
