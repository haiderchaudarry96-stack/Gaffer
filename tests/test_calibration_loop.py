"""Mocked-model tests for two-tier perception calibration; no Bedrock calls are made."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from gaffer.config import load_config
from gaffer.perception.calibration_loop import (
    health,
    pixels_per_metre,
    run_calibration_loop,
    tier1_config,
)


def diagnostics(*, labels: float = 0.7, duplicates: float = 0.2,
                points: float = 13.0) -> dict[str, float | int]:
    """Scalar diagnostics representative of one perception pass."""
    return {"detections": 80, "outside_pitch_detections": 4, "outside_pitch_share": 0.05,
            "team_labelled_share": labels, "team_labelled_share_home": labels / 2,
            "team_labelled_share_away": labels / 2, "static_blobs": 2,
            "static_blob_share": 0.025, "players_per_frame": 21.0,
            "formation_coverage_home": 0.7, "formation_coverage_away": 0.7,
            "team_gate_home": 18.0, "team_gate_away": 19.0, "tracked_frames": 40,
            "outfield_points_home": points, "outfield_points_away": points,
            "duplicate_detections": 16, "duplicate_share": duplicates}


def config(tmp_path: Path, *, tier1: bool = False, tier2: bool = True) -> dict[str, Any]:
    """Return isolated tier switches and trace destination."""
    cfg = copy.deepcopy(load_config())
    tiers = cfg["perception"]["self_calibration"]["calibration_tiers"]
    tiers["tier1"]["enabled"] = tier1
    tiers["tier2"]["enabled"] = tier2
    cfg["agent"]["outputs"]["trace"] = str(tmp_path / "agent_trace.jsonl")
    return cfg


class FakeLLM:
    """A deterministic mocked structured response that captures the request."""

    model_id = "global.amazon.nova-2-lite-v1:0"
    max_attempts = 2

    def __init__(self, response: Any) -> None:
        self.response = response
        self.request: dict[str, Any] | None = None

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        self.request = {"messages": messages, **kwargs}
        uses = [] if self.response is None else [SimpleNamespace(input=self.response)]
        return SimpleNamespace(tool_uses=uses, attempts=1,
                               usage={"input_tokens": 80, "output_tokens": 20},
                               model_id=self.model_id)


def test_healthy_after_tier1_skips_nova(tmp_path: Path) -> None:
    """Healthy scalar ranges stop Tier 2 before constructing the model client."""
    cfg = config(tmp_path)
    healthy = SimpleNamespace(selfcal={"diagnostics": diagnostics(labels=0.9, duplicates=0.1,
                                                                   points=10)})
    result = run_calibration_loop(initial=healthy, cfg=cfg,
                                  run=lambda *_: pytest.fail("must not rerun"),
                                  full_run=lambda _: pytest.fail("must not rerun"),
                                  llm_factory=lambda: pytest.fail("must not call Nova"),
                                  trace_path=tmp_path / "trace.jsonl")
    assert result["calls"] == 0
    steps = [json.loads(row)["step"] for row in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert "tier2_not_asked" in steps


def test_low_outfield_points_fail_minimum_health_check(tmp_path: Path) -> None:
    """A run that loses a team's players is unhealthy even when other checks pass."""
    cfg = config(tmp_path)
    ranges = cfg["perception"]["self_calibration"]["calibration_tiers"]["healthy_ranges"]
    values = diagnostics(labels=0.9, duplicates=0.1, points=10)
    values["outfield_points_home"] = 2.6
    checks = health(values, ranges)
    assert checks["outfield_points_per_team"] is False
    assert checks["duplicate_share"] is True
    assert checks["team_labelled_share"] is True


def run_case(tmp_path: Path, choice: Any,
             measured: dict[str, float | int], *, factory_error: bool = False,
             healthy_initial: bool = False) -> tuple[dict[str, Any], FakeLLM, list[Any], list[Any]]:
    """Exercise proposal flow with a fake model and a measured OpenCV response."""
    cfg = config(tmp_path)
    initial_diag = diagnostics(labels=0.9, duplicates=0.1, points=10) if healthy_initial \
        else diagnostics()
    initial = SimpleNamespace(selfcal={"diagnostics": initial_diag})
    short_baseline = SimpleNamespace(selfcal={"diagnostics": initial_diag})
    candidate = SimpleNamespace(selfcal={"diagnostics": measured})
    fake = FakeLLM(choice)
    windows: list[Any] = []
    full: list[Any] = []

    def factory() -> FakeLLM:
        if factory_error:
            raise RuntimeError("Bedrock unavailable")
        return fake

    run_count = 0

    def run_trial(trial_cfg: dict[str, Any], start: float, end: float) -> Any:
        nonlocal run_count
        windows.append((trial_cfg, start, end))
        run_count += 1
        return short_baseline if run_count == 1 else candidate

    result = run_calibration_loop(
        initial=initial, cfg=cfg,
        run=run_trial,
        full_run=lambda final_cfg: full.append(final_cfg) or candidate,
        llm_factory=factory, trace_path=tmp_path / "trace.jsonl")
    return result, fake, windows, full


def valid_choice() -> dict[str, Any]:
    """A range-valid choice whose reason cites a numeric scalar diagnostic."""
    return {"setting": "perception.self_calibration.gate.scale", "value": 1.6,
            "reason": "duplicate_share 0.2 remains above the healthy threshold"}


def test_valid_choice_kept_on_measured_short_window(tmp_path: Path) -> None:
    """OpenCV measurement, not Nova's preference, keeps a measured improvement."""
    result, fake, windows, full = run_case(tmp_path, valid_choice(),
                                           diagnostics(labels=0.9, duplicates=0.1, points=10))
    assert result["kept"] is True
    assert len(windows) == 2 and all(item[1:] == (1.0, 61.0) for item in windows)
    assert len(full) == 1
    payload = json.loads(fake.request["messages"][0]["content"][0]["text"])
    assert all(isinstance(value, (float, int)) for value in payload.values())


def test_local_scale_boolean_choice_is_allowed_and_measured(tmp_path: Path) -> None:
    """Tier 2 can propose a config-listed local_scale on/off value."""
    choice = {"setting": "perception.self_calibration.local_scale", "value": False,
              "reason": "team_labelled_share 0.7 is below the configured minimum"}
    result, fake, windows, full = run_case(
        tmp_path, choice, diagnostics(labels=0.9, duplicates=0.1, points=10))
    assert result["kept"] is True
    assert len(windows) == 2
    assert windows[-1][0]["perception"]["self_calibration"]["local_scale"] is False
    assert len(full) == 1
    assert full[0]["perception"]["self_calibration"]["local_scale"] is False
    schema = fake.request["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert schema["properties"]["value"]["anyOf"]


def test_measured_diagnostics_reject_nova_choice(tmp_path: Path) -> None:
    """A trial with no measured health improvement is rejected."""
    result, _, windows, full = run_case(tmp_path, valid_choice(), diagnostics())
    assert result["kept"] is False
    assert len(windows) == 2
    assert full == []


@pytest.mark.parametrize("choice", [None, "not json",
    {"setting": "perception.self_calibration.gate.scale", "value": 9.0,
     "reason": "duplicate_share 0.2 exceeds the threshold"},
    {"setting": "perception.self_calibration.gate.scale", "value": 1.55,
     "reason": "duplicate_share 0.2 exceeds the threshold"},
])
def test_invalid_json_out_of_range_and_off_step_fall_back(
        tmp_path: Path, choice: Any) -> None:
    """Missing structured JSON and range/increment violations never reach OpenCV."""
    result, _, windows, full = run_case(tmp_path, choice, diagnostics())
    assert result["kept"] is False
    assert len(windows) == 1 and full == []
    assert "defaults" in result["message"]


def test_bedrock_unavailable_falls_back_without_rerun(tmp_path: Path) -> None:
    """An unavailable model client leaves Tier 1 results active."""
    result, _, windows, full = run_case(tmp_path, valid_choice(), diagnostics(),
                                        factory_error=True)
    assert result["calls"] == 0 and len(windows) == 1 and full == []
    assert "unavailable" in result["message"]


@pytest.mark.parametrize(("px", "expected"), [(14.699, True), (14.7, False), (14.701, False)])
def test_tier1_px_per_m_rule_is_strictly_below_threshold(
        tmp_path: Path, px: float, expected: bool) -> None:
    """The 14.7 rule disables local scale below, not at or above, the threshold."""
    cfg = config(tmp_path, tier1=True, tier2=False)
    adjusted, applied = tier1_config(cfg, px)
    assert applied is expected
    assert adjusted["perception"]["self_calibration"]["local_scale"] is (not expected)


def test_pixels_per_metre_uses_auto_detected_corners() -> None:
    """Corner edge lengths are normalized by configured pitch dimensions."""
    corners = np.array([[0, 0], [1050, 0], [1050, 680], [0, 680]], dtype=float)
    assert pixels_per_metre(corners, 105, 68) == pytest.approx(10.0)

