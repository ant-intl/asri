"""Prefetch wrapper that runs TTS synthesis with lookahead parallelism.

Wraps any TTS handler so that the *next* sentence is already being
synthesized while the current one's audio chunks are being emitted.
The output order is guaranteed to match the input order.
"""

import logging
import threading
from collections import deque
from queue import Empty
from time import perf_counter

from pipeline.control import SESSION_END, is_control_message

logger = logging.getLogger(__name__)


class _Slot:
    """Holds the result of one synthesis job."""
    __slots__ = ("chunks", "done", "event", "gen", "text")

    def __init__(self, gen=None, text: str = ""):
        self.chunks = []
        self.done = False
        self.event = threading.Event()
        self.gen = gen  # captured at fill time, checked at consume time
        self.text = text

    def set_result(self, chunks):
        self.chunks = chunks
        self.done = True
        self.event.set()

    def wait(self, timeout=None):
        return self.event.wait(timeout)


class PrefetchHandler:
    """Drop-in replacement for a BaseHandler in the pipeline that adds
    prefetch parallelism around an inner handler's ``process()`` method.

    Uses plain threads instead of ThreadPoolExecutor for reliability.

    Parameters
    ----------
    inner : BaseHandler
        The fully-constructed TTS handler (already ``setup``-ed).
    prefetch : int
        Number of lookahead slots.  ``2`` means one item is being consumed
        while the next is already being synthesized.
    """

    def __init__(self, inner, prefetch=1, cancel_scope=None):
        self.inner = inner
        self.prefetch = prefetch
        self.cancel_scope = cancel_scope
        self.stop_event = inner.stop_event
        self.queue_in = inner.queue_in
        self.queue_out = inner.queue_out

    @staticmethod
    def _item_text(item) -> str:
        if isinstance(item, tuple) and item:
            head = item[0]
        else:
            head = item
        return head if isinstance(head, str) and not head.startswith("__") else ""

    def _note_playing_text(self, slot: _Slot) -> None:
        if not slot.text or self.cancel_scope is None:
            return
        if hasattr(self.cancel_scope, "note_assistant_text"):
            self.cancel_scope.note_assistant_text(slot.text, slot.gen)

    @staticmethod
    def _worker(process_fn, item, slot):
        """Run synthesis in a dedicated thread, store results in slot."""
        try:
            chunks = list(process_fn(item))
            slot.set_result(chunks)
        except Exception as e:
            logger.error("PrefetchHandler: synthesis error: %s", e, exc_info=True)
            slot.set_result([])

    def run(self):
        logger.info("PrefetchHandler: started (prefetch=%d)", self.prefetch)
        pending: deque[_Slot] = deque()

        try:
            while not self.stop_event.is_set():
                # --- 1. Fill prefetch slots ---------------------------------
                while len(pending) < self.prefetch:
                    try:
                        item = self.queue_in.get(timeout=0.02)
                    except Empty:
                        break

                    if isinstance(item, bytes) and item == b"END":
                        self._drain(pending)
                        self.queue_out.put(b"END")
                        return

                    if is_control_message(item, SESSION_END.kind):
                        # Discard in-flight synthesis — session is over, no one should hear this audio
                        pending.clear()
                        try:
                            self.inner.on_session_end()
                        except Exception as e:
                            logger.error("PrefetchHandler: on_session_end error: %s", e, exc_info=True)
                        self.queue_out.put(item)
                        continue

                    item_gen = None
                    if isinstance(item, tuple) and len(item) >= 3:
                        item_gen = item[2]
                    slot = _Slot(
                        gen=item_gen if item_gen is not None else (
                            self.cancel_scope.generation if self.cancel_scope else None
                        ),
                        text=self._item_text(item),
                    )
                    t = threading.Thread(
                        target=self._worker,
                        args=(self.inner.process, item, slot),
                        daemon=True,
                    )
                    t.start()
                    pending.append(slot)
                    logger.debug("PrefetchHandler: submitted item, pending=%d", len(pending))

                # --- 2. Consume the head slot in order --------------------
                if pending:
                    slot = pending[0]
                    if slot.wait(timeout=0.05):
                        pending.popleft()
                        start = perf_counter()
                        cancelled = False
                        noted_playing = False
                        for chunk in slot.chunks:
                            if slot.gen is not None and self.cancel_scope.is_stale(slot.gen):
                                logger.info("PrefetchHandler: barge-in detected, dropping remaining chunks")
                                cancelled = True
                                break
                            if not noted_playing:
                                self._note_playing_text(slot)
                                noted_playing = True
                            self.queue_out.put(chunk)
                        if cancelled:
                            # Drop all pending slots
                            pending.clear()
                            # Drain stale items from input queue (old LLM response)
                            self._drain_stale_input()
                            continue
                        elapsed = perf_counter() - start
                        if elapsed > 0.001:
                            logger.debug("PrefetchHandler: emitted chunks in %.3f s", elapsed)

        finally:
            logger.debug("PrefetchHandler: stopped")

    def _drain_stale_input(self):
        """After barge-in, discard stale TTS text items from the input queue.

        Race-2 fix: instead of blindly clearing the whole queue, keep items
        whose generation matches the current generation (new response) and
        preserve all control messages. Stale items (gen != current) are
        dropped. Items without a gen tag are treated as stale and dropped
        too, matching the previous behaviour for backward compatibility.
        """
        current_gen = self.cancel_scope.generation if self.cancel_scope else None
        drained = 0
        while True:
            try:
                item = self.queue_in.get_nowait()
            except Empty:
                break
            # Preserve pipeline control messages
            if isinstance(item, bytes) and item == b"END":
                self.queue_in.put(item)
                break
            if is_control_message(item, SESSION_END.kind):
                self.queue_in.put(item)
                break
            # __END_OF_RESPONSE__ must be forwarded so TTS produces
            # __RESPONSE_DONE__ and clears the discarding gate. Carry gen
            # so the TTS handler can still check staleness if needed.
            if isinstance(item, tuple) and len(item) > 0 and item[0] == "__END_OF_RESPONSE__":
                # Keep only if it belongs to the current (new) generation.
                item_gen = item[2] if len(item) >= 3 else None
                if current_gen is None or item_gen is None or item_gen == current_gen:
                    self.queue_in.put(item)
                break
            # Text items: (text, lang, gen) or (text, lang). Keep if gen
            # matches current generation (new response's sentence).
            if isinstance(item, tuple) and len(item) >= 3:
                item_gen = item[2]
                if current_gen is not None and item_gen == current_gen:
                    self.queue_in.put(item)  # new response, keep
                    break
            # Otherwise: stale (no gen, or gen mismatch) -> drop
            drained += 1
        if drained:
            logger.info("PrefetchHandler: drained %d stale items from input queue (kept new-gen items)", drained)

    def _drain(self, pending: deque):
        """Wait for all pending slots and emit their results in order."""
        while pending:
            slot = pending.popleft()
            slot.wait(timeout=10.0)
            if slot.gen is not None and self.cancel_scope and self.cancel_scope.is_stale(slot.gen):
                continue
            noted_playing = False
            for chunk in slot.chunks:
                if not noted_playing:
                    self._note_playing_text(slot)
                    noted_playing = True
                self.queue_out.put(chunk)
