from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from handlers.llm.thinking import disabled_thinking_extra_body


@dataclass(frozen=True)
class ToolTriggerJudgeConfig:
    base_url: str
    model: str = "default"
    api_key: str = "EMPTY"
    temperature: float = 0.0
    timeout_s: float = 120.0
    disable_thinking: bool = True

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _section_value(value: Any) -> str:
    return _compact(value)


_REQUIRED_JUDGE_KEYS = {
    "stable_trigger",
    "semantic_reasonable",
    "schema_exact",
    "matched_tool_name",
    "reason",
}


def validate_tool_trigger_judge_output(parsed: dict[str, Any]) -> dict[str, Any]:
    keys = set(parsed.keys())
    missing = _REQUIRED_JUDGE_KEYS - keys
    extra = keys - _REQUIRED_JUDGE_KEYS
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing keys: {','.join(sorted(missing))}")
        if extra:
            details.append(f"extra keys: {','.join(sorted(extra))}")
        raise ValueError(f"tool trigger judge output must contain exactly the required keys ({'; '.join(details)})")
    for key in ("stable_trigger", "semantic_reasonable", "schema_exact"):
        if not isinstance(parsed[key], bool):
            raise ValueError(f"tool trigger judge output field {key} must be boolean")
    if parsed["matched_tool_name"] is not None and not isinstance(parsed["matched_tool_name"], str):
        raise ValueError("tool trigger judge output field matched_tool_name must be string or null")
    if not isinstance(parsed["reason"], str):
        raise ValueError("tool trigger judge output field reason must be string")
    return parsed


def build_tool_trigger_judge_prompt(
    *,
    conversation_history: list[dict[str, Any]],
    current_fragment: str,
    available_tools: list[dict[str, Any]],
    attempted_tool: dict[str, Any],
    current_turn_state: dict[str, Any] | None = None,
) -> str:
    sections = [
        ("Conversation History", conversation_history),
        ("Current Fragment", current_fragment),
        ("Current Turn State", current_turn_state or {}),
        ("Available Tools", available_tools),
        ("Attempted Tool Call", attempted_tool),
    ]
    body = "\n\n".join(f"### {title}\n{_section_value(value)}" for title, value in sections)
    return (
        f"{body}\n\n"
        "### Task\n"
        "Judge whether the Attempted Tool Call is a stable and reasonable Heartbeat Thinking trigger for the Current Fragment.\n\n"
        "A trigger can be reasonable even if the tool name or argument keys do not exactly match the available schema, "
        "as long as the model clearly attempted the right kind of tool call from stable user information. "
        "However, exact schema validity must be judged separately.\n\n"
        "Rules:\n"
        "- If Current Fragment is empty, stable_trigger must be false.\n"
        "- stable_trigger is true only when the current fragment contains enough stable intent and argument evidence to justify a tool attempt now.\n"
        "- semantic_reasonable is true when the attempted tool intent and arguments are semantically appropriate for the fragment and available tools.\n"
        "- schema_exact is true only when the tool name exactly matches one Available Tools name and every argument key is allowed by that tool schema with required arguments present.\n"
        "- If the attempt uses a semantically plausible but wrong tool name, set semantic_reasonable=true and schema_exact=false, and fill matched_tool_name if one available tool best matches.\n"
        "- If an ID, address, username, code, phone, email, date, location, ticker, or other exact lookup argument is incomplete or corrupted in the fragment, stable_trigger should be false unless the available schema clearly does not require that value.\n"
        "- Do not reward guessing missing exact identifiers. For web search/recommendation/classification tools, semantically similar query wording can still be reasonable.\n\n"
        "Return JSON only with exactly these keys:\n"
        "{"
        "\"stable_trigger\":boolean,"
        "\"semantic_reasonable\":boolean,"
        "\"schema_exact\":boolean,"
        "\"matched_tool_name\":string|null,"
        "\"reason\":string"
        "}"
    )


class ToolTriggerJudgeClient:
    def __init__(self, config: ToolTriggerJudgeConfig):
        self.config = config
        self.session = requests.Session()

    def judge(
        self,
        *,
        conversation_history: list[dict[str, Any]],
        current_fragment: str,
        available_tools: list[dict[str, Any]],
        attempted_tool: dict[str, Any],
        current_turn_state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prompt = build_tool_trigger_judge_prompt(
            conversation_history=conversation_history,
            current_fragment=current_fragment,
            available_tools=available_tools,
            attempted_tool=attempted_tool,
            current_turn_state=current_turn_state,
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict offline judge for Heartbeat Thinking tool triggers. "
                        "Return JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self.config.disable_thinking:
            extra_body = disabled_thinking_extra_body(self.config.model)
            if extra_body:
                payload.update(extra_body)

        start = time.perf_counter()
        response = self.session.post(
            self.config.chat_completions_url,
            json=payload,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            timeout=self.config.timeout_s,
        )
        wall_latency_ms = round((time.perf_counter() - start) * 1000)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("tool trigger judge output must be a JSON object")
        validate_tool_trigger_judge_output(parsed)
        return parsed, {
            "judge_wall_latency_ms": wall_latency_ms,
            "model": self.config.model,
            "base_url": self.config.base_url,
        }
