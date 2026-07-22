"""Unit tests for AgentLoopCore."""

import asyncio
import json
import pytest

from core.agent_loop import (
    AgentLoopCore,
    StreamChunk,
    TextChunk,
    ReasoningChunk,
    ToolCallStarted,
    ToolCallDispatched,
    ToolResult,
    IterationMetrics,
    Error,
)


# =====================================================================
# Test fixtures and helpers
# =====================================================================


def make_streamer(chunks: list[StreamChunk]):
    """Create a simple streamer that yields pre-defined chunks."""
    async def streamer(messages, tools, **kwargs):
        for chunk in chunks:
            yield chunk
    return streamer


def make_tool_executor(responses: dict[str, str] | None = None):
    """Create a simple tool executor that returns predefined responses."""
    responses = responses or {}

    def executor(name: str, args_json: str) -> str:
        if name in responses:
            return responses[name]
        return f"Result from {name}"
    return executor


async def collect_events(loop: AgentLoopCore, messages: list, tools: list | None = None):
    """Run the agent loop and collect all events."""
    events = []
    async for event in loop.run(messages, tools):
        events.append(event)
    return events


# =====================================================================
# Tests: Simple text generation
# =====================================================================


class TestSimpleTextGeneration:
    """Test cases for simple LLM responses without tool calls."""

    @pytest.mark.asyncio
    async def test_text_only_response(self):
        """LLM returns text only, no tools."""
        chunks = [
            StreamChunk(text="Hello"),
            StreamChunk(text=" world"),
            StreamChunk(usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ]
        loop = AgentLoopCore(
            llm_streamer=make_streamer(chunks),
            tool_executor=make_tool_executor(),
        )
        messages = [{"role": "user", "content": "Hi"}]
        events = await collect_events(loop, messages)

        # Should have TextChunks + IterationMetrics
        text_events = [e for e in events if isinstance(e, TextChunk)]
        assert len(text_events) == 2
        assert text_events[0].text == "Hello"
        assert text_events[1].text == " world"

        metrics = [e for e in events if isinstance(e, IterationMetrics)]
        assert len(metrics) == 1
        assert metrics[0].iteration == 0
        assert metrics[0].prompt_tokens == 10
        assert metrics[0].completion_tokens == 5

    @pytest.mark.asyncio
    async def test_empty_response(self):
        """LLM returns nothing."""
        chunks = []
        loop = AgentLoopCore(
            llm_streamer=make_streamer(chunks),
            tool_executor=make_tool_executor(),
        )
        messages = [{"role": "user", "content": "Hi"}]
        events = await collect_events(loop, messages)

        # Should still have IterationMetrics
        metrics = [e for e in events if isinstance(e, IterationMetrics)]
        assert len(metrics) == 1

    @pytest.mark.asyncio
    async def test_reasoning_content(self):
        """LLM returns reasoning/thinking content."""
        chunks = [
            StreamChunk(reasoning="Let me think..."),
            StreamChunk(text="The answer is 42"),
        ]
        loop = AgentLoopCore(
            llm_streamer=make_streamer(chunks),
            tool_executor=make_tool_executor(),
        )
        messages = [{"role": "user", "content": "What is the answer?"}]
        events = await collect_events(loop, messages)

        reasoning_events = [e for e in events if isinstance(e, ReasoningChunk)]
        assert len(reasoning_events) == 1
        assert reasoning_events[0].text == "Let me think..."


# =====================================================================
# Tests: Tool call delta accumulation
# =====================================================================


class TestToolDeltaAccumulation:
    """Test the static tool delta accumulation logic."""

    def test_single_tool_complete(self):
        """Single tool call with all info in one delta."""
        buffers = {}
        delta = {"index": 0, "id": "call_123", "function": {"name": "get_weather", "arguments": '{"city":"Beijing"}'}}
        AgentLoopCore._accumulate_tool_delta(delta, buffers)

        tc = AgentLoopCore._try_parse_tool(buffers[0])
        assert tc is not None
        assert tc.name == "get_weather"
        assert tc.arguments == {"city": "Beijing"}
        assert tc.call_id == "call_123"

    def test_tool_delta_split_across_chunks(self):
        """Tool call arguments split across multiple deltas."""
        buffers = {}

        # First chunk: name + partial arguments
        AgentLoopCore._accumulate_tool_delta(
            {"index": 0, "id": "call_abc", "function": {"name": "search", "arguments": '{"query":'}},
            buffers,
        )
        # Not complete yet
        assert AgentLoopCore._try_parse_tool(buffers[0]) is None

        # Second chunk: rest of arguments
        AgentLoopCore._accumulate_tool_delta(
            {"index": 0, "function": {"arguments": '"test"}'}},
            buffers,
        )
        # Now complete
        tc = AgentLoopCore._try_parse_tool(buffers[0])
        assert tc is not None
        assert tc.name == "search"
        assert tc.arguments == {"query": "test"}

    def test_multiple_tools(self):
        """Multiple tool calls in parallel."""
        buffers = {}
        AgentLoopCore._accumulate_tool_delta(
            {"index": 0, "id": "call_1", "function": {"name": "tool_a", "arguments": '{"x":1}'}},
            buffers,
        )
        AgentLoopCore._accumulate_tool_delta(
            {"index": 1, "id": "call_2", "function": {"name": "tool_b", "arguments": '{"y":2}'}},
            buffers,
        )

        tc0 = AgentLoopCore._try_parse_tool(buffers[0])
        tc1 = AgentLoopCore._try_parse_tool(buffers[1])
        assert tc0.name == "tool_a"
        assert tc1.name == "tool_b"

    def test_invalid_json_returns_none(self):
        """Invalid JSON arguments returns None."""
        buffers = {}
        AgentLoopCore._accumulate_tool_delta(
            {"index": 0, "id": "call_x", "function": {"name": "broken", "arguments": "not json"}},
            buffers,
        )
        assert AgentLoopCore._try_parse_tool(buffers[0]) is None

    def test_empty_name_returns_none(self):
        """Empty name returns None."""
        buffers = {0: {"id": "", "name": "", "arguments": "{}"}}
        assert AgentLoopCore._try_parse_tool(buffers[0]) is None

    def test_empty_arguments_defaults_to_empty_dict(self):
        """Empty arguments string should parse as empty dict."""
        buffers = {0: {"id": "call_z", "name": "no_args", "arguments": ""}}
        tc = AgentLoopCore._try_parse_tool(buffers[0])
        assert tc is not None
        assert tc.arguments == {}

    def test_auto_generated_call_id(self):
        """Missing id should auto-generate one."""
        buffers = {}
        AgentLoopCore._accumulate_tool_delta(
            {"index": 0, "function": {"name": "my_tool", "arguments": "{}"}},
            buffers,
        )
        tc = AgentLoopCore._try_parse_tool(buffers[0])
        assert tc is not None
        assert tc.call_id.startswith("tc_")


# =====================================================================
# Tests: Tool call with streaming dispatch
# =====================================================================


class TestStreamingToolDispatch:
    """Test streaming tool dispatch behavior."""

    @pytest.mark.asyncio
    async def test_single_tool_streaming_dispatch(self):
        """Tool dispatched during LLM streaming when args complete."""
        call_count = 0

        async def multi_streamer(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamChunk(text="Let me check")
                yield StreamChunk(tool_call_delta={
                    "index": 0, "id": "call_w",
                    "function": {"name": "get_weather", "arguments": '{"city":"Beijing"}'},
                })
                yield StreamChunk(text=" Done.")
                yield StreamChunk(usage={"prompt_tokens": 20, "completion_tokens": 10})
            else:
                # Second round: final answer
                yield StreamChunk(text="The weather is Sunny, 25C.")

        loop = AgentLoopCore(
            llm_streamer=multi_streamer,
            tool_executor=make_tool_executor({"get_weather": "Sunny, 25C"}),
            streaming_tools=True,
        )
        messages = [{"role": "user", "content": "What's the weather?"}]
        events = await collect_events(loop, messages)

        # Should have TextChunk + ToolCallStarted + ToolCallDispatched + ToolResult
        assert any(isinstance(e, TextChunk) and e.text == "Let me check" for e in events)
        assert any(isinstance(e, ToolCallStarted) for e in events)
        assert any(isinstance(e, ToolCallDispatched) and e.name == "get_weather" for e in events)
        assert any(isinstance(e, ToolResult) and e.result == "Sunny, 25C" for e in events)

        # Two iterations: first with tool, second with final answer
        metrics = [e for e in events if isinstance(e, IterationMetrics)]
        assert len(metrics) == 2
        assert len(metrics[0].tool_calls) == 1

    @pytest.mark.asyncio
    async def test_tool_dispatch_after_stream(self):
        """With streaming_tools=False, tools dispatched after stream ends."""
        call_count = 0

        async def two_round_streamer(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamChunk(tool_call_delta={
                    "index": 0, "id": "call_1",
                    "function": {"name": "get_time", "arguments": "{}"},
                })
            else:
                yield StreamChunk(text="It is 12:00.")

        loop = AgentLoopCore(
            llm_streamer=two_round_streamer,
            tool_executor=make_tool_executor({"get_time": "12:00"}),
            streaming_tools=False,  # Disable streaming dispatch
        )
        messages = [{"role": "user", "content": "What time?"}]
        events = await collect_events(loop, messages)

        # ToolCallDispatched should appear (after stream ends)
        dispatched = [e for e in events if isinstance(e, ToolCallDispatched)]
        assert len(dispatched) == 1
        assert dispatched[0].name == "get_time"

        results = [e for e in events if isinstance(e, ToolResult)]
        assert len(results) == 1
        assert results[0].result == "12:00"


# =====================================================================
# Tests: Multi-round iteration
# =====================================================================


class TestMultiRoundIteration:
    """Test multi-round agent loop (LLM -> tool -> LLM -> done)."""

    @pytest.mark.asyncio
    async def test_two_round_loop(self):
        """First round: LLM calls tool. Second round: LLM gives final answer."""
        call_count = 0

        async def multi_streamer(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First round: call a tool
                yield StreamChunk(tool_call_delta={
                    "index": 0, "id": "call_r1",
                    "function": {"name": "search", "arguments": '{"q":"test"}'},
                })
            else:
                # Second round: final text answer
                yield StreamChunk(text="Based on the search, the answer is 42.")
                yield StreamChunk(usage={"prompt_tokens": 30, "completion_tokens": 15})

        loop = AgentLoopCore(
            llm_streamer=multi_streamer,
            tool_executor=make_tool_executor({"search": "Found: 42"}),
        )
        messages = [{"role": "user", "content": "Search for test"}]
        events = await collect_events(loop, messages)

        # Two iterations
        metrics = [e for e in events if isinstance(e, IterationMetrics)]
        assert len(metrics) == 2
        assert metrics[0].iteration == 0
        assert metrics[1].iteration == 1

        # Second iteration should have text
        text_events = [e for e in events if isinstance(e, TextChunk)]
        assert any("42" in e.text for e in text_events)

        # Tool result should appear
        results = [e for e in events if isinstance(e, ToolResult)]
        assert len(results) == 1
        assert results[0].result == "Found: 42"

    @pytest.mark.asyncio
    async def test_max_iterations(self):
        """Loop stops after max_iterations."""
        async def always_tool(messages, tools, **kwargs):
            yield StreamChunk(tool_call_delta={
                "index": 0, "id": f"call_{id(messages)}",
                "function": {"name": "loop_tool", "arguments": "{}"},
            })

        loop = AgentLoopCore(
            llm_streamer=always_tool,
            tool_executor=make_tool_executor(),
            max_iterations=3,
        )
        messages = [{"role": "user", "content": "loop"}]
        events = await collect_events(loop, messages)

        metrics = [e for e in events if isinstance(e, IterationMetrics)]
        assert len(metrics) == 3  # Hit max


# =====================================================================
# Tests: Cancellation
# =====================================================================


class TestCancellation:
    """Test cancellation during streaming and tool execution."""

    @pytest.mark.asyncio
    async def test_cancel_during_streaming(self):
        """Cancellation during LLM streaming stops the loop."""
        cancel_after = 2
        chunk_count = 0

        async def cancel_streamer(messages, tools, **kwargs):
            nonlocal chunk_count
            for chunk in [
                StreamChunk(text="chunk1"),
                StreamChunk(text="chunk2"),
                StreamChunk(text="chunk3"),
                StreamChunk(text="chunk4"),
            ]:
                chunk_count += 1
                yield chunk

        cancelled = False

        def is_cancelled():
            nonlocal cancelled
            if chunk_count >= cancel_after:
                cancelled = True
            return cancelled

        loop = AgentLoopCore(
            llm_streamer=cancel_streamer,
            tool_executor=make_tool_executor(),
            is_cancelled=is_cancelled,
        )
        messages = [{"role": "user", "content": "test"}]
        events = await collect_events(loop, messages)

        metrics = [e for e in events if isinstance(e, IterationMetrics)]
        assert len(metrics) == 1
        assert metrics[0].cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_during_tool_execution(self):
        """_run_single_tool returns cancelled when is_cancelled is True."""
        from core.agent_loop.core import ToolCallReady

        loop = AgentLoopCore(
            llm_streamer=make_streamer([]),
            tool_executor=lambda n, a: "should not be called",
            is_cancelled=lambda: True,
        )
        tc = ToolCallReady(name="test_tool", arguments={"x": 1}, call_id="call_t")
        result = await loop._run_single_tool(tc)
        assert result.status == "cancelled"
        assert result.name == "test_tool"
        assert result.call_id == "call_t"


# =====================================================================
# Tests: Error handling
# =====================================================================


class TestErrorHandling:
    """Test error handling in LLM streaming and tool execution."""

    @pytest.mark.asyncio
    async def test_llm_stream_error(self):
        """LLM stream raises exception."""
        async def error_streamer(messages, tools, **kwargs):
            yield StreamChunk(text="partial")
            raise RuntimeError("API timeout")

        loop = AgentLoopCore(
            llm_streamer=error_streamer,
            tool_executor=make_tool_executor(),
        )
        messages = [{"role": "user", "content": "test"}]
        events = await collect_events(loop, messages)

        errors = [e for e in events if isinstance(e, Error)]
        assert len(errors) == 1
        assert "timeout" in errors[0].message

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        """Tool raises exception, captured as error ToolResult."""
        call_count = 0

        async def tool_streamer(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamChunk(tool_call_delta={
                    "index": 0, "id": "call_err",
                    "function": {"name": "bad_tool", "arguments": "{}"},
                })
            else:
                yield StreamChunk(text="Recovering from error.")

        def failing_executor(name, args):
            raise ValueError("Tool crashed")

        loop = AgentLoopCore(
            llm_streamer=tool_streamer,
            tool_executor=failing_executor,
            max_iterations=2,  # Limit to avoid infinite loop
        )
        messages = [{"role": "user", "content": "test"}]
        events = await collect_events(loop, messages)

        results = [e for e in events if isinstance(e, ToolResult)]
        assert len(results) == 1
        assert results[0].status == "error"
        assert "crashed" in results[0].result


# =====================================================================
# Tests: Message history management
# =====================================================================


class TestMessageHistory:
    """Test that messages list is properly managed."""

    @pytest.mark.asyncio
    async def test_messages_not_mutated(self):
        """Original messages list is not mutated."""
        chunks = [StreamChunk(text="Hi")]
        loop = AgentLoopCore(
            llm_streamer=make_streamer(chunks),
            tool_executor=make_tool_executor(),
        )
        original = [{"role": "user", "content": "Hello"}]
        messages = list(original)
        await collect_events(loop, messages)

        # Original should not be mutated
        assert len(original) == 1
        # messages was shallow copied, so it's also not mutated
        assert len(messages) == 1

    @pytest.mark.asyncio
    async def test_assistant_and_tool_messages_appended(self):
        """Assistant + tool messages are appended to internal messages for multi-round."""
        call_count = 0
        captured_messages = []

        async def capturing_streamer(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            captured_messages.append(list(messages))
            if call_count == 1:
                yield StreamChunk(tool_call_delta={
                    "index": 0, "id": "call_h",
                    "function": {"name": "helper", "arguments": "{}"},
                })
            else:
                yield StreamChunk(text="Done")

        loop = AgentLoopCore(
            llm_streamer=capturing_streamer,
            tool_executor=make_tool_executor({"helper": "helped"}),
        )
        messages = [{"role": "user", "content": "Help me"}]
        await collect_events(loop, messages)

        # Second call should have assistant + tool messages
        assert len(captured_messages) == 2
        second_call = captured_messages[1]
        assert len(second_call) == 3  # user + assistant + tool
        assert second_call[1]["role"] == "assistant"
        assert second_call[2]["role"] == "tool"
        assert second_call[2]["content"] == "helped"
