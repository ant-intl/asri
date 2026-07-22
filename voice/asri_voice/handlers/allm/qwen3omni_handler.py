"""
ALLM (Audio Large Language Model) handler for Qwen3-Omni via vLLM.

Replaces both STT and LLM stages: takes raw audio from VAD, sends it to
Qwen3-Omni which understands audio natively, and yields text responses
in the same format as the LLM handlers.
"""

import base64
import io
import json
import logging
import re
import time
import struct

import httpx
import numpy as np
from api.openai_realtime.runtime_config import RuntimeConfig
from handlers.heartbeat_interaction.history_formatter import (
    clean_tool_result_for_model,
    load_heartbeat_response_prompt_template,
    normalize_heartbeat_response_tool_payload,
    render_heartbeat_response_context,
    strip_model_hidden_tool_fields,
)
from handlers.llm.utils import split_sentences
from handlers.llm.tool_call.normalize import normalize_chat_completions_tools
from handlers.llm.tool_call.tool_registry import ToolRegistry
from handlers.llm.tool_call.xml_tool_call import (
    extract_xml_tool_calls,
    render_tool_call_xml,
    render_tool_result_xml,
    tool_schemas_xml_system_block,
)
from openai import OpenAI
from rich.console import Console

from pipeline.base_handler import BaseHandler
from pipeline.cancel_scope import CancelScope
from handlers.llm.chat import Chat
from handlers.llm.utils import remove_unspeechable, strip_xml_tags

logger = logging.getLogger(__name__)
console = Console()

_ROLE_PREFIX_RE = re.compile(r"^\s*assistant\s*[:：]?\s*", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)


def numpy_to_wav_base64(audio_np: np.ndarray, sample_rate: int = 16000) -> str:
    """Convert a numpy int16 audio array to a base64-encoded WAV string."""
    if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
        # Convert float [-1, 1] to int16
        audio_np = (audio_np * 32767).astype(np.int16)
    elif audio_np.dtype != np.int16:
        audio_np = audio_np.astype(np.int16)

    num_samples = len(audio_np)
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * block_align

    buf = io.BytesIO()
    # RIFF header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    # fmt chunk
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))  # chunk size
    buf.write(struct.pack("<H", 1))   # PCM format
    buf.write(struct.pack("<H", num_channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits_per_sample))
    # data chunk
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(audio_np.tobytes())

    return base64.b64encode(buf.getvalue()).decode("ascii")


class Qwen3OmniALLMHandler(BaseHandler):
    """
    Audio Language Model handler using Qwen3-Omni served by vLLM.

    Input:  numpy audio arrays (from VAD, via spoken_prompt_queue)
    Output: (text_chunk, language_code, tools) tuples (same as LLM handlers)
    """

    def setup(
        self,
        model_name="Qwen3-Omni-30B-A3B-Instruct",
        base_url="http://localhost:8000/v1",
        api_key="EMPTY",
        init_chat_prompt="You are a helpful and friendly AI assistant. You are polite, respectful, and aim to provide concise responses of less than 20 words.",
        chat_size=999,
        disable_thinking=True,
        request_timeout_s=30.0,
        cancel_scope: CancelScope | None = None,
        runtime_config: RuntimeConfig | None = None,
        tool_registry: ToolRegistry | None = None,
        heartbeat_cache=None,
        text_output_queue=None,
        max_agent_iterations: int = 10,
        clean_response_text: bool = True,
        gen_kwargs=None,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.cancel_scope = cancel_scope
        self.request_timeout_s = float(request_timeout_s)
        self.request_timeout = httpx.Timeout(
            self.request_timeout_s,
            connect=min(10.0, self.request_timeout_s),
        )
        self.chat = Chat(chat_size)
        self.disable_thinking = disable_thinking
        self.runtime_config = runtime_config
        self.tool_registry = tool_registry
        self.heartbeat_cache = heartbeat_cache
        self.text_output_queue = text_output_queue
        self.max_agent_iterations = max(1, int(max_agent_iterations))
        self.clean_response_text = clean_response_text
        self.gen_kwargs = {k: v for k, v in dict(gen_kwargs or {}).items() if v is not None}
        self._initial_chat_message = None
        self._initial_instructions = init_chat_prompt
        self._last_system_prompt = None
        self._heartbeat_snapshot = []
        self._heartbeat_history_rewrite = None

        if init_chat_prompt:
            self._initial_chat_message = {"role": "system", "content": init_chat_prompt}
            self.chat.init_chat(dict(self._initial_chat_message))

        self._extra_body = (
            {"chat_template_kwargs": {"enable_thinking": False}}
            if disable_thinking
            else None
        )

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._agent_loop_active = tool_registry is not None and len(tool_registry) > 0
        if self._agent_loop_active:
            logger.info(
                "ALLM XML agent loop active: %d server tools registered (%s), max %d iterations",
                len(tool_registry),
                tool_registry.all_server_tool_names(),
                self.max_agent_iterations,
            )
        self.warmup()

    def warmup(self):
        logger.info(f"Warming up {self.__class__.__name__}")
        start = time.time()
        try:
            self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Hello"},
                ],
                max_completion_tokens=5,
                stream=False,
                timeout=self.request_timeout,
            )
        except Exception as e:
            logger.warning(f"Warmup failed (non-fatal): {e}")
        elapsed = time.time() - start
        logger.info(f"{self.__class__.__name__}: warmed up in {elapsed:.3f}s")

    @staticmethod
    def _extra_instructions_system_block(extra_instructions: str | None) -> str:
        if not extra_instructions or not extra_instructions.strip():
            return ""
        return (
            "\n\n### Instruction Prompts for current conversation\n"
            "The following sample-specific instructions extend the default system policy. "
            "Follow them only when they do not conflict with higher-priority safety or harness rules.\n"
            f"{extra_instructions.strip()}"
        )

    def _runtime_tools_for_prompt(self) -> list[dict]:
        tools = []
        if self.runtime_config is not None:
            tools = list(getattr(getattr(self.runtime_config, "session", None), "tools", None) or [])
        if not tools and self.tool_registry is not None and hasattr(self.tool_registry, "tool_schemas_chat_api"):
            tools = self.tool_registry.tool_schemas_chat_api()
        return tools

    def _apply_runtime_config(self) -> None:
        base_instructions = self._initial_instructions
        if self.runtime_config is not None:
            base_instructions = (
                self.runtime_config.session.instructions
                or self._initial_instructions
            )
        extra_instructions = (
            getattr(self.runtime_config, "extra_instructions", "") or ""
            if self.runtime_config is not None
            else ""
        )
        system_prompt = (
            base_instructions
            + tool_schemas_xml_system_block(self._runtime_tools_for_prompt())
            + self._extra_instructions_system_block(extra_instructions)
        )
        if system_prompt != self._last_system_prompt:
            self._last_system_prompt = system_prompt
            self.chat.init_chat({"role": "system", "content": system_prompt})
            logger.info("ALLM instructions updated (%d chars)", len(system_prompt))

    def _tool_context(self, gen):
        context = {}
        if gen is not None:
            context["generation"] = gen
            context["turn_id"] = f"gen:{gen}"
        context["conversation_messages"] = self.chat.to_list()
        context["llm_model_name"] = self.model_name
        context["llm_base_url"] = self.base_url
        context["llm_api_key"] = self.api_key
        return context

    @staticmethod
    def _strip_model_hidden_tool_fields(value):
        return strip_model_hidden_tool_fields(value)

    @staticmethod
    def _clean_tool_result_for_model(result: str) -> str:
        return clean_tool_result_for_model(result)

    @staticmethod
    def _clean_spoken_response_text(text: str) -> str:
        if not text:
            return ""
        cleaned = _THINK_TAG_RE.sub("", text)
        cleaned = _ROLE_PREFIX_RE.sub("", cleaned.strip(), count=1)
        return cleaned.strip()

    @staticmethod
    def _empty_response_retry_message() -> dict:
        return {
            "role": "user",
            "content": (
                "The previous assistant response was empty. "
                "Provide a concise spoken answer to the latest user audio now. "
                "If no action is needed, say a brief acknowledgement."
            ),
        }

    @staticmethod
    def _arguments_key(arguments) -> str:
        try:
            return json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(arguments or {})

    @classmethod
    def _compact_heartbeat_entries(cls, entries, *, max_thinking_entries: int = 12):
        """Keep HeartBeat context compact enough for the response model.

        Long audio turns can trigger the same prefetch tool repeatedly on
        adjacent blocks.  For response conditioning, one latest result per
        tool-name + arguments + result tuple is enough; keeping every duplicate
        bloats the Qwen3-Omni prompt and can push slow samples into timeout.
        """
        if not entries:
            return []

        seen_tool_keys: set[tuple[str, str, str, str]] = set()
        retained_items_by_entry: dict[int, list] = {}
        for idx in range(len(entries) - 1, -1, -1):
            retained = []
            for it in reversed(getattr(entries[idx], "items", []) or []):
                args = strip_model_hidden_tool_fields(getattr(it, "arguments", {}) or {})
                result = cls._clean_tool_result_for_model(getattr(it, "result", "") or "")
                key = (
                    getattr(it, "tool_name", ""),
                    cls._arguments_key(args),
                    getattr(it, "status", "completed"),
                    result,
                )
                if key in seen_tool_keys:
                    continue
                seen_tool_keys.add(key)
                retained.append(it)
            if retained:
                retained_items_by_entry[idx] = list(reversed(retained))

        thinking_budget = max(0, int(max_thinking_entries))
        thinking_kept = 0
        compacted = []
        for idx in range(len(entries) - 1, -1, -1):
            entry = entries[idx]
            items = retained_items_by_entry.get(idx, [])
            has_thinking = bool(getattr(entry, "thinking", ""))
            keep_thinking = has_thinking and thinking_kept < thinking_budget
            if keep_thinking:
                thinking_kept += 1
            if items or keep_thinking:
                compacted.append((entry, items, keep_thinking))
        return list(reversed(compacted))

    @staticmethod
    def _render_assistant_tool_calls_for_history(tool_calls: list[dict]) -> str:
        rendered = []
        for tool_call in tool_calls:
            fn = tool_call.get("function") if isinstance(tool_call, dict) else {}
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}
            if name:
                rendered.append(render_tool_call_xml(name, args))
        return "\n".join(rendered)

    def _inject_heartbeat_context(self) -> None:
        self._heartbeat_snapshot = []
        self._heartbeat_history_rewrite = None
        if self.heartbeat_cache is None:
            self._emit_response_input_messages()
            return

        entries = self.heartbeat_cache.consume_all()
        if not entries:
            self._emit_response_input_messages()
            return

        compacted_entries = self._compact_heartbeat_entries(entries)
        all_items = [it for _, items, _ in compacted_entries for it in items]
        if not compacted_entries:
            self._emit_response_input_messages()
            return

        response_prompt_template = load_heartbeat_response_prompt_template()

        self._heartbeat_snapshot = []
        for it in all_items:
            snap = {
                "tool_name": it.tool_name,
                "arguments": self._strip_model_hidden_tool_fields(it.arguments),
                "status": getattr(it, "status", "completed"),
                "result_preview": self._clean_tool_result_for_model(it.result) if it.result else "",
            }
            self._heartbeat_snapshot.append(snap)

        context_payload = {
            "thinking_entries": [],
            "subtasks": [],
        }
        for entry, items, keep_thinking in compacted_entries:
            entry_payload = {
                "block": entry.order_key,
                "action": getattr(entry, "action", "think"),
                "tools": [],
            }
            if keep_thinking and entry.thinking:
                entry_payload["thinking"] = entry.thinking
            metadata = getattr(entry, "metadata", None)
            if isinstance(metadata, dict) and metadata:
                entry_payload["metadata"] = metadata
            for it in items:
                payload = normalize_heartbeat_response_tool_payload(
                    {
                        "name": it.tool_name,
                        "arguments": it.arguments,
                        "status": getattr(it, "status", "completed"),
                        "result": it.result,
                    },
                    response_prompt_template,
                )
                if payload is not None:
                    entry_payload["tools"].append(payload)
            context_payload["thinking_entries"].append(entry_payload)

        hint = render_heartbeat_response_context(context_payload, response_prompt_template)
        target_idx = None
        for idx in range(len(self.chat.buffer) - 1, -1, -1):
            if self.chat.buffer[idx].get("role") == "user":
                target_idx = idx
                content = self.chat.buffer[idx].get("content")
                if isinstance(content, list):
                    content.append({"type": "text", "text": hint})
                    self._heartbeat_history_rewrite = {"idx": idx, "hint": hint}
                elif isinstance(content, str):
                    self.chat.buffer[idx]["content"] = content + hint
                    self._heartbeat_history_rewrite = {"idx": idx, "hint": hint}
                break
        if target_idx is None:
            logger.warning("ALLM HeartBeat context injection skipped: no user message")
        self._emit_response_input_messages()

    def _emit_response_input_messages(self) -> None:
        if self.text_output_queue is None:
            return
        raw_messages = self.chat.to_list()
        current_user_idx = None
        for idx in range(len(raw_messages) - 1, -1, -1):
            if raw_messages[idx].get("role") == "user":
                current_user_idx = idx
                break

        def _content_to_text(content_val) -> str:
            if isinstance(content_val, list):
                return "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content_val
                )
            return content_val if content_val is not None else ""

        messages_snapshot = []
        for idx, msg in enumerate(raw_messages):
            role = msg.get("role")
            if role is None:
                continue
            content_text = _content_to_text(msg.get("content"))
            if role == "user":
                if idx == current_user_idx and "### HeartbeatContext" in content_text:
                    content_text = "<audio>\n\n" + content_text[content_text.find("### HeartbeatContext"):].lstrip()
                else:
                    content_text = "<audio>"
            messages_snapshot.append({"role": role, "content": content_text})
        self.text_output_queue.put({
            "type": "response.input_messages",
            "trace_level": "replay",
            "messages": messages_snapshot,
            "response_start_ms": int(time.time() * 1000),
        })

    def _finalize_heartbeat_history(self) -> None:
        rewrite = self._heartbeat_history_rewrite
        if not rewrite:
            return
        idx = rewrite.get("idx")
        hint = rewrite.get("hint", "")
        try:
            if not isinstance(idx, int) or idx < 0 or idx >= len(self.chat.buffer):
                return
            message = self.chat.buffer[idx]
            content = message.get("content")
            if isinstance(content, str) and hint in content:
                message["content"] = content.replace(hint, "", 1)
            elif isinstance(content, list):
                for part_idx, part in enumerate(list(content)):
                    if isinstance(part, dict) and part.get("text") == hint:
                        content.pop(part_idx)
                        break
        finally:
            self._heartbeat_history_rewrite = None

    def _call_omni_once(self, gen):
        response = None
        raw_text = ""
        input_tokens = 0
        output_tokens = 0
        llm_start = time.perf_counter()
        ttft_ms = None
        cancelled = False
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.chat.to_list(),
                modalities=["text"],
                stream=True,
                stream_options={"include_usage": True},
                extra_body=self._extra_body,
                timeout=self.request_timeout,
                **self.gen_kwargs,
            )
            for chunk in response:
                if gen is not None and self.cancel_scope is not None and self.cancel_scope.is_stale(gen):
                    logger.info("ALLM generation cancelled (interruption)")
                    cancelled = True
                    break
                usage = getattr(chunk, "usage", None)
                if usage:
                    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(usage, "completion_tokens", 0) or 0
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - llm_start) * 1000
                        logger.info("ALLM TTFT: %.0fms", ttft_ms)
                    raw_text += delta.content
        finally:
            if response is not None and hasattr(response, "close"):
                try:
                    response.close()
                except Exception:
                    pass

        llm_total_ms = (time.perf_counter() - llm_start) * 1000
        clean_text, tool_calls = extract_xml_tool_calls(raw_text)
        if self.clean_response_text:
            clean_text = self._clean_spoken_response_text(remove_unspeechable(strip_xml_tags(clean_text)))
        logger.info(
            "ALLM total: %.0fms cancelled=%s text='%s' tools=%s",
            llm_total_ms,
            cancelled,
            clean_text[:80],
            [tc.get("function", {}).get("name", "?") for tc in tool_calls],
        )
        return {
            "raw_text": raw_text,
            "clean_text": clean_text,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cancelled": cancelled,
            "ttft_ms": ttft_ms,
            "llm_total_ms": llm_total_ms,
        }

    def _yield_spoken_text(self, text: str, language_code, gen):
        printable_text = text or ""
        sentences = split_sentences(printable_text)
        if len(sentences) <= 1:
            if printable_text.strip():
                yield printable_text.strip(), language_code, [], gen
            return
        buf = ""
        for sentence in sentences:
            buf += sentence
            if len(buf) >= 25:
                yield buf, language_code, [], gen
                buf = ""
        if buf.strip():
            yield buf.strip(), language_code, [], gen

    def _execute_server_tools(self, normalized, iteration, gen, tool_context):
        results = []
        for tc in normalized:
            if gen is not None and self.cancel_scope is not None and self.cancel_scope.is_stale(gen):
                results.append(None)
                continue
            logger.info("ALLM XML agent loop [iter %d]: executing %s", iteration, tc.name)
            result = self.tool_registry.execute(
                tc.name,
                tc.arguments,
                cancel_scope=self.cancel_scope,
                gen=gen,
                source="main_llm",
                context=tool_context,
            )
            results.append(result)
        return results

    def _process_with_xml_agent_loop(self, language_code, gen):
        total_input_tokens = 0
        total_output_tokens = 0
        overall_ttft_ms = None
        iterations_metrics = []

        for iteration in range(self.max_agent_iterations):
            call_result = self._call_omni_once(gen)
            total_input_tokens += call_result["input_tokens"]
            total_output_tokens += call_result["output_tokens"]
            if overall_ttft_ms is None and call_result["ttft_ms"] is not None:
                overall_ttft_ms = call_result["ttft_ms"]

            clean_text = call_result["clean_text"]
            tool_calls = call_result["tool_calls"]
            # If this iteration contains tool calls, any surrounding model text
            # is usually a tool-call narration ("Assistant call for ..."). Do
            # not speak it or feed it back as natural language; the next model
            # turn will produce the user-facing answer after tool results.
            should_speak_text = bool(clean_text.strip()) and not tool_calls
            if should_speak_text:
                yield from self._yield_spoken_text(clean_text, language_code, gen)

            if call_result["cancelled"]:
                if should_speak_text:
                    self.chat.append({"role": "assistant", "content": clean_text})
                iterations_metrics.append({
                    "llm_ttft_ms": round(call_result["ttft_ms"]) if call_result["ttft_ms"] is not None else None,
                    "llm_total_ms": round(call_result["llm_total_ms"]),
                    "tool_calls": [],
                    "tool_exec_ms": None,
                })
                break

            if not tool_calls:
                if clean_text.strip():
                    self.chat.append({"role": "assistant", "content": clean_text})
                    iterations_metrics.append({
                        "llm_ttft_ms": round(call_result["ttft_ms"]) if call_result["ttft_ms"] is not None else None,
                        "llm_total_ms": round(call_result["llm_total_ms"]),
                        "tool_calls": [],
                        "tool_exec_ms": None,
                    })
                    break

                iterations_metrics.append({
                    "llm_ttft_ms": round(call_result["ttft_ms"]) if call_result["ttft_ms"] is not None else None,
                    "llm_total_ms": round(call_result["llm_total_ms"]),
                    "tool_calls": [],
                    "tool_exec_ms": None,
                    "empty_response": True,
                })
                if iteration < self.max_agent_iterations - 1:
                    logger.info("ALLM produced empty final response; retrying with explicit answer request")
                    self.chat.append(self._empty_response_retry_message())
                    continue

                fallback_text = "Okay."
                yield from self._yield_spoken_text(fallback_text, language_code, gen)
                self.chat.append({"role": "assistant", "content": fallback_text})
                break

            assistant_tool_history = self._render_assistant_tool_calls_for_history(tool_calls)
            if assistant_tool_history:
                self.chat.append({"role": "assistant", "content": assistant_tool_history})
            else:
                self.chat.append({"role": "assistant", "content": call_result["raw_text"]})
            tool_context = self._tool_context(gen)
            if self.tool_registry is not None:
                for tool_call in tool_calls:
                    self.tool_registry.augment_tool_call_dict(tool_call, tool_context)
            normalized = normalize_chat_completions_tools(tool_calls)
            server_names = self.tool_registry.all_server_tool_names() if self.tool_registry is not None else set()
            tool_names = [tc.name for tc in normalized]
            any_client = any(tc.name not in server_names for tc in normalized)

            iterations_metrics.append({
                "llm_ttft_ms": round(call_result["ttft_ms"]) if call_result["ttft_ms"] is not None else None,
                "llm_total_ms": round(call_result["llm_total_ms"]),
                "tool_calls": tool_names,
                "tool_exec_ms": None,
            })

            if any_client or self.tool_registry is None:
                yield "", language_code, tool_calls, gen
                break

            yield "", language_code, tool_calls, gen
            yield ("__ITERATION_DONE__", None, None, gen)

            tool_start = time.perf_counter()
            tool_results = self._execute_server_tools(normalized, iteration, gen, tool_context)
            iterations_metrics[-1]["tool_exec_ms"] = round((time.perf_counter() - tool_start) * 1000)
            cancelled_during_tools = False
            for tc, result in zip(normalized, tool_results):
                if result is None:
                    cancelled_during_tools = True
                    break
                result_event = {
                    "tool_call_id": tc.call_id,
                    "name": tc.name,
                    "content": result,
                }
                chat_content = self._clean_tool_result_for_model(result)
                self.chat.append({
                    "role": "user",
                    "content": render_tool_result_xml(tc.name, chat_content),
                })
                yield ("__TOOL_RESULT__", result_event, None, gen)
            if cancelled_during_tools:
                break
            continue

        metrics = {
            "overall_ttft_ms": round(overall_ttft_ms) if overall_ttft_ms is not None else None,
            "server_llm_total_ms": sum(item.get("llm_total_ms") or 0 for item in iterations_metrics),
            "server_e2e_ms": round((time.perf_counter() - self.cancel_scope.pipeline_start) * 1000) if self.cancel_scope and self.cancel_scope.pipeline_start else None,
            "server_asr_ms": None,
            "iterations": iterations_metrics,
            "final": True,
            "heartbeat": self._heartbeat_snapshot,
        }
        yield ("__LLM_METRICS__", metrics, None, gen)
        return total_input_tokens, total_output_tokens

    def process(self, spoken_prompt):
        """
        Process audio input from VAD and generate text response.

        Args:
            spoken_prompt: numpy array of audio data (int16 or float32, 16kHz mono)

        Yields:
            (text_chunk, language_code, tools_list) tuples
            ("__TOKEN_USAGE__", input_tokens, output_tokens)
            ("__END_OF_RESPONSE__", None, None)
        """
        logger.debug("ALLM: received audio input, length=%d samples", len(spoken_prompt))
        self._apply_runtime_config()

        # Encode audio as base64 WAV data URI
        wav_b64 = numpy_to_wav_base64(spoken_prompt, sample_rate=16000)
        audio_data_uri = f"data:audio/wav;base64,{wav_b64}"

        # Build user message with audio content
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "audio_url",
                    "audio_url": {"url": audio_data_uri},
                },
            ],
        }

        self.chat.append(user_message)
        self._inject_heartbeat_context()

        gen = self.cancel_scope.generation if self.cancel_scope else None
        total_input = 0
        total_output = 0
        try:
            if getattr(self.runtime_config, "disable_response_generation", False):
                logger.info("ALLM response generation disabled for replay; skipping model call")
                return

            total_input, total_output = yield from self._process_with_xml_agent_loop(None, gen)

        except httpx.ReadTimeout:
            logger.warning(
                "ALLM API read timed out after %.1fs",
                self.request_timeout_s,
            )
        except Exception as e:
            logger.error(f"ALLM API error: {type(e).__name__}: {e}", exc_info=True)
            yield ("Sorry, I encountered an error. Could you try again?", None, [], gen)
        finally:
            self._finalize_heartbeat_history()

        # Strip audio content from history to save memory
        self._strip_audio_from_history()

        if total_input or total_output:
            yield ("__TOKEN_USAGE__", total_input, total_output, gen)
        yield ("__END_OF_RESPONSE__", None, None, gen)

    def _strip_audio_from_history(self):
        """Remove audio data URIs from chat history to save memory."""
        for msg in self.chat.buffer:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            # Replace audio_url entries with the SFT/replay audio placeholder.
            new_content = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "audio_url":
                    new_content.append({"type": "text", "text": "<audio>"})
                else:
                    new_content.append(part)
            msg["content"] = new_content

    def on_session_end(self):
        self.chat.reset()
        if self._initial_chat_message is not None:
            self.chat.init_chat(dict(self._initial_chat_message))
        self._last_system_prompt = None
        if self.heartbeat_cache is not None:
            self.heartbeat_cache.reset()
        logger.debug("ALLM session state reset")
