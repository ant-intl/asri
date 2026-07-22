"""VoxCPM2 TTS handler via vLLM Omni OpenAI-compatible speech API."""

from __future__ import annotations

import logging
import time as _time

import numpy as np

from api.openai_realtime.runtime_config import RuntimeConfig
from handlers.tts.vllm_omni_tts_client import VLLMOmniTTSClient, ref_audio_payload
from pipeline.base_handler import BaseHandler
from pipeline.cancel_scope import CancelScope

logger = logging.getLogger(__name__)


class VoxCPM2TTSHandler(BaseHandler):
    """Text-to-speech handler for deployed VoxCPM2/vLLM Omni services."""

    def setup(
        self,
        should_listen,
        base_url=None,
        model="openbmb/VoxCPM2",
        voice="customer_female_7_omnivoice",
        api_key=None,
        speed=1.0,
        timeout=60.0,
        sample_rate=16000,
        blocksize=512,
        warmup=True,
        warmup_text="你好，我是语音助手。",
        precompute_voice=True,
        require_precomputed_voice=True,
        ref_audio=None,
        ref_text=None,
        voice_consent="I have permission to use this voice sample.",
        speaker_description=None,
        use_ref_audio_each_request=False,
        gen_kwargs={},
        runtime_config: RuntimeConfig | None = None,
        cancel_scope: CancelScope | None = None,
    ):
        if not base_url:
            raise ValueError("VoxCPM2 TTS requires voxcpm2_tts_base_url in YAML config or CLI args")
        self.should_listen = should_listen
        self.runtime_config = runtime_config
        self.cancel_scope = cancel_scope
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.speed = speed
        self.timeout = timeout
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.precompute_voice = precompute_voice
        self.require_precomputed_voice = require_precomputed_voice
        self.voice_consent = voice_consent
        self.speaker_description = speaker_description
        self.use_ref_audio_each_request = use_ref_audio_each_request
        self.client = VLLMOmniTTSClient(
            base_url=self.base_url,
            model=self.model,
            voice=self.voice,
            api_key=api_key,
            timeout=timeout,
            target_sample_rate=sample_rate,
            label="VoxCPM2 TTS",
        )
        logger.info(
            "VoxCPM2TTSHandler: url=%s, model=%s, voice=%s, sample_rate=%d, warmup=%s",
            self.base_url,
            self.model,
            self.voice,
            self.sample_rate,
            warmup,
        )
        if warmup:
            self._precompute_and_warmup(warmup_text)

    def process(self, llm_sentence):
        if isinstance(llm_sentence, tuple) and llm_sentence[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return

        # Accept (text, lang) or (text, lang, gen). gen is carried from the
        # LLM through LMOutputProcessor so we check staleness against the
        # generation the item was produced under, not the current one.
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
        logger.info("VoxCPM2 TTS: request sent%s: '%s'", cumul_tag, llm_sentence[:80])

        start = _time.perf_counter()
        try:
            pcm_data = self.client.synthesize_pcm(
                llm_sentence,
                speed=self.speed,
                extra_body=self._request_extra_body(),
            )
        except Exception as exc:
            logger.error("VoxCPM2 TTS synthesis failed: %s", exc)
            return

        if gen is not None and self.cancel_scope.is_stale(gen):
            logger.info("VoxCPM2 TTS: dropping stale PCM (gen=%d, current=%d)", gen, self.cancel_scope.generation)
            return

        tts_ms = (_time.perf_counter() - start) * 1000
        cumul = ""
        if pipeline_start:
            cumul = f", cumul {(_time.perf_counter() - pipeline_start) * 1000:.0f}ms"
        logger.info("VoxCPM2 TTS (%.0fms%s): got %d bytes PCM", tts_ms, cumul, len(pcm_data))

        yield from self._pcm_to_chunks(pcm_data, gen)

    def _precompute_and_warmup(self, text: str):
        try:
            voices = self._list_voices()
            if self.voice not in voices:
                if self.precompute_voice:
                    if not self.ref_audio:
                        raise RuntimeError(
                            f"VoxCPM2 voice={self.voice} is not registered and ref_audio is empty"
                        )
                    logger.info(
                        "VoxCPM2 TTS precomputing/registering voice=%s from %s",
                        self.voice,
                        self.ref_audio,
                    )
                    self.client.upload_voice(
                        name=self.voice,
                        audio_sample=self.ref_audio,
                        consent=self.voice_consent,
                        ref_text=self.ref_text,
                        speaker_description=self.speaker_description,
                    )
                    voices = self._list_voices()
                if self.voice not in voices:
                    message = (
                        f"VoxCPM2 precomputed voice not found after registration: "
                        f"voice={self.voice}, available={voices[:20]}"
                    )
                    if self.require_precomputed_voice:
                        logger.error(message)
                        raise RuntimeError(message)
                    logger.warning(message)
            if not text:
                return
            start = _time.perf_counter()
            pcm = self.client.synthesize_pcm(text, speed=self.speed)
            logger.info(
                "VoxCPM2 TTS warmup/precomputed voice check completed: %.0fms, pcm=%d bytes",
                (_time.perf_counter() - start) * 1000,
                len(pcm),
            )
        except Exception as exc:
            logger.error(
                "VoxCPM2 TTS warmup failed. Check that the vLLM Omni service has loaded voice=%s: %s",
                self.voice,
                exc,
            )
            if self.require_precomputed_voice:
                raise

    def _list_voices(self) -> list[str]:
        voices = self.client.list_voices()
        logger.info("VoxCPM2 TTS voices loaded: %s", voices[:20])
        return voices

    def _request_extra_body(self):
        if not self.use_ref_audio_each_request:
            return None
        return {
            "ref_audio": ref_audio_payload(self.ref_audio),
            "ref_text": self.ref_text,
        }

    def _pcm_to_chunks(self, pcm_data: bytes, gen: int | None):
        if not pcm_data:
            return
        audio = np.frombuffer(pcm_data, dtype=np.int16)
        for i in range(0, len(audio), self.blocksize):
            if gen is not None and self.cancel_scope.is_stale(gen):
                logger.info("VoxCPM2 TTS: cancelled (interruption)")
                return
            chunk = audio[i : i + self.blocksize]
            if len(chunk) < self.blocksize:
                chunk = np.pad(chunk, (0, self.blocksize - len(chunk)))
            yield chunk
