"""
Message API views.
"""
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...services.session_service import SessionService

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class MessageListView(View):
    """
    Handle message list for a session.
    
    GET /chatbot/api/sessions/{session_id}/messages/
    """
    
    async def get(self, request: HttpRequest, session_id: str) -> JsonResponse:
        """List messages for a session."""
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        
        session_service = SessionService()
        messages, total = await session_service.get_messages(
            session_id=session_id,
            page=page,
            page_size=page_size
        )
        
        return JsonResponse({
            'messages': [
                {
                    'message_id': str(m.message_id),
                    'role': m.role,
                    'content': m.content,
                    'message_type': m.message_type,
                    'parent_message_id': m.parent_message_id,
                    'group_id': m.group_id,
                    'token_count': m.token_count,
                    'metadata': m.metadata,
                    'gmt_create': m.gmt_create.isoformat(),
                }
                for m in messages
            ],
            'total': total,
            'page': page,
            'page_size': page_size
        })


@method_decorator(csrf_exempt, name='dispatch')
class MessageDetailView(View):
    """
    Handle single message operations.
    
    GET /chatbot/api/messages/{message_id}/
    DELETE /chatbot/api/messages/{message_id}/
    """
    
    async def get(self, request: HttpRequest, message_id: str) -> JsonResponse:
        """Get message details."""
        session_service = SessionService()
        message = await session_service.get_message(message_id)
        
        if not message:
            return JsonResponse({'error': 'Message not found'}, status=404)
        
        return JsonResponse({
            'message_id': str(message.message_id),
            'session_id': str(message.session_id),
            'role': message.role,
            'content': message.content,
            'message_type': message.message_type,
            'parent_message_id': message.parent_message_id,
            'group_id': message.group_id,
            'token_count': message.token_count,
            'metadata': message.metadata,
            'gmt_create': message.gmt_create.isoformat(),
        })
    
    async def delete(self, request: HttpRequest, message_id: str) -> JsonResponse:
        """Delete a message."""
        session_service = SessionService()
        success = await session_service.delete_message(message_id)
        
        if not success:
            return JsonResponse({'error': 'Message not found'}, status=404)
        
        return JsonResponse({'success': True})
