"""
WebSocket consumer for real-time chat communication.
"""
import json
import logging
import os
from typing import Optional
from channels.generic.websocket import AsyncWebsocketConsumer

from ...services.websocket_service import WebSocketService
from ...services.session_service import SessionService
from ...tenant.context import tenant_id_var, set_current_tenant_id
from ...tenant.registry import get_tenant_registry

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for handling real-time chat sessions.
    
    Supports:
    - Token-based tenant authentication
    - Real-time streaming responses
    - Session-based conversations
    - Thought/Action/Observation streaming for ReAct agent
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.tenant_id: Optional[str] = None
        self.websocket_service = WebSocketService()
    
    async def connect(self):
        """
        Handle WebSocket connection.

        Authenticates via Bearer token, extracts session_id from URL.
        In local mode (SERVER_ENV=local), uses 'example' tenant when no token provided.
        """
        # Get session_id from URL path
        self.session_id = self.scope['url_route']['kwargs'].get('session_id')

        if not self.session_id:
            logger.warning("Connection rejected: missing session_id")
            await self.close(code=4001)
            return

        # Authenticate via token
        raw_token = self._get_token()
        if not raw_token:
            # Local development mode: use 'example' tenant when no token
            server_env = os.environ.get('SERVER_ENV', '').lower()
            if server_env == 'local':
                logger.info("No token provided in local mode, using 'example' tenant")
                self.tenant_id = 'example'
            else:
                logger.warning("Connection rejected: missing token")
                await self.close(code=4003)
                return
        else:
            registry = get_tenant_registry()
            self.tenant_id = registry.get_tenant_id_by_token(raw_token)
            if not self.tenant_id:
                logger.warning("Connection rejected: invalid token")
                await self.close(code=4003)
                return

        # Extract user_id from query string or headers
        self.user_id = self._get_user_id()

        await self.accept()

        logger.info(
            f"WebSocket connected: session={self.session_id}, "
            f"tenant={self.tenant_id}, user={self.user_id}"
        )

        # Send connection acknowledgment
        await self.send_json({
            'type': 'connected',
            'session_id': self.session_id,
            'message': 'Connection established'
        })
    
    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection.
        """
        logger.info(
            f"WebSocket disconnected: session={self.session_id}, "
            f"user={self.user_id}, code={close_code}"
        )
    
    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle incoming WebSocket messages.

        Expected message format:
        {
            "type": "chat",
            "message": "user message content",
            "metadata": {},  // optional
            "interrupt_message": "..."  // optional, message that triggered interrupt
        }
        """
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON received: {e}")
            await self.send_json({
                'type': 'error',
                'content': 'Invalid JSON format',
                'metadata': {}
            })
            return

        message_type = data.get('type', 'chat')

        if message_type == 'chat':
            await self._handle_chat_message(data)
        elif message_type == 'ping':
            await self._handle_ping()
        elif message_type == 'stop':
            await self._handle_stop()
        elif message_type == 'interrupt':
            await self._handle_interrupt(data)
        elif message_type == 'tool_confirm_response':
            await self._handle_tool_confirm_response(data)
        else:
            await self.send_json({
                'type': 'error',
                'content': f'Unknown message type: {message_type}',
                'metadata': {}
            })
    
    async def _handle_chat_message(self, data: dict):
        """
        Process a chat message and stream response.
        """
        message = data.get('message', '').strip()
        interrupt_message = data.get('interrupt_message', '').strip()
        snapshot_id = data.get('snapshot_id') or data.get('metadata', {}).get('snapshot_id')
        config = data.get('config')

        if not message:
            await self.send_json({
                'type': 'error',
                'content': 'Empty message',
                'metadata': {}
            })
            return

        logger.info(f"Chat message received: session={self.session_id}, length={len(message)}, interrupt={bool(interrupt_message)}, snapshot={bool(snapshot_id)}")

        # Send acknowledgment
        await self.send_json({
            'type': 'ack',
            'content': '',
            'metadata': {'message_received': True}
        })

        try:
            # Set tenant context for this chat processing
            token = set_current_tenant_id(self.tenant_id)
            try:
                # Stream response chunks
                # Pass interrupt_message and snapshot_id to websocket_service
                async for chunk in self.websocket_service.handle_message(
                    session_id=self.session_id,
                    message=message,
                    user_id=self.user_id or 'anonymous',
                    interrupt_message=interrupt_message if interrupt_message else None,
                    snapshot_id=snapshot_id if snapshot_id else None,
                    config=config,
                ):
                    await self.send_json(chunk)
            finally:
                tenant_id_var.reset(token)
                
        except Exception as e:
            logger.exception(f"Error processing chat message: {e}")
            await self.send_json({
                'type': 'error',
                'content': str(e),
                'metadata': {}
            })
    
    async def _handle_ping(self):
        """
        Handle ping message for connection keep-alive.
        """
        await self.send_json({
            'type': 'pong',
            'content': '',
            'metadata': {}
        })
    
    async def _handle_stop(self):
        """
        Handle stop message to cancel current generation.
        """
        # Send interrupt signal to chat_service
        from ...services.chat_service import ChatService
        chat_service = ChatService()
        interrupted = await chat_service.interrupt_session(
            self.session_id,
            interrupt_message=""
        )

        if interrupted:
            await self.send_json({
                'type': 'stopped',
                'content': 'Generation stopped',
                'metadata': {}
            })
        else:
            await self.send_json({
                'type': 'error',
                'content': 'No active stream to stop',
                'metadata': {}
            })

    async def _handle_interrupt(self, data: dict):
        """
        Handle interrupt message to cancel current generation and merge with new message.
        """
        interrupt_message = data.get('interrupt_message', '')

        if not interrupt_message:
            await self.send_json({
                'type': 'error',
                'content': 'Interrupt message is required',
                'metadata': {}
            })
            return

        # Send interrupt signal to chat_service
        from ...services.chat_service import ChatService
        chat_service = ChatService()
        interrupted = await chat_service.interrupt_session(
            self.session_id,
            interrupt_message=interrupt_message
        )

        if interrupted:
            await self.send_json({
                'type': 'interrupted',
                'content': 'Stream interrupted, merging messages...',
                'metadata': {'interrupt_message': interrupt_message}
            })
        else:
            await self.send_json({
                'type': 'error',
                'content': 'No active stream to interrupt',
                'metadata': {}
            })

    async def _handle_tool_confirm_response(self, data: dict):
        """Handle tool confirmation response from client."""
        confirmation_id = data.get('confirmation_id', '').strip()
        approved = data.get('approved', False)

        if not confirmation_id:
            await self.send_json({
                'type': 'error',
                'content': 'confirmation_id is required',
                'metadata': {},
            })
            return

        from ...agent.hooks.confirmation_store import get_confirmation_store
        store = get_confirmation_store()
        success = await store.respond(confirmation_id, approved)

        if success:
            logger.info(
                "Tool confirmation %s: %s (user=%s)",
                confirmation_id, "approved" if approved else "rejected", self.user_id,
            )
        else:
            logger.warning(
                "Tool confirmation %s not found or already resolved", confirmation_id
            )
    
    async def send_json(self, data: dict):
        """
        Send JSON data through WebSocket.
        """
        await self.send(text_data=json.dumps(data, ensure_ascii=False))
    
    def _get_token(self) -> Optional[str]:
        """Extract authentication token from connection scope.

        Checks:
        1. Query string parameter ``token``
        2. ``Authorization: Bearer <token>`` header
        """
        # Try query string
        query_string = self.scope.get('query_string', b'').decode()
        if query_string:
            params = dict(
                param.split('=') for param in query_string.split('&')
                if '=' in param
            )
            if 'token' in params:
                return params['token']

        # Try Authorization header
        headers = dict(self.scope.get('headers', []))
        auth_value = headers.get(b'authorization', b'').decode()
        if auth_value.startswith('Bearer '):
            return auth_value[7:].strip() or None

        return None

    def _get_user_id(self) -> Optional[str]:
        """
        Extract user_id from connection scope.
        
        Checks:
        1. Query string parameter
        2. Headers
        3. Authenticated user
        """
        # Try query string
        query_string = self.scope.get('query_string', b'').decode()
        if query_string:
            params = dict(
                param.split('=') for param in query_string.split('&')
                if '=' in param
            )
            if 'user_id' in params:
                return params['user_id']
        
        # Try headers
        headers = dict(self.scope.get('headers', []))
        if b'x-user-id' in headers:
            return headers[b'x-user-id'].decode()
        
        # Try authenticated user
        user = self.scope.get('user')
        if user and hasattr(user, 'id') and user.is_authenticated:
            return str(user.id)
        
        return None
