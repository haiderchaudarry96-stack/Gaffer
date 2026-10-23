"""Thin client for the Amazon Bedrock Converse API.

Supports plain chat and tool calling, retries throttling / transient errors with
exponential backoff, and logs model, tokens and latency of every call to
`outputs/llm_calls.jsonl` (prompt contents are never logged).

Credentials come from the standard boto3 chain: the `aws configure` profile on the laptop,
the IAM instance role on EC2. Keys are never read, written or printed by this module.

Example:
    client = BedrockClient()
    result = client.chat([user_message("Hello")])
    print(result.text, result.usage)
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    ProfileNotFound,
    ReadTimeoutError,
)

from gaffer.config import load_config, repo_path

# --------------------------------------------------------------------------- errors


class BedrockError(RuntimeError):
    """Base class for all Bedrock client errors. `hint` says how to fix it."""

    def __init__(self, message: str, hint: str = "", code: str = "") -> None:
        super().__init__(message)
        self.hint = hint
        self.code = code

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\n  -> {self.hint}" if self.hint else base


class BedrockCredentialsError(BedrockError):
    """No, partial, invalid or expired AWS credentials."""


class BedrockModelAccessError(BedrockError):
    """Model not enabled for this account, wrong model id, or not available in this region."""


class BedrockThrottlingError(BedrockError):
    """Request throttled. `quota_exhausted` is True for daily-token / zero-quota limits,
    where retrying cannot help."""

    def __init__(self, message: str, hint: str = "", code: str = "",
                 quota_exhausted: bool = False) -> None:
        super().__init__(message, hint, code)
        self.quota_exhausted = quota_exhausted


class BedrockCallError(BedrockError):
    """Any other failure (validation, service error, network)."""


_RETRYABLE = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
}
_CREDENTIAL_CODES = {
    "UnrecognizedClientException",
    "InvalidSignatureException",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
}

# --------------------------------------------------------------------------- messages


def user_message(text: str) -> dict[str, Any]:
    """Build a Converse `user` message with one text block."""
    return {"role": "user", "content": [{"text": text}]}


def tool_spec(name: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    """Build a Converse tool definition from a JSON schema."""
    return {"toolSpec": {"name": name, "description": description,
                         "inputSchema": {"json": input_schema}}}


def tool_result_message(results: list[tuple[str, Any]], is_error: bool = False
                        ) -> dict[str, Any]:
    """Build the `user` message that returns tool results to the model.

    Args:
        results: (tool_use_id, JSON-serialisable result) pairs.
        is_error: mark all results as errors.
    """
    content = []
    for tool_use_id, result in results:
        block: dict[str, Any] = {"toolUseId": tool_use_id, "content": [{"json": result}]}
        if is_error:
            block["status"] = "error"
        content.append({"toolResult": block})
    return {"role": "user", "content": content}


@dataclass
class ToolUse:
    """A tool call requested by the model."""

    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass
class ChatResult:
    """Result of one Converse call."""

    text: str
    tool_uses: list[ToolUse]
    stop_reason: str
    message: dict[str, Any]          # the assistant message, to append to the conversation
    model_id: str
    latency_ms: float
    attempts: int
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason == "tool_use" and bool(self.tool_uses)


# --------------------------------------------------------------------------- client


class BedrockClient:
    """Bedrock Converse client with retries and usage logging.

    Args:
        config: parsed config dict (defaults to `load_config()`).
        client: an existing `bedrock-runtime` client (tests inject a stubbed one).
        log_path: JSONL file for per-call usage logs (defaults to `paths.llm_log`).
        sleep: sleep function used between retries (tests pass a no-op).
    """

    def __init__(self, config: dict[str, Any] | None = None, client: Any | None = None,
                 log_path: str | Path | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cfg = config or load_config()
        b = self.cfg["bedrock"]
        self.model_id: str = b["model_id"]
        self.fallback_model_id: str | None = b.get("fallback_model_id")
        self.max_tokens: int = b.get("max_tokens", 512)
        self.temperature: float = b.get("temperature", 0.2)
        r = b.get("retry", {})
        self.max_attempts: int = r.get("max_attempts", 4)
        self.base_delay: float = r.get("base_delay_s", 1.0)
        self.max_delay: float = r.get("max_delay_s", 20.0)
        self.region: str = self.cfg["aws"]["region"]
        self.log_path = Path(log_path) if log_path else repo_path(self.cfg["paths"]["llm_log"])
        self._sleep = sleep
        self._rng = random.Random(self.cfg.get("seed", 42))
        self.client = client or self._make_client(b.get("timeout_s", 60))

    def _make_client(self, timeout_s: float) -> Any:
        """Create the boto3 `bedrock-runtime` client from the configured profile/region."""
        profile = self.cfg["aws"].get("profile") or None
        try:
            session = boto3.Session(profile_name=profile, region_name=self.region)
        except ProfileNotFound as exc:
            raise BedrockCredentialsError(
                f"AWS profile '{profile}' not found.",
                "Run `aws configure` (or set AWS_PROFILE in .env to an existing profile).",
                "ProfileNotFound") from exc
        # botocore's own retries are off: we retry ourselves so every attempt is visible.
        cfg = Config(retries={"total_max_attempts": 1}, read_timeout=timeout_s,
                     connect_timeout=10)
        try:
            return session.client("bedrock-runtime", config=cfg)
        except NoRegionError as exc:
            raise BedrockCallError("No AWS region configured.",
                                   "Set aws.region in config.yaml.", "NoRegion") from exc

    # ---------------------------------------------------------------- public API
    def chat(self, messages: list[dict[str, Any]], system: str | None = None,
             tools: list[dict[str, Any]] | None = None, tool_choice: str | None = None,
             model_id: str | None = None, max_tokens: int | None = None,
             temperature: float | None = None, purpose: str = "") -> ChatResult:
        """Send one Converse request.

        Args:
            messages: Converse messages (see `user_message`, `tool_result_message`).
            system: optional system prompt.
            tools: optional tool definitions (see `tool_spec`).
            tool_choice: "auto" (default), "any", or a tool name to force that tool.
            model_id: override the configured model / inference profile id.
            max_tokens / temperature: override inference settings.
            purpose: short label written to the usage log (e.g. "smoke_plain").

        Raises:
            BedrockCredentialsError, BedrockModelAccessError, BedrockThrottlingError,
            BedrockCallError.
        """
        model = model_id or self.model_id
        request: dict[str, Any] = {
            "modelId": model,
            "messages": messages,
            "inferenceConfig": {
                "maxTokens": max_tokens or self.max_tokens,
                "temperature": self.temperature if temperature is None else temperature,
            },
        }
        if system:
            request["system"] = [{"text": system}]
        if tools:
            tool_config: dict[str, Any] = {"tools": tools}
            if tool_choice == "any":
                tool_config["toolChoice"] = {"any": {}}
            elif tool_choice and tool_choice != "auto":
                tool_config["toolChoice"] = {"tool": {"name": tool_choice}}
            request["toolConfig"] = tool_config

        t0 = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.client.converse(**request)
                break
            except Exception as exc:  # translated below; nothing is swallowed
                err = self._translate(exc, model)
                retryable = (
                    attempt < self.max_attempts
                    and not (isinstance(err, BedrockThrottlingError) and err.quota_exhausted)
                    and (err.code in _RETRYABLE or err.code in {"Timeout", "Connection"})
                )
                if not retryable:
                    self._log(model, purpose, attempt, t0, error=err)
                    err.attempts = attempt
                    raise err from exc
                delay = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
                self._sleep(delay + self._rng.uniform(0, delay * 0.25))

        result = self._parse(response, model, attempt, t0)
        self._log(model, purpose, attempt, t0, result=result)
        return result

    # ---------------------------------------------------------------- internals
    def _parse(self, response: dict[str, Any], model: str, attempts: int, t0: float
               ) -> ChatResult:
        message = response["output"]["message"]
        texts, tool_uses = [], []
        for block in message.get("content", []):
            if "text" in block:
                texts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_uses.append(ToolUse(tu["toolUseId"], tu["name"], tu.get("input", {})))
        usage = response.get("usage", {})
        return ChatResult(
            text="".join(texts).strip(),
            tool_uses=tool_uses,
            stop_reason=response.get("stopReason", ""),
            message=message,
            model_id=model,
            latency_ms=(time.perf_counter() - t0) * 1000,
            attempts=attempts,
            usage={"input_tokens": usage.get("inputTokens", 0),
                   "output_tokens": usage.get("outputTokens", 0),
                   "total_tokens": usage.get("totalTokens", 0)},
        )

    def _translate(self, exc: Exception, model: str) -> BedrockError:
        """Map boto/botocore exceptions to a specific BedrockError with a fix hint."""
        if isinstance(exc, BedrockError):
            return exc
        if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
            return BedrockCredentialsError(
                "No AWS credentials found.",
                "Run `aws configure` on this machine (or attach an IAM role on EC2). "
                "Never put keys in the repo.", "NoCredentials")
        if isinstance(exc, ReadTimeoutError):
            return BedrockCallError(f"Bedrock call timed out ({exc}).", "Retry later.",
                                    "Timeout")
        if isinstance(exc, EndpointConnectionError):
            return BedrockCallError(f"Cannot reach Bedrock endpoint in {self.region}.",
                                    "Check the internet connection and aws.region.",
                                    "Connection")
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            msg = exc.response.get("Error", {}).get("Message", "")
            low = msg.lower()
            if code in _CREDENTIAL_CODES:
                return BedrockCredentialsError(
                    f"AWS rejected the credentials ({code}): {msg}",
                    "Re-run `aws configure` with a valid access key for Gaffer-dev.", code)
            if code in {"ThrottlingException", "TooManyRequestsException"}:
                quota = "per day" in low or "quota" in low
                hint = ("Daily token quota is exhausted or zero for this account. Wait for "
                        "the Service Quotas increase to be approved (or the daily reset), "
                        "then re-run." if quota else
                        "Too many requests; retried with backoff. Try again shortly.")
                return BedrockThrottlingError(f"Bedrock throttled the request ({code}): {msg}",
                                              hint, code, quota_exhausted=quota)
            if code == "AccessDeniedException":
                return BedrockModelAccessError(
                    f"Access denied for model '{model}': {msg}",
                    "Enable the model under Bedrock > Model access in "
                    f"{self.region}, and check the IAM user has bedrock:InvokeModel.", code)
            if code in {"ResourceNotFoundException"} or (
                    code == "ValidationException"
                    and ("model identifier" in low or "inference profile" in low
                         or "on-demand throughput" in low or "not supported" in low)):
                return BedrockModelAccessError(
                    f"Model '{model}' is not usable in {self.region}: {msg}",
                    "Check bedrock.model_id in config.yaml against "
                    "`aws bedrock list-inference-profiles --region "
                    f"{self.region}`.", code)
            return BedrockCallError(f"Bedrock error ({code}): {msg}", "", code)
        if isinstance(exc, BotoCoreError):
            return BedrockCallError(f"botocore error: {exc}", "", type(exc).__name__)
        return BedrockCallError(f"Unexpected error: {exc!r}", "", type(exc).__name__)

    def _log(self, model: str, purpose: str, attempts: int, t0: float,
             result: ChatResult | None = None, error: BedrockError | None = None) -> None:
        """Append one usage record to the JSONL log (no prompt or reply text)."""
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "model_id": model,
            "region": self.region,
            "purpose": purpose,
            "ok": error is None,
            "attempts": attempts,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        if result is not None:
            record.update(result.usage)
            record["stop_reason"] = result.stop_reason
            record["tool_calls"] = [t.name for t in result.tool_uses]
        if error is not None:
            record["error_code"] = error.code
            record["error"] = str(error).splitlines()[0][:300]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
