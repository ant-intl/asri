"""
WebSocket service for streaming chat responses.
"""
import logging
from typing import Dict, Any, AsyncGenerator

from .chat_service import ChatService
from .session_service import SessionService

logger = logging.getLogger(__name__)


class WebSocketService:
    """
    Service for handling WebSocket chat streaming.

    Wraps ChatService to provide WebSocket-specific functionality.
    """

    def __init__(self):
        self.chat_service = ChatService()
        self.session_service = SessionService()

    async def handle_message(
        self,
        session_id: str,
        message: str,
        user_id: str,
        interrupt_message: str | None = None,
        snapshot_id: str | None = None,
        config: dict | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Handle a WebSocket message and yield response chunks.

        Args:
            session_id: The session identifier
            message: User's message
            user_id: User identifier
            interrupt_message: Optional message that triggered interrupt
            snapshot_id: Optional snapshot ID for frozen config

        Yields:
            Dict chunks containing response data
        """
        # Get session to read config from metadata
        session = await self.session_service.get_session(session_id)
        logger.debug("chat session metadata: %s", session.metadata)

        if not session:
            yield {
                'type': 'error',
                'content': 'Session not found',
                'metadata': {}
            }
            return

        try:
            # Use snapshot config if snapshot_id is provided
            if snapshot_id:
                stream_gen = self.chat_service.stream_chat_with_snapshot(
                    session=session,
                    message=message,
                    user_id=user_id,
                    snapshot_id=snapshot_id,
                    config=config,
                )
            else:
                stream_gen = self.chat_service.stream_chat(
                    session=session,
                    message=message,
                    user_id=user_id,
                    interrupt_message=interrupt_message,
                    config=config,
                )

            async for chunk in stream_gen:
                if chunk.get('type') == 'done':
                    yield {
                        'type': 'done',
                        'content': '',
                        'message_id': chunk.get('message_id'),
                        'trace': chunk.get('trace', []),
                        'metadata': {}
                    }
                else:
                    # Pass through all fields from the new unified format
                    # Includes: type, content, timestamp, status, tool_name,
                    # parameters, result, tool_call_id, metadata
                    yield chunk
        except Exception as e:
            logger.exception(f"WebSocket error: {e}")
            yield {
                'type': 'error',
                'content': str(e),
                'metadata': {}
            }
