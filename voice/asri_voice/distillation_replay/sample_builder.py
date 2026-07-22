from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any

from handlers.heartbeat_interaction.history_formatter import (
    load_heartbeat_response_prompt_template,
    normalize_heartbeat_response_tool_payload,
    render_heartbeat_response_context,
)


@dataclass
class ResponseTurn:
    audio_ref: str
    assistant_response: str
    heartbeat_context: str | list[Any] | dict[str, Any] = field(default_factory=list)
    turn_state: dict[str, Any] = field(default_factory=lambda: {"thinking_entries": []})
    session_state: dict[str, Any] = field(default_factory=lambda: {"subtasks": []})


def _normalize_heartbeat_entry_for_response(
    entry: Any,
    *,
    prompt_template: Any,
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    raw_tools = entry.get("tools")
    if raw_tools is None:
        raw_tools = entry.get("tool_calls")
    tools = [
        item
        for tool in (raw_tools if isinstance(raw_tools, list) else [])
        if (item := normalize_heartbeat_response_tool_payload(tool, prompt_template)) is not None
    ]
    thinking = entry.get("thinking")
    if not thinking and not tools:
        return None

    normalized: dict[str, Any] = {}
    if entry.get("block") is not None:
        normalized["block"] = entry.get("block")
    elif entry.get("block_idx") is not None:
        normalized["block"] = entry.get("block_idx")
    if entry.get("action") is not None:
        normalized["action"] = entry.get("action")
    else:
        normalized["action"] = "think" if entry.get("thinking") or tools else "noop"
    normalized["tools"] = tools
    if thinking:
        normalized["thinking"] = thinking
    return normalized


def _response_context_payload(
    heartbeat_context: str | list[Any] | dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(heartbeat_context, str):
        try:
            heartbeat_context = json.loads(heartbeat_context)
        except json.JSONDecodeError:
            heartbeat_context = []
    if isinstance(heartbeat_context, dict):
        raw_entries = heartbeat_context.get("thinking_entries") or []
    elif isinstance(heartbeat_context, list):
        raw_entries = heartbeat_context
    else:
        raw_entries = []

    prompt_template = load_heartbeat_response_prompt_template()
    entries = [
        item
        for entry in raw_entries
        if (item := _normalize_heartbeat_entry_for_response(entry, prompt_template=prompt_template)) is not None
    ]
    return {
        "thinking_entries": entries,
        "subtasks": session_state.get("subtasks", []) if isinstance(session_state, dict) else [],
    }


def build_response_user_value(turn: ResponseTurn, *, include_heartbeat_context: bool) -> str:
    """Build one response user message.

    Historical response turns keep only their audio placeholder. The replayed
    HeartbeatContext is visible only on the current/final user turn, matching
    runtime behavior and last-round response training.
    """
    if not include_heartbeat_context:
        return "<audio>"
    payload = _response_context_payload(
        turn.heartbeat_context or turn.turn_state,
        turn.session_state,
    )
    return "<audio>" + render_heartbeat_response_context(payload)


def build_response_conversations(
    *,
    system_prompt: str,
    turns: list[ResponseTurn],
) -> list[dict[str, str]]:
    """Build one last-round response SFT conversation."""
    conversations = [{"from": "system", "value": system_prompt}]
    last_idx = len(turns) - 1
    for idx, turn in enumerate(turns):
        conversations.append({
            "from": "user",
            "value": build_response_user_value(turn, include_heartbeat_context=idx == last_idx),
        })
        conversations.append({"from": "assistant", "value": turn.assistant_response})
    return conversations


def build_response_sample(
    *,
    system_prompt: str,
    turns: list[ResponseTurn],
    tools: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task": "heartbeat_response",
        "tools": tools or [],
        "conversations": build_response_conversations(system_prompt=system_prompt, turns=turns),
        "audios": [turn.audio_ref for turn in turns],
        "meta": meta or {},
    }
