"""Unit tests for PrefetchHandler."""

import sys
import time
from pathlib import Path
from threading import Event, Thread
from queue import Queue

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.prefetch_handler import PrefetchHandler
from pipeline.control import SESSION_END


class FakeTTSHandler:
    """Minimal TTS handler stub for testing PrefetchHandler."""

    def __init__(self, delay=0.0):
        self.stop_event = Event()
        self.queue_in = Queue()
        self.queue_out = Queue()
        self.delay = delay
        self.session_ended = False

    def process(self, item):
        if isinstance(item, tuple) and item[0] == "__END_OF_RESPONSE__":
            yield b"__RESPONSE_DONE__"
            return
        text = item if isinstance(item, str) else item[0]
        if self.delay:
            time.sleep(self.delay)
        # Yield a chunk identifying the input
        yield f"audio:{text}"

    def on_session_end(self):
        self.session_ended = True


def _run_prefetch(inner, prefetch=2, timeout=5.0):
    """Run PrefetchHandler in a background thread, return collected outputs."""
    ph = PrefetchHandler(inner, prefetch=prefetch)
    t = Thread(target=ph.run, daemon=True)
    t.start()
    return ph, t


class TestPrefetchOrdering:
    def test_output_order_matches_input(self):
        inner = FakeTTSHandler(delay=0.05)
        ph, t = _run_prefetch(inner, prefetch=2)

        sentences = ["one", "two", "three", "four"]
        for s in sentences:
            inner.queue_in.put(s)
        inner.queue_in.put(b"END")

        results = []
        while True:
            item = inner.queue_out.get(timeout=5)
            if isinstance(item, bytes) and item == b"END":
                break
            results.append(item)

        assert results == [f"audio:{s}" for s in sentences]
        t.join(timeout=2)

    def test_single_item(self):
        inner = FakeTTSHandler()
        ph, t = _run_prefetch(inner)

        inner.queue_in.put("hello")
        inner.queue_in.put(b"END")

        results = []
        while True:
            item = inner.queue_out.get(timeout=5)
            if isinstance(item, bytes) and item == b"END":
                break
            results.append(item)

        assert results == ["audio:hello"]
        t.join(timeout=2)


class TestPrefetchParallelism:
    def test_parallel_faster_than_serial(self):
        delay = 0.1
        n_items = 4
        inner = FakeTTSHandler(delay=delay)
        ph, t = _run_prefetch(inner, prefetch=2)

        t0 = time.perf_counter()
        for i in range(n_items):
            inner.queue_in.put(f"s{i}")
        inner.queue_in.put(b"END")

        results = []
        while True:
            item = inner.queue_out.get(timeout=10)
            if isinstance(item, bytes) and item == b"END":
                break
            results.append(item)
        elapsed = time.perf_counter() - t0

        assert len(results) == n_items
        serial_time = n_items * delay
        # With prefetch=2, should be noticeably faster than serial
        assert elapsed < serial_time * 0.85
        t.join(timeout=2)


class TestPrefetchControlMessages:
    def test_end_sentinel_drains_and_exits(self):
        inner = FakeTTSHandler(delay=0.02)
        ph, t = _run_prefetch(inner)

        inner.queue_in.put("a")
        inner.queue_in.put("b")
        inner.queue_in.put(b"END")

        results = []
        while True:
            item = inner.queue_out.get(timeout=5)
            if isinstance(item, bytes) and item == b"END":
                break
            results.append(item)

        assert "audio:a" in results
        assert "audio:b" in results
        t.join(timeout=2)
        assert not t.is_alive()

    def test_session_end_passes_through(self):
        inner = FakeTTSHandler()
        ph, t = _run_prefetch(inner)

        inner.queue_in.put("before")
        time.sleep(0.1)  # Let it process
        inner.queue_in.put(SESSION_END)
        time.sleep(0.1)
        inner.queue_in.put("after")
        inner.queue_in.put(b"END")

        results = []
        while True:
            item = inner.queue_out.get(timeout=5)
            if isinstance(item, bytes) and item == b"END":
                break
            results.append(item)

        assert "audio:before" in results
        assert SESSION_END in results
        assert "audio:after" in results
        assert inner.session_ended
        t.join(timeout=2)

    def test_stop_event_terminates(self):
        inner = FakeTTSHandler(delay=1.0)
        ph, t = _run_prefetch(inner)

        inner.queue_in.put("slow")
        time.sleep(0.1)
        inner.stop_event.set()

        t.join(timeout=3)
        assert not t.is_alive()


class TestPrefetchSynthesizeStatic:
    def test_materializes_generator(self):
        def fake_process(item):
            yield "chunk1"
            yield "chunk2"

        result = PrefetchHandler._synthesize(fake_process, "test")
        assert result == ["chunk1", "chunk2"]

    def test_empty_generator(self):
        def fake_process(item):
            return
            yield  # make it a generator

        result = PrefetchHandler._synthesize(fake_process, "test")
        assert result == []
