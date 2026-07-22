"""SenseVoice ASR handler — calls remote SenseVoice HTTP API.

Uses the same API format as voice_agent_v2: sends WAV-encoded audio
in tensorFeatures format to the SenseVoice inference endpoint.

Supports two modes:
- One-shot: VAD provides complete audio segments (default pipeline mode)
- Streaming interim: periodically sends sliding-window audio for early
  partial results while the user is still speaking
"""

import base64
import io
import logging
import time
import uuid
import wave

import numpy as np
import requests

from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class SenseVoiceSTTHandler(BaseHandler):

    def setup(
        self,
        url="",
        language="zh",
        timeout=30.0,
        cancel_scope=None,
        text_output_queue=None,
        gen_kwargs={},
    ):
        self.url = url
        self.language = language
        self.timeout = timeout
        self.cancel_scope = cancel_scope
        self.headers = {
            "Content-Type": "application/json;charset=utf-8",
            "MPS-app-name": "speech-to-speech",
            "MPS-http-version": "1.0",
        }
        self.session = requests.Session()
        logger.info("SenseVoiceSTTHandler: url=%s, language=%s", url, language)

    def process(self, spoken_prompt):
        """Convert audio to text via SenseVoice API.

        Args:
            spoken_prompt: numpy int16 array of audio at 16kHz mono.

        Yields:
            (transcription_text, language_code)
        """
        if isinstance(spoken_prompt, np.ndarray):
            audio = spoken_prompt
        else:
            logger.warning("SenseVoice: unexpected input type %s", type(spoken_prompt))
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
            logger.info("SenseVoice ASR (%.0fms%s): %s", asr_ms, cumul, text.strip())
            yield (text.strip(), self.language)
        else:
            logger.debug("SenseVoice ASR (%.0fms): empty result", asr_ms)

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
        """POST WAV audio to SenseVoice API and return transcription.

        Uses the tensorFeatures body format matching voice_agent_v2:
        {
            "features": {},
            "tensorFeatures": {
                "query": {
                    "shapes": [1],
                    "stringValues": ["<base64-wav>"]
                }
            }
        }
        """
        encoded = base64.b64encode(wav_bytes).decode("utf-8")
        payload = {
            "features": {},
            "tensorFeatures": {
                "query": {
                    "shapes": [1],
                    "stringValues": [encoded],
                }
            },
        }

        headers = {**self.headers, "MPS-trace-id": str(uuid.uuid4())}

        try:
            resp = self.session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.debug("SenseVoice raw response: %s", data)
            return data.get("resultMap", {}).get("asr", "")
        except requests.Timeout:
            logger.error("SenseVoice: request timed out")
            return ""
        except Exception as e:
            logger.error("SenseVoice: request failed: %s", e)
            return ""
