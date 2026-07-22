"""DashScope (阿里百炼) STT handler — uses Paraformer via dashscope SDK.

Non-streaming mode: receives complete audio from VAD, writes temp WAV,
calls Recognition.call() for synchronous transcription.

Docs: https://help.aliyun.com/zh/model-studio/paraformer-real-time-speech-recognition-python-sdk
"""

import io
import logging
import os
import tempfile
import time
import wave

import numpy as np

from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class DashScopeSTTHandler(BaseHandler):

    def setup(
        self,
        api_key="",
        model="paraformer-realtime-v2",
        sample_rate=16000,
        language_hints="zh,en",
        timeout=30.0,
        cancel_scope=None,
        text_output_queue=None,
        gen_kwargs={},
    ):
        if not api_key:
            raise ValueError(
                "DashScope STT requires dashscope_stt_api_key. "
                "Get one at https://dashscope.console.aliyun.com/apiKey"
            )

        self.api_key = api_key
        self.model = model
        self.sample_rate = sample_rate
        self.language_hints = [h.strip() for h in language_hints.split(",") if h.strip()] if language_hints else ["zh"]
        self.timeout = timeout
        self.cancel_scope = cancel_scope

        # Configure dashscope SDK
        import dashscope
        dashscope.api_key = api_key

        # Pre-create Recognition instance (reusable across calls)
        from dashscope.audio.asr import Recognition
        self._recognition = Recognition(
            model=model,
            format="wav",
            sample_rate=sample_rate,
            language_hints=self.language_hints,
            callback=None,
        )

        logger.info(
            "DashScopeSTTHandler: model=%s, sample_rate=%d, languages=%s",
            model, sample_rate, self.language_hints,
        )

    def process(self, spoken_prompt):
        """Convert audio to text via DashScope Paraformer API.

        Args:
            spoken_prompt: numpy int16 array of audio at 16kHz mono.

        Yields:
            (transcription_text, language_code)
        """
        if isinstance(spoken_prompt, np.ndarray):
            audio = spoken_prompt
        else:
            logger.warning("DashScope STT: unexpected input type %s", type(spoken_prompt))
            return

        t0 = time.perf_counter()
        wav_bytes = self._pcm_to_wav(audio)

        # Write to temp file (Recognition.call requires file path)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name

            text = self._call_asr(tmp_path)
            asr_ms = (time.perf_counter() - t0) * 1000

            if text and text.strip():
                cumul = ""
                if self.cancel_scope and self.cancel_scope.pipeline_start:
                    cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                    cumul = f", cumul {cumul_ms:.0f}ms"
                logger.info("DashScope ASR (%.0fms%s): %s", asr_ms, cumul, text.strip())
                yield (text.strip(), "zh")
            else:
                logger.debug("DashScope ASR (%.0fms): empty result", asr_ms)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _pcm_to_wav(self, pcm_array: np.ndarray) -> bytes:
        """Encode PCM array as WAV bytes."""
        if pcm_array.dtype in (np.float32, np.float64):
            pcm_array = np.clip(pcm_array * 32767, -32768, 32767).astype(np.int16)
        else:
            pcm_array = pcm_array.astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_array.tobytes())
        return buf.getvalue()

    def _call_asr(self, file_path: str) -> str:
        """Call DashScope Recognition API and return transcription text."""
        from http import HTTPStatus
        try:
            result = self._recognition.call(file_path)
            if result.status_code == HTTPStatus.OK:
                sentences = result.get_sentence()
                if isinstance(sentences, list):
                    return " ".join(s.get("text", "") for s in sentences if isinstance(s, dict))
                elif isinstance(sentences, dict):
                    return sentences.get("text", "")
                return str(sentences) if sentences else ""
            else:
                logger.error("DashScope ASR failed (%d): %s", result.status_code, result.message)
                return ""
        except Exception as e:
            logger.error("DashScope ASR error: %s", e)
            return ""
