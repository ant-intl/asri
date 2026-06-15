"""
Full-duplex LLM Processor for Chat Agent.

Implements non-blocking tool calling with async callback mechanism.
Uses state machine to manage multi-round conversations.
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from ..framework import (
    Frame,
    TextFrame,
    ThinkFrame,
    CardDataFrame,
    LLMFullResponseEndFrame,
    LLMStartFrame,
    LLMEndFrame,
    LLMMessagesAppendFrame,
    FunctionCallInProgressFrame,
    AsyncFunctionCallFrame,
    FunctionCallEndFrame,
    FunctionCallResultFrame,
    FrameDirection,
    FrameProcessor,
    FunctionSchema,
)
from ..state_machine import LLMStateMachine, State, InvalidStateTransition
from ....integrations.llm.base import BaseLLMProvider
from ...agent.context import AgentContext
from ...parsers.extractor import BaseContentExtractor
from ...parsers.mapper import OutputMapper

from apps.integrations.tool.base import ToolRegistry

logger = logging.getLogger(__name__)


class FullDuplexLLMProcessor(FrameProcessor):
    """Full-duplex LLM processor with non-blocking tool calling.

    Key changes from AsriLLMProcessor:
    1. Sends AsyncFunctionCallFrame without waiting for results
    2. Continues processing via FunctionCallEndFrame callbacks
    3. Uses state machine to manage multi-round conversations
    4. Supports concurrent tool execution
    """

    @staticmethod
    def build_tools_payload(schemas: list[FunctionSchema]) -> list[dict]:
        """Convert FunctionSchema list to OpenAI tools format.

        Args:
            schemas: List of FunctionSchema objects.

        Returns:
            List of OpenAI-format tool definitions.
        """
        return [
            {
                "type": "function",
                "function": schema.to_default_dict(),
            }
            for schema in schemas
        ]

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        tools_payload: list[dict] | None = None,
        function_handlers: dict[str, Callable] | None = None,
        context: AgentContext | None = None,
        content_extractor: BaseContentExtractor | None = None,
        output_mapper: OutputMapper | None = None,
        observation_formatter: Callable[[str], dict] | None = None,
        max_iterations: int = 10,
        enable_concurrent_tools: bool = True,
        enable_interleaved_output: bool = True,
        build_prompt_messages: Callable[..., list[dict]] | None = None,
        tool_schemas: list[dict] | None = None,
        skills: list[dict] | None = None,
        interrupt_strategy: str = "none",
        card_config_map: dict[str, dict] | None = None,
        **kwargs,
    ):
        """Initialize the full-duplex LLM processor.

        Args:
            llm_provider: ASRI LLM provider instance.
            tools_payload: OpenAI-format tools list for LLM API payload.
            function_handlers: Dict mapping function_name to async handler.
            context: Agent context for token tracking.
            content_extractor: Optional extractor for parsing LLM text content
                into structured segments (think/answer/tool_call tags).
            output_mapper: Optional mapper that converts extracted segments
                into typed output (think/answer/tool).
            observation_formatter: Optional formatter for tool observations.
            max_iterations: Maximum tool-call rounds to prevent infinite loops.
            enable_concurrent_tools: Whether to execute tools concurrently.
            enable_interleaved_output: Whether to emit intermediate <answer>
                content during streaming. When False, answer content is
                accumulated and only output at the end.
            build_prompt_messages: Optional callback to build prompt-specific
                messages. Used for interleaved thinking mode to rebuild
                2-message structure with tool_ans.
            tool_schemas: List of tool schemas for prompt building.
            skills: List of skills for prompt building.
            interrupt_strategy: Tool interrupt strategy - "immediate",
                "semantic_complete", or "none". Defaults to "none".
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self._llm_provider = llm_provider
        self._tools_payload = tools_payload
        self._function_handlers = function_handlers or {}
        self._context = context
        self._content_extractor = content_extractor
        self._output_mapper = output_mapper
        self._observation_formatter = observation_formatter
        self._max_iterations = max_iterations
        self._enable_concurrent_tools = enable_concurrent_tools
        self._enable_interleaved_output = enable_interleaved_output

        # Prompt-specific message building for interleaved thinking mode
        self._build_prompt_messages = build_prompt_messages
        self._tool_schemas = tool_schemas or []
        self._skills = skills

        # Tool interrupt strategy
        self._interrupt_strategy = interrupt_strategy  # "immediate" | "semantic_complete" | "none"
        self._cancel_event: asyncio.Event | None = None
        self._interrupt_requested: bool = False

        # Card config map: trigger_tool → card_config for auto-generating cards
        self._card_config_map: dict[str, dict] = card_config_map or {}

        # Generic messages in standard OpenAI format (for context persistence)
        self._generic_messages: list[dict] = []
        self._initial_query: str | None = None
        self._first_llm_call_done = False
        self._current_round_tool_results: list[str] = []
        # Flag to ensure current query is appended to _generic_messages only once
        # (after build_messages() has consumed it, so history is empty on first turn)
        self._query_appended_to_context: bool = False

        # State machine for managing conversation flow
        self._state_machine = LLMStateMachine()

        # Message tracking
        self._messages: list[dict] = []  # Current LLM request messages
        self._iteration_count: int = 0

        # Current round tracking
        self._current_assistant_content: str = ''  # Current round assistant content
        self._has_current_round_tools: bool = False  # Whether current round had tools

        # Callback ID to tool_call_id mapping
        self._callback_to_tool: dict[str, str] = {}

        # Pending tool results cache (to maintain correct message order)
        # These are added to _generic_messages after assistant message
        self._pending_tool_results: list[dict] = []

        # Async executor reference (set externally)
        self._async_executor: Optional[FrameProcessor] = None

        # Tool completion tracking using Condition instead of Event
        # This fixes the race condition where tools complete before wait()
        # Condition + counter provides atomic check-and-wait semantics
        self._pending_tool_count: int = 0
        self._pending_tools_condition: asyncio.Condition = asyncio.Condition()

        # Error tracking (exposed to callers via has_error/get_error_message)
        self._error_occurred: bool = False
        self._error_message: str = ''

        # Post-tool LLM skip tracking (requires_llm field on tools)
        self._skip_post_tool_llm: bool = True      # Whether to skip LLM after current round of tools
        self._current_round_tool_errors: bool = False  # Whether any tool in this round errored

    # -------------------------------------------------------------------------
    # Tool completion waiting/notification methods
    # -------------------------------------------------------------------------

    async def _wait_for_tools_complete(self) -> None:
        """Atomically wait for all pending tools to complete.

        Uses Condition instead of Event to fix race condition where
        tools complete before wait() is called.
        """
        async with self._pending_tools_condition:
            while self._pending_tool_count > 0:
                await self._pending_tools_condition.wait()

    async def _notify_tool_complete(self) -> None:
        """Notify that one tool has completed and wake waiters if all done.

        Decrements the pending count and signals all waiters when count reaches 0.
        """
        async with self._pending_tools_condition:
            # Only decrement if count > 0 to prevent negative values
            if self._pending_tool_count > 0:
                self._pending_tool_count -= 1
            if self._pending_tool_count <= 0:
                self._pending_tools_condition.notify_all()

    async def _set_pending_tools(self, count: int) -> None:
        """Set the number of pending tools.

        Args:
            count: Number of tools that will be awaited.
        """
        async with self._pending_tools_condition:
            self._pending_tool_count = count

    def register_async_executor(self, executor: FrameProcessor) -> None:
        """Register the async executor for tool calls.

        Args:
            executor: The AsyncExecutorProcessor instance.
        """
        self._async_executor = executor

    def _extract_query_from_messages(self, messages: list[dict]) -> str:
        """Extract the user query from the initial messages.

        For interleaved thinking mode, the query is extracted from the
        JSON content of the user message.

        Args:
            messages: The initial messages list.

        Returns:
            The user query string.
        """
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'user':
                # Try to parse as JSON (interleaved thinking format)
                if content.startswith('{'):
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and 'user' in parsed:
                            return parsed.get('user', '')
                    except json.JSONDecodeError:
                        pass
                # Plain text user message
                return content
        return ''

    def _build_llm_request_messages(self) -> list[dict]:
        """Build messages for LLM request using prompt-specific builder.

        For interleaved thinking mode, this rebuilds the 2-message structure
        with current tool_ans results from parallel tool calls.

        Returns:
            Messages list for LLM request.
        """
        if self._build_prompt_messages is None:
            # Fallback: use stored messages
            logger.debug(f"No build_prompt_messages callback, using _messages: {len(self._messages)} items")
            return self._messages

        logger.debug(f"Building messages with callback: query='{self._initial_query}', history={len(self._generic_messages)} items, tool_schemas={len(self._tool_schemas)}, skills={len(self._skills) if self._skills else 0}")

        messages = self._build_prompt_messages(
            query=self._initial_query or '',
            history=list(self._generic_messages),
            tool_schemas=self._tool_schemas,
            skills=self._skills,
            tool_ans=self._current_round_tool_results if self._current_round_tool_results else [],
            user_context=self._context.user_context if self._context else {},
        )

        logger.debug(f"Built {len(messages)} messages via callback")
        logger.debug(f"Messages preview: {messages}")

        return messages

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process incoming frames.

        Args:
            frame: The frame to process.
            direction: Direction of frame flow.
        """
        await super().process_frame(frame, direction)

        try:
            if isinstance(frame, LLMMessagesAppendFrame):
                await self._handle_llm_call(frame)

            elif isinstance(frame, FunctionCallEndFrame):
                await self._handle_tool_result(frame, direction)

            elif isinstance(frame, TextFrame):
                # Stream text directly downstream
                await self.push_frame(frame, direction)

            else:
                # Forward other frames
                await self.push_frame(frame, direction)

        except InvalidStateTransition as e:
            logger.error(f"Invalid state transition: {e}")
            await self._handle_error(str(e), direction)

        except Exception as e:
            logger.exception(f"Error processing frame: {e}")
            await self._handle_error(str(e), direction)

    async def _handle_llm_call(self, frame: LLMMessagesAppendFrame) -> None:
        """Handle LLM call with tool calling support.

        Uses an iterative loop to handle multi-round tool calling.
        Each iteration: call LLM -> if tools detected, wait for completion -> continue.
        _handle_tool_result() only collects results and notifies the counter.

        Args:
            frame: The LLM messages append frame with query/history or messages.
        """
        # Initialize on first LLM call (outside loop, runs once)
        if not self._first_llm_call_done:
            self._first_llm_call_done = True
            self._initial_query = frame.query
            self._generic_messages = list(frame.history or [])
            logger.debug(f"Initialized with query: '{self._initial_query}', history: {len(frame.history or [])} items, base messages: {len(self._generic_messages)}")

        while self._iteration_count < self._max_iterations:
            self._iteration_count += 1

            # Reset cancel event for this LLM iteration
            self._cancel_event = asyncio.Event()
            self._interrupt_requested = False

            # Reset current round tracking (except tool_results, needed for message building)
            self._current_assistant_content = ''
            self._has_current_round_tools = False

            # Reset post-tool LLM skip flags for this round
            self._skip_post_tool_llm = True   # assume skip unless a tool requires LLM
            self._current_round_tool_errors = False

            # Build messages for LLM request (uses _current_round_tool_results from previous round)
            logger.debug(f"Building messages: build_prompt_messages={self._build_prompt_messages is not None}, frame.messages={len(frame.messages) if frame.messages else 0}")

            if self._build_prompt_messages:
                messages = self._build_llm_request_messages()
            elif frame.messages:
                messages = list(frame.messages)
            else:
                # Fallback: use generic_messages accumulated from query/history
                logger.info(f"Using generic_messages as fallback: {len(self._generic_messages)} items")
                messages = list(self._generic_messages)

            # Append current query to _generic_messages for context accumulation
            # AFTER messages have been built, so history is empty on the first turn
            # (enables first_turn layer strategy detection in build_messages_with_layers).
            if not self._query_appended_to_context and self._initial_query:
                self._generic_messages.append({
                    "role": "user",
                    "content": self._initial_query,
                })
                self._query_appended_to_context = True

            logger.debug(f"Built {len(messages)} messages for LLM request")

            # Reset tool results AFTER building messages
            self._current_round_tool_results = []

            self._messages = messages

            # Transition to calling state
            if not self._state_machine._state == State.LLM_CALLING:
                self._state_machine.transition_to(State.LLM_CALLING, "starting_llm_call")

            try:
                # Track tool calls sent during streaming (reset each iteration)
                streamed_tool_calls: list[dict] = []
                has_tools = False
                first_tool_sent = False

                async def on_tool_call(tool_call: dict) -> None:
                    """Callback to send tool_calls immediately when detected during streaming."""
                    nonlocal first_tool_sent, has_tools
                    streamed_tool_calls.append(tool_call)
                    has_tools = True
                    self._has_current_round_tools = True

                    func_name = tool_call["function_name"]
                    arguments = tool_call["arguments"]
                    tool_call_id = tool_call["tool_call_id"]
                    callback_id = f"tc_{tool_call_id}"

                    self._callback_to_tool[callback_id] = tool_call_id
                    self._state_machine.add_pending_tool(tool_call_id)

                    # Update pending tool count under Condition lock
                    async with self._pending_tools_condition:
                        self._pending_tool_count += 1

                    if not first_tool_sent:
                        first_tool_sent = True
                        self._state_machine.transition_to(
                            State.TOOL_EXECUTING,
                            f"first_tool_call_{tool_call_id}"
                        )

                    await self.push_frame(
                        FunctionCallInProgressFrame(
                            function_name=func_name,
                            tool_call_id=tool_call_id,
                            arguments=arguments,
                        ),
                        FrameDirection.DOWNSTREAM,
                    )

                    if self._async_executor:
                        await self._async_executor.process_frame(
                            AsyncFunctionCallFrame(
                                function_name=func_name,
                                tool_call_id=tool_call_id,
                                arguments=arguments,
                                callback_id=callback_id,
                                timeout_seconds=30.0,
                            ),
                            FrameDirection.DOWNSTREAM,
                        )
                    else:
                        logger.error("No async executor registered")
                        raise RuntimeError("Async executor not registered")

                # Call LLM with streaming
                tool_calls, text_content = await self._call_llm_stream(
                    messages,
                    on_tool_call=on_tool_call,
                )

                self._current_assistant_content = text_content or ''

                if has_tools:
                    # Tools dispatched during streaming
                    assistant_msg: dict = {"role": "assistant", "content": self._current_assistant_content}
                    if streamed_tool_calls:
                        assistant_msg["tool_calls"] = self._build_openai_tool_calls(streamed_tool_calls)
                    
                    # Add assistant message first
                    self._generic_messages.append(assistant_msg)
                    
                    # Then add all pending tool results (maintains correct order: assistant → tool results)
                    if self._pending_tool_results:
                        self._generic_messages.extend(self._pending_tool_results)
                        logger.debug(
                            f"Added {len(self._pending_tool_results)} cached tool results after assistant message"
                        )
                        self._pending_tool_results.clear()
                    
                    # Wait for all tools to complete, then loop for next LLM round
                    await self._wait_for_tools_complete()

                    # Flush tool results that arrived during the wait
                    if self._pending_tool_results:
                        self._generic_messages.extend(self._pending_tool_results)
                        logger.debug(
                            f"Added {len(self._pending_tool_results)} late-arriving tool results after wait"
                        )
                        self._pending_tool_results.clear()

                    # Check if all tools have requires_llm=False → skip post-tool LLM call
                    if self._skip_post_tool_llm:
                        logger.info(
                            "Skipping post-tool LLM call (has_tools path): "
                            "all tools have requires_llm=False"
                        )
                        await self.push_frame(LLMFullResponseEndFrame())
                        self._state_machine.transition_to(
                            State.COMPLETED, "all_tools_no_llm"
                        )
                        return

                    self._state_machine.transition_to(
                        State.LLM_CALLING, "tools_complete_streaming"
                    )
                    continue

                elif tool_calls:
                    # Fallback: tool_calls collected but not sent via callback
                    self._has_current_round_tools = True
                    assistant_msg = {"role": "assistant", "content": self._current_assistant_content}
                    if tool_calls:
                        assistant_msg["tool_calls"] = self._build_openai_tool_calls(tool_calls)
                    
                    # Add assistant message first
                    self._generic_messages.append(assistant_msg)
                    
                    # Then add all pending tool results
                    if self._pending_tool_results:
                        self._generic_messages.extend(self._pending_tool_results)
                        logger.debug(
                            f"Added {len(self._pending_tool_results)} cached tool results after assistant message (fallback)"
                        )
                        self._pending_tool_results.clear()
                    
                    self._state_machine.transition_to(
                        State.WAITING_FOR_TOOLS,
                        f"found_{len(tool_calls)}_tool_calls"
                    )
                    await self._send_async_tool_calls(
                        tool_calls, direction=FrameDirection.DOWNSTREAM
                    )
                    await self._wait_for_tools_complete()

                    # Flush tool results that arrived during the wait
                    if self._pending_tool_results:
                        self._generic_messages.extend(self._pending_tool_results)
                        logger.debug(
                            f"Added {len(self._pending_tool_results)} late-arriving tool results after wait (fallback)"
                        )
                        self._pending_tool_results.clear()

                    # Check if all tools have requires_llm=False → skip post-tool LLM call
                    if self._skip_post_tool_llm:
                        logger.info(
                            "Skipping post-tool LLM call (tool_calls path): "
                            "all tools have requires_llm=False"
                        )
                        await self.push_frame(LLMFullResponseEndFrame())
                        self._state_machine.transition_to(
                            State.COMPLETED, "all_tools_no_llm"
                        )
                        return

                    self._state_machine.transition_to(
                        State.LLM_CALLING, "tools_complete_fallback"
                    )
                    continue

                else:
                    # No tool calls - conversation complete
                    if self._current_assistant_content:
                        self._generic_messages.append({
                            "role": "assistant",
                            "content": self._current_assistant_content
                        })
                    await self.push_frame(LLMFullResponseEndFrame())
                    self._state_machine.transition_to(State.COMPLETED, "no_tool_calls")
                    return

            except Exception as e:
                logger.exception(f"Error in LLM call: {e}")
                self._error_occurred = True
                self._error_message = str(e)
                try:
                    self._state_machine.transition_to(State.ERROR, f"llm_error: {e}")
                except InvalidStateTransition:
                    try:
                        self._state_machine.transition_to(
                            State.COMPLETED, f"llm_error: {e}"
                        )
                    except InvalidStateTransition:
                        logger.warning(
                            f"Could not transition to ERROR or COMPLETED, "
                            f"current state: {self._state_machine.current_state}"
                        )
                await self.push_frame(LLMFullResponseEndFrame())
                return

        # While loop exhausted - max iterations reached
        logger.warning(f"Max iterations ({self._max_iterations}) reached")
        await self.push_frame(LLMFullResponseEndFrame())
        self._state_machine.transition_to(State.COMPLETED, "max_iterations")

    async def _send_async_tool_calls(
        self,
        tool_calls: list[dict],
        direction: FrameDirection,
    ) -> None:
        """Send async tool call frames.

        Args:
            tool_calls: List of tool call dicts.
            direction: Direction for frames.
        """
        # Transition to executing state BEFORE sending any calls
        # to avoid race condition where tool completes before transition
        self._state_machine.transition_to(
            State.TOOL_EXECUTING,
            f"sending_{len(tool_calls)}_async_calls"
        )

        # Send in-progress frames and start async execution for all tools
        for tc in tool_calls:
            func_name = tc["function_name"]
            arguments = tc["arguments"]
            tool_call_id = tc["tool_call_id"]
            callback_id = f"tc_{tool_call_id}"

            # Track callback mapping
            self._callback_to_tool[callback_id] = tool_call_id

            # Add to state machine
            self._state_machine.add_pending_tool(tool_call_id)

            # Update pending tool count under Condition lock
            async with self._pending_tools_condition:
                self._pending_tool_count += 1

            # Send in-progress frame downstream
            await self.push_frame(
                FunctionCallInProgressFrame(
                    function_name=func_name,
                    tool_call_id=tool_call_id,
                    arguments=arguments,
                ),
                direction,
            )

            # Send async call frame to executor
            if self._async_executor:
                await self._async_executor.process_frame(
                    AsyncFunctionCallFrame(
                        function_name=func_name,
                        tool_call_id=tool_call_id,
                        arguments=arguments,
                        callback_id=callback_id,
                        timeout_seconds=30.0,
                    ),
                    direction,
                )
            else:
                logger.error("No async executor registered")
                raise RuntimeError("Async executor not registered")

    async def _handle_tool_result(
        self,
        frame: FunctionCallEndFrame,
        direction: FrameDirection,
    ) -> None:
        """Handle tool execution result callback.

        Args:
            frame: The function call end frame.
            direction: Direction for frames.
        """
        callback_id = frame.callback_id
        tool_call_id = self._callback_to_tool.get(callback_id, frame.tool_call_id)

        # Update state machine
        if frame.status == "success":
            all_completed = self._state_machine.complete_tool(tool_call_id)
        elif frame.status in ("error", "timeout"):
            all_completed = self._state_machine.fail_tool(
                tool_call_id, frame.error_message
            )
            self._current_round_tool_errors = True
            self._skip_post_tool_llm = False  # Let LLM handle the error
        else:  # cancelled
            all_completed = self._state_machine.cancel_tool(tool_call_id)

        # Extract result content
        result_content = (
            frame.result if frame.status == "success" and isinstance(frame.result, str)
            else frame.error_message if frame.status != "success"
            else str(frame.result) if frame.result is not None
            else ""
        )

        # Append to current round tool results (for tool_ans in next LLM call)
        self._current_round_tool_results.append(result_content)

        # Cache tool result message (will be added after assistant message to maintain correct order)
        # Include 'name' field for Gemini API compatibility
        tool_result_msg = {
            "role": "tool",
            "name": frame.function_name,
            "tool_call_id": tool_call_id,
            "content": result_content,
        }
        self._pending_tool_results.append(tool_result_msg)

        logger.debug(
            f"Tool result for {tool_call_id}: status={frame.status}, "
            f"all_completed={all_completed}, "
            f"_pending_tool_count={self._pending_tool_count}"
        )

        # Push result frame downstream for every tool completion
        await self.push_frame(
            FunctionCallResultFrame(
                function_name=frame.function_name,
                tool_call_id=tool_call_id,
                arguments=None,
                result=result_content,
                status=frame.status,
                error_message=frame.error_message,
            ),
            FrameDirection.DOWNSTREAM,
        )

        # Trigger interrupt based on strategy
        if self._interrupt_strategy == "immediate":
            # Set flag - will be checked in streaming loop after current chunk
            logger.info(
                "Tool %s completed, will cancel after current token (immediate)",
                tool_call_id,
            )
            self._interrupt_requested = True
        elif self._interrupt_strategy == "semantic_complete":
            # Check if all tools are complete
            if self._pending_tool_count == 0:
                logger.info(
                    "All tools completed, will cancel LLM stream (semantic_complete)"
                )
                self._interrupt_requested = True
            else:
                logger.debug(
                    f"Tool {tool_call_id} completed, {self._pending_tool_count} tools still pending"
                )
        # "none" strategy: do nothing

        # Check for card result annotation in tool output.
        # Any tool returning a result with _type="card_result" is routed
        # to CardDataFrame for frontend rendering, bypassing LLM context.
        if frame.status == "success":
            try:
                parsed = json.loads(result_content)
                if isinstance(parsed, dict) and parsed.get("_type") == "card_result":
                    card_data = parsed.get("card_data", {})
                    if card_data:
                        await self.push_frame(
                            CardDataFrame(cards=[card_data]),
                            FrameDirection.DOWNSTREAM,
                        )
                        # Replace result with lightweight acknowledgment
                        result_content = json.dumps({
                            "card_type": card_data.get('card_type', 'unknown'),
                            "status": "generated",
                        })
                        tool_result_msg["content"] = result_content
            except (json.JSONDecodeError, TypeError):
                pass

        # Check if this tool requires LLM post-execution.
        # When a tool has requires_llm=True (the default), the LLM should be
        # called again after this round of tools completes. We only skip if
        # ALL tools in this round have requires_llm=False.
        if frame.status == "success" and self._skip_post_tool_llm:
            try:
                tenant_id = self._context.tenant_id if self._context else None
                tool_instance = ToolRegistry.get_tool(frame.function_name, tenant_id)
                if tool_instance is None:
                    # Tool not in registry → can't determine, default to requires LLM
                    self._skip_post_tool_llm = False
                elif tool_instance.requires_llm:
                    self._skip_post_tool_llm = False
            except Exception:
                self._skip_post_tool_llm = False  # If lookup fails, err on side of LLM

        # Notify counter decrement (may wake _wait_for_tools_complete)
        await self._notify_tool_complete()

    async def _call_llm_stream(
        self,
        messages: list[dict],
        on_tool_call: Callable[[dict], Awaitable[None]] | None = None,
    ) -> tuple[list[dict], str]:
        """Call LLM with streaming.

        When content_extractor and output_mapper are provided, content is
        parsed and pushed as typed frames (ThinkFrame/TextFrame), and
        tool_calls embedded in content are collected and returned.

        When on_tool_call is provided, detected tool_calls are sent immediately
        via the callback instead of being collected and returned.

        Args:
            messages: List of message dicts.
            on_tool_call: Optional async callback to send tool_calls immediately
                when detected during streaming.

        Returns:
            Tuple of (tool_calls list, accumulated text content).
            If on_tool_call is provided, tool_calls list will be empty
            as they are sent immediately via callback.
        """
        # Reset extractor/mapper state for this round
        if self._content_extractor:
            self._content_extractor.reset()
        if self._output_mapper:
            self._output_mapper.reset()

        # Record start time and tokens for LLM trace
        call_start_time = time.time()
        first_chunk_time: Optional[float] = None
        chunk_count: int = 0
        start_prompt_tokens = self._context.prompt_tokens if self._context else 0
        start_completion_tokens = self._context.completion_tokens if self._context else 0
        start_cached_tokens = self._context.cached_tokens if self._context else 0

        # Add LLM start trace
        llm_id = None
        if self._context:
            llm_id, _ = self._context.add_llm_start(
                model=self._llm_provider.get_model_name(),
                provider=self._llm_provider.get_provider_type(),
            )
            # Push LLMStartFrame downstream
            await self.push_frame(
                LLMStartFrame(
                    llm_id=llm_id,
                    model=self._llm_provider.get_model_name(),
                    provider=self._llm_provider.get_provider_type(),
                ),
                FrameDirection.DOWNSTREAM,
            )

        provider_config = getattr(self._llm_provider, "config", {}) or {}

        call_kwargs = {**provider_config}
        if self._tools_payload:
            call_kwargs["tools"] = self._tools_payload

        # Pass cancel_event to provider
        call_kwargs["cancel_event"] = self._cancel_event

        stream = await self._llm_provider.chat(
            messages=messages,
            stream=True,
            **call_kwargs,
        )

        text_parts: list[str] = []
        collected_tool_calls: list[dict] = []
        content_tool_calls: list[dict] = []
        sent_tool_call_ids: set[str] = set()  # Track already sent tool_calls
        # Buffer for accumulating tool_call arguments across streaming chunks
        # vLLM/OAI splits function arguments into multiple delta chunks
        tool_call_buffers: dict[int, dict] = {}

        async for chunk in stream:
            chunk_ts = time.time()

            if not isinstance(chunk, dict):
                # Raw text chunk
                text = str(chunk)
                if text:
                    if first_chunk_time is None:
                        first_chunk_time = chunk_ts
                    chunk_count += 1
                    text_parts.append(text)
                    await self._process_content_chunk(text, content_tool_calls, on_tool_call)
                
                # Check for tool-triggered interrupt after processing chunk
                if self._interrupt_requested and self._cancel_event and not self._cancel_event.is_set():
                    if self._interrupt_strategy in ("immediate", "semantic_complete"):
                        logger.info("Tool result received, cancelling LLM stream after current chunk")
                        self._cancel_event.set()
                        break
                continue

            chunk_type = chunk.get("type", "")

            if chunk_type == "content":
                if first_chunk_time is None:
                    first_chunk_time = chunk_ts
                chunk_count += 1
                text = chunk.get("content", "")
                if text:
                    text_parts.append(text)
                    await self._process_content_chunk(text, content_tool_calls, on_tool_call)

                # Track token usage
                if self._context:
                    usage = chunk.get("usage", {})
                    if usage:
                        self._context.prompt_tokens += usage.get("prompt_tokens", 0)
                        self._context.completion_tokens += usage.get("completion_tokens", 0)
                        chunk_cached = (
                            usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
                            or usage.get('promptTokensDetails', {}).get('cachedInputTokenCount', 0)
                            or 0
                        )
                        if chunk_cached:
                            self._context.cached_tokens += chunk_cached

                # Check for tool-triggered interrupt after processing chunk
                if self._interrupt_requested and self._cancel_event and not self._cancel_event.is_set():
                    if self._interrupt_strategy in ("immediate", "semantic_complete"):
                        logger.info("Tool result received, cancelling LLM stream after current chunk")
                        self._cancel_event.set()
                        break

            elif chunk_type == "reasoning_content":
                text = chunk.get("content", "")
                if text:
                    await self.push_frame(ThinkFrame(text=text))

            elif chunk_type == "tool_calls":
                # Aggregated tool_calls chunk
                functions = chunk.get("functions", [])
                arguments_list = chunk.get("arguments", [])
                tool_ids = chunk.get("tool_ids", [])

                for func_name, args_str, tool_id in zip(functions, arguments_list, tool_ids):
                    # Skip if already sent
                    if tool_id in sent_tool_call_ids:
                        continue
                    sent_tool_call_ids.add(tool_id)

                    try:
                        arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        arguments = {"raw": args_str}

                    tool_call = {
                        "function_name": func_name,
                        "arguments": arguments,
                        "tool_call_id": tool_id,
                    }

                    if on_tool_call:
                        # Send immediately via callback
                        await on_tool_call(tool_call)
                    else:
                        collected_tool_calls.append(tool_call)

            elif chunk_type == "tool_calls_delta":
                # Accumulate tool_call arguments across streaming chunks.
                # vLLM/OAI streaming splits function arguments into multiple
                # delta chunks (e.g. {"arguments":"{\"query\":"},
                # {"arguments":"\"test\""}). We buffer per tool index and
                # only dispatch at stream end.
                for tc in chunk.get("tool_calls", []):
                    idx = tc.get("index", 0)
                    func_info = tc.get("function", {})
                    func_name = func_info.get("name", "")
                    args_fragment = func_info.get("arguments", "")
                    tool_id = tc.get("id", "")

                    # Initialize buffer on first sight of this tool index
                    if idx not in tool_call_buffers:
                        tool_call_buffers[idx] = {
                            "id": tool_id or "",
                            "name": func_name or "",
                            "arguments": "",
                        }
                    # Update fields if provided in this chunk
                    if tool_id:
                        tool_call_buffers[idx]["id"] = tool_id
                    if func_name:
                        tool_call_buffers[idx]["name"] = func_name
                    # Accumulate arguments fragment
                    if args_fragment:
                        tool_call_buffers[idx]["arguments"] += args_fragment

            elif chunk_type == "usage":
                # Handle usage-only chunk (final streaming chunk with token stats)
                usage = chunk.get("usage", {})
                if usage and self._context:
                    self._context.prompt_tokens += usage.get("prompt_tokens", 0)
                    self._context.completion_tokens += usage.get("completion_tokens", 0)
                    chunk_cached = (
                        usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
                        or usage.get('promptTokensDetails', {}).get('cachedInputTokenCount', 0)
                        or 0
                    )
                    if chunk_cached:
                        self._context.cached_tokens += chunk_cached

            elif chunk_type == "done":
                break

        # Flush accumulated tool calls from tool_calls_delta chunks.
        # Arguments have been accumulated across all delta chunks; now parse
        # the complete JSON and dispatch.
        if tool_call_buffers:
            for idx in sorted(tool_call_buffers.keys()):
                buf = tool_call_buffers[idx]
                if not buf["name"]:
                    continue
                tool_id = buf["id"] or f"tc_{uuid.uuid4().hex[:8]}"
                if tool_id in sent_tool_call_ids:
                    continue
                sent_tool_call_ids.add(tool_id)

                args_str = buf["arguments"] or "{}"
                try:
                    arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    arguments = {"raw": args_str}

                tool_call = {
                    "function_name": buf["name"],
                    "arguments": arguments,
                    "tool_call_id": tool_id,
                }

                if on_tool_call:
                    await on_tool_call(tool_call)
                else:
                    collected_tool_calls.append(tool_call)
            tool_call_buffers.clear()

        # Flush extractor buffer at stream end
        if self._content_extractor and self._output_mapper:
            for res_chunk in self._content_extractor.flush_stream():
                out = self._output_mapper.map_stream(res_chunk)
                if out is not None:
                    await self._handle_mapped_output(out, content_tool_calls, on_tool_call)

        # Process content-parsed tool_calls via callback (if not already sent via on_tool_call)
        # This ensures has_tools is set to True for non-streaming responses
        if on_tool_call and content_tool_calls:
            for tc in content_tool_calls:
                await on_tool_call(tc)

        # Calculate duration and add LLM end trace
        call_duration = (time.time() - call_start_time) * 1000  # Convert to ms

        # Calculate TTFT and TPOT
        ttft_ms = ((first_chunk_time - call_start_time) * 1000
                   if first_chunk_time is not None else 0.0)
        gen_time = max(0, call_duration - ttft_ms)
        tpot_ms = 0.0

        if self._context and llm_id:
            # Calculate delta tokens for this LLM call
            current_prompt_tokens = self._context.prompt_tokens
            current_completion_tokens = self._context.completion_tokens
            current_cached_tokens = self._context.cached_tokens

            # Delta tokens = current - start (handles multi-round accumulation)
            delta_prompt_tokens = max(0, current_prompt_tokens - start_prompt_tokens)
            delta_completion_tokens = max(0, current_completion_tokens - start_completion_tokens)
            delta_cached_tokens = max(0, current_cached_tokens - start_cached_tokens)

            # TPOT = generation time per output token
            tpot_ms = (gen_time / max(1, delta_completion_tokens - 1)
                       if delta_completion_tokens > 1 else gen_time if delta_completion_tokens == 1 else 0.0)

            self._context.add_llm_end(
                llm_id=llm_id,
                duration_ms=call_duration,
                prompt_tokens=delta_prompt_tokens,
                completion_tokens=delta_completion_tokens,
                cached_tokens=delta_cached_tokens,
                ttft_ms=ttft_ms,
                chunk_count=chunk_count,
                tpot_ms=tpot_ms,
            )
            # Push LLMEndFrame downstream
            await self.push_frame(
                LLMEndFrame(
                    llm_id=llm_id,
                    duration_ms=call_duration,
                    prompt_tokens=delta_prompt_tokens,
                    completion_tokens=delta_completion_tokens,
                    total_tokens=delta_prompt_tokens + delta_completion_tokens,
                    cached_tokens=delta_cached_tokens,
                    ttft_ms=ttft_ms,
                    chunk_count=chunk_count,
                    tpot_ms=tpot_ms,
                ),
                FrameDirection.DOWNSTREAM,
            )

        # Combine API tool_calls with content-parsed tool_calls
        # Note: content_tool_calls are already sent via on_tool_call above
        return collected_tool_calls, "".join(text_parts)

    async def _process_content_chunk(
        self,
        text: str,
        content_tool_calls: list[dict],
        on_tool_call: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        """Process a content chunk through extractor/mapper or push directly.

        Args:
            text: The content text chunk.
            content_tool_calls: List to append parsed tool_calls to.
            on_tool_call: Optional callback to send tool_calls immediately.
        """
        if self._content_extractor and self._output_mapper:
            # Parse through extractor → mapper → typed frames
            for res_chunk in self._content_extractor.extract_stream(text):
                out = self._output_mapper.map_stream(res_chunk)
                if out is not None:
                    await self._handle_mapped_output(out, content_tool_calls, on_tool_call)
        else:
            # No parser: push all content as TextFrame (legacy behavior)
            await self.push_frame(TextFrame(text=text))

    async def _handle_mapped_output(
        self,
        out,  # LLMOutputChunk
        content_tool_calls: list[dict],
        on_tool_call: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        """Handle a mapped output chunk - push frame or collect tool_call.

        Args:
            out: LLMOutputChunk from mapper.
            content_tool_calls: List to append parsed tool_calls to.
            on_tool_call: Optional callback to send tool_calls immediately.
        """
        if out.type == 'answer':
            if self._enable_interleaved_output:
                await self.push_frame(TextFrame(text=out.content))
            # When enable_interleaved_output=False, answer content is
            # silently accumulated into _current_assistant_content by
            # the extractor and not pushed as intermediate frames.
        elif out.type == 'think':
            await self.push_frame(ThinkFrame(text=out.content))
        elif out.type == 'tool' and out.is_complete:
            # Content-based tool_call: convert to standard format
            tool_obj = out.content  # dict: {"name": ..., "arguments": ...}
            if isinstance(tool_obj, dict):
                name = tool_obj.get('name', '')
                args = tool_obj.get('arguments') or tool_obj.get('parameters', {})

                # Check for duplicate tool_call based on name + arguments
                args_str = json.dumps(args, sort_keys=True) if isinstance(args, dict) else str(args)
                tool_signature = f"{name}:{args_str}"

                # Skip if already exists
                for existing in content_tool_calls:
                    existing_args_str = json.dumps(existing.get('arguments', {}), sort_keys=True)
                    if existing.get('function_name') == name and existing_args_str == args_str:
                        return  # Duplicate found, skip

                # Use uuid to ensure unique tool_call_id even after state reset
                tool_call_id = f'content_tool_{uuid.uuid4().hex[:8]}'

                tool_call = {
                    'function_name': name,
                    'arguments': args if isinstance(args, dict) else {},
                    'tool_call_id': tool_call_id,
                }

                # Send immediately if callback provided, otherwise collect
                if on_tool_call:
                    await on_tool_call(tool_call)
                else:
                    content_tool_calls.append(tool_call)

    async def _handle_error(self, error_message: str, direction: FrameDirection) -> None:
        """Handle error state.

        Args:
            error_message: The error message.
            direction: Direction for frames.
        """
        try:
            self._state_machine.transition_to(State.ERROR, error_message)
        except InvalidStateTransition:
            pass  # Already in error state

        # Send end frame to signal completion
        await self.push_frame(LLMFullResponseEndFrame())

    @staticmethod
    def _build_openai_tool_calls(internal_tool_calls: list[dict]) -> list[dict]:
        """Convert internal tool_call format to OpenAI API format.

        Internal format: ``{"function_name", "arguments", "tool_call_id"}``
        OpenAI format: ``{"id", "type", "function": {"name", "arguments"}}``

        Args:
            internal_tool_calls: List of tool calls in internal format.

        Returns:
            List of tool calls in OpenAI API format.
        """
        result = []
        for tc in internal_tool_calls:
            args = tc.get("arguments", {})
            if isinstance(args, dict):
                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = str(args)

            result.append({
                "id": tc.get("tool_call_id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("function_name", ""),
                    "arguments": args_str,
                }
            })
        return result

    def get_context_messages(self) -> list[dict]:
        """Return the messages list for context persistence.

        Returns generic format messages that can be directly stored in SessionContext.

        Returns:
            List of messages in generic format.
        """
        return list(self._generic_messages)

    def has_error(self) -> bool:
        """Whether an error occurred during LLM processing."""
        return self._error_occurred

    def get_error_message(self) -> str:
        """Return the error message if an error occurred."""
        return self._error_message

    def get_state_info(self) -> dict:
        """Get current state information.

        Returns:
            Dict with state machine info.
        """
        return self._state_machine.get_state_info()

    def reset(self) -> None:
        """Reset the processor state."""
        self._state_machine.reset()
        self._messages = []
        self._generic_messages = []
        self._iteration_count = 0
        self._callback_to_tool.clear()
        # Reset pending tool count (Condition does not need explicit reset)
        self._pending_tool_count = 0
        self._pending_tool_results = []
        if self._content_extractor:
            self._content_extractor.reset()
        if self._output_mapper:
            self._output_mapper.reset()
        # Reset interleaved thinking state
        self._initial_query = None
        self._first_llm_call_done = False
        self._current_round_tool_results = []
        self._current_assistant_content = ''
        self._has_current_round_tools = False

        # Reset post-tool LLM skip flags
        self._skip_post_tool_llm = True
        self._current_round_tool_errors = False
