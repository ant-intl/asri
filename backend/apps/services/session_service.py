"""
Session management service.
"""
import logging
from typing import Optional, Tuple, List
from asgiref.sync import sync_to_async

from ..entities import ChatSession, ChatMessage, SessionContext
from ..tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


class SessionService:
    """Service for managing chat sessions and messages.

    All queries are automatically scoped to the current tenant via
    :func:`~apps.tenant.context.get_current_tenant_id`.
    """

    @staticmethod
    def _tenant_id() -> str:
        """Return the current tenant_id from request context.

        Raises:
            ValueError: If tenant_id is not set in the current request context.
        """
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise ValueError("tenant_id not set in request context")
        return tenant_id
    
    @sync_to_async(thread_sensitive=False)
    def create_session(
        self,
        user_id: str,
        title: str = '',
        user_context: dict = None,
        external_session_id: str = None,
        external_source: str = None
    ) -> ChatSession:
        """Create a new chat session, or return existing one if external_session_id and source match."""
        tenant_id = self._tenant_id()
        
        # If external_session_id is provided, check if it already exists with the same source
        if external_session_id and external_source:
            try:
                existing_session = ChatSession.objects.get(
                    external_session_id=external_session_id,
                    external_source=external_source,
                    tenant_id=tenant_id,
                )
                logger.info(
                    f"Session already exists for external_source={external_source}, "
                    f"external_session_id={external_session_id}, "
                    f"returning session_id={existing_session.session_id}"
                )
                return existing_session
            except ChatSession.DoesNotExist:
                pass
        
        # Create new session
        metadata = {'user_context': user_context or {}}
        session = ChatSession.objects.create(
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            external_session_id=external_session_id,
            external_source=external_source,
            metadata=metadata
        )
        logger.info(f"Created session: {session.session_id} (tenant={tenant_id})")
        return session
    
    @sync_to_async(thread_sensitive=False)
    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get a session by ID."""
        try:
            return ChatSession.objects.get(
                session_id=session_id,
                tenant_id=self._tenant_id(),
            )
        except ChatSession.DoesNotExist:
            return None
    
    @sync_to_async(thread_sensitive=False)
    def get_session_by_external_id(
        self, 
        external_session_id: str,
        external_source: str,
        user_id: str
    ) -> Optional[ChatSession]:
        """Get a session by external session ID and source with user authorization."""
        try:
            return ChatSession.objects.get(
                external_session_id=external_session_id,
                external_source=external_source,
                user_id=user_id,
                tenant_id=self._tenant_id(),
            )
        except ChatSession.DoesNotExist:
            return None
    
    @sync_to_async(thread_sensitive=False)
    def list_sessions(
        self,
        user_id: str,
        status: str = 'active',
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[ChatSession], int]:
        """List sessions for a user."""
        queryset = ChatSession.objects.filter(
            tenant_id=self._tenant_id(),
            user_id=user_id,
            status=status
        ).order_by('-gmt_create')
        
        total = queryset.count()
        offset = (page - 1) * page_size
        sessions = list(queryset[offset:offset + page_size])
        
        return sessions, total
    
    @sync_to_async(thread_sensitive=False)
    def update_session(
        self,
        session_id: str,
        title: str = None,
        status: str = None,
        metadata: dict = None
    ) -> Optional[ChatSession]:
        """Update a session."""
        try:
            session = ChatSession.objects.get(
                session_id=session_id,
                tenant_id=self._tenant_id(),
            )
            
            if title is not None:
                session.title = title
            if status is not None:
                session.status = status
            if metadata is not None:
                session.metadata = metadata
            
            session.save()
            logger.info(f"Updated session: {session_id}")
            return session
            
        except ChatSession.DoesNotExist:
            return None
    
    @sync_to_async(thread_sensitive=False)
    def delete_session(self, session_id: str) -> bool:
        """Soft delete a session."""
        try:
            session = ChatSession.objects.get(
                session_id=session_id,
                tenant_id=self._tenant_id(),
            )
            session.status = 'deleted'
            session.save()
            logger.info(f"Deleted session: {session_id}")
            return True
        except ChatSession.DoesNotExist:
            return False
    
    @sync_to_async(thread_sensitive=False)
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str = 'text',
        parent_message_id: str = None,
        group_id: str = None,
        token_count: int = 0,
        metadata: dict = None
    ) -> ChatMessage:
        """Add a message to a session."""
        tenant_id = self._tenant_id()
        message = ChatMessage.objects.create(
            tenant_id=tenant_id,
            session_id=session_id,
            role=role,
            content=content,
            message_type=message_type,
            parent_message_id=parent_message_id,
            group_id=group_id,
            token_count=token_count,
            metadata=metadata or {}
        )
        
        # Update session title from first user message if empty
        if role == 'user':
            ChatSession.objects.filter(
                session_id=session_id, tenant_id=tenant_id, title=''
            ).update(title=content[:50] + ('...' if len(content) > 50 else ''))
        
        logger.debug(f"Added message: {message.message_id} to session: {session_id}")
        return message
    
    @sync_to_async(thread_sensitive=False)
    def get_messages(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[ChatMessage], int]:
        """Get messages for a session."""
        queryset = ChatMessage.objects.filter(
            session_id=session_id,
            tenant_id=self._tenant_id(),
        ).order_by('gmt_create')
        
        total = queryset.count()
        offset = (page - 1) * page_size
        messages = list(queryset[offset:offset + page_size])
        
        return messages, total
    
    @sync_to_async(thread_sensitive=False)
    def get_message(self, message_id: str) -> Optional[ChatMessage]:
        """Get a message by ID."""
        try:
            return ChatMessage.objects.get(
                message_id=message_id,
                tenant_id=self._tenant_id(),
            )
        except ChatMessage.DoesNotExist:
            return None
    
    @sync_to_async(thread_sensitive=False)
    def delete_message(self, message_id: str) -> bool:
        """Delete a message."""
        try:
            message = ChatMessage.objects.get(
                message_id=message_id,
                tenant_id=self._tenant_id(),
            )
            message.delete()
            logger.info(f"Deleted message: {message_id}")
            return True
        except ChatMessage.DoesNotExist:
            return False
    
    @sync_to_async(thread_sensitive=False)
    def get_conversation_history(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[dict]:
        """Get conversation history for LLM context."""
        messages = ChatMessage.objects.filter(
            session_id=session_id,
            tenant_id=self._tenant_id(),
            message_type='text'
        ).order_by('-gmt_create')[:limit]
        
        history = [
            {'role': m.role, 'content': m.content}
            for m in reversed(list(messages))
        ]
        
        return history

    @sync_to_async(thread_sensitive=False)
    def get_session_context(self, session_id: str) -> List[dict]:
        """Get full LLM context from SessionContext table.

        Returns the complete messages array (including tool_calls,
        tool results, observations) stored from previous turns.
        Returns empty list if no context exists yet (new session).
        """
        tenant_id = self._tenant_id()

        try:
            ctx = SessionContext.objects.get(
                session_id=session_id,
                tenant_id=tenant_id,
            )
            if ctx.messages:
                return ctx.messages
        except SessionContext.DoesNotExist:
            pass

        return []

    @sync_to_async(thread_sensitive=False)
    def save_session_context(
        self,
        session_id: str,
        messages: List[dict],
    ) -> None:
        """Save or update the full LLM context for a session."""
        tenant_id = self._tenant_id()
        SessionContext.objects.update_or_create(
            session_id=session_id,
            defaults={'messages': messages, 'tenant_id': tenant_id},
        )

    @sync_to_async(thread_sensitive=False)
    def get_trace_data(
        self,
        session_id: str,
        after_message_id: str | None = None,
    ) -> dict | None:
        """Get trace data for a session, organized by conversations.

        Returns conversation-paired trace data for the trace observer page.
        Supports incremental polling via ``after_message_id``.

        Args:
            session_id: The session to fetch trace data for.
            after_message_id: If provided, only return conversations whose
                assistant message was modified after this message's ``gmt_modified``.

        Returns:
            Dict with ``session_id``, ``session_title``, ``is_streaming``,
            ``conversations``, and ``last_message_id``.  Returns ``None``
            if the session does not exist.
        """
        tenant_id = self._tenant_id()

        try:
            session = ChatSession.objects.get(
                session_id=session_id,
                tenant_id=tenant_id,
            )
        except ChatSession.DoesNotExist:
            return None

        # Query all messages for this session ordered by creation time
        all_messages = list(
            ChatMessage.objects.filter(
                session_id=session_id,
                tenant_id=tenant_id,
            ).order_by('gmt_create')
        )

        # Build lookup maps
        user_messages: dict[str, ChatMessage] = {}
        assistant_messages: list[ChatMessage] = []
        for msg in all_messages:
            if msg.role == 'user':
                user_messages[str(msg.message_id)] = msg
            elif msg.role == 'assistant':
                assistant_messages.append(msg)

        # Determine cutoff for incremental polling
        cutoff_time = None
        if after_message_id:
            for msg in assistant_messages:
                if str(msg.message_id) == after_message_id:
                    cutoff_time = msg.gmt_modified
                    break

        # Build conversation pairs
        conversations = []
        is_streaming = False
        last_message_id = None

        for assistant_msg in assistant_messages:
            metadata = assistant_msg.metadata or {}
            stream_status = metadata.get('stream_status', 'completed')
            trace = metadata.get('trace', [])

            if stream_status == 'streaming':
                is_streaming = True

            # Skip if before cutoff (incremental polling).
            # Always include streaming messages – their trace data keeps
            # growing but gmt_modified is not updated by QuerySet.update().
            if cutoff_time and assistant_msg.gmt_modified <= cutoff_time and stream_status != 'streaming':
                continue

            # Find paired user message
            parent_id = assistant_msg.parent_message_id
            user_msg = user_messages.get(parent_id) if parent_id else None

            conversations.append({
                'user_message_id': str(user_msg.message_id) if user_msg else None,
                'user_content': user_msg.content if user_msg else '',
                'assistant_message_id': str(assistant_msg.message_id),
                'stream_status': stream_status,
                'trace': trace,
                'gmt_create': assistant_msg.gmt_create.isoformat(),
            })

            last_message_id = str(assistant_msg.message_id)

        return {
            'session_id': str(session.session_id),
            'session_title': session.title or '',
            'is_streaming': is_streaming,
            'conversations': conversations,
            'last_message_id': last_message_id,
        }

    @sync_to_async(thread_sensitive=False)
    def update_message_content(
        self,
        message_id: str,
        content: str,
        metadata: dict = None,
    ) -> None:
        """Update an existing message's content and metadata.

        Used for incremental saving during streaming.
        """
        update_fields = {'content': content}
        if metadata is not None:
            update_fields['metadata'] = metadata
        ChatMessage.objects.filter(
            message_id=message_id,
            tenant_id=self._tenant_id(),
        ).update(**update_fields)
