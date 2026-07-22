"""Streaming ASR Handler — multi-backend, full-audio interim + final output.

Receives raw audio chunks (forked from VAD when speech is active), performs
periodic ASR on the FULL accumulated audio (growing buffer since speech start),
and emits:
  - Interim text: sent to the predict handler for early tool-call prediction
  - Final text: emitted on TURN_END to replace one-shot STT in main pipeline

Supports multiple ASR backends:
  - sensevoice: SenseVoice ASR (default, existing behavior)
  - qwen3: Qwen3-ASR via vLLM OpenAI-compatible transcriptions API
  - dashscope: DashScope Paraformer via dashscope SDK
  - openai_whisper: OpenAI Whisper / compatible transcriptions API

Using full accumulated audio (not sliding window) gives much better ASR quality
since the model has full context from the beginning of the utterance.
"""

import base64
import io
import logging
import os
import tempfile
import time
import uuid
import wave
from queue import Empty

import numpy as np
import requests

from pipeline.base_handler import BaseHandler
from handlers.stt.qwen3_asr_handler import _parse_asr_text, _pcm_to_wav_bytes

logger = logging.getLogger(__name__)

# Sentinel sent when VAD detects end-of-speech
TURN_END = "turn_end"


class FakeStreamingASRHandler(BaseHandler):
    """Streaming ASR that produces interim text per block and final on turn end.

    Supports multiple ASR backends via ``asr_backend`` parameter.

    Setup kwargs:
        asr_backend: "sensevoice" (default), "qwen3", "dashscope", or "openai_whisper"
        url: SenseVoice ASR endpoint URL (sensevoice backend).
        timeout: ASR request timeout in seconds (sensevoice backend).
        qwen3_asr_base_url: Qwen3-ASR vLLM endpoint base URL (qwen3 backend).
        qwen3_asr_model_name: Qwen3-ASR model name (qwen3 backend).
        qwen3_asr_timeout: HTTP request timeout in seconds (qwen3 backend).
        dashscope_api_key: DashScope API key (dashscope backend).
        dashscope_model: DashScope Paraformer model name (dashscope backend).
        dashscope_language_hints: Comma-separated language hints (dashscope backend).
        whisper_url: OpenAI Whisper endpoint URL (openai_whisper backend).
        whisper_api_key: API key (openai_whisper backend).
        whisper_model: Model name (openai_whisper backend).
        whisper_language: Language code (openai_whisper backend).
        block_duration_ms: How often to trigger ASR (in ms of new audio).
        final_reuse_interim_tail_ms: Reuse the last interim transcript on
            TURN_END when the untranscribed tail after that interim is no
            longer than this many milliseconds.
        interim_text_queue: Queue to push interim text for predict handler.
        text_output_queue: Side-channel queue for realtime ASR diagnostics.
        cancel_scope: Shared CancelScope for barge-in awareness.
    """

    def setup(
        self,
        asr_backend="sensevoice",
        url="",
        timeout=10.0,
        qwen3_asr_base_url="",
        qwen3_asr_model_name="",
        qwen3_asr_timeout=30.0,
        dashscope_api_key="",
        dashscope_model="paraformer-realtime-v2",
        dashscope_language_hints="zh,en",
        whisper_url="",
        whisper_api_key="",
        whisper_model="whisper-1",
        whisper_language="zh",
        block_duration_ms=500,
        final_reuse_interim_tail_ms=350,
        interim_text_queue=None,
        text_output_queue=None,
        heartbeat_cache=None,
        cancel_scope=None,
        language="zh",
        gen_kwargs=None,
        audio_segment_buffer=None,
    ):
        self.asr_backend = asr_backend
        self.url = url
        self.timeout = timeout
        self.qwen3_asr_base_url = qwen3_asr_base_url.rstrip("/")
        self.qwen3_asr_model_name = qwen3_asr_model_name
        self.qwen3_asr_timeout = qwen3_asr_timeout
        self.block_duration_ms = block_duration_ms
        self.final_reuse_interim_tail_ms = final_reuse_interim_tail_ms
        self.interim_text_queue = interim_text_queue
        self.text_output_queue = text_output_queue
        self.heartbeat_cache = heartbeat_cache
        self.cancel_scope = cancel_scope
        self.language = language
        self.audio_segment_buffer = audio_segment_buffer

        # Backend-specific config
        self._dashscope_api_key = dashscope_api_key
        self._dashscope_model = dashscope_model
        self._dashscope_language_hints = [
            h.strip() for h in dashscope_language_hints.split(",") if h.strip()
        ] if dashscope_language_hints else ["zh"]
        self._whisper_url = whisper_url
        self._whisper_api_key = whisper_api_key
        self._whisper_model = whisper_model
        self._whisper_language = whisper_language

        # Qwen3-ASR transcriptions URL
        self._qwen3_transcriptions_url = f"{self.qwen3_asr_base_url}/v1/audio/transcriptions"

        # DashScope Recognition instance (lazy-init on first use)
        self._dashscope_recognition = None

        # Block size in samples (16kHz mono)
        self.block_size = 16000 * block_duration_ms // 1000

        # Per-turn state
        self._audio_buffer = np.array([], dtype=np.float32)
        self._last_processed_block = 0
        self._last_interim_text = ""
        self._stopped = False  # stop interim ASR when HeartBeat cache consumed
        self._last_asr_text = ""  # last periodic ASR result (interim/debug only)
        self._last_asr_time = None  # perf_counter of last ASR call completion

        # HTTP session (reuse connections)
        self._session = requests.Session()
        self._headers = {
            "Content-Type": "application/json;charset=utf-8",
            "MPS-app-name": "speech-to-speech",
            "MPS-http-version": "1.0",
        }

        logger.info(
            "[StreamingASR] backend=%s, block=%dms, full-audio mode",
            asr_backend, block_duration_ms,
        )

    def process(self, audio_input):
        """Receive audio chunks or TURN_END.

        On audio chunks: accumulate, and for each new block do sliding-window
        ASR, push interim text to predict handler.

        On TURN_END: do final full-audio ASR and yield (text, language) for
        the main pipeline (replacing one-shot SenseVoiceSTTHandler).
        """
        # --- Handle TURN_END ---
        turn_end_audio = None
        if audio_input is TURN_END:
            turn_end_audio = None
        elif isinstance(audio_input, tuple) and len(audio_input) == 2 and audio_input[0] is TURN_END:
            turn_end_audio = audio_input[1]
        else:
            turn_end_audio = ...  # sentinel: not a TURN_END

        if turn_end_audio is not ...:
            yield from self._handle_turn_end(turn_end_audio)
            return

        # --- Accumulate audio ---
        audio_data = self._parse_audio(audio_input)
        if audio_data is None:
            return

        self._audio_buffer = np.concatenate([self._audio_buffer, audio_data])

        if self._drain_queued_audio_until_turn_end():
            yield from self._handle_turn_end(None)
            return

        # Check if we have a new complete block
        num_blocks = len(self._audio_buffer) // self.block_size
        if num_blocks <= self._last_processed_block:
            return

        # Process new blocks (usually just one new block per call)
        for block_idx in range(self._last_processed_block, num_blocks):
            if self._stopped:
                break

            if self.cancel_scope and self.cancel_scope.discarding:
                # Cancel is in progress — skip the current batch of blocks
                # but do NOT set _stopped.  New speech audio arriving after
                # the cancel must still be processed.
                break

            # Full accumulated audio up to current block
            end_sample = (block_idx + 1) * self.block_size
            full_audio = self._audio_buffer[:end_sample]

            # Call ASR on full accumulated audio
            t0 = time.perf_counter()
            interim_text = self._call_asr(full_audio)
            asr_ms = (time.perf_counter() - t0) * 1000

            if not interim_text:
                logger.debug(
                    "[StreamingASR] block %d: ASR empty (%.0fms)",
                    block_idx, asr_ms,
                )
                continue

            # Dedup: only push if text changed
            if interim_text == self._last_interim_text:
                logger.debug(
                    "[StreamingASR] block %d: unchanged, skip (%.0fms)",
                    block_idx, asr_ms,
                )
                continue

            self._last_interim_text = interim_text
            self._last_asr_text = interim_text
            self._last_asr_time = time.perf_counter()
            logger.info(
                "[StreamingASR] block %d (%.0fms): '%s'",
                block_idx, asr_ms, interim_text[:80],
            )

            # Push interim text + block_idx to predict handler
            if self.interim_text_queue is not None:
                self.interim_text_queue.put((interim_text, block_idx))
            # Store the cumulative audio segment for this block so the
            # HeartBeat worker can ship it to the client alongside the
            # input_messages event.  The consumer (HeartBeat worker)
            # deletes the entry after emitting the event.
            if self.audio_segment_buffer is not None:
                self.audio_segment_buffer[block_idx] = full_audio
            self._emit_asr_debug(
                "interim",
                block_idx=block_idx,
                asr_ms=int(asr_ms),
                audio_ms=int(len(full_audio) / 16000 * 1000),
                text=interim_text,
            )

        self._last_processed_block = num_blocks

    def _drain_queued_audio_until_turn_end(self) -> bool:
        """Collapse queued audio backlog so TURN_END is handled promptly.

        If ASR calls are slower than realtime, the STT queue can contain many
        stale audio chunks followed by TURN_END. Running interim ASR on every
        stale block delays the final transcript. Drain immediately available
        audio chunks, stop at TURN_END, and let final handling run once.
        """
        preserved = []
        drained_chunks = 0
        saw_turn_end = False

        while True:
            try:
                item = self.queue_in.get_nowait()
            except Empty:
                break

            if isinstance(item, str) and item == TURN_END:
                saw_turn_end = True
                break
            if isinstance(item, tuple) and len(item) == 2 and item[0] == TURN_END:
                turn_end_audio = self._parse_audio(item[1])
                if turn_end_audio is not None and len(turn_end_audio) > len(self._audio_buffer):
                    self._audio_buffer = turn_end_audio
                saw_turn_end = True
                break

            audio_data = self._parse_audio(item)
            if audio_data is None:
                preserved.append(item)
                break
            self._audio_buffer = np.concatenate([self._audio_buffer, audio_data])
            drained_chunks += 1

        if preserved:
            with self.queue_in.mutex:
                for item in reversed(preserved):
                    self.queue_in.queue.appendleft(item)
                self.queue_in.not_empty.notify(len(preserved))

        if saw_turn_end:
            logger.info(
                "[StreamingASR] drained queued audio before TURN_END; final_samples=%d",
                len(self._audio_buffer),
            )
            self._emit_asr_debug(
                "backlog_drained",
                drained_chunks=drained_chunks,
                final_samples=len(self._audio_buffer),
                audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
            )
        return saw_turn_end

    def _handle_turn_end(self, turn_end_audio):
        if turn_end_audio is not None:
            audio_data = self._parse_audio(turn_end_audio)
            if audio_data is not None and len(audio_data) > len(self._audio_buffer):
                self._audio_buffer = audio_data

        final_text = self._get_final_text()

        if final_text and final_text.strip():
            cumul = ""
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info(
                "[StreamingASR] FINAL ASR (%s): %s",
                cumul.strip() or "full-audio", final_text.strip(),
            )
            yield (final_text.strip(), self.language)
        else:
            logger.debug("[StreamingASR] FINAL ASR: empty")
            self._emit_asr_debug(
                "final_empty",
                audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
            )

        # Also notify predict handler that turn ended.
        if self.interim_text_queue is not None:
            self.interim_text_queue.put(TURN_END)

        self._reset_turn()

    def _get_final_text(self) -> str:
        if self._audio_buffer is None or len(self._audio_buffer) == 0:
            return ""

        if self._can_reuse_last_interim():
            tail_ms = self._unprocessed_tail_ms()
            logger.info(
                "[StreamingASR] TURN_END: reusing last interim transcript "
                "(tail=%dms <= %dms)",
                tail_ms,
                self.final_reuse_interim_tail_ms,
            )
            self._emit_asr_debug(
                "final_reuse",
                tail_ms=tail_ms,
                audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
                text=self._last_interim_text,
            )
            return self._last_interim_text

        self._emit_asr_debug(
            "final_start",
            audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
        )
        t0 = time.perf_counter()
        final_text = self._call_asr(self._audio_buffer)
        asr_ms = (time.perf_counter() - t0) * 1000
        logger.debug("[StreamingASR] TURN_END: final full-audio ASR took %.0fms", asr_ms)
        self._emit_asr_debug(
            "final_done",
            asr_ms=int(asr_ms),
            audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
            text=final_text,
        )
        return final_text

    def _unprocessed_tail_ms(self) -> int:
        processed_samples = max(0, self._last_processed_block) * self.block_size
        tail_samples = max(0, len(self._audio_buffer) - processed_samples)
        return int(tail_samples / 16000 * 1000)

    def _can_reuse_last_interim(self) -> bool:
        if not self._last_interim_text:
            return False
        if self._last_processed_block <= 0:
            return False
        return self._unprocessed_tail_ms() <= self.final_reuse_interim_tail_ms

    def _emit_asr_debug(self, event: str, **payload):
        if self.text_output_queue is None:
            return
        msg = {
            "type": "asr_debug",
            "event": event,
            "ts_ms": int(time.time() * 1000),
        }
        msg.update(payload)
        try:
            self.text_output_queue.put(msg)
        except Exception:
            logger.debug("[StreamingASR] failed to emit ASR debug event", exc_info=True)

    # ------------------------------------------------------------------ #
    #  Audio parsing
    # ------------------------------------------------------------------ #

    def _parse_audio(self, audio_input) -> np.ndarray | None:
        """Parse various audio input formats to float32 numpy array."""
        if isinstance(audio_input, bytes):
            audio_data = np.frombuffer(audio_input, dtype=np.int16).astype(np.float32) / 32768.0
        elif isinstance(audio_input, tuple) and len(audio_input) == 2:
            _label, audio_data = audio_input
            if not isinstance(audio_data, np.ndarray):
                return None
        elif isinstance(audio_input, np.ndarray):
            audio_data = audio_input
        else:
            return None

        # Normalise dtype
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.float64:
            audio_data = audio_data.astype(np.float32)

        return audio_data

    # ------------------------------------------------------------------ #
    #  ASR backends
    # ------------------------------------------------------------------ #

    def _call_asr(self, audio: np.ndarray) -> str:
        """Dispatch to the configured ASR backend."""
        if self.asr_backend == "qwen3":
            return self._call_asr_qwen3(audio)
        if self.asr_backend == "dashscope":
            return self._call_asr_dashscope(audio)
        if self.asr_backend == "openai_whisper":
            return self._call_asr_openai_whisper(audio)
        return self._call_asr_sensevoice(audio)

    def _call_asr_sensevoice(self, audio: np.ndarray) -> str:
        """Call SenseVoice ASR, return transcription."""
        # Encode to WAV
        if audio.dtype in (np.float32, np.float64):
            pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        else:
            pcm = audio.astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm.tobytes())
        wav_bytes = buf.getvalue()

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

        headers = {**self._headers, "MPS-trace-id": str(uuid.uuid4())}

        try:
            resp = self._session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("resultMap", {}).get("asr", "").strip()
        except requests.Timeout:
            logger.warning("[StreamingASR] SenseVoice timeout")
            return ""
        except Exception as e:
            logger.warning("[StreamingASR] SenseVoice failed: %s", e)
            return ""

    def _call_asr_qwen3(self, audio: np.ndarray) -> str:
        """Call Qwen3-ASR via vLLM transcriptions API, return transcription.

        Also updates ``self.language`` from the detected language tag.
        """
        wav_bytes = _pcm_to_wav_bytes(audio)

        try:
            resp = self._session.post(
                self._qwen3_transcriptions_url,
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": self.qwen3_asr_model_name},
                timeout=self.qwen3_asr_timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            raw_text = result.get("text", "")
            lang, text = _parse_asr_text(raw_text)
            self.language = lang  # update detected language
            return text.strip()
        except requests.Timeout:
            logger.warning("[StreamingASR] Qwen3-ASR timeout")
            return ""
        except Exception as e:
            logger.warning("[StreamingASR] Qwen3-ASR failed: %s", e)
            return ""

    def _call_asr_dashscope(self, audio: np.ndarray) -> str:
        """Call DashScope Paraformer ASR via dashscope SDK."""
        if not self._dashscope_api_key:
            logger.warning("[StreamingASR] DashScope: no api_key configured")
            return ""

        # Lazy-init Recognition instance
        if self._dashscope_recognition is None:
            try:
                import dashscope
                dashscope.api_key = self._dashscope_api_key
                from dashscope.audio.asr import Recognition
                self._dashscope_recognition = Recognition(
                    model=self._dashscope_model,
                    format="wav",
                    sample_rate=16000,
                    language_hints=self._dashscope_language_hints,
                    callback=None,
                )
            except Exception as e:
                logger.error("[StreamingASR] DashScope init failed: %s", e)
                return ""

        wav_bytes = _pcm_to_wav_bytes(audio)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name

            from http import HTTPStatus
            result = self._dashscope_recognition.call(tmp_path)
            if result.status_code == HTTPStatus.OK:
                sentences = result.get_sentence()
                if isinstance(sentences, list):
                    return " ".join(
                        s.get("text", "") for s in sentences if isinstance(s, dict)
                    ).strip()
                if isinstance(sentences, dict):
                    return sentences.get("text", "").strip()
                return str(sentences).strip() if sentences else ""
            logger.warning(
                "[StreamingASR] DashScope failed (%d): %s",
                result.status_code, result.message,
            )
            return ""
        except Exception as e:
            logger.warning("[StreamingASR] DashScope error: %s", e)
            return ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _call_asr_openai_whisper(self, audio: np.ndarray) -> str:
        """Call OpenAI Whisper / compatible transcriptions API."""
        if not self._whisper_url:
            logger.warning("[StreamingASR] OpenAI Whisper: no url configured")
            return ""

        wav_bytes = _pcm_to_wav_bytes(audio)
        headers = {}
        if self._whisper_api_key:
            headers["Authorization"] = f"Bearer {self._whisper_api_key}"

        try:
            resp = self._session.post(
                self._whisper_url,
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": self._whisper_model, "language": self._whisper_language},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get("text", "").strip()
        except requests.Timeout:
            logger.warning("[StreamingASR] OpenAI Whisper timeout")
            return ""
        except Exception as e:
            logger.warning("[StreamingASR] OpenAI Whisper failed: %s", e)
            return ""

    # ------------------------------------------------------------------ #
    #  State management
    # ------------------------------------------------------------------ #

    def _reset_turn(self):
        """Reset per-turn state for next utterance."""
        self._audio_buffer = np.array([], dtype=np.float32)
        self._last_processed_block = 0
        self._last_interim_text = ""
        self._last_asr_text = ""
        self._last_asr_time = None
        self._stopped = False

    def on_session_end(self):
        """Drop any accumulated audio when the realtime client disconnects."""
        self._reset_turn()
