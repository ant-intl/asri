from pathlib import Path
from queue import Queue
import json
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handlers.llm.chat import Chat
from handlers.llm.openai_api_language_model import OpenApiModelHandler
from handlers.llm.tool_call.tool_execution import ToolPolicy
from handlers.llm.tool_call.tool_registry import ToolRegistry
from handlers.heartbeat_interaction.history_formatter import build_sft_prompt
from handlers.heartbeat_interaction.history_formatter import parse_predict_output
from handlers.heartbeat_interaction.history_formatter import tools_markdown
from handlers.heartbeat_interaction.history_formatter import load_prompt_template
from handlers.heartbeat_interaction.history_formatter import load_heartbeat_response_prompt_template
from handlers.heartbeat_interaction.history_formatter import render_heartbeat_response_context
from handlers.heartbeat_interaction.history_formatter_text import build_sft_prompt_text
from handlers.heartbeat_interaction.prompt_templates import get_response_prompt_mapping
from handlers.heartbeat_interaction.prompt_templates import get_thinking_prompt_mapping
from handlers.heartbeat_interaction.heartbeat_cache import (
    HeartBeatCache,
    HeartBeatEntry,
    ToolResultItem,
)
from handlers.heartbeat_interaction.streaming_asr_handler import StreamingASRHeartbeatHandler
from handlers.heartbeat_interaction.handler import HeartbeatInteractionHandler


import pytest

# Skip tests that depend on internal EPOS tools when they are not available
try:
    from tools import epos_tools
    _has_epos = True
except ImportError:
    epos_tools = None
    _has_epos = False

skip_no_epos = pytest.mark.skipif(not _has_epos, reason="Internal epos_tools not available")


def test_parse_predict_output_accepts_async_thinking():
    parsed = parse_predict_output(
        '{"need_to_think":true,"thinking":"User may need setup help.","query_epos_order":"NO_QUERY","search_epos_knowledge":{"query":"BlueTap setup"}}'
    )

    assert parsed["need_to_think"] is True
    assert parsed["thinking"] == "User may need setup help."
    assert parsed["tool_calls"] == [
        {"name": "search_epos_knowledge", "arguments": {"query": "BlueTap setup"}}
    ]


def test_parse_predict_output_accepts_generic_tool_calls():
    parsed = parse_predict_output(
        '{"need_to_think":true,"thinking":"用户想改账户地址",'
        '"query_epos_order":"NO_QUERY","search_epos_knowledge":"NO_QUERY",'
        '"tool_calls":[{"name":"request_update_account_contact_address","arguments":'
        '{"phone":"13822772934","new_address":"Petaling Jaya SS2"}}]}'
    )

    assert parsed["need_to_think"] is True
    assert parsed["thinking"] == "用户想改账户地址"
    assert parsed["tool_calls"] == [
        {
            "name": "request_update_account_contact_address",
            "arguments": {
                "phone": "13822772934",
                "new_address": "Petaling Jaya SS2",
            },
        }
    ]


def test_tools_markdown_accepts_flat_runtime_tool_schema():
    rendered = tools_markdown([
        {
            "name": "recommend_get",
            "description": "Generate category recommendations.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }
    ])

    assert "### recommend_get" in rendered
    assert "Generate category recommendations." in rendered
    assert '"text"' in rendered


def test_omni_heartbeat_prompt_uses_runtime_tools_and_audio_only_user_input():
    template = load_prompt_template("asri-generic-chain-v1")
    prompt = build_sft_prompt(
        chat_messages=[
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "historical transcript should not leak"},
            {"role": "assistant", "content": "Sure."},
        ],
        block_idx=0,
        block_duration_ms=500,
        prompt_template=template,
        tool_context={
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search_products",
                        "description": "Search catalog.",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                }
            ],
            "extra_instructions": "Prefer concise spoken replies.",
        },
    )

    user_value = prompt["messages"][1]["content"]
    assert "search_products" in user_value
    assert "Prefer concise spoken replies." in user_value
    assert "[User]: <audio>" in user_value
    assert "Current" in user_value
    assert "<audio>" in user_value
    assert "historical transcript should not leak" not in user_value
    assert "<asr>" not in user_value


def test_parse_predict_output_accepts_canonical_heartbeat_schema():
    parsed = parse_predict_output(
        '{"action":"think","thinking":"用户确认来电手机",'
        '"tools":[{"name":"send_sms_verification","arguments":{"phone":"13822772934"}}]}'
    )

    assert parsed["action"] == "think"
    assert parsed["thinking"] == "用户确认来电手机"
    assert parsed["tools"] == [
        {"name": "send_sms_verification", "arguments": {"phone": "13822772934"}}
    ]
    assert parsed["need_to_think"] is True
    assert parsed["tool_calls"] == parsed["tools"]


def test_parse_predict_output_accepts_canonical_noop_schema():
    parsed = parse_predict_output('{"action":"noop"}')

    assert parsed["action"] == "noop"
    assert parsed["thinking"] == ""
    assert parsed["tools"] == []
    assert parsed["need_to_think"] is False


def test_dynamic_tools_allow_empty_required_values_in_heartbeat_actionable_check():
    registry = ToolRegistry()
    registry.install_dynamic_tools([
        {
            "type": "function",
            "function": {
                "name": "get_list_of_countries_registered",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "Secret": {"type": "string"},
                        "Token": {"type": "string"},
                        "E-mail": {"type": "string"},
                    },
                    "required": ["action", "Secret", "Token", "E-mail"],
                },
            },
        }
    ])
    arguments = {"action": "countries", "Secret": "", "Token": "", "E-mail": ""}

    streaming_handler = StreamingASRHeartbeatHandler.__new__(StreamingASRHeartbeatHandler)
    streaming_handler.tool_registry = registry
    legacy_handler = HeartbeatInteractionHandler.__new__(HeartbeatInteractionHandler)
    legacy_handler.tool_registry = registry

    assert streaming_handler._has_actionable_arguments("get_list_of_countries_registered", arguments) is True
    assert legacy_handler._has_actionable_arguments("get_list_of_countries_registered", arguments) is True


def test_static_tools_still_reject_empty_required_values_in_heartbeat_actionable_check():
    registry = ToolRegistry()
    registry.register(
        "static_lookup",
        lambda token: "ok",
        parameters={
            "type": "object",
            "properties": {"token": {"type": "string"}},
            "required": ["token"],
        },
    )
    handler = StreamingASRHeartbeatHandler.__new__(StreamingASRHeartbeatHandler)
    handler.tool_registry = registry

    assert handler._has_actionable_arguments("static_lookup", {"token": ""}) is False
    assert handler._has_actionable_arguments("static_lookup", {"token": "abc"}) is True


def test_streaming_asr_predict_stores_thinking_only_entry():
    cache = HeartBeatCache(max_entries=5)
    handler = StreamingASRHeartbeatHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": Chat(1),
            "heartbeat_cache": cache,
            "tool_registry": None,
            "blocking": True,
            "prompt_version": "asri-v0",
        },
    )

    handler._call_predict_model = lambda _history, _text, _block_idx, **_kwargs: (
        '{"thinking":"The request is still incomplete; wait for more speech.",'
        '"query_epos_order":"NO_QUERY","search_epos_knowledge":"NO_QUERY"}'
    )

    assert list(handler.process(("how do I", 0))) == []

    entries = cache.consume_all()
    assert len(entries) == 1
    assert entries[0].order_key == 0
    assert entries[0].thinking == "The request is still incomplete; wait for more speech."
    assert entries[0].items == []


def test_streaming_asr_predict_stores_noop_entry():
    cache = HeartBeatCache(max_entries=5)
    handler = StreamingASRHeartbeatHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": Chat(1),
            "heartbeat_cache": cache,
            "tool_registry": None,
            "blocking": True,
            "prompt_version": "asri-v0",
        },
    )

    handler._call_predict_model = lambda _history, _text, _block_idx, **_kwargs: (
        '{"need_to_think":false,"thinking":"",'
        '"query_epos_order":"NO_QUERY","search_epos_knowledge":"NO_QUERY"}'
    )

    assert list(handler.process(("and then", 1))) == []

    entries = cache.snapshot_for_thinker()
    assert len(entries) == 1
    assert entries[0].order_key == 1
    assert entries[0].action == "noop"
    assert entries[0].need_to_think is False
    assert entries[0].thinking == ""
    assert entries[0].items == []


def test_streaming_asr_generic_write_tool_is_blocked_by_harness():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "request_update_account_contact_address",
        lambda phone, new_address: calls.append((phone, new_address)) or "submitted",
        policy=ToolPolicy.write(idempotency_fields=("phone", "new_address")),
    )
    cache = HeartBeatCache(max_entries=5)
    handler = StreamingASRHeartbeatHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": Chat(1),
            "heartbeat_cache": cache,
            "tool_registry": registry,
            "blocking": True,
            "prompt_version": "asri-v0",
        },
    )

    parsed = parse_predict_output(
        '{"need_to_think":true,"thinking":"用户要求改账户地址",'
        '"query_epos_order":"NO_QUERY","search_epos_knowledge":"NO_QUERY",'
        '"tool_calls":[{"name":"request_update_account_contact_address","arguments":'
        '{"phone":"13822772934","new_address":"Petaling Jaya SS2"}}]}'
    )

    assert handler._handle_dual_tool_prediction(parsed, block_idx=2) is True
    entries = cache.snapshot_for_thinker()
    assert len(entries) == 1
    assert entries[0].thinking == "用户要求改账户地址"
    assert len(entries[0].items) == 1
    item = entries[0].items[0]
    assert item.tool_name == "request_update_account_contact_address"
    assert item.arguments["phone"] == "13822772934"
    assert item.status == "completed"

    result = json.loads(item.result)
    assert result["status"] == "blocked"
    assert result["state"] == "BLOCKED_BY_PERMISSION"
    assert "permission_level" not in result
    assert result["transition"] == ["PROPOSED", "BLOCKED_BY_PERMISSION"]
    assert result["executed"] is False
    assert result["tool_name"] == "request_update_account_contact_address"
    assert result["source"] == "heartbeat_thinking"
    assert calls == []


def test_streaming_asr_verification_code_can_execute_from_thinker():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "send_sms_verification",
        lambda phone: calls.append(phone) or "sent",
        policy=ToolPolicy.write(
            allowed_sources=("main_llm", "heartbeat_thinking"),
            idempotency_fields=("phone",),
        ),
    )
    cache = HeartBeatCache(max_entries=5)
    handler = StreamingASRHeartbeatHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": Chat(1),
            "heartbeat_cache": cache,
            "tool_registry": registry,
            "blocking": True,
            "prompt_version": "asri-v0",
        },
    )

    parsed = parse_predict_output(
        '{"need_to_think":true,"thinking":"用户确认来电手机",'
        '"query_epos_order":"NO_QUERY","search_epos_knowledge":"NO_QUERY",'
        '"tool_calls":[{"name":"send_sms_verification","arguments":'
        '{"phone":"13822772934"}}]}'
    )

    assert handler._handle_dual_tool_prediction(parsed, block_idx=2) is True
    entries = cache.snapshot_for_thinker()
    assert len(entries) == 1
    item = entries[0].items[0]
    assert item.tool_name == "send_sms_verification"
    assert item.status == "completed"

    result = json.loads(item.result)
    assert result["status"] == "completed"
    assert result["state"] == "COMPLETED"
    assert result["executed"] is True
    assert result["source"] == "heartbeat_thinking"
    assert calls == ["13822772934"]


def test_streaming_asr_duplicate_tool_calls_go_through_harness():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "send_sms_verification",
        lambda phone: calls.append(phone) or "sent",
        policy=ToolPolicy.write(
            allowed_sources=("main_llm", "heartbeat_thinking"),
            idempotency_fields=("phone",),
        ),
    )
    cache = HeartBeatCache(max_entries=5)
    handler = StreamingASRHeartbeatHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": Chat(1),
            "heartbeat_cache": cache,
            "tool_registry": registry,
            "blocking": True,
            "prompt_version": "asri-v0",
        },
    )

    parsed = parse_predict_output(
        '{"need_to_think":true,"thinking":"尝试发验证码",'
        '"query_epos_order":"NO_QUERY","search_epos_knowledge":"NO_QUERY",'
        '"tool_calls":[{"name":"send_sms_verification","arguments":'
        '{"phone":"13822772934"}}]}'
    )

    assert handler._handle_dual_tool_prediction(parsed, block_idx=2) is True
    assert handler._handle_dual_tool_prediction(parsed, block_idx=3) is True
    entries = cache.snapshot_for_thinker()
    assert len(entries) == 2
    first = json.loads(entries[0].items[0].result)
    second = json.loads(entries[1].items[0].result)
    assert first["state"] == "COMPLETED"
    assert second["state"] == "DEDUPED_COMPLETED"
    assert calls == ["13822772934"]


def test_heartbeat_thinking_prompt_includes_previous_same_turn_context():
    entry = HeartBeatEntry(
        order_key=0,
        thinking="The user asked about BlueTap setup.",
        trigger_ts_ms=1000,
        elapsed_ms=0,
        items=[
            ToolResultItem(
                tool_name="search_epos_knowledge",
                tool_call_id="heartbeat_1",
                arguments={"query": "BlueTap setup"},
                result="Setup result",
                status="completed",
            )
        ],
    )

    prompt = build_sft_prompt_text(
        chat_messages=[{"role": "user", "content": "previous turn"}],
        current_text="How do I set it up and connect",
        block_idx=3,
        prompt_template=load_prompt_template("asri-v0"),
        async_context_entries=[entry],
    )

    content = prompt["messages"][1]["content"]
    assert "### Conversation History" in content
    assert "### Current Turn State" in content
    assert "### Current Fragment" in content
    assert "The user asked about BlueTap setup." in content
    assert '"trigger_ts_ms"' not in content
    assert '"created_at_ms"' not in content
    assert '"name": "search_epos_knowledge"' in content
    assert "BlueTap setup" in content
    assert "Setup result" in content


def test_heartbeat_thinking_prompt_excludes_server_execution_context():
    prompt = build_sft_prompt_text(
        chat_messages=[],
        current_text="My code is 8899",
        block_idx=1,
        prompt_template=load_prompt_template("asri-v0"),
        tool_context={
            "session_id": "session_demo",
            "user_id": "anonymous_user",
        },
    )

    content = prompt["messages"][1]["content"]
    assert "Tool execution context:" not in content
    assert "session_id: session_demo" not in content
    assert "user_id: anonymous_user" not in content
    assert "Use these exact values for tool arguments named session_id and user_id" not in content


@skip_no_epos
def test_streaming_asr_summary_tool_receives_main_llm_context(monkeypatch):
    epos_tools.reset_verification_state()
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Resp", (), {
                "choices": [
                    type("Choice", (), {
                        "message": type("Msg", (), {"content": "本次通话已完成账户查询，并将摘要发送给客户。"})()
                    })()
                ]
            })()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = type("ChatAPI", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(epos_tools, "OpenAI", FakeOpenAI)

    registry = ToolRegistry(context_provider=lambda: {
        "session_id": "session_async_summary",
        "user_id": "anonymous_user",
    })
    epos_tools.register_tools(registry)
    chat = Chat(3)
    chat.append({"role": "user", "content": "查一下账户余额。"})
    chat.append({"role": "assistant", "content": "查到了，人民币余额85000元。"})
    handler = StreamingASRHeartbeatHandler(
        threading.Event(),
        Queue(),
        Queue(),
        setup_kwargs={
            "chat_ref": chat,
            "heartbeat_cache": HeartBeatCache(max_entries=5),
            "tool_registry": registry,
            "blocking": True,
            "prompt_version": "asri-v0",
            "tool_llm_model_name": "main-summary-model",
            "tool_llm_base_url": "https://summary.example/v1",
            "tool_llm_api_key": "summary-key",
        },
    )

    raw = handler._execute_tool(
        "generate_call_summary",
        {"call_id": "current_session"},
        block_idx=1,
        current_text="好的谢谢，我没什么事了。",
    )
    outer = json.loads(raw)
    result = json.loads(outer["result"])
    assert result["source"] == "llm"
    assert result["summary"] == "本次通话已完成账户查询，并将摘要发送给客户。"
    assert captured["model"] == "main-summary-model"
    assert captured["api_key"] == "summary-key"
    assert captured["base_url"] == "https://summary.example/v1"
    user_prompt = captured["messages"][1]["content"]
    assert "查一下账户余额" in user_prompt
    assert "好的谢谢" in user_prompt


def test_asri_v0_prompt_treats_waiting_as_no_think_and_caps_thinking_length():
    template = load_prompt_template("asri-v0")
    prompt_text = "\n".join([
        template.decision_policy,
        template.output_format,
        template.examples,
    ])

    assert "If the only useful note is to wait for more speech, return" in prompt_text
    assert '"action":"noop"' in prompt_text
    assert "30 Chinese characters" in prompt_text


def test_asri_v0_prompt_defines_context_usage_and_relation_states():
    template = load_prompt_template("asri-v0")
    prompt_text = "\n".join([
        template.task,
        template.business_background,
        template.decision_policy,
        template.history_usage,
        template.examples,
    ])

    assert "Conversation History" in prompt_text
    assert "Current Turn State" in prompt_text
    assert "Current Fragment" in prompt_text
    for relation in ["new", "refined", "repeated", "superseded", "unstable"]:
        assert relation in prompt_text
    assert "Do not add tool business rules" in prompt_text
    assert "Do not infer ASR stability from earlier raw fragments" in prompt_text
    assert "argument values from surrounding labels" in prompt_text
    assert "matching semantic role" in prompt_text
    assert "scope the correction" in prompt_text
    assert "Current fragment ends before a required value is complete" in template.examples
    assert "Semantic role mismatch" in template.examples
    assert "confirmation_number" in template.examples
    assert "Correction scope" in template.examples
    assert "Current fragment repeats an already covered concern" in template.examples


def test_current_prompt_versions_are_defined_in_python_templates():
    thinking = get_thinking_prompt_mapping("asri-v0")
    response = get_response_prompt_mapping("heartbeat-response-v0")

    assert thinking is not None
    assert thinking["system"] == load_prompt_template("asri-v0").system
    assert "Argument boundary unclear" in thinking["examples"]
    assert response is not None
    assert response["header"] == load_heartbeat_response_prompt_template().header
    assert "Full input corrects or replaces" in response["examples"]


def test_heartbeat_response_context_uses_prompt_template():
    template = load_heartbeat_response_prompt_template()
    rendered = render_heartbeat_response_context(
        {"thinking_entries": [], "subtasks": []},
        template,
    )

    assert "### HeartbeatContext" in rendered
    assert "[HeartbeatContext usage]" in rendered
    assert "[HeartbeatContext examples]" in rendered
    assert "Full user input has priority" in rendered
    assert "Full input corrects or replaces" in rendered
    assert "pending or error tool states" in rendered


def test_thinking_prompt_appends_extra_instructions_before_fixed_context():
    prompt = build_sft_prompt_text(
        chat_messages=[],
        current_text="I need help",
        block_idx=0,
        prompt_template=load_prompt_template(),
        extra_instructions="Follow the sample policy.",
    )
    content = prompt["messages"][1]["content"]

    assert "[Extra Instructions]\nFollow the sample policy." in content
    history_idx = content.rindex("### Conversation History")
    turn_state_idx = content.rindex("### Current Turn State")
    fragment_idx = content.rindex("### Current Fragment")
    assert content.index("[Extra Instructions]") < history_idx
    assert history_idx < turn_state_idx
    assert turn_state_idx < fragment_idx


def test_response_system_appends_extra_instructions_without_replacing_default():
    base_system = "Default response policy."
    block = OpenApiModelHandler._extra_instructions_system_block("Use the sample policy.")
    rendered = base_system + OpenApiModelHandler._tools_schema_system_block([]) + block

    assert block.startswith("\n\n### Instruction Prompts for current conversation")
    assert "Use the sample policy." in block
    assert "### Tool Schemas" not in block
    assert rendered.startswith(base_system)
    assert rendered.index(base_system) < rendered.index("### Instruction Prompts")


def test_heartbeat_cache_snapshot_is_non_consuming_and_updates_tool_result():
    cache = HeartBeatCache(max_entries=5)
    cache.store(HeartBeatEntry(
        order_key=0,
        thinking="Need knowledge lookup.",
        items=[
            ToolResultItem(
                tool_name="search_epos_knowledge",
                tool_call_id="heartbeat_1",
                arguments={"query": "BlueTap setup"},
                result="",
                status="pending",
            )
        ],
    ))

    snapshot = cache.snapshot_for_thinker()
    assert snapshot[0].items[0].status == "pending"

    assert cache.update_tool_result("heartbeat_1", "Setup result") is True
    snapshot = cache.snapshot_for_thinker()
    assert snapshot[0].items[0].status == "completed"
    assert snapshot[0].items[0].result == "Setup result"

    consumed = cache.consume_all()
    assert len(consumed) == 1


def test_heartbeat_cache_replay_snapshot_uses_virtual_time_visibility():
    cache = HeartBeatCache(max_entries=5)
    cache.store(HeartBeatEntry(
        order_key=0,
        thinking="Need knowledge lookup.",
        created_at_ms=500,
        llm_completed_at_ms=900,
        items=[
            ToolResultItem(
                tool_name="search_epos_knowledge",
                tool_call_id="heartbeat_virtual",
                arguments={"query": "BlueTap setup"},
                result="Setup result",
                status="completed",
                dispatched_at_ms=500,
                completed_at_ms=1100,
                simulated_latency_ms=600,
            )
        ],
    ))

    assert cache.snapshot_for_thinker(snapshot_at_ms=800) == []

    pending_snapshot = cache.snapshot_for_thinker(snapshot_at_ms=1000)
    assert len(pending_snapshot) == 1
    assert pending_snapshot[0].items[0].status == "pending"
    assert pending_snapshot[0].items[0].result == ""

    completed_snapshot = cache.snapshot_for_thinker(snapshot_at_ms=1200)
    assert completed_snapshot[0].items[0].status == "completed"
    assert completed_snapshot[0].items[0].result == "Setup result"


def test_replay_response_waits_for_pending_heartbeat_tool_result(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_REPLAY_PENDING_TOOL_WAIT_TIMEOUT_S", "1")
    handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
    handler.chat = Chat(3)
    handler.user_role = "user"
    handler.runtime_config = type("RuntimeConfigStub", (), {"trace_level": "replay"})()
    handler.heartbeat_cache = HeartBeatCache(max_entries=5)
    handler._heartbeat_snapshot = []
    handler._heartbeat_history_rewrite = None
    handler.text_output_queue = None
    handler.chat.append({"role": "user", "content": "final user transcript"})
    handler.heartbeat_cache.store(HeartBeatEntry(
        order_key=1,
        thinking="Need stock lookup.",
        items=[
            ToolResultItem(
                tool_name="get_stock_price",
                tool_call_id="heartbeat_wait",
                arguments={"ticker": "SBUX"},
                result="",
                status="pending",
            )
        ],
    ))

    def finish_tool() -> None:
        time.sleep(0.05)
        handler.heartbeat_cache.update_tool_result(
            "heartbeat_wait",
            '{"price": 92.4}',
            status="completed",
        )

    thread = threading.Thread(target=finish_tool)
    thread.start()
    handler._inject_heartbeat_context()
    thread.join(timeout=1)

    content = handler.chat.buffer[0]["content"]
    assert '"status": "completed"' in content
    assert '"result": "{\\"price\\": 92.4}"' in content
    assert '"status": "pending"' not in content


def test_replay_response_virtual_time_keeps_late_tool_pending(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_REPLAY_PENDING_TOOL_WAIT_TIMEOUT_S", "1")
    handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
    handler.chat = Chat(3)
    handler.user_role = "user"
    handler.runtime_config = type("RuntimeConfigStub", (), {"trace_level": "replay"})()
    handler.heartbeat_cache = HeartBeatCache(max_entries=5)
    handler.heartbeat_cache.set_response_snapshot_at_ms(1000)
    handler._heartbeat_snapshot = []
    handler._heartbeat_history_rewrite = None
    handler.text_output_queue = None
    handler.chat.append({"role": "user", "content": "final user transcript"})
    handler.heartbeat_cache.store(HeartBeatEntry(
        order_key=1,
        thinking="Need stock lookup.",
        created_at_ms=500,
        llm_completed_at_ms=700,
        items=[
            ToolResultItem(
                tool_name="get_stock_price",
                tool_call_id="heartbeat_late_virtual",
                arguments={"ticker": "SBUX"},
                result='{"price": 92.4}',
                status="completed",
                dispatched_at_ms=500,
                completed_at_ms=1200,
                simulated_latency_ms=700,
            )
        ],
    ))

    handler._inject_heartbeat_context()

    content = handler.chat.buffer[0]["content"]
    assert '"status": "pending"' in content
    assert '"result":' not in content


def test_non_replay_response_does_not_wait_for_pending_heartbeat_tool_result():
    handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
    handler.chat = Chat(3)
    handler.user_role = "user"
    handler.runtime_config = type("RuntimeConfigStub", (), {"trace_level": "infer"})()
    handler.heartbeat_cache = HeartBeatCache(max_entries=5)
    handler._heartbeat_snapshot = []
    handler._heartbeat_history_rewrite = None
    handler.text_output_queue = None
    handler.chat.append({"role": "user", "content": "final user transcript"})
    handler.heartbeat_cache.store(HeartBeatEntry(
        order_key=1,
        thinking="Need stock lookup.",
        items=[
            ToolResultItem(
                tool_name="get_stock_price",
                tool_call_id="heartbeat_no_wait",
                arguments={"ticker": "SBUX"},
                result="",
                status="pending",
            )
        ],
    ))

    handler._inject_heartbeat_context()

    content = handler.chat.buffer[0]["content"]
    assert '"status": "pending"' in content
    assert '"status": "completed"' not in content


def test_openai_handler_injects_all_heartbeat_thinking_entries():
    handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
    handler.chat = Chat(3)
    handler.user_role = "user"
    handler.heartbeat_cache = HeartBeatCache(max_entries=5)
    handler._heartbeat_snapshot = []
    handler.chat.append({"role": "user", "content": "final user transcript"})

    handler.heartbeat_cache.store(HeartBeatEntry(
        order_key=0,
        thinking="The user is starting a BlueTap support question.",
        trigger_ts_ms=1000,
        elapsed_ms=0,
    ))
    handler.heartbeat_cache.store(HeartBeatEntry(
        order_key=1,
        thinking="The user is asking about Wi-Fi setup.",
        trigger_ts_ms=1500,
        elapsed_ms=500,
        items=[
            ToolResultItem(
                tool_name="search_epos_knowledge",
                tool_call_id="heartbeat_1",
                arguments={
                    "query": "BlueTap Wi-Fi setup",
                    "session_id": "session_demo",
                    "user_id": "anonymous_user",
                },
                result='{"answer":"Connect BlueTap to Wi-Fi from Settings.","source":"cache","session_id":"session_demo","user_id":"anonymous_user"}',
                status="completed",
            )
        ],
    ))

    handler._inject_heartbeat_context()

    content = handler.chat.buffer[0]["content"]
    assert "### HeartbeatContext" in content
    assert '"thinking_entries"' in content
    assert "The user is starting a BlueTap support question." in content
    assert "The user is asking about Wi-Fi setup." in content
    assert '"tools"' in content
    assert '"status": "completed"' in content
    assert '"result_state"' not in content
    assert "Connect BlueTap to Wi-Fi from Settings." in content
    assert len(handler.chat.buffer) == 1
    assert '"source"' not in content
    assert "session_demo" not in content
    assert "anonymous_user" not in content
    assert handler._heartbeat_snapshot[0]["tool_name"] == "search_epos_knowledge"
    assert "session_id" not in handler._heartbeat_snapshot[0]["arguments"]
    assert "user_id" not in handler._heartbeat_snapshot[0]["arguments"]
    assert "session_demo" not in handler._heartbeat_snapshot[0]["result_preview"]
    assert "anonymous_user" not in handler._heartbeat_snapshot[0]["result_preview"]

    handler._finalize_heartbeat_history()

    history_content = handler.chat.buffer[0]["content"]
    assert "The user is starting a BlueTap support question." not in history_content
    assert "The user is asking about Wi-Fi setup." not in history_content
    assert "### HeartbeatContext" not in history_content
    assert len(handler.chat.buffer) == 1
    assert "Connect BlueTap to Wi-Fi from Settings." not in history_content


def test_openai_handler_keeps_blocked_async_tools_as_context_only():
    handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
    handler.chat = Chat(3)
    handler.user_role = "user"
    handler.heartbeat_cache = HeartBeatCache(max_entries=5)
    handler._heartbeat_snapshot = []
    handler.chat.append({"role": "user", "content": "final user transcript"})

    blocked_result = json.dumps(
        {
            "state": "BLOCKED_BY_PERMISSION",
            "status": "blocked",
            "executed": False,
            "tool_name": "request_update_bound_phone",
            "source": "heartbeat_thinking",
            "allowed_sources": ["main_llm"],
            "retry_with_allowed_source": True,
        },
        ensure_ascii=False,
    )
    handler.heartbeat_cache.store(HeartBeatEntry(
        order_key=2,
        thinking="User wants to update bound phone.",
        items=[
            ToolResultItem(
                tool_name="request_update_bound_phone",
                tool_call_id="heartbeat_blocked",
                arguments={"current_phone": "13822772934", "new_phone": "13900001111"},
                result=blocked_result,
                status="completed",
            )
        ],
    ))

    handler._inject_heartbeat_context()

    content = handler.chat.buffer[0]["content"]
    assert "request_update_bound_phone" in content
    assert "BLOCKED_BY_PERMISSION" in content
    assert "was not executed" in content
    assert len(handler.chat.buffer) == 1
