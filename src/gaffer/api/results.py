"""Result payloads: the demo match (samples/w900_1260) and finished analyses, in the shapes the
frontend already reads (web/README.md "Backend API"; `src/data/types.ts`).

`AnalysisResult = {id, label, match_state, timeline, alerts, trace, report}` plus extras the
desk can use: `explanations`, `team_model`, `run_rows`, `report_markdown`. Evidence images are
absolute URLs served by the API. Alerts show their latest state from the shared alert store
(`outputs/alerts.jsonl`, append-only, last line per id wins), so a coach's approval shows up.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from gaffer.agent.alerts import AlertStore
from gaffer.api.storage import Storage, read_json
from gaffer.config import repo_path
from gaffer.schema import Alert


def read_jsonl(text: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def latest_alerts(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r["alert_id"]] = r
    return out


def with_store_state(alerts: dict[str, dict[str, Any]], store: AlertStore
                     ) -> dict[str, dict[str, Any]]:
    """The coach's decision from the shared store wins; creation time stays the original."""
    live = store.all()
    out = {}
    for aid, a in alerts.items():
        s = live.get(aid)
        if s is not None:
            a = {**a, "status": s.status, "decided_utc": s.decided_utc,
                 "coach_note": s.coach_note}
        out[aid] = a
    return out


def evidence_url(base_url: str, prefix: str, event_id: str) -> str:
    return f"{base_url.rstrip('/')}{prefix}/evidence/{event_id}.jpg"


# --------------------------------------------------------------------------- demo


class Demo:
    """The pre-processed demo match (`api.demo`, files copied from `samples/` unchanged)."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        d = cfg["api"]["demo"]
        self.id, self.label, self.view = d["id"], d["label"], d["view"]
        self.dir = repo_path(d["dir"])
        self.names = {k: v for k, v in d["files"].items() if k != "evidence"}
        self.evidence = list(d["files"]["evidence"])
        self.explanation_set = d["explanation_set"]
        self._lock = threading.Lock()
        self._ctx: Any = None
        self._cache: dict[str, Any] = {}

    def available(self) -> bool:
        return all((self.dir / n).exists() for n in self.names.values())

    def file_path(self, name: str) -> Path | None:
        """A sample file by its published name (whitelist: the files the frontend reads)."""
        if name in self.names.values() or name in self.evidence:
            p = self.dir / name
            return p if p.exists() else None
        return None

    def _json(self, key: str) -> Any:
        if key not in self._cache:
            self._cache[key] = json.loads((self.dir / self.names[key]).read_text("utf-8"))
        return self._cache[key]

    def _text(self, key: str) -> str:
        return (self.dir / self.names[key]).read_text("utf-8")

    def context(self) -> Any:
        """MatchContext of the demo match (tactics engine on the sample MatchState, ~2 s)."""
        with self._lock:
            if self._ctx is None:
                from gaffer.agent.context import MatchContext
                from gaffer.schema import load_match_state

                m = load_match_state(self.dir / self.names["match_state"])
                self._ctx = MatchContext(m, self.cfg, view=self.view)
            return self._ctx

    def run_rows(self) -> list[dict[str, Any]]:
        return list(self._json("run_rows").get("rows", []))

    def explanations(self) -> list[dict[str, Any]]:
        return [c for c in self._json("explanations")["candidates"]
                if c.get("set") == self.explanation_set]

    def decisions(self) -> list[dict[str, Any]]:
        """Decided events for chat: decision, code reason, checked explanation."""
        ex = {c["event_id"]: c for c in self.explanations()}
        out = []
        for r in self.run_rows():
            e = ex.get(r["event_id"], {})
            out.append({"event_id": r["event_id"], "decision": r["decision"],
                        "reason": e.get("reason_now") or r["reason"],
                        "explanation": e.get("after") or r.get("explanation"),
                        "explanation_source": e.get("source"),
                        "tool_calls": r.get("tool_calls"), "alert_id": r.get("alert_id")})
        return out

    def timeline(self, base_url: str) -> dict[str, Any]:
        """The contract TacticalTimeline (first pass) with the agent's verification filled for
        the two checked events, from the stored run rows (samples ship no timeline file)."""
        from gaffer.schema import Verification

        tl = self.context().result.timeline.model_copy(deep=True)
        rows = {r["event_id"]: r for r in self.run_rows()}
        for e in tl.events:
            r = rows.get(e.id)
            if r is None:
                continue
            e.status = r["decision"]
            img = (evidence_url(base_url, "/api/demo", e.id)
                   if r.get("evidence_image") else None)
            e.verification = Verification(decided_by=r["decided_by"], decision=r["decision"],
                                          reason=r["reason"], tool_calls=r["tool_calls"],
                                          evidence_image=img, trace_id=r["trace_id"])
        return json.loads(tl.to_json())

    def alerts(self, store: AlertStore, base_url: str) -> list[dict[str, Any]]:
        rows = latest_alerts(read_jsonl(self._text("alerts")))
        out = []
        for a in with_store_state(rows, store).values():
            if a.get("evidence_image"):
                a = {**a, "evidence_image": evidence_url(base_url, "/api/demo", a["event_id"])}
            out.append(a)
        return sorted(out, key=lambda a: a["match_time_s"])

    def sample_alert(self, aid: str) -> Alert | None:
        a = latest_alerts(read_jsonl(self._text("alerts"))).get(aid)
        return None if a is None else Alert.model_validate(a)

    def bundle(self, store: AlertStore, base_url: str) -> dict[str, Any]:
        files = {k: f"{base_url.rstrip('/')}/api/demo/files/{v}" for k, v in self.names.items()}
        files["evidence"] = [f"{base_url.rstrip('/')}/api/demo/files/{n}" for n in self.evidence]
        return {"id": self.id, "label": self.label, "kind": "demo",
                "match_state": self._json("match_state"),
                "timeline": self.timeline(base_url),
                "alerts": self.alerts(store, base_url),
                "trace": read_jsonl(self._text("trace")),
                "report": self._json("report"),
                "report_markdown": self._text("report_markdown"),
                "explanations": self.explanations(),
                "team_model": self._json("team_model"),
                "run_rows": self.run_rows(),
                "files": files}


# --------------------------------------------------------------------------- analyses


def analysis_alerts(store: AlertStore, match_id: str, aid: str, base_url: str
                    ) -> list[dict[str, Any]]:
    prefix = f"alr_{match_id}_"
    out = []
    for a in store.all().values():
        if a.alert_id.startswith(prefix):
            d = a.model_dump()
            if d.get("evidence_image"):
                d["evidence_image"] = evidence_url(base_url, f"/api/analyses/{aid}", a.event_id)
            out.append(d)
    return sorted(out, key=lambda a: a["match_time_s"])


def analysis_result(storage: Storage, aid: str, status: dict[str, Any], store: AlertStore,
                    base_url: str) -> dict[str, Any]:
    """The AnalysisResult of a finished upload."""
    match_id = status.get("match_id") or f"up_{aid}"
    tl = read_json(storage, f"{aid}/timeline.json")
    for e in tl.get("events", []):
        v = e.get("verification")
        if v and v.get("evidence_image"):
            v["evidence_image"] = evidence_url(base_url, f"/api/analyses/{aid}", e["id"])
    name = (status.get("video") or {}).get("filename", "upload")
    report = read_json(storage, f"{aid}/report.json")
    explanations = read_json(storage, f"{aid}/explanations.json")["candidates"]
    rows = read_json(storage, f"{aid}/run_rows.json")["rows"]
    for item in explanations + rows:  # local file paths -> the URL the API serves
        if item.get("evidence_image"):
            item["evidence_image"] = evidence_url(base_url, f"/api/analyses/{aid}",
                                                  item["event_id"])
    return {"id": aid, "label": f"Uploaded match · {name}", "kind": "upload",
            "match_state": read_json(storage, f"{aid}/match_state.json"),
            "timeline": tl,
            "alerts": analysis_alerts(store, match_id, aid, base_url),
            "trace": read_jsonl(storage.read_bytes(f"{aid}/trace.jsonl").decode("utf-8")),
            "report": report,
            "report_markdown": storage.read_bytes(f"{aid}/report.md").decode("utf-8"),
            "explanations": explanations,
            "team_model": read_json(storage, f"{aid}/match_state.teams.json"),
            "run_rows": rows,
            "summary": status.get("summary")}


def evidence_file(job_dir: Path, event_id: str) -> Path | None:
    """The evidence image the agent rendered for `event_id` inside this analysis's folder."""
    hits = sorted((job_dir / "evidence").glob(f"*/{event_id}.*"))
    return hits[0] if hits else None
