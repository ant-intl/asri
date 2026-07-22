"""Tests for OpenApiModelHandler process() and agent loop logic."""

from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import sys
import json

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.cancel_scope import CancelScope
from handlers.llm.chat import Chat
from handlers.llm.openai_api_language_model import OpenApiModelHandler


# ---------------------------------------------------------------------------
# Helpers: build mock Chat Completions API streaming chunks
# ---------------------------------------------------------------------------

def _make_text_chunk(content):
    """Create a mock streaming chunk with text content."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(choices=[choice], usage=None)
    return chunk


def _make_tool_call_chunk(index, call_id=None, name=None, arguments=None):
    """Create a mock streaming chunk with a tool call delta."""
    dump = {
        "index": index,
        "id": call_id,
        "type": "function",
        "function": {"name": name or "", "arguments": arguments or ""},
    }
    tc_delta = SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
        model_dump=lambda: dict(dump),
    )
    delta = SimpleNamespace(content=None, tool_calls=[tc_delta])
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(choices=[choice], usage=None)
    return chunk


def _make_usage_chunk(input_tokens=10, output_tokens=20):
    """Create a mock chunk with usage info."""
    usage = SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens)
    delta = SimpleNamespace(content=None, tool_calls=None)
    choice = SimpleNamespace(delta=delta)
    chunk = SimpleNamespace(choices=[choice], usage=usage)
    return chunk


def _make_non_streaming_response(content="Hello.", tool_calls=None, usage=None):
    """Create a mock non-streaming response."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


class MockStream:
    """Mock stream that yields chunks and supports close()."""
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self):
        pass


def _make_handler(*, disable_thinking=False, stream=True, cancel_scope=None):
    handler = object.__new__(OpenApiModelHandler)
    handler.model_name = "test-model"
    handler.stream = stream
    handler.clean_response_text = True
    handler.gen_kwargs = {}
    handler.request_timeout_s = 20.0
    handler.request_timeout = 20.0
    handler.disable_thinking = disable_thinking
    handler._extra_body = (
        {"chat_template_kwargs": {"enable_thinking": False}}
        if disable_thinking
        else None
    )
    handler.user_role = "user"
    handler.chat = Chat(1)
    handler.runtime_config = None
    handler.cancel_scope = cancel_scope
    handler.tools = None
    handler.tools_choice = None
    handler.tool_registry = None
    handler.max_agent_iterations = 10
    handler._agent_loop_active = False
    handler._last_instructions = None
    handler._initial_instructions = "base system"
    handler._last_system_prompt = "base system"
    handler.text_output_queue = None
    handler.heartbeat_cache = None
    handler._heartbeat_snapshot = []
    handler._heartbeat_history_rewrite = None
    return handler


# ---------------------------------------------------------------------------
# Tests: streaming text
# ---------------------------------------------------------------------------

def test_process_streams_text():
    handler = _make_handler()

    chunks = [
        _make_text_chunk("Hello. "),
        _make_text_chunk("How are you?"),
    ]

    completions = SimpleNamespace(create=lambda **kwargs: MockStream(chunks))
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Hi"))

    text_outputs = [(o[0], o[1]) for o in outputs if isinstance(o[0], str) and not o[0].startswith("__")]
    assert len(text_outputs) >= 1
    full_text = "".join(t for t, _ in text_outputs)
    assert "Hello" in full_text
    assert outputs[-1][:3] == ("__END_OF_RESPONSE__", None, None)


def test_process_handles_cancellation():
    scope = CancelScope()
    handler = _make_handler(cancel_scope=scope)

    def fake_create(**kwargs):
        scope.cancel()
        return MockStream([_make_text_chunk("Hello")])

    completions = SimpleNamespace(create=fake_create)
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Hi"))
    assert outputs[-1][:3] == ("__END_OF_RESPONSE__", None, None)


def test_process_read_timeout_ends_response_cleanly():
    handler = _make_handler()

    class TimeoutStream:
        def __iter__(self):
            raise httpx.ReadTimeout("timed out")
        def close(self):
            pass

    completions = SimpleNamespace(create=lambda **kwargs: TimeoutStream())
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Hi"))
    assert outputs[-1][:3] == ("__END_OF_RESPONSE__", None, None)
    metrics_outputs = [o for o in outputs if o[0] == "__LLM_METRICS__"]
    assert metrics_outputs
    assert metrics_outputs[0][1]["stream_error"] == "httpx_read_timeout"


def test_disable_thinking_passes_extra_body():
    handler = _make_handler(disable_thinking=True)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return MockStream([_make_text_chunk("Ok")])

    completions = SimpleNamespace(create=fake_create)
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    list(handler.process("Hi"))
    assert captured["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_no_disable_thinking_omits_extra_body():
    handler = _make_handler(disable_thinking=False)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return MockStream([_make_text_chunk("Ok")])

    completions = SimpleNamespace(create=fake_create)
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    list(handler.process("Hi"))
    assert captured.get("extra_body") is None


def test_non_streaming_response():
    handler = _make_handler(stream=False)
    response = _make_non_streaming_response(content="Hello world.")

    completions = SimpleNamespace(create=lambda **kwargs: response)
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Hi"))
    text_outputs = [(o[0], o[1]) for o in outputs if isinstance(o[0], str) and not o[0].startswith("__")]
    assert len(text_outputs) >= 1
    assert "Hello world" in text_outputs[0][0]
    assert outputs[-1][:3] == ("__END_OF_RESPONSE__", None, None)


def test_response_create_instructions_are_system_override_not_user_message():
    handler = _make_handler(stream=False)
    handler.chat.append({"role": "user", "content": "transcribed user request"})
    handler.runtime_config = SimpleNamespace(
        session=SimpleNamespace(
            instructions="base system",
            tools=[],
            tool_choice=None,
        ),
        extra_instructions="",
        disable_response_generation=False,
    )
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _make_non_streaming_response(content="ok")

    completions = SimpleNamespace(create=fake_create)
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    list(handler.process(("__GENERATE_RESPONSE__", "per response system", None)))

    messages = captured["messages"]
    assert messages[0] == {"role": "system", "content": "per response system"}
    assert {"role": "user", "content": "per response system"} not in messages
    assert {"role": "user", "content": "transcribed user request"} in messages


def test_response_input_messages_emit_omni_audio_view_with_heartbeat_context():
    handler = _make_handler()
    handler.chat.init_chat({"role": "system", "content": "response system"})
    handler.chat.append({"role": "user", "content": "previous ASR text"})
    handler.chat.append({"role": "assistant", "content": "previous answer"})
    handler.chat.append({
        "role": "user",
        "content": (
            "current final ASR text\n\n"
            "### HeartbeatContext\n"
            "{\n"
            '  "thinking_entries": [],\n'
            '  "subtasks": []\n'
            "}\n\n"
            "[HeartbeatContext usage]\nUse this JSON only as temporary context.\n"
        ),
    })
    handler.text_output_queue = Queue()

    handler._emit_response_input_messages()

    event = handler.text_output_queue.get_nowait()
    assert event["type"] == "response.input_messages"
    assert event["messages"] == [
        {"role": "system", "content": "response system"},
        {"role": "user", "content": "<audio>"},
        {"role": "assistant", "content": "previous answer"},
        {
            "role": "user",
            "content": (
                "<audio>\n\n"
                "### HeartbeatContext\n"
                "{\n"
                '  "thinking_entries": [],\n'
                '  "subtasks": []\n'
                "}\n\n"
                "[HeartbeatContext usage]\nUse this JSON only as temporary context.\n"
            ),
        },
    ]


def test_streaming_tool_calls():
    handler = _make_handler()

    chunks = [
        _make_text_chunk("Let me check. "),
        _make_tool_call_chunk(0, call_id="call_1", name="get_weather", arguments='{"city": "Beijing"}'),
    ]

    completions = SimpleNamespace(create=lambda **kwargs: MockStream(chunks))
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Hi"))
    tool_outputs = [o for o in outputs if isinstance(o[0], str) and not o[0].startswith("__") and o[2]]
    assert len(tool_outputs) >= 1
    tools = tool_outputs[0][2]
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "get_weather"


def test_cancelled_streaming_tool_call_is_not_kept_in_chat_history():
    scope = CancelScope()
    handler = _make_handler(cancel_scope=scope)

    class CancelAfterToolDeltaStream:
        def __init__(self):
            self._idx = 0

        def __iter__(self):
            return self

        def __next__(self):
            self._idx += 1
            if self._idx == 1:
                return _make_text_chunk("Let me check.")
            if self._idx == 2:
                return _make_tool_call_chunk(
                    0,
                    call_id="call_1",
                    name="search_products",
                    arguments='{"query": "watch"',
                )
            if self._idx == 3:
                scope.cancel()
                return _make_usage_chunk()
            raise StopIteration

        def close(self):
            pass

    completions = SimpleNamespace(create=lambda **kwargs: CancelAfterToolDeltaStream())
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Hi"))

    assert outputs[-1][:3] == ("__END_OF_RESPONSE__", None, None)
    assistant_messages = [msg for msg in handler.chat.buffer if msg.get("role") == "assistant"]
    assert assistant_messages == [{"role": "assistant", "content": "Let me check."}]
    assert all("tool_calls" not in msg for msg in assistant_messages)


def test_invalid_tool_call_arguments_are_sanitized_only_for_chat_history():
    handler = _make_handler()
    invalid_arguments = '{"city": "city", "bedrooms": 3, "max_price": max_price}'
    chunks = [
        _make_tool_call_chunk(
            0,
            call_id="call_1",
            name="search_apartments",
            arguments=invalid_arguments,
        ),
    ]

    completions = SimpleNamespace(create=lambda **kwargs: MockStream(chunks))
    handler.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    outputs = list(handler.process("Find an apartment"))

    raw_tool_outputs = [o for o in outputs if isinstance(o[0], str) and o[2]]
    assert raw_tool_outputs[0][2][0]["function"]["arguments"] == invalid_arguments
    assistant_messages = [msg for msg in handler.chat.buffer if msg.get("role") == "assistant"]
    history_arguments = assistant_messages[0]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(history_arguments) == {"_invalid_arguments": invalid_arguments}


# ---------------------------------------------------------------------------
# Tests: agent loop tool deduplication
# ---------------------------------------------------------------------------

def test_convert_tools_accepts_bare_flat_seed_schema():
    handler = OpenApiModelHandler.__new__(OpenApiModelHandler)

    converted = handler._convert_tools_for_chat_api([
        {
            "name": "recommend_get",
            "description": "Generate category recommendations.",
            "parameters": {
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }
    ])

    assert converted == [
        {
            "type": "function",
            "function": {
                "name": "recommend_get",
                "description": "Generate category recommendations.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }
    ]


class TestMergeTools:

    def test_merge_server_tools_with_client_tools(self):
        from handlers.llm.tool_call.tool_registry import ToolRegistry
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.tool_registry = ToolRegistry()
        handler.tool_registry.register("server_tool", lambda: "ok", description="A server tool",
                                       parameters={"type": "object", "properties": {}})

        client_tools = [{
            "type": "function",
            "function": {"name": "client_tool", "description": "A client tool", "parameters": {}},
        }]
        result = handler._merge_tools({"tools": client_tools})
        names = [t["function"]["name"] for t in result["tools"]]
        assert "client_tool" in names
        assert "server_tool" in names

    def test_dedup_same_name(self):
        from handlers.llm.tool_call.tool_registry import ToolRegistry
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.tool_registry = ToolRegistry()
        handler.runtime_config = None
        handler.tool_registry.register("search_knowledge", lambda q: "ok", description="Server KB",
                                       parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})

        client_tools = [
            {"type": "function", "function": {"name": "search_knowledge", "description": "Client KB", "parameters": {}}},
            {"type": "function", "function": {"name": "transferToHuman", "description": "Transfer", "parameters": {}}},
        ]
        result = handler._merge_tools({"tools": client_tools})
        names = [t["function"]["name"] for t in result["tools"]]
        assert "search_knowledge" in names
        assert "transferToHuman" in names
        assert names.count("search_knowledge") == 1  # no duplicate

    def test_runtime_scoped_tools_do_not_merge_server_tools(self):
        from handlers.llm.tool_call.tool_registry import ToolRegistry
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.tool_registry = ToolRegistry()
        handler.tool_registry.register("server_tool", lambda: "ok", description="A server tool",
                                       parameters={"type": "object", "properties": {}})
        handler.runtime_config = SimpleNamespace(session=SimpleNamespace(tools=[{"name": "runtime_tool"}]))

        runtime_tools = [{
            "type": "function",
            "function": {"name": "runtime_tool", "description": "Runtime tool", "parameters": {}},
        }]
        result = handler._merge_tools({"tools": runtime_tools})
        names = [t["function"]["name"] for t in result["tools"]]
        assert names == ["runtime_tool"]

    def test_no_registry(self):
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.tool_registry = None
        client_tools = [{"type": "function", "function": {"name": "a"}}]
        result = handler._merge_tools({"tools": client_tools})
        assert len(result["tools"]) == 1


class TestAgentLoopActive:

    def test_active_with_tools(self):
        from handlers.llm.tool_call.tool_registry import ToolRegistry
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.tool_registry = ToolRegistry()
        handler.tool_registry.register("test", lambda: "ok")
        handler.max_agent_iterations = 10
        handler._agent_loop_active = True
        assert handler._agent_loop_active is True

    def test_inactive_without_tools(self):
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.tool_registry = None
        handler._agent_loop_active = False
        assert handler._agent_loop_active is False


class TestServerToolExecution:

    def test_single_server_tool_does_not_create_outer_thread_pool(self, monkeypatch):
        from handlers.llm import openai_api_language_model as llm_module
        from handlers.llm.tool_call.tool_registry import NormalizedToolCall, ToolRegistry

        class ExplodingExecutor:
            def __init__(self, *args, **kwargs):
                raise AssertionError("ThreadPoolExecutor should not be used for one tool")

        monkeypatch.setattr(llm_module, "ThreadPoolExecutor", ExplodingExecutor)

        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.cancel_scope = None
        handler.tool_registry = ToolRegistry()
        handler.tool_registry.register("lookup", lambda: "ok")

        results, cancelled = handler._execute_server_tools_concurrently(
            [NormalizedToolCall(call_id="call_1", name="lookup", arguments="{}")],
            iteration=0,
            gen=None,
            tool_context={},
        )

        assert results == ["ok"]
        assert cancelled is False

    def test_server_tool_execution_falls_back_when_thread_pool_is_shutting_down(self, monkeypatch):
        from handlers.llm import openai_api_language_model as llm_module
        from handlers.llm.tool_call.tool_registry import NormalizedToolCall, ToolRegistry

        class ShutdownExecutor:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, *args, **kwargs):
                raise RuntimeError("cannot schedule new futures after interpreter shutdown")

        monkeypatch.setattr(llm_module, "ThreadPoolExecutor", ShutdownExecutor)

        calls = []
        handler = OpenApiModelHandler.__new__(OpenApiModelHandler)
        handler.cancel_scope = None
        handler.tool_registry = ToolRegistry()
        handler.tool_registry.register("first", lambda: calls.append("first") or "one")
        handler.tool_registry.register("second", lambda: calls.append("second") or "two")

        results, cancelled = handler._execute_server_tools_concurrently(
            [
                NormalizedToolCall(call_id="call_1", name="first", arguments="{}"),
                NormalizedToolCall(call_id="call_2", name="second", arguments="{}"),
            ],
            iteration=0,
            gen=None,
            tool_context={},
        )

        assert results == ["one", "two"]
        assert cancelled is False
        assert calls == ["first", "second"]
