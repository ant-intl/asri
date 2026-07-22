"""DashScope (阿里百炼) TTS handler — uses CosyVoice via dashscope SDK.

Streaming mode: uses SpeechSynthesizer with ResultCallback to receive PCM
audio chunks via WebSocket as they are synthesized (edge-to-edge streaming).
Falls back to synchronous call() if streaming fails.

Docs: https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api
"""

import logging
import queue
import threading
import time

import numpy as np

from pipeline.base_handler import BaseHandler
from pipeline.cancel_scope import CancelScope
from api.openai_realtime.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

# Map sample_rate to dashscope AudioFormat enum
_PCM_FORMAT_MAP = {
    8000: "PCM_8000HZ_MONO_16BIT",
    16000: "PCM_16000HZ_MONO_16BIT",
    22050: "PCM_22050HZ_MONO_16BIT",
    24000: "PCM_24000HZ_MONO_16BIT",
    44100: "PCM_44100HZ_MONO_16BIT",
    48000: "PCM_48000HZ_MONO_16BIT",
}


class DashScopeTTSHandler(BaseHandler):

    def setup(
        self,
        should_listen,
        api_key="",
        model="cosyvoice-v1",
        voice="longxiaochun",
        sample_rate=16000,
        blocksize=512,
        timeout=30.0,
        max_seconds=0.0,
        max_bytes=0,
        gen_kwargs={},
        runtime_config: RuntimeConfig | None = None,
        cancel_scope: CancelScope | None = None,
    ):
        if not api_key:
            raise ValueError(
                "DashScope TTS requires dashscope_tts_api_key. "
                "Get one at https://dashscope.console.aliyun.com/apiKey"
            )

        self.should_listen = should_listen
        self.runtime_config = runtime_config
        self.cancel_scope = cancel_scope
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.timeout_ms = int(timeout * 1000)
        self.timeout = timeout
        self._pcm_remainder = np.array([], dtype=np.int16)

        # Flow hard limits: stop synthesis if duration or bytes exceed caps.
        self._max_seconds = float(max_seconds) if max_seconds else None
        self._max_bytes = int(max_bytes) if max_bytes else None

        # Active cancel support: keep a reference to the current synthesizer
        # so _on_cancel() can call streaming_cancel() to stop synthesis
        # immediately on user interruption.
        self._active_synthesizer = None
        self._active_queue: queue.Queue | None = None
        if cancel_scope is not None and hasattr(cancel_scope, "register_cancel_listener"):
            cancel_scope.register_cancel_listener(self._on_cancel)

        # Configure dashscope SDK
        import dashscope
        dashscope.api_key = api_key

        # Resolve AudioFormat
        from dashscope.audio.tts_v2 import AudioFormat
        format_name = _PCM_FORMAT_MAP.get(sample_rate, "PCM_16000HZ_MONO_16BIT")
        self._audio_format = getattr(AudioFormat, format_name)

        logger.info(
            "DashScopeTTSHandler: model=%s, voice=%s, sample_rate=%d, format=%s, blocksize=%d",
            model, voice, sample_rate, format_name, blocksize,
        )

    def process(self, llm_sentence):
        """Synthesize text to audio and yield PCM chunks.

        Args:
            llm_sentence: text string, or (text, lang) tuple, or __END_OF_RESPONSE__ sentinel.

        Yields:
            numpy int16 audio chunks of size blocksize.
        """
        if isinstance(llm_sentence, tuple) and llm_sentence[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return

        # Parse input tuple
        language_code = None
        item_gen = None
        if isinstance(llm_sentence, tuple):
            if len(llm_sentence) >= 3:
                llm_sentence, language_code, item_gen = llm_sentence
            else:
                llm_sentence, language_code = llm_sentence[0], llm_sentence[1]
        gen = item_gen if item_gen is not None else (
            self.cancel_scope.generation if self.cancel_scope else None
        )

        _pipeline_start = getattr(self.cancel_scope, 'pipeline_start', 0) if self.cancel_scope else 0

        if not llm_sentence or not llm_sentence.strip():
            return

        cumul_tag = ""
        if _pipeline_start:
            cumul_tag = f", cumul {(time.perf_counter() - _pipeline_start) * 1000:.0f}ms"
        logger.info("DashScope TTS: request sent%s: '%s'", cumul_tag, llm_sentence[:80])

        start = time.perf_counter()
        first_chunk_logged = False
        total_bytes = 0
        self._pcm_remainder = np.array([], dtype=np.int16)

        try:
            chunk_iter = self._stream_tts(llm_sentence)
        except Exception as exc:
            logger.error("DashScope TTS streaming failed: %s, falling back to sync", exc)
            try:
                pcm_data = self._synthesize(llm_sentence)
            except Exception as e2:
                logger.error("DashScope TTS sync fallback also failed: %s", e2)
                return
            if not pcm_data:
                return
            if gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen):
                logger.info("DashScope TTS: dropping stale PCM (gen=%d, current=%d)",
                            gen, self.cancel_scope.generation)
                return
            yield from self._bytes_to_chunks(pcm_data, gen)
            return

        try:
            for pcm_bytes in chunk_iter:
                if not pcm_bytes:
                    continue

                # Flow limit check
                if self._streaming_limit_reached(start, total_bytes):
                    logger.warning("DashScope TTS: flow limit reached, stopping")
                    try:
                        self._active_synthesizer.streaming_cancel()
                    except Exception:
                        pass
                    break

                if not first_chunk_logged:
                    first_chunk_logged = True
                    ttft_ms = (time.perf_counter() - start) * 1000
                    logger.info(
                        "DashScope TTS first chunk (%.0fms%s): %d bytes",
                        ttft_ms, cumul_tag, len(pcm_bytes),
                    )

                if gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen):
                    logger.info("DashScope TTS: cancelled (interruption)")
                    return

                total_bytes += len(pcm_bytes)
                yield from self._bytes_to_chunks(pcm_bytes, gen)
        finally:
            if hasattr(chunk_iter, 'close'):
                try:
                    chunk_iter.close()
                except Exception:
                    pass

        # Flush remaining sub-blocksize tail
        if self._pcm_remainder.size > 0:
            padded = np.pad(self._pcm_remainder, (0, self.blocksize - self._pcm_remainder.size))
            self._pcm_remainder = np.array([], dtype=np.int16)
            if not (gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen)):
                yield padded

        tts_ms = (time.perf_counter() - start) * 1000
        cumul = ""
        if _pipeline_start:
            cumul = f", cumul {(time.perf_counter() - _pipeline_start) * 1000:.0f}ms"
        logger.info("DashScope TTS (%.0fms%s): total %d bytes PCM", tts_ms, cumul, total_bytes)

    def _stream_tts(self, text: str):
        """Stream TTS audio via DashScope callback, yielding PCM byte chunks."""
        from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback

        audio_queue: queue.Queue[bytes | None] = queue.Queue()
        error_holder: list[Exception] = []

        class _Callback(ResultCallback):
            def on_data(self, data: bytes) -> None:
                audio_queue.put(data)

            def on_complete(self) -> None:
                pass

            def on_error(self, message) -> None:
                error_holder.append(Exception(f"DashScope TTS error: {message}"))

            def on_close(self) -> None:
                audio_queue.put(None)

        cb = _Callback()
        synthesizer = SpeechSynthesizer(
            model=self.model,
            voice=self.voice,
            format=self._audio_format,
            callback=cb,
        )
        self._active_synthesizer = synthesizer
        self._active_queue = audio_queue

        def _run_streaming():
            try:
                synthesizer.streaming_call(text)
                synthesizer.streaming_complete(
                    complete_timeout_millis=self.timeout_ms,
                )
            except Exception as exc:
                error_holder.append(exc)
                audio_queue.put(None)

        t = threading.Thread(target=_run_streaming, daemon=True)
        t.start()

        while True:
            try:
                chunk = audio_queue.get(timeout=self.timeout)
            except queue.Empty:
                logger.warning("DashScope TTS: queue timeout, aborting")
                try:
                    synthesizer.streaming_cancel()
                except Exception:
                    pass
                break
            if chunk is None:
                break
            yield chunk

        t.join(timeout=2.0)
        self._active_synthesizer = None
        self._active_queue = None

        if error_holder:
            raise error_holder[0]

    def _streaming_limit_reached(self, start: float, emitted_bytes: int) -> bool:
        """Check if flow hard limits (time / bytes) have been exceeded."""
        if self._max_seconds is not None:
            elapsed = time.perf_counter() - start
            if elapsed >= self._max_seconds:
                logger.warning(
                    "DashScope TTS: max_seconds %.1fs reached after %.1fs",
                    self._max_seconds, elapsed,
                )
                return True
        if self._max_bytes is not None and emitted_bytes > self._max_bytes:
            logger.warning(
                "DashScope TTS: max_bytes %d exceeded by %d emitted bytes",
                self._max_bytes, emitted_bytes,
            )
            return True
        return False

    def _on_cancel(self) -> None:
        """CancelScope listener: stop active DashScope synthesis immediately.

        Called synchronously from CancelScope.cancel() on whatever thread
        triggers the cancel. Sends streaming_cancel() to the DashScope SDK
        and pushes a None sentinel into the audio queue so the main-thread
        generator exits promptly.
        """
        synthesizer = self._active_synthesizer
        if synthesizer is not None:
            try:
                synthesizer.streaming_cancel()
            except Exception:
                pass
        q = self._active_queue
        if q is not None:
            try:
                q.put_nowait(None)
            except Exception:
                pass

    def _synthesize(self, text: str) -> bytes:
        """Synchronous fallback: call DashScope CosyVoice and return full PCM."""
        from dashscope.audio.tts_v2 import SpeechSynthesizer

        synthesizer = SpeechSynthesizer(
            model=self.model,
            voice=self.voice,
            format=self._audio_format,
        )
        audio_data = synthesizer.call(text, timeout_millis=self.timeout_ms)
        if audio_data is None:
            logger.error("DashScope TTS: synthesizer returned None")
            return b""
        return audio_data

    def _bytes_to_chunks(self, pcm_bytes: bytes, gen: int | None):
        """Convert raw PCM bytes to blocksize-aligned numpy int16 chunks.

        Handles sub-blocksize tails across calls via ``_pcm_remainder``.
        """
        if not pcm_bytes:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16)
        if self._pcm_remainder.size > 0:
            audio = np.concatenate([self._pcm_remainder, audio])
            self._pcm_remainder = np.array([], dtype=np.int16)
        end = (len(audio) // self.blocksize) * self.blocksize
        for i in range(0, end, self.blocksize):
            if gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen):
                return
            yield audio[i : i + self.blocksize]
        if end < len(audio):
            self._pcm_remainder = audio[end:]
