"""
Async Executor Processor for full-duplex pipeline.

Manages asynchronous task execution without blocking frame flow.
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from ..framework import (
    Frame,
    FrameDirection,
    FrameProcessor,
    AsyncFunctionCallFrame,
    FunctionCallEndFrame,
    FunctionCallCancelFrame,
)

logger = logging.getLogger(__name__)


class AsyncExecutorProcessor(FrameProcessor):
    """Asynchronous execution processor.

    Responsible for managing async task execution without blocking frame flow.
    When an AsyncFunctionCallFrame is received, it starts the task immediately
    and returns. The result is sent back via FunctionCallEndFrame callback.
    """

    def __init__(
        self,
        handlers: Optional[dict[str, Callable[[Any], Awaitable[Any]]]] = None,
        enable_concurrent: bool = True,
        **kwargs,
    ):
        """Initialize the async executor processor.

        Args:
            handlers: Dict mapping function names to async handler functions.
            enable_concurrent: Whether to execute tools concurrently.
                When False, tools are executed sequentially one at a time.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self._handlers: dict[str, Callable[[Any], Awaitable[Any]]] = handlers or {}
        self._pending_tasks: dict[str, asyncio.Task] = {}
        self._enable_concurrent = enable_concurrent
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._is_executing = False
        self._queue_task: asyncio.Task | None = None

    def register_handler(
        self,
        function_name: str,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> None:
        """Register a handler for a function.

        Args:
            function_name: Name of the function.
            handler: Async handler function that takes arguments and returns result.
        """
        self._handlers[function_name] = handler
        logger.debug(f"Registered handler for function: {function_name}")

    def unregister_handler(self, function_name: str) -> None:
        """Unregister a handler.

        Args:
            function_name: Name of the function to unregister.
        """
        self._handlers.pop(function_name, None)
        logger.debug(f"Unregistered handler for function: {function_name}")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process incoming frames.

        Args:
            frame: The frame to process.
            direction: Direction of frame flow.
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, AsyncFunctionCallFrame):
            # Auto-start since async_executor is not in normal pipeline flow
            if not self._started:
                self._started = True
            # Start async task and return immediately (non-blocking)
            await self._start_async_task(frame, direction)

        elif isinstance(frame, FunctionCallCancelFrame):
            # Cancel async task
            await self._cancel_task(frame.callback_id, direction)

        elif isinstance(frame, FunctionCallEndFrame):
            # Clean up task state and forward result
            self._pending_tasks.pop(frame.callback_id, None)
            await self.push_frame(frame, direction)

        else:
            # Forward other frames
            await self.push_frame(frame, direction)

    async def _start_async_task(
        self,
        frame: AsyncFunctionCallFrame,
        direction: FrameDirection,
    ) -> None:
        """Start an async task.

        Args:
            frame: The async function call frame.
            direction: Direction for callback frame.
        """
        handler = self._handlers.get(frame.function_name)

        if not handler:
            # Return error immediately
            logger.warning(f"No handler registered for function: {frame.function_name}")
            await self.push_frame(
                FunctionCallEndFrame(
                    callback_id=frame.callback_id,
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    status="error",
                    error_message=f"Unknown function: {frame.function_name}",
                ),
                direction,
            )
            return

        if not self._enable_concurrent:
            # Sequential execution: enqueue task and process one at a time
            await self._task_queue.put((handler, frame, direction))
            if not self._is_executing:
                self._queue_task = asyncio.create_task(
                    self._process_queue(),
                    name="async_exec_queue",
                )
            return

        # Cancel any existing task with the same callback_id
        existing_task = self._pending_tasks.get(frame.callback_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
            try:
                await existing_task
            except asyncio.CancelledError:
                pass

        # Create and track async task
        task = asyncio.create_task(
            self._execute_async(handler, frame, direction),
            name=f"async_exec_{frame.callback_id}",
        )
        self._pending_tasks[frame.callback_id] = task

        logger.debug(
            f"Started async task {frame.callback_id} for function {frame.function_name}"
        )

    async def _process_queue(self) -> None:
        """Process queued tasks sequentially.

        Runs as a background task when enable_concurrent=False.
        Processes one task at a time from the queue.
        """
        self._is_executing = True
        try:
            while True:
                try:
                    handler, frame, direction = await asyncio.wait_for(
                        self._task_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    if self._task_queue.empty():
                        break
                    continue

                task = asyncio.create_task(
                    self._execute_async(handler, frame, direction),
                    name=f"async_exec_{frame.callback_id}",
                )
                self._pending_tasks[frame.callback_id] = task
                # Wait for this task to complete before starting the next
                await task
        finally:
            self._is_executing = False

    async def _execute_async(
        self,
        handler: Callable[[Any], Awaitable[Any]],
        frame: AsyncFunctionCallFrame,
        direction: FrameDirection,
    ) -> None:
        """Execute task asynchronously and send callback frame.

        Args:
            handler: The handler function to execute.
            frame: The async function call frame.
            direction: Direction for callback frame.
        """
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                handler(frame),
                timeout=frame.timeout_seconds,
            )

            # Retry once if result is empty
            if not result or (isinstance(result, str) and not result.strip()):
                logger.warning(
                    f"Empty result for {frame.function_name} "
                    f"(tool_call_id={frame.tool_call_id}), retrying once"
                )
                result = await asyncio.wait_for(
                    handler(frame),
                    timeout=frame.timeout_seconds,
                )

            logger.debug("tool execute result: %s tool_call_id=%s", result, frame.tool_call_id)
            # Send success callback
            await self.push_frame(
                FunctionCallEndFrame(
                    callback_id=frame.callback_id,
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    result=result,
                    status="success",
                ),
                direction,
            )

            logger.debug(
                f"Async task {frame.callback_id} completed successfully"
            )

        except asyncio.TimeoutError:
            # Send timeout callback
            await self.push_frame(
                FunctionCallEndFrame(
                    callback_id=frame.callback_id,
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    status="timeout",
                    error_message=(
                        f"Function {frame.function_name} timed out "
                        f"after {frame.timeout_seconds}s"
                    ),
                ),
                direction,
            )

            logger.warning(
                f"Async task {frame.callback_id} timed out after {frame.timeout_seconds}s "
                f"(function={frame.function_name}, tool_call_id={frame.tool_call_id})"
            )

        except asyncio.CancelledError:
            # Send cancelled callback
            await self.push_frame(
                FunctionCallEndFrame(
                    callback_id=frame.callback_id,
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    status="cancelled",
                    error_message=f"Function {frame.function_name} was cancelled",
                ),
                direction,
            )

            logger.debug(
                f"Async task {frame.callback_id} was cancelled "
                f"(function={frame.function_name}, tool_call_id={frame.tool_call_id})"
            )

        except Exception as e:
            # Send error callback
            logger.exception(
                f"Error executing async task {frame.callback_id} "
                f"(function={frame.function_name}, tool_call_id={frame.tool_call_id}): {e}"
            )

            await self.push_frame(
                FunctionCallEndFrame(
                    callback_id=frame.callback_id,
                    function_name=frame.function_name,
                    tool_call_id=frame.tool_call_id,
                    status="error",
                    error_message=str(e),
                ),
                direction,
            )

        finally:
            # Clean up task reference
            self._pending_tasks.pop(frame.callback_id, None)

    async def _cancel_task(
        self,
        callback_id: str,
        direction: FrameDirection,
    ) -> None:
        """Cancel an async task.

        Args:
            callback_id: The callback ID of the task to cancel.
            direction: Direction for any resulting frames.
        """
        task = self._pending_tasks.get(callback_id)

        if not task:
            logger.debug(f"No pending task found for callback_id: {callback_id}")
            return

        if task.done():
            logger.debug(f"Task {callback_id} already completed")
            self._pending_tasks.pop(callback_id, None)
            return

        # Cancel the task
        task.cancel()
        logger.debug(f"Cancelled task {callback_id}")

    async def cleanup(self) -> None:
        """Clean up all pending tasks.

        Should be called when shutting down the processor.
        """
        logger.debug(f"Cleaning up {len(self._pending_tasks)} pending tasks")

        # Cancel all pending tasks
        for callback_id, task in list(self._pending_tasks.items()):
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete
        if self._pending_tasks:
            await asyncio.gather(
                *self._pending_tasks.values(),
                return_exceptions=True,
            )

        self._pending_tasks.clear()

    def get_pending_count(self) -> int:
        """Get the number of pending async tasks.

        Returns:
            Number of pending tasks.
        """
        return len(self._pending_tasks)

    def is_task_pending(self, callback_id: str) -> bool:
        """Check if a task is pending.

        Args:
            callback_id: The callback ID to check.

        Returns:
            True if the task is pending, False otherwise.
        """
        task = self._pending_tasks.get(callback_id)
        return task is not None and not task.done()
