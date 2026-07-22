import threading
import time
from queue import Queue

from handlers.llm.chat import Chat
from handlers.heartbeat_interaction.handler import HeartbeatInteractionHandler
from handlers.heartbeat_interaction.history_formatter import build_sft_prompt
from handlers.heartbeat_interaction.heartbeat_cache import HeartBeatCache
from pipeline.turn_audio_history import TurnAudioHistory
import numpy as np


def test_audio_history_uses_same_turn_window_as_chat():
    chat = Chat(size=1)
    audio_history = TurnAudioHistory(
        max_turns=chat.size + 1,
        max_total_seconds=None,
    )

    for idx in range(3):
        audio_history.append(f"audio{idx}", duration_s=10_000.0)
        chat.append({"role": "user", "content": f"u{idx}"})
        chat.append({"role": "assistant", "content": f"a{idx}"})

    assert audio_history.snapshot() == ["audio1", "audio2"]
    assert [m["content"] for m in chat.buffer if m["role"] == "user"] == ["u1", "u2"]


def test_audio_history_has_no_independent_duration_eviction_when_disabled():
    audio_history = TurnAudioHistory(max_turns=3, max_total_seconds=None)

    for idx in range(3):
        audio_history.append(f"audio{idx}", duration_s=10_000.0)

    assert audio_history.snapshot() == ["audio0", "audio1", "audio2"]


def test_prompt_audio_tag_count_matches_unified_history_window():
    chat = Chat(size=1)
    audio_history = TurnAudioHistory(
        max_turns=chat.size + 1,
        max_total_seconds=None,
    )

    for idx in range(3):
        audio_history.append(f"audio{idx}", duration_s=1.0)
        chat.append({"role": "user", "content": f"u{idx}"})
        chat.append({"role": "assistant", "content": f"a{idx}"})

    prompt = build_sft_prompt(chat.to_list(), block_idx=0)
    history_audio = audio_history.snapshot()

    assert prompt["messages"][1]["content"].count("<audio>") == len(history_audio) + 1


def test_predict_request_projects_audio_to_user_turns_in_chat():
    handler = object.__new__(HeartbeatInteractionHandler)
    handler.chat_ref = type("ChatRef", (), {
        "to_list": lambda self: [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "old final answer"},
            {"role": "user", "content": "latest user"},
            {"role": "assistant", "content": "latest answer"},
        ]
    })()
    handler.turn_audio_history = type("AudioHistory", (), {
        "snapshot": lambda self: ["old_audio", "latest_audio"]
    })()
    handler.block_duration_ms = 500
    handler.block_size = 8000
    handler.current_turn_audio = np.array([], dtype=np.float32)
    handler.last_processed_block = 0
    handler.heartbeat_cache = None
    handler.cancel_scope = None
    handler.prompt_template = None
    handler.triggered_tools_this_turn = set()
    handler._consumed_detected = False
    handler._pending_drain = False
    handler._turn_generation = 0
    handler.blocking = True

    captured = {}

    def fake_call(sft_prompt, cumulative_audio, history_audio_b64):
        captured["history_audio_b64"] = history_audio_b64
        captured["audio_tags"] = sft_prompt["messages"][1]["content"].count("<audio>")
        return None

    handler._call_predict_model = fake_call

    list(handler.process(np.zeros(8000, dtype=np.float32)))

    assert captured["history_audio_b64"] == ["latest_audio"]
    assert captured["audio_tags"] == 2


def test_omni_predict_nonblocking_stores_heartbeat_result():
    class ToolRegistry:
        def execute(self, tool_name, arguments_json):
            return f"result:{tool_name}:{arguments_json}"

    chat = Chat(size=1)
    cache = HeartBeatCache(max_entries=2)
    handler = HeartbeatInteractionHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": chat,
            "heartbeat_cache": cache,
            "tool_registry": ToolRegistry(),
            "blocking": False,
            "max_concurrent": 1,
        },
    )

    def fake_call(_sft_prompt, _cumulative_audio, _history_audio_b64):
        return '{"query_epos_order":"NO_QUERY","search_epos_knowledge":{"query":"wifi setup"}}'

    handler._call_predict_model = fake_call

    assert list(handler.process(np.zeros(handler.block_size, dtype=np.float32))) == []

    deadline = time.time() + 2.0
    while time.time() < deadline:
        with cache._lock:
            if cache._entries:
                break
        time.sleep(0.01)

    with cache._lock:
        assert len(cache._entries) == 1
        entry = cache._entries[0]

    assert entry.order_key == 0
    assert entry.items[0].tool_name == "search_epos_knowledge"
    assert entry.items[0].arguments == {"query": "wifi setup"}
    assert handler.max_concurrent == 1
