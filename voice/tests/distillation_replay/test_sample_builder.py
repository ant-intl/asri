import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from distillation_replay.sample_builder import (
    ResponseTurn,
    build_response_conversations,
    build_response_sample,
)
from client.replay.sft_sample_builder import build_response_with_reference_sample


def _heartbeat_payload(value: str) -> dict:
    start = value.index("### HeartbeatContext") + len("### HeartbeatContext")
    end = value.index("[HeartbeatContext usage]")
    return json.loads(value[start:end].strip())


def test_response_conversations_put_heartbeat_context_only_on_last_user_turn():
    conversations = build_response_conversations(
        system_prompt="<SYSTEM>",
        turns=[
            ResponseTurn(
                audio_ref="turn0_full.wav",
                assistant_response="turn0 answer",
                heartbeat_context=[],
            ),
            ResponseTurn(
                audio_ref="turn1_full.wav",
                assistant_response="turn1 answer",
                heartbeat_context=[
                    {
                        "block": 2,
                        "action": "think",
                        "thinking": "follow-up",
                        "tool_calls": [
                            {
                                "name": "lookup",
                                "arguments": {"order_id": "A1", "session_id": "hidden"},
                                "status": "completed",
                                "result": {"answer": "ok", "source": "debug"},
                            }
                        ],
                    }
                ],
                turn_state={"thinking_entries": [{"block": 2}]},
            ),
        ],
    )

    assert conversations[0] == {"from": "system", "value": "<SYSTEM>"}
    user_turns = [msg for msg in conversations if msg["from"] == "user"]
    assert len(user_turns) == 2
    assert user_turns[0]["value"] == "<audio>"
    assert "HeartbeatContext:" not in user_turns[0]["value"]
    assert user_turns[1]["value"].startswith("<audio>\n\n### HeartbeatContext")
    assert not user_turns[1]["value"].startswith("<audio>\n\n\n### HeartbeatContext")
    assert "### HeartbeatContext" in user_turns[1]["value"]
    assert "[HeartbeatContext usage]" in user_turns[1]["value"]
    assert "[HeartbeatContext examples]" in user_turns[1]["value"]
    assert "HeartbeatContext:" not in user_turns[1]["value"]
    assert "Task: heartbeat_response" not in user_turns[1]["value"]
    assert "TurnState:" not in user_turns[1]["value"]
    assert "SessionState:" not in user_turns[1]["value"]
    assert "follow-up" in user_turns[1]["value"]
    assert '"tools": [' in user_turns[1]["value"]
    assert '"tool_calls"' not in user_turns[1]["value"]
    assert '"source"' not in user_turns[1]["value"]
    assert '"session_id"' not in user_turns[1]["value"]
    assert "- [1200ms]" not in user_turns[1]["value"]
    assert '"created_at_ms"' not in user_turns[1]["value"]
    assert user_turns[1]["value"].index('"block"') < user_turns[1]["value"].index('"action"')
    assert user_turns[1]["value"].index('"action"') < user_turns[1]["value"].index('"tools"')
    assert user_turns[1]["value"].index('"tools"') < user_turns[1]["value"].index('"thinking"')
    payload = _heartbeat_payload(user_turns[1]["value"])
    tool = payload["thinking_entries"][0]["tools"][0]
    assert tool == {
        "name": "lookup",
        "arguments": {"order_id": "A1"},
        "status": "completed",
        "result": "{\"answer\": \"ok\"}",
    }


def test_response_sample_keeps_audio_paths_out_of_message_text():
    sample = build_response_sample(
        system_prompt="<SYSTEM>",
        turns=[
            ResponseTurn("turn0.wav", "a0"),
            ResponseTurn("turn1.wav", "a1"),
        ],
        tools=[{"type": "function", "function": {"name": "lookup"}}],
        meta={
            "conversation_id": "dlg1",
            "turn_index": 1,
            "audio_path": "turn1.wav",
            "trace": {"response_start_ms": 1000},
        },
    )

    assert "id" not in sample
    assert sample["task"] == "heartbeat_response"
    assert sample["tools"] == [{"type": "function", "function": {"name": "lookup"}}]
    assert sample["audios"] == ["turn0.wav", "turn1.wav"]
    for message in sample["conversations"]:
        if message["from"] == "user":
            assert "<audio>" in message["value"]
            assert "turn0.wav" not in message["value"]
            assert "turn1.wav" not in message["value"]
            assert "conversation_id" not in message["value"]
            assert "turn_index" not in message["value"]
            assert "audio_path" not in message["value"]
            assert "trace" not in message["value"]
    user_turns = [msg for msg in sample["conversations"] if msg["from"] == "user"]
    assert "### HeartbeatContext" not in user_turns[0]["value"]
    assert "### HeartbeatContext" in user_turns[-1]["value"]


def test_response_user_value_parses_json_string_heartbeat_context():
    conversations = build_response_conversations(
        system_prompt="<SYSTEM>",
        turns=[
            ResponseTurn(
                audio_ref="turn0_full.wav",
                assistant_response="turn0 answer",
                heartbeat_context='[{"block":2,"thinking":"parsed","tool_calls":[]}]',
            ),
        ],
    )

    value = conversations[1]["value"]
    assert "### HeartbeatContext" in value
    assert '"thinking": "parsed"' in value
    assert '"tool_calls"' not in value
    assert "'[{\\\"block\\\"" not in value


def test_response_sample_renders_historical_tool_calls_as_xml():
    class FakeResponseWithReferenceClient:
        def build(self, **kwargs):
            return {
                "asr_equivalent": True,
                "reference_adjusted": False,
                "reason": "ok",
                "heartbeat_coverage": [],
                "messages": [{"role": "assistant", "content": "Current answer."}],
            }, {"model": "fake", "base_url": "fake"}

    row = {
        "seed_conversations": [
            {"role": "user", "content": "History question."},
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
            {"role": "assistant", "content": "History answer."},
            {"role": "user", "content": "Current question."},
            {"role": "assistant", "content": "Current answer."},
        ],
        "current_user_index": 4,
        "target_assistant_index": 5,
        "history_audio_paths": ["turn0.wav"],
        "current_audio_path": "turn1.wav",
        "tools": [{"type": "function", "function": {"name": "lookup_order"}}],
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "response_input_messages": [
            {"role": "system", "content": "<SYSTEM>"},
            {"role": "user", "content": "History question."},
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
            {"role": "assistant", "content": "History answer."},
            {"role": "user", "content": "<audio>\n\n### HeartbeatContext\n{}"},
        ],
        "heartbeat_context": [],
        "target_tool_trace": [],
        "asr": {"transcript": "Current question."},
    }

    sample, info = build_response_with_reference_sample(
        row,
        trace,
        response_with_reference_client=FakeResponseWithReferenceClient(),
    )

    assert info["status"] == "ok"
    assert sample is not None
    assert sample["conversations"][1] == {"from": "user", "value": "<audio>"}
    assert sample["conversations"][2] == {
        "from": "assistant",
        "value": '<tool_call>\n{"name":"lookup_order","arguments":{"order_id":"H1"}}\n</tool_call>',
    }
    assert sample["conversations"][3] == {
        "from": "user",
        "value": '<tool_result>\n{"name":"lookup_order","result":{"status":"delivered"}}\n</tool_result>',
    }
    assert sample["conversations"][4] == {"from": "assistant", "value": "History answer."}
    assert sample["conversations"][5] == {"from": "user", "value": "<audio>\n\n### HeartbeatContext\n{}"}
    assert sample["conversations"][-1] == {"from": "assistant", "value": "Current answer."}
    assert all("tool_calls" not in message for message in sample["conversations"])
    assert all(message["from"] != "tool" for message in sample["conversations"])


def test_replay_response_sample_uses_runtime_current_user_value_verbatim():
    class FakeResponseWithReferenceClient:
        seen_tools = None

        def build(self, **kwargs):
            self.seen_tools = kwargs["tools"]
            return {
                "asr_equivalent": True,
                "reference_adjusted": False,
                "reason": "ok",
                "heartbeat_coverage": [],
                "messages": [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
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
                        "name": "lookup_order",
                        "content": "{\"status\":\"shipped\"}",
                    },
                    {"role": "assistant", "content": "Order A1 has shipped."},
                ],
            }, {"model": "fake", "base_url": "fake"}

    runtime_user_content = (
        "<audio>\n\n"
        "### HeartbeatContext\n"
        "{\n"
        '  "thinking_entries": [\n'
        '    {"block": 0, "action": "think", "tools": [], "thinking": "查订单"}\n'
        "  ],\n"
        '  "subtasks": []\n'
        "}\n\n"
        "[HeartbeatContext usage]\nUse this JSON only as temporary context.\n"
    )
    row = {
        "seed_conversations": [
            {"role": "user", "content": "Check order A1."},
            {"role": "assistant", "content": "Order A1 has shipped."},
        ],
        "current_user_index": 0,
        "target_assistant_index": 1,
        "current_audio_path": "turn0.wav",
        "tools": [{"type": "function", "function": {"name": "lookup_order"}}],
    }
    trace = {
        "response_event": {"response_start_ms": 1000},
        "response_input_messages": [
            {"role": "system", "content": "<SYSTEM>"},
            {"role": "user", "content": runtime_user_content},
        ],
        "heartbeat_context": [],
        "target_tool_trace": [],
        "asr": {"transcript": "Check order A1."},
    }

    client = FakeResponseWithReferenceClient()
    sample, info = build_response_with_reference_sample(
        row,
        trace,
        response_with_reference_client=client,
    )

    assert info["status"] == "ok"
    assert sample is not None
    assert client.seen_tools == row["tools"]
    assert sample["tools"] == row["tools"]
    assert "### Tool Call XML Format" in sample["conversations"][0]["value"]
    assert "For each function call" in sample["conversations"][0]["value"]
    user_value = sample["conversations"][1]["value"]
    assert user_value == runtime_user_content
    assert sample["conversations"][2] == {
        "from": "assistant",
        "value": '<tool_call>\n{"name":"lookup_order","arguments":{"order_id":"A1"}}\n</tool_call>',
    }
    assert sample["conversations"][3] == {
        "from": "user",
        "value": '<tool_result>\n{"name":"lookup_order","result":{"status":"shipped"}}\n</tool_result>',
    }
    assert sample["conversations"][-1] == {"from": "assistant", "value": "Order A1 has shipped."}
    assert all("tool_calls" not in msg for msg in sample["conversations"])
    assert all(msg["from"] != "tool" for msg in sample["conversations"])
