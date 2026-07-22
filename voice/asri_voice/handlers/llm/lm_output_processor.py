"""
LLM Output Processor

Intercepts LLM output to:
1. Extract tool calls and send them via text_output_queue
2. Forward clean text to TTS pipeline
"""

import logging
from handlers.llm.utils import clean_text
from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class LMOutputProcessor(BaseHandler):
    """
    Processes LLM output to extract tool calls and forward clean text to TTS.

    Input: (text, language_code, tools) tuples from LLM
    Output: (text, language_code) tuples to TTS
    Side effect: Sends {"type": "assistant_text", "text": ..., "tools": ...} to text_output_queue
    """

    def setup(self, text_output_queue=None, runtime_config=None, audio_output_queue=None,
              cancel_scope=None, clean_response_text=True):
        """
        Initialize the processor.

        Args:
            text_output_queue: Queue to send text messages and tool calls
            runtime_config: RuntimeConfig from realtime mode (None in other modes)
            audio_output_queue: Queue for TTS audio output, used to inject
                __RESPONSE_DONE__ directly in text-only mode (None in other modes)
            cancel_scope: CancelScope for checking if current response was cancelled
        """
        self.text_output_queue = text_output_queue
        self.runtime_config = runtime_config
        self.audio_output_queue = audio_output_queue
        self.cancel_scope = cancel_scope
        self.clean_response_text = clean_response_text

    def _is_text_only(self):
        """Check if current session is text-only (no audio output)."""
        if self.runtime_config is None:
            return False
        modalities = getattr(self.runtime_config.session, "modalities", None)
        return modalities is not None and "audio" not in modalities

    def _is_stale(self, item_gen):
        return (
            self.cancel_scope is not None
            and item_gen is not None
            and self.cancel_scope.is_stale(item_gen)
        )

    def process(self, lm_output):
        """
        Process LLM output: send text/tools to WebSocket, forward clean text to TTS.

        Args:
            lm_output: Tuple of (text, language_code, tools)

        Yields:
            Tuple of (text, language_code) for TTS
        """
        sentinel, *_ = lm_output

        if sentinel == "__TOKEN_USAGE__":
            _, input_tokens, output_tokens, *extra = lm_output
            item_gen = extra[0] if extra else None
            if self._is_stale(item_gen):
                logger.debug("Dropping stale token_usage (gen=%s)", item_gen)
                return
            if self.text_output_queue is not None:
                self.text_output_queue.put({
                    "type": "token_usage",
                    "input_tokens": input_tokens or 0,
                    "output_tokens": output_tokens or 0,
                    **({"generation": item_gen} if item_gen is not None else {}),
                })
            return

        if sentinel == "__LLM_METRICS__":
            _, metrics, _, *extra = lm_output
            item_gen = extra[0] if extra else None
            if self._is_stale(item_gen):
                logger.debug("Dropping stale llm_metrics (gen=%s)", item_gen)
                return
            if self.text_output_queue is not None:
                self.text_output_queue.put({
                    "type": "llm_metrics",
                    **metrics,
                    **({"generation": item_gen} if item_gen is not None else {}),
                })
            return

        # Text items carry generation as 4th element (gen); newer sentinels do too.
        text_chunk, language_code, tools, *extra = lm_output
        item_gen = extra[0] if extra else None

        if text_chunk == "__END_OF_RESPONSE__":
            if self._is_stale(item_gen):
                logger.debug("Dropping stale end_of_response (gen=%s)", item_gen)
                return
            if self._is_text_only() and self.audio_output_queue is not None:
                self.audio_output_queue.put(b"__RESPONSE_DONE__")
                logger.info("Text-only mode: injected __RESPONSE_DONE__ directly")
                return
            # Carry gen so downstream (PrefetchHandler) can distinguish stale
            # __END_OF_RESPONSE__ from a new response's during barge-in drain.
            yield ("__END_OF_RESPONSE__", None, item_gen)
            return

        if text_chunk == "__ITERATION_DONE__":
            if self._is_stale(item_gen):
                logger.debug("Dropping stale iteration_done (gen=%s)", item_gen)
                return
            if self.text_output_queue is not None:
                self.text_output_queue.put({
                    "type": "iteration_done",
                    **({"generation": item_gen} if item_gen is not None else {}),
                })
                logger.info("Agent loop: iteration done, signaling response boundary")
            return

        if text_chunk == "__TOOL_RESULT__":
            if self._is_stale(item_gen):
                logger.debug("Dropping stale tool_result (gen=%s)", item_gen)
                return
            tool_result_data = language_code  # repurposed arg carries tool result dict
            if self.text_output_queue is not None:
                msg = {
                    "type": "tool_result",
                    "tool_call_id": tool_result_data["tool_call_id"],
                    "name": tool_result_data["name"],
                    "content": tool_result_data["content"],
                    **({"generation": item_gen} if item_gen is not None else {}),
                }
                for _key in ("source", "cache_info"):
                    if _key in tool_result_data:
                        msg[_key] = tool_result_data[_key]
                self.text_output_queue.put(msg)
                logger.info("Agent loop: tool result for %s sent to clients", tool_result_data["name"])
            return

        if self._is_stale(item_gen):
            logger.debug("Dropping stale assistant_text before websocket/TTS (gen=%s): '%s'", item_gen, str(text_chunk)[:60])
            return

        logger.info(f"\033[32mLM processor: text='{text_chunk[:50] if text_chunk else None}', tools={tools}\033[0m")

        # Send text + tools to WebSocket clients
        if self.text_output_queue is not None:
            response_text = clean_text(text_chunk) if self.clean_response_text and text_chunk else text_chunk
            message = {
                "type": "assistant_text",
                "text": response_text,
                **({"generation": item_gen} if item_gen is not None else {}),
            }
            if tools:
                message["tools"] = tools
                tool_names = [t.get("name") or t.get("function", {}).get("name", "?") for t in tools]
                logger.info(f"Sending to clients: text='{text_chunk}', tools={tool_names}")
            else:
                logger.debug(f"Sending to clients: text='{text_chunk}' (no tools)")
            self.text_output_queue.put(message)

        # Forward clean text to TTS (yield to maintain streaming).
        # Carry gen so PrefetchHandler can distinguish stale sentences from
        # new-response sentences during a barge-in drain (race-2 fix).
        # The stale-generation check above protects both WebSocket and TTS.
        if text_chunk:
            if self._is_text_only():
                logger.debug(f"Text-only mode: skipping TTS for '{text_chunk}'")
            else:
                clean = clean_text(text_chunk)
                if clean:
                    yield (clean, language_code, item_gen)
