import time
from queue import Queue
from threading import Event, Lock, Thread

from pipeline.cancel_scope import CancelScope
from pipeline.streaming_prefetch_handler import StreamingHeadPrefetchHandler


class FakeStreamingTTS:
    def __init__(self):
        self.stop_event = Event()
        self.queue_in = Queue()
        self.queue_out = Queue()
        self.starts = {}
        self._lock = Lock()

    def process(self, item):
        if isinstance(item, tuple) and item[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return

        text = item[0] if isinstance(item, tuple) else item
        with self._lock:
            self.starts[text] = time.perf_counter()

        if text == "first":
            yield "first:chunk0"
            time.sleep(0.15)
            yield "first:chunk1"
        elif text == "second":
            time.sleep(0.05)
            yield "second:chunk0"
        elif text == "old_second":
            time.sleep(0.05)
            yield "old_second:chunk0"
        elif text == "new_first":
            yield "new_first:chunk0"

    def on_session_end(self):
        pass


def test_streaming_head_prefetch_streams_first_and_prefetches_second():
    inner = FakeStreamingTTS()
    wrapper = StreamingHeadPrefetchHandler(inner, prefetch=1)
    thread = Thread(target=wrapper.run, daemon=True)
    thread.start()

    t0 = time.perf_counter()
    inner.queue_in.put(("first", "en", 1))
    inner.queue_in.put(("second", "en", 1))
    inner.queue_in.put(("__END_OF_RESPONSE__", None, 1))
    inner.queue_in.put(b"END")

    first_chunk = inner.queue_out.get(timeout=1)
    first_chunk_ms = (time.perf_counter() - t0) * 1000
    assert first_chunk == "first:chunk0"
    assert first_chunk_ms < 100

    outputs = [first_chunk]
    while True:
        item = inner.queue_out.get(timeout=3)
        outputs.append(item)
        if item == b"END":
            break

    assert outputs == [
        "first:chunk0",
        "first:chunk1",
        "second:chunk0",
        b"__RESPONSE_DONE__",
        b"END",
    ]
    assert inner.starts["second"] < inner.starts["first"] + 0.15
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_streaming_head_cancel_drops_old_prefetch_and_streams_new_generation_head():
    inner = FakeStreamingTTS()
    cancel_scope = CancelScope()
    wrapper = StreamingHeadPrefetchHandler(inner, prefetch=1, cancel_scope=cancel_scope)
    thread = Thread(target=wrapper.run, daemon=True)
    thread.start()

    inner.queue_in.put(("first", "en", 0))
    inner.queue_in.put(("old_second", "en", 0))

    assert inner.queue_out.get(timeout=1) == "first:chunk0"

    cancel_scope.cancel()
    inner.queue_in.put(("new_first", "en", 1))
    inner.queue_in.put(("__END_OF_RESPONSE__", None, 1))
    inner.queue_in.put(b"END")

    outputs = []
    while True:
        item = inner.queue_out.get(timeout=3)
        outputs.append(item)
        if item == b"END":
            break

    assert "first:chunk1" not in outputs
    assert "old_second:chunk0" not in outputs
    assert outputs == ["new_first:chunk0", b"__RESPONSE_DONE__", b"END"]
    thread.join(timeout=1)
    assert not thread.is_alive()
