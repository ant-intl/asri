"""Qwen3-ASR native streaming handler.

This handler keeps the VADASR pipeline contract but talks to the Qwen3-ASR
streaming demo/server API:

  POST /api/start
  POST /api/chunk?session_id=...  (float32 PCM bytes)
  POST /api/finish?session_id=...

Unlike ``FakeStreamingASRHandler`` with the ``qwen3`` backend, this does not
re-run ASR over a growing WAV through ``/v1/audio/transcriptions``. The remote
service owns the Qwen streaming state for the current turn.
"""

import logging
import threading
import time
from contextlib import nullcontext
from queue import Empty

import numpy as np
import requests

from handlers.stt.fake_streaming_asr import TURN_END
from handlers.stt.qwen3_asr_handler import _normalize_language
from pipeline.base_handler import BaseHandler

logger = logging.getLogger(__name__)

_REQUEST_LOCKS_GUARD = threading.Lock()
_REQUEST_LOCKS: dict[str, threading.RLock] = {}


def _request_lock_for_base_url(base_url: str) -> threading.RLock:
    with _REQUEST_LOCKS_GUARD:
        lock = _REQUEST_LOCKS.get(base_url)
        if lock is None:
            lock = threading.RLock()
            _REQUEST_LOCKS[base_url] = lock
        return lock


class Qwen3ASRStreamingHandler(BaseHandler):
    """STT handler for Qwen3-ASR native streaming service.

    Input and output are intentionally compatible with VADASR mode:
    audio chunks arrive while VAD is active, ``TURN_END`` closes the remote
    streaming session, and the handler yields ``(text, language)`` once at the
    end of speech. Interim text is pushed to ``interim_text_queue`` for
    HeartBeat Thinking.
    """

    def setup(
        self,
        base_url="http://127.0.0.1:8000",
        timeout=30.0,
        connect_timeout=5.0,
        feed_duration_ms=500,
        final_reuse_interim_tail_ms=350,
        interim_text_queue=None,
        text_output_queue=None,
        heartbeat_cache=None,
        cancel_scope=None,
        language="zh",
        gen_kwargs=None,
        audio_segment_buffer=None,
        serialize_requests=True,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.feed_duration_ms = feed_duration_ms
        self.final_reuse_interim_tail_ms = final_reuse_interim_tail_ms
        self.interim_text_queue = interim_text_queue
        self.text_output_queue = text_output_queue
        self.heartbeat_cache = heartbeat_cache
        self.cancel_scope = cancel_scope
        self.language = language
        self.audio_segment_buffer = audio_segment_buffer
        self.serialize_requests = serialize_requests

        self.feed_size = max(1, 16000 * int(feed_duration_ms) // 1000)
        self._session = requests.Session()
        self._state_lock = threading.RLock()
        self._request_lock = _request_lock_for_base_url(self.base_url) if serialize_requests else None
        self._session_id = None
        self._audio_buffer = np.array([], dtype=np.float32)
        self._pending_audio = np.array([], dtype=np.float32)
        self._last_processed_block = 0
        self._last_interim_text = ""
        self._last_asr_text = ""
        self._last_asr_time = None
        self._last_feed_audio_len = 0

        logger.info(
            "[Qwen3ASRStreaming] url=%s, feed=%dms, native streaming mode, serialize_requests=%s",
            self.base_url,
            self.feed_duration_ms,
            self.serialize_requests,
        )

    def process(self, audio_input):
        with self._state_lock:
            yield from self._process_locked(audio_input)

    def _process_locked(self, audio_input):
        turn_end_audio = None
        if isinstance(audio_input, str) and audio_input == TURN_END:
            turn_end_audio = None
        elif isinstance(audio_input, tuple) and len(audio_input) == 2 and audio_input[0] == TURN_END:
            turn_end_audio = audio_input[1]
        else:
            turn_end_audio = ...

        if turn_end_audio is not ...:
            yield from self._handle_turn_end(turn_end_audio)
            return

        audio_data = self._parse_audio(audio_input)
        if audio_data is None:
            return

        self._audio_buffer = np.concatenate([self._audio_buffer, audio_data])
        self._pending_audio = np.concatenate([self._pending_audio, audio_data])

        if self._drain_queued_audio_until_turn_end():
            yield from self._handle_turn_end(None)
            return

        while len(self._pending_audio) >= self.feed_size:
            if self.cancel_scope and self.cancel_scope.discarding:
                break
            chunk = self._pending_audio[: self.feed_size]
            self._pending_audio = self._pending_audio[self.feed_size :]
            block_idx = self._last_processed_block
            self._last_processed_block += 1
            self._last_feed_audio_len += len(chunk)
            self._send_streaming_chunk(chunk, block_idx)

    def _drain_queued_audio_until_turn_end(self) -> bool:
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
                    missing = turn_end_audio[self._last_feed_audio_len :]
                    self._pending_audio = missing.astype(np.float32, copy=False)
                saw_turn_end = True
                break

            audio_data = self._parse_audio(item)
            if audio_data is None:
                preserved.append(item)
                break
            self._audio_buffer = np.concatenate([self._audio_buffer, audio_data])
            self._pending_audio = np.concatenate([self._pending_audio, audio_data])
            drained_chunks += 1

        if preserved:
            with self.queue_in.mutex:
                for item in reversed(preserved):
                    self.queue_in.queue.appendleft(item)
                self.queue_in.not_empty.notify(len(preserved))

        if saw_turn_end:
            logger.info(
                "[Qwen3ASRStreaming] drained queued audio before TURN_END; final_samples=%d",
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
                self._pending_audio = audio_data[self._last_feed_audio_len :].astype(np.float32, copy=False)

        final_text = self._get_final_text()

        if final_text and final_text.strip():
            cumul = ""
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info(
                "[Qwen3ASRStreaming] FINAL ASR (%s): %s",
                cumul.strip() or "native-streaming",
                final_text.strip(),
            )
            yield (final_text.strip(), self.language)
        else:
            logger.debug("[Qwen3ASRStreaming] FINAL ASR: empty")
            self._emit_asr_debug(
                "final_empty",
                audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
            )

        if self.interim_text_queue is not None:
            self.interim_text_queue.put(TURN_END)

        self._reset_turn(finish_remote=False)

    def _get_final_text(self) -> str:
        if len(self._audio_buffer) == 0:
            return ""

        if self._can_reuse_last_interim():
            tail_ms = self._unprocessed_tail_ms()
            logger.info(
                "[Qwen3ASRStreaming] TURN_END: reusing last interim transcript "
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
            self._finish_remote_session()
            return self._last_interim_text

        if len(self._pending_audio) > 0:
            self._emit_asr_debug(
                "tail_chunk_start",
                audio_ms=int(len(self._pending_audio) / 16000 * 1000),
            )
            self._send_streaming_chunk(self._pending_audio, self._last_processed_block)
            self._last_processed_block += 1
            self._last_feed_audio_len += len(self._pending_audio)
            self._pending_audio = np.array([], dtype=np.float32)

        self._emit_asr_debug(
            "final_start",
            audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
        )
        t0 = time.perf_counter()
        result = self._finish_remote_session()
        asr_ms = (time.perf_counter() - t0) * 1000
        text = str(result.get("text") or self._last_interim_text or "").strip()
        language = result.get("language")
        if language:
            self.language = _normalize_language(str(language))
        self._emit_asr_debug(
            "final_done",
            asr_ms=int(asr_ms),
            audio_ms=int(len(self._audio_buffer) / 16000 * 1000),
            text=text,
        )
        return text

    def _send_streaming_chunk(self, chunk: np.ndarray, block_idx: int) -> str:
        if len(chunk) == 0:
            return self._last_interim_text

        t0 = time.perf_counter()
        result = self._post_chunk(chunk)
        asr_ms = (time.perf_counter() - t0) * 1000

        language = result.get("language")
        if language:
            self.language = _normalize_language(str(language))
        interim_text = str(result.get("text") or "").strip()

        if not interim_text:
            logger.debug(
                "[Qwen3ASRStreaming] block %d: empty (%.0fms)",
                block_idx,
                asr_ms,
            )
            return ""

        self._last_asr_text = interim_text
        self._last_asr_time = time.perf_counter()
        if interim_text == self._last_interim_text:
            logger.debug(
                "[Qwen3ASRStreaming] block %d: unchanged, skip (%.0fms)",
                block_idx,
                asr_ms,
            )
            return interim_text

        self._last_interim_text = interim_text
        logger.info(
            "[Qwen3ASRStreaming] block %d (%.0fms): '%s'",
            block_idx,
            asr_ms,
            interim_text[:80],
        )

        if self.interim_text_queue is not None:
            self.interim_text_queue.put((interim_text, block_idx))
        if self.audio_segment_buffer is not None:
            end_sample = min(len(self._audio_buffer), self._last_feed_audio_len)
            self.audio_segment_buffer[block_idx] = self._audio_buffer[:end_sample]
        self._emit_asr_debug(
            "interim",
            block_idx=block_idx,
            asr_ms=int(asr_ms),
            audio_ms=int(self._last_feed_audio_len / 16000 * 1000),
            text=interim_text,
        )
        return interim_text

    def _request_guard(self):
        if self._request_lock is None:
            return nullcontext()
        return self._request_lock

    def _start_remote_session(self) -> str:
        with self._request_guard():
            resp = self._session.post(
                f"{self.base_url}/api/start",
                timeout=(self.connect_timeout, self.timeout),
            )
        resp.raise_for_status()
        data = resp.json()
        session_id = data.get("session_id")
        if not session_id:
            raise RuntimeError(f"Qwen3 streaming start returned no session_id: {data}")
        self._session_id = str(session_id)
        self._emit_asr_debug("session_start", session_id=self._session_id)
        return self._session_id

    def _ensure_remote_session(self) -> str:
        if self._session_id:
            return self._session_id
        return self._start_remote_session()

    def _post_chunk(self, chunk: np.ndarray) -> dict:
        session_id = self._ensure_remote_session()
        pcm = np.asarray(chunk, dtype=np.float32).reshape(-1)
        try:
            with self._request_guard():
                resp = self._session.post(
                    f"{self.base_url}/api/chunk",
                    params={"session_id": session_id},
                    data=pcm.tobytes(),
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=(self.connect_timeout, self.timeout),
                )
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.warning("[Qwen3ASRStreaming] chunk request timed out")
            return {}
        except Exception as e:
            logger.warning("[Qwen3ASRStreaming] chunk request failed: %s", e)
            return {}

    def _finish_remote_session(self) -> dict:
        if not self._session_id:
            return {}
        session_id = self._session_id
        self._session_id = None
        try:
            with self._request_guard():
                resp = self._session.post(
                    f"{self.base_url}/api/finish",
                    params={"session_id": session_id},
                    timeout=(self.connect_timeout, self.timeout),
                )
            resp.raise_for_status()
            data = resp.json()
            self._emit_asr_debug("session_finish", session_id=session_id)
            return data
        except requests.Timeout:
            logger.warning("[Qwen3ASRStreaming] finish request timed out")
            return {}
        except Exception as e:
            logger.warning("[Qwen3ASRStreaming] finish request failed: %s", e)
            return {}

    def _parse_audio(self, audio_input) -> np.ndarray | None:
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

        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.float64:
            audio_data = audio_data.astype(np.float32)
        elif audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)
        return audio_data.reshape(-1)

    def _unprocessed_tail_ms(self) -> int:
        tail_samples = max(0, len(self._audio_buffer) - self._last_feed_audio_len)
        return int(tail_samples / 16000 * 1000)

    def _can_reuse_last_interim(self) -> bool:
        if not self._last_interim_text:
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
            logger.debug("[Qwen3ASRStreaming] failed to emit ASR debug event", exc_info=True)

    def _reset_turn(self, finish_remote=True):
        if finish_remote:
            self._finish_remote_session()
        self._audio_buffer = np.array([], dtype=np.float32)
        self._pending_audio = np.array([], dtype=np.float32)
        self._last_processed_block = 0
        self._last_interim_text = ""
        self._last_asr_text = ""
        self._last_asr_time = None
        self._last_feed_audio_len = 0

    def on_session_end(self):
        self._reset_turn(finish_remote=True)

    def cleanup(self):
        self._reset_turn(finish_remote=True)
        self._session.close()
