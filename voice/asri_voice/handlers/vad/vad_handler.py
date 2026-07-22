import time
import torchaudio
from handlers.vad.vad_iterator import VADIterator
from pipeline.base_handler import BaseHandler
import numpy as np
import torch
from rich.console import Console

from utils.utils import int2float
import logging

from api.openai_realtime.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

# Optional import for audio enhancement
try:
    from df.enhance import enhance, init_df
    HAS_DF = True
except (ImportError, ModuleNotFoundError) as e:
    HAS_DF = False
    logger.warning(f"DeepFilterNet not available for audio enhancement: {e}")

console = Console()


class VADHandler(BaseHandler):
    """
    Handles voice activity detection. When voice activity is detected, audio will be accumulated until the end of speech is detected and then passed
    to the following part.
    """

    def setup(
        self,
        should_listen,
        thresh=0.3,
        sample_rate=16000,
        min_silence_ms=1000,
        min_speech_ms=500,
        max_speech_ms=float("inf"),
        speech_pad_ms=30,
        audio_enhancement=False,
        enable_realtime_transcription=False,
        realtime_processing_pause=0.25,
        enable_vadasr=False,
        text_output_queue=None,
        runtime_config: RuntimeConfig | None = None,
        cancel_scope=None,
        playback_queue=None,
        enable_barge_in=False,
        pipeline_state=None,
    ):
        # ``pipeline_state`` is the new PipelineStateMachine (single source of
        # truth). ``should_listen`` is kept for backward compatibility — when
        # a state machine is supplied, should_listen is a shim and we drive
        # transitions through the machine; otherwise we fall back to the old
        # Event-based behaviour.
        from pipeline.pipeline_state import PipelineState, PipelineStateMachine
        self.pipeline_state: PipelineStateMachine | None = pipeline_state
        self.should_listen = should_listen
        self.cancel_scope = cancel_scope
        self.playback_queue = playback_queue
        # When a state machine is present, barge-in detection is always on
        # (VAD runs in every state). The legacy enable_barge_in flag only
        # matters for the old Event path.
        self.enable_barge_in = enable_barge_in or (pipeline_state is not None)
        self.sample_rate = sample_rate
        self.min_silence_ms = min_silence_ms
        self.min_speech_ms = min_speech_ms
        self.max_speech_ms = max_speech_ms
        self.enable_realtime_transcription = enable_realtime_transcription
        self.realtime_processing_pause = realtime_processing_pause
        self.enable_vadasr = enable_vadasr
        self.text_output_queue = text_output_queue
        self.runtime_config = runtime_config
        self._last_turn_detection = None
        import os
        _hub_cache = os.path.expanduser("~/.cache/torch/hub/snakers4_silero-vad_master")
        if os.path.isdir(_hub_cache):
            self.model, _ = torch.hub.load(
                _hub_cache, "silero_vad", source="local",
                trust_repo=True, skip_validation=True,
            )
        else:
            self.model, _ = torch.hub.load(
                "snakers4/silero-vad", "silero_vad",
                trust_repo=True, skip_validation=True,
            )
        self.iterator = VADIterator(
            self.model,
            threshold=thresh,
            sampling_rate=sample_rate,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self.audio_enhancement = audio_enhancement
        if audio_enhancement:
            if not HAS_DF:
                logger.error("Audio enhancement requested but DeepFilterNet is not available. Disabling audio enhancement.")
                self.audio_enhancement = False
            else:
                self.enhanced_model, self.df_state, _ = init_df()

        # State for progressive audio release
        self.last_process_time = 0

        # Predict side-branch: forward audio during speech
        self.predict_audio_queue = None

        # Throttled logging state (summary once per second)
        self._last_log_time = 0.0
        self._log_chunks = 0
        self._log_speech_starts = 0
        self._log_speech_ends = 0
        self._log_progressive_yields = 0
        self._speech_started_emitted = False
        self._vadasr_buffer_flushed = False

    def _apply_runtime_turn_detection(self):
        """Check RuntimeConfig for turn_detection changes and apply them."""
        if not self.runtime_config or not self.runtime_config.session.audio.input.turn_detection:
            return
        td_raw = self.runtime_config.session.audio.input.turn_detection
        if td_raw is self._last_turn_detection:
            return
        self._last_turn_detection = td_raw

        # Convert Pydantic models (e.g. OpenAI SDK ServerVad) to dict;
        # plain dicts pass through unchanged.
        if hasattr(td_raw, "model_dump"):
            td = td_raw.model_dump(exclude_none=True)
        elif isinstance(td_raw, dict):
            td = td_raw
        else:
            logger.warning(f"Unexpected turn_detection type: {type(td_raw)}")
            return

        if "threshold" in td:
            self.iterator.threshold = td["threshold"]
            logger.info(f"VAD threshold updated to {td['threshold']}")
        if "silence_duration_ms" in td:
            self.iterator.min_silence_samples = (
                self.sample_rate * td["silence_duration_ms"] / 1000
            )
            logger.info(f"VAD silence duration updated to {td['silence_duration_ms']}ms")

    def process(self, audio_chunk):
        self._apply_runtime_turn_detection()
        logger.debug(f"VAD received {len(audio_chunk)} bytes")

        # Resolve current pipeline phase. When a state machine is present we
        # use it; otherwise fall back to the legacy should_listen Event.
        if self.pipeline_state is not None:
            state = self.pipeline_state.state
            listening = self.pipeline_state.should_listen
            vad_running = self.pipeline_state.vad_should_run
        else:
            state = None
            listening = self.should_listen.is_set()
            vad_running = listening or self.enable_barge_in

        # If VAD should not run at all (should not happen with state machine),
        # bail out early. Legacy path without barge-in also bails out.
        if not vad_running:
            return

        # Barge-in path: THINKING/SPEAKING (i.e. not listening) but VAD runs.
        if not listening:
            return (yield from self._process_bargein(audio_chunk, state))

        # Normal listening mode (IDLE/LISTENING)
        return (yield from self._process_listening(audio_chunk))

    def _process_bargein(self, audio_chunk, state):
        """Barge-in detection during THINKING/SPEAKING.

        VAD runs on every chunk. When speech accumulates past min_speech_ms:
        1. Cancel the in-flight response (cancel_scope.cancel()).
        2. Transition to LISTENING so downstream STT accepts audio.
        3. Emit speech_started so _send_loop flushes stale audio.
        4. Flush the VAD buffer to STT (so the interrupting speech is
           transcribed, not dropped).

        Does NOT clear playback_queue here — that race (VAD thread clearing
        send_q while _send_loop reads it) is handled by _send_loop reacting
        to the speech_started event and doing a coordinated flush.
        """
        audio_int16 = np.frombuffer(audio_chunk, dtype=np.int16)
        audio_float32 = int2float(audio_int16)
        self.iterator(torch.from_numpy(audio_float32))

        if self.iterator.triggered and not self._speech_started_emitted:
            buffer_samples = sum(len(t) for t in self.iterator.buffer)
            buffer_duration_ms = buffer_samples / self.sample_rate * 1000
            if buffer_duration_ms >= self.min_speech_ms:
                self._speech_started_emitted = True
                logger.info(
                    "Barge-in detected (%.0fms buffered, state=%s)",
                    buffer_duration_ms,
                    state.value if state is not None else "legacy",
                )
                # Cancel in-flight response first (gen++, discarding=True).
                if self.cancel_scope:
                    self.cancel_scope.cancel()
                # Transition to LISTENING — should_listen shim set() maps here.
                if self.pipeline_state is not None:
                    self.pipeline_state.to_listening()
                else:
                    self.should_listen.set()
                # Notify _send_loop so it flushes stale audio + clears discarding.
                if self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_started"})
        # No audio yielded during barge-in path; STT will receive the buffer
        # once we're back in the listening path (next chunks). The interrupting
        # speech is captured by the VAD buffer and flushed to STT when
        # _speech_started_emitted becomes True in the listening path.
        return
        yield  # unreachable; keeps this a generator

    def _process_listening(self, audio_chunk):
        """Normal listening mode (IDLE/LISTENING). Yields audio downstream."""
        self._log_chunks += 1
        audio_int16 = np.frombuffer(audio_chunk, dtype=np.int16)
        audio_float32 = int2float(audio_int16)

        vad_output = self.iterator(torch.from_numpy(audio_float32))

        # Deferred speech_started: only emit once buffer >= min_speech_ms
        is_triggered_now = self.iterator.triggered
        if is_triggered_now and not self._speech_started_emitted:
            buffer_samples = sum(len(t) for t in self.iterator.buffer)
            buffer_duration_ms = buffer_samples / self.sample_rate * 1000
            if buffer_duration_ms >= self.min_speech_ms:
                self._speech_started_emitted = True
                self._log_speech_starts += 1
                logger.info("Speech started (confirmed, %.0fms buffered)", buffer_duration_ms)
                if self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_started"})
                # Fork: flush accumulated buffer to predict side-branch
                if self.predict_audio_queue is not None:
                    buf_array = torch.cat(self.iterator.buffer).cpu().numpy()
                    self.predict_audio_queue.put(buf_array)
                # VADASR: yield accumulated buffer to main STT.
                # Mark flushed so the post-bargein block below doesn't
                # yield the buffer a second time during normal speech.
                if self.enable_vadasr:
                    self._vadasr_buffer_flushed = True
                    yield torch.cat(self.iterator.buffer).cpu().numpy()

        # Post-bargein VADASR buffer flush (once only).
        # Separate if-block (not elif) so ongoing chunks flow through
        # the _speech_started_emitted block below after the flush.
        _just_flushed = False
        if is_triggered_now and self._speech_started_emitted and self.enable_vadasr:
            if self.iterator.buffer and not getattr(self, '_vadasr_buffer_flushed', False):
                self._vadasr_buffer_flushed = True
                _just_flushed = True
                buf_array = torch.cat(self.iterator.buffer).cpu().numpy()
                logger.debug("VAD: flushing post-bargein buffer (%.0fms) to VADASR",
                             buf_array.nbytes / 2 / self.sample_rate * 1000)
                yield buf_array

        # Fork: forward real-time audio to predict side-branch while speaking.
        # Skip the current chunk when we just flushed the full buffer above
        # (it is already included in the flushed buffer).
        if self._speech_started_emitted and not _just_flushed:
            if self.predict_audio_queue is not None:
                self.predict_audio_queue.put(audio_chunk)
            # VADASR: yield raw audio chunk to main STT
            if self.enable_vadasr:
                yield audio_chunk

        # Log a summary once per second instead of every chunk
        now = time.time()
        if now - self._last_log_time >= 1.0:
            state_label = "SPEAKING" if is_triggered_now else "silent"
            logger.debug(
                f"VAD: {self._log_chunks} chunks/s | {state_label} | "
                f"starts={self._log_speech_starts} ends={self._log_speech_ends} progressive={self._log_progressive_yields}"
            )
            self._log_chunks = 0
            self._log_speech_starts = 0
            self._log_speech_ends = 0
            self._log_progressive_yields = 0
            self._last_log_time = now

        if self.enable_vadasr:
            # Edge case: barge-in where speech ended before progressive
            # chunks could flush the accumulated buffer.
            if vad_output is not None and len(vad_output) > 0 and not getattr(self, '_vadasr_buffer_flushed', False):
                self._vadasr_buffer_flushed = True
                buf_array = torch.cat(vad_output).cpu().numpy()
                logger.debug("VAD: edge-flush post-bargein buffer (%.0fms) to VADASR",
                             buf_array.nbytes / 2 / self.sample_rate * 1000)
                yield buf_array
            yield from self._process_vadasr(vad_output)
        elif self.enable_realtime_transcription:
            # Progressive mode: yield audio chunks while speaking
            yield from self._process_realtime(vad_output)
        else:
            # Original mode: yield only when speech ends
            yield from self._process_normal(vad_output)

    def _process_realtime(self, vad_output):
        """Process with real-time progressive audio release."""
        # Check if we're currently in a speech segment
        if hasattr(self.iterator, "buffer") and len(self.iterator.buffer) > 0:
            current_time = time.time()

            # Yield accumulated audio periodically while speaking
            if (current_time - self.last_process_time) >= self.realtime_processing_pause:
                array = torch.cat(self.iterator.buffer).cpu().numpy()
                duration_ms = len(array) / self.sample_rate * 1000

                if duration_ms >= self.min_speech_ms:
                    self._log_progressive_yields += 1
                    logger.debug(f"VAD: yielding progressive audio ({duration_ms:.0f}ms)")
                    yield ("progressive", array)
                    self.last_process_time = current_time

        # Handle end of speech
        if vad_output is not None:
            if len(vad_output) == 0:
                logger.info("VAD: phantom trigger (empty buffer), closing speech pair")
                if self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_stopped", "duration_s": 0})
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False
                return

            array = torch.cat(vad_output).cpu().numpy()
            duration_ms = len(array) / self.sample_rate * 1000

            if duration_ms < self.min_speech_ms or duration_ms > self.max_speech_ms:
                logger.info(
                    f"VAD: discarding {duration_ms:.0f}ms segment "
                    f"(bounds: {self.min_speech_ms}-{self.max_speech_ms}ms)"
                )
                if self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_stopped", "duration_s": 0})
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False
            else:
                if not self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_started"})
                self._log_speech_ends += 1
                self.should_listen.clear()
                if self.cancel_scope:
                    self.cancel_scope.pipeline_start = time.perf_counter()
                logger.info(f"Speech ended ({duration_ms:.0f}ms), stop listening")
                if self.text_output_queue:
                    self.text_output_queue.put({
                        "type": "speech_stopped",
                        "duration_s": duration_ms / 1000.0,
                    })
                if self.audio_enhancement:
                    array = self._apply_audio_enhancement(array)
                yield ("final", array)
                self.last_process_time = 0
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False

    def _process_normal(self, vad_output):
        """Original processing: yield only when speech ends."""
        if vad_output is not None:
            if len(vad_output) == 0:
                logger.info("VAD: phantom trigger (empty buffer), closing speech pair")
                if self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_stopped", "duration_s": 0})
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False
                return

            array = torch.cat(vad_output).cpu().numpy()
            duration_ms = len(array) / self.sample_rate * 1000
            if duration_ms < self.min_speech_ms or duration_ms > self.max_speech_ms:
                logger.info(
                    f"VAD: discarding {duration_ms:.0f}ms segment "
                    f"(bounds: {self.min_speech_ms}-{self.max_speech_ms}ms)"
                )
                if self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_stopped", "duration_s": 0})
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False
            else:
                if not self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_started"})
                self._log_speech_ends += 1
                self.should_listen.clear()
                if self.cancel_scope:
                    self.cancel_scope.pipeline_start = time.perf_counter()
                logger.info(f"Speech ended ({duration_ms:.0f}ms), stop listening")
                if self.text_output_queue:
                    self.text_output_queue.put({
                        "type": "speech_stopped",
                        "duration_s": duration_ms / 1000.0,
                    })
                if self.audio_enhancement:
                    array = self._apply_audio_enhancement(array)
                yield array
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False

    def _process_vadasr(self, vad_output):
        """VADASR mode: send TURN_END at end-of-speech.

        Progressive audio chunks (initial buffer + ongoing chunks) are yielded
        directly in process() body. This method only handles end-of-speech
        and sends the TURN_END sentinel downstream to the streaming ASR handler.
        """
        from handlers.stt.fake_streaming_asr import TURN_END

        if vad_output is not None:
            if len(vad_output) == 0:
                logger.info("VADASR: phantom trigger (empty buffer), closing speech pair")
                if self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_stopped", "duration_s": 0})
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False
                return

            array = torch.cat(vad_output).cpu().numpy()
            duration_ms = len(array) / self.sample_rate * 1000
            if duration_ms < self.min_speech_ms or duration_ms > self.max_speech_ms:
                logger.info(
                    "VADASR: discarding %.0fms segment (bounds: %.0f-%.0fms)",
                    duration_ms, self.min_speech_ms, self.max_speech_ms,
                )
                if self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_stopped", "duration_s": 0})
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False
            else:
                if not self._speech_started_emitted and self.text_output_queue:
                    self.text_output_queue.put({"type": "speech_started"})
                self._log_speech_ends += 1
                self.should_listen.clear()
                if self.cancel_scope:
                    self.cancel_scope.pipeline_start = time.perf_counter()
                logger.info("VADASR: Speech ended (%.0fms), sending TURN_END", duration_ms)
                if self.text_output_queue:
                    self.text_output_queue.put({
                        "type": "speech_stopped",
                        "duration_s": duration_ms / 1000.0,
                    })
                # Fork TURN_END + full audio to predict side-branch if active
                if self.predict_audio_queue is not None:
                    self.predict_audio_queue.put((TURN_END, array))
                yield TURN_END
                self._speech_started_emitted = False
                self._vadasr_buffer_flushed = False

    def _apply_audio_enhancement(self, array):
        """Apply audio enhancement if enabled."""
        if self.sample_rate != self.df_state.sr():
            audio_float32 = torchaudio.functional.resample(
                torch.from_numpy(array),
                orig_freq=self.sample_rate,
                new_freq=self.df_state.sr(),
            )
            enhanced = enhance(
                self.enhanced_model,
                self.df_state,
                audio_float32.unsqueeze(0),
            )
            enhanced = torchaudio.functional.resample(
                enhanced,
                orig_freq=self.df_state.sr(),
                new_freq=self.sample_rate,
            )
        else:
            enhanced = enhance(
                self.enhanced_model, self.df_state, torch.from_numpy(array)
            )
        return enhanced.numpy().squeeze()

    def on_session_end(self):
        self.iterator.reset_states()
        self.iterator.buffer = []
        self.accumulated_audio = []
        self.last_process_time = 0
        self._speech_started_emitted = False
        self._vadasr_buffer_flushed = False
        if self.pipeline_state is not None:
            self.pipeline_state.to_idle()
        else:
            self.should_listen.set()
        logger.debug("VAD session state reset")

    @property
    def min_time_to_debug(self):
        return 0.00001
