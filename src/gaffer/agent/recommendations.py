"""Deterministic, evidence-grounded role suggestions for confirmed events (N4)."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gaffer.agent.posture import build_evidence
from gaffer.api.event_store import PersistedEventRecord

Role = Literal["attacker", "midfielder", "defender"]
Objective = Literal["chase", "protect", "balanced"]
Side = Literal["home", "away"]


class CoachContext(BaseModel):
    """Explicit coach-entered context. Empty values are allowed and yield a withheld result."""

    model_config = ConfigDict(extra="forbid")

    coach_side: Side | None = None
    objective: Objective | None = None
    available_substitute_roles: list[Role] = Field(default_factory=list, max_length=3)

    @field_validator("available_substitute_roles")
    @classmethod
    def unique_roles(cls, roles: list[Role]) -> list[Role]:
        if len(roles) != len(set(roles)):
            raise ValueError("substitute roles must not contain duplicates")
        return roles


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def context_key(context: CoachContext) -> str:
    """Stable hash so replaying an identical request returns the same recommendation."""
    payload = context.model_dump(mode="json")
    payload["available_substitute_roles"] = sorted(payload["available_substitute_roles"])
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evidence_key(record: PersistedEventRecord) -> str:
    raw = json.dumps({"status": record.posture_status, "result": record.posture_result},
                     sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _valid_citations(citations: Any, record: PersistedEventRecord) -> bool:
    """Fail closed if persisted posture citations are malformed or outside verified match time."""
    if not isinstance(citations, list) or len(citations) < 2:
        return False
    boundary = getattr(record, "verification_match_time_s", None)
    if not isinstance(boundary, (int, float)):
        return False
    for citation in citations:
        if not isinstance(citation, dict):
            return False
        path, unit = citation.get("metric_path"), citation.get("unit")
        value, window = citation.get("value"), citation.get("match_time_window_s")
        if not isinstance(path, str) or not path.startswith(
                ("opencv_metrics.", "opencv_reanalysis.after.")):
            return False
        if not isinstance(unit, str) or not unit.strip():
            return False
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            return False
        if not isinstance(window, list) or len(window) != 2 \
                or any(isinstance(t, bool) or not isinstance(t, (int, float))
                       or not math.isfinite(t) for t in window):
            return False
        if window[0] < 0 or window[1] < window[0] or window[1] > boundary:
            return False
    # Re-check every cited number against the event's own stored OpenCV metrics (the same index
    # the N3 validator uses). A second-look citation has no stored metric to re-check: withhold.
    stored = {c["metric_path"]: c for c in build_evidence(record)["citable_metrics"]}
    for citation in citations:
        ref = stored.get(citation["metric_path"])
        if ref is None or float(citation["value"]) != float(ref["value"]) \
                or citation["unit"] != ref["unit"] \
                or [float(t) for t in citation["match_time_window_s"]] != [
                    float(t) for t in ref["match_time_window_s"]]:
            return False
    return True


POLICY_VERSION = "2"  # 2: shape-matchup option when posture is unclear (22 Oct)


def _lines(formation: str | None) -> tuple[int, int] | None:
    """(back line, front line) player counts of a formation name like '3-4-3'."""
    try:
        parts = [int(x) for x in str(formation).split("-")]
    except ValueError:
        return None
    return (parts[0], parts[-1]) if len(parts) >= 3 else None


def _shape_matchup(record: PersistedEventRecord, context: CoachContext
                   ) -> tuple[str, dict[str, str] | None, str, str]:
    """Role option from the verified shape change alone (no posture): the opponent's back and
    front line counts before and after. Returns (condition, action, rationale, withheld reason).
    Only two documented rules: chasing + a smaller opponent back line -> an attacker for a
    defender; protecting + a bigger opponent front line -> a defender for an attacker."""
    a, b = _lines(record.from_formation), _lines(record.to_formation)
    if a is None or b is None:
        return "", None, "", "The verified formations cannot be read as lines."
    roles = context.available_substitute_roles
    change = f"{record.from_formation} to {record.to_formation}"
    who = record.team_name or "The opponent"
    if context.objective == "chase" and b[0] < a[0]:
        if "attacker" not in roles:
            return "", None, "", "No available attacking substitute role was entered."
        return (f"If you are chasing a goal while {who} keeps {b[0]} at the back (was {a[0]}).",
                {"consider_replacing": "defender", "with_available_role": "attacker"},
                f"Gaffer verified {who}'s switch from {change}: one player fewer in their back "
                f"line. An extra attacker can stretch a back {b[0]}. This uses the verified shape "
                "only (the posture read was not conclusive); the coach decides.", "")
    if context.objective == "protect" and b[1] > a[1]:
        if "defender" not in roles:
            return "", None, "", "No available defensive substitute role was entered."
        return (f"If you are protecting a lead while {who} keeps {b[1]} up front (was {a[1]}).",
                {"consider_replacing": "attacker", "with_available_role": "defender"},
                f"Gaffer verified {who}'s switch from {change}: one more player in their front "
                f"line. An extra defender keeps a spare player against a front {b[1]}. This uses "
                "the verified shape only (the posture read was not conclusive); the coach "
                "decides.", "")
    return "", None, "", ""


def create_recommendation(record: PersistedEventRecord, context: CoachContext,
                          *, created_at_utc: str | None = None) -> dict[str, Any]:
    """Apply the small N4 policy to persisted N3 posture evidence and coach context."""
    now = created_at_utc or _now()
    coach_context_key = context_key(context)
    normalized_context = context.model_copy(update={
        "available_substitute_roles": sorted(context.available_substitute_roles)})
    evidence_key = _evidence_key(record)
    request_key = hashlib.sha256(
        f"{coach_context_key}:{evidence_key}:policy{POLICY_VERSION}".encode()).hexdigest()
    recommendation_id = uuid.uuid5(
        uuid.NAMESPACE_URL, f"gaffer:recommendation:{record.record_id}:{request_key}").hex
    posture = record.posture_result or {}
    citations = posture.get("citations", [])
    citations_valid = _valid_citations(citations, record)
    posture_name = posture.get("posture")
    evidence_strength = posture.get("evidence_strength", 0.0)
    if not isinstance(evidence_strength, (int, float)):
        evidence_strength = 0.0

    status = "withheld"
    reason = ""
    condition = ""
    action: dict[str, str] | None = None
    rationale = ""
    basis = "posture"
    posture_ok = (record.posture_status == "completed"
                  and posture_name in {"attacking", "defensive", "hybrid"}
                  and posture.get("source") == "bedrock" and citations_valid
                  and evidence_strength > 0)

    if context.coach_side is None:
        reason = "Select which team you are coaching."
    elif context.objective is None:
        reason = "Select a match objective before advice can be considered."
    elif not context.available_substitute_roles:
        reason = "Enter at least one available substitute role."
    elif record.status != "confirmed":
        reason = "The formation event is not deterministically confirmed."
    elif record.team == context.coach_side:
        reason = "This event is your team's change; this response rule covers opponent changes."
    elif record.posture_status != "completed" or posture_name not in {
            "attacking", "defensive", "hybrid"}:
        reason = "Supported tactical posture evidence is not available."
    elif posture.get("source") != "bedrock" or not citations_valid or evidence_strength <= 0:
        reason = "The posture assessment does not contain enough validated evidence."
    elif context.objective == "chase" and posture_name == "defensive":
        if "attacker" not in context.available_substitute_roles:
            reason = "No available attacking substitute role was entered."
        else:
            status = "ready"
            condition = (
                "If the opponent's defensive posture continues while you are chasing a goal, "
                "and changing your shape is appropriate.")
            action = {"consider_replacing": "defender", "with_available_role": "attacker"}
            rationale = ("The verified opponent event has a supported defensive posture. "
                         "An available attacking role could offer a more forward option; the coach "
                         "decides whether the match situation supports that change.")
    elif context.objective == "protect" and posture_name == "attacking":
        if "defender" not in context.available_substitute_roles:
            reason = "No available defensive substitute role was entered."
        else:
            status = "ready"
            condition = (
                "If the opponent's attacking posture continues while you are protecting a lead, "
                "and additional defensive cover is appropriate.")
            action = {"consider_replacing": "attacker", "with_available_role": "defender"}
            rationale = ("The verified opponent event has a supported attacking posture. "
                         "An available defensive role could add cover; the coach decides whether "
                         "the match situation supports that change.")
    elif context.objective == "balanced":
        reason = "No balanced-objective role rule is supported by the current evidence."
    else:
        reason = ("The current objective and supported posture do not match a documented "
                  "role-advice rule.")

    # No posture-based option: a confirmed opponent change can still support a documented
    # shape-matchup option (line counts only, no posture claim). Context problems, an
    # unconfirmed event or the coach's own team's change are never overridden.
    eligible = (context.coach_side is not None and context.objective is not None
                and bool(context.available_substitute_roles) and record.status == "confirmed"
                and record.team != context.coach_side)
    if status != "ready" and eligible:
        m_cond, m_action, m_why, m_reason = _shape_matchup(record, context)
        if m_action is not None:
            status, condition, action, rationale = "ready", m_cond, m_action, m_why
            basis, reason = "shape_matchup", ""
        elif m_reason and posture_ok:
            reason = m_reason
        elif not posture_ok:
            reason = (reason + " The verified shape change does not open a role option for "
                      "this objective either.") if not m_reason else f"{reason} {m_reason}"
    posture_used = status == "ready" and basis == "posture"

    return {
        "schema_version": "1.0",
        "recommendation_id": recommendation_id,
        "record_id": record.record_id,
        "event_id": record.event_id,
        "status": status,
        "context": normalized_context.model_dump(mode="json"),
        "context_key": coach_context_key,
        "evidence_key": evidence_key,
        "request_key": request_key,
        "posture_status_at_creation": record.posture_status,
        "posture_trace_id": posture.get("trace_id"),
        "condition": condition,
        "action": action,
        "rationale": rationale,
        "basis": basis if status == "ready" else None,
        "shape_evidence": {"team": record.team_name, "from": record.from_formation,
                           "to": record.to_formation,
                           "event_time_s": record.candidate_time_s}
        if status == "ready" and basis == "shape_matchup" else None,
        "citations": citations if posture_used else [],
        "posture": posture_name if posture_used else None,
        "evidence_strength": float(evidence_strength) if posture_used else 0.0,
        "confidence_note": "Evidence strength is not a calibrated probability.",
        "withheld_reason": reason or None,
        "created_at_utc": now,
    }
