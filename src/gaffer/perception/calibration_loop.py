"""Optional, measured self-calibration suggestions for OpenCV perception."""

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
    """A strictly checked numeric setting proposal from the configured model."""

    model_config = ConfigDict(extra="forbid", strict=True)
    setting: str
    value: float
    reason: str


def append_trace(path: str | Path, entry: dict[str, Any]) -> None:
    """Append one JSONL calibration step, creating its parent directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _TRACE_LOCK, target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, separators=(",", ":"), allow_nan=False) + "\n")


def _set_path(cfg: dict[str, Any], dotted: str, value: float) -> None:
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


def _get_path(cfg: dict[str, Any], dotted: str) -> float:
    """Read an existing nested numeric config key."""
    cursor: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise ValueError("setting is not an existing config path")
        cursor = cursor[part]
    return float(cursor)


def _validate_choice(raw: Any, allowed: dict[str, Any],
                     diagnostics: dict[str, float | int], step_tolerance: float,
                     min_reason_chars: int, max_reason_chars: int) -> CalibrationChoice:
    """Validate output schema, allowed setting, numeric range, and configured step."""
    choice = CalibrationChoice.model_validate(raw)
    if not min_reason_chars <= len(choice.reason) <= max_reason_chars:
        raise ValueError("reason is outside its configured length")
    rule = allowed.get(choice.setting)
    if not isinstance(rule, dict):
        raise ValueError("setting is not on the allowed list")
    lo, hi = float(rule["min"]), float(rule["max"])
    step = float(rule["step"])
    if not math.isfinite(choice.value) or not lo <= choice.value <= hi:
        raise ValueError("value is outside its configured range")
    if step <= 0 or abs((choice.value - lo) / step - round((choice.value - lo) / step)) \
            > step_tolerance:
        raise ValueError("value is not on a configured step")
    reason = choice.reason.lower()
    cites_diagnostic = any(
        name.lower() in reason and format(float(value), ".4g") in reason
        for name, value in diagnostics.items())
    if not cites_diagnostic:
        raise ValueError("reason does not cite a diagnostic name and value")
    return choice


def _score(d: dict[str, float | int], quality: dict[str, Any]) -> float:
    """Score only measured aggregate diagnostics; no model output enters this decision."""
    team = float(d["team_labelled_share"])
    coverage = (float(d["formation_coverage_home"])
                + float(d["formation_coverage_away"])) / 2
    outside = float(d["outside_pitch_share"])
    static = float(d["static_blob_share"])
    expected = float(quality["expected_players_per_frame"])
    tolerance = float(quality["players_per_frame_tolerance"])
    player_penalty = min(float(quality["player_deviation_cap"]),
                         abs(float(d["players_per_frame"]) - expected) / tolerance)
    weights = quality["score_weights"]
    return (float(weights["team_labelled_share"]) * team
            + float(weights["formation_coverage"]) * coverage
            - float(weights["outside_pitch_share"]) * outside
            - float(weights["static_blob_share"]) * static
            - float(weights["players_per_frame_deviation"]) * player_penalty)


def _tool(allowed: dict[str, Any], min_reason_chars: int,
          max_reason_chars: int) -> dict[str, Any]:
    """Build a closed tool schema whose setting names come only from config."""
    schema = {
        "type": "object",
        "properties": {
            "setting": {"type": "string", "enum": list(allowed)},
            "value": {"type": "number"},
            "reason": {"type": "string", "minLength": min_reason_chars,
                       "maxLength": max_reason_chars},
        },
        "required": ["setting", "value", "reason"],
        "additionalProperties": False,
    }
    return tool_spec("adjust_perception_setting", "Return one allowed numeric setting choice.",
                     schema)


def run_calibration_loop(*, initial: Any, cfg: dict[str, Any],
                         run: Callable[[dict[str, Any]], Any],
                         llm_factory: Callable[[], Any] | None,
                         trace_path: str | Path,
                         usage: Any = None,
                         on_message: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Try at most the configured number of OpenCV reruns and keep measured improvements only.

    The Bedrock request contains a numeric-only diagnostic object. Failures leave the initial
    result and config unchanged. `run` performs one complete configured perception window.
    """
    section = cfg["perception"]["self_calibration"]["agentic"]
    result, active_cfg = initial, copy.deepcopy(cfg)
    kept_any = False
    diagnostics = result.selfcal.get("diagnostics", {})
    quality = section["quality"]
    best_score = _score(diagnostics, quality)
    calls = 0
    cost = 0.0
    tokens_in = 0
    tokens_out = 0
    elapsed_s = 0.0
    retries = int(section["max_retries"])
    allowed = section["allowed_settings"]
    append_trace(trace_path, {"component": "perception_calibration", "step": "baseline",
                              "diagnostics": diagnostics, "score": best_score,
                              "enabled": bool(section["enabled"])})
    if not section["enabled"] or retries <= 0:
        return {"result": result, "config": active_cfg, "kept": kept_any,
                "calls": calls, "cost_usd": cost,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "elapsed_s": elapsed_s, "message": ""}

    message = ""
    initial_score = best_score

    def reset_to_default() -> None:
        """Restore deterministic settings after a Bedrock, validation, or rerun failure."""
        nonlocal result, active_cfg, best_score, kept_any
        result, active_cfg = initial, copy.deepcopy(cfg)
        best_score, kept_any = initial_score, False
        append_trace(trace_path, {"component": "perception_calibration",
                                  "step": "restore_default", "calls": calls,
                                  "cost_usd": round(cost, 8)})

    for retry in range(min(retries, int(section["max_calls_per_analysis"]))):
        if llm_factory is None:
            message = "Calibration kept the OpenCV defaults because Bedrock is not configured."
            reset_to_default()
            if on_message:
                on_message(message)
            append_trace(trace_path, {"component": "perception_calibration", "step": "fallback",
                                      "reason": "bedrock_unavailable"})
            break
        if usage is not None:
            calls_left, cost_left = usage.bedrock_left()
            if calls_left <= 0:
                message = "Calibration kept the OpenCV defaults because the Bedrock budget is used."
                reset_to_default()
                if on_message:
                    on_message(message)
                append_trace(trace_path, {"component": "perception_calibration", "step": "fallback",
                                          "reason": "daily_budget_exhausted"})
                break
        if (calls >= int(section["max_calls_per_analysis"])
                or cost >= float(section["max_cost_usd_per_analysis"])):
            message = "Calibration kept the OpenCV defaults because its Bedrock budget is used."
            reset_to_default()
            if on_message:
                on_message(message)
            append_trace(trace_path, {"component": "perception_calibration", "step": "fallback",
                                      "reason": "analysis_budget_exhausted"})
            break
        call_started = time.perf_counter()
        call_finished = False
        try:
            llm = llm_factory()
            if llm is None:
                raise RuntimeError("client_unavailable")
            prices = cfg["agent"]["llm"]["prices_per_1k"][llm.model_id]
            remaining_attempts = int(section["max_calls_per_analysis"]) - calls
            if usage is not None:
                remaining_attempts = min(remaining_attempts, calls_left)
            allowed_attempts = min(int(llm.max_attempts), remaining_attempts)
            worst_call_cost = (
                int(section["max_input_tokens"]) * float(prices[0])
                + int(section["max_tokens"]) * float(prices[1])) / 1000
            worst_total_cost = worst_call_cost * allowed_attempts
            if cost + worst_total_cost > float(section["max_cost_usd_per_analysis"]):
                raise RuntimeError("analysis_cost_budget_would_be_exceeded")
            if usage is not None and cost_left < worst_total_cost:
                message = "Calibration kept the OpenCV defaults because the remaining Bedrock " \
                          "budget is too small."
                reset_to_default()
                if on_message:
                    on_message(message)
                append_trace(trace_path, {"component": "perception_calibration",
                                          "step": "fallback",
                                          "reason": "daily_cost_budget_too_small"})
                break
            # A single request cannot retry beyond the remaining configured call budget.
            llm.max_attempts = allowed_attempts
            numeric_payload = {k: float(v) for k, v in diagnostics.items()}
            system = ("Use only the numeric diagnostics supplied by the user message. Choose one "
                      "setting from this allowed list and a value within its range and step: "
                      + json.dumps(allowed, separators=(",", ":"))
                      + ". Return exactly one adjust_perception_setting tool call. The reason "
                      "must cite diagnostic metric names and values. Do not request files, "
                      "coordinates, pixels, names, or other data.")
            reply = llm.chat([user_message(json.dumps(numeric_payload, separators=(",", ":")))],
                             system=system, tools=[_tool(allowed,
                                                        int(section["min_reason_chars"]),
                                                        int(section["max_reason_chars"]))],
                             tool_choice="adjust_perception_setting",
                             max_tokens=int(section["max_tokens"]),
                             temperature=float(section["temperature"]),
                             purpose="perception_self_calibration")
            elapsed_s += time.perf_counter() - call_started
            call_finished = True
            calls += int(reply.attempts)
            token_usage = reply.usage
            tokens_in += int(token_usage.get("input_tokens", 0))
            tokens_out += int(token_usage.get("output_tokens", 0))
            prices = cfg["agent"]["llm"]["prices_per_1k"][reply.model_id]
            call_cost = (int(token_usage.get("input_tokens", 0)) * float(prices[0])
                         + int(token_usage.get("output_tokens", 0)) * float(prices[1])) / 1000
            cost += call_cost
            if usage is not None:
                usage.add_bedrock(int(reply.attempts), call_cost,
                                  int(token_usage.get("input_tokens", 0)),
                                  int(token_usage.get("output_tokens", 0)))
            if len(reply.tool_uses) != 1:
                raise ValueError("response did not contain exactly one structured choice")
            choice = _validate_choice(reply.tool_uses[0].input, allowed, diagnostics,
                                      float(section["step_tolerance"]),
                                      int(section["min_reason_chars"]),
                                      int(section["max_reason_chars"]))
        except Exception as exc:
            if not call_finished:
                elapsed_s += time.perf_counter() - call_started
            failed_attempts = int(getattr(exc, "attempts", 0))
            if failed_attempts:
                calls += failed_attempts
                if usage is not None:
                    usage.add_bedrock(failed_attempts, 0.0)
            message = "Calibration kept the OpenCV defaults because its Bedrock suggestion " \
                      "was unavailable or invalid."
            reset_to_default()
            if on_message:
                on_message(message)
            append_trace(trace_path, {"component": "perception_calibration", "step": "fallback",
                                      "reason": "bedrock_or_schema_failure",
                                      "error_type": type(exc).__name__, "calls": calls,
                                      "cost_usd": round(cost, 8)})
            break

        trial_cfg = copy.deepcopy(active_cfg)
        try:
            if math.isclose(_get_path(active_cfg, choice.setting), choice.value,
                            abs_tol=float(section["no_change_tolerance"])):
                append_trace(trace_path, {"component": "perception_calibration",
                                          "step": "no_change",
                                          "setting": choice.setting, "value": choice.value,
                                          "retry": retry + 1})
                break
            _set_path(trial_cfg, choice.setting, float(choice.value))
        except ValueError:
            message = "Calibration kept the OpenCV defaults because its setting was invalid."
            reset_to_default()
            if on_message:
                on_message(message)
            append_trace(trace_path, {"component": "perception_calibration", "step": "fallback",
                                      "reason": "setting_path_invalid", "calls": calls})
            break
        append_trace(trace_path, {"component": "perception_calibration", "step": "proposal",
                                  "diagnostics": diagnostics, "setting": choice.setting,
                                  "value": choice.value, "reason": choice.reason,
                                  "retry": retry + 1})
        started = time.perf_counter()
        try:
            trial = run(trial_cfg)
        except Exception as exc:
            elapsed_s += time.perf_counter() - started
            message = "Calibration kept the OpenCV defaults because the re-check could not finish."
            reset_to_default()
            if on_message:
                on_message(message)
            append_trace(trace_path, {"component": "perception_calibration", "step": "fallback",
                                      "reason": "opencv_rerun_failed",
                                      "error_type": type(exc).__name__, "retry": retry + 1})
            break
        elapsed_s += time.perf_counter() - started
        trial_diagnostics = trial.selfcal.get("diagnostics", {})
        trial_score = _score(trial_diagnostics, quality)
        keep = trial_score >= best_score + float(section["min_score_gain"])
        append_trace(trace_path, {"component": "perception_calibration", "step": "measurement",
                                  "diagnostics": trial_diagnostics, "score": trial_score,
                                  "baseline_score": best_score, "kept": keep,
                                  "retry": retry + 1})
        if not keep:
            message = ("OpenCV's measured checks did not improve; the earlier measured settings "
                       "remain active." if kept_any else
                       "Calibration kept the OpenCV defaults; OpenCV's measured checks did not "
                       "improve.")
            if on_message:
                on_message(message)
            break
        active_cfg, result, diagnostics, best_score = (
            trial_cfg, trial, trial_diagnostics, trial_score)
        kept_any = True
        message = f"Gaffer re-checked the detection settings: {choice.reason}"
        if on_message:
            on_message(message)

    return {"result": result, "config": active_cfg, "kept": kept_any, "calls": calls,
            "cost_usd": round(cost, 8), "elapsed_s": round(elapsed_s, 3),
            "tokens_in": tokens_in, "tokens_out": tokens_out, "message": message}
