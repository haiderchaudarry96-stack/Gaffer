"""Bedrock client tests. The LLM is always mocked (botocore Stubber): no network, no credits."""

from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import NoCredentialsError
from botocore.stub import Stubber

from gaffer.config import load_config
from gaffer.llm.bedrock_client import (
    BedrockCallError,
    BedrockClient,
    BedrockCredentialsError,
    BedrockModelAccessError,
    BedrockThrottlingError,
    tool_result_message,
    tool_spec,
    user_message,
)

TOOL = tool_spec("count_visible_players", "Count players.",
                 {"type": "object", "properties": {"team": {"type": "string"}},
                  "required": ["team"]})


def _response(content: list[dict], stop: str = "end_turn") -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
        "metrics": {"latencyMs": 42},
    }


@pytest.fixture
def setup(tmp_path: Path):
    """A BedrockClient wired to a stubbed bedrock-runtime client and a temp log file."""
    cfg = load_config()
    raw = boto3.client("bedrock-runtime", region_name="ap-southeast-2",
                       aws_access_key_id="testing", aws_secret_access_key="testing",
                       config=Config(retries={"total_max_attempts": 1}))
    stub = Stubber(raw)
    sleeps: list[float] = []
    client = BedrockClient(cfg, client=raw, log_path=tmp_path / "llm.jsonl",
                           sleep=sleeps.append)
    with stub:
        yield client, stub, sleeps, tmp_path / "llm.jsonl"


def _log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_plain_chat_parses_text_usage_and_logs(setup):
    client, stub, _, log = setup
    stub.add_response("converse", _response([{"text": "Hello coach."}]), {
        "modelId": client.model_id,
        "messages": [user_message("hi")],
        "inferenceConfig": {"maxTokens": client.max_tokens, "temperature": client.temperature},
    })
    res = client.chat([user_message("hi")], purpose="test")
    assert res.text == "Hello coach."
    assert res.usage == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert not res.wants_tools
    rec = _log(log)[0]
    assert rec["ok"] and rec["model_id"] == client.model_id and rec["total_tokens"] == 18
    assert rec["purpose"] == "test" and "latency_ms" in rec
    assert "hi" not in json.dumps(rec)  # prompt text is never logged


def test_tool_calling_round_trip(setup):
    client, stub, _, log = setup
    stub.add_response("converse", _response(
        [{"toolUse": {"toolUseId": "tu_1", "name": "count_visible_players",
                      "input": {"team": "home"}}}], stop="tool_use"))
    stub.add_response("converse", _response([{"text": "9 home players are visible."}]))

    msgs = [user_message("how many?")]
    first = client.chat(msgs, tools=[TOOL], system="sys", tool_choice="any")
    assert first.wants_tools
    assert first.tool_uses[0].name == "count_visible_players"
    assert first.tool_uses[0].input == {"team": "home"}

    msgs += [first.message, tool_result_message([("tu_1", {"players_visible": 9})])]
    final = client.chat(msgs, tools=[TOOL])
    assert final.text.startswith("9 home")
    assert [r["tool_calls"] for r in _log(log)] == [["count_visible_players"], []]


def test_request_includes_tool_config_and_system(setup):
    client, stub, _, _ = setup
    stub.add_response("converse", _response([{"text": "ok"}]), {
        "modelId": "apac.amazon.nova-micro-v1:0",
        "messages": [user_message("x")],
        "system": [{"text": "be brief"}],
        "inferenceConfig": {"maxTokens": 50, "temperature": 0.0},
        "toolConfig": {"tools": [TOOL], "toolChoice": {"tool": {"name": "count_visible_players"}}},
    })
    client.chat([user_message("x")], system="be brief", tools=[TOOL],
                tool_choice="count_visible_players", model_id="apac.amazon.nova-micro-v1:0",
                max_tokens=50, temperature=0.0)


def test_transient_throttling_is_retried_with_backoff(setup):
    client, stub, sleeps, log = setup
    for _ in range(2):
        stub.add_client_error("converse", service_error_code="ThrottlingException",
                              service_message="Rate exceeded", http_status_code=429)
    stub.add_response("converse", _response([{"text": "finally"}]))
    res = client.chat([user_message("x")])
    assert res.text == "finally" and res.attempts == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]  # exponential
    assert _log(log)[0]["attempts"] == 3


def test_retries_give_up_after_max_attempts(setup):
    client, stub, sleeps, log = setup
    for _ in range(client.max_attempts):
        stub.add_client_error("converse", service_error_code="ThrottlingException",
                              service_message="Rate exceeded", http_status_code=429)
    with pytest.raises(BedrockThrottlingError) as ei:
        client.chat([user_message("x")])
    assert not ei.value.quota_exhausted
    assert len(sleeps) == client.max_attempts - 1
    rec = _log(log)[0]
    assert not rec["ok"] and rec["error_code"] == "ThrottlingException"


def test_daily_quota_throttling_fails_fast_with_clear_message(setup):
    client, stub, sleeps, _ = setup
    stub.add_client_error("converse", service_error_code="ThrottlingException",
                          service_message="Too many tokens per day, please wait before "
                                          "trying again.", http_status_code=429)
    with pytest.raises(BedrockThrottlingError) as ei:
        client.chat([user_message("x")])
    assert ei.value.quota_exhausted
    assert sleeps == []  # no pointless retries
    assert "quota" in str(ei.value).lower()


def test_access_denied_maps_to_model_access_error(setup):
    client, stub, _, _ = setup
    stub.add_client_error("converse", service_error_code="AccessDeniedException",
                          service_message="You don't have access to the model.",
                          http_status_code=403)
    with pytest.raises(BedrockModelAccessError) as ei:
        client.chat([user_message("x")])
    assert "Model access" in str(ei.value)


def test_invalid_model_id_maps_to_model_access_error(setup):
    client, stub, _, _ = setup
    stub.add_client_error("converse", service_error_code="ValidationException",
                          service_message="The provided model identifier is invalid.",
                          http_status_code=400)
    with pytest.raises(BedrockModelAccessError) as ei:
        client.chat([user_message("x")])
    assert "list-inference-profiles" in str(ei.value)


def test_bad_credentials_map_to_credentials_error(setup):
    client, stub, _, _ = setup
    stub.add_client_error("converse", service_error_code="UnrecognizedClientException",
                          service_message="The security token included in the request is "
                                          "invalid.", http_status_code=403)
    with pytest.raises(BedrockCredentialsError):
        client.chat([user_message("x")])


def test_other_validation_error_is_not_retried(setup):
    client, stub, sleeps, _ = setup
    stub.add_client_error("converse", service_error_code="ValidationException",
                          service_message="messages: must not be empty", http_status_code=400)
    with pytest.raises(BedrockCallError):
        client.chat([user_message("x")])
    assert sleeps == []


class _NoCredsClient:
    def converse(self, **_):
        raise NoCredentialsError()


def test_missing_credentials_gives_clear_error(tmp_path: Path):
    client = BedrockClient(load_config(), client=_NoCredsClient(),
                           log_path=tmp_path / "l.jsonl", sleep=lambda _: None)
    with pytest.raises(BedrockCredentialsError) as ei:
        client.chat([user_message("x")])
    assert "aws configure" in str(ei.value)


def test_missing_profile_gives_clear_error(tmp_path: Path):
    cfg = dict(load_config())
    cfg["aws"] = {**cfg["aws"], "profile": "gaffer-profile-that-does-not-exist"}
    with pytest.raises(BedrockCredentialsError) as ei:
        BedrockClient(cfg, log_path=tmp_path / "l.jsonl")
    assert "not found" in str(ei.value)
