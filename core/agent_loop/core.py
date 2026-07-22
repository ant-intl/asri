"""
Framework-agnostic Agent Loop Core with streaming tool dispatch.

Shared between Django's FullDuplexLLMProcessor (async) and
Voice's OpenApiModelHandler (sync, bridged via asyncio).

Key feature: STREAMING tool execution.
  Tool calls are dispatched as soon as their arguments form valid JSON
  during LLM streaming, NOT after the stream ends. This matches Django's
  "full-duplex" behavior where LLM continues generating while tools
  already execute in parallel.

Usage:
    from core.agent_loop import AgentLoopCore, StreamChunk, TextChunk, ToolResult

    loop = AgentLoopCore(
        llm_streamer=my_llm_streamer,
        tool_executor=my_tool_executor,
        max_iterations=10,
    )
    async for event in loop.run(messages, tools):
        if isinstance(event, TextChunk):
            handle_text(event.text)
        elif isinstance(event, ToolResult):
            handle_result(event)
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional, Union

logger = logging.getLogger(__name__)


# =====================================================================
# Events -- what the loop yields to callers
# =====================================================================


@dataclass
class TextChunk:
    """LLM output text fragment."""
    text: str


@dataclass
class ReasoningChunk:
    """LLM reasoning/thinking content fragment."""
    text: str


@dataclass
class ToolCallStarted:
    """First tool_call delta arrived -- callers should flush buffered text."""
    pass


@dataclass
class ToolCallDispatched:
    """A tool call was dispatched for execution (streaming, not yet finished)."""
    name: str
    call_id: str


@dataclass
class ToolCallReady:
    """A complete tool call detected (used internally)."""
    name: str
    arguments: dict
    call_id: str


@dataclass
class ToolResult:
    """Tool execution completed."""
    name: str
    call_id: str
    result: str
    status: str = "success"  # success | error | cancelled


@dataclass
class IterationMetrics:
    """Metrics for one iteration of the agent loop."""
    iteration: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ttft_ms: float = 0.0
    duration_ms: float = 0.0
    tool_calls: list = field(default_factory=list)
    cancelled: bool = False


@dataclass
class Error:
    """An error occurred during the agent loop."""
    message: str


# Union type for type hints
AgentEvent = Union[
    TextChunk,
    ReasoningChunk,
    ToolCallStarted,
    ToolCallDispatched,
    ToolResult,
    IterationMetrics,
    Error,
]


# =====================================================================
# LLM Stream Chunk -- what llm_streamer yields
# =====================================================================


@dataclass
class StreamChunk:
    """Normalized LLM streaming chunk.

    Each llm_streamer implementation normalizes its raw chunks into this format.
    Only one field is set per chunk.

    Attributes:
        text: Content text delta.
        reasoning: Reasoning/thinking text delta.
        tool_call_delta: Tool call delta in OpenAI format:
            {"index": int, "id": str, "function": {"name": str, "arguments": str}}
        usage: Token usage info:
            {"prompt_tokens": int, "completion_tokens": int, ...}
    """
    text: str = ""
    reasoning: str = ""
    tool_call_delta: Optional[dict] = None
    usage: Optional[dict] = None


# =====================================================================
# AgentLoopCore
# =====================================================================


class AgentLoopCore:
    """Multi-round LLM + streaming Tool execution loop.

    Supports FULL-DUPLEX: tool calls are dispatched during LLM streaming
    as soon as their arguments form valid JSON, allowing tool execution
    to overlap with ongoing LLM generation.

    Args:
        llm_streamer: async callable(messages, tools, **kwargs) -> AsyncGenerator[StreamChunk]
            Each call does ONE LLM streaming request and yields normalized chunks.
        tool_executor: callable(name, arguments_json_str) -> str
            Executes a tool synchronously, returns result string.
        max_iterations: Maximum tool-call rounds (default 10).
        is_cancelled: Optional callable() -> bool. Checked between stream chunks
            and before tool execution. Return True to abort.
        streaming_tools: bool (default True). When True, tool calls are dispatched
            during LLM streaming as soon as arguments are valid JSON.
            When False, all tool calls are collected and executed after stream ends
            (matches Voice's original behavior).

    Example timeline for one iteration (streaming_tools=True)::

        LLM:    [text][text][tc_delta][tc_delta][tc_delta][text][done]
                                     |                        |
        Tool:                   [dispatch]---->[result]        |
                                     |            |            |
        Events: TextChunk TextChunk ToolCallStarted
                               ToolCallDispatched ToolResult IterationMetrics
    """

    def __init__(
        self,
        llm_streamer: Callable[..., AsyncGenerator[StreamChunk, None]],
        tool_executor: Callable[[str, str], str],
        max_iterations: int = 10,
        is_cancelled: Optional[Callable[[], bool]] = None,
        streaming_tools: bool = True,
    ):
        self._llm_streamer = llm_streamer
        self._tool_executor = tool_executor
        self._max_iterations = max_iterations
        self._is_cancelled = is_cancelled or (lambda: False)
        self._streaming_tools = streaming_tools

    async def run(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        **llm_kwargs: Any,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute the agent loop with streaming tool dispatch.

        Args:
            messages: OpenAI-format messages list. A shallow copy is made
                internally; assistant and tool messages are appended across
                iterations without mutating the caller's list.
            tools: OpenAI-format tool definitions.
            **llm_kwargs: Extra kwargs forwarded to llm_streamer
                (e.g. model, temperature).

        Yields:
            AgentEvent instances (TextChunk, ToolCallStarted, ToolCallDispatched,
            ToolResult, IterationMetrics, Error, ReasoningChunk).
        """
        # Shallow copy to avoid mutating caller's list
        messages = list(messages)

        for iteration in range(self._max_iterations):
            iter_start = time.perf_counter()
            ttft_ms = 0.0
            prompt_tokens = 0
            completion_tokens = 0
            cancelled = False
            text_content = ""

            # Tool call accumulation + streaming dispatch tracking
            tool_buffers: dict[int, dict] = {}  # index -> {id, name, arguments}
            dispatched: dict[int, asyncio.Task] = {}  # index -> running task
            first_tool_delta_seen = False

            # ----- 1. LLM streaming + concurrent tool dispatch -----
            try:
                async for chunk in self._llm_streamer(messages, tools, **llm_kwargs):
                    if self._is_cancelled():
                        cancelled = True
                        # Cancel any in-flight tool tasks
                        for task in dispatched.values():
                            task.cancel()
                        break

                    # Handle text content
                    if chunk.text:
                        if ttft_ms == 0.0:
                            ttft_ms = (time.perf_counter() - iter_start) * 1000
                        text_content += chunk.text
                        yield TextChunk(text=chunk.text)

                    # Handle reasoning/thinking content
                    if chunk.reasoning:
                        yield ReasoningChunk(text=chunk.reasoning)

                    # Handle tool call deltas
                    if chunk.tool_call_delta:
                        if not first_tool_delta_seen:
                            first_tool_delta_seen = True
                            yield ToolCallStarted()

                        self._accumulate_tool_delta(chunk.tool_call_delta, tool_buffers)

                        # STREAMING DISPATCH: check if any tool call has
                        # complete arguments (valid JSON) and hasn't been
                        # dispatched yet
                        if self._streaming_tools:
                            for idx, buf in tool_buffers.items():
                                if idx in dispatched:
                                    continue  # already dispatched
                                tc = self._try_parse_tool(buf)
                                if tc is not None:
                                    task = asyncio.create_task(
                                        self._run_single_tool(tc)
                                    )
                                    dispatched[idx] = task
                                    yield ToolCallDispatched(
                                        name=tc.name, call_id=tc.call_id
                                    )

                    # Handle usage info
                    if chunk.usage:
                        prompt_tokens = chunk.usage.get("prompt_tokens", 0) or prompt_tokens
                        completion_tokens = chunk.usage.get("completion_tokens", 0) or completion_tokens

            except Exception as exc:
                logger.exception("AgentLoopCore: LLM stream error: %s", exc)
                yield Error(message=str(exc))
                return

            # ----- 2. Flush remaining tool calls (not dispatched during stream) -----
            remaining_tools: list[tuple[int, ToolCallReady]] = []
            for idx in sorted(tool_buffers.keys()):
                if idx in dispatched:
                    continue  # already running
                tc = self._try_parse_tool(tool_buffers[idx])
                if tc is not None:
                    remaining_tools.append((idx, tc))
                else:
                    # Arguments never became valid JSON - log warning
                    buf = tool_buffers[idx]
                    if buf.get("name"):
                        logger.warning(
                            "Tool %s arguments never formed valid JSON: %r",
                            buf["name"],
                            buf.get("arguments", "")[:200],
                        )

            if remaining_tools and not cancelled:
                for idx, tc in remaining_tools:
                    task = asyncio.create_task(self._run_single_tool(tc))
                    dispatched[idx] = task
                    yield ToolCallDispatched(name=tc.name, call_id=tc.call_id)

            # ----- 3. Wait for all dispatched tools -----
            all_tool_results: list[ToolResult] = []
            if dispatched and not cancelled:
                for idx in sorted(dispatched.keys()):
                    task = dispatched[idx]
                    try:
                        result = await task
                        all_tool_results.append(result)
                    except asyncio.CancelledError:
                        buf = tool_buffers.get(idx, {})
                        all_tool_results.append(ToolResult(
                            name=buf.get("name", ""),
                            call_id=buf.get("id", ""),
                            result="",
                            status="cancelled",
                        ))

            if cancelled:
                yield IterationMetrics(
                    iteration=iteration,
                    cancelled=True,
                    ttft_ms=ttft_ms,
                    duration_ms=(time.perf_counter() - iter_start) * 1000,
                )
                return

            # ----- 4. Build assistant message + tool messages for history -----
            # Collect all tool calls (dispatched + remaining)
            all_tool_calls: list[ToolCallReady] = []
            for idx in sorted(tool_buffers.keys()):
                tc = self._try_parse_tool(tool_buffers[idx])
                if tc is not None:
                    all_tool_calls.append(tc)

            assistant_msg: dict = {"role": "assistant", "content": text_content or ""}
            if all_tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in all_tool_calls
                ]
            messages.append(assistant_msg)

            # ----- 5. No tools? Done. -----
            if not all_tool_calls:
                yield IterationMetrics(
                    iteration=iteration,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    ttft_ms=ttft_ms,
                    duration_ms=(time.perf_counter() - iter_start) * 1000,
                )
                return

            # Append tool results to messages and yield them
            for result in all_tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "content": result.result,
                    "name": result.name,
                })
                yield result

            yield IterationMetrics(
                iteration=iteration,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                ttft_ms=ttft_ms,
                duration_ms=(time.perf_counter() - iter_start) * 1000,
                tool_calls=[
                    {"name": tc.name, "call_id": tc.call_id}
                    for tc in all_tool_calls
                ],
            )

            # Continue to next iteration (LLM sees tool results)

        # Max iterations exhausted
        logger.warning(
            "AgentLoopCore: max iterations (%d) reached", self._max_iterations
        )

    # -----------------------------------------------------------------
    # Tool call delta accumulation
    # -----------------------------------------------------------------

    @staticmethod
    def _accumulate_tool_delta(delta: dict, buffers: dict[int, dict]) -> None:
        """Accumulate streaming tool_call deltas into per-index buffers.

        Both Django's tool_calls_delta chunks and Voice's delta.tool_calls
        use the same OpenAI format: {"index", "id", "function": {"name", "arguments"}}.

        Args:
            delta: A single tool_call delta from the LLM stream.
            buffers: Per-index accumulation buffers (mutated in place).
        """
        idx = delta.get("index", 0)
        if idx not in buffers:
            buffers[idx] = {"id": "", "name": "", "arguments": ""}
        buf = buffers[idx]
        if delta.get("id"):
            buf["id"] = delta["id"]
        fn = delta.get("function", {})
        if fn.get("name"):
            buf["name"] += fn["name"]
        if fn.get("arguments"):
            buf["arguments"] += fn["arguments"]

    @staticmethod
    def _try_parse_tool(buf: dict) -> Optional[ToolCallReady]:
        """Try to parse a tool buffer into a complete ToolCallReady.

        Returns None if the buffer doesn't have a valid name + parseable args.
        For streaming dispatch: returns None to wait for more deltas.
        For final flush: also returns None if args are invalid.

        Args:
            buf: Tool buffer with {"id", "name", "arguments"} keys.

        Returns:
            ToolCallReady if valid, None otherwise.
        """
        if not buf.get("name"):
            return None
        args_str = buf.get("arguments", "") or "{}"
        try:
            arguments = json.loads(args_str)
        except (json.JSONDecodeError, TypeError):
            # Not yet complete (streaming) or genuinely invalid
            return None
        return ToolCallReady(
            name=buf["name"],
            arguments=arguments,
            call_id=buf.get("id") or f"tc_{uuid.uuid4().hex[:8]}",
        )

    # -----------------------------------------------------------------
    # Tool execution
    # -----------------------------------------------------------------

    async def _run_single_tool(self, tc: ToolCallReady) -> ToolResult:
        """Execute a single tool, handling errors gracefully.

        Args:
            tc: The tool call to execute.

        Returns:
            ToolResult with the execution outcome.
        """
        if self._is_cancelled():
            return ToolResult(
                name=tc.name, call_id=tc.call_id, result="", status="cancelled"
            )
        try:
            args_str = json.dumps(tc.arguments, ensure_ascii=False)
            # Run sync tool_executor in thread to not block event loop
            result = await asyncio.to_thread(self._tool_executor, tc.name, args_str)
            logger.info("Tool %s (call_id=%s) completed", tc.name, tc.call_id)
            return ToolResult(
                name=tc.name, call_id=tc.call_id, result=str(result)
            )
        except Exception as exc:
            logger.exception(
                "Tool %s (call_id=%s) failed: %s", tc.name, tc.call_id, exc
            )
            return ToolResult(
                name=tc.name,
                call_id=tc.call_id,
                result=f"Error executing tool '{tc.name}': {exc}",
                status="error",
            )
