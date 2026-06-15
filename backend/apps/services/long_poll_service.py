"""
Long Poll Service - HTTP Long Polling for streaming simulation.

Manages in-memory state for ongoing polling tasks and provides
blocking wait mechanism for incremental content delivery.

Uses user_message_id as the polling identifier since it's available
immediately when the user message is saved.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

from asgiref.sync import sync_to_async

from .chat_service import ChatService
from ..entities.session import ChatSession

logger = logging.getLogger(__name__)


@dataclass
class LongPollTask:
    """Represents a single long polling task."""
    user_message_id: str                 # User message ID (polling identifier)
    session_id: str                      # Associated session
    user_id: str                         # User identifier
    message: str                         # User message
    tenant_id: Optional[str]             # Tenant ID
    status: str = 'running'              # running / done / error / cancelled
    chunks: list = field(default_factory=list)  # All produced chunks
    error: Optional[str] = None          # Error message if failed
    done_event: asyncio.Event = field(default_factory=asyncio.Event)  # Completion signal
    new_chunk_event: asyncio.Event = field(default_factory=asyncio.Event)  # New chunk signal
    created_at: datetime = field(default_factory=datetime.now)  # Creation time
    background_task: Optional[asyncio.Task] = None  # Background task reference
    metadata: dict = field(default_factory=dict)  # Additional metadata (usage, trace, etc.)


class LongPollService:
    """
    Service for managing HTTP long polling tasks.
    
    This enables streaming-like experience over HTTP by:
    1. Saving user message and getting user_message_id
    2. Creating a task that runs stream_chat() in background
    3. Storing chunks in memory keyed by user_message_id
    4. Providing blocking wait for new chunks
    5. Cleaning up completed tasks
    """

    def __init__(self):
        self._active_tasks: Dict[str, LongPollTask] = {}
        self._task_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._chat_service = ChatService()

    async def _get_task_lock(self, user_message_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific task (thread-safe)."""
        async with self._global_lock:
            if user_message_id not in self._task_locks:
                self._task_locks[user_message_id] = asyncio.Lock()
            return self._task_locks[user_message_id]

    async def create_and_start_task(
        self,
        session: ChatSession,
        message: str,
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> LongPollTask:
        """
        Create a new long polling task and start background streaming.
        
        Args:
            session: ChatSession object
            message: User message
            user_id: User identifier
            tenant_id: Optional tenant ID
            
        Returns:
            LongPollTask instance with user_message_id
        """
        session_id = str(session.session_id)
        
        # Save user message first to get real user_message_id
        from .session_service import SessionService
        session_service = SessionService()
        
        user_message = await session_service.add_message(
            session_id=session_id,
            role='user',
            content=message,
            message_type='text'
        )
        user_message_id = str(user_message.message_id)
        
        # Create task
        task = LongPollTask(
            user_message_id=user_message_id,
            session_id=session_id,
            user_id=user_id,
            message=message,
            tenant_id=tenant_id,
        )
        
        # Register task
        self._active_tasks[user_message_id] = task
        
        # Start background task (without saving user message again)
        task.background_task = asyncio.create_task(
            self._run_streaming(task, session, message, user_id, tenant_id)
        )
        
        return task

    async def _run_streaming(
        self,
        task: LongPollTask,
        session: ChatSession,
        message: str,
        user_id: str,
        tenant_id: Optional[str],
    ):
        """
        Background task: Run stream_chat and collect chunks.
        
        This runs stream_chat() as an async generator and stores
        each chunk in the task's chunks list.
        """
        try:
            async for chunk in self._chat_service.stream_chat(
                session=session,
                message=message,
                user_id=user_id,
                tenant_id=tenant_id,
                user_message_id=task.user_message_id,
            ):
                # Safely append chunk
                lock = await self._get_task_lock(task.user_message_id)
                async with lock:
                    task.chunks.append(chunk)
                    task.new_chunk_event.set()  # Wake up waiting poll requests
                
                # Collect metadata from done chunk
                if chunk.get('type') == 'done':
                    task.metadata['trace'] = chunk.get('trace', [])
                    task.metadata['message_id'] = chunk.get('message_id')

            task.status = 'done'
            logger.info(f"Long poll task {task.user_message_id} completed")
            
        except Exception as e:
            logger.exception(f"Long poll task {task.user_message_id} error")
            task.status = 'error'
            task.error = str(e)
            
            lock = await self._get_task_lock(task.user_message_id)
            async with lock:
                task.chunks.append({
                    'type': 'error',
                    'content': str(e),
                })
        finally:
            task.done_event.set()

    async def poll_chunks(
        self,
        user_message_id: str,
        last_offset: int,
        timeout: float = 30.0,
    ) -> dict:
        """
        Poll for new chunks with blocking wait.
        
        Args:
            user_message_id: User message ID
            last_offset: Last received chunk offset
            timeout: Maximum wait time in seconds
            
        Returns:
            Dict with status, offset, chunks, and optional metadata
        """
        task = self._active_tasks.get(user_message_id)

        if not task:
            return {
                'user_message_id': user_message_id,
                'status': 'error',
                'offset': last_offset,
                'chunks': [],
                'error': 'Task not found',
            }

        # Fast path: Has new chunks
        if last_offset < len(task.chunks):
            new_chunks = task.chunks[last_offset:]
            return {
                'user_message_id': user_message_id,
                'status': task.status,
                'offset': len(task.chunks),
                'chunks': new_chunks,
            }
        
        # Slow path: Wait for new chunks or completion
        if task.status == 'running':
            # Clear the event before waiting to ensure we wait for NEW chunks
            # This prevents immediate return if event was already set by previous poll
            task.new_chunk_event.clear()
            
            try:
                # Wait for either new chunk or completion
                await asyncio.wait_for(
                    asyncio.wait(
                        [
                            asyncio.create_task(task.new_chunk_event.wait()),
                            asyncio.create_task(task.done_event.wait()),
                        ],
                        return_when=asyncio.FIRST_COMPLETED,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Timeout: Return empty chunks, client will poll again
                return {
                    'user_message_id': user_message_id,
                    'status': 'running',
                    'offset': last_offset,
                    'chunks': [],
                }
            
            # Re-check for new chunks
            if last_offset < len(task.chunks):
                new_chunks = task.chunks[last_offset:]
                return {
                    'user_message_id': user_message_id,
                    'status': task.status,
                    'offset': len(task.chunks),
                    'chunks': new_chunks,
                }
        
        # Task finished, return final state
        response = {
            'user_message_id': user_message_id,
            'status': task.status,
            'offset': len(task.chunks),
            'chunks': [],
        }
        
        # Include metadata if done
        if task.status == 'done' and task.metadata:
            response['trace'] = task.metadata.get('trace', [])
            response['assistant_message_id'] = task.metadata.get('message_id')
            # Extract usage from last answer chunk if available
            for chunk in reversed(task.chunks):
                if chunk.get('type') == 'done' and chunk.get('metadata', {}).get('usage'):
                    response['usage'] = chunk['metadata']['usage']
                    break
        
        if task.status == 'error' and task.error:
            response['error'] = task.error
        
        return response

    async def cancel_task(self, user_message_id: str) -> bool:
        """
        Cancel a running polling task.
        
        Args:
            user_message_id: User message ID
            
        Returns:
            True if cancelled, False if task not found or already finished
        """
        task = self._active_tasks.get(user_message_id)
        
        if not task or task.status != 'running':
            return False
        
        task.status = 'cancelled'
        task.done_event.set()
        
        # Cancel background task
        if task.background_task and not task.background_task.done():
            task.background_task.cancel()
        
        logger.info(f"Long poll task {user_message_id} cancelled")
        return True

    async def cleanup_tasks(self):
        """
        Periodic cleanup: Remove tasks older than 30 minutes.
        Call this from a periodic task (e.g., Celery beat).
        """
        cutoff = datetime.now() - timedelta(minutes=30)
        to_remove = [
            msg_id
            for msg_id, task in self._active_tasks.items()
            if task.created_at < cutoff
        ]
        
        for msg_id in to_remove:
            task = self._active_tasks.pop(msg_id, None)
            if task and task.background_task and not task.background_task.done():
                task.background_task.cancel()
            logger.debug(f"Cleaned up expired long poll task: {msg_id}")
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} expired long poll tasks")


# Global instance
long_poll_service = LongPollService()
