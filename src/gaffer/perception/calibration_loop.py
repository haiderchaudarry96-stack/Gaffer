"""Default-off, measured OpenCV self-calibration tiers for upload analysis."""

from __future__ import annotations

import copy
import json
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from gaffer.llm.bedrock_client import tool_spec, user_message

_TRACE_LOCK = threading.Lock()


class CalibrationChoice(BaseModel):
    """A strictly checked scalar setting proposal from the configured model."""

    model_config = ConfigDict(extra="forbid", strict=True)
    setting: str
    value: float | bool
    reason: str


def append_trace(path: str | Path, entry: dict[str, Any]) -> None:
    """Append one JSONL calibration step, creating its parent directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _TRACE_LOCK, target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, separators=(",", ":"), allow_nan=False) + "\n")


def pixels_per_metre(corners: Any, length_m: float, width_m: float) -> float:
    """Estimate pixels/metre from a confirmed pitch's auto-detected four image corners."""
    import numpy as np

    pts = np.asarray(corners, dtype=float).reshape(4, 2)
    edges = np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)
    long_px = float((edges[0] + edges[2]) / 2)
    short_px = float((edges[1] + edges[3]) / 2)
    if short_px > long_px:
        long_px, short_px = short_px, long_px
    return float((long_px / length_m + short_px / width_m) / 2)


def tier1_config(cfg: dict[str, Any], px_per_m: float | None) -> tuple[dict[str, Any], bool]:
    """Apply Tier 1's configured local-scale rule without mutating the base config."""
    out = copy.deepcopy(cfg)
    tier = out["perception"]["self_calibration"]["calibration_tiers"]["tier1"]
    applied = bool(tier["enabled"] and px_per_m is not None
                   and px_per_m < float(tier["local_scale_min_px_per_m"]))
    if applied:
        out["perception"]["self_calibration"]["local_scale"] = False
    return out, applied


def _set_path(cfg: dict[str, Any], dotted: str, value: float | bool) -> None:
    """Set an existing nested config key without mutating the baseline config."""
    cursor: dict[str, Any] = cfg
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            raise ValueError("setting is not an existing config path")
        cursor = child
    if parts[-1] not in cursor:
        raise ValueError("setting is not an existing config path")
    cursor[parts[-1]] = value


def _get_path(cfg: dict[str, Any], dotted: str) -> float | bool:
    """Read an existing nested numeric or boolean config key."""
    cursor: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise ValueError("setting is not an existing config path")
        cursor = cursor[part]
    if isinstance(cursor, bool):
        return cursor
    return float(cursor)


def _validate_choice(raw: Any, allowed: dict[str, Any], diagnostics: dict[str, float | int],
                     section: dict[str, Any]) -> CalibrationChoice:
    """Validate schema, configured scalar choice, and diagnostic citation."""
    choice = CalibrationChoice.model_validate(raw)
    if not int(section["min_reason_chars"]) <= len(choice.reason) <= int(
            section["max_reason_chars"]):
        raise ValueError("reason is outside its configured length")
    rule = allowed.get(choice.setting)
    if not isinstance(rule, dict):
        raise ValueError("setting is not on the allowed list")
    if "values" in rule:
        if not isinstance(choice.value, bool) or choice.value not in rule["values"]:
            raise ValueError("value is outside its configured choices")
    else:
        if isinstance(choice.value, bool):
            raise ValueError("numeric setting requires a numeric value")
        lo, hi, step = float(rule["min"]), float(rule["max"]), float(rule["step"])
        if not math.isfinite(choice.value) or not lo <= choice.value <= hi:
            raise ValueError("value is outside its configured range")
        if step <= 0 or abs((choice.value - lo) / step - round((choice.value - lo) / step)) \
                > float(section["step_tolerance"]):
            raise ValueError("value is not on a configured step")
    reason = choice.reason.lower()
    cited = any(name.lower() in reason and format(float(value), ".4g") in reason
                for name, value in diagnostics.items())
    if not cited:
        raise ValueError("reason does not cite a diagnostic name and value")
    return choice


def health(diagnostics: dict[str, float | int], ranges: dict[str, Any]) -> dict[str, bool]:
    """Return configured scalar health checks; no model output enters these decisions."""
    return {
        "outfield_points_per_team": all(
            float(ranges["min_outfield_points_per_team"])
            <= float(diagnostics[f"outfield_points_{side}"])
            <= float(ranges["max_outfield_points_per_team"]) for side in ("home", "away")),
        "duplicate_share": float(diagnostics["duplicate_share"]) <= float(
            ranges["max_duplicate_share"]),
        "team_labelled_share": float(diagnostics["team_labelled_share"]) >= float(
            ranges["min_team_labelled_share"]),
    }


def _health_score(diagnostics: dict[str, float | int], ranges: dict[str, Any]) -> float:
    """Score distance to the configured healthy ranges for measured keep/reject decisions."""
    max_points = float(ranges["max_outfield_points_per_team"])
    min_points = float(ranges["min_outfield_points_per_team"])
    point_excess = sum((max(0.0, float(diagnostics[f"outfield_points_{side}"]) - max_points)
                        + max(0.0, min_points - float(diagnostics[f"outfield_points_{side}"])))
                       / max_points for side in ("home", "away"))
    duplicate_excess = max(0.0, float(diagnostics["duplicate_share"])
                           - float(ranges["max_duplicate_share"]))
    label_shortfall = max(0.0, float(ranges["min_team_labelled_share"])
                          - float(diagnostics["team_labelled_share"]))
    return point_excess + duplicate_excess + label_shortfall


def _tool(allowed: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    """Build a closed tool schema whose setting names come only from config."""
    schema = {"type": "object", "properties": {
        "setting": {"type": "string", "enum": list(allowed)},
        "value": {"anyOf": [{"type": "number"}, {"type": "boolean"}]},
        "reason": {"type": "string", "minLength": int(section["min_reason_chars"]),
                   "maxLength": int(section["max_reason_chars"])},
    }, "required": ["setting", "value", "reason"], "additionalProperties": False}
    return tool_spec("adjust_perception_setting", "Return one allowed scalar setting choice.",
                     schema)


def run_calibration_loop(*, initial: Any, cfg: dict[str, Any],
                         run: Callable[..., Any], llm_factory: Callable[[], Any] | None,
                         trace_path: str | Path, usage: Any = None,
                         on_message: Callable[[str], None] | None = None,
                         px_per_m: float | None = None,
                         full_run: Callable[[dict[str, Any]], Any] | None = None
                         ) -> dict[str, Any]:
    """Run scalar health checks, then at most two measured short-window Nova trials.

    `run(config, start_s, end_s)` is the short-window OpenCV callback; `full_run(config)` is
    called once only if a proposal improves measured health. `initial` is the existing full pass.
    """
    root = cfg["perception"]["self_calibration"]["calibration_tiers"]
    one, two = root["tier1"], root["tier2"]
    result, active_cfg = initial, copy.deepcopy(cfg)
    tier1_cfg, rule_applied = tier1_config(active_cfg, px_per_m)
    if rule_applied:
        active_cfg = tier1_cfg
    ranges = root["healthy_ranges"]
    diagnostics = result.selfcal.get("diagnostics", {})
    check = health(diagnostics, ranges)
    trace = {"component": "perception_calibration", "diagnostics": diagnostics,
             "pixels_per_metre": px_per_m, "tier1_enabled": bool(one["enabled"]),
             "tier1_rule": "local_scale_off" if rule_applied else "unchanged",
             "health": check}
    append_trace(trace_path, {**trace, "step": "tier1_measured_rule_applied_or_not"})
    append_trace(trace_path, {**trace, "step": "tier1_health",
                              "still_unhealthy": not all(check.values())})
    outcome: dict[str, Any] = {"result": result, "config": active_cfg,
                               "tier1_rule_applied": rule_applied, "kept": False,
                               "calls": 0, "cost_usd": 0.0, "elapsed_s": 0.0,
                               "tokens_in": 0, "tokens_out": 0, "message": "",
                               "nova_choices": []}
    unhealthy = not all(check.values())
    if not bool(two["enabled"]):
        append_trace(trace_path, {**trace, "step": "tier2_not_asked",
                                  "reason": "disabled", "still_unhealthy": unhealthy})
        return outcome
    if not unhealthy:
        append_trace(trace_path, {**trace, "step": "tier2_not_asked",
                                  "reason": "healthy_after_tier1", "still_unhealthy": False})
        return outcome
    append_trace(trace_path, {**trace, "step": "tier2_short_baseline_started",
                              "still_unhealthy": True})
    msg = "OpenCV checks are outside the configured ranges; Gaffer kept its measured defaults."
    start_s = float(two["window_start_s"])
    end_s = start_s + float(two["window_s"])
    try:
        started = time.perf_counter()
        short_baseline = run(active_cfg, start_s, end_s)
        outcome["elapsed_s"] += time.perf_counter() - started
    except Exception as exc:
        msg = "OpenCV could not complete the short baseline re-check; Tier 1 results were kept."
        append_trace(trace_path, {**trace, "step": "fallback",
                                  "reason": "opencv_short_baseline_failed",
                                  "error_type": type(exc).__name__})
        outcome.update(result=result, config=active_cfg, message=msg)
        if on_message:
            on_message(msg)
        return outcome
    diagnostics = short_baseline.selfcal.get("diagnostics", {})
    check = health(diagnostics, ranges)
    best_score = _health_score(diagnostics, ranges)
    append_trace(trace_path, {**trace, "step": "tier2_short_baseline_measured",
                              "diagnostics": diagnostics, "health": check,
                              "still_unhealthy": not all(check.values()),
                              "window_start_s": start_s, "window_end_s": end_s})
    if all(check.values()):
        append_trace(trace_path, {**trace, "step": "nova_not_asked",
                                  "reason": "healthy_short_window", "still_unhealthy": False})
        msg = "OpenCV checks passed on the short re-check; Gaffer kept its original results."
        outcome.update(config=active_cfg, message=msg)
        if on_message:
            on_message(msg)
        return outcome
    allowed = two["allowed_settings"]
    for index in range(int(two["max_retries"])):
        if llm_factory is None:
            msg = ("OpenCV checks remain outside range; Bedrock is unavailable, so defaults were "
                   "kept.")
            append_trace(trace_path, {**trace, "step": "nova_not_asked",
                                      "reason": "bedrock_unavailable"})
            append_trace(trace_path, {**trace, "step": "fallback", "reason": "bedrock_unavailable"})
            break
        if usage is not None:
            calls_left, cost_left = usage.bedrock_left()
            if calls_left <= 0 or cost_left <= 0:
                msg = ("OpenCV checks remain outside range; the Bedrock budget is used, so "
                       "defaults were kept.")
                append_trace(trace_path, {**trace, "step": "nova_not_asked",
                                          "reason": "daily_budget_exhausted"})
                append_trace(trace_path, {**trace, "step": "fallback",
                                          "reason": "daily_budget_exhausted"})
                break
        started = time.perf_counter()
        finished = False
        request_started = False
        try:
            llm = llm_factory()
            if llm is None:
                raise RuntimeError("client_unavailable")
            prices = cfg["agent"]["llm"]["prices_per_1k"][llm.model_id]
            max_calls = int(two["max_calls_per_analysis"])
            if outcome["calls"] >= max_calls:
                append_trace(trace_path, {**trace, "step": "nova_not_asked",
                                          "reason": "analysis_call_limit"})
                break
            attempts = min(int(llm.max_attempts), max_calls - int(outcome["calls"]))
            if usage is not None:
                attempts = min(attempts, calls_left)
            worst = (int(two["max_input_tokens"]) * float(prices[0])
                     + int(two["max_tokens"]) * float(prices[1])) / 1000 * attempts
            if (float(two["max_cost_usd_per_analysis"]) < worst + outcome["cost_usd"]
                    or (usage is not None and cost_left < worst)):
                raise RuntimeError("calibration_cost_budget_would_be_exceeded")
            llm.max_attempts = attempts
            payload = {key: float(value) for key, value in diagnostics.items()}
            system = ("Use only the scalar numeric diagnostics in the user message. Choose one "
                      "setting from this allowed list and a value within its range and step: "
                      + json.dumps(allowed, separators=(",", ":"))
                      + ". Return exactly one structured tool choice. The short reason must cite "
                      "a diagnostic name and value. Do not request or provide pixels, coordinates, "
                      "filenames, or user text.")
            append_trace(trace_path, {**trace, "step": "nova_asked",
                                      "still_unhealthy": True, "retry": index + 1})
            request_started = True
            reply = llm.chat([user_message(json.dumps(payload, separators=(",", ":")))],
                             system=system, tools=[_tool(allowed, two)],
                             tool_choice="adjust_perception_setting",
                             max_tokens=int(two["max_tokens"]),
                             temperature=float(two["temperature"]),
                             purpose="perception_tier2_calibration")
            outcome["elapsed_s"] += time.perf_counter() - started
            finished = True
            outcome["calls"] += int(reply.attempts)
            tokens = reply.usage
            outcome["tokens_in"] += int(tokens.get("input_tokens", 0))
            outcome["tokens_out"] += int(tokens.get("output_tokens", 0))
            prices = cfg["agent"]["llm"]["prices_per_1k"][reply.model_id]
            call_cost = (int(tokens.get("input_tokens", 0)) * float(prices[0])
                         + int(tokens.get("output_tokens", 0)) * float(prices[1])) / 1000
            outcome["cost_usd"] += call_cost
            if usage is not None:
                usage.add_bedrock(int(reply.attempts), call_cost,
                                  int(tokens.get("input_tokens", 0)),
                                  int(tokens.get("output_tokens", 0)))
            if len(reply.tool_uses) != 1:
                raise ValueError("response did not contain exactly one structured choice")
            choice = _validate_choice(reply.tool_uses[0].input, allowed, diagnostics, two)
        except Exception as exc:
            if not finished:
                outcome["elapsed_s"] += time.perf_counter() - started
            if not request_started:
                append_trace(trace_path, {**trace, "step": "nova_not_asked",
                                          "reason": "client_or_budget_failure",
                                          "error_type": type(exc).__name__})
            failed = int(getattr(exc, "attempts", 0))
            outcome["calls"] += failed
            if usage is not None and failed:
                usage.add_bedrock(failed, 0.0)
            msg = ("OpenCV checks remain outside range; Nova's suggestion was unavailable or "
                   "invalid, so defaults were kept.")
            append_trace(trace_path, {**trace, "step": "fallback",
                                      "reason": "bedrock_or_schema_failure",
                                      "error_type": type(exc).__name__})
            break
        trial_cfg = copy.deepcopy(active_cfg)
        current = _get_path(active_cfg, choice.setting)
        unchanged = current is choice.value if isinstance(current, bool) else (
            not isinstance(choice.value, bool)
            and math.isclose(current, choice.value,
                             abs_tol=float(two["no_change_tolerance"])))
        if unchanged:
            append_trace(trace_path, {**trace, "step": "proposal_unchanged",
                                      "setting": choice.setting, "retry": index + 1})
            break
        _set_path(trial_cfg, choice.setting, choice.value)
        append_trace(trace_path, {**trace, "step": "nova_choice",
                                  "setting": choice.setting, "value": choice.value,
                                  "reason": choice.reason, "retry": index + 1,
                                  "window_start_s": start_s, "window_end_s": end_s})
        try:
            t0 = time.perf_counter()
            trial = run(trial_cfg, start_s, end_s)
            outcome["elapsed_s"] += time.perf_counter() - t0
        except Exception as exc:
            msg = "OpenCV could not complete the short re-check; the tier 1 settings were kept."
            append_trace(trace_path, {**trace, "step": "fallback",
                                      "reason": "opencv_trial_failed",
                                      "error_type": type(exc).__name__})
            break
        measured = trial.selfcal.get("diagnostics", {})
        score = _health_score(measured, ranges)
        kept = score < best_score - float(two["min_health_improvement"])
        append_trace(trace_path, {**trace, "step": "opencv_measured_choice_kept_or_rejected",
                                  "measured_diagnostics": measured, "health_score": score,
                                  "previous_health_score": best_score, "kept": kept,
                                  "retry": index + 1})
        if not kept:
            msg = "OpenCV measured no improvement in the short re-check; tier 1 settings were kept."
            break
        diagnostics, best_score, active_cfg = measured, score, trial_cfg
        outcome["nova_choices"].append({"setting": choice.setting, "value": choice.value})
        if full_run is not None:
            try:
                t0 = time.perf_counter()
                result = full_run(active_cfg)
                outcome["elapsed_s"] += time.perf_counter() - t0
            except Exception as exc:
                msg = "OpenCV could not finish the full pass; tier 1 results were retained."
                active_cfg = tier1_cfg if rule_applied else copy.deepcopy(cfg)
                append_trace(trace_path, {**trace, "step": "fallback",
                                          "reason": "opencv_full_rerun_failed",
                                          "error_type": type(exc).__name__})
                break
        else:
            result = trial
        outcome.update(result=result, config=active_cfg, kept=True)
        msg = f"Gaffer re-checked a {int(two['window_s'])}-second window: {choice.reason}"
        if on_message:
            on_message(msg)
        break
    outcome["result"], outcome["config"], outcome["message"] = result, active_cfg, msg
    if on_message and msg:
        on_message(msg)
    return outcome
