"""OpenAI TTS handler — calls OpenAI-compatible speech synthesis API.

Supports OpenAI TTS API, Azure TTS, Edge-TTS-Server, and other
OpenAI-compatible /v1/audio/speech endpoints.

Uses POST /v1/audio/speech with JSON body:
{
    "model": "tts-1",
    "input": "Hello world",
    "voice": "alloy",
    "response_format": "pcm"
}

Receives streaming PCM audio and yields numpy chunks as they arrive
(edge-to-edge streaming: first HTTP chunk → first audio playback).
"""

from __future__ import annotations

import logging
import time as _time

import numpy as np
import requests

from api.openai_realtime.runtime_config import RuntimeConfig
from pipeline.base_handler import BaseHandler
from pipeline.cancel_scope import CancelScope

logger = logging.getLogger(__name__)


class OpenAITTSHandler(BaseHandler):
    """Text-to-speech handler using OpenAI TTS API format."""

    def setup(
        self,
        should_listen,
        base_url="",
        api_key="",
        model="tts-1",
        voice="alloy",
        speed=1.0,
        timeout=30.0,
        sample_rate=16000,
        blocksize=512,
        gen_kwargs={},
        runtime_config: RuntimeConfig | None = None,
        cancel_scope: CancelScope | None = None,
    ):
        if not base_url:
            raise ValueError(
                "OpenAI TTS requires openai_tts_base_url in YAML config or CLI args. "
                "Example: https://api.openai.com/v1"
            )
        self.should_listen = should_listen
        self.runtime_config = runtime_config
        self.cancel_scope = cancel_scope
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.speed = speed
        self.timeout = timeout
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.session = requests.Session()
        self._pcm_remainder = np.array([], dtype=np.int16)

        # Active cancel: save response reference so _on_cancel can close the
        # HTTP stream immediately on user interruption.
        self._active_response: requests.Response | None = None
        if cancel_scope is not None and hasattr(cancel_scope, "register_cancel_listener"):
            cancel_scope.register_cancel_listener(self._on_cancel)

        logger.info(
            "OpenAITTSHandler: url=%s, model=%s, voice=%s, sample_rate=%d",
            self.base_url, self.model, self.voice, self.sample_rate,
        )

    def process(self, llm_sentence):
        if isinstance(llm_sentence, tuple) and llm_sentence[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return

        # Accept (text, lang) or (text, lang, gen)
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
        logger.info("OpenAI TTS: request sent%s: '%s'", cumul_tag, llm_sentence[:80])

        start = _time.perf_counter()
        first_chunk_logged = False
        total_bytes = 0
        self._pcm_remainder = np.array([], dtype=np.int16)

        try:
            pcm_iter = self._stream_tts_request(llm_sentence)
        except Exception as exc:
            logger.error("OpenAI TTS synthesis failed: %s", exc)
            return

        try:
            for pcm_chunk in pcm_iter:
                if not pcm_chunk:
                    continue

                # Log first chunk latency
                if not first_chunk_logged:
                    first_chunk_logged = True
                    ttft_ms = (_time.perf_counter() - start) * 1000
                    logger.info(
                        "OpenAI TTS first chunk (%.0fms%s): %d bytes",
                        ttft_ms, cumul_tag, len(pcm_chunk),
                    )

                # Check cancellation before yielding
                if gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen):
                    logger.info("OpenAI TTS: cancelled (interruption)")
                    return

                total_bytes += len(pcm_chunk)
                yield from self._bytes_to_chunks(pcm_chunk, gen)
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
            # HTTP stream closed by _on_cancel — normal cancellation path
            logger.info("OpenAI TTS: stream closed by cancellation")
        finally:
            # Ensure HTTP connection is released
            if hasattr(pcm_iter, 'close'):
                try:
                    pcm_iter.close()
                except Exception:
                    pass
            self._active_response = None

        # Flush any remaining sub-blocksize tail
        if self._pcm_remainder.size > 0:
            padded = np.pad(self._pcm_remainder, (0, self.blocksize - self._pcm_remainder.size))
            self._pcm_remainder = np.array([], dtype=np.int16)
            if not (gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen)):
                yield padded

        tts_ms = (_time.perf_counter() - start) * 1000
        cumul = ""
        if pipeline_start:
            cumul = f", cumul {(_time.perf_counter() - pipeline_start) * 1000:.0f}ms"
        logger.info("OpenAI TTS (%.0fms%s): total %d bytes PCM", tts_ms, cumul, total_bytes)

    def _stream_tts_request(self, text: str):
        """POST text to TTS API, return streaming PCM chunk iterator."""
        url = f"{self.base_url}/audio/speech"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "speed": self.speed,
            "response_format": "pcm",
        }
        resp = self.session.post(
            url, json=payload, headers=headers,
            timeout=self.timeout, stream=True,
        )
        resp.raise_for_status()
        self._active_response = resp
        return resp.iter_content(chunk_size=4096)

    def _on_cancel(self) -> None:
        """CancelScope listener: close the active HTTP stream immediately.

        Called synchronously from CancelScope.cancel(). Closing the response
        causes iter_content to raise ConnectionError, which breaks the
        generator loop in process() and stops playback promptly.
        """
        resp = self._active_response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

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
