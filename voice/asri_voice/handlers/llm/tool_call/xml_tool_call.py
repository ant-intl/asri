"""XML tool-call helpers for text-only tool invocation.

Qwen3-Omni does not use the Chat Completions native ``tool_calls`` interface in
the audio-native path.  The response model emits tool calls as JSON objects
wrapped by ``<tool_call>...</tool_call>`` tags, matching the SFT projection.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any


TOOL_CALL_XML_INSTRUCTION = """### Tool Call XML Format
When a tool call is required, return a JSON object with the function name and arguments inside <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>

Return only schema-valid arguments. If a tool result is provided later in <tool_result> XML, use that result to continue the answer."""

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)


def _strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


def _normalise_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_xml_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract XML tool calls and return ``(clean_text, chat_api_tool_calls)``.

    The returned tool calls use Chat Completions format so they can flow through
    the existing realtime event and server-side execution code.
    """
    if not text:
        return "", []

    tool_calls: list[dict[str, Any]] = []
    for match in _TOOL_CALL_RE.finditer(text):
        raw_payload = _strip_json_fence(match.group(1))
        try:
            payload = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name") or payload.get("function_name") or payload.get("tool_name")
        if not isinstance(name, str) or not name.strip():
            continue
        arguments = _normalise_arguments(payload.get("arguments", payload.get("args", {})))
        tool_calls.append(
            {
                "id": str(payload.get("id") or payload.get("call_id") or f"call_{uuid.uuid4().hex[:12]}"),
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )

    clean_text = _TOOL_CALL_RE.sub("", text).strip()
    return clean_text, tool_calls


def render_tool_call_xml(name: str, arguments: Any) -> str:
    payload = {
        "name": name,
        "arguments": _normalise_arguments(arguments),
    }
    return "<tool_call>\n" + json.dumps(payload, ensure_ascii=False) + "\n</tool_call>"


def render_tool_result_xml(name: str, result: Any) -> str:
    payload = {
        "name": name,
        "result": result,
    }
    return "<tool_result>\n" + json.dumps(payload, ensure_ascii=False) + "\n</tool_result>"


def normalise_tool_schemas_for_prompt(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Render Chat/Realtime tool schemas in one compact prompt format."""
    normalized: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = function.get("name") or tool.get("name")
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "description": function.get("description") or tool.get("description") or "",
                "parameters": function.get("parameters") or tool.get("parameters") or {},
            }
        )
    return normalized


def tool_schemas_xml_system_block(tools: list[dict[str, Any]] | None) -> str:
    """Build the system-prompt block for XML tool calling."""
    normalized = normalise_tool_schemas_for_prompt(tools)
    if not normalized:
        return ""
    return (
        "\n\n### Tool Schemas\n"
        "The following tools are available. Use them only by emitting XML tool calls in the required format.\n"
        + json.dumps(normalized, ensure_ascii=False, indent=2)
        + "\n\n"
        + TOOL_CALL_XML_INSTRUCTION
    )
