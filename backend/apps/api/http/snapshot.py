"""
Session Snapshot API views.

Provides CRUD endpoints for session snapshots and a config preview endpoint.
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from asgiref.sync import sync_to_async

from ...services.snapshot_service import SnapshotService
from ...entities import ChatSession
from ...tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


def _tenant_id() -> str:
    return get_current_tenant_id() or 'default'


@method_decorator(csrf_exempt, name='dispatch')
class SnapshotListView(View):
    """List and create session snapshots."""

    async def get(self, request: HttpRequest) -> JsonResponse:
        """List snapshots with pagination.

        Query params: page (default 1), page_size (default 20)
        """
        tenant_id = _tenant_id()
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        result = await SnapshotService.list_snapshots(
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
        )
        return JsonResponse(result)

    async def post(self, request: HttpRequest) -> JsonResponse:
        """Create a snapshot from a session.

        Body: { session_id, name, description (optional) }
        """
        tenant_id = _tenant_id()

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        session_id = data.get('session_id')
        name = data.get('name', '').strip()
        description = data.get('description', '')
        settings = data.get('settings', {})

        if not session_id:
            return JsonResponse({'error': 'session_id is required'}, status=400)
        if not name:
            return JsonResponse({'error': 'name is required'}, status=400)

        # Fetch session
        try:
            session = await sync_to_async(ChatSession.objects.get)(
                session_id=session_id,
                tenant_id=tenant_id,
            )
        except ChatSession.DoesNotExist:
            return JsonResponse({'error': 'Session not found'}, status=404)

        created_by = request.META.get('HTTP_X_USER_ID', '') or ''

        try:
            snap = await SnapshotService.create_from_session(
                session=session,
                name=name,
                description=description,
                settings=settings,
                created_by=created_by,
                tenant_id=tenant_id,
            )
            return JsonResponse({
                'id': str(snap.id),
                'name': snap.name,
                'gmt_create': snap.gmt_create.isoformat() if snap.gmt_create else None,
            }, status=201)
        except Exception as e:
            logger.exception("Failed to create snapshot: %s", e)
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class SnapshotDetailView(View):
    """Handle single snapshot operations."""

    async def get(self, request: HttpRequest, snapshot_id: str) -> JsonResponse:
        """Get snapshot details."""
        tenant_id = _tenant_id()
        snap = await SnapshotService.get_snapshot(snapshot_id, tenant_id)
        if snap is None:
            return JsonResponse({'error': 'Snapshot not found'}, status=404)
        return JsonResponse(snap)

    async def put(self, request: HttpRequest, snapshot_id: str) -> JsonResponse:
        """Update snapshot name/description."""
        tenant_id = _tenant_id()

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        snap = await SnapshotService.update_snapshot(
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            name=data.get('name'),
            description=data.get('description'),
        )
        if snap is None:
            return JsonResponse({'error': 'Snapshot not found'}, status=404)
        return JsonResponse(snap)

    async def delete(self, request: HttpRequest, snapshot_id: str) -> JsonResponse:
        """Soft-delete a snapshot."""
        tenant_id = _tenant_id()
        ok = await SnapshotService.delete_snapshot(snapshot_id, tenant_id)
        if not ok:
            return JsonResponse({'error': 'Snapshot not found'}, status=404)
        return JsonResponse({'success': True})


@method_decorator(csrf_exempt, name='dispatch')
class SnapshotConfigPreviewView(View):
    """Preview resolved configuration for a snapshot."""

    async def get(self, request: HttpRequest, snapshot_id: str) -> JsonResponse:
        """Get snapshot config preview with resolved LLM provider info."""
        tenant_id = _tenant_id()
        preview = await SnapshotService.get_snapshot_config_preview(snapshot_id, tenant_id)
        if preview is None:
            return JsonResponse({'error': 'Snapshot not found'}, status=404)
        return JsonResponse(preview)
