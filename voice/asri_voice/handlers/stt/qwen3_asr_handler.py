"""Qwen3-ASR handler — calls vLLM-hosted Qwen3-ASR via OpenAI transcriptions API."""

import io
import logging
import re
import time
import wave

import httpx
import numpy as np

from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)

# Qwen3-ASR output format: "language English<asr_text>Hello world."
_TEXT_RE = re.compile(r"^language\s+(\S+)\s*<asr_text>(.*)$", re.DOTALL)


def _normalize_language(lang: str) -> str:
    lang = (lang or "").strip().lower()
    if lang in ("english", "en"):
        return "en"
    if lang in ("chinese", "zh", "mandarin"):
        return "zh"
    return lang or "zh"


def _parse_asr_text(raw: str) -> tuple[str, str]:
    """Parse Qwen3-ASR output into (language_code, text).

    Input:  ``language English<asr_text>Two.``
    Output: ``("en", "Two.")``
    """
    if not raw:
        return ("zh", "")
    raw = raw.strip()
    m = _TEXT_RE.match(raw)
    if m:
        lang = _normalize_language(m.group(1))
        text = m.group(2).strip()
        return (lang, text)
    # Fallback: no language tag found, return as-is
    logger.debug("Qwen3-ASR: could not parse language tag from: %s", raw[:100])
    return ("zh", raw)


def _pcm_to_wav_bytes(pcm_array: np.ndarray) -> bytes:
    """Encode PCM array as WAV bytes (16kHz, mono, 16-bit).

    Accepts int16 or float32/float64 arrays. Float arrays are scaled to int16.
    """
    if pcm_array.dtype == np.float32 or pcm_array.dtype == np.float64:
        pcm_array = np.clip(pcm_array * 32767, -32768, 32767).astype(np.int16)
    else:
        pcm_array = pcm_array.astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm_array.tobytes())
    return buf.getvalue()


class Qwen3ASRSTTHandler(BaseHandler):
    """STT handler using Qwen3-ASR via vLLM OpenAI-compatible transcriptions API.

    Accepts numpy int16 audio (16kHz mono), converts to WAV, sends to vLLM
    transcriptions endpoint, and yields (text, language_code) tuples.
    """

    def setup(
        self,
        base_url="",
        model_name="",
        timeout=30.0,
        cancel_scope=None,
        text_output_queue=None,
        gen_kwargs=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.cancel_scope = cancel_scope
        self._transcriptions_url = f"{self.base_url}/v1/audio/transcriptions"
        self._http = httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0))
        logger.info(
            "Qwen3ASRSTTHandler: url=%s, model=%s",
            self.base_url,
            self.model_name,
        )

    def process(self, spoken_prompt):
        """Convert audio to text via Qwen3-ASR vLLM API.

        Args:
            spoken_prompt: numpy int16 array of audio at 16kHz mono.

        Yields:
            (transcription_text, language_code)
        """
        if isinstance(spoken_prompt, np.ndarray):
            audio = spoken_prompt
        else:
            logger.warning("Qwen3-ASR: unexpected input type %s", type(spoken_prompt))
            return

        t0 = time.perf_counter()
        wav_bytes = _pcm_to_wav_bytes(audio)
        raw_text = self._call_asr(wav_bytes)
        lang, text = _parse_asr_text(raw_text)
        asr_ms = (time.perf_counter() - t0) * 1000

        if text:
            cumul = ""
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info("Qwen3-ASR (%.0fms%s, lang=%s): %s", asr_ms, cumul, lang, text)
            yield (text, lang)
        else:
            logger.debug("Qwen3-ASR (%.0fms): empty result (raw=%s)", asr_ms, raw_text[:80] if raw_text else "None")

    def _pcm_to_wav(self, pcm_array: np.ndarray) -> bytes:
        """Encode PCM array as WAV bytes (16kHz, mono, 16-bit)."""
        return _pcm_to_wav_bytes(pcm_array)

    def _call_asr(self, wav_bytes: bytes) -> str:
        """POST WAV audio to Qwen3-ASR vLLM transcriptions endpoint.

        Returns the raw ``text`` field from the transcription response,
        or empty string on failure.
        """
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model": self.model_name}

        try:
            resp = self._http.post(
                self._transcriptions_url,
                files=files,
                data=data,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.debug("Qwen3-ASR raw response: %s", result)
            return result.get("text", "")
        except httpx.TimeoutException:
            logger.error("Qwen3-ASR: request timed out")
            return ""
        except Exception as e:
            logger.error("Qwen3-ASR: request failed: %s", e)
            return ""
