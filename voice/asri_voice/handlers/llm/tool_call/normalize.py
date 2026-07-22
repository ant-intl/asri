"""Normalize tool calls from different API formats into NormalizedToolCall.

Supports:
- Chat Completions API format: {"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}
- Responses API / Realtime API format: {"name": "...", "arguments": "...", "call_id": "...", "type": "function_call"}
"""

import logging

from handlers.llm.tool_call.tool_registry import NormalizedToolCall

logger = logging.getLogger(__name__)


def normalize_chat_completions_tools(
    tool_calls: list[dict],
) -> list[NormalizedToolCall]:
    """Convert Chat Completions API tool calls to NormalizedToolCall.

    Input format::

        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Beijing"}'},
        }
    """
    result = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        if not name:
            logger.warning("Skipping tool call with empty name: %s", tc)
            continue
        result.append(NormalizedToolCall(
            call_id=tc.get("id", ""),
            name=name,
            arguments=fn.get("arguments", ""),
            raw_dict=tc,
        ))
    return result


def normalize_responses_api_tools(
    tool_calls: list[dict],
) -> list[NormalizedToolCall]:
    """Convert Responses API / Realtime API tool calls to NormalizedToolCall.

    Input format::

        {
            "name": "get_weather",
            "arguments": '{"city": "Beijing"}',
            "call_id": "call_abc",
            "type": "function_call",
        }
    """
    result = []
    for tc in tool_calls:
        name = tc.get("name", "")
        if not name:
            logger.warning("Skipping tool call with empty name: %s", tc)
            continue
        result.append(NormalizedToolCall(
            call_id=tc.get("call_id", ""),
            name=name,
            arguments=tc.get("arguments", ""),
            raw_dict=tc,
        ))
    return result