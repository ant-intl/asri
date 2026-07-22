"""OpenAI Whisper STT handler — calls OpenAI-compatible transcription API.

Supports OpenAI Whisper API, faster-whisper-server, vLLM Whisper,
and other OpenAI-compatible /v1/audio/transcriptions endpoints.

Uses multipart/form-data to send audio file + model + language.
Returns standard JSON {"text": "..."}.
"""

import io
import logging
import time
import wave

import numpy as np
import requests

from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class OpenAIWhisperSTTHandler(BaseHandler):
    """Speech-to-text handler using OpenAI Whisper API format."""

    def setup(
        self,
        url="",
        api_key="",
        model="whisper-1",
        language="zh",
        timeout=30.0,
        cancel_scope=None,
        text_output_queue=None,
        gen_kwargs={},
    ):
        if not url:
            raise ValueError(
                "OpenAI Whisper STT requires openai_whisper_stt_url in YAML config or CLI args. "
                "Example: https://api.openai.com/v1/audio/transcriptions"
            )
        self.url = url
        self.api_key = api_key
        self.model = model
        self.language = language
        self.timeout = timeout
        self.cancel_scope = cancel_scope
        self.session = requests.Session()
        logger.info(
            "OpenAIWhisperSTTHandler: url=%s, model=%s, language=%s",
            url, model, language,
        )

    def process(self, spoken_prompt):
        """Convert audio to text via OpenAI Whisper API.

        Args:
            spoken_prompt: numpy int16 array of audio at 16kHz mono.

        Yields:
            (transcription_text, language_code)
        """
        if isinstance(spoken_prompt, np.ndarray):
            audio = spoken_prompt
        else:
            logger.warning("OpenAIWhisper: unexpected input type %s", type(spoken_prompt))
            return

        t0 = time.perf_counter()
        wav_bytes = self._pcm_to_wav(audio)
        text = self._call_asr(wav_bytes)
        asr_ms = (time.perf_counter() - t0) * 1000

        if text and text.strip():
            cumul = ""
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info("OpenAIWhisper ASR (%.0fms%s): %s", asr_ms, cumul, text.strip())
            yield (text.strip(), self.language)
        else:
            logger.debug("OpenAIWhisper ASR (%.0fms): empty result", asr_ms)

    def _pcm_to_wav(self, pcm_array: np.ndarray) -> bytes:
        """Encode PCM array as WAV bytes (16kHz, mono, 16-bit).

        Accepts float32 [-1,1] or int16 input.
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

    def _call_asr(self, wav_bytes: bytes) -> str:
        """POST WAV audio to OpenAI Whisper API and return transcription.

        Uses multipart/form-data format:
        - file: audio file (WAV)
        - model: model name
        - language: language code (optional)
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }
        data = {
            "model": self.model,
            "language": self.language,
        }

        try:
            resp = self.session.post(
                self.url,
                files=files,
                data=data,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.debug("OpenAIWhisper raw response: %s", result)
            return result.get("text", "")
        except requests.Timeout:
            logger.error("OpenAIWhisper: request timed out")
            return ""
        except requests.HTTPError as e:
            logger.error("OpenAIWhisper: HTTP error %s: %s", e.response.status_code, e.response.text[:200])
            return ""
        except Exception as e:
            logger.error("OpenAIWhisper: request failed: %s", e)
            return ""
