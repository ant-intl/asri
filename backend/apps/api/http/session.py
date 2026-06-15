"""
Session API views.
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...services.session_service import SessionService

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class SessionListView(View):
    """
    Handle session list and creation.
    
    GET /chatbot/api/sessions/
    POST /chatbot/api/sessions/
    """
    
    async def get(self, request: HttpRequest) -> JsonResponse:
        """List sessions for the authenticated user."""
        # Use user_id from middleware (extracted from header/query string)
        user_id = getattr(request, 'user_id', 'anonymous')
        status = request.GET.get('status', 'active')
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        
        session_service = SessionService()
        sessions, total = await session_service.list_sessions(
            user_id=user_id,
            status=status,
            page=page,
            page_size=page_size
        )
        
        return JsonResponse({
            'sessions': [
                {
                    'session_id': str(s.session_id),
                    'external_source': s.external_source,
                    'external_session_id': s.external_session_id,
                    'title': s.title,
                    'status': s.status,
                    'agent_type': s.agent_type,
                    'gmt_create': s.gmt_create.isoformat(),
                    'gmt_modified': s.gmt_modified.isoformat(),
                }
                for s in sessions
            ],
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    async def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new session for the authenticated user."""
        try:
            data = json.loads(request.body)

            # Use user_id from middleware (extracted from header/query string)
            user_id = getattr(request, 'user_id', 'anonymous')
            title = data.get('title', '')
            # user_context is a separate parameter, not placed inside metadata
            user_context = data.get('user_context', {})
            external_source = data.get('external_source')
            external_session_id = data.get('external_session_id')

            session_service = SessionService()
            session = await session_service.create_session(
                user_id=user_id,
                title=title,
                user_context=user_context,
                external_session_id=external_session_id,
                external_source=external_source
            )

            return JsonResponse({
                'session_id': str(session.session_id),
                'external_source': session.external_source,
                'external_session_id': session.external_session_id,
                'title': session.title,
                'status': session.status,
                'metadata': session.metadata,
                'gmt_create': session.gmt_create.isoformat(),
            }, status=201)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception:
            logger.exception("Create session error")
            return JsonResponse({'error': 'An internal error occurred'}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class SessionDetailView(View):
    """
    Handle single session operations.
    
    GET /chatbot/api/sessions/{session_id}/
    PUT /chatbot/api/sessions/{session_id}/
    DELETE /chatbot/api/sessions/{session_id}/
    """
    
    async def get(self, request: HttpRequest, session_id: str) -> JsonResponse:
        """Get session details with ownership validation."""
        session_service = SessionService()
        session = await session_service.get_session(session_id)
        
        if not session:
            return JsonResponse({'error': 'Session not found'}, status=404)
        
        # Validate session ownership
        request_user_id = getattr(request, 'user_id', 'anonymous')
        if session.user_id != request_user_id:
            logger.warning(
                "Permission denied: user=%s attempted to access session=%s owned by user=%s",
                request_user_id,
                session_id,
                session.user_id,
            )
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        return JsonResponse({
            'session_id': str(session.session_id),
            'external_source': session.external_source,
            'external_session_id': session.external_session_id,
            'user_id': session.user_id,
            'title': session.title,
            'status': session.status,
            'agent_type': session.agent_type,
            'metadata': session.metadata,
            'gmt_create': session.gmt_create.isoformat(),
            'gmt_modified': session.gmt_modified.isoformat(),
        })
    
    async def put(self, request: HttpRequest, session_id: str) -> JsonResponse:
        """Update session with ownership validation."""
        try:
            # Validate session ownership before update
            session_service = SessionService()
            session = await session_service.get_session(session_id)
            
            if not session:
                return JsonResponse({'error': 'Session not found'}, status=404)
            
            request_user_id = getattr(request, 'user_id', 'anonymous')
            if session.user_id != request_user_id:
                logger.warning(
                    "Permission denied: user=%s attempted to update session=%s owned by user=%s",
                    request_user_id,
                    session_id,
                    session.user_id,
                )
                return JsonResponse({'error': 'Permission denied'}, status=403)
            
            data = json.loads(request.body)
            
            session = await session_service.update_session(
                session_id=session_id,
                title=data.get('title'),
                status=data.get('status'),
                metadata=data.get('metadata')
            )
            
            if not session:
                return JsonResponse({'error': 'Session not found'}, status=404)
            
            return JsonResponse({
                'session_id': str(session.session_id),
                'title': session.title,
                'status': session.status,
                'gmt_modified': session.gmt_modified.isoformat(),
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception:
            logger.exception("Update session error")
            return JsonResponse({'error': 'An internal error occurred'}, status=500)
    
    async def delete(self, request: HttpRequest, session_id: str) -> JsonResponse:
        """Delete (soft) session with ownership validation."""
        session_service = SessionService()
        
        # Validate session ownership before delete
        session = await session_service.get_session(session_id)
        if not session:
            return JsonResponse({'error': 'Session not found'}, status=404)
        
        request_user_id = getattr(request, 'user_id', 'anonymous')
        if session.user_id != request_user_id:
            logger.warning(
                "Permission denied: user=%s attempted to delete session=%s owned by user=%s",
                request_user_id,
                session_id,
                session.user_id,
            )
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        success = await session_service.delete_session(session_id)
        
        if not success:
            return JsonResponse({'error': 'Session not found'}, status=404)
        
        return JsonResponse({'success': True})
