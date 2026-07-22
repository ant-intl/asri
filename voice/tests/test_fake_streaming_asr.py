import threading
from queue import Queue

import numpy as np

from handlers.stt.fake_streaming_asr import FakeStreamingASRHandler, TURN_END


def test_turn_end_runs_final_asr_even_after_periodic_result():
    interim_queue = Queue()
    handler = FakeStreamingASRHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "asr_backend": "sensevoice",
            "block_duration_ms": 500,
            "final_reuse_interim_tail_ms": 0,
            "interim_text_queue": interim_queue,
        },
    )

    call_lengths = []

    def fake_asr(audio):
        call_lengths.append(len(audio))
        return f"text-{len(call_lengths)}"

    handler._call_asr_sensevoice = fake_asr

    full_block = np.zeros(handler.block_size, dtype=np.float32)
    tail = np.zeros(handler.block_size // 2, dtype=np.float32)

    assert list(handler.process(full_block)) == []
    assert list(handler.process(tail)) == []
    assert list(handler.process(TURN_END)) == [("text-2", "zh")]

    assert call_lengths == [handler.block_size, handler.block_size + len(tail)]
    assert interim_queue.get_nowait() == ("text-1", 0)
    assert interim_queue.get_nowait() == TURN_END


def test_turn_end_queued_in_backlog_skips_stale_interim_asr():
    interim_queue = Queue()
    queue_in = Queue()
    handler = FakeStreamingASRHandler(
        threading.Event(),
        queue_in,
        Queue(),
        setup_kwargs={
            "asr_backend": "sensevoice",
            "block_duration_ms": 500,
            "interim_text_queue": interim_queue,
        },
    )

    call_lengths = []

    def fake_asr(audio):
        call_lengths.append(len(audio))
        return f"text-{len(audio)}"

    handler._call_asr_sensevoice = fake_asr

    full_block = np.zeros(handler.block_size, dtype=np.float32)
    tail = np.zeros(handler.block_size // 2, dtype=np.float32)
    queue_in.put(tail)
    queue_in.put(TURN_END)

    assert list(handler.process(full_block)) == [
        (f"text-{len(full_block) + len(tail)}", "zh")
    ]

    assert call_lengths == [len(full_block) + len(tail)]
    assert interim_queue.get_nowait() == TURN_END
    assert interim_queue.empty()


def test_turn_end_reuses_recent_interim_when_tail_is_small():
    interim_queue = Queue()
    handler = FakeStreamingASRHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "asr_backend": "sensevoice",
            "block_duration_ms": 500,
            "interim_text_queue": interim_queue,
        },
    )

    tail = np.zeros(handler.block_size // 2, dtype=np.float32)
    handler._audio_buffer = np.concatenate([
        np.zeros(handler.block_size, dtype=np.float32),
        tail,
    ])
    handler._last_processed_block = 1
    handler._last_interim_text = "喂，你好。"

    def fail_if_called(_audio):
        raise AssertionError("final ASR should not run for a small tail")

    handler._call_asr_sensevoice = fail_if_called

    assert list(handler.process(TURN_END)) == [("喂，你好。", "zh")]
    assert interim_queue.get_nowait() == TURN_END


def test_streaming_asr_emits_debug_events_for_interim_and_final_reuse():
    interim_queue = Queue()
    text_output_queue = Queue()
    handler = FakeStreamingASRHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "asr_backend": "sensevoice",
            "block_duration_ms": 500,
            "interim_text_queue": interim_queue,
            "text_output_queue": text_output_queue,
        },
    )

    handler._call_asr_sensevoice = lambda _audio: "喂，你好。"

    full_block = np.zeros(handler.block_size, dtype=np.float32)
    assert list(handler.process(full_block)) == []
    assert list(handler.process(TURN_END)) == [("喂，你好。", "zh")]

    events = []
    while not text_output_queue.empty():
        events.append(text_output_queue.get_nowait())

    assert any(
        event.get("type") == "asr_debug"
        and event.get("event") == "interim"
        and event.get("block_idx") == 0
        and event.get("text") == "喂，你好。"
        for event in events
    )
    assert any(
        event.get("type") == "asr_debug"
        and event.get("event") == "final_reuse"
        and event.get("text") == "喂，你好。"
        for event in events
    )
