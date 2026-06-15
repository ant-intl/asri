"""
Hook configuration API views.

Provides CRUD endpoints for HookConfig management:
- GET  /api/admin/hooks/         → list all hooks for tenant
- POST /api/admin/hooks/         → create new hook
- GET  /api/admin/hooks/<id>/    → get hook detail
- PUT  /api/admin/hooks/<id>/    → update hook
- DELETE /api/admin/hooks/<id>/  → delete (soft-delete)
- POST /api/admin/hooks/<id>/toggle/ → toggle enable/disable
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...entities import HookConfig
from ...tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


def _tenant_id() -> str:
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        raise ValueError("tenant_id not set in request context")
    return tenant_id


@method_decorator(csrf_exempt, name='dispatch')
class HookListView(View):
    """Handle Hook list and creation."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """List all hooks for the current tenant."""
        tenant_id = _tenant_id()
        hooks = HookConfig.objects.filter(tenant_id=tenant_id)
        hooks_list = [
            {
                'id': hook.id,
                'tenant_id': hook.tenant_id,
                'hook_type': hook.hook_type,
                'hook_name': hook.hook_name,
                'description': hook.description,
                'is_active': hook.is_active,
                'config_json': hook.config_json,
                'gmt_create': hook.gmt_create.isoformat() if hook.gmt_create else None,
                'gmt_modified': hook.gmt_modified.isoformat() if hook.gmt_modified else None,
            }
            for hook in hooks
        ]
        return JsonResponse({'hooks': hooks_list})

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new hook configuration."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        hook_type = data.get('hook_type', '').strip()
        hook_name = data.get('hook_name', '').strip()

        if not hook_type:
            return JsonResponse({'error': 'hook_type is required'}, status=400)
        if not hook_name:
            return JsonResponse({'error': 'hook_name is required'}, status=400)

        tenant_id = _tenant_id()

        # Check uniqueness
        if HookConfig.objects.filter(tenant_id=tenant_id, hook_name=hook_name).exists():
            return JsonResponse(
                {'error': f'Hook "{hook_name}" already exists for this tenant'},
                status=409,
            )

        try:
            hook = HookConfig.objects.create(
                tenant_id=tenant_id,
                hook_type=hook_type,
                hook_name=hook_name,
                description=data.get('description', ''),
                is_active=data.get('is_active', True),
                config_json=data.get('config_json', {}),
            )
            return JsonResponse(
                {'id': hook.id, 'hook_name': hook.hook_name},
                status=201,
            )
        except Exception as e:
            logger.exception(f"Create hook error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class HookDetailView(View):
    """Handle single hook operations: get, update, delete, toggle."""

    def get(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Get hook details."""
        try:
            hook = HookConfig.objects.get(pk=pk, tenant_id=_tenant_id())
        except HookConfig.DoesNotExist:
            return JsonResponse({'error': 'Hook not found'}, status=404)

        return JsonResponse({
            'id': hook.id,
            'tenant_id': hook.tenant_id,
            'hook_type': hook.hook_type,
            'hook_name': hook.hook_name,
            'description': hook.description,
            'is_active': hook.is_active,
            'config_json': hook.config_json,
            'gmt_create': hook.gmt_create.isoformat() if hook.gmt_create else None,
            'gmt_modified': hook.gmt_modified.isoformat() if hook.gmt_modified else None,
        })

    def put(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Update hook configuration."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        try:
            hook = HookConfig.objects.get(pk=pk, tenant_id=_tenant_id())
        except HookConfig.DoesNotExist:
            return JsonResponse({'error': 'Hook not found'}, status=404)

        updatable_fields = [
            'hook_type', 'hook_name', 'description', 'is_active', 'config_json',
        ]
        for field in updatable_fields:
            if field in data:
                setattr(hook, field, data[field])

        try:
            hook.save()
        except Exception as e:
            logger.exception(f"Update hook error: {e}")
            return JsonResponse({'error': str(e)}, status=500)

        return JsonResponse({'id': hook.id, 'hook_name': hook.hook_name})

    def delete(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Soft-delete (deactivate) a hook configuration."""
        try:
            hook = HookConfig.objects.get(pk=pk, tenant_id=_tenant_id())
        except HookConfig.DoesNotExist:
            return JsonResponse({'error': 'Hook not found'}, status=404)

        hook.is_active = False
        hook.save()
        return JsonResponse({'success': True})


@method_decorator(csrf_exempt, name='dispatch')
class HookToggleView(View):
    """Toggle hook enable/disable status."""

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Toggle is_active for a hook."""
        try:
            hook = HookConfig.objects.get(pk=pk, tenant_id=_tenant_id())
        except HookConfig.DoesNotExist:
            return JsonResponse({'error': 'Hook not found'}, status=404)

        hook.is_active = not hook.is_active
        hook.save()
        return JsonResponse({
            'id': hook.id,
            'hook_name': hook.hook_name,
            'is_active': hook.is_active,
        })
