from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_replay_runner():
    path = REPO_ROOT / "scripts" / "run_distillation_seed_replay.py"
    spec = importlib.util.spec_from_file_location("run_distillation_seed_replay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        heartbeat_block_duration_ms=500,
        tool_mock_simulated_latency_min_ms=20,
        tool_mock_simulated_latency_max_ms=100,
        speed=1.0,
    )


def test_trace_uses_virtual_response_start_on_virtual_timeline() -> None:
    from client.replay.trace_builder import build_replay_trace

    args = _args()
    args.virtual_response_start_ms = 1500

    trace = build_replay_trace(
        {"current_audio_path": "turn0.wav"},
        [
            {
                "client_elapsed_ms": 10,
                "event": {
                    "type": "heartbeat_thinking",
                    "event": "thinking",
                    "block_idx": 1,
                    "thinking": "visible at virtual 1000ms",
                },
            },
            {
                "client_elapsed_ms": 20,
                "event": {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "hello",
                },
            },
        ],
        args,
    )

    assert trace["response_event"]["response_start_ms"] == 1500
    assert trace["response_event"]["response_start_source"] == "virtual_audio_timeline"
    assert trace["asr"]["wall_transcription_completed_ms"] == 20
    assert trace["audio"]["send_speed"] == 1.0
    assert trace["heartbeat_context"] == [
        {
            "block": 1,
            "action": "think",
            "tools": [],
            "thinking": "visible at virtual 1000ms",
        }
    ]


def test_response_sample_renders_tool_calls_as_xml() -> None:
    runner = _load_replay_runner()

    class PassthroughResponseWithReferenceClient:
        def build(self, **kwargs):
            return {
                "asr_equivalent": True,
                "reference_adjusted": False,
                "reason": "Keep the GT reference messages.",
                "heartbeat_coverage": [],
                "messages": kwargs["current_turn_messages"],
            }, {"response_with_reference_wall_latency_ms": 1, "model": "fake", "base_url": "fake"}

    row = {
        "seed_conversations": [
            {"role": "user", "content": "Check order A1."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_seed_1",
                        "type": "function",
                        "function": {
                            "name": "lookup_order",
                            "arguments": "{\"order_id\":\"A1\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_seed_1",
                "name": "lookup_order",
                "content": "{\"status\":\"shipped\"}",
            },
            {"role": "assistant", "content": "Order A1 has shipped."},
        ],
        "current_user_index": 0,
        "target_assistant_index": 3,
        "current_audio_path": "turn0.wav",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup_order",
                    "parameters": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    },
                },
            }
        ],
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "response_input_messages": [
            {"role": "user", "content": "Check order A1."},
        ],
        "heartbeat_context": [],
        "session_state": {"subtasks": []},
        "target_tool_trace": [],
        "asr": {"transcript": "Check order A1."},
    }

    sample, info = runner._build_response_with_reference_sample(
        row,
        trace,
        response_with_reference_client=PassthroughResponseWithReferenceClient(),
    )

    assert info["status"] == "ok"
    assert sample is not None
    assistant_with_tool = sample["conversations"][1]
    tool_message = sample["conversations"][2]
    assert assistant_with_tool == {
        "from": "assistant",
        "value": '<tool_call>\n{"name":"lookup_order","arguments":{"order_id":"A1"}}\n</tool_call>',
    }
    assert tool_message == {
        "from": "user",
        "value": '<tool_result>\n{"name":"lookup_order","result":{"status":"shipped"}}\n</tool_result>',
    }


def test_real_response_sample_renders_historical_tool_calls_as_xml(tmp_path) -> None:
    from client.replay.replay_session import ReplaySession

    session = ReplaySession(
        row={
            "system_prompt": "<SYSTEM>",
            "history_messages": [
                {"role": "user", "content": "Check order H1."},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_hist_1",
                            "type": "function",
                            "function": {
                                "name": "lookup_order",
                                "arguments": "{\"order_id\":\"H1\"}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_hist_1",
                    "name": "lookup_order",
                    "content": "{\"status\":\"delivered\"}",
                },
                {"role": "assistant", "content": "Order H1 was delivered."},
            ],
            "history_audio_paths": ["turn0.wav"],
            "current_audio_path": "turn1.wav",
            "tools": [{"type": "function", "function": {"name": "lookup_order"}}],
        },
        host="127.0.0.1",
        port=8765,
        config_path="configs/asri-voice.yaml",
        speed=1.0,
        client_timeout_s=1.0,
        drain_after_transcription_s=0.0,
        heartbeat_block_duration_ms=500,
        tool_mock_simulated_latency_min_ms=20,
        tool_mock_simulated_latency_max_ms=100,
        work_dir=tmp_path,
        log_dir=tmp_path,
        idx=1,
        response_with_reference_client=None,
        tool_trigger_judge=None,
    )
    sample = session._build_real_response_sample([
        {"event": {"type": "response.created"}},
        {"event": {"type": "response.output_text.delta", "delta": "Current answer."}},
        {"event": {"type": "response.done", "status": "completed"}},
    ])

    assert sample is not None
    assert sample["tools"] == [{"type": "function", "function": {"name": "lookup_order"}}]
    assert "### Tool Call XML Format" in sample["conversations"][0]["value"]
    assert sample["conversations"][1] == {"from": "user", "value": "<audio>"}
    assert sample["conversations"][2] == {
        "from": "assistant",
        "value": '<tool_call>\n{"name":"lookup_order","arguments":{"order_id":"H1"}}\n</tool_call>',
    }
    assert sample["conversations"][3] == {
        "from": "user",
        "value": '<tool_result>\n{"name":"lookup_order","result":{"status":"delivered"}}\n</tool_result>',
    }
    assert sample["conversations"][4] == {"from": "assistant", "value": "Order H1 was delivered."}
    assert sample["conversations"][-1] == {"from": "assistant", "value": "Current answer."}
    assert all("tool_calls" not in message for message in sample["conversations"])
    assert all(message["from"] != "tool" for message in sample["conversations"])


def test_history_toolcall_drop_removes_empty_assistant_and_paired_tool_result(tmp_path) -> None:
    from client.replay.replay_session import ReplaySession

    class AlwaysDrop:
        def random(self) -> float:
            return 0.0

    session = ReplaySession(
        row={"history_messages": [], "current_audio_path": "turn1.wav"},
        host="127.0.0.1",
        port=8765,
        config_path="configs/asri-voice.yaml",
        speed=1.0,
        client_timeout_s=1.0,
        drain_after_transcription_s=0.0,
        heartbeat_block_duration_ms=500,
        tool_mock_simulated_latency_min_ms=20,
        tool_mock_simulated_latency_max_ms=100,
        work_dir=tmp_path,
        log_dir=tmp_path,
        idx=1,
        response_with_reference_client=None,
        tool_trigger_judge=None,
    )
    messages = [
        {"role": "user", "content": "Get a quote."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_hist_1",
                    "type": "function",
                    "function": {"name": "generate_random_quote", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_hist_1",
            "name": "generate_random_quote",
            "content": '{"quote":"Stay hungry."}',
        },
        {"role": "assistant", "content": "Stay hungry."},
    ]

    dropped = session._maybe_drop_history_toolcalls(messages, 1.0, AlwaysDrop())

    assert dropped == [
        {"role": "user", "content": "Get a quote."},
        {"role": "assistant", "content": "Stay hungry."},
    ]
    assert session.dropped_history_toolcalls == [
        {
            "tool_call_id": "call_hist_1",
            "name": "generate_random_quote",
            "arguments": "{}",
        }
    ]


def test_history_payload_drops_orphan_empty_assistant_tool_result(tmp_path) -> None:
    from client.replay.replay_session import ReplaySession

    session = ReplaySession(
        row={
            "history_messages": [
                {"role": "user", "content": "Get a quote."},
                {"role": "assistant", "content": ""},
                {
                    "role": "tool",
                    "name": "generate_random_quote",
                    "content": '{"quote":"Stay hungry."}',
                },
                {"role": "assistant", "content": "Stay hungry."},
            ],
            "current_audio_path": "turn1.wav",
        },
        host="127.0.0.1",
        port=8765,
        config_path="configs/asri-voice.yaml",
        speed=1.0,
        client_timeout_s=1.0,
        drain_after_transcription_s=0.0,
        heartbeat_block_duration_ms=500,
        tool_mock_simulated_latency_min_ms=20,
        tool_mock_simulated_latency_max_ms=100,
        work_dir=tmp_path,
        log_dir=tmp_path,
        idx=1,
        response_with_reference_client=None,
        tool_trigger_judge=None,
    )

    payload = session._build_history_payload()

    assert payload["messages"] == [
        {"role": "user", "content": "Get a quote."},
        {"role": "assistant", "content": "Stay hungry."},
    ]


def test_response_sft_filters_dropped_history_toolcall_pairs() -> None:
    from client.replay.sft_sample_builder import build_response_with_reference_sample

    class PassthroughResponseWithReferenceClient:
        def build(self, **kwargs):
            return {
                "asr_equivalent": True,
                "reference_adjusted": False,
                "reason": "Keep the current turn reference.",
                "heartbeat_coverage": [],
                "messages": kwargs["current_turn_messages"],
            }, {"response_with_reference_wall_latency_ms": 1, "model": "fake", "base_url": "fake"}

    row = {
        "current_user_text": "Give me another quote.",
        "seed_conversations": [
            {"role": "user", "content": "Give me a quote."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_hist_1",
                        "type": "function",
                        "function": {"name": "generate_random_quote", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_hist_1",
                "name": "generate_random_quote",
                "content": '{"quote":"Stay hungry."}',
            },
            {"role": "assistant", "content": "Stay hungry."},
            {"role": "user", "content": "Give me another quote."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_cur_1",
                        "type": "function",
                        "function": {"name": "generate_random_quote", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_cur_1",
                "name": "generate_random_quote",
                "content": '{"quote":"Stay foolish."}',
            },
            {"role": "assistant", "content": "Stay foolish."},
        ],
        "current_user_index": 4,
        "target_assistant_index": 7,
        "history_audio_paths": ["turn0.wav"],
        "current_audio_path": "turn1.wav",
        "tools": [{"type": "function", "function": {"name": "generate_random_quote"}}],
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "response_input_messages": [
            {"role": "system", "content": "<SYSTEM>"},
            {"role": "user", "content": "Give me a quote."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_hist_1",
                        "type": "function",
                        "function": {"name": "generate_random_quote", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_hist_1",
                "name": "generate_random_quote",
                "content": '{"quote":"Stay hungry."}',
            },
            {"role": "assistant", "content": "Stay hungry."},
            {"role": "user", "content": "Give me another quote."},
        ],
        "heartbeat_context": [],
        "target_tool_trace": [
            {"name": "generate_random_quote", "arguments": {}, "result": {"quote": "Stay foolish."}},
        ],
        "asr": {"transcript": "Give me another quote."},
    }

    sample, info = build_response_with_reference_sample(
        row,
        trace,
        response_with_reference_client=PassthroughResponseWithReferenceClient(),
        dropped_history_toolcalls=[
            {"tool_call_id": "call_hist_1", "name": "generate_random_quote", "arguments": "{}"},
        ],
    )

    assert info["status"] == "ok"
    assert sample is not None
    assert sample["conversations"] == [
        {"from": "system", "value": "<SYSTEM>\n\n### Tool Call XML Format\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{\"name\": <function-name>, \"arguments\": <args-json-object>}\n</tool_call>"},
        {"from": "user", "value": "<audio>"},
        {"from": "assistant", "value": "Stay hungry."},
        {"from": "user", "value": "Give me another quote."},
        {
            "from": "assistant",
            "value": '<tool_call>\n{"name":"generate_random_quote","arguments":{}}\n</tool_call>',
        },
        {
            "from": "user",
            "value": '<tool_result>\n{"name":"generate_random_quote","result":{"quote":"Stay foolish."}}\n</tool_result>',
        },
        {"from": "assistant", "value": "Stay foolish."},
    ]
    assert all(message["value"] for message in sample["conversations"] if message["from"] == "assistant")


def test_response_sft_filters_orphan_empty_assistant_tool_result() -> None:
    from client.replay.sft_sample_builder import build_response_with_reference_sample

    class PassthroughResponseWithReferenceClient:
        def build(self, **kwargs):
            return {
                "asr_equivalent": True,
                "reference_adjusted": False,
                "reason": "Keep the current turn reference.",
                "heartbeat_coverage": [],
                "messages": kwargs["current_turn_messages"],
            }, {"response_with_reference_wall_latency_ms": 1, "model": "fake", "base_url": "fake"}

    row = {
        "current_user_text": "Give me another quote.",
        "seed_conversations": [
            {"role": "user", "content": "Give me a quote."},
            {"role": "assistant", "content": ""},
            {"role": "tool", "name": "generate_random_quote", "content": '{"quote":"Stay hungry."}'},
            {"role": "assistant", "content": "Stay hungry."},
            {"role": "user", "content": "Give me another quote."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_cur_1",
                        "type": "function",
                        "function": {"name": "generate_random_quote", "arguments": "{}"},
                    }
                ],
            },
        ],
        "current_user_index": 4,
        "target_assistant_index": 5,
        "history_audio_paths": ["turn0.wav"],
        "current_audio_path": "turn1.wav",
        "tools": [{"type": "function", "function": {"name": "generate_random_quote"}}],
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "response_input_messages": [
            {"role": "system", "content": "<SYSTEM>"},
            {"role": "user", "content": "Give me a quote."},
            {"role": "assistant", "content": ""},
            {"role": "tool", "name": "generate_random_quote", "content": '{"quote":"Stay hungry."}'},
            {"role": "assistant", "content": "Stay hungry."},
            {"role": "user", "content": "Give me another quote."},
        ],
        "heartbeat_context": [],
        "target_tool_trace": [
            {"name": "generate_random_quote", "arguments": {}, "result": {"quote": "Stay foolish."}},
        ],
        "asr": {"transcript": "Give me another quote."},
    }

    sample, info = build_response_with_reference_sample(
        row,
        trace,
        response_with_reference_client=PassthroughResponseWithReferenceClient(),
    )

    assert info["status"] == "ok"
    assert sample is not None
    assert sample["conversations"] == [
        {"from": "system", "value": "<SYSTEM>\n\n### Tool Call XML Format\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{\"name\": <function-name>, \"arguments\": <args-json-object>}\n</tool_call>"},
        {"from": "user", "value": "<audio>"},
        {"from": "assistant", "value": "Stay hungry."},
        {"from": "user", "value": "Give me another quote."},
        {
            "from": "assistant",
            "value": '<tool_call>\n{"name":"generate_random_quote","arguments":{}}\n</tool_call>',
        },
    ]
    assert all(message["value"] for message in sample["conversations"] if message["from"] == "assistant")
    assert not any(str(message["value"]).lstrip().startswith("<tool_result>") for message in sample["conversations"])


def test_legacy_history_toolcall_drop_removes_adjacent_idless_tool_result() -> None:
    runner = _load_replay_runner()

    class AlwaysDrop:
        def random(self) -> float:
            return 0.0

    messages = [
        {"role": "user", "content": "Get a quote."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_hist_1",
                    "type": "function",
                    "function": {"name": "generate_random_quote", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": '{"quote":"Stay hungry."}'},
        {"role": "assistant", "content": "Stay hungry."},
    ]

    dropped = runner._maybe_drop_history_toolcalls(messages, 1.0, AlwaysDrop())

    assert dropped == [
        {"role": "user", "content": "Get a quote."},
        {"role": "assistant", "content": "Stay hungry."},
    ]


def test_response_with_reference_uses_asr_visible_tool_payload_instead_of_rejecting() -> None:
    runner = _load_replay_runner()

    class FakeResponseWithReferenceClient:
        def build(self, **kwargs):
            assert kwargs["target_tool_trace"] == [
                {"name": "lookup_order", "arguments": {"order_id": "A1"}, "result": {"status": "shipped"}},
            ]
            return {
                "asr_equivalent": False,
                "reference_adjusted": True,
                "reason": "Final ASR changed the order id, so adjust to the ASR-visible request.",
                "heartbeat_coverage": [
                    {
                        "reference_tool": "lookup_order",
                        "heartbeat_tool": None,
                        "covered": False,
                        "decision": "not_covered",
                        "reason": "No heartbeat result is available.",
                    }
                ],
                "messages": [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_asr_1",
                                "type": "function",
                                "function": {
                                    "name": "lookup_order",
                                    "arguments": "{\"order_id\":\"B2\"}",
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_asr_1",
                        "name": "lookup_order",
                        "content": "{\"status\":\"processing\"}",
                    },
                    {"role": "assistant", "content": "Order B2 is processing."},
                ],
            }, {"response_with_reference_wall_latency_ms": 1, "model": "fake", "base_url": "fake"}

    row = {
        "current_user_text": "Check order A1.",
        "seed_conversations": [
            {"role": "user", "content": "Check order A1."},
            {"role": "assistant", "content": "Order A1 has shipped."},
        ],
        "current_user_index": 0,
        "target_assistant_index": 1,
        "current_audio_path": "turn0.wav",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup_order",
                    "parameters": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    },
                },
            }
        ],
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "response_input_messages": [
            {"role": "user", "content": "Check order A1."},
        ],
        "heartbeat_context": [],
        "session_state": {"subtasks": []},
        "target_tool_trace": [
            {"name": "lookup_order", "arguments": {"order_id": "A1"}, "result": {"status": "shipped"}},
        ],
        "asr": {"transcript": "Check order B2."},
    }

    sample, info = runner._build_response_with_reference_sample(
        row,
        trace,
        response_with_reference_client=FakeResponseWithReferenceClient(),
    )

    assert info["status"] == "ok"
    assert info["response_with_reference"]["status"] == "ok"
    assert info["response_with_reference"]["asr_equivalent"] is False
    assert info["response_with_reference"]["heartbeat_coverage"][0]["covered"] is False
    assert sample is not None
    assert sample["conversations"][1] == {
        "from": "assistant",
        "value": '<tool_call>\n{"name":"lookup_order","arguments":{"order_id":"B2"}}\n</tool_call>',
    }
    assert sample["conversations"][2] == {
        "from": "user",
        "value": '<tool_result>\n{"name":"lookup_order","result":{"status":"processing"}}\n</tool_result>',
    }
    assert sample["conversations"][3] == {"from": "assistant", "value": "Order B2 is processing."}


def test_trace_omits_null_completed_tool_result_from_heartbeat_context() -> None:
    runner = _load_replay_runner()
    records = [
        {
            "client_elapsed_ms": 100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_call",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
            },
        },
        {
            "client_elapsed_ms": 200,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_result",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
                "status": "completed",
                "result": None,
            },
        },
        {
            "client_elapsed_ms": 1000,
            "event": {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "check order A1",
            },
        },
    ]

    trace = runner._build_replay_trace({"target_tool_trace": []}, records, _args())

    tool = trace["heartbeat_context"][0]["tools"][0]
    assert tool["status"] == "completed"
    assert "result" not in tool


def test_trace_preserves_thinking_input_messages_outside_response_context() -> None:
    runner = _load_replay_runner()
    input_messages = [
        {"role": "system", "content": "heartbeat system"},
        {"role": "user", "content": "### Current Fragment\ncheck order A1"},
    ]
    raw_response = '{"action":"think","thinking":"用户想查订单","tools":[]}'
    records = [
        {
            "client_elapsed_ms": 100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "input_messages",
                "block_idx": 0,
                "current_fragment": "check order A1",
                "messages": input_messages,
                "trace_level": "replay",
            },
        },
        {
            "client_elapsed_ms": 120,
            "event": {
                "type": "heartbeat_thinking",
                "event": "response",
                "block_idx": 0,
                "text": raw_response,
            },
        },
        {
            "client_elapsed_ms": 130,
            "event": {
                "type": "heartbeat_thinking",
                "event": "thinking",
                "block_idx": 0,
                "thinking": "用户想查订单",
            },
        },
        {
            "client_elapsed_ms": 1000,
            "event": {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "check order A1",
            },
        },
    ]

    trace = runner._build_replay_trace({"target_tool_trace": []}, records, _args())
    thinking = trace["heartbeat_thinkings"][0]

    assert thinking["input_messages"] == input_messages
    assert thinking["raw_response"] == raw_response
    assert trace["heartbeat_context"][0] == {
        "block": 0,
        "action": "think",
        "tools": [],
        "thinking": "用户想查订单",
    }


def test_build_heartbeat_thinking_samples_from_saved_messages() -> None:
    runner = _load_replay_runner()
    trace = {
        "heartbeat_thinkings": [
            {
                "block": 0,
                "t_ms": 500,
                "status": "completed",
                "input_messages": [
                    {"role": "system", "content": "heartbeat system"},
                    {"role": "user", "content": "### Current Fragment\ncheck order A1"},
                ],
                "raw_response": '{"action":"think","thinking":"用户想查订单","tools":[]}',
            }
        ]
    }
    row = {
        "dataset_name": "ToolMind",
        "conversation_id": "conv_001",
        "turn_index": 1,
    }

    samples = runner._build_heartbeat_thinking_samples(row, trace)

    assert len(samples) == 1
    assert samples[0]["task"] == "heartbeat_thinking"
    assert samples[0]["conversations"] == [
        {"from": "system", "value": "heartbeat system"},
        {"from": "user", "value": "### Current Fragment\ncheck order A1"},
        {"from": "assistant", "value": '{"action":"think","thinking":"用户想查订单","tools":[]}'},
    ]
    assert "tools" not in samples[0]


def test_trace_with_missing_response_start_has_no_visible_heartbeat_context() -> None:
    runner = _load_replay_runner()
    records = [
        {
            "client_elapsed_ms": 100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_call",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
            },
        },
        {
            "client_elapsed_ms": 200,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_result",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
                "status": "completed",
                "result": "{\"status\":\"shipped\"}",
            },
        },
    ]
    row = {
        "target_tool_trace": [
            {"name": "lookup_order", "arguments": {"order_id": "A1"}, "result": {"status": "shipped"}},
        ]
    }

    trace = runner._build_replay_trace(row, records, _args())

    assert trace["response_event"]["response_start_ms"] is None
    assert trace["heartbeat_context"] == []
    assert trace["target_tool_trace"] == row["target_tool_trace"]
    assert "alignment" not in trace


def test_trace_keeps_first_response_input_messages_snapshot() -> None:
    runner = _load_replay_runner()
    records = [
        {
            "client_elapsed_ms": 1000,
            "event": {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "check Starbucks stock",
            },
        },
        {
            "client_elapsed_ms": 1001,
            "event": {
                "type": "response.input_messages",
                "response_start_ms": 1000,
                "messages": [
                    {"role": "system", "content": "response system"},
                    {
                        "role": "user",
                        "content": "<audio>\n\n### HeartbeatContext\n{}",
                    },
                ],
            },
        },
        {
            "client_elapsed_ms": 1500,
            "event": {
                "type": "response.input_messages",
                "response_start_ms": 1500,
                "messages": [
                    {"role": "system", "content": "response system"},
                    {"role": "user", "content": "<audio>"},
                    {"role": "assistant", "content": "<tool_call>{}</tool_call>"},
                    {"role": "tool", "content": "{}"},
                ],
            },
        },
    ]

    trace = runner._build_replay_trace({}, records, _args())

    assert trace["response_input_messages"] == [
        {"role": "system", "content": "response system"},
        {"role": "user", "content": "<audio>\n\n### HeartbeatContext\n{}"},
    ]
    assert trace["response_input_messages_ms"] == 1000


def test_response_sample_requires_response_with_reference_client() -> None:
    runner = _load_replay_runner()
    row = {
        "seed_conversations": [
            {"role": "user", "content": "Check order A1."},
            {"role": "assistant", "content": "Order A1 has shipped."},
        ],
        "current_user_index": 0,
        "target_assistant_index": 1,
        "current_audio_path": "turn0.wav",
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "heartbeat_context": [],
        "session_state": {"subtasks": []},
        "target_tool_trace": [],
        "asr": {"transcript": "Check order A1."},
    }

    sample, info = runner._build_response_with_reference_sample(row, trace)

    assert sample is None
    assert info["status"] == "missing_response_with_reference_client"


def test_tool_summary_distinguishes_error_results_from_effective_results() -> None:
    runner = _load_replay_runner()
    records = [
        {
            "client_elapsed_ms": 100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_call",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
            },
        },
        {
            "client_elapsed_ms": 200,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_result",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
                "status": "completed",
                "result": "Error executing tool 'lookup_order': LLM mock did not produce a result",
            },
        },
        {
            "client_elapsed_ms": 1000,
            "event": {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "check order A1",
            },
        },
    ]

    trace = runner._build_replay_trace({"target_tool_trace": []}, records, _args())

    assert trace["tool_summary"]["tool_attempt_count"] == 1
    assert trace["tool_summary"]["completed_tool_event_count"] == 1
    assert trace["tool_summary"]["tool_result_error_count"] == 1
    assert trace["tool_summary"]["visible_completed_tool_count"] == 1
    assert trace["tool_summary"]["effective_tool_result_count"] == 0
    assert trace["tool_summary"]["effective_visible_tool_result_count"] == 0


def test_tool_summary_counts_raw_tool_predictions_without_tool_call_events() -> None:
    runner = _load_replay_runner()
    records = [
        {
            "client_elapsed_ms": 100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "response",
                "block_idx": 0,
                "text": (
                    "{\"action\":\"think\",\"thinking\":\"用户想查订单\","
                    "\"tools\":[{\"name\":\"lookup_order\",\"arguments\":{\"order_id\":\"A1\"}}]}"
                ),
            },
        },
        {
            "client_elapsed_ms": 1000,
            "event": {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "check order A1",
            },
        },
        {
            "client_elapsed_ms": 1100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "response",
                "block_idx": 1,
                "text": (
                    "{\"action\":\"think\",\"thinking\":\"用户又想查订单\","
                    "\"tools\":[{\"name\":\"lookup_order\",\"arguments\":{\"order_id\":\"A1\"}}]}"
                ),
            },
        },
    ]

    trace = runner._build_replay_trace({"target_tool_trace": []}, records, _args())

    assert trace["tool_summary"]["raw_tool_prediction_count"] == 2
    assert trace["tool_summary"]["raw_tool_prediction_without_tool_call_count"] == 2
    assert trace["tool_summary"]["raw_tool_prediction_without_tool_call_before_response_count"] == 1
    assert trace["tool_summary"]["raw_tool_prediction_without_tool_call_after_response_count"] == 1
    assert trace["tool_summary"]["tool_attempt_count"] == 0


def test_tool_summary_counts_effective_results_and_target_references() -> None:
    runner = _load_replay_runner()
    records = [
        {
            "client_elapsed_ms": 100,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_call",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
            },
        },
        {
            "client_elapsed_ms": 200,
            "event": {
                "type": "heartbeat_thinking",
                "event": "tool_result",
                "block_idx": 0,
                "tool_name": "lookup_order",
                "tool_call_id": "hb_1",
                "arguments": {"order_id": "A1"},
                "status": "completed",
                "result": "{\"status\":\"shipped\"}",
            },
        },
        {
            "client_elapsed_ms": 1000,
            "event": {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "check order A1",
            },
        },
    ]
    row = {
        "target_tool_trace": [
            {"name": "lookup_order", "arguments": {"order_id": "A1"}, "result": {"status": "shipped"}},
        ]
    }

    trace = runner._build_replay_trace(row, records, _args())

    assert trace["tool_summary"]["effective_tool_result_count"] == 1
    assert trace["tool_summary"]["effective_visible_tool_result_count"] == 1
    assert trace["tool_summary"]["target_tool_reference_count"] == 1
    assert "alignment" not in trace
