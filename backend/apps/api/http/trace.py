"""
Trace API views for session observation.
"""
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View

from ...services.session_service import SessionService

logger = logging.getLogger(__name__)


class SessionTraceView(View):
    """Return trace data for a session, organized by conversations.

    GET /chatbot/api/admin/sessions/{session_id}/trace/

    Admin endpoint using fixed 'example' tenant (handled by middleware).
    Supports incremental polling via ``after_id`` query parameter.
    """

    async def get(self, request: HttpRequest, session_id: str) -> JsonResponse:
        """Get trace data for a session."""
        after_id = request.GET.get('after_id')

        session_service = SessionService()
        result = await session_service.get_trace_data(
            session_id=session_id,
            after_message_id=after_id,
        )

        if result is None:
            return JsonResponse({'error': 'Session not found'}, status=404)

        return JsonResponse(result)
