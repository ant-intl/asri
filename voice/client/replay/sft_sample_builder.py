"""Build ShareGPT-style SFT samples from a replay trace.

Two kinds of samples are produced:

* **Thinking samples** (``task: "heartbeat_thinking"``): one per
  completed heartbeat block.  Input = the system + user messages that
  the runtime sent to the Heartbeat LLM; output = the raw JSON response
  (``{"action":"think","thinking":"...","tools":[...]}``).

* **Response samples** (``task: "heartbeat_response"``): one per row.
  Input = the runtime response LLM input messages snapshot (with the
  HeartbeatContext-injected user message); output = the LLM-rewritten
  response messages (adjusted for final ASR + heartbeat tool coverage).

The builder is pure: given a row and a trace, it returns a list of
sample dicts.  No I/O.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from distillation_replay.response_with_reference import ResponseWithReferenceClient
from distillation_replay.tool_trigger_judge import ToolTriggerJudgeClient

TOOL_CALL_XML_INSTRUCTION = (
    "### Tool Call XML Format\n"
    "For each function call, return a json object with function name and "
    "arguments within <tool_call></tool_call> XML tags:\n"
    "<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n'
    "</tool_call>"
)


# ---------------------------------------------------------------------------
# Message normalization helpers
# ---------------------------------------------------------------------------


def _role(message: dict[str, Any]) -> str:
    return str(message.get("role") or message.get("from") or "")


def _content(message: dict[str, Any]) -> str:
    return str(message.get("content") if message.get("content") is not None else message.get("value") or "")


def _schema_tool_name(tool_def: dict[str, Any]) -> str:
    function = tool_def.get("function") if isinstance(tool_def.get("function"), dict) else {}
    return str(function.get("name") or tool_def.get("name") or "")


def _schema_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function.get("name") or tool.get("name") or "")
        if name:
            names.add(name)
    return names


def _normalize_response_with_reference_message(message: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    role = _role(message)
    if role not in {"assistant", "tool"}:
        return None
    normalized: dict[str, Any] = {"role": role, "content": _content(message)}
    if role == "assistant" and isinstance(message.get("tool_calls"), list):
        calls: list[dict[str, Any]] = []
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(function.get("name") or call.get("name") or "")
            if not name:
                continue
            arguments = function.get("arguments", call.get("arguments", {}))
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            elif not isinstance(arguments, str):
                arguments = "{}"
            calls.append({
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            })
            for key in ("id", "call_id", "tool_call_id"):
                if call.get(key) is not None:
                    calls[-1][key] = call.get(key)
        if calls:
            normalized["tool_calls"] = calls
    if role == "tool":
        if message.get("name") is not None:
            normalized["name"] = message.get("name")
        if message.get("tool_call_id") is not None:
            normalized["tool_call_id"] = message.get("tool_call_id")
    return normalized


def _validate_response_messages(
    messages: list[dict[str, Any]],
    *,
    available_tool_names: set[str],
) -> str | None:
    """Return an error string if the LLM-rewritten messages are invalid, else None."""
    for message in messages:
        role = _role(message)
        content = _content(message)
        if role == "assistant":
            tool_calls = message.get("tool_calls") or []
            if not content.strip() and not tool_calls:
                return "assistant message must have non-empty content or tool_calls"
            for call in tool_calls:
                if not isinstance(call, dict):
                    return "tool_call must be a dict"
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                name = str(function.get("name") or call.get("name") or "")
                if not name:
                    return "tool_call must have a function name"
                if name not in available_tool_names:
                    return f"tool_call name {name!r} not in available tool schemas"
                arguments = function.get("arguments", call.get("arguments", ""))
                if isinstance(arguments, str):
                    if not arguments.strip():
                        continue
                    try:
                        json.loads(arguments)
                    except json.JSONDecodeError:
                        return f"tool_call arguments for {name!r} must be valid JSON"
        elif role == "tool":
            if not content.strip():
                return "tool message must have non-empty content"
            name = str(message.get("name") or "")
            if not name:
                return "tool message must have a 'name'"
            if name not in available_tool_names:
                return f"tool message name {name!r} not in available tool schemas"
        else:
            return f"unexpected role {role!r} in LLM-rewritten messages"
    return None


def _copy_tool_calls_for_sft(tool_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    copied: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        copied.append(deepcopy(call))
    return copied


def _json_or_text_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _tool_call_xml(call: dict[str, Any]) -> str | None:
    if not isinstance(call, dict):
        return None
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(function.get("name") or call.get("name") or "")
    if not name:
        return None
    arguments = function.get("arguments", call.get("arguments", {}))
    arguments = _json_or_text_value(arguments)
    if not isinstance(arguments, dict):
        arguments = {}
    payload = {"name": name, "arguments": arguments}
    return (
        "<tool_call>\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
        "</tool_call>"
    )


def _assistant_value_with_xml_tool_calls(message: dict[str, Any]) -> str:
    value = _content(message).strip()
    xml_calls = [
        xml
        for call in _copy_tool_calls_for_sft(message.get("tool_calls"))
        if (xml := _tool_call_xml(call)) is not None
    ]
    if not xml_calls:
        return value
    if value:
        return value + "\n\n" + "\n".join(xml_calls)
    return "\n".join(xml_calls)


def _tool_result_user_value(message: dict[str, Any]) -> str:
    payload: dict[str, Any] = {}
    if message.get("name") is not None:
        payload["name"] = message.get("name")
    payload["result"] = _json_or_text_value(_content(message))
    return (
        "<tool_result>\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
        "</tool_result>"
    )


def _system_value_with_xml_tool_instruction(value: str, *, tools: list[dict[str, Any]]) -> str:
    if not tools or TOOL_CALL_XML_INSTRUCTION in value:
        return value
    return value.rstrip() + "\n\n" + TOOL_CALL_XML_INSTRUCTION


def append_response_sft_message(
    conversations: list[dict[str, Any]],
    message: dict[str, Any],
    *,
    tools: list[dict[str, Any]] | None = None,
    user_value: str | None = None,
) -> None:
    """Append one message after projecting native tool messages to XML.

    Omni response SFT does not consume native OpenAI ``tool_calls`` or
    ``role=tool`` messages.  Use this helper for both history and target
    response messages so historical tool calls cannot leak through a
    separate assembly path.
    """
    role = _role(message)
    if role == "system":
        conversations.append({
            "from": "system",
            "value": _system_value_with_xml_tool_instruction(
                _content(message),
                tools=tools or [],
            ),
        })
    elif role == "user":
        conversations.append({"from": "user", "value": _content(message) if user_value is None else user_value})
    elif role == "assistant":
        conversations.append({
            "from": "assistant",
            "value": _assistant_value_with_xml_tool_calls(message),
        })
    elif role == "tool":
        conversations.append({"from": "user", "value": _tool_result_user_value(message)})


def _tool_call_id(call: dict[str, Any]) -> str:
    if not isinstance(call, dict):
        return ""
    return str(call.get("id") or call.get("call_id") or call.get("tool_call_id") or "")


def _drop_orphan_empty_assistant_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop malformed history pairs that have tool results but no tool call.

    Some upstream seed histories contain an empty assistant message followed by
    one or more ``role=tool`` messages, with the original assistant tool_calls
    already missing. These pairs are not valid response SFT history: keeping
    them projects to an empty assistant turn plus orphan ``<tool_result>``.
    """
    filtered: list[dict[str, Any]] = []
    dropping_tool_results = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = _role(message)
        if role == "assistant" and not _content(message).strip() and not message.get("tool_calls"):
            dropping_tool_results = True
            continue
        if role == "tool" and dropping_tool_results:
            continue
        dropping_tool_results = False
        filtered.append(message)
    return filtered


def _drop_history_toolcall_pairs_for_sft(
    messages: list[dict[str, Any]],
    dropped_history_toolcalls: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Remove dropped historical assistant tool calls and paired tool results.

    ``ReplaySession`` applies history tool-call dropout before sending history
    to the runtime server. Response SFT samples are built from the runtime
    response-input snapshot, so apply the same pair filtering here to avoid
    emitting an empty assistant turn followed by an orphan ``<tool_result>``.
    """
    dropped_ids = {
        str(item.get("tool_call_id") or item.get("id") or item.get("call_id"))
        for item in (dropped_history_toolcalls or [])
        if isinstance(item, dict) and (item.get("tool_call_id") or item.get("id") or item.get("call_id"))
    }
    if not dropped_ids:
        return _drop_orphan_empty_assistant_tool_results(messages)

    filtered: list[dict[str, Any]] = []
    pending_idless_tool_results = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = _role(message)
        if role == "assistant" and isinstance(message.get("tool_calls"), list):
            remaining_calls: list[dict[str, Any]] = []
            dropped_count = 0
            for call in message.get("tool_calls") or []:
                call_id = _tool_call_id(call)
                if call_id and call_id in dropped_ids:
                    dropped_count += 1
                    continue
                remaining_calls.append(call)
            pending_idless_tool_results += dropped_count
            if remaining_calls:
                new_message = dict(message)
                new_message["tool_calls"] = remaining_calls
                filtered.append(new_message)
                continue
            new_message = dict(message)
            new_message.pop("tool_calls", None)
            if _content(new_message).strip():
                filtered.append(new_message)
            continue
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            if tool_call_id in dropped_ids:
                if pending_idless_tool_results > 0:
                    pending_idless_tool_results -= 1
                continue
            if not tool_call_id and pending_idless_tool_results > 0:
                pending_idless_tool_results -= 1
                continue
            filtered.append(message)
            continue

        pending_idless_tool_results = 0
        filtered.append(message)
    return _drop_orphan_empty_assistant_tool_results(filtered)


def _validate_thinking_response(raw_response: str) -> str | None:
    """Return an error string if raw_response is not a valid thinking output, else None."""
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        return "raw_response is not valid JSON"
    if not isinstance(parsed, dict):
        return "raw_response must be a JSON object"
    action = parsed.get("action")
    if action not in {"think", "noop"}:
        return f"action must be 'think' or 'noop', got: {action!r}"
    if action == "think":
        thinking = parsed.get("thinking")
        if not isinstance(thinking, str) or not thinking.strip():
            return "action='think' requires non-empty 'thinking' string"
        tools = parsed.get("tools")
        if not isinstance(tools, list):
            return "action='think' requires 'tools' array"
    else:
        if "thinking" in parsed:
            return "action='noop' must not include 'thinking'"
        if "tools" in parsed:
            return "action='noop' must not include 'tools'"
    return None


# ---------------------------------------------------------------------------
# Target assistant index helper
# ---------------------------------------------------------------------------


def _detect_split_speech(trace: dict[str, Any]) -> dict[str, Any] | None:
    """Read the split-speech detection result saved on the trace.

    The trace builder records ``split_speech_detected`` based on whether
    VAD emitted more than one ``input_audio_buffer.speech_started`` (or
    more than one final transcription) within a single audio send.
    When set, SFT sample construction is skipped — the trace is still
    saved so the split can be inspected.
    """
    detected = trace.get("split_speech_detected")
    if isinstance(detected, dict):
        return detected
    return None


def _target_assistant_index(row: dict[str, Any], conversations: list[dict[str, Any]]) -> int | None:
    idx = row.get("target_assistant_index")
    if isinstance(idx, int) and 0 <= idx < len(conversations) and _role(conversations[idx]) == "assistant":
        return idx
    current_user_idx = row.get("current_user_index")
    if not isinstance(current_user_idx, int):
        current_user_idx = None
        for i in range(len(conversations) - 1, -1, -1):
            if _role(conversations[i]) == "user":
                current_user_idx = i
                break
    if current_user_idx is None:
        return None
    candidate = None
    for i in range(current_user_idx + 1, len(conversations)):
        if _role(conversations[i]) != "assistant":
            continue
        candidate = i
        if _content(conversations[i]).strip():
            return i
    return candidate


# ---------------------------------------------------------------------------
# Thinking SFT samples
# ---------------------------------------------------------------------------


def build_heartbeat_thinking_samples(row: dict[str, Any], trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Build thinking SFT samples from the trace.

    Each completed heartbeat block produces one sample:

    * Input: ``system`` + ``user`` messages that the runtime sent to the
      Heartbeat LLM (``input_messages`` field of the trace entry).
    * Output: the raw JSON response (``raw_response`` field).

    The sample is structured for audio-in model training:

    * ``audios`` = history_audio_paths + [segment_audio_path]
    * User messages in conversation history are replaced with ``<audio>``
    * The current fragment's ``<asr>`` tag is replaced with ``<audio>``

    Samples are filtered to only include blocks where:

    * ``status == "completed"``
    * ``raw_response`` is a non-empty string
    * ``input_messages`` is a non-empty list
    * The raw response passes ``_validate_thinking_response``
    """
    samples: list[dict[str, Any]] = []
    history_audio_paths: list[str] = list(row.get("history_audio_paths") or [])

    if _detect_split_speech(trace) is not None:
        return samples

    for entry in trace.get("heartbeat_thinkings") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "completed":
            continue
        raw_response = entry.get("raw_response")
        input_messages = entry.get("input_messages")
        if not isinstance(raw_response, str) or not raw_response.strip():
            continue
        if not isinstance(input_messages, list) or not input_messages:
            continue

        validation_error = _validate_thinking_response(raw_response)
        if validation_error is not None:
            continue

        conversations: list[dict[str, str]] = []
        original_fragment_text: str | None = None
        for message in input_messages:
            if not isinstance(message, dict):
                continue
            role = _role(message)
            if role not in {"system", "user"}:
                continue
            value = _content(message)
            if role == "user":
                new_value, original = _replace_asr_tags_with_audio(value)
                if original is not None:
                    original_fragment_text = original
                value = new_value
            conversations.append({"from": role, "value": value})

        if not conversations:
            continue
        conversations.append({"from": "assistant", "value": raw_response.strip()})

        audio_segment_path = entry.get("audio_segment_path")
        audios = list(history_audio_paths)
        if audio_segment_path:
            audios.append(audio_segment_path)

        samples.append({
            "task": "heartbeat_thinking",
            "conversations": conversations,
            "audios": audios,
            "meta": {
                "dataset_name": row.get("dataset_name"),
                "dialogue_id": row.get("dialogue_id"),
                "conversation_id": row.get("conversation_id"),
                "turn_index": row.get("turn_index"),
                "block": entry.get("block"),
                "t_ms": entry.get("t_ms"),
                "trace_path": None,
                "audio_segment_path": audio_segment_path,
                "audio_segment_sample_rate": entry.get("audio_segment_sample_rate"),
                "audio_segment_samples": entry.get("audio_segment_samples"),
                "original_fragment_text": original_fragment_text,
            },
        })
    return samples


def _replace_asr_tags_with_audio(user_text: str) -> tuple[str, str | None]:
    """Replace ALL ``<asr>...</asr>`` blocks with ``<audio>``.

    Returns ``(new_text, original_asr_text)``.  ``original_asr_text`` is
    the first ``<asr>`` block content, or ``None`` when no ``<asr>`` block
    was found.
    """
    import re
    pattern = re.compile(r"<asr>(.*?)</asr>", re.DOTALL)
    match = pattern.search(user_text)
    if match is None:
        return user_text, None
    original_asr = match.group(1)
    new_text = pattern.sub("<audio>", user_text)
    return new_text, original_asr


# ---------------------------------------------------------------------------
# Response SFT samples (with reference)
# ---------------------------------------------------------------------------


def build_response_with_reference_sample(
    row: dict[str, Any],
    trace: dict[str, Any],
    *,
    response_with_reference_client: ResponseWithReferenceClient | None = None,
    dropped_history_toolcalls: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build a response SFT sample using the Response With Reference LLM.

    The sample's input messages come from the runtime response LLM
    input messages snapshot (``response_input_messages`` in the trace).
    The output messages are produced by the LLM, which rewrites the GT
    reference messages to account for final ASR and heartbeat tool
    coverage.

    Returns ``(sample, info)`` where ``sample`` is None if the sample
    could not be built (with ``info`` explaining why).
    """
    seed_conversations = row.get("seed_conversations")
    if not isinstance(seed_conversations, list) or not seed_conversations:
        return None, {"status": "missing_seed_conversations"}
    target_idx = _target_assistant_index(row, seed_conversations)
    current_user_idx = row.get("current_user_index")
    if target_idx is None or not isinstance(current_user_idx, int):
        return None, {"status": "missing_target_turn"}
    if (trace.get("response_event") or {}).get("response_start_ms") is None:
        return None, {"status": "missing_response_start"}
    if response_with_reference_client is None:
        return None, {"status": "missing_response_with_reference_client"}

    split_info = _detect_split_speech(trace)
    if split_info is not None:
        return None, {"status": "split_speech_detected", **split_info}

    runtime_messages = trace.get("response_input_messages") or []
    if not isinstance(runtime_messages, list) or not runtime_messages:
        return None, {"status": "missing_response_input_messages"}

    runtime_current_user_idx: int | None = None
    for idx in range(len(runtime_messages) - 1, -1, -1):
        if _role(runtime_messages[idx]) == "user":
            runtime_current_user_idx = idx
            break
    if runtime_current_user_idx is None:
        return None, {"status": "missing_current_user_in_runtime_messages"}

    scoped = [msg for msg in seed_conversations[: target_idx + 1] if isinstance(msg, dict)]
    reference_messages = list(scoped)
    current_user_idx_in_reference = current_user_idx
    if not (
        0 <= current_user_idx_in_reference < len(reference_messages)
        and _role(reference_messages[current_user_idx_in_reference]) == "user"
    ):
        current_user_idx_in_reference = None
        for idx in range(len(reference_messages) - 1, -1, -1):
            if _role(reference_messages[idx]) == "user":
                current_user_idx_in_reference = idx
                break
    if current_user_idx_in_reference is None:
        return None, {"status": "missing_current_user_for_response_with_reference"}

    try:
        parsed, response_with_reference_meta = response_with_reference_client.build(
            history_messages=reference_messages[:current_user_idx_in_reference],
            seed_current_user_text=str(row.get("current_user_text") or ""),
            final_asr_transcript=str((trace.get("asr") or {}).get("transcript") or ""),
            current_turn_messages=reference_messages[current_user_idx_in_reference + 1 :],
            tools=row.get("tools") or [],
            heartbeat_context=trace.get("heartbeat_context") or [],
            target_tool_trace=trace.get("target_tool_trace") or [],
            dropped_history_toolcalls=dropped_history_toolcalls,
        )
        llm_messages = [
            normalized
            for message in parsed.get("messages") or []
            if (normalized := _normalize_response_with_reference_message(message)) is not None
        ]
        if not llm_messages:
            return None, {
                "status": "empty_response_with_reference_messages",
                "asr_equivalent": bool(parsed.get("asr_equivalent")),
                "reference_adjusted": bool(parsed.get("reference_adjusted")),
                "reason": str(parsed.get("reason") or ""),
                "heartbeat_coverage": parsed.get("heartbeat_coverage") if isinstance(parsed.get("heartbeat_coverage"), list) else [],
                **response_with_reference_meta,
            }
        validation_error = _validate_response_messages(
            llm_messages,
            available_tool_names=_schema_tool_names(row.get("tools") or []),
        )
        if validation_error is not None:
            return None, {
                "status": "invalid_response_with_reference_messages",
                "error": validation_error,
                "asr_equivalent": bool(parsed.get("asr_equivalent")),
                "reference_adjusted": bool(parsed.get("reference_adjusted")),
                "reason": str(parsed.get("reason") or ""),
                "heartbeat_coverage": parsed.get("heartbeat_coverage") if isinstance(parsed.get("heartbeat_coverage"), list) else [],
                **response_with_reference_meta,
            }
        response_with_reference_info: dict[str, Any] = {
            "status": "ok",
            "applied": True,
            "asr_equivalent": bool(parsed.get("asr_equivalent")),
            "reference_adjusted": bool(parsed.get("reference_adjusted")),
            "reason": str(parsed.get("reason") or ""),
            "heartbeat_coverage": parsed.get("heartbeat_coverage") if isinstance(parsed.get("heartbeat_coverage"), list) else [],
            "returned_messages": len(llm_messages),
            **response_with_reference_meta,
        }
    except Exception as exc:
        return None, {
            "status": "response_with_reference_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    runtime_sample_messages = _drop_history_toolcall_pairs_for_sft(
        [msg for msg in runtime_messages[: runtime_current_user_idx + 1] if isinstance(msg, dict)],
        dropped_history_toolcalls,
    )
    runtime_sample_current_user_idx: int | None = None
    for idx in range(len(runtime_sample_messages) - 1, -1, -1):
        if _role(runtime_sample_messages[idx]) == "user":
            runtime_sample_current_user_idx = idx
            break
    if runtime_sample_current_user_idx is None:
        return None, {"status": "missing_current_user_after_history_toolcall_filter"}

    conversations: list[dict[str, Any]] = []
    for idx, message in enumerate(runtime_sample_messages):
        role = _role(message)
        if role == "system":
            append_response_sft_message(conversations, message, tools=row.get("tools") or [])
        elif role == "user":
            if idx == runtime_sample_current_user_idx:
                append_response_sft_message(conversations, message)
            else:
                append_response_sft_message(conversations, message, user_value="<audio>")
        elif role == "assistant":
            append_response_sft_message(conversations, message)
        elif role == "tool":
            append_response_sft_message(conversations, message)
    for message in llm_messages:
        append_response_sft_message(conversations, message)

    audio_refs = list(row.get("history_audio_paths") or []) + [row.get("current_audio_path")]
    sample = {
        "task": "heartbeat_response",
        "tools": row.get("tools") or [],
        "conversations": conversations,
        "audios": [audio for audio in audio_refs if audio],
        "meta": {
            "dataset_name": row.get("dataset_name"),
            "dialogue_id": row.get("dialogue_id"),
            "conversation_id": row.get("conversation_id"),
            "turn_index": row.get("turn_index"),
            "response_with_reference": {
                "source": "gt_seed",
                "response_generation": "disabled",
                "target_tool_trace": trace.get("target_tool_trace") or [],
                "final_asr_transcript": str((trace.get("asr") or {}).get("transcript") or ""),
                "result": response_with_reference_info,
            },
            "trace_path": None,
        },
    }
    return sample, {
        "status": "ok",
        "conversation_messages": len(conversations),
        "response_with_reference": response_with_reference_info,
    }
