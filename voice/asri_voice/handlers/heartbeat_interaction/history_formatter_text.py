"""Text-mode history formatter for streaming-ASR HeartBeat Interaction.

Unlike the omni-mode formatter (which uses ``<audio>`` placeholders and
base64 audio_url items), this module formats history and current-turn
text as plain text — suitable for a text-only LLM (e.g. vLLM Qwen3.5).

Prompt structure is identical to the omni version except:
- History user messages render actual text: ``[User]: <transcribed text>``
- Current user input is plain text instead of ``<audio>`` tag.
"""

import json
import logging
from handlers.heartbeat_interaction.history_formatter import (
    NO_QUERY,
    PromptTemplate,
    load_prompt_template,
    parse_predict_output,  # noqa: re-export
    render_tools_block,
    tools_markdown,
)

# Versions that include tool calls and tool results in conversation history.
FULL_HISTORY_VERSIONS = {
    "asri-v0",
    "asri-generic-v0",
    "asri-generic-interrupt-gate-v0",
}

logger = logging.getLogger(__name__)
_RUNTIME_MANAGED_KEYS = {"session_id", "user_id"}


# --------------------------------------------------------------------------- #
#  Text-mode history formatting
# --------------------------------------------------------------------------- #

def format_history_for_sft_text(messages: list[dict]) -> str:
    """Convert ``Chat.to_list()`` into the SFT ``Conversation history:`` body.

    Output uses actual transcribed text for user messages::

        [User]: How much does BlueTap cost?
        [Assistant]: The BlueTap device costs ...
        [User]: Can I pay with Apple Pay?

    In text mode, there is NO ``<audio>`` placeholder — user messages
    contain the actual transcribed text.  This differs from omni mode
    which uses ``<audio>`` + audio_url attachments.

    Rules:
    - ``system`` messages are skipped.
    - ``user`` messages emit ``[User]: <content text>``.
    - ``assistant`` messages with non-empty ``content`` emit
      ``[Assistant]: <text>``.
    - ``assistant`` messages with only ``tool_calls`` are skipped.
    - ``tool`` messages are skipped.
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            content = msg.get("content", "")
            lines.append(f"[User]: {content}")
        elif role == "assistant":
            content = msg.get("content")
            if content:
                lines.append(f"[Assistant]: {content}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Full-history formatting for the current ASRI prompt.
# --------------------------------------------------------------------------- #

def format_history_for_sft_text_full(messages: list[dict]) -> str:
    """Like :func:`format_history_for_sft_text` but includes tool calls and
    tool results so the predict model sees the full multi-turn trajectory.

    Output::

        [User]: I want to check the stock price for Microsoft.
        [Assistant]: <tool_call>get_5_day_historical_daily_prices({"ticker": "MSFT"})</tool_call>
        [Tool]: {"ticker":"MSFT","prices":[...]}
        [Assistant]: Here is the recent Microsoft price trend...

    Rules:
    - ``system`` messages are skipped.
    - ``user`` messages emit ``[User]: <content text>``.
    - ``assistant`` with ``tool_calls`` emits ``[Assistant]: <tool_call>name(json_args)</tool_call>``.
    - ``assistant`` with non-empty ``content`` emits ``[Assistant]: <text>``.
    - ``tool`` messages emit ``[Tool]: <content>``.
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            content = msg.get("content", "")
            lines.append(f"[User]: {content}")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            content = msg.get("content")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", "")
                    if not isinstance(args, str):
                        args = json.dumps(args, ensure_ascii=False)
                    lines.append(f"[Assistant]: <tool_call>{name}({args})</tool_call>")
            elif content:
                lines.append(f"[Assistant]: {content}")
            # Skip assistant messages with neither tool_calls nor content
        elif role == "tool":
            content = msg.get("content", "")
            lines.append(f"[Tool]: {content}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Text-mode HeartBeat prompt assembly
# --------------------------------------------------------------------------- #

def _format_time_range(start_s: float, end_s: float) -> str:
    """Render a time range like ``[0.0s - 0.5s]`` (one decimal place)."""
    return f"[{start_s:.1f}s - {end_s:.1f}s]"


def _strip_runtime_managed_keys(value):
    if isinstance(value, dict):
        return {
            k: _strip_runtime_managed_keys(v)
            for k, v in value.items()
            if k not in _RUNTIME_MANAGED_KEYS
        }
    if isinstance(value, list):
        return [_strip_runtime_managed_keys(v) for v in value]
    return value


def format_heartbeat_turn_state(entries: list) -> str:
    """Format same-turn HeartBeat thinker/tool state for later prompts."""
    payload = {
        "thinking_entries": [],
        "subtasks": [],
    }
    for entry in entries:
        entry_payload = {
            "block": getattr(entry, "order_key", None),
            "action": getattr(entry, "action", "think"),
            "tools": [],
        }
        thinking = getattr(entry, "thinking", "")
        if thinking:
            entry_payload["thinking"] = thinking
        metadata = getattr(entry, "metadata", None)
        if isinstance(metadata, dict) and metadata:
            entry_payload["metadata"] = metadata

        for item in getattr(entry, "items", []) or []:
            status = getattr(item, "status", "completed")
            tool_payload = {
                "name": getattr(item, "tool_name", ""),
                "arguments": _strip_runtime_managed_keys(getattr(item, "arguments", {})),
                "status": status,
            }
            result = getattr(item, "result", "")
            if status == "completed" and result:
                tool_payload["result"] = result
            entry_payload["tools"].append(tool_payload)
        payload["thinking_entries"].append(entry_payload)

    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_heartbeat_prompt_text(
    chat_messages: list[dict],
    current_text: str,
    block_idx: int,
    block_duration_ms: int = 500,
    prompt_template: PromptTemplate | None = None,
    async_context_entries: list | None = None,
    tool_context: dict | None = None,
    current_turn_metadata: dict | None = None,
    extra_instructions: str | None = None,
) -> dict:
    """Build the complete runtime HeartBeat prompt for the text-mode predict model.

    Returns a dict with ``"messages"`` key containing the standard
    ``[system_msg, user_msg]`` pair — pure text, no audio items.

    Args:
        chat_messages: Snapshot from ``Chat.to_list()`` (OpenAI format).
        current_text: Current partial ASR transcription text.
        block_idx: Zero-based index of the current audio block.
        block_duration_ms: Block duration in milliseconds (default 500).
        prompt_template: A :class:`PromptTemplate` instance.
        async_context_entries: Completed same-turn HeartBeat thinker/cache entries
            available when this prompt is built.

    Returns:
        ``{"messages": [system_msg, user_msg]}``
    """
    if prompt_template is None:
        prompt_template = load_prompt_template("asri-v0")

    runtime_tools = (
        tool_context.get("tools")
        if isinstance(tool_context, dict) and isinstance(tool_context.get("tools"), list)
        else None
    )
    tools_block = (
        render_tools_block(runtime_tools)
        if runtime_tools is not None
        else render_tools_block(prompt_template.tools)
    )

    system_msg = {"role": "system", "content": prompt_template.system}

    # Conversation history block (text-based)
    is_full_history = prompt_template.version in FULL_HISTORY_VERSIONS
    if is_full_history:
        history_body = format_history_for_sft_text_full(chat_messages)
    else:
        history_body = format_history_for_sft_text(chat_messages)

    # Current audio block — cumulative window starting at 0
    end_s = (block_idx + 1) * block_duration_ms / 1000.0
    time_range = _format_time_range(0.0, end_s)

    turn_state = format_heartbeat_turn_state(async_context_entries or [])
    if extra_instructions is None and isinstance(tool_context, dict):
        extra_instructions = tool_context.get("extra_instructions")
    user_text = prompt_template.render_user_prompt(
        tools_block=tools_block,
        history_body=history_body,
        current_fragment=current_text,
        time_range=time_range,
        current_turn_state=turn_state,
        current_turn_metadata=current_turn_metadata,
        extra_instructions=extra_instructions,
        mode="text",
    )

    user_msg = {"role": "user", "content": user_text}
    return {"messages": [system_msg, user_msg]}


# Backward-compatible name used by older tests and offline prompt tooling.
build_sft_prompt_text = build_heartbeat_prompt_text
