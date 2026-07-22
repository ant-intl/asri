"""HeartBeat Interaction Handler — side-branch handler that runs alongside the main pipeline.

Receives raw audio chunks from a forked copy of ``recv_audio_chunks_queue``
(before VAD), accumulates them into fixed-duration blocks, and for each
block constructs an SFT-aligned prompt that is **byte-identical** to the
training data.

The prompt template version is configurable via ``prompt_version``. The current
repository keeps ``"asri-v0"``.

The model output is the SFT dual-tool JSON::

    {"query_epos_order": "NO_QUERY" | {...}, "search_epos_knowledge": "NO_QUERY" | {...}}

For each non-NO_QUERY tool, this handler executes the tool via the shared
``ToolRegistry`` and stores the result in ``HeartBeatCache`` so the main LLM
handler can consume the HeartBeat context on its next ``process()`` call.
"""

import json
import logging
import inspect
import threading
import time
import uuid

import numpy as np

from utils.utils import log_llm_request
from pipeline.base_handler import BaseHandler
from handlers.heartbeat_interaction.history_formatter import (
    PromptTemplate,
    build_sft_prompt,
    iter_predict_tool_calls,
    load_prompt_template,
    parse_predict_output,
)
from handlers.heartbeat_interaction.heartbeat_cache import HeartBeatCache, HeartBeatEntry, ToolResultItem

logger = logging.getLogger(__name__)

# ANSI colour for side-branch logging
_M = "\033[35m"  # magenta
_R = "\033[0m"   # reset

# Sentinel sent to the predict handler when VAD detects end-of-speech.
# The handler resets per-turn state (audio buffer, block counter, etc.)
# so it's ready for the next utterance.
TURN_END = "turn_end"


class HeartbeatInteractionHandler(BaseHandler):
    """Side-branch handler: constructs SFT-format input and (optionally) calls
    the HeartBeat Interaction omni model.

    Setup kwargs (injected via ``build_pipeline``):
        chat_ref:  Reference to the LLM handler's ``Chat`` object (read-only).
        model_name:  Predict model name (for vLLM API).
        base_url:  Predict model API base URL.
        api_key:  Predict model API key.
        block_duration_ms:  Audio block duration in milliseconds.
        request_timeout_s:  API request timeout.
        cancel_scope:  Shared CancelScope for barge-in awareness.
        heartbeat_cache:  Shared HeartBeatCache for storing HeartBeat tool results.
        tool_registry:  ToolRegistry for executing HeartBeat tool calls.
        prompt_version:  Prompt template version.
        blocking:  If true, call predict inline on the ingestion thread.
        max_concurrent:  Non-blocking in-flight predict request cap.

    The SFT system / business background / tool schema / decision policy /
    examples are all hard-coded in :mod:`history_formatter` to match the
    training data byte-for-byte; no EPOS system prompt is injected here.
    """

    def setup(
        self,
        chat_ref=None,
        turn_audio_history=None,
        model_name="Qwen3-Omni-8B",
        base_url="http://localhost:8906/v1",
        api_key="dummy",
        block_duration_ms=500,
        request_timeout_s=5.0,
        cancel_scope=None,
        heartbeat_cache=None,
        tool_registry=None,
        gen_kwargs=None,
        prompt_version="asri-v0",
        blocking=True,
        max_concurrent=8,
        runtime_config=None,
        text_output_queue=None,
        fd_mode=False,
        tool_llm_model_name=None,
        tool_llm_base_url=None,
        tool_llm_api_key=None,
    ):
        self.chat_ref = chat_ref
        self.turn_audio_history = turn_audio_history
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.block_duration_ms = block_duration_ms
        self.request_timeout_s = request_timeout_s
        self.cancel_scope = cancel_scope
        self.heartbeat_cache: HeartBeatCache | None = heartbeat_cache
        self.tool_registry = tool_registry
        self.prompt_template: PromptTemplate = load_prompt_template(prompt_version)
        self.blocking: bool = bool(blocking)
        self.max_concurrent: int = max(1, int(max_concurrent))
        self.runtime_config = runtime_config
        self.text_output_queue = text_output_queue
        self.fd_mode = bool(fd_mode)
        self.tool_llm_model_name = tool_llm_model_name
        self.tool_llm_base_url = tool_llm_base_url
        self.tool_llm_api_key = tool_llm_api_key
        self._logged_tool_context_source: bool = False

        # Block size in samples (16kHz mono)
        self.block_size = 16000 * block_duration_ms // 1000

        # Per-turn state
        self.current_turn_audio = np.array([], dtype=np.float32)
        self.last_processed_block = 0
        # Once the LLM consumes the HeartBeat cache, the predict handler
        # must stop for the rest of this turn — even across separate
        # ``process()`` calls.  This flag is reset on TURN_END.
        self._consumed_detected: bool = False
        # Keep omni/audio mode aligned with the streaming_asr text predictor:
        # blocking=False submits one worker per audio block, capped by this
        # semaphore.  Turn generation makes stale worker results harmless.
        self._predict_semaphore = threading.Semaphore(self.max_concurrent)
        self._inflight: set[threading.Thread] = set()
        self._inflight_lock = threading.Lock()
        self._turn_generation: int = 0
        self._turn_lock = threading.Lock()
        self._pending_drain: bool = True
        self._turn_start_perf: float | None = None

        # Lazy-init OpenAI client (only when model is actually available)
        self._client = None

        # Race-5 fix: subscribe to CancelScope so barge-in immediately bumps
        # _turn_generation, causing inflight workers to drop stale results
        # instead of leaking them into the next turn's cache.
        if self.cancel_scope is not None and hasattr(self.cancel_scope, "register_cancel_listener"):
            self.cancel_scope.register_cancel_listener(self._on_cancel)

        logger.info(
            "%sHeartbeatInteractionHandler: model=%s, base_url=%s, block=%dms, "
            "prompt=%s, mode=%s, max_concurrent=%d, fd_mode=%s%s",
            _M, model_name, base_url, block_duration_ms, prompt_version,
            "blocking" if self.blocking else "async+ordered-insert",
            self.max_concurrent,
            self.fd_mode,
            _R,
        )

    def _get_client(self):
        """Lazily initialise the OpenAI client for the predict model."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_retries=0,
                )
            except Exception as exc:
                logger.warning("HeartBeatInteraction: failed to init OpenAI client: %s", exc)
        return self._client

    def _should_continue_predict(self, turn_gen: int) -> bool:
        if turn_gen != self._turn_generation:
            return False
        if self._consumed_detected:
            return False
        if self.heartbeat_cache and self.heartbeat_cache.is_consumed():
            self._consumed_detected = True
            return False
        if self.cancel_scope and self.cancel_scope.discarding:
            return False
        return True

    def _heartbeat_tool_context(self) -> dict | None:
        """Build tool context for HeartBeat Thinking prompts.

        Realtime evaluation can provide per-sample tools through
        ``conversation.history.set`` or server tools through ``tools_module``.
        Omni thinking uses the same prompt schema path as streaming-ASR mode.
        """
        context = (
            self.runtime_config.tool_context()
            if self.runtime_config is not None and hasattr(self.runtime_config, "tool_context")
            else None
        )
        if context is None:
            context = {}
        else:
            context = dict(context)

        tools = context.get("tools")
        if not tools and self.tool_registry is not None and hasattr(self.tool_registry, "tool_schemas_chat_api"):
            try:
                tools = self.tool_registry.tool_schemas_chat_api()
            except Exception:
                logger.exception("Failed to render server tool schemas for HeartBeat Thinking")
                tools = None
            if tools:
                context["tools"] = tools
                if not self._logged_tool_context_source:
                    names = []
                    for tool in tools:
                        func = tool.get("function") if isinstance(tool, dict) else None
                        if isinstance(func, dict) and func.get("name"):
                            names.append(str(func["name"]))
                    logger.info(
                        "%s[HeartBeatInteraction] using %d server tool schemas for prompt: %s%s",
                        _M, len(tools), names, _R,
                    )
                    self._logged_tool_context_source = True
        return context

    def _fd_current_turn_metadata(self) -> dict | None:
        if not self.fd_mode:
            return None
        return {
            "fd_mode": True,
            "input_relation": "normal_user_turn",
        }

    def _emit_thinker_event(self, event: str, **payload) -> None:
        if self.text_output_queue is None:
            return
        try:
            self.text_output_queue.put({
                "type": "heartbeat_thinking",
                "event": event,
                "ts_ms": int(time.time() * 1000),
                **payload,
            })
        except Exception:
            logger.exception("Failed to emit HeartBeat Thinking event")
            raise

    def process(self, audio_input):
        """Receive a raw audio chunk from the mic/socket queue, accumulate,
        and for each new complete block call the SFT-aligned predict model.

        Args:
            audio_input: raw audio bytes (int16 PCM 16kHz mono) from
                ``recv_audio_chunks_queue``, or a numpy int16 array from VAD
                output (backward-compatible), or a
                ``("progressive"/"final", array)`` tuple, or the
                ``TURN_END`` sentinel to reset per-turn state.

        Yields:
            In blocking mode, the raw model response string (the SFT
            dual-tool JSON) for every block where any tool was triggered.
            In non-blocking mode, yields nothing; workers store results in
            ``HeartBeatCache`` asynchronously.
        """
        # Handle turn-end sentinel from VAD.
        # Format: (TURN_END, audio_ndarray) or bare TURN_END (legacy).
        turn_end_audio = None
        if audio_input is TURN_END:
            turn_end_audio = None
        elif isinstance(audio_input, tuple) and len(audio_input) == 2 and audio_input[0] is TURN_END:
            turn_end_audio = audio_input[1]
        else:
            turn_end_audio = ...  # sentinel: not a TURN_END

        if turn_end_audio is not ...:
            if len(self.current_turn_audio) > 0:
                logger.info(
                    "%s[HeartBeatInteraction] TURN_END: resetting turn "
                    "(%.1fs audio, %d blocks processed)%s",
                    _M, len(self.current_turn_audio) / 16000.0,
                    self.last_processed_block, _R,
                )
            # Store the VAD-processed audio into turn_audio_history NOW
            # (not earlier in _VadOutWithSignal) so it aligns with the
            # chat history that STT will soon populate.
            if turn_end_audio is not None and self.turn_audio_history is not None:
                from pipeline.turn_audio_history import encode_audio_base64
                dur = len(turn_end_audio) / 16000.0
                self.turn_audio_history.append(
                    encode_audio_base64(turn_end_audio), duration_s=dur
                )
            self._reset_turn()
            return

        # If LLM already consumed our HeartBeat cache in a previous process()
        # call, skip all processing until TURN_END resets the turn.
        if self._pending_drain:
            self._pending_drain = False
            if self.heartbeat_cache is not None and self.heartbeat_cache.is_consumed():
                logger.info(
                    "%s[HeartBeatInteraction] drained stale consumed flag "
                    "from previous turn at first audio block%s",
                    _M, _R,
                )

        if self._consumed_detected:
            return

        # Convert raw bytes to numpy float32
        if isinstance(audio_input, bytes):
            audio_data = np.frombuffer(audio_input, dtype=np.int16).astype(np.float32) / 32768.0
        elif isinstance(audio_input, tuple) and len(audio_input) == 2:
            _label, audio_data = audio_input
            if not isinstance(audio_data, np.ndarray):
                return
        elif isinstance(audio_input, np.ndarray):
            audio_data = audio_input
        else:
            return

        # Normalise dtype to float32 [-1, 1] (same as librosa.load output)
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype in (np.float64,):
            audio_data = audio_data.astype(np.float32)

        # Accumulate audio for the current user turn
        self.current_turn_audio = np.concatenate([self.current_turn_audio, audio_data])

        # How many complete blocks do we have now?
        num_blocks = len(self.current_turn_audio) // self.block_size
        if num_blocks <= self.last_processed_block:
            return  # No new complete blocks yet

        # Skip if no chat reference available
        if self.chat_ref is None:
            logger.debug("HeartBeatInteraction: no chat_ref, skipping")
            return

        # Process each new block
        for block_idx in range(self.last_processed_block, num_blocks):
            # Stop if LLM already consumed our HeartBeat cache (one-shot signal)
            if self.heartbeat_cache and self.heartbeat_cache.is_consumed():
                logger.info("%s[HeartBeatInteraction] HeartBeat cache consumed by LLM, stopping%s", _M, _R)
                self._consumed_detected = True
                break

            # Check barge-in
            if self.cancel_scope and self.cancel_scope.discarding:
                logger.debug("HeartBeatInteraction: discarding (barge-in)")
                break

            # Cumulative audio up to this block
            cumulative_audio = self.current_turn_audio[: (block_idx + 1) * self.block_size]
            cumulative_duration_s = len(cumulative_audio) / 16000.0

            # Snapshot chat history (thread-safe: to_list() creates a new list)
            history_snapshot = list(self.chat_ref.to_list())
            history_audio_b64 = (
                self.turn_audio_history.snapshot()
                if self.turn_audio_history is not None
                else []
            )
            history_user_count = sum(
                1 for m in history_snapshot if m.get("role") == "user"
            )
            if len(history_audio_b64) > history_user_count:
                history_audio_b64 = (
                    history_audio_b64[-history_user_count:]
                    if history_user_count > 0
                    else []
                )

            # Build SFT-format prompt (byte-identical to training format)
            sft_prompt = build_sft_prompt(
                chat_messages=history_snapshot,
                block_idx=block_idx,
                block_duration_ms=self.block_duration_ms,
                prompt_template=self.prompt_template,
                async_context_entries=(
                    self.heartbeat_cache.snapshot_for_thinker()
                    if self.heartbeat_cache is not None
                    else []
                ),
                tool_context=self._heartbeat_tool_context(),
                current_turn_metadata=self._fd_current_turn_metadata(),
                extra_instructions=(
                    getattr(getattr(self, "runtime_config", None), "extra_instructions", "")
                    if getattr(self, "runtime_config", None) is not None
                    else ""
                ),
            )

            logger.info(
                "%s[HeartBeatInteraction] block %d (%.1fs audio)%s",
                _M, block_idx, cumulative_duration_s, _R,
            )
            if getattr(self, "_turn_start_perf", None) is None:
                self._turn_start_perf = time.perf_counter()
            trigger_ts_ms = int(time.time() * 1000)
            elapsed_ms = int((time.perf_counter() - self._turn_start_perf) * 1000)
            logger.info(
                "%s[ToolCallThinker] trigger block=%d ts_ms=%d elapsed_ms=%d audio_s=%.1f%s",
                _M, block_idx, trigger_ts_ms, elapsed_ms, cumulative_duration_s, _R,
            )
            self._emit_thinker_event(
                "trigger",
                block_idx=block_idx,
                trigger_ts_ms=trigger_ts_ms,
                elapsed_ms=elapsed_ms,
                audio_s=round(cumulative_duration_s, 3),
                fd_mode=self.fd_mode,
            )
            logger.debug(
                "%s[HeartBeatInteraction] SFT user prompt:\n%s%s",
                _M, sft_prompt["messages"][1]["content"][:500], _R,
            )

            turn_gen = self._turn_generation
            if self.blocking:
                # Call predict model inline (legacy behavior).
                raw_response = self._invoke_predict_model(
                    sft_prompt,
                    cumulative_audio,
                    history_audio_b64,
                    block_idx,
                    turn_gen=turn_gen,
                )
                if self._process_predict_result(
                    raw_response, turn_gen, block_idx, trigger_ts_ms, elapsed_ms,
                ):
                    yield raw_response
            else:
                # Submit asynchronously.  Copy cumulative audio because
                # self.current_turn_audio keeps growing after this block.
                worker = threading.Thread(
                    target=self._predict_worker,
                    args=(
                        sft_prompt,
                        cumulative_audio.copy(),
                        list(history_audio_b64),
                        block_idx,
                        turn_gen,
                        trigger_ts_ms,
                        elapsed_ms,
                    ),
                    daemon=True,
                    name=f"omni-predict-{block_idx}",
                )
                with self._inflight_lock:
                    self._inflight.add(worker)
                worker.start()

        self.last_processed_block = num_blocks

    def _process_predict_result(
        self,
        raw_response,
        turn_gen: int,
        block_idx: int,
        trigger_ts_ms: int | None = None,
        elapsed_ms: int | None = None,
    ) -> bool:
        """Parse predict output and store tool results if this turn is current."""
        if raw_response is None:
            return False
        parsed = parse_predict_output(raw_response)
        if parsed is None:
            # Malformed output — skip this block and keep listening.
            return False

        with self._turn_lock:
            if turn_gen != self._turn_generation:
                logger.debug(
                    "%s[HeartBeatInteraction] block %d stale (gen %d != %d), drop%s",
                    _M, block_idx, turn_gen, self._turn_generation, _R,
                )
                return False
            if self._consumed_detected:
                return False
            if self.heartbeat_cache and self.heartbeat_cache.is_consumed():
                self._consumed_detected = True
                return False
            if self.cancel_scope and self.cancel_scope.discarding:
                return False
            return self._handle_dual_tool_prediction(
                parsed,
                block_idx,
                trigger_ts_ms=trigger_ts_ms,
                elapsed_ms=elapsed_ms,
            )

    def _predict_worker(
        self,
        sft_prompt,
        cumulative_audio,
        history_audio_b64,
        block_idx: int,
        turn_gen: int,
        trigger_ts_ms: int | None,
        elapsed_ms: int | None,
    ) -> None:
        """Run one completed block, dropping it immediately when saturated."""
        try:
            acquired = self._predict_semaphore.acquire(blocking=False)
            if not acquired:
                logger.info(
                    "%s[HeartBeatInteraction] block %d skipped: in-flight limit reached%s",
                    _M, block_idx, _R,
                )
                return
            try:
                if not self._should_continue_predict(turn_gen):
                    logger.debug(
                        "%s[HeartBeatInteraction] block %d stale at worker entry, skip LLM%s",
                        _M, block_idx, _R,
                    )
                    return
                raw_response = self._invoke_predict_model(
                    sft_prompt,
                    cumulative_audio,
                    history_audio_b64,
                    block_idx,
                    turn_gen=turn_gen,
                )
                self._process_predict_result(
                    raw_response, turn_gen, block_idx, trigger_ts_ms, elapsed_ms,
                )
            finally:
                self._predict_semaphore.release()
        except Exception as exc:
            logger.warning(
                "%s[HeartBeatInteraction] block %d worker failed: %s: %s%s",
                _M, block_idx, type(exc).__name__, exc, _R,
            )
        finally:
            with self._inflight_lock:
                self._inflight.discard(threading.current_thread())

    def _invoke_predict_model(
        self,
        sft_prompt,
        cumulative_audio,
        history_audio_b64,
        block_idx: int,
        turn_gen: int | None,
    ):
        """Call ``_call_predict_model`` while tolerating older test fakes."""
        call = self._call_predict_model
        try:
            signature = inspect.signature(call)
        except (TypeError, ValueError):
            return call(
                sft_prompt,
                cumulative_audio,
                history_audio_b64,
                block_idx,
                turn_gen=turn_gen,
            )

        params = list(signature.parameters.values())
        has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        positional_capacity = sum(
            p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            for p in params
        )
        args = [sft_prompt, cumulative_audio, history_audio_b64]
        if has_varargs or positional_capacity >= 4:
            args.append(block_idx)
        kwargs = {}
        if has_varkw or "turn_gen" in signature.parameters:
            kwargs["turn_gen"] = turn_gen
        return call(*args, **kwargs)

    def _handle_dual_tool_prediction(
        self,
        parsed: dict,
        block_idx: int,
        trigger_ts_ms: int | None = None,
        elapsed_ms: int | None = None,
    ) -> bool:
        """Process a parsed thinker prediction.

        Rules:
        1. value/query field must be non-empty to count as triggered
        2. Same tool+args already executed → dedup skip
        3. Same tool different args → execute again, append to cache
        4. Inject side takes the last entry by time

        Returns ``True`` if at least one new tool was triggered this block.
        """
        thinking = parsed.get("thinking", "")
        if isinstance(thinking, str):
            thinking = thinking.strip()
        else:
            thinking = json.dumps(thinking, ensure_ascii=False)
        if thinking:
            logger.info(
                "%s[ToolCallThinker] thinking block=%d: %s%s",
                _M, block_idx, thinking[:300], _R,
            )
            self._emit_thinker_event(
                "thinking",
                block_idx=block_idx,
                thinking=thinking,
                need_to_think=True,
            )

        triggered_now = False
        items: list[ToolResultItem] = []
        entry_metadata = self._fd_current_turn_metadata() or {}
        for tool_name, value in iter_predict_tool_calls(parsed):
            if not isinstance(value, dict):
                continue
            valid, reason = self._validate_tool_call_schema(tool_name, value)
            if not valid:
                logger.warning(
                    "[HeartBeatInteraction] tool call error %s(%s): %s",
                    tool_name,
                    json.dumps(value, ensure_ascii=False),
                    reason,
                )
                triggered_now = True
                call_id = f"heartbeat_{uuid.uuid4().hex[:8]}"
                self._emit_thinker_event(
                    "tool_call",
                    block_idx=block_idx,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    arguments=value,
                    status="error",
                    reason=reason,
                )
                self._emit_thinker_event(
                    "tool_result",
                    block_idx=block_idx,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    arguments=value,
                    result=f"Error: {reason}",
                    status="error",
                )
                items.append(ToolResultItem(
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    arguments=value,
                    result=f"Error: {reason}",
                    status="error",
                ))
                continue
            value = self._augment_tool_arguments(tool_name, value, block_idx)
            # Rule 1: required action arguments must be non-empty
            if not self._has_actionable_arguments(tool_name, value):
                logger.debug(
                    "[HeartBeatInteraction] %s skipped: missing actionable arguments",
                    tool_name,
                )
                continue
            logger.info(
                "%s[HeartBeatInteraction] TRIGGERED at block %d: %s(%s)%s",
                _M, block_idx, tool_name,
                json.dumps(value, ensure_ascii=False), _R,
            )
            call_id = f"heartbeat_{uuid.uuid4().hex[:8]}"
            self._emit_thinker_event(
                "tool_call",
                block_idx=block_idx,
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments=value,
            )
            item = self._execute_tool(tool_name, value, call_id=call_id)
            if item is not None:
                items.append(item)
                self._emit_thinker_event(
                    "tool_result",
                    block_idx=block_idx,
                    tool_name=item.tool_name,
                    tool_call_id=item.tool_call_id,
                    arguments=item.arguments,
                    result=item.result,
                    status=getattr(item, "status", "completed"),
                )
            triggered_now = True

        # Store thinker output and all triggered tools from this predict call
        # as a single entry.
        if (thinking or items) and self.heartbeat_cache is not None:
            entry = HeartBeatEntry(
                items=items,
                order_key=block_idx,
                thinking=thinking,
                trigger_ts_ms=trigger_ts_ms,
                elapsed_ms=elapsed_ms,
                metadata=entry_metadata,
            )
            self.heartbeat_cache.store(entry)

        # Summary: predicted queries at this block
        if items:
            queries = []
            for it in items:
                q = it.arguments.get("value") or it.arguments.get("query") or ""
                queries.append(f"{it.tool_name}={q[:80]}")
            logger.info(
                "%s[HeartBeatInteraction] block %d: %d tool(s) predicted — %s%s",
                _M, block_idx, len(items), " | ".join(queries), _R,
            )

        return triggered_now

    def _validate_tool_call_schema(self, tool_name: str, arguments: dict) -> tuple[bool, str]:
        if self.tool_registry is None:
            return False, "no_tool_registry"
        if hasattr(self.tool_registry, "has") and not self.tool_registry.has(tool_name):
            return False, "unknown_tool"
        if not hasattr(self.tool_registry, "parameters"):
            return True, "ok"
        parameters = self.tool_registry.parameters(tool_name) or {}
        properties = parameters.get("properties") if isinstance(parameters, dict) else {}
        if not isinstance(properties, dict):
            properties = {}
        allowed = set(properties.keys())
        required = parameters.get("required") if isinstance(parameters, dict) else []
        required_keys = {str(key) for key in required} if isinstance(required, list) else set()
        if allowed:
            extra_keys = sorted(str(key) for key in arguments.keys() if key not in allowed)
            if extra_keys:
                return False, f"unsupported_arguments:{','.join(extra_keys)}"
        missing_required = sorted(key for key in required_keys if key not in arguments)
        if missing_required:
            return False, f"missing_required:{','.join(missing_required)}"
        return True, "ok"

    def _has_actionable_arguments(self, tool_name: str, arguments: dict) -> bool:
        if self.tool_registry is not None and hasattr(self.tool_registry, "parameters"):
            if hasattr(self.tool_registry, "is_dynamic") and self.tool_registry.is_dynamic(tool_name):
                return True
            parameters = self.tool_registry.parameters(tool_name) or {}
            required = parameters.get("required") or []
            if not required:
                return True
            return all(self._is_actionable_value(arguments.get(key)) for key in required)
        return bool(arguments)

    @staticmethod
    def _is_actionable_value(value) -> bool:
        if value is None or value == "":
            return False
        if isinstance(value, str) and value.strip().lower() in {
            "pending",
            "unknown",
            "n/a",
            "na",
            "tbd",
            "none",
        }:
            return False
        if isinstance(value, (list, dict)) and not value:
            return False
        return True

    def _augment_tool_arguments(self, tool_name: str, arguments: dict, block_idx: int) -> dict:
        if self.tool_registry is None or not hasattr(self.tool_registry, "augment_arguments"):
            return arguments
        conversation_messages = (
            self.chat_ref.to_list()
            if self.chat_ref is not None and hasattr(self.chat_ref, "to_list")
            else []
        )
        return self.tool_registry.augment_arguments(
            tool_name,
            arguments,
            context={
                "block_idx": block_idx,
                "generation": self._turn_generation,
                "turn_id": f"async_turn:{self._turn_generation}",
                "conversation_messages": conversation_messages,
                "llm_model_name": self.tool_llm_model_name,
                "llm_base_url": self.tool_llm_base_url,
                "llm_api_key": self.tool_llm_api_key,
            },
        )

    def _call_predict_model(
        self,
        sft_prompt,
        cumulative_audio,
        history_audio_b64,
        block_idx: int,
        turn_gen: int | None = None,
    ):
        """Call the omni predict model with SFT prompt + audio.

        Constructs a single user message containing the full SFT prompt
        text (with ``<audio>`` placeholders preserved) plus all audio
        items appended as ``audio_url`` content entries — byte-identical
        to the training data format where one ``<audio>`` tag maps to
        one entry in the ``audios`` array.

        Message layout (matches training data exactly)::

            [system, user(text + <audio> tags + audio_url items), ...]

        No ``"Understood."`` injection, no message splitting, no
        ``<audio>`` → ``"[audio attached below]"`` replacement.

        Returns the prediction string, or ``None`` if the model is not
        available or the call fails.
        """
        client = self._get_client()
        if client is None:
            return None

        try:
            # Encode current turn audio as base64 WAV
            audio_b64 = self._encode_audio_base64(cumulative_audio)

            system_msg = sft_prompt["messages"][0]
            user_text = sft_prompt["messages"][1]["content"]

            # Count <audio> placeholders in the prompt text.
            # Each <audio> tag corresponds to one audio_url content item.
            # Order: history user turns first, then current user turn.
            audio_tag_count = user_text.count("<audio>")

            # Build the user content: text first, then all audio items.
            # The Qwen3-Omni processor maps <audio> tags in the text to
            # the audio_url content items in order (1st tag → 1st audio, etc.)
            user_content = [{"type": "text", "text": user_text}]

            # Append history audio items (one per [User]: <audio> line)
            for hist_b64 in history_audio_b64:
                user_content.append({
                    "type": "audio_url",
                    "audio_url": {"url": f"data:audio/wav;base64,{hist_b64}"},
                })

            # Append current turn audio (last <audio> tag)
            user_content.append({
                "type": "audio_url",
                "audio_url": {"url": f"data:audio/wav;base64,{audio_b64}"},
            })

            # Integrity check: audio count must match <audio> tag count
            actual_audio_count = len(user_content) - 1  # subtract the text item
            if actual_audio_count != audio_tag_count:
                logger.warning(
                    "%s[HeartBeatInteraction] Audio count mismatch: "
                    "%d <audio> tags vs %d audio items "
                    "(%d history + 1 current). "
                    "This may cause model misalignment!%s",
                    _M, audio_tag_count, actual_audio_count,
                    len(history_audio_b64), _R,
                )

            messages = [
                system_msg,
                {"role": "user", "content": user_content},
            ]

            if turn_gen is not None and not self._should_continue_predict(turn_gen):
                return None
            log_llm_request(
                logger, "HeartBeat.llm", self.model_name, messages,
                max_tokens=256, timeout=self.request_timeout_s,
            )
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=256,
                timeout=self.request_timeout_s,
            )

            result = response.choices[0].message.content.strip()
            logger.info(
                "%s[HeartBeatInteraction] model response: %s%s",
                _M, result, _R,
            )
            return result

        except Exception as exc:
            logger.warning(
                "%s[HeartBeatInteraction] model call failed: %s: %s%s",
                _M, type(exc).__name__, exc, _R,
            )
            return None

    @staticmethod
    def _encode_audio_base64(pcm_array: np.ndarray) -> str:
        """Encode current-turn float32 PCM as base64 WAV (16kHz mono PCM_16)."""
        from pipeline.turn_audio_history import encode_audio_base64
        return encode_audio_base64(pcm_array)

    
    def _execute_tool(self, tool_name: str, arguments: dict, call_id: str | None = None) -> ToolResultItem | None:
        """Execute one HeartBeat tool call and return the result item.

        Does NOT store to cache — the caller collects all items from one
        predict invocation and stores them as a single ``HeartBeatEntry``.
        """
        if self.heartbeat_cache is None or self.tool_registry is None:
            logger.debug("HeartBeatInteraction: no heartbeat_cache or tool_registry, skipping execute")
            return None

        if not tool_name:
            logger.warning("HeartBeatInteraction: missing tool_name, skipping")
            return None

        call_id = call_id or f"heartbeat_{uuid.uuid4().hex[:8]}"
        arguments_json = json.dumps(arguments, ensure_ascii=False)

        logger.info(
            "%s[HeartBeatInteraction] executing HeartBeat tool: %s(%s)%s",
            _M, tool_name, arguments_json, _R,
        )

        try:
            conversation_messages = (
                self.chat_ref.to_list()
                if self.chat_ref is not None and hasattr(self.chat_ref, "to_list")
                else []
            )
            result = self.tool_registry.execute(
                tool_name,
                arguments_json,
                source="heartbeat_thinking",
                context={
                    "generation": self._turn_generation,
                    "turn_id": f"async_turn:{self._turn_generation}",
                    "conversation_messages": conversation_messages,
                    "llm_model_name": self.tool_llm_model_name,
                    "llm_base_url": self.tool_llm_base_url,
                    "llm_api_key": self.tool_llm_api_key,
                },
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            result = self.tool_registry.execute(tool_name, arguments_json)

        if result is None:
            logger.warning("HeartBeatInteraction: tool %s returned None", tool_name)
            result = f"Error: tool '{tool_name}' returned no result"

        logger.info(
            "%s[HeartBeatInteraction] HeartBeat result: %s%s",
            _M, result, _R,
        )

        return ToolResultItem(
            tool_name=tool_name,
            tool_call_id=call_id,
            arguments=arguments,
            result=result,
        )

    def on_session_end(self):
        """Reset per-turn state at session boundary."""
        self._reset_turn()
        if self.heartbeat_cache is not None:
            self.heartbeat_cache.reset()
        if self.turn_audio_history is not None:
            self.turn_audio_history.reset()
        logger.debug("HeartBeatInteraction: session state reset")

    def _on_cancel(self) -> None:
        """CancelScope listener: reset turn on barge-in (race-5 fix).

        Bumps _turn_generation so inflight omni-predict workers drop their
        results via the gen check, preventing stale thinking from leaking
        into the next turn's cache.
        """
        try:
            self._reset_turn()
            logger.info("%s[HeartBeatInteraction] barge-in: reset turn (gen bump)%s", _M, _R)
        except Exception:
            logger.exception("HeartBeatInteraction: _on_cancel failed")

    def _reset_turn(self):
        """Reset per-turn state (audio buffer, block counter, triggered tools,
        consumed-detected flag)."""
        with self._turn_lock:
            self._turn_generation += 1
            self.current_turn_audio = np.array([], dtype=np.float32)
            self.last_processed_block = 0
            self._consumed_detected = False
            self._pending_drain = True
            self._turn_start_perf = None
            inflight_count = len(self._inflight)
        if inflight_count:
            logger.debug(
                "%s[HeartBeatInteraction] reset_turn: %d inflight worker(s) "
                "abandoned (results will be dropped by gen check)%s",
                _M, inflight_count, _R,
            )

    def cleanup(self):
        """Handler exit: stale async workers drop their results by generation."""
        try:
            with self._turn_lock:
                self._turn_generation += 1
        except Exception:
            pass
