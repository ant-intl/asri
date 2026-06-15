"""
Output collector processor for Pipeline Agent.

Terminal processor in the Pipeline chain that translates pipecat Frames
into ASRI chunk dicts and writes them into an asyncio.Queue for
consumption by ChatAgent.run() / stream().
"""
import asyncio
import logging
import time

from ..framework import (
    Frame,
    TextFrame,
    ThinkFrame,
    CardDataFrame,
    EndFrame,
    LLMFullResponseEndFrame,
    LLMStartFrame,
    LLMEndFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    FrameDirection,
    FrameProcessor,
)

logger = logging.getLogger(__name__)


class OutputCollectorProcessor(FrameProcessor):
    """Collects Pipeline output frames into an asyncio.Queue.

    Translates pipecat Frame types into ASRI-standard chunk dicts
    compatible with BaseAgent.stream() yield format:
      {'type': 'answer'|'tool_call'|'tool_result'|'done'|'error', 'content': str, ...}
    """

    def __init__(self, output_queue: asyncio.Queue, **kwargs):
        """Initialize the output collector.

        Args:
            output_queue: Queue to write translated chunks into.
        """
        super().__init__(**kwargs)
        self._queue = output_queue

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process a frame and write the corresponding chunk to the queue."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            text = frame.text
            if text:
                await self._queue.put({
                    'type': 'answer',
                    'content': text,
                    'timestamp': int(time.time() * 1000),
                })

        elif isinstance(frame, ThinkFrame):
            text = frame.text
            if text:
                await self._queue.put({
                    'type': 'think',
                    'content': text,
                    'timestamp': int(time.time() * 1000),
                })

        elif isinstance(frame, FunctionCallInProgressFrame):
            await self._queue.put({
                'type': 'tool_call',
                'status': 'calling',
                'tool_name': frame.function_name,
                'parameters': frame.arguments,
                'tool_call_id': frame.tool_call_id,
                'timestamp': int(time.time() * 1000),
            })

        elif isinstance(frame, FunctionCallResultFrame):
            result = frame.result
            if isinstance(result, dict):
                content = result.get('result', str(result))
            else:
                content = str(result) if result else ''
            chunk = {
                'type': 'tool_result',
                'status': frame.status,
                'tool_name': frame.function_name,
                'result': content,
                'tool_call_id': frame.tool_call_id,
                'timestamp': int(time.time() * 1000),
            }
            if frame.error_message:
                chunk['error_message'] = frame.error_message
            await self._queue.put(chunk)

        elif isinstance(frame, CardDataFrame):
            for card in frame.cards:
                await self._queue.put({
                    'type': 'card',
                    'card_data': card,
                    'timestamp': int(time.time() * 1000),
                })

        elif isinstance(frame, LLMFullResponseEndFrame):
            await self._queue.put({
                'type': 'done',
                'content': '',
                'timestamp': int(time.time() * 1000),
            })

        elif isinstance(frame, LLMStartFrame):
            await self._queue.put({
                'type': 'llm_start',
                'llm_id': frame.llm_id,
                'model': frame.model,
                'provider': frame.provider,
                'timestamp': int(time.time() * 1000),
            })

        elif isinstance(frame, LLMEndFrame):
            await self._queue.put({
                'type': 'llm_end',
                'llm_id': frame.llm_id,
                'duration_ms': frame.duration_ms,
                'prompt_tokens': frame.prompt_tokens,
                'completion_tokens': frame.completion_tokens,
                'total_tokens': frame.total_tokens,
                'cached_tokens': frame.cached_tokens,
                'ttft_ms': frame.ttft_ms,
                'chunk_count': frame.chunk_count,
                'tpot_ms': frame.tpot_ms,
                'timestamp': int(time.time() * 1000),
            })

        elif isinstance(frame, EndFrame):
            # Sentinel: signals the queue consumer to stop
            await self._queue.put(None)

        # Always forward the frame downstream (no-op for terminal processor,
        # but maintains pipecat contract)
        await self.push_frame(frame, direction)
