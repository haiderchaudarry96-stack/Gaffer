"""Phase 0 smoke test: one plain Bedrock call, then one tool-calling round trip.

Uses the `aws configure` credentials and the model / region from config.yaml.
Exit codes: 0 = OK, 2 = blocked on AWS quota (throttled), 1 = any other error.

Usage:
    py scripts\\smoke_test_bedrock.py [--fallback]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gaffer.llm.bedrock_client import (  # noqa: E402
    BedrockClient,
    BedrockError,
    BedrockThrottlingError,
    tool_result_message,
    tool_spec,
    user_message,
)

DUMMY_TOOL = tool_spec(
    "count_visible_players",
    "Return how many players of a team are visible in the video at a given match time.",
    {
        "type": "object",
        "properties": {
            "team": {"type": "string", "enum": ["home", "away"]},
            "t": {"type": "number", "description": "match time in seconds"},
        },
        "required": ["team", "t"],
    },
)


def count_visible_players(team: str, t: float) -> dict:
    """Dummy tool implementation: a fixed, small JSON result."""
    return {"team": team, "t": t, "players_visible": 9 if team == "home" else 8}


def report(label: str, result) -> None:
    print(f"\n[{label}] model={result.model_id} latency={result.latency_ms:.0f} ms "
          f"attempts={result.attempts} stop={result.stop_reason}")
    print(f"  tokens: in={result.usage['input_tokens']} out={result.usage['output_tokens']} "
          f"total={result.usage['total_tokens']}")
    if result.text:
        print(f"  reply: {result.text}")
    for tu in result.tool_uses:
        print(f"  tool call: {tu.name}({tu.input})")


def run(client: BedrockClient, model_id: str) -> None:
    """Plain call, then tool call -> execute tool -> final answer."""
    plain = client.chat([user_message("In one sentence: what does a football gaffer do?")],
                        model_id=model_id, max_tokens=80, purpose="smoke_plain")
    report("plain", plain)

    messages = [user_message("How many home players are visible at t=125 s? "
                             "Use the tool, then answer in one sentence.")]
    first = client.chat(messages, tools=[DUMMY_TOOL], model_id=model_id,
                        system="You are a football analysis assistant. Use tools for data.",
                        purpose="smoke_tool_request")
    report("tool request", first)
    if not first.wants_tools:
        raise BedrockError("Model did not request the tool.",
                           "Tool calling did not trigger; inspect the reply above.")
    messages.append(first.message)
    results = [(tu.tool_use_id, count_visible_players(**tu.input)) for tu in first.tool_uses]
    print(f"  tool results sent back: {[r for _, r in results]}")
    messages.append(tool_result_message(results))
    final = client.chat(messages, tools=[DUMMY_TOOL], model_id=model_id,
                        system="You are a football analysis assistant. Use tools for data.",
                        purpose="smoke_tool_answer")
    report("tool answer", final)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fallback", action="store_true", help="use bedrock.fallback_model_id")
    args = ap.parse_args()
    try:
        client = BedrockClient()
        model = client.fallback_model_id if args.fallback else client.model_id
        print(f"region={client.region} model={model}")
        run(client, model)
    except BedrockThrottlingError as exc:
        print(f"\nBLOCKED ON AWS QUOTA:\n  {exc}", file=sys.stderr)
        print(f"  (logged to {client.log_path})", file=sys.stderr)
        return 2
    except BedrockError as exc:
        print(f"\nERROR ({type(exc).__name__}):\n  {exc}", file=sys.stderr)
        return 1
    print(f"\nPASS: plain call and tool calling work. Usage logged to {client.log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
