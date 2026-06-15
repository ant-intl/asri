"""
Version snapshot API views.
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...services.version_service import VersionService
from ...entities import VersionSnapshot

logger = logging.getLogger(__name__)


def _tenant_id(request) -> str:
    """Tenant ID from middleware-set ``request.tenant_id``, falling back to ``'example'``."""
    tenant_id = getattr(request, 'tenant_id', None)
    return tenant_id if isinstance(tenant_id, str) and tenant_id else 'example'


def serialize_version(v: VersionSnapshot, include_data: bool = False) -> dict:
    """Serialize a VersionSnapshot to dict.

    Args:
        v: VersionSnapshot instance.
        include_data: Whether to include snapshot_data in the response.

    Returns:
        Serialized dict.
    """
    result = {
        'id': str(v.id),
        'entity_type': v.entity_type,
        'entity_id': v.entity_id,
        'version_number': v.version_number,
        'label': v.label,
        'description': v.description,
        'is_active': v.is_active,
        'created_by': v.created_by,
        'gmt_create': v.gmt_create.isoformat() if v.gmt_create else None,
        'gmt_modified': v.gmt_modified.isoformat() if v.gmt_modified else None,
    }
    if include_data:
        result['snapshot_data'] = v.snapshot_data
    return result


@method_decorator(csrf_exempt, name='dispatch')
class VersionListView(View):
    """List and create version snapshots.

    GET /chatbot/api/admin/versions/?entity_type=x&entity_id=y
    POST /chatbot/api/admin/versions/
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """List version snapshots for an entity."""
        entity_type = request.GET.get('entity_type', '')
        entity_id = request.GET.get('entity_id', '')

        if not entity_type or not entity_id:
            return JsonResponse(
                {'error': 'entity_type and entity_id are required'},
                status=400,
            )

        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        versions, total = VersionService.list_versions(
            entity_type, entity_id, page, page_size, tenant_id=_tenant_id(request),
        )
        data = [serialize_version(v) for v in versions]
        return JsonResponse({'versions': data, 'total': total})

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a version snapshot manually (with label)."""
        try:
            data = json.loads(request.body)
            entity_type = data.get('entity_type', '')
            entity_id = data.get('entity_id', '')

            if not entity_type or not entity_id:
                return JsonResponse(
                    {'error': 'entity_type and entity_id are required'},
                    status=400,
                )

            snapshot = VersionService.create_snapshot(
                entity_type=entity_type,
                entity_id=entity_id,
                label=data.get('label', ''),
                description=data.get('description', ''),
                created_by=data.get('created_by', ''),
                tenant_id=_tenant_id(request),
            )
            return JsonResponse(serialize_version(snapshot), status=201)

        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Create version snapshot error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class VersionDetailView(View):
    """Retrieve, update, and delete version snapshots.

    GET /chatbot/api/admin/versions/{version_id}/
    PUT /chatbot/api/admin/versions/{version_id}/
    DELETE /chatbot/api/admin/versions/{version_id}/
    """

    def get(self, request: HttpRequest, version_id: str) -> JsonResponse:
        """Get version snapshot details (including snapshot_data)."""
        snapshot = VersionService.get_version(version_id, tenant_id=_tenant_id(request))
        if snapshot is None:
            return JsonResponse({'error': 'Version not found'}, status=404)
        return JsonResponse(serialize_version(snapshot, include_data=True))

    def put(self, request: HttpRequest, version_id: str) -> JsonResponse:
        """Update version label and description."""
        try:
            data = json.loads(request.body)
            snapshot = VersionService.update_version_label(
                version_id=version_id,
                label=data.get('label', ''),
                description=data.get('description', ''),
                tenant_id=_tenant_id(request),
            )
            if snapshot is None:
                return JsonResponse({'error': 'Version not found'}, status=404)
            return JsonResponse(serialize_version(snapshot))
        except Exception as e:
            logger.exception(f"Update version error: {e}")
            return JsonResponse({'error': str(e)}, status=500)

    def delete(self, request: HttpRequest, version_id: str) -> JsonResponse:
        """Delete a version snapshot (cannot delete active version)."""
        try:
            deleted = VersionService.delete_version(version_id, tenant_id=_tenant_id(request))
            if deleted:
                return JsonResponse({}, status=204)
            return JsonResponse({'error': 'Version not found'}, status=404)
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Delete version error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class VersionActivateView(View):
    """Activate (rollback to) a version snapshot.

    POST /chatbot/api/admin/versions/{version_id}/activate/
    """

    def post(self, request: HttpRequest, version_id: str) -> JsonResponse:
        """Activate a version snapshot."""
        try:
            snapshot = VersionService.activate_version(version_id, tenant_id=_tenant_id(request))
            return JsonResponse({
                'success': True,
                'message': (
                    f"Activated version v{snapshot.version_number} "
                    f"for {snapshot.entity_type}/{snapshot.entity_id}"
                ),
                'version': serialize_version(snapshot),
            })
        except ValueError as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Activate version error: {e}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class VersionDiffView(View):
    """Compare two version snapshots.

    GET /chatbot/api/admin/versions/diff/?version_a=x&version_b=y
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """Get diff between two version snapshots."""
        version_a = request.GET.get('version_a', '')
        version_b = request.GET.get('version_b', '')

        if not version_a or not version_b:
            return JsonResponse(
                {'error': 'version_a and version_b are required'},
                status=400,
            )

        try:
            diff_result = VersionService.compute_diff(version_a, version_b, tenant_id=_tenant_id(request))
            return JsonResponse(diff_result)
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception(f"Compute version diff error: {e}")
            return JsonResponse({'error': str(e)}, status=500)
