"""OmniVoice TTS handler — calls OmniVoice HTTP TTS service.

Matches the TTS service in voice_agent_v2: POST multipart form to
/tts/fast, receive streaming WAV, pipe through ffmpeg to get PCM
s16le, then yield fixed-size numpy int16 chunks.
"""

import logging
import subprocess

import numpy as np

from pipeline.base_handler import BaseHandler
from pipeline.cancel_scope import CancelScope
from api.openai_realtime.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)


class OmniVoiceTTSHandler(BaseHandler):

    def setup(
        self,
        should_listen,
        base_url="http://localhost:8864",
        ref_audio_path="",
        ref_text="",
        num_step=None,
        sample_rate=24000,
        device="cpu",
        blocksize=512,
        gen_kwargs={},
        runtime_config: RuntimeConfig | None = None,
        cancel_scope: CancelScope | None = None,
    ):
        self.should_listen = should_listen
        self.runtime_config = runtime_config
        self.cancel_scope = cancel_scope
        self.base_url = base_url.rstrip("/")
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.num_step = num_step
        self.sample_rate = sample_rate
        self.blocksize = blocksize

        # Shared session for connection pooling — avoids TCP+SSL handshake
        # per request when PrefetchHandler runs multiple workers concurrently.
        import requests as _requests
        self._http = _requests.Session()
        self._http.headers.update({"Connection": "keep-alive"})

        logger.info(
            "OmniVoiceTTSHandler: url=%s, ref_audio=%s, num_step=%s, sample_rate=%d, blocksize=%d",
            self.base_url, ref_audio_path, num_step, sample_rate, blocksize,
        )

    def process(self, llm_sentence):
        if isinstance(llm_sentence, tuple) and llm_sentence[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return

        # Accept (text, lang) or (text, lang, gen). gen is carried from the
        # LLM through LMOutputProcessor so staleness reflects the item's
        # generation, not the current one (race-2 fix).
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
        # Snapshot pipeline_start so cumul values stay consistent even
        # when a new speech-end overwrites the shared field mid-flight.
        _pipeline_start = getattr(self.cancel_scope, 'pipeline_start', 0) if self.cancel_scope else 0

        if not llm_sentence or not llm_sentence.strip():
            return

        import time as _time
        cumul_tag = ""
        if _pipeline_start:
            cumul_tag = f", cumul {(_time.perf_counter() - _pipeline_start) * 1000:.0f}ms"
        logger.info("OmniVoice TTS: request sent%s: '%s'", cumul_tag, llm_sentence[:80])

        try:
            tts_start = _time.perf_counter()
            pcm_data = self._synthesize(llm_sentence)
            tts_ms = (_time.perf_counter() - tts_start) * 1000
            cumul = ""
            if _pipeline_start:
                cumul_ms = (_time.perf_counter() - _pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info("OmniVoice TTS (%.0fms%s): got %d bytes PCM", tts_ms, cumul, len(pcm_data))
        except Exception as e:
            logger.error("OmniVoice TTS synthesis failed: %s", e)
            return

        if len(pcm_data) == 0:
            return

        istale = gen is not None and self.cancel_scope.is_stale(gen)
        if istale:
            logger.info("OmniVoice TTS: dropping stale PCM (gen=%d, current=%d)",
                        gen, self.cancel_scope.generation)
            return

        audio = np.frombuffer(pcm_data, dtype=np.int16)

        for i in range(0, len(audio), self.blocksize):
            if gen is not None and self.cancel_scope.is_stale(gen):
                logger.info("OmniVoice TTS: cancelled (interruption)")
                return
            chunk = audio[i : i + self.blocksize]
            if len(chunk) < self.blocksize:
                chunk = np.pad(chunk, (0, self.blocksize - len(chunk)))
            yield chunk

    def _synthesize(self, text: str) -> bytes:
        """POST to OmniVoice, pipe WAV through ffmpeg to get PCM s16le bytes."""

        url = f"{self.base_url}/tts/fast"
        form_data = {"text": text, "num_step": str(self.num_step or 32)}

        ffmpeg = subprocess.Popen(
            [
                "ffmpeg",
                "-probesize", "32",
                "-analyzeduration", "0",
                "-fflags", "+nobuffer+fastseek+flush_packets",
                "-flags", "low_delay",
                "-i", "pipe:0",
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        try:
            multipart = {k: (None, v) for k, v in form_data.items()}
            resp = self._http.post(url, files=multipart, timeout=60, stream=True)
            if resp.status_code != 200:
                logger.error("OmniVoice TTS request failed (%d): %s", resp.status_code, resp.text[:200])
                ffmpeg.kill()
                return b""

            # Collect all WAV data first, then use communicate() to avoid
            # pipe deadlock when ffmpeg output exceeds the OS pipe buffer.
            wav_data = b"".join(resp.iter_content(chunk_size=8192))
            pcm_data, _ = ffmpeg.communicate(input=wav_data, timeout=30)
            return pcm_data
        except Exception as e:
            logger.error("OmniVoice TTS pipeline error: %s", e)
            try:
                ffmpeg.kill()
            except Exception:
                pass
            return b""
