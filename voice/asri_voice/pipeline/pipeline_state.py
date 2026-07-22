"""Pipeline-wide state machine for barge-in coordination.

Replaces the loose pair of ``should_listen`` (threading.Event) and
``response_playing`` (threading.Event) with a single source of truth.

The four states map to the lifecycle of one user turn:

    IDLE      -- waiting for the user to start speaking
    LISTENING -- user is speaking (VAD accumulating audio, STT running)
    THINKING  -- user finished speaking; ASR/LLM processing; VAD keeps
                  running so barge-in can interrupt the "thinking" gap
    SPEAKING  -- TTS audio is being played back; VAD keeps running so
                  barge-in can interrupt playback

Design goals (see docs/barge-in-improvement-plan.md):

1. VAD always runs. The old ``if not should_listen.is_set(): return`` early
   exit created a "thinking gap" where user speech was dropped. With the
   state machine, VAD processes every audio chunk; only the *downstream
   yield* of audio to STT is gated by state.
2. Single transition point. ``cancel_scope.cancel()`` and the state
   transition happen together via :meth:`cancel_and_listen`, so there is
   no window where cancellation is signalled but listening is not
   re-enabled.
3. Listeners. VAD and the realtime ``_send_loop`` register listeners so
   they react to transitions (e.g. clear playback queue on
   SPEAKING -> LISTENING) without polling.

Backward compatibility: handlers that still take ``should_listen`` as a
``threading.Event`` get a shim that forwards ``set/clear/is_set`` to the
state machine. ``response_playing`` likewise. New code should use the
state machine directly.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class _EventShim(threading.Event):
    """A threading.Event backed by the state machine.

    ``set`` corresponds to "listening is allowed" (IDLE/LISTENING),
    ``clear`` corresponds to "listening is not allowed" (THINKING/SPEAKING).
    Used so legacy handlers that take ``should_listen: threading.Event``
    keep working without signature changes.
    """

    def __init__(self, machine: "PipelineStateMachine", allowed_states):
        super().__init__()
        self._machine = machine
        self._allowed_states = allowed_states
        # Keep the underlying Event flag in sync with the machine state.
        # Initial state is IDLE -> listening allowed -> set.
        if machine.state in allowed_states:
            super().set()
        else:
            super().clear()
        machine.add_listener(self._on_transition)

    def _on_transition(self, old: PipelineState, new: PipelineState) -> None:
        if new in self._allowed_states:
            super().set()
        else:
            super().clear()


class PipelineStateMachine:
    """Single source of truth for the pipeline phase.

    Thread safety: transitions take a lock so listeners observe a
    consistent (old, new) pair. State reads are lock-free (Python's GIL
    makes enum/int reads atomic at the bytecode level).
    """

    LISTENING_STATES = frozenset({PipelineState.IDLE, PipelineState.LISTENING})
    # VAD always runs; this is kept for explicit checks and future gating.
    VAD_RUNNING_STATES = frozenset({
        PipelineState.IDLE, PipelineState.LISTENING,
        PipelineState.THINKING, PipelineState.SPEAKING,
    })
    # States in which audio should be yielded downstream to STT/ASR.
    YIELD_AUDIO_STATES = frozenset({PipelineState.IDLE, PipelineState.LISTENING})

    def __init__(self) -> None:
        self._state = PipelineState.IDLE
        self._lock = threading.Lock()
        self._listeners: list = []
        # Shims for legacy handlers (created lazily by make_should_listen / make_response_playing)
        self._should_listen_shim: _EventShim | None = None
        self._response_playing_shim: _EventShim | None = None

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def should_listen(self) -> bool:
        """True when new user speech should be accepted (IDLE/LISTENING)."""
        return self._state in self.LISTENING_STATES

    @property
    def vad_should_run(self) -> bool:
        """VAD always runs — barge-in must be detectable in every phase."""
        return self._state in self.VAD_RUNNING_STATES

    @property
    def should_yield_audio(self) -> bool:
        """True when VAD-emitted audio should flow to STT (IDLE/LISTENING)."""
        return self._state in self.YIELD_AUDIO_STATES

    @property
    def is_speaking(self) -> bool:
        return self._state == PipelineState.SPEAKING

    @property
    def is_thinking_or_speaking(self) -> bool:
        return self._state in (PipelineState.THINKING, PipelineState.SPEAKING)

    def transition(self, new: PipelineState) -> None:
        old = self._state
        if old is new:
            return
        with self._lock:
            self._state = new
        logger.debug("PipelineState: %s -> %s", old.value, new.value)
        for listener in list(self._listeners):
            try:
                listener(old, new)
            except Exception:
                logger.exception("PipelineState listener raised; ignoring")

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def to_listening(self) -> None:
        """Convenience: transition to LISTENING (user started speaking)."""
        self.transition(PipelineState.LISTENING)

    def to_thinking(self) -> None:
        """Convenience: transition to THINKING (end-of-speech detected)."""
        self.transition(PipelineState.THINKING)

    def to_speaking(self) -> None:
        """Convenience: transition to SPEAKING (first TTS chunk sent)."""
        self.transition(PipelineState.SPEAKING)

    def to_idle(self) -> None:
        """Convenience: transition to IDLE (response fully done)."""
        self.transition(PipelineState.IDLE)

    # --- Legacy shims ----------------------------------------------------- #

    def make_should_listen(self) -> threading.Event:
        """Return a threading.Event shim for legacy ``should_listen``.

        ``set``/``clear`` on the returned Event are forwarded to the state
        machine: ``set`` -> LISTENING (if currently IDLE), ``clear`` ->
        THINKING (if currently IDLE/LISTENING). Reads (``is_set``) reflect
        ``should_listen``.
        """
        if self._should_listen_shim is None:
            self._should_listen_shim = _ShouldListenShim(self)
        return self._should_listen_shim

    def make_response_playing(self) -> threading.Event:
        """Return a threading.Event shim for legacy ``response_playing``.

        ``set`` -> SPEAKING, ``clear`` -> IDLE (if currently SPEAKING).
        Reads reflect ``is_speaking``.
        """
        if self._response_playing_shim is None:
            self._response_playing_shim = _ResponsePlayingShim(self)
        return self._response_playing_shim


class _ShouldListenShim(_EventShim):
    """Legacy ``should_listen`` Event backed by the state machine.

    Forwards writes (set/clear) to state transitions so legacy code that
    calls ``should_listen.set()`` / ``should_listen.clear()`` still drives
    the state machine.
    """

    def __init__(self, machine: PipelineStateMachine):
        super().__init__(machine, PipelineStateMachine.LISTENING_STATES)

    def set(self) -> bool:
        # Legacy code calls should_listen.set() to (re-)enable listening.
        # If we're in THINKING/SPEAKING this is a "barge-in / response done"
        # signal -> go to IDLE so the next speech starts a clean turn.
        self._machine.transition(PipelineState.IDLE)
        return True

    def clear(self) -> None:
        # Legacy code calls should_listen.clear() on end-of-speech -> THINKING.
        self._machine.transition(PipelineState.THINKING)


class _ResponsePlayingShim(_EventShim):
    """Legacy ``response_playing`` Event backed by the state machine."""

    def __init__(self, machine: PipelineStateMachine):
        super().__init__(machine, {PipelineState.SPEAKING})

    def set(self) -> bool:
        # Legacy code calls response_playing.set() when first audio chunk sent.
        self._machine.transition(PipelineState.SPEAKING)
        return True

    def clear(self) -> None:
        # Legacy code calls response_playing.clear() when response cancelled/done.
        if self._machine.state == PipelineState.SPEAKING:
            self._machine.transition(PipelineState.IDLE)
