"""Evidence-grounded Bedrock posture assessment for persisted OpenCV events.

This advisory step runs once per confirmed event. It is deliberately separate from the
deterministic event verifier and never writes verification or coach-decision fields.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gaffer.agent.loop import RateLimiter
from gaffer.api.event_store import EventStore, PersistedEventRecord, utc_now
from gaffer.api.usage import Usage
from gaffer.config import repo_path
from gaffer.llm.bedrock_client import (
    BedrockCredentialsError,
    BedrockError,
    BedrockThrottlingError,
    user_message,
)

Posture = Literal["attacking", "defensive", "hybrid", "unclear"]
POSTURE_SYSTEM = """You are assessing a football team's observed tactical posture from a small,
stored OpenCV metric snapshot. Return one JSON object only, matching the requested schema.

The primary event is already a deterministically verified formation change. Assess posture
separately as attacking, defensive, hybrid, or unclear. Never infer it from a formation name.
Use the before/after shape metrics and their match-clock windows. A directional label needs at
least two independent observed metric types that agree with the label. Use hybrid only when
observed metrics point in meaningfully mixed directions. Otherwise use unclear.

The drone pipeline does not reliably observe the ball, possession, pressing or intent. Do not
invent or claim any of them. A pressing_index is usable only if a non-null valid value is supplied.
Centroid coordinates are raw pitch metres (x/y), not attacking-direction-normalized; do not use
them to infer forward/backward movement. defensive_line_m is attacking-direction-normalized:
larger means farther forward. compactness_m is front-to-back depth; width_m is lateral spread.
These measurements describe shape, not proof of tactical intent.

Citations: the evidence lists every citable value in citable_metrics. Copy whole entries from
that list only, with metric_path, value, unit and match_time_window_s exactly as given (for example
"opencv_metrics.after.defensive_line_m"). Nothing outside citable_metrics can be cited; a formation
name is never a metric. If evidence is weak, missing, conflicting, or not safely interpretable
(see quality, coverage and each window's confidence), return unclear and say why.

The explanation is your claim: one or two short coach-readable sentences about observed shape
only, never using the words ball, possession, pressing, pressure, intent or opponent. Put caveats
about signals that are not measured in limitations, not in the explanation.

If the stored post-event window is materially incomplete and visual_reanalysis_available is true,
you may return one visual_reanalysis_request for a short window strictly after the candidate time,
using one allowed sample rate. Do not request it just to repeat existing evidence. After extra
OpenCV evidence is supplied, answer the posture question and do not request another window.

Return raw JSON (no code fence) matching:
{"posture":"attacking|defensive|hybrid|unclear","evidence_strength":0.0,
 "explanation":"short text","citations":[<entries copied from citable_metrics>],
 "limitations":["short caveat"],"visual_reanalysis_request":null}
evidence_strength is a bounded evidence-strength judgment, not a calibrated probability."""

# Signals the top-view pipeline does not measure: never allowed in the model's claim text.
UNSUPPORTED_CLAIM_RE = re.compile(r"\b(ball|possession|press(?:ing|ure)?|intent|opponent)\b",
                                  re.IGNORECASE)


class VisualReanalysisRequest(BaseModel):
    """One bounded post-event OpenCV window requested by Bedrock."""

    model_config = ConfigDict(extra="forbid")

    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    sample_fps: int = Field(ge=1, le=30)


class PostureCitation(BaseModel):
    """A citation copied verbatim from the event's compact stored metric snapshot."""

    model_config = ConfigDict(extra="forbid")

    metric_path: str = Field(min_length=1, max_length=120)
    value: float
    unit: str = Field(min_length=1, max_length=48)
    match_time_window_s: tuple[float, float]


class PostureAssessment(BaseModel):
    """Typed, versioned model output before provenance metadata is added."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    posture: Posture
    evidence_strength: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1, max_length=320)
    citations: list[PostureCitation] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    visual_reanalysis_request: VisualReanalysisRequest | None = None


class PostureTrace:
    """Append-only, compact trace that contains no credentials or raw video payloads."""

    _lock = threading.Lock()

    def __init__(self, path: str | Path) -> None:
        self.path = repo_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, trace_id: str, step: str, fields: dict[str, Any]) -> None:
        row = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "trace_id": trace_id, "step": step, **fields}
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                                allow_nan=False) + "\n")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _window(segment: Any) -> tuple[float, float] | None:
    if not isinstance(segment, dict):
        return None
    start, end = segment.get("start_s"), segment.get("end_s")
    if not (_finite_number(start) and _finite_number(end) and start >= 0 and end > start):
        return None
    return float(start), float(end)


def _unit(path: str) -> str | None:
    field = path.rsplit(".", 1)[-1]
    return {
        "defensive_line_m": "m (attacking-direction-normalized)",
        "compactness_m": "m (front-to-back depth)",
        "width_m": "m (lateral spread)",
        "confidence": "score (0-1)",
        "pressing_index": "index (0-1)",
        "x": "m (raw pitch x)",
        "y": "m (raw pitch y)",
    }.get(field)


def _valid_metric(path: str, value: Any) -> bool:
    if not _finite_number(value):
        return False
    key = path.rsplit(".", 1)[-1]
    limits = {
        "defensive_line_m": (0.0, 105.0), "compactness_m": (0.0, 105.0),
        "width_m": (0.0, 68.0), "confidence": (0.0, 1.0),
        "pressing_index": (0.0, 1.0), "x": (0.0, 105.0), "y": (0.0, 68.0),
    }
    lo, hi = limits.get(key, (0.0, 0.0))
    return lo <= float(value) <= hi


def _segment_metrics(record: PersistedEventRecord, key: str) -> dict[str, Any]:
    value = record.opencv_metrics.get(key)
    return value if isinstance(value, dict) else {}


def build_evidence(record: PersistedEventRecord) -> dict[str, Any]:
    """Create the small Bedrock payload exclusively from one persisted video event."""
    metrics = record.opencv_metrics
    quality = metrics.get("quality") if isinstance(metrics.get("quality"), dict) else {}
    coverage = metrics.get("coverage") if isinstance(metrics.get("coverage"), dict) else {}
    reanalysis = metrics.get("reanalysis") if isinstance(metrics.get("reanalysis"), dict) else {}
    compact_segments: dict[str, Any] = {}
    for name in ("before", "after"):
        source = _segment_metrics(record, name)
        segment_window = _window(source)
        metric_values: dict[str, float | None] = {}
        for key in ("defensive_line_m", "compactness_m", "width_m", "confidence",
                    "pressing_index"):
            val = source.get(key)
            metric_values[key] = float(val) if _valid_metric(f"{name}.{key}", val) else None
        centroid = source.get("centroid")
        if isinstance(centroid, dict):
            for key in ("x", "y"):
                val = centroid.get(key)
                metric_values[f"centroid.{key}"] = (
                    float(val) if _valid_metric(f"{name}.{key}", val) else None)
        compact_segments[name] = {
            "window_s": list(segment_window) if segment_window else None,
            "formation": source.get("formation") if isinstance(source.get("formation"), str)
            else None,
            "metrics": metric_values,
        }

    verification = record.verification or {}
    result = {
        "schema_version": "1.0",
        "event": {
            "record_id": record.record_id, "event_id": record.event_id,
            "match_id": record.match_id, "analysis_id": record.analysis_id,
            "event_type": record.event_type, "team": record.team,
            "team_name": record.team_name, "candidate_time_s": record.candidate_time_s,
            "formation_change": {"from": record.from_formation, "to": record.to_formation},
            "verifier": {"status": record.status,
                         "reason": verification.get("reason"),
                         "match_time_boundary_s": record.verification_match_time_s,
                         "reanalysis": {
                             key: reanalysis.get(key) for key in
                             ("window", "sample_fps", "frames", "coverage")
                             if key in reanalysis
                         }},
        },
        "shape_windows": compact_segments,
        "coverage": coverage,
        "quality": {key: quality.get(key) for key in (
            "uncertain_fraction", "mean_players_visible", "verification_window")
                    if key in quality},
        "coordinate_conventions": {
            "defensive_line_m": "attacking-direction-normalized; higher is farther forward",
            "compactness_m": "front-to-back team depth; not a direct intent label",
            "width_m": "lateral team spread",
            "centroid": "raw pitch x/y metres; not attacking-direction-normalized",
            "ball_possession_pressing": (
                "unavailable unless a valid stored metric is explicitly present"),
        },
    }
    result["citable_metrics"] = citable_metrics(result)
    return result


def citable_metrics(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value the validator accepts as a citation, in the exact form it must be copied."""
    return [{"metric_path": path, "value": value, "unit": unit,
             "match_time_window_s": list(window)}
            for path, (value, unit, window) in _citation_index(evidence).items()]


def _citation_index(evidence: dict[str, Any]) -> dict[str, tuple[float, str, tuple[float, float]]]:
    out = {}
    for side in ("before", "after", "visual_after"):
        segment = evidence["shape_windows"].get(side)
        if not isinstance(segment, dict):
            continue
        window = segment.get("window_s")
        if not isinstance(window, list) or len(window) != 2:
            continue
        for key, value in segment["metrics"].items():
            # Formation confidence is quality metadata, not an independent tactical signal.
            if key == "confidence":
                continue
            prefix = "opencv_reanalysis" if side == "visual_after" else "opencv_metrics"
            metric_side = "after" if side == "visual_after" else side
            path = f"{prefix}.{metric_side}.{key}"
            unit = _unit(path)
            if unit and _valid_metric(path, value):
                out[path] = (float(value), unit, (float(window[0]), float(window[1])))
    return out


def _citations_match(assessment: PostureAssessment, evidence: dict[str, Any]
                     ) -> tuple[bool, str, set[str]]:
    available = _citation_index(evidence)
    metric_sides: dict[str, set[str]] = {}
    seen: set[str] = set()
    for citation in assessment.citations:
        source = available.get(citation.metric_path)
        if source is None:
            return False, f"missing_or_null_metric:{citation.metric_path}", set()
        value, unit, window = source
        if (float(citation.value) != value or citation.unit != unit
                or tuple(citation.match_time_window_s) != window):
            return False, f"citation_mismatch:{citation.metric_path}", set()
        if citation.metric_path in seen:
            return False, f"duplicate_citation:{citation.metric_path}", set()
        seen.add(citation.metric_path)
        parts = citation.metric_path.split(".", 2)
        side = parts[1] if parts[0] == "opencv_metrics" else parts[1]
        if side == "after" and parts[0] == "opencv_reanalysis":
            side = "visual_after"
        metric = parts[2]
        metric_sides.setdefault(metric, set()).add(side)
    paired = {name for name, sides in metric_sides.items()
              if "before" in sides and ("after" in sides or "visual_after" in sides)}
    if assessment.posture != "unclear" and len(paired) < 2:
        return False, "directional_label_needs_two_paired_metric_types", paired
    return True, "citations_valid", paired


def _comparison_signals(evidence: dict[str, Any], threshold_m: float,
                        width_threshold_m: float) -> tuple[bool, bool, set[str]]:
    before = evidence["shape_windows"]["before"]["metrics"]
    after_block = (evidence["shape_windows"].get("visual_after")
                   or evidence["shape_windows"]["after"])
    after = after_block["metrics"]
    line_a, line_b = before.get("defensive_line_m"), after.get("defensive_line_m")
    if not (_finite_number(line_a) and _finite_number(line_b)):
        return False, False, set()
    delta_line = float(line_b) - float(line_a)
    direction = "advance" if delta_line >= threshold_m else (
        "retreat" if delta_line <= -threshold_m else "neutral")
    corroboration: set[str] = set()
    for key, limit in (("compactness_m", threshold_m), ("width_m", width_threshold_m)):
        old, new = before.get(key), after.get(key)
        if _finite_number(old) and _finite_number(new):
            delta = float(new) - float(old)
            if delta >= limit:
                corroboration.add(f"{key}:expand")
            elif delta <= -limit:
                corroboration.add(f"{key}:contract")
    return direction == "advance", direction == "retreat", corroboration


def _classification_supported(posture: Posture, evidence: dict[str, Any], paired: set[str],
                              cfg: dict[str, Any]) -> tuple[bool, str]:
    quality = evidence.get("quality", {})
    coverage = evidence.get("coverage", {})
    visual = evidence.get("visual_reanalysis")
    visual = visual if isinstance(visual, dict) else {}
    min_coverage = float(cfg.get("min_coverage", 0.5))
    if isinstance(coverage, dict):
        for key in ("coverage_before", "coverage_after", "footage_frac"):
            if key == "coverage_after" and _finite_number(visual.get("coverage")):
                continue
            value = coverage.get(key)
            if _finite_number(value) and float(value) < min_coverage:
                return False, f"weak_quality_low_{key}"
    visual_coverage = visual.get("coverage")
    if _finite_number(visual_coverage) and float(visual_coverage) < min_coverage:
        return False, "weak_quality_low_visual_reanalysis_coverage"
    uncertain = visual.get("uncertain_fraction", quality.get("uncertain_fraction"))
    if _finite_number(uncertain) and uncertain > float(cfg.get("max_uncertain_fraction", 0.5)):
        return False, "weak_quality_high_uncertainty"
    for side in ("before", "after"):
        segment = evidence["shape_windows"].get("visual_after") if side == "after" \
            else evidence["shape_windows"][side]
        segment = segment or evidence["shape_windows"][side]
        confidence = segment["metrics"].get("confidence")
        if confidence is None or confidence < float(cfg.get("min_segment_confidence", 0.45)):
            return False, "weak_quality_low_segment_confidence"
    visible = visual.get("mean_players_visible", quality.get("mean_players_visible"))
    if _finite_number(visible) and visible < float(cfg.get("min_mean_players_visible", 6.0)):
        return False, "weak_quality_low_player_visibility"
    if posture == "unclear":
        return True, "model_unclear"
    forward, backward, corroboration = _comparison_signals(
        evidence, float(cfg.get("directional_delta_min_m", 2.0)),
        float(cfg.get("width_delta_min_m", 3.0)))
    cited = {name.rsplit(".", 1)[-1] for name in paired}
    if posture == "attacking":
        expanding = {item.split(":", 1)[0] for item in corroboration
                     if item.endswith(":expand")}
        ok = forward and bool(expanding) and "defensive_line_m" in cited \
            and bool(expanding & cited)
        return ok, "attacking_shape_signals_supported" if ok else "unsupported_attacking_label"
    if posture == "defensive":
        contracting = {item.split(":", 1)[0] for item in corroboration
                       if item.endswith(":contract")}
        ok = backward and bool(contracting) and "defensive_line_m" in cited \
            and bool(contracting & cited)
        return ok, "defensive_shape_signals_supported" if ok else "unsupported_defensive_label"
    if posture == "hybrid":
        contracting = {item.split(":", 1)[0] for item in corroboration
                       if item.endswith(":contract")}
        expanding = {item.split(":", 1)[0] for item in corroboration
                     if item.endswith(":expand")}
        opposite_line_signal = ("defensive_line_m" in cited and
                                ((forward and bool(contracting & cited))
                                 or (backward and bool(expanding & cited))))
        mixed_shape_dimensions = bool(expanding & cited) and bool(contracting & cited)
        conflict = opposite_line_signal or mixed_shape_dimensions
        return conflict, "mixed_shape_signals_supported" if conflict else "unsupported_hybrid_label"
    return False, "unknown_posture"


def validate_assessment(raw_text: str, evidence: dict[str, Any], cfg: dict[str, Any],
                        stage: str = "model") -> tuple[PostureAssessment | None, str]:
    """Parse and validate a model result, downgrading unsupported directional labels.

    The banned-signal check reads the claim (the explanation) only; `limitations` may say which
    signals are not measured. `stage` prefixes that rejection reason ("model"/"reassessment")."""
    # Nova often wraps its JSON in a ```json fence; the content is still checked in full.
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw_text.strip(), flags=re.DOTALL)
    try:
        data = json.loads(fenced.group(1) if fenced else raw_text)
        assessment = PostureAssessment.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        return None, f"malformed_result:{type(exc).__name__}"
    if UNSUPPORTED_CLAIM_RE.search(assessment.explanation):
        return None, f"{stage}_made_unsupported_ball_possession_pressure_or_intent_claim"
    ok, citation_reason, paired = _citations_match(assessment, evidence)
    if not ok:
        return None, citation_reason
    supported, reason = _classification_supported(assessment.posture, evidence, paired, cfg)
    if not supported and assessment.posture == "unclear":
        # The model already declined a label and the quality checks agree: keep its answer,
        # record why the evidence is weak and cap the strength (no label is ever added).
        return assessment.model_copy(update={
            "evidence_strength": min(float(assessment.evidence_strength), 0.35),
            "limitations": list(dict.fromkeys([*assessment.limitations, reason]))[:8],
        }), "model_unclear"
    if not supported:
        return (assessment.model_copy(update={
            "posture": "unclear",
            "evidence_strength": min(float(assessment.evidence_strength), 0.35),
            "explanation": ("The stored shape metrics do not support a reliable directional "
                            "posture label."),
            "limitations": list(dict.fromkeys([*assessment.limitations, reason]))[:8],
        }), reason)
    return assessment, reason


def _proposed_posture(raw_text: str) -> str | None:
    """The label the model itself proposed (trace only), or None if it is unreadable."""
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw_text.strip(), flags=re.DOTALL)
    try:
        value = json.loads(fenced.group(1) if fenced else raw_text).get("posture")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _fallback(record: PersistedEventRecord, *, trace_id: str, model_id: str | None,
              reason: str, now: str | None = None, evidence: list[dict[str, Any]] | None = None,
              source: str = "deterministic_fallback") -> dict[str, Any]:
    return {
        "schema_version": "1.0", "posture": "unclear", "source": source,
        "analysis_time_utc": now or utc_now(), "model_id": model_id,
        "trace_id": trace_id,
        "explanation": ("A reliable tactical posture could not be assessed from the available "
                        "evidence."),
        "evidence_strength": 0.0, "citations": evidence or [], "limitations": [reason],
    }


class PostureAnalyzer:
    """Event analyzer with one optional bounded OpenCV evidence round and separate budgets."""

    def __init__(self, cfg: dict[str, Any], store: EventStore,
                 llm_factory: Any, usage: Usage | None = None,
                 trace_path: str | Path | None = None,
                 visual_reanalysis: Any | None = None) -> None:
        self.cfg = cfg
        self.settings = cfg.get("api", {}).get("posture", {})
        self.store = store
        self.llm_factory = llm_factory
        self.usage = usage
        path = trace_path or self.settings.get("trace_path", "outputs/api/posture_trace.jsonl")
        self.trace = PostureTrace(path)
        self.limiter = RateLimiter(int(self.settings.get("max_rpm", 6)))
        self.visual_reanalysis = visual_reanalysis

    def _request_is_bounded(self, record: PersistedEventRecord,
                            request: VisualReanalysisRequest) -> tuple[bool, str]:
        start, end = float(request.start_s), float(request.end_s)
        boundary = record.verification_match_time_s
        if end <= start or start < record.candidate_time_s:
            return False, "visual_reanalysis_must_be_after_candidate_time"
        if end - start > float(self.settings.get("max_reanalysis_window_s", 45.0)):
            return False, "visual_reanalysis_window_exceeds_configured_limit"
        if boundary is None or end > boundary:
            return False, "visual_reanalysis_exceeds_verified_match_time_boundary"
        allowed_fps = self.settings.get("reanalysis_fps", [5])
        if int(request.sample_fps) not in [int(rate) for rate in allowed_fps]:
            return False, "visual_reanalysis_sample_rate_not_allowed"
        # Do not spend video compute if the persisted post-event interval already has all
        # primary shape metrics and a useful window. The request is only for a real evidence gap.
        after = record.opencv_metrics.get("after")
        coverage = record.opencv_metrics.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        quality = record.opencv_metrics.get("quality")
        quality = quality if isinstance(quality, dict) else {}
        coverage_after = coverage.get("coverage_after")
        uncertain = quality.get("uncertain_fraction")
        visible = quality.get("mean_players_visible")
        quality_sufficient = (
            _finite_number(coverage_after)
            and float(coverage_after) >= float(self.settings.get("min_coverage", 0.5))
            and _finite_number(uncertain)
            and float(uncertain) <= float(self.settings.get("max_uncertain_fraction", 0.5))
            and _finite_number(visible)
            and float(visible) >= float(self.settings.get("min_mean_players_visible", 6.0)))
        if isinstance(after, dict):
            available = all(_valid_metric(f"after.{key}", after.get(key)) for key in (
                "defensive_line_m", "compactness_m", "width_m"))
            interval = _window(after)
            if (available and interval
                    and quality_sufficient
                    and interval[1] - max(interval[0], record.candidate_time_s) >= 30):
                return False, "stored_post_event_metrics_are_already_sufficient"
        return True, "bounded_visual_reanalysis_requested"

    @staticmethod
    def _visual_evidence(value: Any, request: VisualReanalysisRequest
                         ) -> tuple[dict[str, Any] | None, str]:
        if not isinstance(value, dict):
            return None, "visual_reanalysis_returned_no_metrics"
        window = value.get("window_s")
        metrics = value.get("metrics")
        if not isinstance(window, list) or len(window) != 2 \
                or not (_finite_number(window[0]) and _finite_number(window[1])) \
                or float(window[0]) < request.start_s \
                or float(window[1]) > request.end_s \
                or float(window[1]) <= float(window[0]) or not isinstance(metrics, dict):
            return None, "visual_reanalysis_returned_invalid_window_or_metrics"
        compact = {}
        for key in ("defensive_line_m", "compactness_m", "width_m", "confidence",
                    "pressing_index"):
            val = metrics.get(key)
            compact[key] = float(val) if _valid_metric(f"after.{key}", val) else None
        centroid = metrics.get("centroid")
        if isinstance(centroid, dict):
            compact["centroid.x"] = (float(centroid["x"])
                                     if _valid_metric("after.x", centroid.get("x")) else None)
            compact["centroid.y"] = (float(centroid["y"])
                                     if _valid_metric("after.y", centroid.get("y")) else None)
        if not any(compact[key] is not None for key in (
                "defensive_line_m", "compactness_m", "width_m")):
            return None, "visual_reanalysis_has_no_usable_shape_metrics"
        return ({"window_s": [float(window[0]), float(window[1])],
                 "metrics": compact,
                 "quality": {key: value.get("quality", {}).get(key)
                             for key in ("coverage", "mean_players_visible",
                                         "uncertain_fraction", "confidence")
                             if _finite_number(value.get("quality", {}).get(key))},
                 "formation": value.get("formation") if isinstance(value.get("formation"), str)
                 else None}, "visual_reanalysis_metrics_valid")

    def _request(self, client: Any, evidence_text: str, max_output: int) -> Any:
        self.limiter.wait()
        return client.chat([user_message(evidence_text)], system=POSTURE_SYSTEM,
                           max_tokens=max_output, temperature=0.0,
                           purpose="event_tactical_posture")

    def _save_fallback(self, record: PersistedEventRecord, trace_id: str, model_id: str | None,
                       reason: str, *, status: Literal["unavailable", "failed"] = "unavailable",
                       attempt_id: str | None = None, calls: int | None = None,
                       cost: float | None = None, raw_hash: str | None = None,
                       tokens: tuple[int, int] = (0, 0)) -> str:
        result = _fallback(record, trace_id=trace_id, model_id=model_id, reason=reason)
        result["usage"] = {"calls": int(calls or 0), "input_tokens": int(tokens[0]),
                            "output_tokens": int(tokens[1]), "cost_usd": round(float(cost or 0), 8)}
        self.trace.write(trace_id, "fallback", {"event_id": record.event_id,
                         "reason": reason, "source": "deterministic_fallback",
                         "status": status, "model_output_sha256": raw_hash})
        self.store.save_posture_result(record_id=record.record_id, status=status,
                                       result=result,
                                       trace_ref=self._trace_ref(trace_id),
                                       attempt_id=attempt_id, actual_calls=calls,
                                       actual_cost_usd=cost)
        return status

    def _trace_ref(self, trace_id: str) -> str:
        try:
            path = self.trace.path.resolve().relative_to(repo_path(".").resolve()).as_posix()
        except ValueError:
            path = self.trace.path.as_posix()
        return f"{path}#{trace_id}"

    def analyze(self, record_id: str, *, retry: bool = False) -> str:
        """Analyze one persisted confirmed event. Repeating without `retry` is a no-op."""
        record = self.store.get(record_id)
        if record is None:
            return "event_not_found"
        trace_id = "posture_" + uuid.uuid4().hex[:16]
        self.trace.write(trace_id, "event_retrieved", {
            "record_id": record.record_id, "event_id": record.event_id,
            "match_id": record.match_id, "verification_status": record.status,
            "posture_status": record.posture_status})
        if record.status != "confirmed":
            self.trace.write(trace_id, "skipped", {"event_id": record.event_id,
                             "reason": "deterministic_verifier_not_confirmed"})
            return "skipped_unverified"
        if (not isinstance(record.verification, dict)
                or record.verification.get("decision") != "confirmed"):
            self.trace.write(trace_id, "skipped", {"event_id": record.event_id,
                             "reason": "confirmed_record_missing_deterministic_verifier_decision"})
            return "skipped_unverified"
        if record.posture_status == "pending" and not retry:
            return "already_pending"
        if record.posture_status != "not_requested" and not retry:
            return "already_processed"
        preserve_completed = record.posture_status == "completed"

        model_id = str(self.settings.get("model_id") or self.cfg["bedrock"]["model_id"])
        try:
            evidence = build_evidence(record)
            evidence["visual_reanalysis_available"] = callable(self.visual_reanalysis)
            evidence_text = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"),
                                       allow_nan=False)
            if len(evidence_text) > int(self.settings.get("max_evidence_chars", 8000)):
                raise ValueError("bounded_event_evidence_exceeds_configured_size")
        except (TypeError, ValueError, KeyError) as exc:
            why = str(exc)[:120] or "invalid_event_evidence"
            self.trace.write(trace_id, "evidence_rejected", {"event_id": record.event_id,
                             "reason": why})
            if preserve_completed:
                return f"retry_not_started:{why}"
            return self._save_fallback(record, trace_id, model_id, why, status="failed")
        evidence_hash = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
        self.trace.write(trace_id, "evidence_supplied", {
            "event_id": record.event_id, "evidence": evidence,
            "evidence_sha256": evidence_hash, "characters": len(evidence_text)})

        if not callable(self.llm_factory):
            if preserve_completed:
                return "retry_not_started:bedrock_client_unavailable"
            return self._save_fallback(record, trace_id, model_id, "bedrock_client_unavailable")
        price_map = self.settings.get("prices_per_million", {})
        price = price_map.get(model_id) if isinstance(price_map, dict) else None
        if not isinstance(price, dict) or not _finite_number(price.get("input")) \
                or not _finite_number(price.get("output")):
            if preserve_completed:
                return "retry_not_started:model_price_unavailable"
            return self._save_fallback(record, trace_id, model_id, "model_price_unavailable")
        max_input = int(self.settings.get("max_input_tokens", 12000))
        max_output = int(self.settings.get("max_output_tokens", 500))
        max_calls = 2  # first assessment plus, only if needed, one visual-evidence reassessment
        reserved_cost = max_input * float(price["input"]) / 1_000_000 \
            + max_output * float(price["output"]) / 1_000_000
        reserved_cost *= max_calls
        if self.usage is not None:
            calls_left, cost_left = self.usage.bedrock_left()
            if calls_left < max_calls or cost_left < reserved_cost:
                if preserve_completed:
                    return "retry_not_started:global_api_bedrock_budget_exhausted"
                return self._save_fallback(record, trace_id, model_id,
                                           "global_api_bedrock_budget_exhausted")
        attempt_id = trace_id
        reserved, why = self.store.reserve_posture_attempt(
            record_id=record.record_id, attempt_id=attempt_id, model_id=model_id,
            trace_ref=self._trace_ref(trace_id),
            reserved_calls=max_calls, reserved_cost_usd=reserved_cost,
            max_calls_per_event=int(self.settings.get("max_calls_per_event", 2)),
            max_calls_per_match=int(self.settings.get("max_calls_per_match", 12)),
            max_cost_usd_per_event=float(self.settings.get("max_cost_usd_per_event", 0.02)),
            max_cost_usd_per_match=float(self.settings.get("max_cost_usd_per_match", 0.10)),
            stale_pending_after_s=int(self.settings.get("stale_pending_after_s", 900)),
            retry=retry)
        if not reserved:
            if why in {"already_processed", "already_pending", "event_not_found",
                       "event_not_confirmed"}:
                return why
            if preserve_completed:
                return f"retry_not_started:posture_budget_unavailable:{why}"
            return self._save_fallback(record, trace_id, model_id,
                                       f"posture_budget_unavailable:{why}")

        client = None
        response = None
        total_calls = 0
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        try:
            client = self.llm_factory()
            if client is None:
                raise RuntimeError("bedrock_client_unavailable")
            # The regular verifier client and its retry/budget configuration remain untouched.
            if hasattr(client, "max_attempts"):
                client.max_attempts = 1
            response = self._request(client, evidence_text, max_output)
            total_calls += max(1, int(getattr(response, "attempts", 1)))
            tokens = response.usage or {}
            call_cost = (int(tokens.get("input_tokens", 0)) * float(price["input"])
                         + int(tokens.get("output_tokens", 0)) * float(price["output"])) / 1_000_000
            total_cost += call_cost
            total_input_tokens += int(tokens.get("input_tokens", 0))
            total_output_tokens += int(tokens.get("output_tokens", 0))
            if self.usage is not None:
                self.usage.add_bedrock(max(1, int(getattr(response, "attempts", 1))), call_cost,
                                       int(tokens.get("input_tokens", 0)),
                                       int(tokens.get("output_tokens", 0)))
            if response.stop_reason != "end_turn" or response.tool_uses or not response.text:
                raise ValueError("model_returned_no_single_text_answer")
            assessment, validation = validate_assessment(response.text, evidence, self.settings)
            model_output_hash = hashlib.sha256(response.text.encode("utf-8")).hexdigest()
            visual_request = assessment.visual_reanalysis_request if assessment else None
            if visual_request is not None:
                allowed, request_reason = self._request_is_bounded(record, visual_request)
                if not allowed or not callable(self.visual_reanalysis):
                    reason = (request_reason if not allowed
                              else "visual_reanalysis_context_unavailable")
                    self.trace.write(trace_id, "opencv_reanalysis", {
                        "event_id": record.event_id, "status": "unavailable",
                        "reason": reason,
                        "requested_window_s": [visual_request.start_s, visual_request.end_s],
                        "requested_sample_fps": visual_request.sample_fps})
                    return self._save_fallback(
                        record, trace_id, model_id, reason, status="failed",
                        attempt_id=attempt_id, calls=total_calls, cost=total_cost,
                        raw_hash=model_output_hash)
                try:
                    visual_value = self.visual_reanalysis(record, visual_request)
                    visual_segment, visual_reason = self._visual_evidence(visual_value,
                                                                          visual_request)
                except Exception as exc:
                    visual_segment = None
                    visual_reason = f"visual_reanalysis_failed:{type(exc).__name__}"
                self.trace.write(trace_id, "opencv_reanalysis", {
                    "event_id": record.event_id,
                    "status": "completed" if visual_segment else "unavailable",
                    "reason": visual_reason,
                    "requested_window_s": [visual_request.start_s, visual_request.end_s],
                    "requested_sample_fps": visual_request.sample_fps,
                    "result": visual_segment})
                if visual_segment is None:
                    return self._save_fallback(
                        record, trace_id, model_id, visual_reason, status="failed",
                        attempt_id=attempt_id, calls=total_calls, cost=total_cost,
                        raw_hash=model_output_hash)
                evidence["shape_windows"]["visual_after"] = visual_segment
                evidence["visual_reanalysis"] = {
                    "window_s": visual_segment["window_s"],
                    **visual_segment["quality"],
                }
                evidence["visual_reanalysis_available"] = False
                evidence["citable_metrics"] = citable_metrics(evidence)
                evidence_text = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"),
                                           allow_nan=False)
                if len(evidence_text) > int(self.settings.get("max_evidence_chars", 8000)):
                    raise ValueError("bounded_reanalysis_evidence_exceeds_configured_size")
                self.trace.write(trace_id, "reassessment_step", {
                    "event_id": record.event_id,
                    "reason": "OpenCV supplied the requested bounded post-event metrics",
                    "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
                    "characters": len(evidence_text)})
                response = None
                response = self._request(client, evidence_text, max_output)
                total_calls += max(1, int(getattr(response, "attempts", 1)))
                tokens = response.usage or {}
                call_cost = (
                    int(tokens.get("input_tokens", 0)) * float(price["input"])
                    + int(tokens.get("output_tokens", 0)) * float(price["output"])) / 1_000_000
                total_cost += call_cost
                total_input_tokens += int(tokens.get("input_tokens", 0))
                total_output_tokens += int(tokens.get("output_tokens", 0))
                if self.usage is not None:
                    self.usage.add_bedrock(max(1, int(getattr(response, "attempts", 1))),
                                           call_cost, int(tokens.get("input_tokens", 0)),
                                           int(tokens.get("output_tokens", 0)))
                if response.stop_reason != "end_turn" or response.tool_uses or not response.text:
                    raise ValueError("reassessment_returned_no_single_text_answer")
                assessment, validation = validate_assessment(response.text, evidence,
                                                             self.settings, stage="reassessment")
                if assessment and assessment.visual_reanalysis_request is not None:
                    raise ValueError("reassessment_requested_an_additional_visual_window")
                model_output_hash = hashlib.sha256(response.text.encode("utf-8")).hexdigest()
            if assessment is not None:
                assessment = assessment.model_copy(update={
                    "limitations": list(dict.fromkeys([
                        *assessment.limitations,
                        *(["The ball and possession are not reliably observed in this "
                           "top-view footage."]
                          if "pressing_index" not in _citation_index(evidence) else []),
                    ]))[:8],
                })
            self.trace.write(trace_id, "model_decision", {
                "event_id": record.event_id, "model_id": response.model_id,
                "model_output_sha256": model_output_hash,
                "model_posture": _proposed_posture(response.text),  # before any code downgrade
                "posture": assessment.posture if assessment else None,
                "citations": ([c.model_dump(mode="json") for c in assessment.citations]
                              if assessment else []), "validation": validation,
                "tokens": {"input": total_input_tokens, "output": total_output_tokens},
                "cost_usd": round(total_cost, 8)})
            if assessment is None:
                return self._save_fallback(
                    record, trace_id, model_id, validation, status="failed",
                    attempt_id=attempt_id, calls=total_calls, cost=total_cost,
                    raw_hash=model_output_hash,
                    tokens=(total_input_tokens, total_output_tokens))
            fallback_downgrade = assessment.posture == "unclear" and validation not in {
                "model_unclear", "attacking_shape_signals_supported",
                "defensive_shape_signals_supported", "mixed_shape_signals_supported"}
            if fallback_downgrade:
                result = _fallback(record, trace_id=trace_id, model_id=response.model_id,
                                   reason=validation,
                                   evidence=[c.model_dump(mode="json")
                                             for c in assessment.citations],
                                   source="deterministic_fallback")
                result["explanation"] = assessment.explanation
                status: Literal["completed", "unavailable", "failed"] = "completed"
                result["usage"] = {"calls": total_calls,
                                   "input_tokens": total_input_tokens,
                                   "output_tokens": total_output_tokens,
                                   "cost_usd": round(total_cost, 8)}
            else:
                result = {
                    **assessment.model_dump(mode="json"), "source": "bedrock",
                    "analysis_time_utc": utc_now(), "model_id": response.model_id,
                    "trace_id": trace_id,
                    "usage": {"calls": total_calls,
                              "input_tokens": total_input_tokens,
                              "output_tokens": total_output_tokens,
                              "cost_usd": round(total_cost, 8)},
                }
                status = "completed"
            self.store.save_posture_result(
                record_id=record.record_id, status=status, result=result,
                trace_ref=self._trace_ref(trace_id), attempt_id=attempt_id,
                actual_calls=total_calls, actual_cost_usd=total_cost)
            self.trace.write(trace_id, "validated_result_saved", {
                "event_id": record.event_id, "status": status,
                "posture": result["posture"], "source": result["source"],
                "trace_ref": self._trace_ref(trace_id)})
            return status
        except Exception as exc:
            if isinstance(exc, BedrockCredentialsError):
                reason = "missing_aws_credentials"
                status = "unavailable"
            elif isinstance(exc, BedrockThrottlingError):
                reason = "bedrock_throttled"
                status = "failed"
            elif isinstance(exc, BedrockError):
                reason = f"bedrock_{exc.code.lower() or 'error'}"
                status = "failed"
            elif isinstance(exc, TimeoutError):
                reason, status = "bedrock_timeout", "failed"
            elif isinstance(exc, ValueError):
                reason, status = str(exc)[:120], "failed"
            else:
                reason, status = "bedrock_call_failed", "failed"
            # A request that fails before returning usage is conservatively charged at its
            # reserved single-call ceiling. Previously completed requests are already charged.
            if client is not None and response is not None and total_calls == 0:
                total_calls = max(1, int(getattr(response, "attempts", 1)))
            elif client is not None and (response is None or total_calls == 0):
                total_calls += 1
                total_cost += reserved_cost / max_calls
                if self.usage is not None:
                    self.usage.add_bedrock(1, reserved_cost / max_calls)
            # Keep the rejected answer's hash and tokens so a guard rejection can be audited.
            raw_hash = (hashlib.sha256(response.text.encode("utf-8")).hexdigest()
                        if response is not None and response.text else None)
            return self._save_fallback(
                record, trace_id, model_id, reason, status=status, attempt_id=attempt_id,
                calls=total_calls, cost=total_cost, raw_hash=raw_hash,
                tokens=(total_input_tokens, total_output_tokens))

