"""Qwen3-TTS handler using vLLM-Omni streaming PCM output."""

from __future__ import annotations

import logging
import time as _time

import numpy as np

from handlers.tts.qwen3_tts_handler import Qwen3TTSHandler
from pipeline.streaming_prefetch_handler import SUPPRESS_TTS_PLAYING_NOTE

logger = logging.getLogger(__name__)


class _LinearPCMResampler:
    """Small stateful mono int16 resampler for streaming PCM chunks."""

    def __init__(self, source_rate: int, target_rate: int):
        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        self._buffer = np.array([], dtype=np.float32)
        self._buffer_start = 0.0
        self._total_in = 0
        self._next_out_at = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples is None or len(samples) == 0:
            return np.array([], dtype=np.int16)
        if self.source_rate == self.target_rate:
            return samples.astype(np.int16, copy=False)

        incoming = samples.astype(np.float32, copy=False)
        if len(self._buffer) == 0:
            self._buffer_start = float(self._total_in)
            self._buffer = incoming
        else:
            self._buffer = np.concatenate([self._buffer, incoming])
        self._total_in += len(incoming)

        max_source_at = self._buffer_start + len(self._buffer) - 1
        if self._next_out_at > max_source_at:
            return np.array([], dtype=np.int16)

        step = self.source_rate / self.target_rate
        positions = np.arange(self._next_out_at, max_source_at + 1e-6, step, dtype=np.float64)
        if len(positions) == 0:
            return np.array([], dtype=np.int16)

        local_positions = positions - self._buffer_start
        values = np.interp(local_positions, np.arange(len(self._buffer)), self._buffer)
        self._next_out_at = float(positions[-1] + step)

        keep_from = max(0, int(np.floor(self._next_out_at - self._buffer_start)) - 1)
        if keep_from > 0:
            self._buffer = self._buffer[keep_from:]
            self._buffer_start += keep_from

        return np.clip(np.rint(values), -32768, 32767).astype(np.int16)


class Qwen3TTSStreamingHandler(Qwen3TTSHandler):
    """Qwen3-TTS/vLLM-Omni TTS with true HTTP streaming PCM output.

    The existing ``qwen3_tts`` handler keeps using ``stream=false`` and full-WAV
    decode. This handler is a separate ``tts`` choice so the old path remains
    unchanged.
    """

    def setup(
        self,
        should_listen,
        source_sample_rate=24000,
        network_chunk_bytes=4096,
        idle_timeout=3.0,
        send_speed=False,
        streaming_source_sample_rate=None,
        streaming_network_chunk_bytes=None,
        streaming_idle_timeout=None,
        streaming_send_speed=None,
        **kwargs,
    ):
        if streaming_source_sample_rate is not None:
            source_sample_rate = streaming_source_sample_rate
        if streaming_network_chunk_bytes is not None:
            network_chunk_bytes = streaming_network_chunk_bytes
        if streaming_idle_timeout is not None:
            idle_timeout = streaming_idle_timeout
        if streaming_send_speed is not None:
            send_speed = streaming_send_speed
        self.streaming_source_sample_rate = int(source_sample_rate)
        self.streaming_network_chunk_bytes = int(network_chunk_bytes)
        self.streaming_idle_timeout = float(idle_timeout) if idle_timeout else None
        self.streaming_send_speed = bool(send_speed)
        super().setup(should_listen, **kwargs)
        logger.info(
            "Qwen3TTSStreamingHandler: source_sample_rate=%d, target_sample_rate=%d, network_chunk=%d, idle_timeout=%s",
            self.streaming_source_sample_rate,
            self.sample_rate,
            self.streaming_network_chunk_bytes,
            self.streaming_idle_timeout,
        )

    def process(self, llm_sentence):
        if isinstance(llm_sentence, tuple) and llm_sentence[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return

        item_gen = None
        if isinstance(llm_sentence, tuple):
            if len(llm_sentence) >= 3:
                llm_sentence, _lang, item_gen = llm_sentence
            else:
                llm_sentence = llm_sentence[0]
        gen = item_gen if item_gen is not None else (
            self.cancel_scope.generation if self.cancel_scope else None
        )
        pipeline_start = getattr(self.cancel_scope, "pipeline_start", 0) if self.cancel_scope else 0

        if not llm_sentence or not llm_sentence.strip():
            return

        cumul_tag = ""
        if pipeline_start:
            cumul_tag = f", cumul {(_time.perf_counter() - pipeline_start) * 1000:.0f}ms"
        logger.info("Qwen3-TTS streaming: request sent%s: '%s'", cumul_tag, llm_sentence[:80])

        start = _time.perf_counter()
        first_audio_logged = False
        playing_noted = False
        source_leftover = b""
        target_pending = np.array([], dtype=np.int16)
        resampler = _LinearPCMResampler(self.streaming_source_sample_rate, self.sample_rate)

        speed = self.speed if self.streaming_send_speed else None
        try:
            byte_iter = self.client.stream_pcm_bytes(
                llm_sentence,
                speed=speed,
                extra_body=self._request_extra_body(),
                chunk_size=self.streaming_network_chunk_bytes,
                idle_timeout=self.streaming_idle_timeout,
            )
            for raw_chunk in byte_iter:
                if self._is_stale(gen):
                    logger.info("Qwen3-TTS streaming: cancelled before consuming next audio chunk")
                    return

                source_leftover += raw_chunk
                usable = len(source_leftover) - (len(source_leftover) % 2)
                if usable <= 0:
                    continue
                source_samples = np.frombuffer(source_leftover[:usable], dtype=np.int16)
                source_leftover = source_leftover[usable:]
                target_samples = resampler.process(source_samples)
                if len(target_samples) == 0:
                    continue

                if not first_audio_logged:
                    first_audio_logged = True
                    logger.info(
                        "Qwen3-TTS streaming TTFA %.0fms (%d source samples)",
                        (_time.perf_counter() - start) * 1000,
                        len(source_samples),
                    )

                if not playing_noted:
                    self._note_playing_text(llm_sentence, gen)
                    playing_noted = True

                target_pending = np.concatenate([target_pending, target_samples])
                while len(target_pending) >= self.blocksize:
                    if self._is_stale(gen):
                        logger.info("Qwen3-TTS streaming: cancelled (interruption)")
                        return
                    chunk = target_pending[: self.blocksize]
                    target_pending = target_pending[self.blocksize :]
                    yield chunk

            if len(source_leftover) >= 2:
                target_samples = resampler.process(np.frombuffer(source_leftover, dtype=np.int16))
                target_pending = np.concatenate([target_pending, target_samples])

            if len(target_pending) > 0:
                if self._is_stale(gen):
                    logger.info("Qwen3-TTS streaming: dropping stale final chunk")
                    return
                if not playing_noted:
                    self._note_playing_text(llm_sentence, gen)
                if len(target_pending) < self.blocksize:
                    target_pending = np.pad(target_pending, (0, self.blocksize - len(target_pending)))
                yield target_pending[: self.blocksize]

            logger.info(
                "Qwen3-TTS streaming done %.0fms",
                (_time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            logger.error("Qwen3-TTS streaming synthesis failed: %s", exc)
            return

    def _note_playing_text(self, text: str, gen: int | None) -> None:
        if SUPPRESS_TTS_PLAYING_NOTE.get():
            return
        if self.cancel_scope is None or not text:
            return
        if hasattr(self.cancel_scope, "note_assistant_text"):
            self.cancel_scope.note_assistant_text(text, gen)

    def _is_stale(self, gen: int | None) -> bool:
        return bool(gen is not None and self.cancel_scope is not None and self.cancel_scope.is_stale(gen))
