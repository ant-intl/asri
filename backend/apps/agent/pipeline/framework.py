"""
Lightweight pipeline framework for Pipeline Agent.

Provides Frame-based processor chain abstractions inspired by pipecat-ai,
without the heavy dependency tree (numba, numpy, nltk, Pillow, etc.).
Only implements the minimal subset required by ASRI's ChatAgent.
"""
import itertools
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

# Auto-incrementing ID generator for frames
_frame_id_counter = itertools.count()


# =============================================================================
# FrameDirection
# =============================================================================

class FrameDirection(Enum):
    """Direction of frame flow through the processor chain."""
    DOWNSTREAM = 1
    UPSTREAM = 2


# =============================================================================
# Frame hierarchy
# =============================================================================

@dataclass
class Frame:
    """Base frame type. All frames carry an auto-generated id."""
    id: int = field(init=False, default_factory=lambda: next(_frame_id_counter))


@dataclass
class StartFrame(Frame):
    """System frame that initializes the processor chain.

    Must be the first frame processed by any processor.
    """
    pass


@dataclass
class EndFrame(Frame):
    """System frame signalling the end of the pipeline."""
    pass


@dataclass
class TextFrame(Frame):
    """Carries a text token/chunk from the LLM."""
    text: str = ""


@dataclass
class ThinkFrame(Frame):
    """Carries a thinking/reasoning chunk from the LLM (hidden from user)."""
    text: str = ""


@dataclass
class LLMMessagesAppendFrame(Frame):
    """Triggers an LLM call with the given messages or query/history.

    For interleaved thinking mode, use query and history to let the processor
    build messages internally using prompt.build_messages().

    For native mode, use messages directly.

    Args:
        query: User's current query.
        history: Previous conversation messages in generic format.
        messages: Pre-built messages list (for native mode).
        run_llm: Whether to trigger LLM call.
    """
    query: str = ''
    history: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    run_llm: Optional[bool] = None


@dataclass
class LLMFullResponseEndFrame(Frame):
    """Signals that the LLM has finished its full response."""
    pass


@dataclass
class LLMStartFrame(Frame):
    """Signals the start of an LLM call with metadata."""
    llm_id: str = ""
    model: str = ""
    provider: str = ""


@dataclass
class LLMEndFrame(Frame):
    """Signals the end of an LLM call with usage statistics."""
    llm_id: str = ""
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    ttft_ms: float = 0.0
    chunk_count: int = 0
    tpot_ms: float = 0.0


@dataclass
class FunctionCallInProgressFrame(Frame):
    """Signals that a function call is being executed."""
    function_name: str = ""
    tool_call_id: str = ""
    arguments: Any = None


@dataclass
class FunctionCallResultFrame(Frame):
    """Carries the result of a function call."""
    function_name: str = ""
    tool_call_id: str = ""
    arguments: Any = None
    result: Any = None
    status: str = "success"       # success / error / timeout / cancelled
    error_message: str = ""


@dataclass
class AsyncFunctionCallFrame(Frame):
    """Asynchronous function call request frame.

    When this frame is sent, the processor returns immediately without
    waiting for execution results. After execution completes, a
    FunctionCallEndFrame is sent back via callback.
    """
    function_name: str = ""
    tool_call_id: str = ""
    arguments: Any = None
    callback_id: str = ""  # Used to correlate callbacks
    timeout_seconds: float = 30.0  # Timeout for the async operation
    result_callback: Optional[Callable[..., Awaitable[None]]] = None


@dataclass
class FunctionCallEndFrame(Frame):
    """Asynchronous function call completion callback frame.

    Sent by AsyncExecutor back to the pipeline after tool execution completes.
    """
    callback_id: str = ""  # Correlates to AsyncFunctionCallFrame
    function_name: str = ""
    tool_call_id: str = ""
    result: Any = None
    status: str = "success"  # success / error / timeout / cancelled
    error_message: str = ""


@dataclass
class FunctionCallCancelFrame(Frame):
    """Cancel asynchronous function call frame.

    Used to cancel an ongoing async task.
    """
    callback_id: str = ""


@dataclass
class CardDataFrame(Frame):
    """Carries card data for frontend rendering.

    Cards are generated from tool results and sent to the frontend
    via WebSocket, bypassing the LLM context entirely.
    """
    cards: list[dict] = field(default_factory=list)


@dataclass
class PipelineControlFrame(Frame):
    """Pipeline control frame.

    Used to control pipeline operations like pause, resume, flush, reset.
    """
    command: str = ""  # pause / resume / flush / reset
    params: dict = field(default_factory=dict)


# =============================================================================
# FrameProcessor
# =============================================================================

class FrameProcessor:
    """Minimal frame processor with direct-mode support.

    Processors are linked into a chain via ``link()``. When
    ``enable_direct_mode=True``, ``push_frame()`` synchronously
    forwards frames to the next processor without an internal queue,
    enabling per-request execution without a background event loop.
    """

    def __init__(self, *, enable_direct_mode: bool = False, **kwargs):
        self._enable_direct_mode = enable_direct_mode
        self._next: Optional["FrameProcessor"] = None
        self._prev: Optional["FrameProcessor"] = None
        self._started: bool = False

    def link(self, processor: "FrameProcessor") -> "FrameProcessor":
        """Link this processor to the next downstream processor.

        Args:
            processor: The downstream processor.

        Returns:
            The linked processor (for chaining).
        """
        self._next = processor
        processor._prev = self
        logger.debug(f"Linking {self.__class__.__name__} -> {processor.__class__.__name__}")
        return processor

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process an incoming frame.

        Subclasses should call ``await super().process_frame(frame, direction)``
        first. The base implementation handles ``StartFrame`` bookkeeping.

        Args:
            frame: The frame to process.
            direction: Direction of frame flow.
        """
        if isinstance(frame, StartFrame):
            self._started = True

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Push a frame to the adjacent processor.

        In direct mode, immediately calls ``_next.process_frame()``
        (downstream) or ``_prev.process_frame()`` (upstream).

        Args:
            frame: The frame to push.
            direction: Direction to push towards.
        """
        if not self._started and not isinstance(frame, StartFrame):
            logger.error(
                f"{self.__class__.__name__}: Trying to push {frame.__class__.__name__} "
                "but StartFrame not received yet"
            )
            return

        if direction == FrameDirection.DOWNSTREAM and self._next:
            await self._next.process_frame(frame, direction)
        elif direction == FrameDirection.UPSTREAM and self._prev:
            await self._prev.process_frame(frame, direction)


# =============================================================================
# FunctionSchema
# =============================================================================

class FunctionSchema:
    """Schema describing a callable function for LLM function_calling.

    Compatible with OpenAI tools format via ``to_default_dict()``.
    """

    def __init__(
        self,
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ):
        self._name = name
        self._description = description
        self._properties = properties
        self._required = required or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def properties(self) -> dict[str, Any]:
        return self._properties

    @property
    def required(self) -> list[str]:
        return self._required

    def to_default_dict(self) -> dict[str, Any]:
        """Convert to OpenAI function definition format.

        Returns:
            Dict with 'name', 'description', and 'parameters'.
        """
        return {
            "name": self._name,
            "description": self._description,
            "parameters": {
                "type": "object",
                "properties": self._properties,
                "required": self._required,
            },
        }


# =============================================================================
# FunctionCallParams
# =============================================================================

@dataclass
class FunctionCallParams:
    """Parameters passed to a function call handler.

    Attributes:
        function_name: Name of the function being called.
        tool_call_id: Unique identifier for this tool call.
        arguments: Arguments dict from the LLM.
        llm: Reference to the LLM processor (or None).
        context: Optional context object.
        result_callback: Async callback to return the result.
    """
    function_name: str
    tool_call_id: str
    arguments: Mapping[str, Any]
    llm: Any = None
    context: Any = None
    result_callback: Optional[Callable[..., Awaitable[None]]] = None


# =============================================================================
# PipelineTask
# =============================================================================

import asyncio


class PipelineTask:
    """Manages the lifecycle of a pipeline execution.

    Inspired by pipecat's PipelineTask, this class provides a simple
    wrapper for driving a frame processor chain from start to finish.

    Example:
        async def main():
            task = PipelineTask(llm_processor)
            await task.run(messages)
            # Or drive manually:
            # await llm_processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
            # await llm_processor.process_frame(
            #     LLMMessagesAppendFrame(messages=messages),
            #     FrameDirection.DOWNSTREAM
            # )
    """

    def __init__(self, root: "FrameProcessor"):
        """Initialize the pipeline task.

        Args:
            root: The root FrameProcessor of the pipeline chain.
        """
        self._root = root
        self._done = asyncio.Event()
        self._cancelled = False

    @property
    def root(self) -> "FrameProcessor":
        """Get the root processor."""
        return self._root

    @property
    def is_done(self) -> bool:
        """Check if the task has finished."""
        return self._done.is_set()

    @property
    def is_cancelled(self) -> bool:
        """Check if the task was cancelled."""
        return self._cancelled

    async def run(self, messages: list[dict]) -> None:
        """Run the pipeline with the given messages.

        This is a convenience method that sends StartFrame followed by
        LLMMessagesAppendFrame to the root processor.

        Args:
            messages: List of message dicts for the LLM.
        """
        # Initialize the processor chain with StartFrame
        await self._root.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        # Push the actual message frame
        await self._root.process_frame(
            LLMMessagesAppendFrame(messages=messages, run_llm=True),
            FrameDirection.DOWNSTREAM
        )

    async def cancel(self) -> None:
        """Cancel the pipeline execution.

        Sets the cancelled flag and signals the done event.
        Subclasses or processors may override this to perform cleanup.
        """
        self._cancelled = True
        self._done.set()
        logger.debug(f"PipelineTask cancelled")

    def stop_when_done(self) -> None:
        """Signal that the pipeline has completed.

        Call this from processors when the pipeline should end.
        """
        self._done.set()
        logger.debug(f"PipelineTask marked as done")

    async def wait(self) -> None:
        """Wait for the pipeline to complete or be cancelled."""
        await self._done.wait()

    def has_finished(self) -> bool:
        """Check if the task has finished (alias for is_done)."""
        return self._done.is_set()

    def __repr__(self) -> str:
        return (
            f"PipelineTask(root={self._root.__class__.__name__}, "
            f"done={self._done.is_set()}, "
            f"cancelled={self._cancelled})"
        )
