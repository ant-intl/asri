"""Format Chat history into the SFT-aligned prompt expected by the
HeartBeat Interaction streaming trigger model.

The current prompt templates are defined in ``prompt_templates/``. They define
the system prompt, business background, tool schemas, decision policy, output
format, and examples.  :func:`load_prompt_template` loads the named version;
:func:`build_sft_prompt` assembles the full prompt from a template plus
the dynamic conversation history and current audio block.

The dynamic pieces are:

- The ``Conversation history:`` block, built from ``Chat.to_list()``.
- The ``Current user audio: <audio>\\n[start_s - end_s]`` line, computed
  from the current ``block_idx`` and ``block_duration_ms``.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from handlers.heartbeat_interaction.prompt_templates import (
    get_response_prompt_definition,
    get_response_prompt_mapping,
    get_thinking_prompt_definition,
    get_thinking_prompt_mapping,
)

logger = logging.getLogger(__name__)

MODEL_HIDDEN_TOOL_RESULT_KEYS = {
    "session_id",
    "user_id",
    "idempotency_key",
    "execution_id",
    "duplicate_of_execution_id",
    "permission_level",
    "source",
    "allowed_sources",
    "retry_with_allowed_source",
    "retry_instruction",
    "blocked_reason",
    "transition",
    "duplicate_state",
    "duplicate_status",
}


# --------------------------------------------------------------------------- #
#  Prompt template dataclass
# --------------------------------------------------------------------------- #

@dataclass
class PromptTemplate:
    """Versioned prompt template for the HeartBeat Interaction model.

    Fields correspond to the sections of the SFT user prompt.

    The current template uses fields matching the HeartBeat prompt layout:
    ``task``, ``history_usage``, ``argument_rules``.
    When ``task`` is present, the user prompt is assembled with the current
    HeartBeat sections.
    """

    system: str
    business_background: str
    tools: list[dict]
    decision_policy: str
    output_format: str
    examples: str = ""
    version: str = ""
    task: str = ""
    history_usage: str = ""
    argument_rules: str = ""
    renderer: Any = None

    def tools_json(self) -> str:
        """Serialize tool definitions with indent=2 (matches training data)."""
        return json.dumps(self.tools, indent=2, ensure_ascii=False)

    def tools_markdown(self) -> str:
        """Format tools as markdown sections (matches step3 distiller format).

        Produces::

            ### search_epos_knowledge
            Description: ...
            Parameters: {...}
        """
        return tools_markdown(self.tools)

    def render_user_prompt(
        self,
        *,
        tools_block: str,
        history_body: str,
        current_fragment: str,
        time_range: str,
        current_turn_state: str | None = None,
        current_turn_metadata: dict | None = None,
        extra_instructions: str | None = None,
        mode: str = "text",
    ) -> str:
        """Render the complete HeartBeat Thinking user message.

        The registered Python prompt definition owns the prompt layout. This
        wrapper keeps the historical ``PromptTemplate`` API while keeping
        assembly out of the runtime formatter.
        """
        if self.renderer is None or not hasattr(self.renderer, "render_user_prompt"):
            raise ValueError(f"Prompt template has no renderer: {self.version}")
        return self.renderer.render_user_prompt(
            tools_block=tools_block,
            history_body=history_body,
            current_fragment=current_fragment,
            time_range=time_range,
            current_turn_state=current_turn_state,
            current_turn_metadata=current_turn_metadata,
            extra_instructions=extra_instructions,
            mode=mode,
        )


def tools_markdown(tools: list[dict]) -> str:
    """Format a runtime-provided tool schema like ``PromptTemplate.tools_markdown``."""
    lines = []
    for tool_def in tools:
        if not isinstance(tool_def, dict):
            continue
        func = tool_def.get("function") if isinstance(tool_def.get("function"), dict) else {}
        name = func.get("name") or tool_def.get("name") or ""
        description = func.get("description") or tool_def.get("description") or ""
        parameters = func.get("parameters") or tool_def.get("parameters") or {}
        lines.append(f"### {name}")
        lines.append(f"Description: {description}")
        lines.append(f"Parameters: {json.dumps(parameters, ensure_ascii=False, indent=2)}")
        lines.append("")
    return "\n".join(lines)


NO_TOOLS_BLOCK = "No tools are available in this request."


def render_tools_block(tools: list[dict]) -> str:
    """Render the injected tools section, including the empty-tool case."""
    block = tools_markdown(tools)
    return block if block.strip() else NO_TOOLS_BLOCK


# Historical prompt versions were removed from this repository. Keep the set
# empty so the remaining asri-v0 template always uses the current format.
LEGACY_FORMAT_VERSIONS: set[str] = set()

# --------------------------------------------------------------------------- #
#  Template loader
# --------------------------------------------------------------------------- #

_cache: dict[str, PromptTemplate] = {}


def load_prompt_template(version: str = "asri-v0") -> PromptTemplate:
    """Load a prompt template by version name.

    Looks for a code-defined template in ``prompt_templates/``. Results are
    cached so repeated calls are free.

    Args:
        version: Template version string. The current repository keeps only ``"asri-v0"``.

    Returns:
        A :class:`PromptTemplate` instance.

    Raises:
        ValueError: If the template version is not registered.
    """
    if version in _cache:
        return _cache[version]

    definition = get_thinking_prompt_definition(version)
    data = get_thinking_prompt_mapping(version)
    if data is None:
        raise ValueError(f"Prompt template version is not registered: {version}")

    template = PromptTemplate(
        system=data["system"].rstrip("\n"),
        business_background=data["business_background"].rstrip("\n"),
        tools=data.get("tools") or [],
        decision_policy=data["decision_policy"].rstrip("\n"),
        output_format=data["output_format"].rstrip("\n"),
        examples=data.get("examples", "").rstrip("\n") if data.get("examples") else "",
        version=version,
        task=data.get("task", "").rstrip("\n") if data.get("task") else "",
        history_usage=data.get("history_usage", "").rstrip("\n") if data.get("history_usage") else "",
        argument_rules=data.get("argument_rules", "").rstrip("\n") if data.get("argument_rules") else "",
        renderer=definition,
    )
    _cache[version] = template
    return template


@dataclass
class HeartbeatResponsePromptTemplate:
    """Template for temporary HeartbeatContext injected into response prompts."""

    header: str
    usage: str = ""
    examples: str = ""
    blocked_tool_note: str = ""
    version: str = ""
    renderer: Any = None

    def render_context(self, context_payload: dict) -> str:
        if self.renderer is None or not hasattr(self.renderer, "render_context"):
            raise ValueError(f"Heartbeat response prompt template has no renderer: {self.version}")
        return self.renderer.render_context(context_payload)


_response_cache: dict[str, HeartbeatResponsePromptTemplate] = {}


def load_heartbeat_response_prompt_template(version: str = "heartbeat-response-v0") -> HeartbeatResponsePromptTemplate:
    """Load the Heartbeat Response context prompt template."""
    if version in _response_cache:
        return _response_cache[version]

    definition = get_response_prompt_definition(version)
    data = get_response_prompt_mapping(version)
    if data is None:
        raise ValueError(f"Heartbeat response prompt template version is not registered: {version}")

    template = HeartbeatResponsePromptTemplate(
        header=data["header"].rstrip("\n"),
        usage=data.get("usage", "").rstrip("\n") if data.get("usage") else "",
        examples=data.get("examples", "").rstrip("\n") if data.get("examples") else "",
        blocked_tool_note=data.get("blocked_tool_note", "").rstrip("\n") if data.get("blocked_tool_note") else "",
        version=version,
        renderer=definition,
    )
    _response_cache[version] = template
    return template


def render_heartbeat_response_context(
    context_payload: dict,
    prompt_template: HeartbeatResponsePromptTemplate | None = None,
) -> str:
    """Render the temporary HeartbeatContext block injected into Response."""
    if prompt_template is None:
        prompt_template = load_heartbeat_response_prompt_template()

    return prompt_template.render_context(context_payload)


def strip_model_hidden_tool_fields(value: Any) -> Any:
    """Remove tool execution metadata that should never enter model input."""
    if isinstance(value, dict):
        return {
            k: strip_model_hidden_tool_fields(v)
            for k, v in value.items()
            if k not in MODEL_HIDDEN_TOOL_RESULT_KEYS
        }
    if isinstance(value, list):
        return [strip_model_hidden_tool_fields(v) for v in value]
    return value


def clean_tool_result_for_model(result: Any) -> str:
    """Serialize a tool result after stripping runtime/debug-only fields."""
    if result is None or result == "":
        return ""
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result
    else:
        parsed = result
    return json.dumps(strip_model_hidden_tool_fields(parsed), ensure_ascii=False)


def normalize_heartbeat_response_tool_payload(
    tool: dict[str, Any],
    prompt_template: HeartbeatResponsePromptTemplate | None = None,
) -> dict[str, Any] | None:
    """Normalize one HeartBeat tool state into the runtime Response payload shape."""
    if not isinstance(tool, dict):
        return None
    name = tool.get("name") or tool.get("tool_name")
    if not name:
        return None
    arguments = tool.get("arguments") if isinstance(tool.get("arguments"), dict) else {}
    status = str(tool.get("status") or "completed")
    payload: dict[str, Any] = {
        "name": str(name),
        "arguments": strip_model_hidden_tool_fields(arguments),
        "status": status,
    }

    clean_result = clean_tool_result_for_model(tool.get("result"))
    harness_state = None
    if clean_result:
        try:
            parsed_state = json.loads(clean_result)
            if isinstance(parsed_state, dict):
                harness_state = parsed_state.get("state")
        except (json.JSONDecodeError, TypeError):
            pass
        payload["result"] = clean_result
        if (
            harness_state == "BLOCKED_BY_PERMISSION"
            and prompt_template is not None
            and prompt_template.blocked_tool_note
        ):
            payload["note"] = prompt_template.blocked_tool_note
    return payload


# --------------------------------------------------------------------------- #
#  History formatting
# --------------------------------------------------------------------------- #

def format_history_for_sft(messages: list[dict]) -> str:
    """Convert ``Chat.to_list()`` into the SFT ``Conversation history:`` body.

    Output follows the SFT convention::

        [User]: <audio>
        [Assistant]: Hi! How can I help you today?
        [User]: <audio>
        [Assistant]: BlueTap is a portable payment terminal ...

    Every ``user`` message is rendered as ``[User]: <audio>``.  The predict
    handler attaches actual audio data from ``TurnAudioHistory`` to each
    corresponding user message when calling the omni model.

    Rules:

    - ``system`` messages are skipped (the system text is fixed and emitted
      separately by :func:`build_sft_prompt`).
    - ``user`` messages are rendered as ``[User]: <audio>``.  The predict
      handler maps these to real audio from the shared history buffer.
    - ``assistant`` messages with non-empty ``content`` emit ``[Assistant]: <text>``.
    - ``assistant`` messages with only ``tool_calls`` are skipped — the
      training samples never include a tool_call line in history.
    - ``tool`` messages are skipped for the same reason.

    Returns just the body lines joined by ``\\n``.  The leading
    ``"Conversation history:\\n"`` header is added by the caller.
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            lines.append("[User]: <audio>")
        elif role == "assistant":
            content = msg.get("content")
            if content:
                lines.append(f"[Assistant]: {content}")
        # system / tool / assistant-with-only-tool_calls are intentionally dropped
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  SFT prompt assembly
# --------------------------------------------------------------------------- #

def _format_time_range(start_s: float, end_s: float) -> str:
    """Render a time range like ``[0.0s - 0.5s]`` (one decimal place)."""
    return f"[{start_s:.1f}s - {end_s:.1f}s]"


def build_sft_prompt(
    chat_messages: list[dict],
    block_idx: int,
    block_duration_ms: int = 500,
    prompt_template: PromptTemplate | None = None,
    async_context_entries: list | None = None,
    tool_context: dict | None = None,
    current_turn_metadata: dict | None = None,
    extra_instructions: str | None = None,
) -> dict:
    """Build the complete SFT-format prompt for the HeartBeat Interaction model.

    Returns a dict with a ``"messages"`` key containing the standard
    ``[system_msg, user_msg]`` pair.  The caller injects the actual audio
    bytes (replacing the trailing ``<audio>`` placeholder) when sending
    the request to the omni predict model.

    Args:
        chat_messages: Snapshot from ``Chat.to_list()`` (OpenAI format).
        block_idx: Zero-based index of the current audio block.  The
            corresponding time range is
            ``[0.0, (block_idx + 1) * block_duration_ms / 1000]``.
        block_duration_ms: Block duration in milliseconds (default 500,
            matching the SFT training data).
        prompt_template: A :class:`PromptTemplate` instance. If ``None``,
            ``asri-v0`` is loaded.

    Returns:
        ``{"messages": [system_msg, user_msg]}`` — byte-identical to what
        the model saw during training (modulo the dynamic pieces: history
        lines and the cumulative time range).
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

    # Conversation history block
    history_body = format_history_for_sft(chat_messages)

    # Current audio block — cumulative window starting at 0
    end_s = (block_idx + 1) * block_duration_ms / 1000.0
    time_range = _format_time_range(0.0, end_s)

    turn_state = format_heartbeat_turn_state(async_context_entries or [])
    if extra_instructions is None and isinstance(tool_context, dict):
        extra_instructions = tool_context.get("extra_instructions")
    user_text = prompt_template.render_user_prompt(
        tools_block=tools_block,
        history_body=history_body,
        current_fragment="<audio>",
        time_range=time_range,
        current_turn_state=turn_state,
        current_turn_metadata=current_turn_metadata,
        extra_instructions=extra_instructions,
        mode="audio",
    )

    user_msg = {"role": "user", "content": user_text}
    return {"messages": [system_msg, user_msg]}


def _strip_runtime_managed_keys(value):
    if isinstance(value, dict):
        return {
            k: _strip_runtime_managed_keys(v)
            for k, v in value.items()
            if k not in {"session_id", "user_id"}
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


# --------------------------------------------------------------------------- #
#  Output parsing (SFT assistant text → individual tool calls)
# --------------------------------------------------------------------------- #

NO_QUERY = "NO_QUERY"


def _normalize_tools(parsed: dict) -> list[dict]:
    calls: list[dict] = []

    raw_calls = parsed.get("tools", parsed.get("tool_calls", []))
    if isinstance(raw_calls, dict):
        raw_calls = [raw_calls]
    if isinstance(raw_calls, list):
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            name = (
                raw.get("name")
                or raw.get("tool_name")
                or raw.get("function_name")
                or fn.get("name")
            )
            arguments = raw.get("arguments", raw.get("args", fn.get("arguments", {})))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments else {}
                except json.JSONDecodeError:
                    arguments = {}
            if name and isinstance(arguments, dict):
                calls.append({"name": name, "arguments": arguments})

    for legacy_name in ("query_epos_order", "search_epos_knowledge"):
        value = parsed.get(legacy_name, NO_QUERY)
        if isinstance(value, dict):
            calls.append({"name": legacy_name, "arguments": value})

    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for call in calls:
        key = (
            call["name"],
            json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call)
    return deduped


def iter_predict_tool_calls(parsed: dict) -> list[tuple[str, dict]]:
    """Return normalized ``(tool_name, arguments)`` calls from parsed output."""
    calls = parsed.get("tools", parsed.get("tool_calls", []))
    if not isinstance(calls, list):
        return []
    normalized: list[tuple[str, dict]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        arguments = call.get("arguments")
        if isinstance(name, str) and isinstance(arguments, dict):
            normalized.append((name, arguments))
    return normalized


def parse_predict_output(text: str) -> dict | None:
    """Parse the model's assistant output into a thinker/tool-call dict.

    Canonical expected shape::

        {
          "action": "noop" | "think",
          "thinking": "...",
          "tools": [{"name": "...", "arguments": {...}}]
        }

    Returns the parsed dict, or ``None`` if the text is not valid JSON or
    does not have the expected top-level structure. Legacy prompt outputs using
    ``need_to_think``/``tool_calls`` or direct ``query_epos_order``/``search_epos_knowledge``
    keys are still accepted and normalized into ``action``/``tools``.
    """
    if not text:
        return None
    text = text.strip()
    # Some models wrap JSON in ```json ... ``` fences; strip them.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("predict output is not valid JSON: %s", text[:200])
        return None
    if not isinstance(parsed, dict):
        logger.warning("predict output is not a JSON object: %s", text[:200])
        return None
    thinking = parsed.get("thinking", "")
    if thinking is None:
        thinking = ""
    elif not isinstance(thinking, str):
        thinking = json.dumps(thinking, ensure_ascii=False)
    tools = _normalize_tools(parsed)
    raw_action = parsed.get("action")
    if isinstance(raw_action, str):
        action = raw_action.strip().lower()
    else:
        action = ""

    need_to_think = parsed.get("need_to_think")
    if isinstance(need_to_think, str):
        need_to_think = need_to_think.strip().lower() not in (
            "false", "0", "no", "no_think", "<no_think>"
        )
    elif need_to_think is not None:
        need_to_think = bool(need_to_think)
    explicit_action = action in {"noop", "think"}
    if not explicit_action:
        if thinking.strip() or tools:
            action = "think"
        elif need_to_think is False:
            action = "noop"
        elif raw_action:
            action = "noop"
        else:
            action = "think"
    if action == "noop":
        thinking = ""
        tools = []
    normalized = {
        "action": action,
        "thinking": thinking.strip(),
        "tools": tools,
        # Compatibility for callers/tests that have not moved yet.
        "need_to_think": action == "think",
        "tool_calls": tools,
    }
    return normalized
