"""ElevenLabs STT handler — calls ElevenLabs speech-to-text API.

Endpoint: POST /v1/speech-to-text
Auth: xi-api-key header
Request: multipart/form-data (file + model_id + language_code)
Response: JSON {"text": "..."}

Docs: https://elevenlabs.io/docs/api-reference/speech-to-text
"""

import io
import logging
import time
import wave

import numpy as np
import requests

from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class ElevenLabsSTTHandler(BaseHandler):
    """Speech-to-text handler using ElevenLabs API."""

    def setup(
        self,
        api_key="",
        model="scribe_v1",
        language_code=None,
        timeout=30.0,
        cancel_scope=None,
        text_output_queue=None,
        gen_kwargs={},
    ):
        if not api_key:
            raise ValueError(
                "ElevenLabs STT requires elevenlabs_stt_api_key in YAML config or CLI args. "
                "Get your API key at https://elevenlabs.io/app/settings/api-keys"
            )
        self.api_key = api_key
        self.model = model
        self.language_code = language_code
        self.timeout = timeout
        self.cancel_scope = cancel_scope
        self.session = requests.Session()
        logger.info(
            "ElevenLabsSTTHandler: model=%s, language=%s",
            model, language_code,
        )

    def process(self, spoken_prompt):
        """Convert audio to text via ElevenLabs STT API.

        Args:
            spoken_prompt: numpy int16 array of audio at 16kHz mono.

        Yields:
            (transcription_text, language_code)
        """
        if isinstance(spoken_prompt, np.ndarray):
            audio = spoken_prompt
        else:
            logger.warning("ElevenLabsSTT: unexpected input type %s", type(spoken_prompt))
            return

        t0 = time.perf_counter()
        wav_bytes = self._pcm_to_wav(audio)
        text = self._call_stt(wav_bytes)
        stt_ms = (time.perf_counter() - t0) * 1000

        if text and text.strip():
            cumul = ""
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info("ElevenLabsSTT (%.0fms%s): %s", stt_ms, cumul, text.strip())
            yield (text.strip(), self.language_code or "auto")
        else:
            logger.debug("ElevenLabsSTT (%.0fms): empty result", stt_ms)

    def _pcm_to_wav(self, pcm_array: np.ndarray) -> bytes:
        """Encode PCM array as WAV bytes (16kHz, mono, 16-bit)."""
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

    def _call_stt(self, wav_bytes: bytes) -> str:
        """POST WAV audio to ElevenLabs STT API and return transcription."""
        url = "https://api.elevenlabs.io/v1/speech-to-text"

        headers = {
            "xi-api-key": self.api_key,
        }

        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }
        data = {
            "model_id": self.model,
        }
        if self.language_code:
            data["language_code"] = self.language_code

        try:
            resp = self.session.post(
                url,
                files=files,
                data=data,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.debug("ElevenLabsSTT raw response: %s", result)
            return result.get("text", "")
        except requests.Timeout:
            logger.error("ElevenLabsSTT: request timed out")
            return ""
        except requests.HTTPError as e:
            logger.error("ElevenLabsSTT: HTTP error %s: %s", e.response.status_code, e.response.text[:200])
            return ""
        except Exception as e:
            logger.error("ElevenLabsSTT: request failed: %s", e)
            return ""
