"""
Tool configuration API views.
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...entities import ToolConfig
from ...tenant.context import get_current_tenant_id
from ...integrations.tool import BuiltInToolRegistry

logger = logging.getLogger(__name__)


def _tenant_id() -> str:
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        raise ValueError("tenant_id not set in request context")
    return tenant_id


@method_decorator(csrf_exempt, name='dispatch')
class ToolListView(View):
    """Handle Tool list (including built-in tools) and creation."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """List all tools including built-in tools."""
        tenant_id = _tenant_id()

        # Ensure built-in registry is initialized
        BuiltInToolRegistry.ensure_initialized()

        # Get user-created tools from database (exclude 'tool' type which are built-in configs)
        db_tools = ToolConfig.objects.filter(
            tenant_id=tenant_id
        ).exclude(tool_type='tool')  # Exclude built-in tool configs

        db_tools_list = [
            {
                'id': t.id,
                'name': t.name,
                'description': t.description,
                'parameters_schema': t.parameters_schema,
                'is_active': t.is_active,
                'gmt_create': t.gmt_create.isoformat(),
                'config_json': t.config_json,
                'tool_type': t.tool_type,
                'is_builtin': False,  # User-created tools
            }
            for t in db_tools
        ]

        # Get built-in tools
        builtin_tools = BuiltInToolRegistry.list_builtin_tools(tenant_id)
        builtin_tools_list = [
            {
                'name': t['name'],
                'description': t['description'],
                'is_active': t['is_enabled'],  # Map is_enabled to is_active
                'tool_type': 'tool',  # All built-in tools are 'tool' type
                'is_builtin': True,  # Mark as built-in
            }
            for t in builtin_tools
        ]

        # Combine and return (built-in first, then user-created)
        all_tools = builtin_tools_list + db_tools_list

        return JsonResponse({
            'tools': all_tools
        })

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new tool."""
        try:
            data = json.loads(request.body)

            tool = ToolConfig.objects.create(
                tenant_id=_tenant_id(),
                name=data['name'],
                tool_type=data['tool_type'],
                description=data.get('description', ''),
                parameters_schema=data.get('parameters_schema', {}),
                config_json=data.get('config_json', {}),
                is_active=data.get('is_active', True),
            )

            return JsonResponse({
                'id': tool.id,
                'name': tool.name,
            }, status=201)

        except KeyError as e:
            return JsonResponse({'error': f'Missing required field: {e}'}, status=400)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.exception(f"Create tool error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ToolDetailView(View):
    """Handle single tool operations."""

    def get(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Get tool details."""
        try:
            tool = ToolConfig.objects.get(
                pk=pk, tenant_id=_tenant_id()
            )
            return JsonResponse({
                'id': tool.id,
                'name': tool.name,
                'description': tool.description,
                'parameters_schema': tool.parameters_schema,
                'config_json': tool.config_json,
                'is_active': tool.is_active,
                'gmt_create': tool.gmt_create.isoformat(),
                'tool_type': tool.tool_type,
                'is_builtin': False,
            })
        except ToolConfig.DoesNotExist:
            return JsonResponse({'error': 'Tool not found'}, status=404)

    def put(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Update tool."""
        try:
            data = json.loads(request.body)
            tool = ToolConfig.objects.get(
                pk=pk, tenant_id=_tenant_id()
            )

            for field in ['name', 'description', 'parameters_schema', 'config_json', 'is_active', 'tool_type']:
                if field in data:
                    setattr(tool, field, data[field])

            tool.save()
            return JsonResponse({'id': tool.id, 'name': tool.name})

        except ToolConfig.DoesNotExist:
            return JsonResponse({'error': 'Tool not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

    def delete(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Delete tool."""
        try:
            tool = ToolConfig.objects.get(
                pk=pk, tenant_id=_tenant_id()
            )
            tool.is_active = False
            tool.save()
            return JsonResponse({'success': True})
        except ToolConfig.DoesNotExist:
            return JsonResponse({'error': 'Tool not found'}, status=404)


@method_decorator(csrf_exempt, name='dispatch')
class BuiltInToolToggleView(View):
    """Handle built-in tool enable/disable operations via tenant config."""

    def post(self, request: HttpRequest, tool_name: str) -> JsonResponse:
        """Toggle built-in tool enabled state."""
        # Delegate to admin_config_sync
        from .admin_config_sync import BuiltInToolToggleView as AdminView
        return AdminView().post(request, tool_name)
