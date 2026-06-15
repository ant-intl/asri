"""
Poll Chat API Views - HTTP Long Polling for streaming simulation.

Provides three endpoints:
1. POST /poll/chat/init/ - Initiate a polling chat session
2. POST /poll/chat/chunks/ - Poll for incremental chunks
3. POST /poll/chat/cancel/{user_message_id}/ - Cancel a polling task
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...services.long_poll_service import long_poll_service
from ...services.session_service import SessionService

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class PollChatInitView(View):
    """
    Initiate a new polling chat session.
    
    Creates a background task that runs stream_chat() and returns
    the user_message_id for polling.
    """
    
    async def post(self, request: HttpRequest):
        try:
            data = json.loads(request.body)
            session_id = data.get('session_id')
            message = data.get('message')
            user_id = data.get('user_id', 'anonymous')
            tenant_id = getattr(request, 'tenant_id', None)
            
            if not message:
                return JsonResponse(
                    {'error': 'message is required'},
                    status=400,
                )
            
            if not session_id:
                return JsonResponse(
                    {'error': 'session_id is required'},
                    status=400,
                )
            
            session_service = SessionService()
            session = await session_service.get_session(session_id)
            if not session:
                return JsonResponse(
                    {'error': 'Session not found'},
                    status=404,
                )
            
            # Create and start polling task (runs async in ASGI environment)
            task = await long_poll_service.create_and_start_task(
                session=session,
                message=message,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            
            return JsonResponse({
                'user_message_id': task.user_message_id,
                'session_id': session.session_id,
                'external_session_id': session.external_session_id,
                'status': 'running',
            })
            
        except Exception as e:
            logger.exception("Failed to create polling task")
            return JsonResponse(
                {'error': f'Internal server error: {str(e)}'},
                status=500,
            )


@method_decorator(csrf_exempt, name='dispatch')
class PollChatChunksView(View):
    """
    Poll for incremental chunks from a running polling task.
    
    Blocks for up to 30 seconds if no new chunks are available.
    Returns immediately if new chunks exist or task is complete.
    """
    
    async def post(self, request: HttpRequest):
        try:
            data = json.loads(request.body)
            user_message_id = data.get('user_message_id', '')
            if not user_message_id:
                return JsonResponse({'error': 'user_message_id is required'}, status=400)
            last_offset = data.get('last_offset', 0)
            timeout = data.get('timeout', 30.0)

            last_offset = int(last_offset)
            timeout = int(timeout)
            
            # Poll for chunks (may block up to 30 seconds)
            result = await long_poll_service.poll_chunks(
                user_message_id=user_message_id,
                last_offset=last_offset,
                timeout=timeout,
            )
            
            return JsonResponse(result)
            
        except Exception as e:
            logger.exception(f"Failed to poll chunks for {user_message_id}")
            return JsonResponse(
                {'error': f'Internal server error: {str(e)}'},
                status=500,
            )


@method_decorator(csrf_exempt, name='dispatch')
class PollChatCancelView(View):
    """
    Cancel a running polling task.
    """
    
    async def post(self, request: HttpRequest, user_message_id: str):
        try:
            cancelled = await long_poll_service.cancel_task(
                user_message_id=user_message_id,
            )
            
            return JsonResponse({
                'user_message_id': user_message_id,
                'cancelled': cancelled,
            })
            
        except Exception as e:
            logger.exception(f"Failed to cancel polling task {user_message_id}")
            return JsonResponse(
                {'error': f'Internal server error: {str(e)}'},
                status=500,
            )
