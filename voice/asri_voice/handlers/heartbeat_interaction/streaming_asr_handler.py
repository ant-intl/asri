"""Streaming Text Predict Handler — consumes interim ASR text for prediction.

Receives interim text blocks from the FakeStreamingASRHandler (via queue),
and for each new text:
1. Build text prompt with chat history
2. Call text LLM for tool-call prediction
3. Execute and cache triggered tools in HeartBeatCache

This handler does NOT do ASR itself — it only consumes text produced by
the streaming SenseVoice handler.

Flow:
    interim_text_queue → StreamingASRHeartbeatHandler
                            → build prompt → call vLLM → parse → execute & cache
"""

import base64
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from openai import OpenAI

from utils.utils import log_llm_request
from pipeline.base_handler import BaseHandler
from handlers.llm.thinking import disabled_thinking_extra_body
from handlers.heartbeat_interaction.history_formatter import (
    PromptTemplate,
    iter_predict_tool_calls,
    load_prompt_template,
    parse_predict_output,
)
from handlers.heartbeat_interaction.history_formatter_text import build_heartbeat_prompt_text
from handlers.heartbeat_interaction.heartbeat_cache import HeartBeatCache, HeartBeatEntry, ToolResultItem

logger = logging.getLogger(__name__)

# ANSI colour for side-branch logging
_M = "\033[35m"  # magenta
_R = "\033[0m"   # reset

# Sentinel sent to the predict handler when VAD detects end-of-speech.
TURN_END = "turn_end"


def _strip_asr_tags(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip ``<asr>`` and ``</asr>`` tags from message content.

    The prompt template wraps the current fragment with ``<asr>`` tags so
    the SFT builder can locate the ASR text and replace it with
    ``<audio>``.  Before calling the LLM, the tags are stripped so the
    LLM sees plain ASR text.
    """
    stripped: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and ("<asr>" in content or "</asr>" in content):
            new_message = dict(message)
            new_message["content"] = content.replace("<asr>", "").replace("</asr>", "")
            stripped.append(new_message)
        else:
            stripped.append(message)
    return stripped


class StreamingASRHeartbeatHandler(BaseHandler):
    """Text-mode predict handler consuming interim ASR text from streaming SenseVoice.

    Setup kwargs:
        chat_ref:  Reference to the LLM handler's Chat object (read-only).
        model_name:  Text LLM model name (e.g. Qwen3.5-122B-A10B).
        base_url:  Text LLM API base URL (e.g. http://127.0.0.1:18001/v1).
        api_key:  API key for the text LLM.
        block_duration_ms:  Block duration (for prompt context, matching ASR interval).
        request_timeout_s:  LLM API request timeout.
        cancel_scope:  Shared CancelScope for barge-in awareness.
        heartbeat_cache:  Shared HeartBeatCache for storing HeartBeat results.
        tool_registry:  ToolRegistry for executing HeartBeat tool calls.
        prompt_version:  Prompt template version (default "asri-v0").
        disable_thinking:  Disable thinking/reasoning in the text LLM.
    """

    def setup(
        self,
        chat_ref=None,
        model_name="Qwen3.5-122B-A10B",
        base_url="http://127.0.0.1:18001/v1",
        api_key="dummy",
        block_duration_ms=500,
        request_timeout_s=5.0,
        cancel_scope=None,
        heartbeat_cache=None,
        tool_registry=None,
        gen_kwargs=None,
        prompt_version="asri-v0",
        disable_thinking=True,
        blocking=True,
        max_concurrent=8,
        text_output_queue=None,
        runtime_config=None,
        tool_llm_model_name=None,
        tool_llm_base_url=None,
        tool_llm_api_key=None,
        audio_segment_buffer=None,
        fd_mode=False,
    ):
        self.chat_ref = chat_ref
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.block_duration_ms = block_duration_ms
        self.request_timeout_s = request_timeout_s
        self.cancel_scope = cancel_scope
        self.heartbeat_cache: HeartBeatCache | None = heartbeat_cache
        self.tool_registry = tool_registry
        self.prompt_template: PromptTemplate = load_prompt_template(prompt_version)
        self.disable_thinking = disable_thinking
        self.blocking: bool = bool(blocking)
        self.max_concurrent: int = max(1, int(max_concurrent))
        self.text_output_queue = text_output_queue
        self.runtime_config = runtime_config
        self.tool_llm_model_name = tool_llm_model_name
        self.tool_llm_base_url = tool_llm_base_url
        self.tool_llm_api_key = tool_llm_api_key
        self.audio_segment_buffer = audio_segment_buffer
        self.fd_mode = bool(fd_mode)

        # Per-turn state
        self._block_idx = 0
        self._last_text: str = ""  # dedup: skip if text unchanged
        self._consumed_detected: bool = False  # persist consumed signal across process() calls
        # Consume-flag drain is deferred until the first interim text of a
        # new turn.  Reason: reset_turn (triggered by TURN_END via the
        # short interim_text_queue path) often runs BEFORE the LLM main
        # path calls ``consume_all()``, so draining at reset time catches
        # nothing, and the LLM's later consume then strands a stale True
        # on the shared cache — the first interim of the next turn reads
        # it, sets ``_consumed_detected`` and skips the whole turn.  By
        # deferring the drain to the first real text of the turn, we
        # absorb whichever order the two paths ended up in.
        self._pending_drain: bool = True

        # Lazy-init LLM client
        self._llm_client = None

        # Non-blocking mode: each interim text spawns a short-lived
        # ``threading.Thread(daemon=True)`` (NOT a ThreadPoolExecutor —
        # Python 3.13's global ``_shutdown`` flag inside concurrent.futures
        # can spuriously reject new submissions after certain atexit /
        # daemon interactions, even when the process is alive).  A
        # ``Semaphore`` caps the number of in-flight LLM HTTP calls so
        # a burst of interim blocks can't flood the upstream endpoint.
        # Acquisition is non-blocking: a block is dropped immediately
        # when every slot is occupied.
        self._predict_semaphore = threading.Semaphore(self.max_concurrent)
        # ``_inflight`` tracks live worker threads so ``_reset_turn`` can
        # report / clear stale ones.  Stale results are dropped by the
        # turn-generation check, so we never wait on these threads.
        self._inflight: set[threading.Thread] = set()
        self._inflight_blocks: dict[threading.Thread, int] = {}
        self._inflight_lock = threading.Lock()
        self.replay_tool_latency_min_ms = int(os.getenv("HEARTBEAT_REPLAY_TOOL_MOCK_SIMULATED_LATENCY_MIN_MS", "20"))
        self.replay_tool_latency_max_ms = int(os.getenv("HEARTBEAT_REPLAY_TOOL_MOCK_SIMULATED_LATENCY_MAX_MS", "100"))
        self.replay_snapshot_wait_timeout_s = float(os.getenv("HEARTBEAT_REPLAY_SNAPSHOT_WAIT_TIMEOUT_S", "60"))

        # ``_turn_generation`` is bumped on every _reset_turn; stale
        # worker threads (spawned under a previous turn) check this in
        # their result-handling path and silently drop their result.
        # This means reset_turn never blocks waiting for inflight LLM
        # calls — fire-and-forget.
        self._turn_generation: int = 0
        self._turn_start_perf: float | None = None
        self._current_turn_interrupting_response: bool = False
        self._current_turn_interrupt_metadata: dict = {}
        self._logged_tool_context_source: bool = False
        # Lock held briefly during the "check-gen + check-consumed +
        # store" critical section of each result handler, and during
        # the gen-bump inside _reset_turn.  Ingestion (process) and
        # reset run in the BaseHandler thread so they don't race each
        # other, only worker threads do.
        self._turn_lock = threading.Lock()

        # State-accumulated write tools: arguments collected during
        # heartbeat_thinking, submitted for execution at TURN_END.
        self._accumulated_lock = threading.Lock()
        self._accumulated_tool_calls: dict[str, dict[str, Any]] = {}
        self._accumulated_sequence = 0

        # Race-5 fix: subscribe to CancelScope so barge-in immediately bumps
        # _turn_generation. Inflight workers then drop their results via the
        # gen check instead of storing stale thinking into the next turn's
        # cache (which would leak into the LLM's HeartbeatContext).
        if self.cancel_scope is not None and hasattr(self.cancel_scope, "register_cancel_listener"):
            self.cancel_scope.register_cancel_listener(self._on_cancel)

        logger.info(
            "%s[StreamingASR-HeartBeat] model=%s, base_url=%s, "
            "block=%dms, prompt=%s, mode=%s, max_concurrent=%d, fd_mode=%s%s",
            _M, model_name, base_url,
            block_duration_ms, prompt_version,
            "blocking" if self.blocking else "async+ordered-insert",
            self.max_concurrent,
            self.fd_mode,
            _R,
        )

    def _is_replay_trace(self) -> bool:
        return getattr(self.runtime_config, "trace_level", None) == "replay"

    def _virtual_ms_for_block(self, block_idx: int) -> int:
        return int(block_idx + 1) * int(self.block_duration_ms)

    def _wait_for_prior_replay_work(self, block_idx: int) -> None:
        """Wait for earlier replay work to materialize before snapshotting.

        This wait only collects facts into ``HeartBeatCache``.  Visibility is
        still decided later by the virtual timeline.
        """
        if not self._is_replay_trace():
            return
        deadline = time.monotonic() + max(0.0, self.replay_snapshot_wait_timeout_s)
        current = threading.current_thread()
        while True:
            with self._inflight_lock:
                prior = [
                    t
                    for t, t_block in self._inflight_blocks.items()
                    if t is not current and t_block < block_idx and t.is_alive()
                ]
            if not prior:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "[StreamingASR-HeartBeat] replay snapshot block=%d timed out waiting for %d prior worker(s)",
                    block_idx,
                    len(prior),
                )
                break
            for thread in prior:
                thread.join(timeout=min(0.2, max(0.0, remaining)))
        if self.heartbeat_cache is not None:
            remaining = self.heartbeat_cache.wait_for_pending_results(
                max(0.0, deadline - time.monotonic())
            )
            if remaining > 0:
                logger.warning(
                    "[StreamingASR-HeartBeat] replay snapshot block=%d still has %d pending tool result(s)",
                    block_idx,
                    remaining,
                )

    def _snapshot_for_block(self, block_idx: int) -> list[HeartBeatEntry]:
        if self.heartbeat_cache is None:
            return []
        if not self._is_replay_trace():
            return self.heartbeat_cache.snapshot_for_thinker()
        self._wait_for_prior_replay_work(block_idx)
        return self.heartbeat_cache.snapshot_for_thinker(
            snapshot_at_ms=self._virtual_ms_for_block(block_idx)
        )

    def wait_for_replay_idle(self, timeout_s: float | None = None) -> None:
        """Hook for replay response snapshots before consuming cache."""
        if not self._is_replay_trace():
            return
        timeout = self.replay_snapshot_wait_timeout_s if timeout_s is None else float(timeout_s)
        deadline = time.monotonic() + max(0.0, timeout)
        current = threading.current_thread()
        while True:
            with self._inflight_lock:
                inflight = [
                    t for t in self._inflight if t is not current and t.is_alive()
                ]
            if not inflight:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "[StreamingASR-HeartBeat] replay response drain timed out waiting for %d worker(s)",
                    len(inflight),
                )
                break
            for thread in inflight:
                thread.join(timeout=min(0.2, max(0.0, remaining)))
        if self.heartbeat_cache is not None:
            self.heartbeat_cache.wait_for_pending_results(
                max(0.0, deadline - time.monotonic())
            )

    def _heartbeat_tool_context(self) -> dict | None:
        """Build tool context for HeartBeat Thinking prompts.

        Realtime evaluation often registers tools server-side via
        ``tools_module``. In that mode client-supplied ``session.tools`` are
        intentionally ignored, so fall back to the server registry schemas.
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
                        "%s[StreamingASR-HeartBeat] using %d server tool schemas for prompt: %s%s",
                        _M, len(tools), names, _R,
                    )
                    self._logged_tool_context_source = True
        return context

    def _emit_thinker_event(self, event: str, **payload) -> None:
        """Send HeartBeat Thinking status to realtime/websocket clients, if present."""
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

    def _consume_audio_segment(self, block_idx: int) -> dict | None:
        """Pop the audio segment for ``block_idx`` from the shared buffer.

        Returns a dict with ``b64`` (base64-encoded int16 PCM), ``sample_rate``,
        and ``samples`` (number of int16 samples), or ``None`` if the buffer
        is not configured or no segment exists for this block.
        """
        if self.audio_segment_buffer is None:
            return None
        audio = self.audio_segment_buffer.pop(block_idx, None)
        if audio is None:
            return None
        try:
            import numpy as np
            if isinstance(audio, np.ndarray):
                if audio.dtype in (np.float32, np.float64):
                    pcm = np.clip(audio, -1.0, 1.0).astype(np.float32)
                    pcm = (pcm * 32767.0).astype(np.int16)
                else:
                    pcm = audio.astype(np.int16)
                pcm_bytes = pcm.tobytes()
            else:
                pcm_bytes = bytes(audio)
            samples = len(pcm_bytes) // 2
            b64 = base64.b64encode(pcm_bytes).decode("ascii")
            return {
                "b64": b64,
                "sample_rate": 16000,
                "samples": samples,
            }
        except Exception as exc:
            logger.warning(
                "%s[StreamingASR-HeartBeat] audio segment encode failed: %s%s",
                _M, exc, _R,
            )
            return None

    def _fd_current_turn_metadata(self) -> dict | None:
        if not self.fd_mode:
            return None
        metadata = {
            "fd_mode": True,
            "interrupting_current_response": bool(self._current_turn_interrupting_response),
            "input_relation": (
                "barge_in_during_assistant_response"
                if self._current_turn_interrupting_response
                else "normal_user_turn"
            ),
        }
        if self._current_turn_interrupt_metadata:
            metadata.update(self._current_turn_interrupt_metadata)
        return metadata

    # --------------------------------------------------------------------- #
    #  Client accessor
    # --------------------------------------------------------------------- #

    def _get_llm_client(self) -> OpenAI | None:
        if self._llm_client is None:
            try:
                self._llm_client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_retries=0,
                )
            except Exception as e:
                logger.warning("%s[StreamingASR-HeartBeat] LLM client init failed: %s%s", _M, e, _R)
                return None
        return self._llm_client

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

    # --------------------------------------------------------------------- #
    #  Main process loop — receives text (not audio!)
    # --------------------------------------------------------------------- #

    def process(self, text_input):
        """Receive interim text from streaming ASR or TURN_END signal.

        Two execution modes (controlled by ``self.blocking``):

        - **blocking=True**: the LLM is called synchronously on the
          ingestion thread.  Each interim text waits for the HTTP
          response before the next one can be processed.  Simplest
          semantics, no concurrency, useful as a baseline.

        - **blocking=False** (default): every interim text spawns a
          short-lived ``threading.Thread(daemon=True)`` worker.  A
          ``Semaphore`` (``max_concurrent``) caps in-flight HTTP
          calls; ingestion always returns immediately.  Workers
          complete out-of-order — whichever finishes first writes to
          the cache first.  Per-block ordering in the cache is
          guaranteed by passing ``block_idx`` as ``order_key`` to
          ``HeartBeatCache.store()``, which inserts by ascending key
          so a late-arriving earlier block slots in ahead of later
          blocks.

        TURN_END synchronously resets per-turn state (bumps
        ``_turn_generation``).  Inflight workers from this turn are
        detached; they either see the bumped generation at worker entry
        and skip the LLM call, or complete the call and drop the result
        at the pre-store generation check.

        This generator yields nothing — all side effects (cache
        stores) happen inside the blocking call or the worker thread.
        queue_out is a sink here.
        """
        if text_input is TURN_END or text_input == TURN_END:
            if self._block_idx > 0:
                logger.info(
                    "%s[StreamingASR-HeartBeat] TURN_END: resetting turn "
                    "(%d blocks, last_text='%s')%s",
                    _M, self._block_idx, self._last_text[:50], _R,
                )
            self._reset_turn()
            return

        # Accept (text, block_idx) tuple or plain string.
        if isinstance(text_input, tuple) and len(text_input) == 2:
            asr_text, audio_block_idx = text_input
        elif isinstance(text_input, str):
            asr_text = text_input
            audio_block_idx = self._block_idx
        else:
            return

        asr_text = asr_text.strip()
        if not asr_text:
            return

        # First real text of the turn — drain any stale consumed flag
        # left behind by the previous turn's LLM consume.  See the
        # comment on ``_pending_drain`` in setup() for the timing
        # rationale.  is_consumed() is one-shot (read clears).
        if self._pending_drain:
            self._pending_drain = False
            if self.heartbeat_cache is not None:
                if self.heartbeat_cache.is_consumed():
                    logger.info(
                        "%s[StreamingASR-HeartBeat] drained stale consumed flag "
                        "from previous turn at first interim%s",
                        _M, _R,
                    )

        # One-shot: if LLM already consumed HeartBeat cache, stop for this turn.
        if self._consumed_detected:
            return
        if self.heartbeat_cache and self.heartbeat_cache.is_consumed():
            self._consumed_detected = True
            return

        if self.cancel_scope and self.cancel_scope.discarding:
            return

        # Dedup: skip if text unchanged.
        if asr_text == self._last_text:
            logger.debug("%s[StreamingASR-HeartBeat] block %d: text unchanged, skip%s",
                         _M, self._block_idx, _R)
            return
        self._last_text = asr_text

        if self.chat_ref is None:
            return

        block_idx = audio_block_idx
        self._block_idx += 1

        logger.info(
            "%s[StreamingASR-HeartBeat] block %d %s: '%s'%s",
            _M, block_idx,
            "call" if self.blocking else "spawn",
            asr_text[:80], _R,
        )
        if getattr(self, "_turn_start_perf", None) is None:
            self._turn_start_perf = time.perf_counter()
        trigger_ts_ms = int(time.time() * 1000)
        elapsed_ms = int((time.perf_counter() - self._turn_start_perf) * 1000)
        logger.info(
            "%s[StreamingASR-Thinker] trigger block=%d ts_ms=%d elapsed_ms=%d text='%s'%s",
            _M, block_idx, trigger_ts_ms, elapsed_ms, asr_text[:160], _R,
        )
        self._emit_thinker_event(
            "trigger",
            block_idx=block_idx,
            trigger_ts_ms=trigger_ts_ms,
            elapsed_ms=elapsed_ms,
            text=asr_text,
            interrupting_current_response=self._current_turn_interrupting_response,
            fd_mode=self.fd_mode,
            interrupted_assistant_text=(
                self._current_turn_interrupt_metadata.get("interrupted_assistant_text", "")
                if self.fd_mode
                else ""
            ),
        )

        # Snapshot chat history in the ingestion thread.  Capture current
        # turn_generation so result handling can detect a reset.
        history_snapshot = list(self.chat_ref.to_list())
        turn_gen = self._turn_generation

        if self.blocking:
            # Synchronous path: call LLM inline, process result inline.
            # Each interim text blocks the ingestion thread until the
            # HTTP response returns; later interims arrive after.
            raw_response = self._call_predict_model(
                history_snapshot, asr_text, block_idx, turn_gen=turn_gen,
            )
            self._process_predict_result(
                raw_response, turn_gen, block_idx, trigger_ts_ms, elapsed_ms,
                current_text=asr_text,
            )
            return

        # Non-blocking path: spawn a daemon worker thread that tries to
        # acquire the semaphore, calls the LLM, and handles the result.
        # Ingestion returns immediately; a saturated worker drops this
        # block instead of waiting for capacity.
        worker = threading.Thread(
            target=self._predict_worker,
            args=(history_snapshot, asr_text, block_idx, turn_gen, trigger_ts_ms, elapsed_ms),
            daemon=True,
            name=f"streaming-predict-{block_idx}",
        )
        with self._inflight_lock:
            self._inflight.add(worker)
            self._inflight_blocks[worker] = block_idx
        worker.start()
        return
        yield  # unreachable; makes process a generator per BaseHandler contract

    # --------------------------------------------------------------------- #
    #  Result handling — shared by sync (blocking) and async worker
    # --------------------------------------------------------------------- #

    def _process_predict_result(
        self,
        raw_response,
        turn_gen: int,
        block_idx: int,
        trigger_ts_ms: int | None = None,
        elapsed_ms: int | None = None,
        current_text: str = "",
    ) -> None:
        """Parse LLM response, check gates under lock, store to cache.

        Shared by:
         - blocking path (called inline on ingestion thread)
         - non-blocking path (called from ``_predict_worker`` on its
           own daemon thread after the HTTP call returns)

        The turn_lock is acquired only for the atomic
        "check-gen + check-consumed + store" section so concurrent
        workers don't interleave their store operations and a
        reset_turn happening after result-parse-time is caught.
        """
        if raw_response is None:
            return
        completion_elapsed_ms = (
            int((time.perf_counter() - self._turn_start_perf) * 1000)
            if getattr(self, "_turn_start_perf", None) is not None
            else elapsed_ms
        )
        llm_completed_at_ms = completion_elapsed_ms
        if self._is_replay_trace() and isinstance(elapsed_ms, int) and isinstance(completion_elapsed_ms, int):
            real_llm_latency_ms = max(0, completion_elapsed_ms - elapsed_ms)
            llm_completed_at_ms = self._virtual_ms_for_block(block_idx) + real_llm_latency_ms
        parsed = parse_predict_output(raw_response)
        if parsed is None:
            return

        with self._turn_lock:
            if turn_gen != self._turn_generation:
                logger.debug(
                    "%s[StreamingASR-HeartBeat] block %d stale (gen %d≠%d), drop%s",
                    _M, block_idx, turn_gen, self._turn_generation, _R,
                )
                return
            if self._consumed_detected:
                return
            if self.heartbeat_cache and self.heartbeat_cache.is_consumed():
                self._consumed_detected = True
                return
            if self.cancel_scope and self.cancel_scope.discarding:
                return
            self._handle_dual_tool_prediction(
                parsed,
                block_idx,
                trigger_ts_ms=trigger_ts_ms,
                elapsed_ms=elapsed_ms,
                llm_completed_at_ms=llm_completed_at_ms,
                current_text=current_text,
            )

    def _predict_worker(self, history, asr_text, block_idx, turn_gen, trigger_ts_ms, elapsed_ms):
        """Non-blocking mode: one worker thread per interim text.

        Steps:
          1. Try once to acquire the concurrency semaphore without
             waiting. If the upstream is saturated, drop this block —
             the next interim will supersede it anyway.
          2. Early-exit if a reset already bumped the turn generation
             before the worker started its LLM call.
          3. Call the LLM.
          4. Dispatch to ``_process_predict_result`` (which does the
             gen + consumed + store checks under lock).
        """
        try:
            acquired = self._predict_semaphore.acquire(blocking=False)
            if not acquired:
                logger.info(
                    "%s[StreamingASR-HeartBeat] block %d skipped: in-flight limit reached%s",
                    _M, block_idx, _R,
                )
                return
            try:
                # If a reset happened before this worker entered, don't bother
                # calling the LLM — the result would be dropped anyway.
                if not self._should_continue_predict(turn_gen):
                    logger.debug(
                        "%s[StreamingASR-HeartBeat] block %d stale at worker entry, skip LLM%s",
                        _M, block_idx, _R,
                    )
                    return
                raw = self._call_predict_model(history, asr_text, block_idx, turn_gen=turn_gen)
                self._process_predict_result(
                    raw, turn_gen, block_idx, trigger_ts_ms, elapsed_ms,
                    current_text=asr_text,
                )
            finally:
                self._predict_semaphore.release()
        except Exception as exc:
            logger.warning(
                "%s[StreamingASR-HeartBeat] block %d worker failed: %s: %s%s",
                _M, block_idx, type(exc).__name__, exc, _R,
            )
        finally:
            with self._inflight_lock:
                current = threading.current_thread()
                self._inflight.discard(current)
                self._inflight_blocks.pop(current, None)

    # --------------------------------------------------------------------- #
    #  Model call (text-only)
    # --------------------------------------------------------------------- #

    def _call_predict_model(self, chat_messages, current_text, block_idx, turn_gen: int | None = None):
        """Call text LLM with the runtime HeartBeat prompt + current ASR text.

        Returns the prediction string, or None on failure.
        """
        logger.info(
            "%s[StreamingASR-HeartBeat] block %d _call_predict_model START on %s%s",
            _M, block_idx, threading.current_thread().name, _R,
        )
        client = self._get_llm_client()
        if client is None:
            logger.warning(
                "%s[StreamingASR-HeartBeat] block %d no LLM client, abort%s",
                _M, block_idx, _R,
            )
            return None

        try:
            heartbeat_prompt = build_heartbeat_prompt_text(
                chat_messages=chat_messages,
                current_text=current_text,
                block_idx=block_idx,
                block_duration_ms=self.block_duration_ms,
                prompt_template=self.prompt_template,
                async_context_entries=(
                    self._snapshot_for_block(block_idx)
                    if self.heartbeat_cache is not None
                    else []
                ),
                tool_context=self._heartbeat_tool_context(),
                extra_instructions=(
                    getattr(self.runtime_config, "extra_instructions", "")
                    if self.runtime_config is not None
                    else ""
                ),
                current_turn_metadata=self._fd_current_turn_metadata(),
            )

            _is_instruct = "instruct" in self.model_name.lower()
            extra_body = None
            if _is_instruct:
                extra_body = {"top_k": 20, "min_p": 0.0}
            elif self.disable_thinking:
                extra_body = disabled_thinking_extra_body(self.model_name)

            _extra_kwargs = {}
            if _is_instruct:
                _extra_kwargs = {"temperature": 0.7, "top_p": 0.8}

            if turn_gen is not None and not self._should_continue_predict(turn_gen):
                return None
            if self.audio_segment_buffer is not None:
                audio_segment = self._consume_audio_segment(block_idx)
                self._emit_thinker_event(
                    "input_messages",
                    trace_level="replay",
                    block_idx=block_idx,
                    current_fragment=current_text,
                    messages=heartbeat_prompt["messages"],
                    audio_segment_b64=audio_segment.get("b64") if audio_segment else None,
                    audio_segment_sample_rate=audio_segment.get("sample_rate") if audio_segment else None,
                    audio_segment_samples=audio_segment.get("samples") if audio_segment else None,
                )
            llm_messages = _strip_asr_tags(heartbeat_prompt["messages"])
            log_llm_request(
                logger, "StreamingASR.llm", self.model_name, llm_messages,
                max_tokens=256, timeout=self.request_timeout_s,
                extra_body=extra_body, **_extra_kwargs,
            )
            response = client.chat.completions.create(
                model=self.model_name,
                messages=llm_messages,
                max_tokens=256,
                timeout=self.request_timeout_s,
                extra_body=extra_body,
                **_extra_kwargs,
            )

            result = response.choices[0].message.content.strip()
            logger.info(
                "%s[StreamingASR-Thinker] response block=%d: %s%s",
                _M, block_idx, result, _R,
            )
            self._emit_thinker_event(
                "response",
                block_idx=block_idx,
                text=result,
            )
            return result

        except Exception as exc:
            logger.warning(
                "%s[StreamingASR-HeartBeat] LLM call failed: %s: %s%s",
                _M, type(exc).__name__, exc, _R,
            )
            return None

    # --------------------------------------------------------------------- #
    #  Tool handling
    # --------------------------------------------------------------------- #

    def _handle_dual_tool_prediction(
        self,
        parsed: dict,
        block_idx: int,
        trigger_ts_ms: int | None = None,
        elapsed_ms: int | None = None,
        llm_completed_at_ms: int | None = None,
        current_text: str = "",
    ) -> bool:
        """Process parsed thinker output, execute new tools, and cache it."""
        action = str(parsed.get("action") or ("think" if parsed.get("need_to_think", True) else "noop")).lower()
        if action not in {"noop", "think"}:
            action = "think"
        need_to_think = action == "think"
        thinking = parsed.get("thinking", "")
        if isinstance(thinking, str):
            thinking = thinking.strip()
        else:
            thinking = json.dumps(thinking, ensure_ascii=False)
        if thinking:
            logger.info(
                "%s[StreamingASR-Thinker] thinking block=%d: %s%s",
                _M, block_idx, thinking[:300], _R,
            )
            self._emit_thinker_event(
                "thinking",
                block_idx=block_idx,
                thinking=thinking,
                need_to_think=need_to_think,
            )
        if not need_to_think:
            logger.info(
                "%s[StreamingASR-Thinker] no incremental thinking needed at block=%d%s",
                _M, block_idx, _R,
            )
            self._emit_thinker_event(
                "no_think",
                block_idx=block_idx,
                need_to_think=False,
            )

        triggered_any = False
        items: list[ToolResultItem] = []
        entry_metadata = self._fd_current_turn_metadata() or {}
        for tool_name, value in iter_predict_tool_calls(parsed):
            if not isinstance(value, dict):
                continue
            if self.tool_registry is None:
                logger.info(
                    "%s[StreamingASR-HeartBeat] ignoring predicted tool call %s(%s): no tools registered%s",
                    _M,
                    tool_name,
                    json.dumps(value, ensure_ascii=False),
                    _R,
                )
                continue
            valid, reason = self._validate_tool_call_schema(tool_name, value)
            if not valid:
                logger.warning(
                    "[StreamingASR-HeartBeat] tool call error %s(%s): %s",
                    tool_name,
                    json.dumps(value, ensure_ascii=False),
                    reason,
                )
                triggered_any = True
                call_id = f"heartbeat_{uuid.uuid4().hex[:8]}"
                self._emit_thinker_event(
                    "tool_call",
                    block_idx=block_idx,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    arguments=value,
                    status="error",
                    reason=reason,
                    current_fragment=current_text,
                )
                self._emit_thinker_event(
                    "tool_result",
                    block_idx=block_idx,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    arguments=value,
                    result=f"Error: {reason}",
                    status="error",
                    current_fragment=current_text,
                )
                continue
            value = self._augment_tool_arguments(tool_name, value, block_idx, current_text)
            # Rule 1: required action arguments must be non-empty.
            if not self._has_actionable_arguments(tool_name, value):
                logger.debug(
                    "[StreamingASR-HeartBeat] %s skipped: missing actionable arguments",
                    tool_name,
                )
                continue

            triggered_any = True
            call_id = f"heartbeat_{uuid.uuid4().hex[:8]}"
            dispatched_at_ms = self._virtual_ms_for_block(block_idx)
            simulated_latency_ms = HeartBeatCache.stable_tool_latency_ms(
                tool_name=tool_name,
                arguments=value,
                min_ms=self.replay_tool_latency_min_ms,
                max_ms=self.replay_tool_latency_max_ms,
                salt=f"{block_idx}:{len(items)}",
            )
            logger.info(
                "%s[StreamingASR-HeartBeat] TRIGGERED %s at block %d: %s%s",
                _M, tool_name, block_idx, json.dumps(value, ensure_ascii=False), _R,
            )
            self._emit_thinker_event(
                "tool_call",
                block_idx=block_idx,
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments=value,
                current_fragment=current_text,
            )
            items.append(ToolResultItem(
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments=value,
                result="",
                status="pending",
                dispatched_at_ms=dispatched_at_ms,
                completed_at_ms=dispatched_at_ms + simulated_latency_ms,
                simulated_latency_ms=simulated_latency_ms,
            ))

        should_store = (not need_to_think) or thinking or items
        if should_store and self.heartbeat_cache is not None:
            self.heartbeat_cache.store(HeartBeatEntry(
                action=action,
                items=items,
                order_key=block_idx,
                thinking=thinking,
                need_to_think=need_to_think,
                trigger_ts_ms=trigger_ts_ms,
                created_at_ms=elapsed_ms,
                elapsed_ms=elapsed_ms,
                metadata=entry_metadata,
                llm_completed_at_ms=llm_completed_at_ms,
            ))

        for item in items:
            if item.status == "error":
                continue
            result = self._execute_tool(
                item.tool_name, item.arguments, block_idx, current_text,
                tool_call_id=item.tool_call_id,
            )
            parsed_result = self._parse_tool_state_result(result)
            status = self._tool_result_status(parsed_result, default="completed")
            if parsed_result and parsed_result.get("state") == "ACCUMULATED":
                self._record_accumulated_tool_call(
                    item=item,
                    result=result,
                    block_idx=block_idx,
                    current_text=current_text,
                )
            if self.heartbeat_cache is not None:
                self.heartbeat_cache.update_tool_result(
                    item.tool_call_id,
                    result,
                    status=status,
                )
            item.result = result
            item.status = status
            self._emit_thinker_event(
                "tool_result",
                block_idx=block_idx,
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                arguments=item.arguments,
                result=result,
                status=status,
                **self._tool_result_event_fields(parsed_result),
            )

        return triggered_any

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

    def _augment_tool_arguments(
        self,
        tool_name: str,
        arguments: dict,
        block_idx: int,
        current_text: str = "",
    ) -> dict:
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
                "partial_user_text": current_text,
                "llm_model_name": self.tool_llm_model_name,
                "llm_base_url": self.tool_llm_base_url,
                "llm_api_key": self.tool_llm_api_key,
            },
        )

    def _execute_tool(
        self,
        tool_name: str,
        arguments: dict,
        block_idx: int,
        current_text: str = "",
        tool_call_id: str | None = None,
        source: str = "heartbeat_thinking",
    ) -> str:
        """Execute one HeartBeat tool call and return its result text."""
        if self.tool_registry is None:
            return f"Error: no tool registry available for '{tool_name}'"

        arguments_json = json.dumps(arguments, ensure_ascii=False)

        logger.info(
            "%s[StreamingASR-HeartBeat] executing HeartBeat tool: %s(%s) block=%d source=%s%s",
            _M, tool_name, arguments_json, block_idx, source, _R,
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
                source=source,
                context={
                    "block_idx": block_idx,
                    "generation": self._turn_generation,
                    "turn_id": f"async_turn:{self._turn_generation}",
                    "conversation_messages": conversation_messages,
                    "partial_user_text": current_text,
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
            result = f"Error: tool '{tool_name}' returned no result"

        logger.info(
            "%s[StreamingASR-HeartBeat] HeartBeat result: %s%s",
            _M, result, _R,
        )

        logger.info(
            "[StreamingASR-HeartBeat] prepared cache item id=%s",
            id(self.heartbeat_cache) if self.heartbeat_cache is not None else None,
        )
        return result

    # --------------------------------------------------------------------- #
    #  State management
    # --------------------------------------------------------------------- #

    @staticmethod
    def _parse_tool_state_result(result: str | None) -> dict[str, Any] | None:
        if not isinstance(result, str):
            return None
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _tool_result_status(
        parsed_result: dict[str, Any] | None,
        default: str = "completed",
    ) -> str:
        if not parsed_result:
            return default
        status = parsed_result.get("status")
        if isinstance(status, str) and status:
            return status
        state = parsed_result.get("state")
        if isinstance(state, str) and state:
            return state.lower()
        return default

    @staticmethod
    def _tool_result_event_fields(parsed_result: dict[str, Any] | None) -> dict[str, Any]:
        if not parsed_result:
            return {}
        fields: dict[str, Any] = {}
        for key in ("state", "executed", "pending_execution_stage"):
            if key in parsed_result:
                fields[key] = parsed_result[key]
        return fields

    def _record_accumulated_tool_call(
        self,
        *,
        item: ToolResultItem,
        result: str,
        block_idx: int,
        current_text: str,
    ) -> None:
        with self._accumulated_lock:
            self._accumulated_sequence += 1
            sequence = self._accumulated_sequence
            previous = self._accumulated_tool_calls.get(item.tool_name)
            if previous and self.heartbeat_cache is not None:
                previous_call_id = str(previous.get("tool_call_id") or "")
                if previous_call_id:
                    self.heartbeat_cache.update_tool_result(
                        previous_call_id,
                        json.dumps(
                            {
                                "state": "ACCUMULATED",
                                "status": "superseded",
                                "executed": False,
                                "tool_name": item.tool_name,
                                "superseded_by_tool_call_id": item.tool_call_id,
                                "pending_execution_stage": "turn_end",
                            },
                            ensure_ascii=False,
                        ),
                        status="superseded",
                    )
            self._accumulated_tool_calls[item.tool_name] = {
                "tool_name": item.tool_name,
                "tool_call_id": item.tool_call_id,
                "arguments": dict(item.arguments),
                "result": result,
                "block_idx": block_idx,
                "current_text": current_text,
                "sequence": sequence,
            }

    def _submit_accumulated_tools_on_turn_end_locked(self) -> None:
        with self._accumulated_lock:
            pending = list(self._accumulated_tool_calls.values())
            self._accumulated_tool_calls.clear()
        if not pending:
            return

        logger.info(
            "%s[StreamingASR-HeartBeat] TURN_END: submitting %d accumulated tool(s)%s",
            _M, len(pending), _R,
        )

        def _run_call(call: dict[str, Any]) -> dict[str, Any] | None:
            tool_name = str(call.get("tool_name") or "")
            tool_call_id = str(call.get("tool_call_id") or "")
            arguments = call.get("arguments")
            if not tool_name or not tool_call_id or not isinstance(arguments, dict):
                return None
            block_idx = int(call.get("block_idx") or 0)
            current_text = str(call.get("current_text") or "")
            result = self._execute_tool(
                tool_name,
                arguments,
                block_idx,
                current_text,
                tool_call_id=tool_call_id,
                source="heartbeat_turn_end",
            )
            parsed_result = self._parse_tool_state_result(result)
            status = self._tool_result_status(parsed_result, default="completed")
            return {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "arguments": arguments,
                "block_idx": block_idx,
                "sequence": int(call.get("sequence") or 0),
                "result": result,
                "parsed_result": parsed_result,
                "status": status,
            }

        max_workers = max(1, min(len(pending), int(os.getenv("HEARTBEAT_TURN_END_TOOL_WORKERS", "8"))))
        completed: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_run_call, call) for call in pending]
            for future in as_completed(futures):
                result_item = future.result()
                if result_item is not None:
                    completed.append(result_item)

        completed.sort(key=lambda item: (int(item.get("sequence") or 0), int(item.get("block_idx") or 0)))
        for item in completed:
            tool_name = item["tool_name"]
            tool_call_id = item["tool_call_id"]
            arguments = item["arguments"]
            block_idx = item["block_idx"]
            result = item["result"]
            parsed_result = item["parsed_result"]
            status = item["status"]
            if self.heartbeat_cache is not None:
                updated = self.heartbeat_cache.update_tool_result(tool_call_id, result, status=status)
                if not updated:
                    self.heartbeat_cache.store(HeartBeatEntry(
                        action="think",
                        items=[ToolResultItem(
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            arguments=arguments,
                            result=result,
                            status=status,
                        )],
                        order_key=block_idx,
                        thinking="",
                        need_to_think=True,
                    ))
            self._emit_thinker_event(
                "tool_result",
                phase="turn_end",
                block_idx=block_idx,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
                result=result,
                status=status,
                **self._tool_result_event_fields(parsed_result),
            )

    def _on_cancel(self) -> None:
        """CancelScope listener: reset turn on barge-in (race-5 fix).

        Called synchronously from CancelScope.cancel() on whatever thread
        triggers the cancel (router thread / VAD thread). Bumps
        _turn_generation so inflight HeartBeat workers drop their results
        via the gen check, preventing stale thinking from leaking into the
        next turn's cache.
        """
        try:
            self._reset_turn()
            if self.fd_mode:
                self._current_turn_interrupting_response = True
                if self.cancel_scope is not None and hasattr(self.cancel_scope, "last_interrupt_metadata"):
                    self._current_turn_interrupt_metadata = self.cancel_scope.last_interrupt_metadata()
                else:
                    self._current_turn_interrupt_metadata = {}
            logger.info("%s[StreamingASR-HeartBeat] barge-in: reset turn (gen bump)%s", _M, _R)
        except Exception:
            logger.exception("StreamingASR-HeartBeat: _on_cancel failed")

    def _reset_turn(self):
        """Reset per-turn state — fire-and-forget with no inflight wait.

        This is called from the ingestion thread on TURN_END (or from
        session teardown).  We:

        1. Bump ``_turn_generation`` inside ``_turn_lock`` so any
           worker holding or about to acquire the lock sees the new
           generation and drops its result before touching the cache.
           Workers that have not started the LLM call will also see the
           bumped generation at their entry check and skip the call
           entirely.
        2. Clear per-turn bookkeeping.
        3. Mark ``_pending_drain`` so the stale consumed-flag drain
           happens at the first interim text of the NEXT turn (the
           LLM main path often consumes AFTER this reset runs).

        We DO NOT wait on inflight worker threads or try to cancel
        them — they are daemon threads, their results are discarded
        via the generation check, and the OS reaps them when they
        finish their HTTP call.  The ``_inflight`` set is left alone;
        workers remove themselves on exit.
        """
        if self._is_replay_trace():
            self.wait_for_replay_idle(timeout_s=self.replay_snapshot_wait_timeout_s)
            if self.heartbeat_cache is not None:
                self.heartbeat_cache.set_response_snapshot_at_ms(
                    int(self._block_idx) * int(self.block_duration_ms)
                )
        # Submit accumulated write tools before resetting turn state
        self._submit_accumulated_tools_on_turn_end_locked()
        with self._turn_lock:
            self._turn_generation += 1
            self._block_idx = 0
            self._last_text = ""
            self._consumed_detected = False
            self._turn_start_perf = None
            self._current_turn_interrupting_response = False
            self._current_turn_interrupt_metadata = {}
            # Defer the consumed-flag drain to the first interim text of
            # the next turn — LLM consume often lands AFTER reset, so
            # draining here catches nothing.  See setup() comment.
            self._pending_drain = True
            inflight_count = len(self._inflight)

        if inflight_count:
            logger.debug(
                "%s[StreamingASR-HeartBeat] reset_turn: %d inflight worker(s) "
                "abandoned (results will be dropped by gen check)%s",
                _M, inflight_count, _R,
            )

    def on_session_end(self):
        """Reset state at session boundary."""
        # _reset_turn bumps generation so any inflight worker from the
        # ending session drops its result.
        self._reset_turn()
        if self.heartbeat_cache is not None:
            self.heartbeat_cache.reset()
        logger.debug("[StreamingASR-HeartBeat] session state reset")

    def cleanup(self):
        """Handler exit.  Daemon worker threads are reaped by the OS —
        nothing to explicitly shutdown."""
        # Bump generation one last time so any still-running worker
        # drops its result.  No executor to shutdown anymore.
        try:
            with self._turn_lock:
                self._turn_generation += 1
        except Exception:
            pass
