"""
Unit tests for full-duplex pipeline components.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from apps.agent.pipeline.framework import (
    Frame,
    FrameDirection,
    StartFrame,
    EndFrame,
    TextFrame,
    AsyncFunctionCallFrame,
    FunctionCallEndFrame,
    FunctionCallCancelFrame,
    LLMMessagesAppendFrame,
    LLMFullResponseEndFrame,
    FunctionCallInProgressFrame,
)
from apps.agent.pipeline.state_machine import LLMStateMachine, State, InvalidStateTransition
from apps.agent.pipeline.processors.async_executor import AsyncExecutorProcessor
from apps.agent.pipeline.processors.full_duplex_llm_processor import FullDuplexLLMProcessor


class TestLLMStateMachine:
    """Tests for LLMStateMachine."""

    def test_initial_state(self):
        """Test initial state is IDLE."""
        sm = LLMStateMachine()
        assert sm.current_state == State.IDLE
        assert sm.is_idle
        assert not sm.is_calling
        assert not sm.has_pending_tools

    def test_valid_transitions(self):
        """Test valid state transitions."""
        sm = LLMStateMachine()

        # IDLE -> LLM_CALLING
        sm.transition_to(State.LLM_CALLING)
        assert sm.is_calling

        # LLM_CALLING -> WAITING_FOR_TOOLS
        sm.transition_to(State.WAITING_FOR_TOOLS)
        assert sm.is_waiting_for_tools

        # WAITING_FOR_TOOLS -> TOOL_EXECUTING
        sm.transition_to(State.TOOL_EXECUTING)
        assert sm.is_executing_tools

        # TOOL_EXECUTING -> LLM_CALLING
        sm.transition_to(State.LLM_CALLING)
        assert sm.is_calling

        # LLM_CALLING -> COMPLETED
        sm.transition_to(State.COMPLETED)
        assert sm.is_completed

    def test_invalid_transitions(self):
        """Test invalid state transitions raise exception."""
        sm = LLMStateMachine()

        # IDLE cannot go directly to COMPLETED
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(State.COMPLETED)

        # IDLE cannot go directly to WAITING_FOR_TOOLS
        with pytest.raises(InvalidStateTransition):
            sm.transition_to(State.WAITING_FOR_TOOLS)

    def test_pending_tools(self):
        """Test pending tools tracking."""
        sm = LLMStateMachine()

        sm.add_pending_tool("tool_1")
        sm.add_pending_tool("tool_2")

        assert sm.pending_tool_count == 2
        assert sm.has_pending_tools

        # Complete one tool
        all_done = sm.complete_tool("tool_1")
        assert not all_done
        assert sm.pending_tool_count == 1

        # Complete the last tool
        all_done = sm.complete_tool("tool_2")
        assert all_done
        assert not sm.has_pending_tools

    def test_tool_failure(self):
        """Test tool failure handling."""
        sm = LLMStateMachine()

        sm.add_pending_tool("tool_1")
        sm.add_pending_tool("tool_2")

        # Fail one tool
        all_done = sm.fail_tool("tool_1", "error message")
        assert not all_done
        assert sm.pending_tool_count == 1

    def test_reset(self):
        """Test state machine reset."""
        sm = LLMStateMachine()

        sm.transition_to(State.LLM_CALLING)
        sm.add_pending_tool("tool_1")

        sm.reset()

        assert sm.is_idle
        assert not sm.has_pending_tools

    def test_state_info(self):
        """Test getting state info."""
        sm = LLMStateMachine()
        sm.add_pending_tool("tool_1")

        info = sm.get_state_info()
        assert info["state"] == "idle"
        assert "tool_1" in info["pending_tools"]
        assert info["pending_count"] == 1


class TestAsyncExecutorProcessor:
    """Tests for AsyncExecutorProcessor."""

    @pytest.fixture
    def executor(self):
        """Create an AsyncExecutorProcessor for testing."""
        return AsyncExecutorProcessor(enable_direct_mode=True)

    @pytest.fixture
    def mock_handler(self):
        """Create a mock async handler."""
        return AsyncMock(return_value={"result": "success"})

    @pytest.mark.asyncio
    async def test_register_handler(self, executor):
        """Test handler registration."""
        handler = AsyncMock()

        executor.register_handler("test_func", handler)
        assert "test_func" in executor._handlers

        executor.unregister_handler("test_func")
        assert "test_func" not in executor._handlers

    @pytest.mark.asyncio
    async def test_async_function_call_success(self, executor, mock_handler):
        """Test successful async function call."""
        executor.register_handler("test_func", mock_handler)

        # Create a mock next processor to capture the callback
        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append(frame)

        mock_next = MockNextProcessor()
        executor._next = mock_next
        executor._started = True

        # Send async function call frame
        await executor.process_frame(
            AsyncFunctionCallFrame(
                function_name="test_func",
                tool_call_id="tc_1",
                arguments={"query": "test"},
                callback_id="cb_1",
            ),
            FrameDirection.DOWNSTREAM,
        )

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Check that handler was called with AsyncFunctionCallFrame
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args[0][0]
        assert isinstance(call_args, AsyncFunctionCallFrame)
        assert call_args.function_name == "test_func"
        assert call_args.arguments == {"query": "test"}

        # Check that callback frame was sent
        assert len(captured_frames) == 1
        assert isinstance(captured_frames[0], FunctionCallEndFrame)
        assert captured_frames[0].callback_id == "cb_1"
        assert captured_frames[0].status == "success"
        assert captured_frames[0].result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_async_function_call_error(self, executor):
        """Test async function call with error."""
        error_handler = AsyncMock(side_effect=Exception("test error"))
        executor.register_handler("error_func", error_handler)

        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append(frame)

        mock_next = MockNextProcessor()
        executor._next = mock_next
        executor._started = True

        await executor.process_frame(
            AsyncFunctionCallFrame(
                function_name="error_func",
                tool_call_id="tc_1",
                arguments={},
                callback_id="cb_1",
            ),
            FrameDirection.DOWNSTREAM,
        )

        await asyncio.sleep(0.1)

        assert len(captured_frames) == 1
        assert captured_frames[0].status == "error"
        assert "test error" in captured_frames[0].error_message

    @pytest.mark.asyncio
    async def test_async_function_call_timeout(self, executor):
        """Test async function call timeout."""
        async def slow_handler(args):
            await asyncio.sleep(1.0)  # Slow operation
            return "result"

        executor.register_handler("slow_func", slow_handler)

        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append(frame)

        mock_next = MockNextProcessor()
        executor._next = mock_next
        executor._started = True

        await executor.process_frame(
            AsyncFunctionCallFrame(
                function_name="slow_func",
                tool_call_id="tc_1",
                arguments={},
                callback_id="cb_1",
                timeout_seconds=0.01,  # Very short timeout
            ),
            FrameDirection.DOWNSTREAM,
        )

        await asyncio.sleep(0.1)

        assert len(captured_frames) == 1
        assert captured_frames[0].status == "timeout"

    @pytest.mark.asyncio
    async def test_unknown_function(self, executor):
        """Test handling of unknown function."""
        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append(frame)

        mock_next = MockNextProcessor()
        executor._next = mock_next
        executor._started = True

        await executor.process_frame(
            AsyncFunctionCallFrame(
                function_name="unknown_func",
                tool_call_id="tc_1",
                arguments={},
                callback_id="cb_1",
            ),
            FrameDirection.DOWNSTREAM,
        )

        assert len(captured_frames) == 1
        assert captured_frames[0].status == "error"
        assert "Unknown function" in captured_frames[0].error_message

    @pytest.mark.asyncio
    async def test_cancel_task(self, executor):
        """Test task cancellation."""
        slow_handler = AsyncMock()
        slow_handler.side_effect = asyncio.sleep(10.0)

        executor.register_handler("slow_func", slow_handler)

        executor._started = True

        # Start a slow task
        await executor.process_frame(
            AsyncFunctionCallFrame(
                function_name="slow_func",
                tool_call_id="tc_1",
                arguments={},
                callback_id="cb_1",
            ),
            FrameDirection.DOWNSTREAM,
        )

        # Verify task is pending
        assert executor.is_task_pending("cb_1")
        assert executor.get_pending_count() == 1

        # Cancel the task
        await executor.process_frame(
            FunctionCallCancelFrame(callback_id="cb_1"),
            FrameDirection.DOWNSTREAM,
        )

        await asyncio.sleep(0.1)

        # Task should no longer be pending
        assert not executor.is_task_pending("cb_1")

    @pytest.mark.asyncio
    async def test_cleanup(self, executor):
        """Test cleanup of pending tasks."""
        slow_handler = AsyncMock()
        slow_handler.side_effect = asyncio.sleep(10.0)

        executor.register_handler("slow_func", slow_handler)
        executor._started = True

        # Start multiple slow tasks
        for i in range(3):
            await executor.process_frame(
                AsyncFunctionCallFrame(
                    function_name="slow_func",
                    tool_call_id=f"tc_{i}",
                    arguments={},
                    callback_id=f"cb_{i}",
                ),
                FrameDirection.DOWNSTREAM,
            )

        assert executor.get_pending_count() == 3

        # Cleanup
        await executor.cleanup()

        assert executor.get_pending_count() == 0


class TestFullDuplexLLMProcessor:
    """Tests for FullDuplexLLMProcessor."""

    @pytest.fixture
    def mock_llm_provider(self):
        """Create a mock LLM provider."""
        provider = MagicMock()
        provider.config = {}

        async def mock_chat(*args, **kwargs):
            # Simulate streaming response with no tool calls
            async def generator():
                yield {"type": "content", "content": "Hello"}
                yield {"type": "content", "content": " world"}
                yield {"type": "done"}

            return generator()

        provider.chat = mock_chat
        return provider

    @pytest.fixture
    def mock_async_executor(self):
        """Create a mock async executor."""
        executor = MagicMock()
        executor.process_frame = AsyncMock()
        return executor

    @pytest.fixture
    def processor(self, mock_llm_provider, mock_async_executor):
        """Create a FullDuplexLLMProcessor for testing."""
        proc = FullDuplexLLMProcessor(
            llm_provider=mock_llm_provider,
            enable_direct_mode=True,
        )
        proc.register_async_executor(mock_async_executor)
        return proc

    @pytest.mark.asyncio
    async def test_process_text_frame(self, processor):
        """Test processing text frame."""
        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append(frame)

        processor.link(MockNextProcessor())
        processor._started = True

        await processor.process_frame(
            TextFrame(text="Hello"),
            FrameDirection.DOWNSTREAM,
        )

        assert len(captured_frames) == 1
        assert isinstance(captured_frames[0], TextFrame)
        assert captured_frames[0].text == "Hello"

    @pytest.mark.asyncio
    async def test_max_iterations(self, processor, mock_llm_provider):
        """Test max iterations limit."""
        call_count = 0

        async def mock_chat_with_tools(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            async def generator():
                # First call returns tool calls, subsequent calls return text
                if call_count <= 2:
                    yield {
                        "type": "tool_calls",
                        "functions": ["test_func"],
                        "arguments": ['{"query": "test"}'],
                        "tool_ids": [f"tc_{call_count}"],
                    }
                else:
                    yield {"type": "content", "content": "Final answer"}
                yield {"type": "done"}

            return generator()

        mock_llm_provider.chat = mock_chat_with_tools
        processor._max_iterations = 2

        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append(frame)
                # Simulate async executor sending callback for tool calls
                if isinstance(frame, FunctionCallInProgressFrame):
                    # Send the callback back to processor
                    asyncio.create_task(
                        processor.process_frame(
                            FunctionCallEndFrame(
                                callback_id=f"tc_{frame.tool_call_id}",
                                function_name=frame.function_name,
                                tool_call_id=frame.tool_call_id,
                                result="Tool result",
                                status="success",
                            ),
                            direction,
                        )
                    )

        processor.link(MockNextProcessor())
        processor._started = True

        await processor.process_frame(
            LLMMessagesAppendFrame(messages=[{"role": "user", "content": "test"}]),
            FrameDirection.DOWNSTREAM,
        )

        # Wait for async callbacks
        await asyncio.sleep(0.2)

        # Should hit max iterations and complete
        end_frames = [f for f in captured_frames if isinstance(f, LLMFullResponseEndFrame)]
        assert len(end_frames) == 1
        # Verify we hit the max iterations (2 LLM calls with tool results)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_get_context_messages(self, processor):
        """Test getting context messages."""
        processor._final_messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

        messages = processor.get_context_messages()

        # System message should be filtered out
        assert len(messages) == 2
        assert all(m.get("role") != "system" for m in messages)

    @pytest.mark.asyncio
    async def test_reset(self, processor):
        """Test processor reset."""
        processor._messages = [{"role": "user", "content": "test"}]
        processor._final_messages = [{"role": "assistant", "content": "response"}]
        processor._iteration_count = 5

        processor.reset()

        assert processor._messages == []
        assert processor._final_messages == []
        assert processor._iteration_count == 0
        assert processor._state_machine.is_idle


class TestIntegration:
    """Integration tests for full-duplex pipeline."""

    @pytest.mark.asyncio
    async def test_full_flow_with_tool_call(self):
        """Test complete flow with tool call."""
        # This is a simplified integration test
        # In practice, you'd use the actual LLM provider and handlers

        # Create components
        executor = AsyncExecutorProcessor(enable_direct_mode=True)

        # Register a simple handler that works with AsyncFunctionCallFrame
        async def echo_handler(frame: AsyncFunctionCallFrame):
            return f"Echo: {frame.arguments.get('message', '')}"

        executor.register_handler("echo", echo_handler)

        # Create mock next processor
        captured_frames = []

        class MockNextProcessor:
            async def process_frame(self, frame, direction):
                captured_frames.append((type(frame).__name__, frame))

        mock_next = MockNextProcessor()
        executor.link(mock_next)

        # Start executor
        await executor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

        # Send async function call
        await executor.process_frame(
            AsyncFunctionCallFrame(
                function_name="echo",
                tool_call_id="tc_1",
                arguments={"message": "Hello"},
                callback_id="cb_1",
            ),
            FrameDirection.DOWNSTREAM,
        )

        # Wait for completion
        await asyncio.sleep(0.1)

        # Verify flow
        frame_types = [name for name, _ in captured_frames]
        assert "FunctionCallEndFrame" in frame_types

        # Find the result frame
        result_frames = [f for name, f in captured_frames if name == "FunctionCallEndFrame"]
        assert len(result_frames) == 1
        assert result_frames[0].result == "Echo: Hello"
        assert result_frames[0].status == "success"


class TestRaceConditionFix:
    """Tests for race condition fixes using Condition instead of Event.

    These tests verify that the fix for the race condition where tools
    complete before wait() is called works correctly.
    """

    @pytest.fixture
    def processor(self):
        """Create a FullDuplexLLMProcessor for testing."""
        provider = MagicMock()
        provider.config = {}

        async def mock_chat(*args, **kwargs):
            async def generator():
                yield {"type": "content", "content": "test"}
                yield {"type": "done"}
            return generator()

        provider.chat = mock_chat

        async_executor = MagicMock()
        async_executor.process_frame = AsyncMock()

        proc = FullDuplexLLMProcessor(
            llm_provider=provider,
            enable_direct_mode=True,
        )
        proc.register_async_executor(async_executor)
        return proc

    @pytest.mark.asyncio
    async def test_condition_not_event(self, processor):
        """Verify that processor uses Condition instead of Event."""
        # Check that _pending_tools_condition exists and is a Condition
        assert hasattr(processor, '_pending_tools_condition')
        assert isinstance(processor._pending_tools_condition, asyncio.Condition)
        # Check that _tools_complete_event does NOT exist (was replaced)
        assert not hasattr(processor, '_tools_complete_event')

    @pytest.mark.asyncio
    async def test_wait_for_tools_complete_basic(self, processor):
        """Test basic wait/notify with Condition."""
        # Set pending count to 1
        await processor._set_pending_tools(1)

        # Complete it in a separate task after a small delay
        async def complete_after():
            await asyncio.sleep(0.01)
            await processor._notify_tool_complete()

        # Wait and complete concurrently
        await asyncio.gather(
            processor._wait_for_tools_complete(),
            complete_after()
        )

        # Verify count is 0
        async with processor._pending_tools_condition:
            assert processor._pending_tool_count == 0

    @pytest.mark.asyncio
    async def test_notify_before_wait(self, processor):
        """Test that notify before wait works correctly (the race condition scenario)."""
        # This tests the exact race condition that was fixed:
        # Tool completes before wait() is called

        # Set pending count to 1
        await processor._set_pending_tools(1)

        # Complete immediately (simulating fast tool execution)
        await processor._notify_tool_complete()

        # Now wait - should return immediately since count is already 0
        # This would have deadlocked with Event but works with Condition
        wait_task = asyncio.create_task(processor._wait_for_tools_complete())

        # Give it a moment to run
        await asyncio.sleep(0.01)

        # Should have completed (not deadlocked)
        assert wait_task.done(), "wait() deadlocked when notify came before wait()"

    @pytest.mark.asyncio
    async def test_multiple_tools_concurrent(self, processor):
        """Test multiple tools completing concurrently."""
        num_tools = 5
        await processor._set_pending_tools(num_tools)

        async def complete_tool(i: int):
            await asyncio.sleep(0.001 * (num_tools - i))  # Different delays
            await processor._notify_tool_complete()

        # Complete all tools concurrently
        await asyncio.gather(*[complete_tool(i) for i in range(num_tools)])

        # All should be done
        async with processor._pending_tools_condition:
            assert processor._pending_tool_count == 0

    @pytest.mark.asyncio
    async def test_reset_clears_pending_count(self, processor):
        """Test that reset() clears the pending tool count."""
        await processor._set_pending_tools(5)

        processor.reset()

        async with processor._pending_tools_condition:
            assert processor._pending_tool_count == 0

    @pytest.mark.asyncio
    async def test_error_handler_resets_condition(self, processor):
        """Test that error handler properly resets the condition."""
        # Set pending tools
        await processor._set_pending_tools(3)

        # Simulate error handling by calling _set_pending_tools(0)
        await processor._set_pending_tools(0)

        # Now wait should return immediately
        wait_task = asyncio.create_task(processor._wait_for_tools_complete())
        await asyncio.sleep(0.01)

        assert wait_task.done(), "Error handler did not properly reset condition"
