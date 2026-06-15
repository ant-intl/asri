"""
Chat service - main orchestration for chat functionality.
"""
import logging
import uuid
import asyncio
import time
from typing import Dict, Any, List, Optional, Callable

from .session_service import SessionService
from ..agent.agent.chat_agent import ChatAgent
from ..agent.agent.base import BaseAgent
from ..agent.agent.context import AgentContext
from ..agent.hooks.base import HookManager, HookAction
from ..agent.hooks.registry import HookRegistry
from ..agent.hooks.confirmation_store import get_confirmation_store
from ..agent.hooks.confirmation_hook import ToolConfirmationHook
from ..agent.prompts import get_active_prompt_async
from ..integrations.llm.registry import LLMRegistry
from ..tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


# Global registry for active streaming sessions
_streaming_sessions: dict[str, asyncio.Event] = {}

# Per-session "stream done" events: signalled when a stream finishes cleanup,
# so a new stream for the same session can wait before loading context.
_stream_done_events: dict[str, asyncio.Event] = {}


class ChatService:
    """
    Main chat service that orchestrates the conversation flow.

    Handles single and batch chat requests, coordinating between
    sessions, agents, and LLM providers.
    """

    def __init__(self):
        self.session_service = SessionService()
        self.llm_registry = LLMRegistry()

    @staticmethod
    async def _interleave_agent_and_confirm(
        agent_gen,
        confirm_queue: asyncio.Queue,
    ):
        """Yield agent chunks interleaved with confirm queue messages.

        Uses ``asyncio.wait`` to prevent deadlock when the agent is blocked
        waiting for tool confirmation (e.g. ``ToolConfirmationHook.wait()``).
        Without this, ``confirm_queue`` messages are never consumed because
        the ``async for`` loop can't iterate until the agent yields again.
        """
        _STREAM_DONE = object()

        async def _next_agent(iterator):
            try:
                return await iterator.__anext__()
            except StopAsyncIteration:
                return _STREAM_DONE

        agent_iter = agent_gen.__aiter__()
        agent_task = asyncio.create_task(_next_agent(agent_iter))
        confirm_task = asyncio.create_task(confirm_queue.get())

        try:
            while True:
                # Collect only tasks that are still pending
                pending_tasks = []
                if not agent_task.done():
                    pending_tasks.append(agent_task)
                if not confirm_task.done():
                    pending_tasks.append(confirm_task)

                if not pending_tasks:
                    break

                done, _ = await asyncio.wait(
                    pending_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for t in done:
                    if t is agent_task:
                        result = agent_task.result()
                        if result is _STREAM_DONE:
                            return
                        yield result
                        agent_task = asyncio.create_task(_next_agent(agent_iter))
                    else:
                        yield confirm_task.result()
                        confirm_task = asyncio.create_task(confirm_queue.get())
        finally:
            if not agent_task.done():
                agent_task.cancel()
            if not confirm_task.done():
                confirm_task.cancel()

    async def _create_agent(
        self,
        tenant_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> BaseAgent:
        """Create a ChatAgent instance configured from tenant config.

        Args:
            tenant_id: Optional tenant ID for tool/skill isolation. If not provided,
                will use the current tenant from context (set by middleware).
            snapshot_id: Optional session snapshot ID. If provided, creates an agent
                from the frozen snapshot configuration instead of live tenant config.
        """
        # Use tenant from context if not explicitly provided
        if tenant_id is None:
            from ..tenant.context import get_current_tenant_id
            tenant_id = get_current_tenant_id()
            logger.debug(f"Using tenant_id from context: {tenant_id}")

        # If snapshot_id is provided, use frozen config
        if snapshot_id:
            from .snapshot_service import SnapshotService
            agent, _ = await SnapshotService.create_agent_from_snapshot(
                snapshot_id, tenant_id,
            )
            if agent is not None:
                return agent
            logger.warning(
                "Failed to create agent from snapshot %s, falling back to live config",
                snapshot_id,
            )

        # Get provider from tenant config
        llm = await self.llm_registry.get_provider_from_config(tenant_id)

        # Get active prompt template from database
        prompt = await get_active_prompt_async(tenant_id)

        return ChatAgent(
            llm_provider=llm,
            prompt=prompt,
            tenant_id=tenant_id,
        )

    @staticmethod
    async def _prepare_hooks(
        tenant_id: str | None,
        session_id: str,
    ) -> tuple[HookManager | None, Callable | None]:
        """Load tenant hooks and create HookManager with runtime deps.

        Returns (hook_manager, confirm_notify_cb).
        Returns (None, None) if no hooks are configured.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for hook preparation")
        tid = tenant_id

        hooks = await HookRegistry.get_hooks_for_tenant(tid)
        if not hooks:
            return None, None

        hook_manager = HookManager()
        store = get_confirmation_store()

        async def _confirm_notify(confirmation_id, tool_name, arguments, context):
            """Push confirmation request to the streaming queue."""
            confirm_data = {
                'type': 'tool_confirm_request',
                'confirmation_id': confirmation_id,
                'tool_name': tool_name,
                'arguments': arguments,
                'timeout': 30,
                'timestamp': int(time.time() * 1000),
            }
            # Store on context for passive checks
            context.metadata['_pending_confirmation'] = confirm_data
            # Push to streaming queue if available
            queue = context.metadata.get('_confirm_queue')
            if queue is not None:
                try:
                    queue.put_nowait(confirm_data)
                except asyncio.QueueFull:
                    logger.warning("Confirm queue full for session")

        for hook in hooks:
            if isinstance(hook, ToolConfirmationHook):
                hook.set_runtime_deps(store=store, notify_cb=_confirm_notify)
            hook_manager.register(hook)

        logger.info(
            "Loaded %d hooks for tenant '%s' session=%s",
            len(hooks), tid, session_id,
        )
        return hook_manager, _confirm_notify
    
    async def chat(
        self,
        session: 'ChatSession',
        message: str,
        user_id: str,
        response_count: int = 1,
        tenant_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Process a single chat message.

        Args:
            session: ChatSession object
            message: User's message
            user_id: User identifier
            response_count: Number of responses to generate (for one-question-many-answers)
            tenant_id: Optional tenant ID for tool/skill isolation.
            snapshot_id: Optional session snapshot ID for frozen config.

        Returns:
            Dict containing response content, message_id, trace, and usage
        """
        session_id = str(session.session_id)

        # Resolve tenant_id from context if not explicitly provided
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
            if not tenant_id:
                raise ValueError("tenant_id not set in request context")

        # Read user_context from session metadata
        session_metadata = session.metadata or {}
        user_context = session_metadata.get('user_context', {})

        # Load context BEFORE saving user message to avoid duplicate
        history = await self.session_service.get_session_context(
            session_id=session_id,
        )

        # Add user message to session
        user_message = await self.session_service.add_message(
            session_id=session_id,
            role='user',
            content=message,
            message_type='text'
        )

        # Load hooks for this tenant
        hook_manager, _ = await self._prepare_hooks(tenant_id, session_id)

        # ── on_user_message Hook ──────────────────────────────────
        if hook_manager:
            context_pre = AgentContext(
                current_query=message,
                messages=history or [],
                session_id=session_id,
                tenant_id=tenant_id,
                user_context=user_context,
                hook_manager=hook_manager,
            )
            msg_result = await hook_manager.execute_user_message_hooks(
                message, history or [], context_pre
            )
            if msg_result.action == HookAction.DENY:
                return {
                    'message_id': None,
                    'content': msg_result.reason or '消息被拒绝',
                    'trace': [],
                    'usage': {},
                }
            if msg_result.action == HookAction.STOP:
                return {
                    'message_id': None,
                    'content': msg_result.reason or 'Agent 已中止',
                    'trace': [],
                    'usage': {},
                }
            if msg_result.action == HookAction.MODIFY and msg_result.modified_data:
                message = msg_result.modified_data

        # Create and run agent - parameters are auto-fetched from tenant config
        agent = await self._create_agent(
            tenant_id=tenant_id,
            snapshot_id=snapshot_id,
        )

        # Create AgentContext with user_context
        max_iterations = int(config.get('max_iterations', 10)) if config else 10
        context = AgentContext(
            current_query=message,
            messages=history or [],
            max_iterations=max_iterations,
            session_id=session_id,
            tenant_id=tenant_id,
            user_context=user_context,
            hook_manager=hook_manager,
        )

        result = await agent.run(
            query=message,
            history=history,
            context=context,
        )

        # ── Record cache stats ────────────────────────────────────
        try:
            from .cache_stats_service import CacheStatsService
            await CacheStatsService().record_from_context(
                session_id=session_id,
                user_id=user_id,
                context=context,
                model_name=result.get('model', ''),
                llm_provider=result.get('provider', ''),
            )
        except Exception as e:
            logger.warning(f"Failed to record cache stats: {e}")

        # ── on_agent_stop Hook ────────────────────────────────────
        if hook_manager:
            # Inject context_messages and model into context for hook consumption
            context.metadata['_context_messages'] = result.get('context_messages', [])
            context.metadata['_model'] = result.get('model', '')
            await hook_manager.execute_agent_stop_hooks(
                result.get('answer', ''), result.get('trace', []), context
            )
        
        # Save assistant response
        assistant_message = await self.session_service.add_message(
            session_id=session_id,
            role='assistant',
            content=result['answer'],
            message_type='text',
            parent_message_id=str(user_message.message_id),
            token_count=result.get('total_tokens', 0),
            metadata={
                'trace': result.get('trace', []),
                'model': result.get('model', ''),
                'stream_status': 'completed',
            }
        )
        
        # Persist full context for subsequent requests
        context_messages = result.get('context_messages')
        if context_messages is not None:
            await self.session_service.save_session_context(
                session_id=session_id,
                messages=context_messages,
            )
        
        return {
            'message_id': str(assistant_message.message_id),
            'content': result['answer'],
            'trace': result.get('trace', []),
            'system_prompt': result.get('system_prompt'),
            'tools': result.get('tools', []),
            'usage': {
                'prompt_tokens': result.get('prompt_tokens', 0),
                'completion_tokens': result.get('completion_tokens', 0),
                'total_tokens': result.get('total_tokens', 0),
            },
            'context_messages': result.get('context_messages'),
        }
    
    async def batch_chat(
        self,
        session,
        messages: List[str],
        user_id: str,
        group_id: str = None,
        tenant_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Process multiple messages as a batch (many-questions-one-answer).

        Args:
            session: ChatSession object
            messages: List of user messages
            user_id: User identifier
            group_id: Optional group ID for the batch
            tenant_id: Optional tenant ID for tool/skill isolation.
            snapshot_id: Optional session snapshot ID for frozen config.

        Returns:
            Dict containing combined response
        """
        session_id = str(session.session_id)

        # Read user_context from session metadata
        session_metadata = session.metadata or {}
        user_context = session_metadata.get('user_context', {})

        if not group_id:
            group_id = str(uuid.uuid4())

        # Load context BEFORE saving user messages to avoid duplicate
        history = await self.session_service.get_session_context(
            session_id=session_id,
        )

        # Add all user messages with the same group_id
        for msg in messages:
            await self.session_service.add_message(
                session_id=session_id,
                role='user',
                content=msg,
                message_type='text',
                group_id=group_id
            )
        
        # Combine messages into a single query
        combined_query = "\n".join([f"Question {i+1}: {m}" for i, m in enumerate(messages)])
        combined_query = f"Please answer the following questions:\n\n{combined_query}"

        # Create and run agent - parameters are auto-fetched from tenant config
        agent = await self._create_agent(
            tenant_id=tenant_id,
            snapshot_id=snapshot_id,
        )

        # Create AgentContext with user_context
        context = AgentContext(
            current_query=combined_query,
            messages=history or [],
            max_iterations=10,
            tenant_id=tenant_id,
            user_context=user_context,
        )

        result = await agent.run(
            query=combined_query,
            history=history,
            context=context,
        )
        
        # Save assistant response
        assistant_message = await self.session_service.add_message(
            session_id=session_id,
            role='assistant',
            content=result['answer'],
            message_type='text',
            group_id=group_id,
            token_count=result.get('total_tokens', 0),
            metadata={
                'trace': result.get('trace', []),
                'batch_size': len(messages),
                'stream_status': 'completed',
            }
        )
        
        # Persist full context
        context_messages = result.get('context_messages')
        if context_messages is not None:
            await self.session_service.save_session_context(
                session_id=session_id,
                messages=context_messages,
            )
        
        return {
            'group_id': group_id,
            'message_id': str(assistant_message.message_id),
            'content': result['answer'],
            'trace': result.get('trace', []),
            'usage': {
                'prompt_tokens': result.get('prompt_tokens', 0),
                'completion_tokens': result.get('completion_tokens', 0),
                'total_tokens': result.get('total_tokens', 0),
            }
        }
    
    async def stream_chat(
        self,
        session,
        message: str,
        user_id: str,
        tenant_id: str | None = None,
        user_message_id: str | None = None,
        snapshot_id: str | None = None,
        config: dict | None = None,
    ):
        """
        Stream chat response (generator for WebSocket/SSE).

        Saves assistant message incrementally during streaming so that
        content is recoverable on reconnection. After the stream ends,
        persists the full LLM context to SessionContext for use in
        subsequent requests.

        Args:
            session: ChatSession object
            message: User message text
            user_id: User identifier
            tenant_id: Optional tenant ID
            user_message_id: If provided, skip saving user message (already saved by caller)
            snapshot_id: Optional session snapshot ID for frozen config.

        Interrupt handling:
            - Interrupt signal is delivered via interrupt_session()
            - This method checks local and TBase-backed interrupt signals
            - When interrupted: saves context, marks message, returns
        """
        session_id = str(session.session_id)
        stream_tenant_id = tenant_id or get_current_tenant_id()
        if not stream_tenant_id:
            raise ValueError("tenant_id not set in request context")

        # Read user_context from session metadata
        session_metadata = session.metadata or {}
        user_context = session_metadata.get('user_context', {})

        # ─── Auto-interrupt previous stream and wait for it to finish ───
        old_event = _streaming_sessions.get(session_id)
        if old_event is not None:
            old_event.set()  # Signal the old stream to stop
            logger.info(f"Auto-interrupted previous stream for session {session_id}")
            old_done = _stream_done_events.get(session_id)
            if old_done is not None:
                try:
                    await asyncio.wait_for(old_done.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Timeout waiting for previous stream to finish: {session_id}"
                    )

        # Register this session as actively streaming
        interrupt_event = asyncio.Event()
        done_event = asyncio.Event()
        _streaming_sessions[session_id] = interrupt_event
        _stream_done_events[session_id] = done_event

        try:
            # Initialize variables referenced in finally-block fallback
            agent = None
            full_response: list[str] = []
            trace: list[dict] = []
            assistant_msg_id = None
            context_saved = False

            # 1. Load context BEFORE saving user message to avoid duplicate
            history = await self.session_service.get_session_context(
                session_id=session_id,
            )

            # 2. Save user message (skip if already saved by caller, e.g. long polling)
            if user_message_id:
                saved_user_message_id = user_message_id
            else:
                user_message = await self.session_service.add_message(
                    session_id=session_id,
                    role='user',
                    content=message,
                    message_type='text'
                )
                saved_user_message_id = str(user_message.message_id)

            # 3. Create assistant message placeholder for incremental saving
            assistant_message = await self.session_service.add_message(
                session_id=session_id,
                role='assistant',
                content='',
                message_type='text',
                parent_message_id=saved_user_message_id,
                metadata={'stream_status': 'streaming', 'trace': []}
            )
            assistant_msg_id = str(assistant_message.message_id)

            # 4. Load hooks for this tenant
            hook_manager = None
            hook_manager, _ = await self._prepare_hooks(stream_tenant_id, session_id)

            # ── on_user_message Hook ──────────────────────────────
            if hook_manager:
                temp_ctx = AgentContext(
                    current_query=message,
                    messages=history or [],
                    session_id=session_id,
                    tenant_id=stream_tenant_id,
                    hook_manager=hook_manager,
                )
                msg_result = await hook_manager.execute_user_message_hooks(
                    message, history or [], temp_ctx
                )
                if msg_result.action == HookAction.DENY:
                    yield {
                        'type': 'error',
                        'content': msg_result.reason or '消息被拒绝',
                    }
                    return
                if msg_result.action == HookAction.STOP:
                    yield {
                        'type': 'error',
                        'content': msg_result.reason or 'Agent 已中止',
                    }
                    return
                if msg_result.action == HookAction.MODIFY and msg_result.modified_data:
                    message = msg_result.modified_data

            # 5. Stream with event-based incremental saving
            # Parameters are auto-fetched from tenant config
            agent = await self._create_agent(
                tenant_id=stream_tenant_id,
                snapshot_id=snapshot_id,
            )

            # Apply runtime config overrides if provided
            if config and 'interrupt_strategy' in config:
                agent._interrupt_strategy = config['interrupt_strategy']
                logger.debug(
                    "Overrode agent interrupt_strategy to %s from runtime config",
                    config['interrupt_strategy'],
                )

            full_response = []
            trace = []
            cards: list[dict] = []
            new_context_messages = None
            context_saved = False  # Track if context has been saved
            first_token_saved = False

            # Build shared confirmation queue for hook notifications
            confirm_queue: asyncio.Queue = asyncio.Queue()

            # Context for the agent (shared with hooks)
            max_iterations = int(config.get('max_iterations', 10)) if config else 10
            stream_ctx = AgentContext(
                current_query=message,
                messages=history or [],
                max_iterations=max_iterations,
                session_id=session_id,
                tenant_id=stream_tenant_id,
                hook_manager=hook_manager,
                user_context=user_context,
            )
            stream_ctx.metadata['_confirm_queue'] = confirm_queue

            async for chunk in self._interleave_agent_and_confirm(
                agent.stream(query=message, history=history, context=stream_ctx),
                confirm_queue,
            ):
                # Check for interrupt signal
                if await self._should_interrupt(session_id, stream_tenant_id, interrupt_event):
                    logger.info(f"Stream interrupted for session {session_id}")
                    
                    # Save current context before interruption
                    try:
                        current_context = await agent.get_context_messages()
                        if current_context:
                            # Ensure the current round's assistant message is included
                            # When interrupted during streaming, the assistant message
                            # may not have been added to _generic_messages yet
                            current_content = ''.join(full_response)
                            if current_content:
                                # Check if last message is already an assistant message
                                last_msg = current_context[-1] if current_context else None
                                if not last_msg or last_msg.get('role') != 'assistant':
                                    # Assistant message not yet in context, add it manually
                                    current_context.append({
                                        "role": "assistant",
                                        "content": current_content,
                                    })
                                    logger.debug(
                                        f"Added missing assistant message to interrupted context "
                                        f"(content length: {len(current_content)})"
                                    )
                            
                            await self.session_service.save_session_context(
                                session_id=session_id,
                                messages=current_context,
                            )
                            context_saved = True
                            logger.debug(
                                f"Saved interrupted context for session {session_id}, "
                                f"{len(current_context)} messages"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to save interrupted context: {e}")
                    
                    # Mark interrupted assistant message
                    await self.session_service.update_message_content(
                        message_id=assistant_msg_id,
                        content=''.join(full_response),
                        metadata={'stream_status': 'interrupted', 'trace': trace},
                    )
                    logger.debug(
                        f"Marked assistant message {assistant_msg_id} as interrupted"
                    )
                    
                    # Simply return - the frontend will handle sending a new request
                    # with the merged message. No recursive call needed.
                    return

                chunk_type = chunk.get('type')

                # Check for STOP signal from hooks
                if stream_ctx.metadata.get('_stop_agent'):
                    stop_reason = stream_ctx.metadata.get('_stop_reason', 'Agent 被 Hook 中止')
                    yield {'type': 'error', 'content': stop_reason}
                    await self.session_service.update_message_content(
                        message_id=assistant_msg_id,
                        content=''.join(full_response),
                        metadata={'stream_status': 'stopped_by_hook', 'trace': trace},
                    )
                    return

                # Check for pending confirmations from hooks
                # Note: _interleave_agent_and_confirm already handles queue consumption.
                # This is a redundant safety net for any race conditions.
                try:
                    confirm_chunk = confirm_queue.get_nowait()
                    yield confirm_chunk
                except asyncio.QueueEmpty:
                    pass

                if chunk_type == 'answer':
                    full_response.append(chunk.get('content', ''))
                    # Keep each answer chunk in original order for trace
                    trace.append(chunk)
                    yield chunk
                    # Event: save on first answer chunk arrival
                    if not first_token_saved:
                        first_token_saved = True
                        await self.session_service.update_message_content(
                            message_id=assistant_msg_id,
                            content=''.join(full_response),
                            metadata={'stream_status': 'streaming', 'trace': trace},
                        )

                elif chunk_type in ('think', 'thinking', 'tool_call', 'tool_result', 'llm_start', 'llm_end'):
                    # Keep each think/event chunk in original order for trace
                    trace.append(chunk)
                    yield chunk
                    # Event: save on each trace event
                    await self.session_service.update_message_content(
                        message_id=assistant_msg_id,
                        content=''.join(full_response),
                        metadata={'stream_status': 'streaming', 'trace': trace},
                    )

                elif chunk_type == 'tool_confirm_request':
                    # Confirmation request - forward directly, not a trace event
                    yield chunk

                elif chunk_type == 'card':
                    # Card data bypasses LLM response text and goes directly
                    # to the frontend for rendering (e.g. KYC result card).
                    card_data = chunk.get('card_data', {})
                    if card_data:
                        cards.append(card_data)
                    yield chunk

                elif chunk_type == 'done':
                    new_context_messages = chunk.get('context_messages')

                    # ── on_agent_stop Hook ────────────────────────
                    if hook_manager:
                        stream_ctx.metadata['_context_messages'] = new_context_messages
                        content = ''.join(full_response)
                        await hook_manager.execute_agent_stop_hooks(content, trace, stream_ctx)

                    yield {
                        'type': 'done',
                        'content': '',
                        'message_id': assistant_msg_id,
                        'trace': trace,
                        'metadata': {},
                    }
                    break

            # 4. Record cache stats from streaming context
            try:
                from .cache_stats_service import CacheStatsService
                await CacheStatsService().record_from_context(
                    session_id=session_id,
                    user_id=user_id,
                    context=stream_ctx,
                )
            except Exception as e:
                logger.warning(f"Failed to record cache stats from stream: {e}")

            # 5. Final save - mark as completed
            metadata: dict[str, any] = {'stream_status': 'completed', 'trace': trace}
            if cards:
                metadata['cards'] = cards
            await self.session_service.update_message_content(
                message_id=assistant_msg_id,
                content=''.join(full_response),
                metadata=metadata,
            )

            # 6. Persist full context for subsequent requests
            if new_context_messages is not None:
                await self.session_service.save_session_context(
                    session_id=session_id,
                    messages=new_context_messages,
                )
                context_saved = True

        finally:
            # Fallback: save context if not already saved (e.g. stream was
            # killed by WS disconnect before interrupt detection could fire)
            try:
                if not context_saved and agent is not None:
                    try:
                        fallback_ctx = await agent.get_context_messages()
                        if fallback_ctx:
                            current_content = ''.join(full_response)
                            if current_content:
                                last_msg = fallback_ctx[-1] if fallback_ctx else None
                                if not last_msg or last_msg.get('role') != 'assistant':
                                    fallback_ctx.append({
                                        "role": "assistant",
                                        "content": current_content,
                                    })
                            await self.session_service.save_session_context(
                                session_id=session_id,
                                messages=fallback_ctx,
                            )
                            logger.info(
                                f"Finally-block saved context for {session_id} "
                                f"({len(fallback_ctx)} messages)"
                            )
                    except Exception as e:
                        logger.warning(f"Finally-block context save failed: {e}")

                    # Mark assistant message as interrupted
                    if assistant_msg_id and full_response:
                        try:
                            await self.session_service.update_message_content(
                                message_id=assistant_msg_id,
                                content=''.join(full_response),
                                metadata={'stream_status': 'interrupted', 'trace': trace},
                            )
                        except Exception as e:
                            logger.warning(f"Finally-block message update failed: {e}")
            finally:
                _streaming_sessions.pop(session_id, None)
                done_ev = _stream_done_events.pop(session_id, None)
                if done_ev is not None:
                    done_ev.set()  # Notify waiting new stream

    # ------------------------------------------------------------------
    # Snapshot-based chat methods
    # ------------------------------------------------------------------

    async def _resolve_snapshot_config(
        self,
        snapshot_id: str,
        tenant_id: str,
    ) -> ChatAgent | None:
        """Resolve a snapshot and build a ChatAgent with frozen skills/tools.

        Args:
            snapshot_id: The snapshot ID to resolve.
            tenant_id: Tenant ID for skill/tool filtering.

        Returns:
            ChatAgent instance configured with frozen config,
            or None if the snapshot cannot be resolved.
        """
        from .snapshot_service import SnapshotService

        frozen = await SnapshotService.get_frozen_config(snapshot_id, tenant_id)
        if frozen is None:
            logger.error("Snapshot %s not found or inactive", snapshot_id)
            return None
        if frozen['llm_provider'] is None:
            logger.error(
                "Cannot create agent from snapshot %s: LLM provider not resolvable",
                snapshot_id,
            )
            return None

        # Reconstruct prompt from frozen snapshot data.
        # Priority: 1. DynamicPrompt.from_frozen  2. system_prompt string  3. live active prompt
        system_prompt = frozen.get('system_prompt')
        prompt_data = frozen.get('prompt_data')
        prompt = None

        if prompt_data:
            try:
                from ..agent.prompts.dynamic_prompt import DynamicPrompt
                prompt = DynamicPrompt.from_frozen(prompt_data)
                logger.info(
                    "Reconstructed prompt from snapshot %s (name=%s)",
                    snapshot_id, prompt.prompt_name,
                )
            except Exception as e:
                logger.warning(
                    "Failed to reconstruct prompt from snapshot %s: %s",
                    snapshot_id, e,
                )

        if prompt is None and not system_prompt:
            # Nothing usable in snapshot - fallback to live active prompt
            logger.info(
                "Fallback to live prompt for snapshot %s (no frozen prompt data)",
                snapshot_id,
            )
            prompt = await get_active_prompt_async(tenant_id)

        # Fetch full skill descriptions for frozen skill references
        full_skills = None
        frozen_skills = frozen.get('skills', [])
        if frozen_skills:
            from ..integrations.skill.registry import SkillRegistry
            all_skills = SkillRegistry.list_skills_with_descriptions(
                tenant_id=tenant_id,
            )
            skill_names = {s['name'] for s in frozen_skills}
            full_skills = [
                s for s in all_skills if s['name'] in skill_names
            ]
            logger.info(
                f"_resolve_snapshot_config: filtered {len(full_skills)} skills "
                f"from {len(frozen_skills)} frozen refs"
            )

        # Fetch tool schemas for frozen tool references
        full_tools = None
        frozen_tools = frozen.get('tools', [])
        if frozen_tools:
            from ..integrations.tool.base import ToolRegistry
            all_tools = ToolRegistry.list_tools_with_schemas(
                tenant_id=tenant_id,
            )
            tool_names = {t['name'] for t in frozen_tools}
            full_tools = [
                t for t in all_tools
                if t.get('function', {}).get('name') in tool_names
            ]
            logger.info(
                f"_resolve_snapshot_config: filtered {len(full_tools)} tools "
                f"from {len(frozen_tools)} frozen refs"
            )

        return ChatAgent(
            llm_provider=frozen['llm_provider'],
            system_prompt=system_prompt if prompt is None else None,
            prompt=prompt,
            tenant_id=tenant_id,
            frozen_skills=full_skills,
            frozen_tools=full_tools,
            execution_mode=frozen.get('execution_mode', 'interleaved'),
        )

    async def chat_with_snapshot(
        self,
        session: 'ChatSession',
        message: str,
        user_id: str,
        snapshot_id: str,
        response_count: int = 1,
        tenant_id: str | None = None,
    ) -> Dict[str, Any]:
        """Chat using a snapshot's frozen configuration.

        Unlike :meth:`chat`, this method fully honours the frozen snapshot
        configuration including skills and tools.  It does **not** fall
        back to live tenant config.

        Args:
            session: ChatSession object.
            message: User's message.
            user_id: User identifier.
            snapshot_id: Session snapshot ID (required).
            response_count: Number of responses to generate.
            tenant_id: Optional tenant ID.

        Returns:
            Dict containing response content, message_id, trace, and usage.
        """
        session_id = str(session.session_id)

        if tenant_id is None:
            tenant_id = get_current_tenant_id()
            if not tenant_id:
                raise ValueError("tenant_id not set in request context")

        session_metadata = session.metadata or {}
        user_context = session_metadata.get('user_context', {})

        # Load context BEFORE saving user message
        history = await self.session_service.get_session_context(
            session_id=session_id,
        )

        # Save user message
        user_message = await self.session_service.add_message(
            session_id=session_id,
            role='user',
            content=message,
            message_type='text',
        )

        # Load hooks
        hook_manager, _ = await self._prepare_hooks(tenant_id, session_id)

        # ── on_user_message Hook ──────────────────────────────────
        if hook_manager:
            context_pre = AgentContext(
                current_query=message,
                messages=history or [],
                session_id=session_id,
                tenant_id=tenant_id,
                user_context=user_context,
                hook_manager=hook_manager,
            )
            msg_result = await hook_manager.execute_user_message_hooks(
                message, history or [], context_pre,
            )
            if msg_result.action == HookAction.DENY:
                return {
                    'message_id': None,
                    'content': msg_result.reason or '消息被拒绝',
                    'trace': [],
                    'usage': {},
                }
            if msg_result.action == HookAction.STOP:
                return {
                    'message_id': None,
                    'content': msg_result.reason or 'Agent 已中止',
                    'trace': [],
                    'usage': {},
                }
            if msg_result.action == HookAction.MODIFY and msg_result.modified_data:
                message = msg_result.modified_data

        # Build agent from snapshot frozen config (NOT from _create_agent)
        agent = await self._resolve_snapshot_config(snapshot_id, tenant_id)
        if agent is None:
            raise ValueError(
                f"Failed to resolve snapshot {snapshot_id} for chat"
            )

        # Create AgentContext
        context = AgentContext(
            current_query=message,
            messages=history or [],
            max_iterations=10,
            session_id=session_id,
            tenant_id=tenant_id,
            user_context=user_context,
            hook_manager=hook_manager,
        )

        result = await agent.run(
            query=message,
            history=history,
            context=context,
        )

        # ── Record cache stats ────────────────────────────────────
        try:
            from .cache_stats_service import CacheStatsService
            await CacheStatsService().record_from_context(
                session_id=session_id,
                user_id=user_id,
                context=context,
                model_name=result.get('model', ''),
                llm_provider=result.get('provider', ''),
            )
        except Exception as e:
            logger.warning(f"Failed to record cache stats: {e}")

        # ── on_agent_stop Hook ────────────────────────────────────
        if hook_manager:
            context.metadata['_context_messages'] = result.get('context_messages', [])
            context.metadata['_model'] = result.get('model', '')
            await hook_manager.execute_agent_stop_hooks(
                result.get('answer', ''), result.get('trace', []), context,
            )

        # Save assistant response
        assistant_message = await self.session_service.add_message(
            session_id=session_id,
            role='assistant',
            content=result['answer'],
            message_type='text',
            parent_message_id=str(user_message.message_id),
            token_count=result.get('total_tokens', 0),
            metadata={
                'trace': result.get('trace', []),
                'model': result.get('model', ''),
                'stream_status': 'completed',
            },
        )

        # Persist full context for subsequent requests
        context_messages = result.get('context_messages')
        if context_messages is not None:
            await self.session_service.save_session_context(
                session_id=session_id,
                messages=context_messages,
            )

        return {
            'message_id': str(assistant_message.message_id),
            'content': result['answer'],
            'trace': result.get('trace', []),
            'system_prompt': result.get('system_prompt'),
            'tools': result.get('tools', []),
            'usage': {
                'prompt_tokens': result.get('prompt_tokens', 0),
                'completion_tokens': result.get('completion_tokens', 0),
                'total_tokens': result.get('total_tokens', 0),
            },
            'context_messages': result.get('context_messages'),
        }

    async def stream_chat_with_snapshot(
        self,
        session,
        message: str,
        user_id: str,
        snapshot_id: str,
        tenant_id: str | None = None,
        user_message_id: str | None = None,
        config: dict | None = None,
    ):
        """Stream chat response using a snapshot's frozen configuration.

        Unlike :meth:`stream_chat`, this method fully honours the frozen
        snapshot configuration including skills and tools.  It does **not**
        fall back to live tenant config.

        Args:
            session: ChatSession object.
            message: User message text.
            user_id: User identifier.
            snapshot_id: Session snapshot ID (required).
            tenant_id: Optional tenant ID.
            user_message_id: If provided, skip saving user message.

        Yields:
            Chunks with 'type' and 'content' for SSE streaming.
        """
        session_id = str(session.session_id)
        stream_tenant_id = tenant_id or get_current_tenant_id()
        if not stream_tenant_id:
            raise ValueError("tenant_id not set in request context")

        session_metadata = session.metadata or {}
        user_context = session_metadata.get('user_context', {})

        # ─── Auto-interrupt previous stream and wait for it to finish ───
        old_event = _streaming_sessions.get(session_id)
        if old_event is not None:
            old_event.set()  # Signal the old stream to stop
            logger.info(f"Auto-interrupted previous stream for session {session_id}")
            old_done = _stream_done_events.get(session_id)
            if old_done is not None:
                try:
                    await asyncio.wait_for(old_done.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Timeout waiting for previous stream to finish: {session_id}"
                    )

        # Register this session as actively streaming
        interrupt_event = asyncio.Event()
        done_event = asyncio.Event()
        _streaming_sessions[session_id] = interrupt_event
        _stream_done_events[session_id] = done_event

        try:
            # Initialize variables referenced in finally-block fallback
            agent = None
            full_response: list[str] = []
            trace: list[dict] = []
            assistant_msg_id = None
            context_saved = False

            # 1. Load context BEFORE saving user message
            history = await self.session_service.get_session_context(
                session_id=session_id,
            )

            # 2. Save user message
            if user_message_id:
                saved_user_message_id = user_message_id
            else:
                user_message = await self.session_service.add_message(
                    session_id=session_id,
                    role='user',
                    content=message,
                    message_type='text',
                )
                saved_user_message_id = str(user_message.message_id)

            # 3. Create assistant message placeholder
            assistant_message = await self.session_service.add_message(
                session_id=session_id,
                role='assistant',
                content='',
                message_type='text',
                parent_message_id=saved_user_message_id,
                metadata={'stream_status': 'streaming', 'trace': []},
            )
            assistant_msg_id = str(assistant_message.message_id)

            # 4. Load hooks
            hook_manager = None
            hook_manager, _ = await self._prepare_hooks(
                stream_tenant_id, session_id,
            )

            # ── on_user_message Hook ──────────────────────────────
            if hook_manager:
                temp_ctx = AgentContext(
                    current_query=message,
                    messages=history or [],
                    session_id=session_id,
                    tenant_id=stream_tenant_id,
                    hook_manager=hook_manager,
                )
                msg_result = await hook_manager.execute_user_message_hooks(
                    message, history or [], temp_ctx,
                )
                if msg_result.action == HookAction.DENY:
                    yield {
                        'type': 'error',
                        'content': msg_result.reason or '消息被拒绝',
                    }
                    return
                if msg_result.action == HookAction.STOP:
                    yield {
                        'type': 'error',
                        'content': msg_result.reason or 'Agent 已中止',
                    }
                    return
                if msg_result.action == HookAction.MODIFY and msg_result.modified_data:
                    message = msg_result.modified_data

            # 5. Build agent from snapshot frozen config
            agent = await self._resolve_snapshot_config(
                snapshot_id, stream_tenant_id,
            )

            # Apply runtime config overrides if provided
            if agent and config and 'interrupt_strategy' in config:
                agent._interrupt_strategy = config['interrupt_strategy']
                logger.debug(
                    "Overrode agent interrupt_strategy to %s from runtime config (snapshot)",
                    config['interrupt_strategy'],
                )

            if agent is None:
                logger.error(
                    "Failed to resolve snapshot %s for streaming",
                    snapshot_id,
                )
                yield {
                    'type': 'error',
                    'content': f'无法加载 snapshot {snapshot_id}',
                }
                return

            full_response = []
            trace = []
            cards: list[dict] = []
            new_context_messages = None
            context_saved = False
            first_token_saved = False

            confirm_queue: asyncio.Queue = asyncio.Queue()

            max_iterations = int(config.get('max_iterations', 10)) if config else 10
            stream_ctx = AgentContext(
                current_query=message,
                messages=history or [],
                max_iterations=max_iterations,
                session_id=session_id,
                tenant_id=stream_tenant_id,
                hook_manager=hook_manager,
                user_context=user_context,
            )
            stream_ctx.metadata['_confirm_queue'] = confirm_queue

            # 6. Stream from agent
            async for chunk in self._interleave_agent_and_confirm(
                agent.stream(query=message, history=history, context=stream_ctx),
                confirm_queue,
            ):
                # Check for interrupt signal
                if await self._should_interrupt(
                    session_id, stream_tenant_id, interrupt_event,
                ):
                    logger.info(f"Stream interrupted for session {session_id}")
                    try:
                        current_context = await agent.get_context_messages()
                        if current_context:
                            current_content = ''.join(full_response)
                            if current_content:
                                last_msg = current_context[-1] if current_context else None
                                if not last_msg or last_msg.get('role') != 'assistant':
                                    current_context.append({
                                        'role': 'assistant',
                                        'content': current_content,
                                    })
                            await self.session_service.save_session_context(
                                session_id=session_id,
                                messages=current_context,
                            )
                            context_saved = True
                    except Exception as e:
                        logger.warning(f"Failed to save interrupted context: {e}")

                    await self.session_service.update_message_content(
                        message_id=assistant_msg_id,
                        content=''.join(full_response),
                        metadata={'stream_status': 'interrupted', 'trace': trace},
                    )
                    return

                chunk_type = chunk.get('type')

                # Check for STOP signal from hooks
                if stream_ctx.metadata.get('_stop_agent'):
                    stop_reason = stream_ctx.metadata.get(
                        '_stop_reason', 'Agent 被 Hook 中止',
                    )
                    yield {'type': 'error', 'content': stop_reason}
                    await self.session_service.update_message_content(
                        message_id=assistant_msg_id,
                        content=''.join(full_response),
                        metadata={
                            'stream_status': 'stopped_by_hook',
                            'trace': trace,
                        },
                    )
                    return

                # Check for pending confirmations
                # Note: _interleave_agent_and_confirm already handles queue consumption.
                # This is a redundant safety net for any race conditions.
                try:
                    confirm_chunk = confirm_queue.get_nowait()
                    yield confirm_chunk
                except asyncio.QueueEmpty:
                    pass

                if chunk_type == 'answer':
                    full_response.append(chunk.get('content', ''))
                    trace.append(chunk)
                    yield chunk
                    if not first_token_saved:
                        first_token_saved = True
                        await self.session_service.update_message_content(
                            message_id=assistant_msg_id,
                            content=''.join(full_response),
                            metadata={
                                'stream_status': 'streaming',
                                'trace': trace,
                            },
                        )

                elif chunk_type in (
                    'think', 'thinking', 'tool_call', 'tool_result',
                    'llm_start', 'llm_end',
                ):
                    trace.append(chunk)
                    yield chunk
                    await self.session_service.update_message_content(
                        message_id=assistant_msg_id,
                        content=''.join(full_response),
                        metadata={'stream_status': 'streaming', 'trace': trace},
                    )

                elif chunk_type == 'tool_confirm_request':
                    # Confirmation request - forward directly, not a trace event
                    yield chunk

                elif chunk_type == 'card':
                    card_data = chunk.get('card_data', {})
                    if card_data:
                        cards.append(card_data)
                    yield chunk

                elif chunk_type == 'done':
                    new_context_messages = chunk.get('context_messages')

                    # ── on_agent_stop Hook ────────────────────────
                    if hook_manager:
                        stream_ctx.metadata['_context_messages'] = (
                            new_context_messages
                        )
                        content = ''.join(full_response)
                        await hook_manager.execute_agent_stop_hooks(
                            content, trace, stream_ctx,
                        )

                    yield {
                        'type': 'done',
                        'content': '',
                        'message_id': assistant_msg_id,
                        'trace': trace,
                        'metadata': {},
                    }
                    break

            # Record cache stats
            try:
                from .cache_stats_service import CacheStatsService
                await CacheStatsService().record_from_context(
                    session_id=session_id,
                    user_id=user_id,
                    context=stream_ctx,
                )
            except Exception as e:
                logger.warning(f"Failed to record cache stats from stream: {e}")

            # Final save - mark as completed
            metadata: dict[str, any] = {
                'stream_status': 'completed',
                'trace': trace,
            }
            if cards:
                metadata['cards'] = cards
            await self.session_service.update_message_content(
                message_id=assistant_msg_id,
                content=''.join(full_response),
                metadata=metadata,
            )

            # Persist full context
            if new_context_messages is not None:
                await self.session_service.save_session_context(
                    session_id=session_id,
                    messages=new_context_messages,
                )
                context_saved = True

        finally:
            # Fallback: save context if not already saved (e.g. stream was
            # killed by WS disconnect before interrupt detection could fire)
            try:
                if not context_saved and agent is not None:
                    try:
                        fallback_ctx = await agent.get_context_messages()
                        if fallback_ctx:
                            current_content = ''.join(full_response)
                            if current_content:
                                last_msg = fallback_ctx[-1] if fallback_ctx else None
                                if not last_msg or last_msg.get('role') != 'assistant':
                                    fallback_ctx.append({
                                        "role": "assistant",
                                        "content": current_content,
                                    })
                            await self.session_service.save_session_context(
                                session_id=session_id,
                                messages=fallback_ctx,
                            )
                            logger.info(
                                f"Finally-block saved context for {session_id} "
                                f"({len(fallback_ctx)} messages)"
                            )
                    except Exception as e:
                        logger.warning(f"Finally-block context save failed: {e}")

                    # Mark assistant message as interrupted
                    if assistant_msg_id and full_response:
                        try:
                            await self.session_service.update_message_content(
                                message_id=assistant_msg_id,
                                content=''.join(full_response),
                                metadata={'stream_status': 'interrupted', 'trace': trace},
                            )
                        except Exception as e:
                            logger.warning(f"Finally-block message update failed: {e}")
            finally:
                _streaming_sessions.pop(session_id, None)
                done_ev = _stream_done_events.pop(session_id, None)
                if done_ev is not None:
                    done_ev.set()  # Notify waiting new stream

    async def interrupt_session(self, session_id: str, interrupt_message: str) -> bool:
        """
        Interrupt an active streaming session.

        Args:
            session_id: The session to interrupt
            interrupt_message: The new message that triggered the interrupt

        Returns:
            True if the session was interrupted, False if no active stream
        """
        if session_id in _streaming_sessions:
            event = _streaming_sessions[session_id]
            event.interrupt_message = interrupt_message
            event.set()
            logger.info(f"Interrupt signal sent to session {session_id}")
            return True

        logger.debug(f"No active stream for session {session_id}")
        return False

    async def _should_interrupt(
        self,
        session_id: str,
        tenant_id: str,
        interrupt_event: asyncio.Event,
    ) -> bool:
        """Check local interrupt signal."""
        return interrupt_event.is_set()
