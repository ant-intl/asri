"""ElevenLabs TTS handler — calls ElevenLabs text-to-speech API.

Endpoint: POST /v1/text-to-speech/{voice_id}
Auth: xi-api-key header
Response: MP3/PCM audio stream (configurable output_format)

Docs: https://elevenlabs.io/docs/api-reference/text-to-speech
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

# ElevenLabs output format → (sample_rate, channels, encoding)
OUTPUT_FORMATS = {
    "pcm_16000": (16000, 1, "pcm"),
    "pcm_22050": (22050, 1, "pcm"),
    "pcm_24000": (24000, 1, "pcm"),
    "pcm_44100": (44100, 1, "pcm"),
    "mp3_44100_128": (44100, 1, "mp3"),
    "mp3_44100_192": (44100, 1, "mp3"),
}


class ElevenLabsTTSHandler(BaseHandler):
    """Text-to-speech handler using ElevenLabs API."""

    def setup(
        self,
        should_listen,
        api_key="",
        voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel (default)
        model="eleven_multilingual_v2",
        output_format="pcm_16000",
        timeout=30.0,
        sample_rate=16000,
        blocksize=512,
        gen_kwargs={},
        runtime_config: RuntimeConfig | None = None,
        cancel_scope: CancelScope | None = None,
    ):
        if not api_key:
            raise ValueError(
                "ElevenLabs TTS requires elevenlabs_tts_api_key in YAML config or CLI args. "
                "Get your API key at https://elevenlabs.io/app/settings/api-keys"
            )
        self.should_listen = should_listen
        self.runtime_config = runtime_config
        self.cancel_scope = cancel_scope
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.output_format = output_format
        self.timeout = timeout
        self.blocksize = blocksize

        # Determine sample rate from output_format
        if output_format in OUTPUT_FORMATS:
            self.sample_rate, _, self._encoding = OUTPUT_FORMATS[output_format]
        else:
            self.sample_rate = sample_rate
            self._encoding = "pcm"

        self.session = requests.Session()
        logger.info(
            "ElevenLabsTTSHandler: voice=%s, model=%s, format=%s, sample_rate=%d",
            voice_id, model, output_format, self.sample_rate,
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
        logger.info("ElevenLabs TTS: request sent%s: '%s'", cumul_tag, llm_sentence[:80])

        start = _time.perf_counter()
        try:
            audio_data = self._synthesize(llm_sentence)
        except Exception as exc:
            logger.error("ElevenLabs TTS synthesis failed: %s", exc)
            return

        if gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen):
            logger.info("ElevenLabs TTS: dropping stale audio (gen=%d, current=%d)", gen, self.cancel_scope.generation)
            return

        tts_ms = (_time.perf_counter() - start) * 1000
        cumul = ""
        if pipeline_start:
            cumul = f", cumul {(_time.perf_counter() - pipeline_start) * 1000:.0f}ms"
        logger.info("ElevenLabs TTS (%.0fms%s): got %d bytes", tts_ms, cumul, len(audio_data))

        yield from self._audio_to_chunks(audio_data, gen)

    def _synthesize(self, text: str) -> bytes:
        """POST text to ElevenLabs TTS API and return audio bytes."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"

        headers = {
            "Accept": "audio/mpeg" if self._encoding == "mp3" else "audio/pcm",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key,
        }

        payload = {
            "text": text,
            "model_id": self.model,
            "output_format": self.output_format,
        }

        resp = self.session.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.timeout,
            stream=True,
        )
        resp.raise_for_status()

        chunks = []
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                chunks.append(chunk)

        return b"".join(chunks)

    def _audio_to_chunks(self, audio_data: bytes, gen: int | None):
        """Convert audio bytes to numpy chunks, respecting cancellation.

        For PCM output, directly converts to int16 numpy array.
        For MP3 output, logs a warning (MP3 decoding not implemented).
        """
        if not audio_data:
            return

        if self._encoding == "mp3":
            logger.error(
                "ElevenLabs TTS: MP3 output received but decoding not implemented. "
                "Please use a PCM output_format (e.g., pcm_16000)."
            )
            return

        # PCM decoding
        audio = np.frombuffer(audio_data, dtype=np.int16)
        for i in range(0, len(audio), self.blocksize):
            if gen is not None and self.cancel_scope and self.cancel_scope.is_stale(gen):
                logger.info("ElevenLabs TTS: cancelled (interruption)")
                return
            chunk = audio[i : i + self.blocksize]
            if len(chunk) < self.blocksize:
                chunk = np.pad(chunk, (0, self.blocksize - len(chunk)))
            yield chunk
