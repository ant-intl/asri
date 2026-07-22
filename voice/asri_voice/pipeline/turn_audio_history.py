"""Thread-safe ring buffer of completed turn audio as base64 WAV strings.

Writer: VAD handler / eval service (appends on end-of-speech or history load).
Reader: HeartbeatInteractionHandler (snapshots for multi-turn SFT prompts).

Audio is stored as base64-encoded WAV (16kHz mono PCM_16) strings because
the only consumer is the predict handler, which sends them directly to the
Qwen3-Omni API.  Storing pre-encoded avoids re-encoding on every snapshot.

Follows the same shared-object pattern as ``Chat`` (``chat_ref``).
"""

import base64
import io
import threading

import numpy as np
import soundfile as sf


def encode_audio_base64(pcm_array: np.ndarray) -> str:
    """Encode a PCM array as base64 WAV (16kHz mono PCM_16).

    Accepts float32/float64 ([-1,1]) or int16 arrays.
    Aligned with vLLM-Omni gradio_demo: float32 → clip → *32767 → int16.
    """
    if pcm_array.dtype in (np.float32, np.float64):
        pcm_array = np.clip(pcm_array, -1.0, 1.0)
        pcm_array = (pcm_array * 32767).astype(np.int16)
    elif pcm_array.dtype != np.int16:
        pcm_array = pcm_array.astype(np.int16)
    buf = io.BytesIO()
    sf.write(buf, pcm_array, 16000, subtype="PCM_16", format="WAV")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class TurnAudioHistory:
    """Thread-safe ring buffer of completed turn audio as base64 WAV strings.

    Args:
        max_turns: Maximum number of turns to retain.
        max_total_seconds: Maximum total audio duration in seconds
            (at 16kHz).  Oldest turns are evicted when exceeded.
    """

    def __init__(
        self,
        max_turns: int = 10,
        max_total_seconds: int | None = 120,
    ):
        self._lock = threading.Lock()
        self._turns: list[str] = []
        self._durations: list[float] = []
        self._max_turns = max_turns
        self._max_total_seconds = max_total_seconds

    def append(self, audio_b64: str, duration_s: float = 0.0) -> None:
        """Append a pre-encoded base64 WAV string for a completed turn."""
        with self._lock:
            self._turns.append(audio_b64)
            self._durations.append(duration_s)
            self._evict_if_needed()

    def snapshot(self) -> list[str]:
        """Return a copy of the base64 list (thread-safe)."""
        with self._lock:
            return list(self._turns)

    def reset(self) -> None:
        """Called on session end."""
        with self._lock:
            self._turns.clear()
            self._durations.clear()

    def _evict_if_needed(self):
        total_s = sum(self._durations)
        while self._turns and (
            len(self._turns) > self._max_turns
            or (
                self._max_total_seconds is not None
                and total_s > self._max_total_seconds
            )
        ):
            self._turns.pop(0)
            total_s -= self._durations.pop(0)
