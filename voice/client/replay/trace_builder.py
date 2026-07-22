"""Build a structured ``heartbeat_replay_trace.v1`` trace from raw events.

The trace is the single source of truth for downstream SFT sample
construction.  It captures:

* The original seed conversation (``conversation_gt``).
* Per-block heartbeat thinking entries (``heartbeat_thinkings``).
* The response LLM input messages snapshot (``response_input_messages``).
* Tool attempt/result events with virtual-time bookkeeping.
* Trigger judgements and tool summary statistics.

The builder is pure: given a row and a list of event records, it returns
a trace dict.  No I/O, no WebSocket calls.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from distillation_replay.response_with_reference import has_effective_tool_result
from distillation_replay.tool_latency import stable_virtual_tool_latency_ms
from distillation_replay.tool_trigger_judge import ToolTriggerJudgeClient
from handlers.heartbeat_interaction.history_formatter import (
    load_heartbeat_response_prompt_template,
    normalize_heartbeat_response_tool_payload,
    parse_predict_output,
)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _json_or_text(value: Any) -> Any:
    """Parse a JSON string, otherwise return the value unchanged."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _stable_latency_ms(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    min_ms: int,
    max_ms: int,
    salt: str = "",
) -> int:
    """Deterministic simulated tool latency based on the replay tier policy.

    ``min_ms`` and ``max_ms`` are retained for compatibility with older runner
    arguments.  Current replay uses stable tool-name tiers.
    """
    return stable_virtual_tool_latency_ms(
        tool_name=tool_name,
        arguments=arguments,
        salt=salt,
    )


def _looks_like_error_result(value: Any) -> bool:
    """Heuristic: does this tool result string look like an error?"""
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    return (
        lowered.startswith("error:")
        or lowered.startswith("error executing tool")
        or "llm mock did not produce a result" in lowered
        or "tool_error" in lowered
    )


def _has_effective_tool_result(tool: dict[str, Any]) -> bool:
    """Check if a tool has an effective (non-error, non-empty) completed result."""
    if tool.get("status") != "completed":
        return False
    return has_effective_tool_result(tool.get("result"))


def _detect_split_speech(raw_counts: dict[str, int]) -> dict[str, Any] | None:
    """Detect when VAD splits one audio send into multiple speech segments.

    Returns a dict with split details if detected, else ``None``.  The
    trace records this so downstream consumers can know why SFT samples
    were skipped.
    """
    speech_started_count = int(raw_counts.get("input_audio_buffer.speech_started") or 0)
    transcription_completed_count = int(
        raw_counts.get("conversation.item.input_audio_transcription.completed") or 0
    )
    if speech_started_count > 1 or transcription_completed_count > 1:
        return {
            "speech_started_count": speech_started_count,
            "transcription_completed_count": transcription_completed_count,
        }
    return None


def _trace_tool_stats(trace: dict[str, Any]) -> dict[str, Any]:
    """Compute summary statistics about tools in the trace."""
    attempts = trace.get("tool_attempt_events") or []
    tool_events = trace.get("tool_events") or []
    response_start_ms = (trace.get("response_event") or {}).get("response_start_ms")
    raw_tool_prediction_count = 0
    raw_tool_prediction_without_tool_call_count = 0
    raw_tool_prediction_without_tool_call_before_response_count = 0
    raw_tool_prediction_without_tool_call_after_response_count = 0
    for entry in trace.get("heartbeat_events") or []:
        raw_response = entry.get("raw_response")
        parsed = parse_predict_output(raw_response) if isinstance(raw_response, str) else None
        predicted_tools = parsed.get("tools") if isinstance(parsed, dict) else []
        if not isinstance(predicted_tools, list):
            predicted_tools = []
        raw_tool_prediction_count += len(predicted_tools)
        if predicted_tools and not entry.get("tool_calls"):
            dropped_count = len(predicted_tools)
            raw_tool_prediction_without_tool_call_count += dropped_count
            response_wall_ms = None
            for wall_event in entry.get("wall_events") or []:
                if wall_event.get("event") == "response":
                    response_wall_ms = wall_event.get("client_elapsed_ms")
                    break
            if (
                isinstance(response_start_ms, int)
                and isinstance(response_wall_ms, int)
                and response_wall_ms > response_start_ms
            ):
                raw_tool_prediction_without_tool_call_after_response_count += dropped_count
            else:
                raw_tool_prediction_without_tool_call_before_response_count += dropped_count
    visible_completed: list[dict[str, Any]] = []
    visible_error: list[dict[str, Any]] = []
    visible_pending: list[dict[str, Any]] = []
    for entry in trace.get("heartbeat_context") or []:
        for tool in entry.get("tools") or []:
            status = tool.get("status")
            if status == "completed":
                visible_completed.append(tool)
            elif status == "error":
                visible_error.append(tool)
            else:
                visible_pending.append(tool)

    result_error_events = [
        tool
        for tool in tool_events
        if tool.get("status") == "error" or _looks_like_error_result(tool.get("result"))
    ]
    effective_events = [tool for tool in tool_events if _has_effective_tool_result(tool)]
    effective_visible = [tool for tool in visible_completed if _has_effective_tool_result(tool)]
    return {
        "tool_attempt_count": len(attempts),
        "schema_error_tool_attempt_count": sum(1 for item in attempts if item.get("status") == "error"),
        "raw_tool_prediction_count": raw_tool_prediction_count,
        "raw_tool_prediction_without_tool_call_count": raw_tool_prediction_without_tool_call_count,
        "raw_tool_prediction_without_tool_call_before_response_count": (
            raw_tool_prediction_without_tool_call_before_response_count
        ),
        "raw_tool_prediction_without_tool_call_after_response_count": (
            raw_tool_prediction_without_tool_call_after_response_count
        ),
        "tool_event_count": len(tool_events),
        "completed_tool_event_count": sum(1 for item in tool_events if item.get("status") == "completed"),
        "tool_result_error_count": len(result_error_events),
        "effective_tool_result_count": len(effective_events),
        "visible_completed_tool_count": len(visible_completed),
        "visible_error_tool_count": len(visible_error),
        "visible_pending_tool_count": len(visible_pending),
        "effective_visible_tool_result_count": len(effective_visible),
        "target_tool_reference_count": len(trace.get("target_tool_trace") or []),
    }


# ---------------------------------------------------------------------------
# Event accumulation — walk the raw event stream and group by block
# ---------------------------------------------------------------------------


def _accumulate_events(
    records: list[dict[str, Any]],
    row: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Walk raw event records and accumulate per-block state.

    Returns a dict with keys:
    - ``transcription_ms``: wall-clock ms when final ASR completed.
    - ``transcript``: final ASR transcript text.
    - ``response_input_messages``: first messages snapshot from
      ``response.input_messages`` event. Later events may be emitted by
      tool-loop follow-up LLM calls after the temporary HeartbeatContext has
      been finalized, so they must not replace the response-start input.
    - ``response_input_messages_ms``: response_start_ms from the same event.
    - ``heartbeat_by_block``: dict[block_idx] -> per-block accumulator.
    - ``tool_calls``: dict[call_id] -> tool_call dict.
    - ``tool_attempts``: list of tool attempt dicts.
    - ``raw_counts``: dict[event_type] -> count.
    """
    transcription_ms: int | None = None
    transcript = ""
    heartbeat_by_block: dict[int, dict[str, Any]] = {}
    tool_calls: dict[str, dict[str, Any]] = {}
    tool_attempts: list[dict[str, Any]] = []
    raw_counts: dict[str, int] = {}
    response_input_messages: list[dict[str, Any]] = []
    response_input_messages_ms: int | None = None

    for record in records:
        event = record.get("event") or {}
        etype = event.get("type")
        if etype:
            raw_counts[etype] = raw_counts.get(etype, 0) + 1
        elapsed = int(record.get("client_elapsed_ms") or 0)
        if etype == "conversation.item.input_audio_transcription.completed":
            transcription_ms = elapsed
            transcript = str(event.get("transcript") or "")
            continue
        if etype == "response.input_messages":
            messages = event.get("messages")
            if isinstance(messages, list) and not response_input_messages:
                response_input_messages = messages
                response_input_messages_ms = event.get("response_start_ms")
            continue
        if etype != "heartbeat_thinking":
            continue
        block_idx = event.get("block_idx")
        if not isinstance(block_idx, int):
            continue
        virtual_ms = (block_idx + 1) * args.heartbeat_block_duration_ms
        hb = heartbeat_by_block.setdefault(
            block_idx,
            {
                "block_idx": block_idx,
                "created_at_ms": virtual_ms,
                "wall_events": [],
                "thinking": "",
                "tool_calls": [],
            },
        )
        hb["wall_events"].append({
            "event": event.get("event"),
            "client_elapsed_ms": elapsed,
            "ts_ms": event.get("ts_ms"),
        })
        hevent = event.get("event")
        if hevent == "input_messages":
            messages = event.get("messages")
            hb["input_messages"] = messages if isinstance(messages, list) else []
            hb["current_fragment"] = event.get("current_fragment") or ""
            if event.get("audio_segment_path"):
                hb["audio_segment_path"] = event.get("audio_segment_path")
                hb["audio_segment_sample_rate"] = event.get("audio_segment_sample_rate")
                hb["audio_segment_samples"] = event.get("audio_segment_samples")
        elif hevent == "thinking" and event.get("thinking"):
            hb["action"] = "think"
            hb["thinking"] = str(event.get("thinking"))
        elif hevent == "response":
            hb["action"] = "think"
            hb["raw_response"] = event.get("text")
        elif hevent == "no_think":
            if "action" not in hb:
                hb["action"] = "noop"
        elif hevent == "tool_call":
            hb["action"] = "think"
            call_id = str(event.get("tool_call_id") or f"heartbeat_{block_idx}_{len(tool_calls)}")
            arguments = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
            event_status = str(event.get("status") or "pending")
            if event_status == "error":
                tool_call = {
                    "tool_call_id": call_id,
                    "status": "error",
                    "reason": event.get("reason") or "",
                    "name": str(event.get("tool_name") or ""),
                    "arguments": arguments,
                    "block_idx": block_idx,
                    "dispatched_at_ms": virtual_ms,
                    "tool_completed_at_ms": virtual_ms,
                    "wall_dispatched_at_ms": elapsed,
                    "created_at_ms": virtual_ms,
                    "wall_event_ms": elapsed,
                    "current_fragment": event.get("current_fragment") or "",
                }
                tool_calls[call_id] = tool_call
                hb["tool_calls"].append(tool_call)
                tool_attempts.append(tool_call)
                continue
            latency_ms = _stable_latency_ms(
                tool_name=str(event.get("tool_name") or ""),
                arguments=arguments,
                min_ms=args.tool_mock_simulated_latency_min_ms,
                max_ms=args.tool_mock_simulated_latency_max_ms,
                salt=str(call_id),
            )
            tool_call = {
                "tool_call_id": call_id,
                "name": str(event.get("tool_name") or ""),
                "arguments": arguments,
                "block_idx": block_idx,
                "dispatched_at_ms": virtual_ms,
                "simulated_latency_ms": latency_ms,
                "tool_completed_at_ms": virtual_ms + latency_ms,
                "wall_dispatched_at_ms": elapsed,
                "status": "pending",
                "current_fragment": event.get("current_fragment") or "",
            }
            tool_calls[call_id] = tool_call
            hb["tool_calls"].append(tool_call)
            tool_call["created_at_ms"] = virtual_ms
            tool_call["wall_event_ms"] = elapsed
            tool_attempts.append(tool_call)
        elif hevent == "tool_result":
            hb["action"] = "think"
            call_id = str(event.get("tool_call_id") or "")
            tool_call = tool_calls.get(call_id)
            if tool_call is None:
                arguments = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
                latency_ms = _stable_latency_ms(
                    tool_name=str(event.get("tool_name") or ""),
                    arguments=arguments,
                    min_ms=args.tool_mock_simulated_latency_min_ms,
                    max_ms=args.tool_mock_simulated_latency_max_ms,
                    salt=str(call_id or block_idx),
                )
                tool_call = {
                    "tool_call_id": call_id or f"heartbeat_{block_idx}_{len(tool_calls)}",
                    "name": str(event.get("tool_name") or ""),
                    "arguments": arguments,
                    "block_idx": block_idx,
                    "dispatched_at_ms": virtual_ms,
                    "simulated_latency_ms": latency_ms,
                    "tool_completed_at_ms": virtual_ms + latency_ms,
                }
                tool_calls[tool_call["tool_call_id"]] = tool_call
                hb["tool_calls"].append(tool_call)
            tool_call["status"] = str(event.get("status") or "completed")
            tool_call["result"] = _json_or_text(event.get("result"))
            tool_call["wall_completed_at_ms"] = elapsed
            for attempt in reversed(tool_attempts):
                if attempt.get("tool_call_id") == tool_call.get("tool_call_id"):
                    attempt["status"] = tool_call["status"]
                    break

    return {
        "transcription_ms": transcription_ms,
        "transcript": transcript,
        "response_input_messages": response_input_messages,
        "response_input_messages_ms": response_input_messages_ms,
        "heartbeat_by_block": heartbeat_by_block,
        "tool_calls": tool_calls,
        "tool_attempts": tool_attempts,
        "raw_counts": raw_counts,
    }


# ---------------------------------------------------------------------------
# Trigger judgement
# ---------------------------------------------------------------------------


def _build_trigger_judgements(
    *,
    row: dict[str, Any],
    tool_attempts: list[dict[str, Any]],
    heartbeat_entries: list[dict[str, Any]],
    trigger_judge: ToolTriggerJudgeClient | None,
) -> list[dict[str, Any]]:
    """Build trigger judgement entries for each tool attempt."""
    trigger_judgements: list[dict[str, Any]] = []
    for attempt in tool_attempts:
        judgement = {
            "status": "skipped_no_tool_trigger_judge",
            "stable_trigger": None,
            "semantic_reasonable": None,
            "schema_exact": None,
        }
        if trigger_judge is not None:
            try:
                parsed, judge_meta = trigger_judge.judge(
                    conversation_history=row.get("history_messages") or [],
                    current_fragment=str(attempt.get("current_fragment") or ""),
                    current_turn_state={"thinking_entries": heartbeat_entries},
                    available_tools=row.get("tools") or [],
                    attempted_tool={
                        "name": attempt.get("name"),
                        "arguments": attempt.get("arguments") or {},
                        "status": attempt.get("status"),
                        "reason": attempt.get("reason"),
                    },
                )
                judgement = {
                    "status": "ok",
                    "stable_trigger": bool(parsed.get("stable_trigger")),
                    "semantic_reasonable": bool(parsed.get("semantic_reasonable")),
                    "schema_exact": bool(parsed.get("schema_exact")),
                    "matched_tool_name": parsed.get("matched_tool_name"),
                    "reason": str(parsed.get("reason") or ""),
                    **judge_meta,
                }
            except Exception as exc:
                judgement = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "stable_trigger": None,
                    "semantic_reasonable": None,
                    "schema_exact": None,
                }
        trigger_judgements.append({
            "attempt": attempt,
            "judgement": judgement,
        })
    return trigger_judgements


# ---------------------------------------------------------------------------
# Main entrypoint — build the full trace dict
# ---------------------------------------------------------------------------


def build_replay_trace(
    row: dict[str, Any],
    records: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    trigger_judge: ToolTriggerJudgeClient | None = None,
) -> dict[str, Any]:
    """Build a structured trace from raw event records.

    Parameters
    ----------
    row:
        The seed row dict (contains dataset_name, dialogue_id, etc.).
    records:
        List of ``{"client_elapsed_ms": int, "event": dict}`` records
        from the WebSocket event stream.
    args:
        Namespace with ``heartbeat_block_duration_ms``,
        ``tool_mock_simulated_latency_min_ms``,
        ``tool_mock_simulated_latency_max_ms``, ``speed``.
    trigger_judge:
        Optional ``ToolTriggerJudgeClient`` for judging tool trigger
        stability.

    Returns
    -------
    dict
        A ``heartbeat_replay_trace.v1`` trace dict.
    """
    acc = _accumulate_events(records, row, args)
    wall_transcription_ms = acc["transcription_ms"]
    virtual_response_start_ms = getattr(args, "virtual_response_start_ms", None)
    transcription_ms = (
        int(virtual_response_start_ms)
        if wall_transcription_ms is not None and virtual_response_start_ms is not None
        else wall_transcription_ms
    )
    transcript = acc["transcript"]
    heartbeat_by_block = acc["heartbeat_by_block"]
    tool_calls = acc["tool_calls"]
    tool_attempts = acc["tool_attempts"]
    raw_counts = acc["raw_counts"]
    response_input_messages = acc["response_input_messages"]
    response_input_messages_ms = acc["response_input_messages_ms"]

    response_start_ms = transcription_ms
    heartbeat_entries: list[dict[str, Any]] = []
    heartbeat_thinkings: list[dict[str, Any]] = []
    response_prompt_template = load_heartbeat_response_prompt_template()
    all_heartbeat_blocks = sorted(heartbeat_by_block.values(), key=lambda item: item["created_at_ms"])

    for hb in all_heartbeat_blocks:
        if not (hb.get("thinking") or hb.get("tool_calls") or isinstance(hb.get("input_messages"), list)):
            continue
        thinking_tools: list[dict[str, Any]] = []
        for tool in hb.get("tool_calls") or []:
            tool_item = {
                "name": tool.get("name"),
                "arguments": tool.get("arguments") or {},
                "status": tool.get("status") or "pending",
            }
            if tool.get("result") not in (None, ""):
                tool_item["result"] = tool.get("result")
            if tool.get("reason"):
                tool_item["error"] = tool.get("reason")
            if tool.get("dispatched_at_ms") is not None:
                tool_item["dispatched_at_ms"] = tool.get("dispatched_at_ms")
            if tool.get("tool_completed_at_ms") is not None:
                tool_item["completed_at_ms"] = tool.get("tool_completed_at_ms")
            if tool.get("simulated_latency_ms") is not None:
                tool_item["simulated_latency_ms"] = tool.get("simulated_latency_ms")
            thinking_tools.append(tool_item)
        thinking_entry = {
            "block": hb["block_idx"],
            "t_ms": hb["created_at_ms"],
            "status": (
                "completed"
                if hb.get("action") or hb.get("thinking") or thinking_tools
                else "parse_error"
            ),
            "fragment": hb.get("current_fragment") or "",
            "action": hb.get("action") or ("think" if hb.get("thinking") or thinking_tools else "noop"),
            "thinking": hb.get("thinking") or "",
            "tools": thinking_tools,
        }
        if isinstance(hb.get("input_messages"), list):
            thinking_entry["input_messages"] = hb["input_messages"]
        if hb.get("audio_segment_path"):
            thinking_entry["audio_segment_path"] = hb["audio_segment_path"]
            thinking_entry["audio_segment_sample_rate"] = hb.get("audio_segment_sample_rate")
            thinking_entry["audio_segment_samples"] = hb.get("audio_segment_samples")
        if hb.get("raw_response") not in (None, ""):
            thinking_entry["raw_response"] = hb.get("raw_response")
        heartbeat_thinkings.append(thinking_entry)

    visible_heartbeat_blocks = (
        all_heartbeat_blocks
        if response_start_ms is not None
        else []
    )
    for hb in visible_heartbeat_blocks:
        if response_start_ms is not None and hb["created_at_ms"] > response_start_ms:
            continue
        visible_tools: list[dict[str, Any]] = []
        for tool in hb.get("tool_calls") or []:
            tool_public = {
                "name": tool.get("name"),
                "arguments": tool.get("arguments") or {},
                "status": tool.get("status") or "pending",
            }
            if tool.get("status") == "error":
                tool_public["result"] = tool.get("result") or f"Error: {tool.get('reason') or 'tool_error'}"
                normalized_tool = normalize_heartbeat_response_tool_payload(tool_public, response_prompt_template)
                if normalized_tool is not None:
                    visible_tools.append(normalized_tool)
                continue
            completed_at = tool.get("tool_completed_at_ms")
            if response_start_ms is not None and isinstance(completed_at, int) and completed_at <= response_start_ms and tool.get("status") == "completed":
                if tool.get("result") not in (None, ""):
                    tool_public["result"] = tool.get("result")
            elif response_start_ms is not None and isinstance(completed_at, int) and completed_at > response_start_ms:
                tool_public["status"] = "pending"
            normalized_tool = normalize_heartbeat_response_tool_payload(tool_public, response_prompt_template)
            if normalized_tool is not None:
                visible_tools.append(normalized_tool)
        if hb.get("thinking") or visible_tools:
            response_entry = {
                "block": hb["block_idx"],
                "action": hb.get("action") or "think",
                "tools": visible_tools,
            }
            if hb.get("thinking"):
                response_entry["thinking"] = hb.get("thinking") or ""
            heartbeat_entries.append(response_entry)

    trigger_judgements = _build_trigger_judgements(
        row=row,
        tool_attempts=tool_attempts,
        heartbeat_entries=heartbeat_entries,
        trigger_judge=trigger_judge,
    )

    split_speech_detected = _detect_split_speech(raw_counts)

    trace = {
        "dataset_name": row.get("dataset_name"),
        "dialogue_id": row.get("dialogue_id"),
        "conversation_id": row.get("conversation_id"),
        "turn_index": row.get("turn_index"),
        "audio": {
            "current_audio_path": row.get("current_audio_path"),
            "history_audio_paths": row.get("history_audio_paths") or [],
            "send_speed": args.speed,
        },
        "asr": {
            "transcript": transcript,
            "transcription_completed_ms": transcription_ms,
            "wall_transcription_completed_ms": wall_transcription_ms,
        },
        "response_event": {
            "response_generation": "disabled",
            "response_start_ms": response_start_ms,
            "response_start_policy": "final_asr_completed",
            "response_start_source": (
                "virtual_audio_timeline"
                if wall_transcription_ms is not None and virtual_response_start_ms is not None
                else "wall_clock"
            ),
        },
        "virtual_time": {
            "heartbeat_block_duration_ms": args.heartbeat_block_duration_ms,
            "mock_tool_latency_policy": "tool_name_tiered_v1",
            "mock_tool_latency_tiers": {
                "instant": [1, 10],
                "fast": [20, 100],
                "normal": [200, 800],
                "slow": [1000, 3000],
            },
            "mock_tool_latency_min_ms": args.tool_mock_simulated_latency_min_ms,
            "mock_tool_latency_max_ms": args.tool_mock_simulated_latency_max_ms,
            "wall_clock_llm_latency_used_for_visibility": False,
            "audio_send_speed": args.speed,
        },
        "heartbeat_context": heartbeat_entries,
        "heartbeat_thinkings": heartbeat_thinkings,
        "response_input_messages": response_input_messages,
        "response_input_messages_ms": response_input_messages_ms,
        "session_state": {"subtasks": []},
        "heartbeat_events": sorted(heartbeat_by_block.values(), key=lambda item: item["created_at_ms"]),
        "heartbeat_events_shape": "debug_timeline_not_model_input",
        "tool_events": sorted(tool_calls.values(), key=lambda item: (item.get("dispatched_at_ms") or 0, item.get("tool_call_id") or "")),
        "tool_attempt_events": sorted(tool_attempts, key=lambda item: (item.get("created_at_ms") or 0, item.get("wall_event_ms") or 0)),
        "trigger_judgements": trigger_judgements,
        "input_tool_mock_examples": _tool_mock_example_stats(row),
        "target_tool_trace": row.get("target_tool_trace") or [],
        "raw_event_counts": raw_counts,
        "split_speech_detected": split_speech_detected,
    }
    trace["tool_summary"] = _trace_tool_stats(trace)
    return trace


# ---------------------------------------------------------------------------
# Helpers re-exported for the SFT sample builder
# ---------------------------------------------------------------------------


def _role(message: dict[str, Any]) -> str:
    return str(message.get("role") or message.get("from") or "")


def _content(message: dict[str, Any]) -> str:
    return str(message.get("content") if message.get("content") is not None else message.get("value") or "")


def _schema_tool_name(tool_def: dict[str, Any]) -> str:
    function = tool_def.get("function") if isinstance(tool_def.get("function"), dict) else {}
    return str(function.get("name") or tool_def.get("name") or "")


def _tool_mock_example_stats(row: dict[str, Any]) -> dict[str, Any]:
    examples_by_tool = row.get("tool_mock_examples") if isinstance(row.get("tool_mock_examples"), dict) else {}
    counts = {
        str(name): len(items)
        for name, items in examples_by_tool.items()
        if isinstance(items, list)
    }
    schema_names = [
        name
        for tool in row.get("tools") or []
        if isinstance(tool, dict) and (name := _schema_tool_name(tool))
    ]
    target_names = [
        str(item.get("name"))
        for item in row.get("target_tool_trace") or []
        if isinstance(item, dict) and item.get("name")
    ]
    return {
        "schema_tool_count": len(schema_names),
        "schema_tool_names": schema_names,
        "tool_mock_example_counts": counts,
        "schema_tools_without_mock_examples": [name for name in schema_names if counts.get(name, 0) <= 0],
        "target_tool_names": target_names,
    }
