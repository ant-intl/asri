from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from handlers.llm.thinking import disabled_thinking_extra_body


def normalize_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_tool_mock_prompt(
    *,
    tool_name: str,
    tool_schema: dict[str, Any],
    arguments: dict[str, Any],
    tool_examples: list[dict[str, Any]],
    conversation_prior_mock_results: list[dict[str, Any]] | None = None,
) -> str:
    """Build the sectioned Tool Mock LLM input."""
    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join([
        f"### Tool\n{dump({'name': tool_name, 'schema': tool_schema})}",
        f"### Arguments\n{dump(arguments)}",
        (
            "### Tool Examples\n"
            "Each item has arguments and result. If examples are present, generate only the raw tool result with "
            "the same shape as one result; do not output the whole example object. If examples are empty, infer a "
            "plausible raw backend result from Tool and Arguments only.\n"
            f"{dump(tool_examples)}"
        ),
        f"### Conversation Prior Mock Results\n{dump(conversation_prior_mock_results or [])}",
    ])


def extract_tool_examples(tool_def: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract per-tool examples from common dynamic tool schema locations."""
    if not isinstance(tool_def, dict):
        return []
    candidates = [
        tool_def.get("tool_examples"),
        tool_def.get("examples"),
        tool_def.get("x-examples"),
    ]
    function = tool_def.get("function")
    if isinstance(function, dict):
        candidates.extend([
            function.get("tool_examples"),
            function.get("examples"),
            function.get("x-examples"),
        ])
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            candidates.extend([
                parameters.get("tool_examples"),
                parameters.get("examples"),
                parameters.get("x-examples"),
            ])
    parameters = tool_def.get("parameters")
    if isinstance(parameters, dict):
        candidates.extend([
            parameters.get("tool_examples"),
            parameters.get("examples"),
            parameters.get("x-examples"),
        ])

    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _shape_name(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def _matches_example_shape(value: Any, example: Any) -> bool:
    if _shape_name(value) != _shape_name(example):
        return False
    if isinstance(example, dict):
        # Keep this permissive: tool examples describe the result family, but
        # individual tool outputs may carry optional fields. Required shape is
        # enforced at the top-level key/type level.
        for key, example_value in example.items():
            if key not in value:
                return False
            if not _matches_example_shape(value[key], example_value):
                return False
    if isinstance(example, list):
        if not example:
            return value == []
        if not value:
            return False
        return all(
            any(_matches_example_shape(value_item, example_item) for example_item in example)
            for value_item in value
        )
    return True


def _is_empty_tool_result(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (dict, list)):
        return len(value) == 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    return False


def parse_tool_mock_output(raw_output: str, tool_examples: list[dict[str, Any]]) -> Any:
    """Parse a Tool Mock LLM response as raw tool result.

    If examples are provided, the model output must match the structure of at
    least one tool_examples[].result value. Without examples, accept any
    non-empty valid JSON result; that path is useful for non-target tool calls
    and does not by itself prove GT coverage.
    """
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError("tool mock output must be valid JSON") from exc

    if _is_empty_tool_result(parsed):
        raise ValueError("tool mock output must not be empty")

    example_results = [item.get("result") for item in tool_examples if isinstance(item, dict) and "result" in item]
    if not example_results:
        return parsed
    if not any(_matches_example_shape(parsed, example) for example in example_results):
        expected = ", ".join(sorted({_shape_name(example) for example in example_results}))
        raise ValueError(f"tool mock output shape mismatch; expected one of: {expected}")
    return parsed


@dataclass
class ToolMockCache:
    """Per-conversation cache keyed by tool_name + normalized arguments."""

    _values: dict[tuple[str, str], Any]

    def __init__(self) -> None:
        self._values = {}

    def key(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, str]:
        return (tool_name, normalize_arguments(arguments))

    def get(self, tool_name: str, arguments: dict[str, Any]) -> Any | None:
        return self._values.get(self.key(tool_name, arguments))

    def put(self, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
        self._values[self.key(tool_name, arguments)] = result


@dataclass(frozen=True)
class ToolMockLLMConfig:
    base_url: str
    model: str = "default"
    api_key: str = "EMPTY"
    temperature: float = 0.0
    timeout_s: float = 120.0
    disable_thinking: bool = True

    @classmethod
    def from_env(cls, prefix: str = "HEARTBEAT_TOOL_MOCK") -> "ToolMockLLMConfig | None":
        base_url = os.getenv(f"{prefix}_BASE_URL")
        if not base_url:
            return None
        return cls(
            base_url=base_url,
            model=os.getenv(f"{prefix}_MODEL", "default"),
            api_key=os.getenv(f"{prefix}_API_KEY", "EMPTY"),
            temperature=float(os.getenv(f"{prefix}_TEMPERATURE", "0")),
            timeout_s=float(os.getenv(f"{prefix}_TIMEOUT_S", "120")),
            disable_thinking=os.getenv(f"{prefix}_DISABLE_THINKING", "true").lower() not in {"0", "false", "no"},
        )

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"


class ToolMockLLMClient:
    """OpenAI-compatible client for offline dynamic tool-result synthesis."""

    def __init__(self, config: ToolMockLLMConfig):
        self.config = config
        self.session = requests.Session()

    def generate(
        self,
        *,
        tool_name: str,
        tool_schema: dict[str, Any],
        arguments: dict[str, Any],
        tool_examples: list[dict[str, Any]],
        conversation_prior_mock_results: list[dict[str, Any]] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        prompt = build_tool_mock_prompt(
            tool_name=tool_name,
            tool_schema=tool_schema,
            arguments=arguments,
            tool_examples=tool_examples,
            conversation_prior_mock_results=conversation_prior_mock_results or [],
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Generate a plausible backend tool result only. Return valid JSON "
                        "with no extra result/confidence/reason wrapper. When Tool Examples "
                        "are present, the top-level shape must match one of Tool Examples[].result. "
                        "When Tool Examples are empty, infer a concise plausible backend-result "
                        "shape from the tool schema/name and arguments. Use Tool Examples as "
                        "result-shape and behavior references, not as values to copy blindly. "
                        "For search, recommendation, classification, news, "
                        "knowledge, weather, or similarly semantic tools, arguments with "
                        "similar meaning may reasonably produce similar results. For exact "
                        "lookup tools such as order IDs, shipment IDs, account IDs, usernames, "
                        "wallet addresses, verification codes, phone/email identifiers, or "
                        "database record IDs, small argument differences should produce a "
                        "clearly different result, not-found/error, or validation failure. "
                        "Never invent hidden tool state beyond schema, arguments, examples, "
                        "and prior mock results in this same conversation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self.config.disable_thinking:
            extra_body = disabled_thinking_extra_body(self.config.model)
            if extra_body:
                payload.update(extra_body)

        max_attempts = int(os.getenv("HEARTBEAT_TOOL_MOCK_MAX_RETRY", "3"))
        total_start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_start = time.perf_counter()
            try:
                response = self.session.post(
                    self.config.chat_completions_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    timeout=self.config.timeout_s,
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                result = parse_tool_mock_output(content, tool_examples)
                wall_latency_ms = round((time.perf_counter() - total_start) * 1000)
                return result, {
                    "mock_wall_latency_ms": wall_latency_ms,
                    "mock_attempts": attempt,
                    "model": self.config.model,
                    "base_url": self.config.base_url,
                }
            except Exception as exc:
                last_error = exc
                attempt_ms = round((time.perf_counter() - attempt_start) * 1000)
                print(
                    f"[ToolMockLLMClient] tool={tool_name} attempt={attempt}/{max_attempts} "
                    f"failed in {attempt_ms}ms: {type(exc).__name__}: {exc}",
                    flush=True,
                )
                if attempt < max_attempts:
                    time.sleep(min(2.0 ** (attempt - 1), 5.0))
        raise RuntimeError(
            f"Tool mock LLM failed after {max_attempts} attempts for tool={tool_name}: {last_error}"
        )
