class CancelScope:
    """Unified cancellation signal for the speech-to-speech pipeline.

    Uses a generation counter so pipeline threads (LLM, TTS) can detect
    cancellation without brief-pulse timing games, and an internal
    ``discarding`` flag so the async send loop can drop stale output.

    Thread safety: one writer (the asyncio router thread) and multiple
    readers (pipeline handler threads).  Python's GIL makes int/bool
    reads and writes atomic at the bytecode level, so no lock is needed.
    """

    def __init__(self):
        self._gen: int = 0
        self._discarding: bool = False
        self._cancel_time: float = 0.0  # perf_counter when cancel() was last called
        self.pipeline_start: float = 0.0  # perf_counter timestamp set by VAD on speech end
        self.turn_asr_ms: int | None = None  # ASR latency (ms), set by TranscriptionNotifier on transcription_completed
        self._current_assistant_text: str = ""
        self._current_assistant_generation: int | None = None
        self._last_interrupt_metadata: dict = {}
        # Subscribers notified synchronously inside cancel(). Used by the
        # HeartBeat handlers to reset their turn generation on barge-in so
        # inflight workers drop stale results instead of leaking them into
        # the next turn's cache (race-5 fix).
        self._cancel_listeners: list = []

    def note_assistant_text(self, text: str, generation: int | None = None) -> None:
        """Record the latest assistant sentence/chunk that may be interrupted."""
        if not text:
            return
        self._current_assistant_text = str(text).strip()
        self._current_assistant_generation = generation

    def last_interrupt_metadata(self) -> dict:
        """Return metadata captured when the current response was interrupted."""
        return dict(self._last_interrupt_metadata)

    def register_cancel_listener(self, fn) -> None:
        """Register a callback invoked synchronously by :meth:`cancel`.

        The callback receives no arguments and runs on the thread that
        calls ``cancel()`` (typically the asyncio router thread or the VAD
        thread). It must be non-blocking; long work should schedule itself.
        """
        self._cancel_listeners.append(fn)

    @property
    def generation(self) -> int:
        """Current generation number.  Pipeline threads capture this at
        the start of each response and compare with ``is_stale``."""
        return self._gen

    def cancel(self) -> None:
        """Cancel the current response.

        Increments the generation (so pipeline threads see their captured
        generation as stale) and enables the send-loop discard guard.
        Notifies cancel listeners (e.g. HeartBeat handlers) so they can
        reset per-turn state synchronously with the generation bump.
        """
        import logging
        logger = logging.getLogger(__name__)
        self._gen = (self._gen + 1) & 0xFFFFFFFF
        self._discarding = True
        self._cancel_time = __import__('time').perf_counter()
        self._last_interrupt_metadata = {
            "interrupted_assistant_text": self._current_assistant_text,
            "interrupted_assistant_generation": self._current_assistant_generation,
            "interrupt_ts_ms": int(__import__('time').time() * 1000),
        }
        logger.debug("CancelScope.cancel(): gen=%d, discarding=True", self._gen)
        for listener in list(self._cancel_listeners):
            try:
                listener()
            except Exception:
                logger.exception("CancelScope cancel listener raised; ignoring")

    def response_done(self) -> None:
        """Pipeline acknowledged completion.  Clears the discard guard."""
        import logging
        logger = logging.getLogger(__name__)
        self._discarding = False
        self._cancel_time = 0.0
        self._current_assistant_text = ""
        self._current_assistant_generation = None
        logger.debug("CancelScope.response_done(): discarding cleared")

    def new_response(self) -> None:
        """An explicit ``response.create`` starts a new response.
        Clears the discard guard."""
        self._discarding = False
        self._cancel_time = 0.0
        self._current_assistant_text = ""
        self._current_assistant_generation = None

    def is_stale(self, gen: int) -> bool:
        """Return True if *gen* has been superseded by a ``cancel`` call."""
        return gen != self._gen

    @property
    def discarding(self) -> bool:
        """Whether the send loop should silently drop stale output."""
        return self._discarding

    @property
    def discarding_duration(self) -> float:
        """Seconds since cancel() was last called, or 0 if not discarding."""
        if not self._discarding or self._cancel_time == 0.0:
            return 0.0
        return __import__('time').perf_counter() - self._cancel_time

    def reset(self) -> None:
        """Clear discard state (e.g. on new session connect)."""
        self._discarding = False
        self._current_assistant_text = ""
        self._current_assistant_generation = None
        self._last_interrupt_metadata = {}
