"""Mocked-model tests for opt-in perception calibration; no Bedrock calls are made."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gaffer.config import load_config
from gaffer.perception.calibration_loop import run_calibration_loop


def diagnostics(*, label: float = 0.8, coverage: float = 0.7) -> dict[str, float | int]:
    """Compact scalar diagnostics representative of one perception pass."""
    return {
        "detections": 80,
        "outside_pitch_detections": 4,
        "outside_pitch_share": 0.05,
        "team_labelled_share": label,
        "team_labelled_share_home": label / 2,
        "team_labelled_share_away": label / 2,
        "static_blobs": 2,
        "static_blob_share": 0.025,
        "players_per_frame": 21.0,
        "formation_coverage_home": coverage,
        "formation_coverage_away": coverage,
        "team_gate_home": 18.0,
        "team_gate_away": 19.0,
        "tracked_frames": 40,
    }


def config(tmp_path: Path) -> dict[str, Any]:
    """Return an isolated config with calibration enabled and a trace inside the test folder."""
    cfg = copy.deepcopy(load_config())
    cfg["perception"]["self_calibration"]["agentic"]["enabled"] = True
    cfg["agent"]["outputs"]["trace"] = str(tmp_path / "agent_trace.jsonl")
    return cfg


class FakeLLM:
    """A deterministic mocked tool response that captures only the request shape."""

    model_id = "global.amazon.nova-2-lite-v1:0"
    max_attempts = 2

    def __init__(self, response: dict[str, Any] | None) -> None:
        self.response = response
        self.request: dict[str, Any] | None = None

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        self.request = {"messages": messages, **kwargs}
        tools = [] if self.response is None else [SimpleNamespace(input=self.response)]
        return SimpleNamespace(tool_uses=tools, attempts=1, usage={"input_tokens": 80,
                                                                     "output_tokens": 20},
                               model_id=self.model_id)


def run_with_choice(tmp_path: Path, choice: dict[str, Any] | None,
                    trial: dict[str, float | int], *, response_error: bool = False
                    ) -> tuple[dict[str, Any], FakeLLM, list[dict[str, Any]]]:
    """Run the loop against a fake Bedrock response and controlled OpenCV rerun."""
    cfg = config(tmp_path)
    baseline = SimpleNamespace(selfcal={"diagnostics": diagnostics()})
    candidate = SimpleNamespace(selfcal={"diagnostics": trial})
    fake = FakeLLM(choice)
    calls: list[dict[str, Any]] = []

    def factory() -> FakeLLM:
        if response_error:
            raise RuntimeError("credentials unavailable")
        return fake

    result = run_calibration_loop(
        initial=baseline, cfg=cfg,
        run=lambda trial_cfg: calls.append(trial_cfg) or candidate,
        llm_factory=factory, trace_path=tmp_path / "agent_trace.jsonl")
    return result, fake, calls


def test_valid_choice_is_kept_only_after_measured_improvement(tmp_path: Path) -> None:
    """A valid bounded choice is rerun and kept when OpenCV's diagnostic score improves."""
    choice = {"setting": "perception.self_calibration.gate.scale", "value": 1.6,
              "reason": "team_labelled_share 0.95 improved from 0.80"}
    result, fake, reruns = run_with_choice(tmp_path, choice, diagnostics(label=0.95, coverage=0.9))
    assert result["kept"] is True
    assert result["config"]["perception"]["self_calibration"]["gate"]["scale"] == 1.6
    assert len(reruns) == 1
    assert fake.request is not None
    payload = json.loads(fake.request["messages"][0]["content"][0]["text"])
    assert all(isinstance(value, (int, float)) for value in payload.values())
    assert result["message"].startswith("Gaffer re-checked the detection settings:")


def test_invalid_json_shape_falls_back_to_deterministic_config(tmp_path: Path) -> None:
    """No structured choice means no rerun and the original config remains active."""
    result, _, reruns = run_with_choice(tmp_path, None, diagnostics(label=0.99))
    assert result["kept"] is False
    assert reruns == []
    assert result["config"]["perception"]["self_calibration"]["gate"]["scale"] == 1.5
    assert "invalid" in result["message"]


def test_out_of_range_choice_falls_back(tmp_path: Path) -> None:
    """A schema-valid setting with an out-of-range value is rejected before OpenCV reruns."""
    choice = {"setting": "perception.self_calibration.gate.scale", "value": 9.0,
              "reason": "team_labelled_share 0.80"}
    result, _, reruns = run_with_choice(tmp_path, choice, diagnostics(label=0.99))
    assert result["kept"] is False
    assert reruns == []
    trace = [json.loads(row) for row in (tmp_path / "agent_trace.jsonl").read_text().splitlines()]
    assert trace[-1]["reason"] == "bedrock_or_schema_failure"


def test_unavailable_bedrock_uses_default_without_call(tmp_path: Path) -> None:
    """Client construction failure is a coach-readable deterministic fallback."""
    cfg = config(tmp_path)
    initial = SimpleNamespace(selfcal={"diagnostics": diagnostics()})
    result = run_calibration_loop(
        initial=initial, cfg=cfg, run=lambda _: pytest.fail("must not rerun"),
        llm_factory=lambda: (_ for _ in ()).throw(RuntimeError("credentials unavailable")),
        trace_path=tmp_path / "agent_trace.jsonl")
    assert result["kept"] is False
    assert result["calls"] == 0
    assert "defaults" in result["message"]


def test_measured_diagnostics_reject_nova_choice(tmp_path: Path) -> None:
    """A lower measured score rejects Nova's proposal and retains the deterministic baseline."""
    choice = {"setting": "perception.self_calibration.gate.scale", "value": 1.6,
              "reason": "team_labelled_share 0.80"}
    result, _, reruns = run_with_choice(tmp_path, choice, diagnostics(label=0.3, coverage=0.2))
    assert result["kept"] is False
    assert len(reruns) == 1
    assert result["config"]["perception"]["self_calibration"]["gate"]["scale"] == 1.5
    trace = [json.loads(row) for row in (tmp_path / "agent_trace.jsonl").read_text().splitlines()]
    assert trace[-1]["step"] == "measurement"
    assert trace[-1]["kept"] is False

