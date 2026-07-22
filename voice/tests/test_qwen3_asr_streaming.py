import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import numpy as np

from handlers.stt.fake_streaming_asr import TURN_END
from handlers.stt.qwen3_asr_streaming_handler import Qwen3ASRStreamingHandler


def _handler(**kwargs):
    setup = {
        "base_url": "http://asr.test",
        "feed_duration_ms": 500,
        "interim_text_queue": Queue(),
    }
    setup.update(kwargs)
    return Qwen3ASRStreamingHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs=setup,
    )


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _ConcurrentProbeSession:
    def __init__(self, monitor, name):
        self.monitor = monitor
        self.name = name

    def post(self, url, **kwargs):
        with self.monitor["lock"]:
            self.monitor["active"] += 1
            self.monitor["max_active"] = max(self.monitor["max_active"], self.monitor["active"])
            if self.monitor["active"] > 1:
                self.monitor["overlaps"].append(url)
        try:
            time.sleep(0.02)
            if url.endswith("/api/start"):
                return _FakeResponse({"session_id": self.name})
            if url.endswith("/api/chunk"):
                return _FakeResponse({"language": "zh", "text": f"{self.name}文本"})
            if url.endswith("/api/finish"):
                return _FakeResponse({"language": "zh", "text": f"{self.name}完成"})
            return _FakeResponse({})
        finally:
            with self.monitor["lock"]:
                self.monitor["active"] -= 1

    def close(self):
        return None


def test_qwen3_asr_streaming_emits_interim_and_final_reuse():
    interim_queue = Queue()
    text_output_queue = Queue()
    handler = _handler(
        interim_text_queue=interim_queue,
        text_output_queue=text_output_queue,
    )

    posted = []
    finished = []

    def fake_post(chunk):
        posted.append(len(chunk))
        return {"language": "Chinese", "text": "喂，你好。"}

    def fake_finish():
        finished.append(True)
        return {"language": "Chinese", "text": "喂，你好。"}

    handler._post_chunk = fake_post
    handler._finish_remote_session = fake_finish

    full_block = np.zeros(handler.feed_size, dtype=np.float32)
    assert list(handler.process(full_block)) == []
    assert list(handler.process(TURN_END)) == [("喂，你好。", "zh")]

    assert posted == [handler.feed_size]
    assert finished == [True]
    assert interim_queue.get_nowait() == ("喂，你好。", 0)
    assert interim_queue.get_nowait() == TURN_END


def test_qwen3_asr_streaming_flushes_tail_on_turn_end():
    interim_queue = Queue()
    handler = _handler(
        interim_text_queue=interim_queue,
        final_reuse_interim_tail_ms=100,
    )

    posted = []

    def fake_post(chunk):
        posted.append(len(chunk))
        if len(posted) == 1:
            return {"language": "zh", "text": "打开"}
        return {"language": "zh", "text": "打开蓝牙。"}

    def fake_finish():
        return {"language": "zh", "text": handler._last_interim_text}

    handler._post_chunk = fake_post
    handler._finish_remote_session = fake_finish

    full_block = np.zeros(handler.feed_size, dtype=np.float32)
    tail = np.zeros(handler.feed_size // 2, dtype=np.float32)

    assert list(handler.process(full_block)) == []
    assert list(handler.process(tail)) == []
    assert list(handler.process(TURN_END)) == [("打开蓝牙。", "zh")]

    assert posted == [handler.feed_size, handler.feed_size // 2]
    assert interim_queue.get_nowait() == ("打开", 0)
    assert interim_queue.get_nowait() == ("打开蓝牙。", 1)
    assert interim_queue.get_nowait() == TURN_END


def test_qwen3_asr_streaming_serializes_remote_requests_across_handlers_by_default():
    monitor = {
        "lock": threading.Lock(),
        "active": 0,
        "max_active": 0,
        "overlaps": [],
    }
    h1 = _handler()
    h2 = _handler()
    h1._session = _ConcurrentProbeSession(monitor, "甲")
    h2._session = _ConcurrentProbeSession(monitor, "乙")

    barrier = threading.Barrier(2)
    full_block = np.zeros(h1.feed_size, dtype=np.float32)

    def run(handler):
        barrier.wait(timeout=1)
        return list(handler.process(full_block))

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1 = pool.submit(run, h1)
        r2 = pool.submit(run, h2)
        assert r1.result(timeout=2) == []
        assert r2.result(timeout=2) == []

    assert monitor["overlaps"] == []
    assert monitor["max_active"] == 1
    assert h1.interim_text_queue.get_nowait() == ("甲文本", 0)
    assert h2.interim_text_queue.get_nowait() == ("乙文本", 0)


def test_qwen3_asr_streaming_allows_remote_requests_when_serialization_disabled():
    monitor = {
        "lock": threading.Lock(),
        "active": 0,
        "max_active": 0,
        "overlaps": [],
    }
    h1 = _handler(serialize_requests=False)
    h2 = _handler(serialize_requests=False)
    h1._session = _ConcurrentProbeSession(monitor, "甲")
    h2._session = _ConcurrentProbeSession(monitor, "乙")

    barrier = threading.Barrier(2)
    full_block = np.zeros(h1.feed_size, dtype=np.float32)

    def run(handler):
        barrier.wait(timeout=1)
        return list(handler.process(full_block))

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1 = pool.submit(run, h1)
        r2 = pool.submit(run, h2)
        assert r1.result(timeout=2) == []
        assert r2.result(timeout=2) == []

    assert monitor["overlaps"]
    assert monitor["max_active"] == 2
    assert h1.interim_text_queue.get_nowait() == ("甲文本", 0)
    assert h2.interim_text_queue.get_nowait() == ("乙文本", 0)
