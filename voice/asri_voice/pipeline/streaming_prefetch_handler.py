"""Hybrid wrapper for streaming TTS plus lookahead prefetch.

The first sentence of a response cannot benefit from lookahead because there is
no earlier audio playback to hide synthesis latency behind. For streaming TTS,
that first sentence should be emitted chunk-by-chunk as soon as the server
produces audio. Later sentences can still be synthesized in the background while
the current sentence is playing.
"""

import logging
import threading
from collections import deque
from contextvars import ContextVar
from queue import Empty

from pipeline.control import SESSION_END, is_control_message

logger = logging.getLogger(__name__)

SUPPRESS_TTS_PLAYING_NOTE = ContextVar("SUPPRESS_TTS_PLAYING_NOTE", default=False)


class _Slot:
    __slots__ = ("chunks", "done", "event", "gen", "is_response_end", "text")

    def __init__(self, gen=None, text: str = "", is_response_end: bool = False):
        self.chunks = []
        self.done = False
        self.event = threading.Event()
        self.gen = gen
        self.text = text
        self.is_response_end = is_response_end

    def set_result(self, chunks):
        self.chunks = chunks
        self.done = True
        self.event.set()

    def wait(self, timeout=None):
        return self.event.wait(timeout)


class _StreamState:
    __slots__ = ("done", "gen", "stale", "thread")

    def __init__(self, gen=None):
        self.done = threading.Event()
        self.gen = gen
        self.stale = False
        self.thread: threading.Thread | None = None


class StreamingHeadPrefetchHandler:
    """Preserve first-sentence streaming while prefetching later TTS items."""

    def __init__(self, inner, prefetch=1, cancel_scope=None):
        self.inner = inner
        self.prefetch = max(1, int(prefetch))
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

    @staticmethod
    def _item_gen(item):
        if isinstance(item, tuple) and len(item) >= 3:
            return item[2]
        return None

    @staticmethod
    def _is_response_end(item) -> bool:
        return isinstance(item, tuple) and len(item) > 0 and item[0] == "__END_OF_RESPONSE__"

    def _is_stale(self, gen) -> bool:
        return bool(gen is not None and self.cancel_scope is not None and self.cancel_scope.is_stale(gen))

    def _requeue_front(self, item) -> None:
        with self.queue_in.mutex:
            self.queue_in.queue.appendleft(item)
            self.queue_in.not_empty.notify()

    def _note_playing_text(self, text: str, gen) -> None:
        if not text or self.cancel_scope is None:
            return
        if hasattr(self.cancel_scope, "note_assistant_text"):
            self.cancel_scope.note_assistant_text(text, gen)

    @staticmethod
    def _prefetch_worker(process_fn, item, slot):
        token = SUPPRESS_TTS_PLAYING_NOTE.set(True)
        try:
            slot.set_result(list(process_fn(item)))
        except Exception as e:
            logger.error("StreamingHeadPrefetchHandler: synthesis error: %s", e, exc_info=True)
            slot.set_result([])
        finally:
            SUPPRESS_TTS_PLAYING_NOTE.reset(token)

    def _stream_worker(self, item, state: _StreamState):
        try:
            for chunk in self.inner.process(item):
                gen = self._item_gen(item)
                if self._is_stale(gen):
                    state.stale = True
                    logger.info("StreamingHeadPrefetchHandler: streaming head became stale")
                    break
                self.queue_out.put(chunk)
        except Exception as e:
            logger.error("StreamingHeadPrefetchHandler: streaming head error: %s", e, exc_info=True)
        finally:
            state.done.set()

    def _start_prefetch(self, item) -> _Slot:
        slot = _Slot(
            gen=self._item_gen(item),
            text=self._item_text(item),
            is_response_end=self._is_response_end(item),
        )
        thread = threading.Thread(
            target=self._prefetch_worker,
            args=(self.inner.process, item, slot),
            daemon=True,
        )
        thread.start()
        return slot

    def _emit_slot(self, slot: _Slot) -> bool:
        if self._is_stale(slot.gen):
            logger.info("StreamingHeadPrefetchHandler: dropping stale prefetched slot")
            return False
        noted_playing = False
        for chunk in slot.chunks:
            if self._is_stale(slot.gen):
                logger.info("StreamingHeadPrefetchHandler: dropping remaining stale prefetched chunks")
                return False
            if not noted_playing:
                self._note_playing_text(slot.text, slot.gen)
                noted_playing = True
            self.queue_out.put(chunk)
        return True

    def run(self):
        logger.info("StreamingHeadPrefetchHandler: started (prefetch=%d)", self.prefetch)
        pending: deque[_Slot] = deque()
        stream_state: _StreamState | None = None
        response_needs_streaming_head = True
        should_exit = False

        try:
            while not self.stop_event.is_set():
                active_stream_is_stale = bool(stream_state is not None and self._is_stale(stream_state.gen))
                if stream_state is not None and active_stream_is_stale:
                    stream_state.stale = True

                if stream_state is not None and stream_state.done.is_set():
                    if stream_state.thread is not None:
                        stream_state.thread.join(timeout=0.01)
                    if stream_state.stale:
                        pending = deque(slot for slot in pending if not self._is_stale(slot.gen))
                        self._drain_stale_input()
                        response_needs_streaming_head = True
                    stream_state = None

                while not should_exit and len(pending) < self.prefetch:
                    if stream_state is not None and self._is_stale(stream_state.gen):
                        # Keep new-generation input queued until the stale
                        # streaming head has stopped, so its first sentence can
                        # become the next streaming head instead of a prefetched slot.
                        break
                    try:
                        item = self.queue_in.get(timeout=0.02)
                    except Empty:
                        break

                    if isinstance(item, bytes) and item == b"END":
                        should_exit = True
                        break

                    if stream_state is not None and self._is_stale(stream_state.gen):
                        self._requeue_front(item)
                        break

                    if is_control_message(item, SESSION_END.kind):
                        pending.clear()
                        try:
                            self.inner.on_session_end()
                        except Exception as e:
                            logger.error(
                                "StreamingHeadPrefetchHandler: on_session_end error: %s",
                                e,
                                exc_info=True,
                            )
                        self.queue_out.put(item)
                        response_needs_streaming_head = True
                        continue

                    if (
                        response_needs_streaming_head
                        and stream_state is None
                        and not pending
                        and not self._is_response_end(item)
                    ):
                        response_needs_streaming_head = False
                        stream_state = _StreamState(gen=self._item_gen(item))
                        stream_state.thread = threading.Thread(
                            target=self._stream_worker,
                            args=(item, stream_state),
                            daemon=True,
                        )
                        stream_state.thread.start()
                        continue

                    pending.append(self._start_prefetch(item))

                if stream_state is None and pending:
                    slot = pending[0]
                    if slot.wait(timeout=0.02):
                        pending.popleft()
                        emitted = self._emit_slot(slot)
                        if not emitted and self._is_stale(slot.gen):
                            pending.clear()
                            self._drain_stale_input()
                        if slot.is_response_end:
                            response_needs_streaming_head = True
                        continue

                if should_exit:
                    if stream_state is not None:
                        stream_state.done.wait(timeout=10.0)
                        stream_state = None
                    self._drain(pending)
                    self.queue_out.put(b"END")
                    return
        finally:
            logger.debug("StreamingHeadPrefetchHandler: stopped")

    def _drain_stale_input(self):
        current_gen = self.cancel_scope.generation if self.cancel_scope else None
        while True:
            try:
                item = self.queue_in.get_nowait()
            except Empty:
                break
            if isinstance(item, bytes) and item == b"END":
                self._requeue_front(item)
                break
            if is_control_message(item, SESSION_END.kind):
                self._requeue_front(item)
                break
            if self._is_response_end(item):
                item_gen = self._item_gen(item)
                if current_gen is None or item_gen is None or item_gen == current_gen:
                    self._requeue_front(item)
                break
            item_gen = self._item_gen(item)
            if current_gen is not None and item_gen == current_gen:
                self._requeue_front(item)
                break

    def _drain(self, pending: deque[_Slot]):
        while pending:
            slot = pending.popleft()
            slot.wait(timeout=10.0)
            if self._is_stale(slot.gen):
                continue
            self._emit_slot(slot)
