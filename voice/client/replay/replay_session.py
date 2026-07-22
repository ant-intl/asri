"""ReplaySession — drive one seed row through a realtime server in-process.

Unlike shelling out to ``heartbeat_audio_client.py``, this class opens a
WebSocket directly, streams the audio, collects events, and writes the
structured trace + SFT samples.  No subprocess, no temp files for the
client session.

The session is a one-shot: ``run()`` opens the WebSocket, sends the
session update + history, streams the audio, waits for transcription +
drain, then closes.  All artifacts (events, trace, thinking samples,
response sample) are written under ``work_dir`` / ``log_dir``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from client.audio import load_audio_pcm
from client.replay.sft_sample_builder import (
    append_response_sft_message,
    build_heartbeat_thinking_samples,
    build_response_with_reference_sample,
)
from client.replay.trace_builder import build_replay_trace
from client.ws_session import send_history, send_session_update
from distillation_replay.response_with_reference import ResponseWithReferenceClient
from distillation_replay.tool_trigger_judge import ToolTriggerJudgeClient


def _role(message: dict[str, Any]) -> str:
    return str(message.get("role") or message.get("from") or "")


def _content(message: dict[str, Any]) -> str:
    return str(message.get("content") if message.get("content") is not None else message.get("value") or "")


def _drop_orphan_empty_assistant_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop malformed empty-assistant/tool-result history pairs.

    A few source histories have already lost the assistant ``tool_calls`` while
    retaining the following tool result. Sending that pair to replay, or later
    projecting it to response SFT, creates an empty assistant turn plus an
    orphan tool result.
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


class ReplaySession:
    """Drive one seed row through the realtime server in-process.

    Parameters
    ----------
    row:
        The seed row dict (contains current_audio_path, history_messages,
        tools, etc.).
    host:
        Realtime server host.
    port:
        Realtime server port.
    config_path:
        Path to the server YAML config (unused here, but kept for
        compatibility with the runner).
    speed:
        Audio send speed multiplier.  Must be 1.0 for replay.
    client_timeout_s:
        Seconds to wait for response.done after sending audio.
    drain_after_transcription_s:
        Seconds to keep receiving events after final ASR completes.
    heartbeat_block_duration_ms:
        Heartbeat block duration in ms (used for virtual time).
    tool_mock_simulated_latency_min_ms:
        Minimum simulated tool latency in ms.
    tool_mock_simulated_latency_max_ms:
        Maximum simulated tool latency in ms.
    work_dir:
        Directory to write per-row work files (events, trace, samples).
    log_dir:
        Directory to write per-row log files.
    idx:
        Row index (1-based) for naming files.
    response_with_reference_client:
        Optional ``ResponseWithReferenceClient`` for building response
        SFT samples with LLM-based rewriting.
    tool_trigger_judge:
        Optional ``ToolTriggerJudgeClient`` for judging tool trigger
        stability.
    """

    def __init__(
        self,
        *,
        row: dict[str, Any],
        host: str,
        port: int,
        config_path: str,
        speed: float,
        client_timeout_s: float,
        drain_after_transcription_s: float,
        heartbeat_block_duration_ms: int,
        tool_mock_simulated_latency_min_ms: int,
        tool_mock_simulated_latency_max_ms: int,
        work_dir: Path,
        log_dir: Path,
        idx: int,
        response_with_reference_client: ResponseWithReferenceClient | None,
        tool_trigger_judge: ToolTriggerJudgeClient | None,
        history_toolcall_drop_rate: float = 0.0,
    ) -> None:
        self.row = row
        self.host = host
        self.port = port
        self.config_path = config_path
        if speed != 1.0:
            raise ValueError("distillation replay audio must run at original speed 1.0")
        self.speed = speed
        self.client_timeout_s = client_timeout_s
        self.drain_after_transcription_s = drain_after_transcription_s
        self.heartbeat_block_duration_ms = heartbeat_block_duration_ms
        self.tool_mock_simulated_latency_min_ms = tool_mock_simulated_latency_min_ms
        self.tool_mock_simulated_latency_max_ms = tool_mock_simulated_latency_max_ms
        self.work_dir = work_dir
        self.log_dir = log_dir
        self.idx = idx
        self.response_with_reference_client = response_with_reference_client
        self.tool_trigger_judge = tool_trigger_judge
        self.history_toolcall_drop_rate = history_toolcall_drop_rate
        self.dropped_history_toolcalls: list[dict[str, Any]] = []

        self.events_path = work_dir / f"events_{idx:03d}.jsonl"
        self.trace_path = work_dir / f"trace_{idx:03d}.json"
        self.thinking_samples_path = work_dir / f"heartbeat_thinking_{idx:03d}.jsonl"
        self.sample_path = work_dir / f"heartbeat_response_{idx:03d}.json"
        self.real_response_path = work_dir / f"real_response_{idx:03d}.json"
        self.log_path = log_dir / f"replay_{idx:03d}.log"

    async def run(self) -> dict[str, Any]:
        """Run the replay session and return a summary dict.

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.
        """
        import websockets

        ws_url = f"ws://{self.host}:{self.port}/v1/realtime/text"
        pcm_data = await asyncio.to_thread(self._load_audio_pcm)
        chunk_bytes = 1024 * 2
        send_interval_s = (1024 / 16000) / self.speed
        silence = b"\x00" * int(16000 * 1200 / 1000) * 2
        virtual_response_start_ms = int(
            ((len(pcm_data) + len(silence)) / 2) / 16000 * 1000
        )

        start = time.monotonic()
        events: list[dict[str, Any]] = []
        response_done = asyncio.Event()
        response_input_messages_done = asyncio.Event()
        transcription_done = asyncio.Event()
        stop_receive = asyncio.Event()
        real_response_started = asyncio.Event()
        real_response_done = asyncio.Event()

        events_file = self.events_path.open("w", encoding="utf-8")
        try:
            open_timeout_s = max(
                10.0,
                min(self.client_timeout_s, float(os.getenv("HEARTBEAT_REPLAY_WS_OPEN_TIMEOUT_S", "60"))),
            )
            async with websockets.connect(
                ws_url,
                max_size=16 * 1024 * 1024,
                open_timeout=open_timeout_s,
            ) as ws:
                await self._send_session_update(ws)
                await self._send_history(ws)

                async def receive_events(ws) -> None:
                    async for raw in ws:
                        if stop_receive.is_set():
                            break
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        record = {
                            "client_elapsed_ms": int((time.monotonic() - start) * 1000),
                            "event": event,
                        }
                        events_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                        events_file.flush()
                        events.append(record)
                        etype = event.get("type", "")
                        if etype == "conversation.item.input_audio_transcription.completed":
                            transcription_done.set()
                        elif etype == "response.input_messages":
                            response_input_messages_done.set()
                        if etype == "response.created":
                            real_response_started.set()
                        if etype == "response.done":
                            response = event.get("response", {})
                            if response.get("status") == "cancelled":
                                pass  # keep waiting
                            else:
                                response_done.set()
                                real_response_done.set()
                        elif etype == "error":
                            response_done.set()
                            real_response_done.set()

                async def send_audio(ws) -> None:
                    offset = 0
                    while offset < len(pcm_data):
                        chunk = pcm_data[offset:offset + chunk_bytes]
                        offset += len(chunk)
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }))
                        await asyncio.sleep(send_interval_s)
                    for sil_offset in range(0, len(silence), chunk_bytes):
                        chunk = silence[sil_offset:sil_offset + chunk_bytes]
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }))
                        await asyncio.sleep(send_interval_s)

                receiver = asyncio.create_task(receive_events(ws))
                await send_audio(ws)

                await self._wait_for_response_input_after_transcription(
                    transcription_done=transcription_done,
                    response_input_messages_done=response_input_messages_done,
                    response_done=response_done,
                )

                try:
                    await asyncio.wait_for(response_done.wait(), timeout=self.client_timeout_s)
                except asyncio.TimeoutError:
                    pass
                finally:
                    stop_receive.set()
                    receiver.cancel()
                    try:
                        await receiver
                    except asyncio.CancelledError:
                        pass
        finally:
            events_file.close()

        self._save_audio_segments(events)

        trace = build_replay_trace(
            self.row,
            events,
            argparse.Namespace(
                heartbeat_block_duration_ms=self.heartbeat_block_duration_ms,
                tool_mock_simulated_latency_min_ms=self.tool_mock_simulated_latency_min_ms,
                tool_mock_simulated_latency_max_ms=self.tool_mock_simulated_latency_max_ms,
                speed=self.speed,
                virtual_response_start_ms=virtual_response_start_ms,
            ),
            trigger_judge=self.tool_trigger_judge,
        )
        self.trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        thinking_samples = build_heartbeat_thinking_samples(self.row, trace)
        if thinking_samples:
            self.thinking_samples_path.write_text(
                "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in thinking_samples),
                encoding="utf-8",
            )
        response_sample, response_info = build_response_with_reference_sample(
            self.row,
            trace,
            response_with_reference_client=self.response_with_reference_client,
            dropped_history_toolcalls=self.dropped_history_toolcalls,
        )
        if response_sample is not None:
            self.sample_path.write_text(json.dumps(response_sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Build a real response sample from the actual response LLM output
        real_response_sample = self._build_real_response_sample(events)
        if real_response_sample is not None:
            self.real_response_path.write_text(json.dumps(real_response_sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        return {
            "index": self.idx,
            "status": "ok",
            "dataset_name": self.row.get("dataset_name"),
            "dialogue_id": self.row.get("dialogue_id"),
            "conversation_id": self.row.get("conversation_id"),
            "turn_index": self.row.get("turn_index"),
            "events_path": str(self.events_path),
            "trace_path": str(self.trace_path),
            "thinking_sample_path": str(self.thinking_samples_path) if thinking_samples else None,
            "thinking_sample_count": len(thinking_samples),
            "response_sample_path": str(self.sample_path) if response_sample is not None else None,
            "real_response_sample_path": str(self.real_response_path) if real_response_sample is not None else None,
            "response_with_reference": response_info,
        }

    def _load_audio_pcm(self) -> bytes:
        audio_path = Path(self.row["current_audio_path"])
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(audio_path),
            "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1",
        ]
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout

    def _build_real_response_sample(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Build a real response sample from the actual response LLM output.

        Extracts the response LLM output from the event stream and builds
        a ShareGPT-style sample that mirrors the runtime response.  This
        is the "real" response trajectory — the actual LLM call output,
        not the response-with-reference rewrite.
        """
        # Find response.created and response.done events
        response_created_event: dict[str, Any] | None = None
        response_done_event: dict[str, Any] | None = None
        text_parts: list[str] = []
        in_response = False

        for record in events:
            event = record.get("event") or {}
            etype = event.get("type", "")
            if etype == "response.created":
                response_created_event = event
                in_response = True
            elif etype == "response.done":
                response_done_event = event
                in_response = False
            elif in_response and etype == "response.output_audio_transcript.done":
                transcript = event.get("transcript", "")
                if transcript:
                    text_parts.append(transcript)
            elif in_response and etype == "response.output_text.delta":
                delta = event.get("delta", "")
                if delta:
                    text_parts.append(delta)

        if response_created_event is None:
            return None

        # Build the real response sample
        full_text = "".join(text_parts)
        conversations: list[dict[str, Any]] = []
        # Add system message if available
        system_content = self.row.get("system_prompt") or ""
        if system_content:
            append_response_sft_message(
                conversations,
                {"role": "system", "content": system_content},
                tools=self.row.get("tools") or [],
            )
        # Add history messages
        for msg in self.row.get("history_messages") or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            if role == "user":
                append_response_sft_message(conversations, msg, user_value="<audio>")
            elif role in {"assistant", "tool"}:
                append_response_sft_message(conversations, msg)
        # Add current user turn (audio)
        conversations.append({"from": "user", "value": "<audio>"})
        # Add the real response
        conversations.append({"from": "assistant", "value": full_text})

        return {
            "task": "heartbeat_response_real",
            "tools": self.row.get("tools") or [],
            "conversations": conversations,
            "audios": list(self.row.get("history_audio_paths") or []) + [self.row.get("current_audio_path")],
            "meta": {
                "dataset_name": self.row.get("dataset_name"),
                "dialogue_id": self.row.get("dialogue_id"),
                "conversation_id": self.row.get("conversation_id"),
                "turn_index": self.row.get("turn_index"),
                "response_created_event": response_created_event,
                "response_done_event": response_done_event,
                "full_response_text": full_text,
            },
        }

    def _save_audio_segments(self, events: list[dict[str, Any]]) -> None:
        """Persist audio segments shipped with ``input_messages`` events.

        The server emits a ``heartbeat_thinking`` event with
        ``event="input_messages"`` for each HeartBeat block in replay mode.
        When the shared audio segment buffer is configured, the event also
        carries ``audio_segment_b64`` (base64-encoded int16 PCM),
        ``audio_segment_sample_rate``, and ``audio_segment_samples``.

        This method decodes each segment, writes it to
        ``work_dir/audio_segment_{idx}_block{block_idx}.pcm``, and mutates the
        event in-place to replace the bulky ``audio_segment_b64`` field with a
        lightweight ``audio_segment_path`` pointer.  Downstream trace and SFT
        builders read the path to reference the segment file.
        """
        import base64

        for record in events:
            event = record.get("event") or {}
            if event.get("type") != "heartbeat_thinking":
                continue
            if event.get("event") != "input_messages":
                continue
            b64 = event.get("audio_segment_b64")
            if not b64:
                continue
            block_idx = event.get("block_idx")
            try:
                pcm_bytes = base64.b64decode(b64)
            except Exception:
                continue
            seg_path = self.work_dir / f"audio_segment_{self.idx:03d}_block{block_idx}.pcm"
            seg_path.write_bytes(pcm_bytes)
            event["audio_segment_path"] = str(seg_path)
            event["audio_segment_sample_rate"] = event.get("audio_segment_sample_rate")
            event["audio_segment_samples"] = event.get("audio_segment_samples")
            event.pop("audio_segment_b64", None)

    async def _send_session_update(self, ws) -> None:
        await send_session_update(ws, modalities=["text"])

    async def _send_history(self, ws) -> None:
        history_payload = self._build_history_payload()
        await send_history(
            ws,
            history_payload=history_payload,
            trace_level="replay",
            disable_response_generation=False,
        )

    async def _wait_for_response_input_after_transcription(
        self,
        *,
        transcription_done: asyncio.Event,
        response_input_messages_done: asyncio.Event,
        response_done: asyncio.Event,
    ) -> None:
        """Wait for the response input snapshot after final ASR.

        ``response.input_messages`` is the replay artifact used to build the
        response SFT sample.  Waiting on that concrete event avoids losing the
        snapshot when server-side event delivery is slightly delayed, while
        still bounding the wait with the existing drain timeout.
        """
        try:
            await asyncio.wait_for(transcription_done.wait(), timeout=30.0)
            pending_wait_s = float(os.getenv("HEARTBEAT_REPLAY_PENDING_TOOL_WAIT_TIMEOUT_S", "30"))
            response_input_timeout_s = max(
                self.drain_after_transcription_s,
                min(self.client_timeout_s, pending_wait_s + 5.0),
            )
            if response_input_timeout_s > 0 and not response_input_messages_done.is_set():
                try:
                    await asyncio.wait_for(
                        response_input_messages_done.wait(),
                        timeout=response_input_timeout_s,
                    )
                except asyncio.TimeoutError:
                    pass
            response_done.set()
        except asyncio.TimeoutError:
            pass


    def _build_history_payload(self) -> dict[str, Any]:
        row = self.row
        messages: list[dict[str, Any]] = []
        extra_parts: list[str] = []
        for message in row.get("history_messages") or []:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "system":
                continue
            messages.append(message)

        # Apply random toolcall dropping to simulate heartbeat cover
        if self.history_toolcall_drop_rate > 0 and messages:
            import random
            rng = random.Random(hash((row.get("conversation_id"), row.get("turn_index"), self.idx)))
            messages = self._maybe_drop_history_toolcalls(messages, self.history_toolcall_drop_rate, rng)
        messages = _drop_orphan_empty_assistant_tool_results(messages)

        row_extra = row.get("extra_instructions")
        if isinstance(row_extra, str) and row_extra.strip():
            extra_parts.append(row_extra.strip())
        payload = {
            "messages": messages,
            "audio_paths": row.get("history_audio_paths") or [],
            "tools": row.get("tools") or [],
            "tool_mock_examples": row.get("tool_mock_examples") or {},
            "target_tool_trace": row.get("target_tool_trace") or [],
            "extra_instructions": "\n\n".join(extra_parts),
        }
        return payload

    def _maybe_drop_history_toolcalls(
        self,
        messages: list[dict[str, Any]],
        drop_rate: float,
        rng: Any,
    ) -> list[dict[str, Any]]:
        """Randomly drop tool_calls from history turns to simulate heartbeat cover.

        For each assistant message that has ``tool_calls``, independently decide
        whether to "cover" it (i.e. simulate the case where heartbeat already
        completed the tool call, so the response doesn't re-emit it).  When
        covered, the assistant tool-call turn and the corresponding ``tool``
        result messages are removed as a pair. Empty assistant messages are not
        kept as placeholder turns.

        Dropped toolcall info is recorded in ``self.dropped_history_toolcalls``
        for the response-with-reference LLM to judge whether to re-emit.
        """
        if drop_rate <= 0:
            return messages

        # Collect tool_call_ids to drop, along with the full toolcall info
        dropped_ids: set[str] = set()
        for message in messages:
            if not isinstance(message, dict):
                continue
            if _role(message) != "assistant":
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list) or not tool_calls:
                continue
            # Decide whether to drop this assistant's tool_calls
            if rng.random() < drop_rate:
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    call_id = call.get("id") or call.get("call_id") or call.get("tool_call_id")
                    if call_id:
                        dropped_ids.add(str(call_id))
                        # Record dropped toolcall info
                        function = call.get("function") if isinstance(call.get("function"), dict) else {}
                        self.dropped_history_toolcalls.append({
                            "tool_call_id": str(call_id),
                            "name": str(function.get("name") or call.get("name") or ""),
                            "arguments": function.get("arguments", call.get("arguments", {})),
                        })

        if not dropped_ids:
            return messages

        # Build new messages list, dropping covered tool_calls and their paired
        # results. Some legacy or normalized messages may lack tool_call_id on
        # the tool result, so keep an adjacency fallback for the immediately
        # following id-less tool messages.
        result: list[dict[str, Any]] = []
        pending_unlinked_tool_results = 0
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = _role(message)
            if role == "assistant" and isinstance(message.get("tool_calls"), list):
                # Filter out dropped tool_calls
                remaining_calls = []
                for call in message["tool_calls"]:
                    if not isinstance(call, dict):
                        remaining_calls.append(call)
                        continue
                    call_id = call.get("id") or call.get("call_id") or call.get("tool_call_id")
                    if call_id and str(call_id) in dropped_ids:
                        pending_unlinked_tool_results += 1
                        continue  # drop this tool_call
                    remaining_calls.append(call)
                if remaining_calls:
                    new_msg = dict(message)
                    new_msg["tool_calls"] = remaining_calls
                    result.append(new_msg)
                else:
                    # All tool_calls were dropped. Keep assistant content only
                    # if there is actual text; otherwise drop the empty
                    # assistant tool-call message together with its result.
                    new_msg = dict(message)
                    new_msg.pop("tool_calls", None)
                    if _content(new_msg).strip():
                        result.append(new_msg)
            elif role == "tool":
                # Drop tool results whose tool_call_id was dropped
                tool_call_id = str(message.get("tool_call_id") or "")
                if tool_call_id in dropped_ids:
                    if pending_unlinked_tool_results > 0:
                        pending_unlinked_tool_results -= 1
                    continue  # drop this tool result
                if not tool_call_id and pending_unlinked_tool_results > 0:
                    pending_unlinked_tool_results -= 1
                    continue  # drop this tool result
                result.append(message)
            else:
                pending_unlinked_tool_results = 0
                result.append(message)

        return result
