import json

from handlers.llm.tool_call.tool_execution import (
    IdempotencyKeyBuilder,
    InMemoryExecutionStore,
    ToolExecutionHarness,
    ToolPolicy,
)
from handlers.llm.tool_call.tool_registry import ToolRegistry


def test_read_tool_returns_raw_result():
    registry = ToolRegistry()
    registry.register("lookup", lambda q: f"found:{q}")

    result = registry.execute("lookup", json.dumps({"q": "order"}), source="heartbeat_thinking")

    assert result == "found:order"


def test_dynamic_tool_can_use_llm_mock_executor(monkeypatch):
    calls = []

    def fake_generate(self, **kwargs):
        calls.append(kwargs)
        return {"status": "ok", "content": kwargs["arguments"]["q"]}, {"mock_wall_latency_ms": 7}

    monkeypatch.setenv("HEARTBEAT_DYNAMIC_TOOL_EXECUTOR", "llm_mock")
    monkeypatch.setenv("HEARTBEAT_TOOL_MOCK_BASE_URL", "https://mock.example.com")
    monkeypatch.setattr(
        "distillation_replay.mock_tool.ToolMockLLMClient.generate",
        fake_generate,
    )
    registry = ToolRegistry()
    registry.install_dynamic_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Lookup record",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                },
            },
        ],
        tool_mock_examples={
            "lookup": [
                {
                    "arguments": {"q": "example"},
                    "result": {"status": "ok", "content": "example result"},
                }
            ]
        },
    )

    first = registry.execute("lookup", json.dumps({"q": "order"}), context={"session_id": "conv-1"})
    second = registry.execute("lookup", json.dumps({"q": "order"}), context={"session_id": "conv-1"})

    assert json.loads(first) == {"status": "ok", "content": "order"}
    assert json.loads(second) == {"status": "ok", "content": "order"}
    assert len(calls) == 1
    assert calls[0]["conversation_prior_mock_results"] == []


def test_dynamic_tool_llm_mock_runs_without_examples(monkeypatch):
    calls = []

    def fake_generate(self, **kwargs):
        calls.append(kwargs)
        return {"status": "ok", "content": kwargs["tool_name"]}, {"mock_wall_latency_ms": 7}

    monkeypatch.setenv("HEARTBEAT_DYNAMIC_TOOL_EXECUTOR", "llm_mock")
    monkeypatch.setenv("HEARTBEAT_TOOL_MOCK_BASE_URL", "https://mock.example.com")
    monkeypatch.setattr(
        "distillation_replay.mock_tool.ToolMockLLMClient.generate",
        fake_generate,
    )
    registry = ToolRegistry()
    registry.install_dynamic_tools([
        {
            "type": "function",
            "function": {
                "name": "lookup_without_examples",
                "description": "Lookup record",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            },
        }
    ])

    result = registry.execute("lookup_without_examples", json.dumps({"q": "order"}), context={"session_id": "conv-1"})

    assert json.loads(result) == {"status": "ok", "content": "lookup_without_examples"}
    assert len(calls) == 1
    assert calls[0]["tool_examples"] == []


def test_dynamic_tool_registration_is_queryable():
    registry = ToolRegistry()
    registry.register("static_lookup", lambda q: "ok")
    registry.install_dynamic_tools([
        {
            "type": "function",
            "function": {
                "name": "dynamic_lookup",
                "description": "Dynamic lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"token": {"type": "string"}},
                    "required": ["token"],
                },
            },
        }
    ])

    assert registry.is_dynamic("dynamic_lookup") is True
    assert registry.is_dynamic("static_lookup") is False
    assert registry.is_dynamic("missing") is False


def test_read_tool_business_precondition_returns_state_result():
    registry = ToolRegistry()
    registry.register(
        "query_sensitive_data",
        lambda: json.dumps({
            "status": "identity_verification_required",
            "required_tools": ["send_sms_verification", "verify_sms_code"],
        }),
    )

    result = registry.execute("query_sensitive_data", "{}", source="heartbeat_thinking")

    parsed = json.loads(result)
    assert parsed["status"] == "precondition_required"
    assert parsed["state"] == "PRECONDITION_REQUIRED"
    assert parsed["transition"] == ["PROPOSED", "RUNNING", "PRECONDITION_REQUIRED"]
    assert parsed["executed"] is False
    assert parsed["precondition"] == "identity_verification_required"
    assert parsed["tool_name"] == "query_sensitive_data"


def test_heartbeat_thinking_write_tool_is_blocked_without_executing():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "send_code",
        lambda phone: calls.append(phone) or "sent",
        policy=ToolPolicy.write(idempotency_fields=("phone",)),
    )

    result = registry.execute(
        "send_code",
        json.dumps({"phone": "13800000000"}),
        source="heartbeat_thinking",
        context={"turn_id": "turn_1"},
    )

    parsed = json.loads(result)
    assert parsed["status"] == "blocked"
    assert parsed["state"] == "BLOCKED_BY_PERMISSION"
    assert "permission_level" not in parsed
    assert parsed["transition"] == ["PROPOSED", "BLOCKED_BY_PERMISSION"]
    assert parsed["executed"] is False
    assert parsed["tool_name"] == "send_code"
    assert "not allowed" in parsed["blocked_reason"]
    assert calls == []


def test_main_write_tool_is_deduped_within_same_turn():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "send_code",
        lambda phone: calls.append(phone) or "sent",
        policy=ToolPolicy.write(idempotency_fields=("phone",)),
    )

    first = registry.execute(
        "send_code",
        json.dumps({"phone": "13800000000"}),
        source="main_llm",
        context={"turn_id": "turn_1"},
    )
    second = registry.execute(
        "send_code",
        json.dumps({"phone": "13800000000"}),
        source="main_llm",
        context={"turn_id": "turn_1"},
    )

    first_parsed = json.loads(first)
    second_parsed = json.loads(second)
    assert first_parsed["status"] == "completed"
    assert first_parsed["state"] == "COMPLETED"
    assert first_parsed["transition"] == ["PROPOSED", "RUNNING", "COMPLETED"]
    assert first_parsed["executed"] is True
    assert second_parsed["status"] == "deduped"
    assert second_parsed["state"] == "DEDUPED_COMPLETED"
    assert second_parsed["transition"] == ["PROPOSED", "DEDUPED_COMPLETED"]
    assert second_parsed["duplicate_state"] == "COMPLETED"
    assert second_parsed["executed"] is False
    assert second_parsed["result"] == "sent"
    assert calls == ["13800000000"]


def test_heartbeat_thinking_allowed_write_tool_is_deduped_within_same_turn():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "send_code",
        lambda phone: calls.append(phone) or "sent",
        policy=ToolPolicy.write(
            allowed_sources=("main_llm", "heartbeat_thinking"),
            idempotency_fields=("phone",),
        ),
    )

    first = registry.execute(
        "send_code",
        json.dumps({"phone": "13800138000"}),
        source="heartbeat_thinking",
        context={"turn_id": "turn_1"},
    )
    second = registry.execute(
        "send_code",
        json.dumps({"phone": "13800138000"}),
        source="heartbeat_thinking",
        context={"turn_id": "turn_1"},
    )

    first_parsed = json.loads(first)
    second_parsed = json.loads(second)
    assert first_parsed["status"] == "completed"
    assert first_parsed["state"] == "COMPLETED"
    assert "permission_level" not in first_parsed
    assert first_parsed["executed"] is True
    assert second_parsed["status"] == "deduped"
    assert second_parsed["state"] == "DEDUPED_COMPLETED"
    assert "permission_level" not in second_parsed
    assert second_parsed["executed"] is False
    assert second_parsed["result"] == "sent"
    assert calls == ["13800138000"]


def test_state_accumulated_auto_does_not_execute_from_heartbeat_thinking():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "prepare_followup",
        lambda target_id: calls.append(target_id) or "prepared",
        policy=ToolPolicy.state_accumulated_auto(idempotency_fields=("target_id",)),
    )

    result = registry.execute(
        "prepare_followup",
        json.dumps({"target_id": "PI123"}),
        source="heartbeat_thinking",
        context={"turn_id": "turn_1"},
    )

    parsed = json.loads(result)
    assert parsed["status"] == "accumulated"
    assert parsed["state"] == "ACCUMULATED"
    assert "permission_level" not in parsed
    assert parsed["executed"] is False
    assert parsed["pending_execution_stage"] == "turn_end"
    assert calls == []


def test_state_accumulated_auto_can_execute_after_turn_boundary():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "prepare_followup",
        lambda target_id: calls.append(target_id) or "prepared",
        policy=ToolPolicy.state_accumulated_auto(idempotency_fields=("target_id",)),
    )

    result = registry.execute(
        "prepare_followup",
        json.dumps({"target_id": "PI123"}),
        source="main_llm",
        context={"turn_id": "turn_1"},
    )

    parsed = json.loads(result)
    assert parsed["status"] == "completed"
    assert parsed["state"] == "COMPLETED"
    assert "permission_level" not in parsed
    assert parsed["executed"] is True
    assert calls == ["PI123"]


def test_running_duplicate_returns_explicit_deduped_running_state():
    store = InMemoryExecutionStore()
    harness = ToolExecutionHarness(store=store)
    policy = ToolPolicy.write(idempotency_fields=("phone",))
    context = {"turn_id": "turn_1"}
    arguments = {"phone": "13800000000"}
    idempotency_key = IdempotencyKeyBuilder.build(
        tool_name="send_code",
        arguments=arguments,
        policy=policy,
        context=context,
    )
    assert idempotency_key is not None
    running = store.create_running(
        idempotency_key=idempotency_key,
        tool_name="send_code",
        arguments=arguments,
        source="main_llm",
    )

    result = harness.execute(
        tool_name="send_code",
        arguments_json=json.dumps(arguments),
        policy=policy,
        raw_executor=lambda: "sent",
        source="main_llm",
        context=context,
    )

    parsed = json.loads(result)
    assert parsed["status"] == "deduped"
    assert parsed["state"] == "DEDUPED_RUNNING"
    assert parsed["transition"] == ["PROPOSED", "DEDUPED_RUNNING"]
    assert parsed["duplicate_state"] == "RUNNING"
    assert parsed["duplicate_status"] == "running"
    assert parsed["duplicate_of_execution_id"] == running.execution_id


def test_main_write_tool_can_execute_again_in_new_turn():
    calls = []
    registry = ToolRegistry()
    registry.register(
        "send_code",
        lambda phone: calls.append(phone) or f"sent:{len(calls)}",
        policy=ToolPolicy.write(idempotency_fields=("phone",)),
    )

    first = registry.execute(
        "send_code",
        json.dumps({"phone": "13800000000"}),
        source="main_llm",
        context={"turn_id": "turn_1"},
    )
    second = registry.execute(
        "send_code",
        json.dumps({"phone": "13800000000"}),
        source="main_llm",
        context={"turn_id": "turn_2"},
    )

    assert json.loads(first)["status"] == "completed"
    assert json.loads(second)["status"] == "completed"
    assert calls == ["13800000000", "13800000000"]


def test_business_precondition_failure_does_not_lock_same_turn_retry():
    verified = False
    calls = []

    def update_order(pi_number):
        calls.append(pi_number)
        if not verified:
            return json.dumps({
                "status": "identity_verification_required",
                "executed": False,
            })
        return "submitted"

    registry = ToolRegistry()
    registry.register(
        "update_order",
        update_order,
        policy=ToolPolicy.write(idempotency_fields=("pi_number",)),
    )

    first = registry.execute(
        "update_order",
        json.dumps({"pi_number": "4431"}),
        source="main_llm",
        context={"turn_id": "turn_1"},
    )
    verified = True
    second = registry.execute(
        "update_order",
        json.dumps({"pi_number": "4431"}),
        source="main_llm",
        context={"turn_id": "turn_1"},
    )

    first_parsed = json.loads(first)
    second_parsed = json.loads(second)
    assert first_parsed["status"] == "precondition_required"
    assert first_parsed["state"] == "PRECONDITION_REQUIRED"
    assert first_parsed["transition"] == ["PROPOSED", "RUNNING", "PRECONDITION_REQUIRED"]
    assert first_parsed["precondition"] == "identity_verification_required"
    assert first_parsed["executed"] is False
    assert second_parsed["status"] == "completed"
    assert second_parsed["state"] == "COMPLETED"
    assert second_parsed["result"] == "submitted"
    assert calls == ["4431", "4431"]


def test_tool_registry_injects_session_context_arguments():
    calls = []
    registry = ToolRegistry(
        context_provider=lambda: {
            "session_id": "session_demo",
            "user_id": "anonymous_user",
        }
    )
    registry.register(
        "send_code",
        lambda session_id, user_id, phone: calls.append((session_id, user_id, phone)) or "sent",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["session_id", "user_id", "phone"],
        },
        policy=ToolPolicy.write(
            allowed_sources=("main_llm", "heartbeat_thinking"),
            idempotency_fields=("session_id", "user_id", "phone"),
        ),
    )

    result = registry.execute(
        "send_code",
        json.dumps({"phone": "13800138000"}),
        source="heartbeat_thinking",
        context={"turn_id": "turn_1"},
    )

    parsed = json.loads(result)
    assert parsed["status"] == "completed"
    assert parsed["state"] == "COMPLETED"
    assert parsed["arguments"]["session_id"] == "session_demo"
    assert parsed["arguments"]["user_id"] == "anonymous_user"
    assert calls == [("session_demo", "anonymous_user", "13800138000")]

    schema = registry.tool_schemas_chat_api()[0]["function"]["parameters"]["properties"]
    assert "session_id" not in schema
    assert "user_id" not in schema
    assert "phone" in schema


def test_tool_registry_overrides_model_supplied_session_context():
    calls = []
    registry = ToolRegistry(
        context_provider=lambda: {
            "session_id": "session_runtime",
            "user_id": "anonymous_user",
        }
    )
    registry.register(
        "send_code",
        lambda session_id, user_id, phone: calls.append((session_id, user_id, phone)) or "sent",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["session_id", "user_id", "phone"],
        },
        policy=ToolPolicy.write(
            allowed_sources=("main_llm", "heartbeat_thinking"),
            idempotency_fields=("session_id", "user_id", "phone"),
        ),
    )

    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "send_code",
            "arguments": json.dumps({
                "session_id": "wrong_session",
                "user_id": "wrong_user",
                "phone": "13800138000",
            }),
        },
    }
    registry.augment_tool_call_dict(
        tool_call,
        context={"turn_id": "turn_1", "session_id": "wrong_context"},
    )

    augmented_args = json.loads(tool_call["function"]["arguments"])
    assert augmented_args["session_id"] == "session_runtime"
    assert augmented_args["user_id"] == "anonymous_user"

    result = registry.execute(
        "send_code",
        json.dumps({
            "session_id": "wrong_session",
            "user_id": "wrong_user",
            "phone": "13800138000",
        }),
        source="heartbeat_thinking",
        context={"turn_id": "turn_1", "user_id": "wrong_context_user"},
    )

    parsed = json.loads(result)
    assert parsed["status"] == "completed"
    assert parsed["state"] == "COMPLETED"
    assert parsed["arguments"]["session_id"] == "session_runtime"
    assert parsed["arguments"]["user_id"] == "anonymous_user"
    assert calls == [("session_runtime", "anonymous_user", "13800138000")]
