"""
Admin config sync views for enabling/disabling tools and models.
"""
import logging

from asgiref.sync import async_to_sync
from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...entities import ToolConfig, LLMProviderConfig, Tenant

logger = logging.getLogger(__name__)


def _tenant_id(request) -> str:
    """Tenant ID from middleware-set ``request.tenant_id``, falling back to ``'example'``."""
    tenant_id = getattr(request, 'tenant_id', None)
    return tenant_id if isinstance(tenant_id, str) and tenant_id else 'example'


def _trigger_tool_reload(tenant_id: str) -> None:
    """Trigger immediate tool reload after config change.

    This ensures tools are reloaded immediately when configuration changes,
    without waiting for the 60-second periodic refresh.
    """
    try:
        from ...integrations.tool.reload_manager import get_tool_reload_manager
        from ...tenant.registry import get_tenant_registry

        # Force reload registry to get latest config from DB
        registry = get_tenant_registry()
        registry.force_reload()

        # Get fresh config from registry
        config = registry.get_config(tenant_id)

        # Force reload tools immediately
        reload_manager = get_tool_reload_manager()
        count = async_to_sync(reload_manager.reload_if_needed)(
            tenant_id, config, force=True
        )
        if count > 0:
            logger.info(f"Immediately reloaded {count} tools for tenant '{tenant_id}'")
    except Exception as e:
        logger.error(f"Failed to trigger tool reload for tenant '{tenant_id}': {e}")


def sync_all_active_tools_to_tenant(tenant_id: str) -> None:
    """Sync all is_active=True ToolConfigs to tenant config_json TOOLS array."""
    tools = ToolConfig.objects.filter(tenant_id=tenant_id, is_active=True)

    tenant = Tenant.objects.get(tenant_id=tenant_id)
    config = tenant.config_json or {}

    tools_config = []
    for tool in tools:
        tools_config.append({
            'name': tool.name,
            'type': tool.tool_type,
            'enabled': True,
            'config': tool.config_json or {}
        })

    config['TOOLS'] = tools_config
    tenant.config_json = config
    tenant.save()
    logger.info(f"Synced {len(tools_config)} active tools to tenant {tenant_id}")

    # Trigger immediate tool reload
    _trigger_tool_reload(tenant_id)


def sync_active_model_to_tenant(tenant_id: str, model_id: int) -> None:
    """Sync specified LLMProviderConfig to tenant config_json model field."""
    model = LLMProviderConfig.objects.get(pk=model_id, tenant_id=tenant_id)
    tenant = Tenant.objects.get(tenant_id=tenant_id)

    config = tenant.config_json or {}

    if model.is_active:
        config['model'] = {
            'provider_type': model.provider_type,
            'model_name': model.model_name,
            'api_base': model.api_base,
            'api_key': model.api_key_encrypted,
            'config': model.config_json or {}
        }
        logger.info(f"Synced model {model.name} to tenant {tenant_id}")
    else:
        config.pop('model', None)
        logger.info(f"Removed model from tenant {tenant_id}")

    tenant.config_json = config
    tenant.save()

    # Trigger immediate tool reload (model change may affect tool behavior)
    _trigger_tool_reload(tenant_id)


@method_decorator(csrf_exempt, name='dispatch')
class ToolEnableView(View):
    """Enable a tool and sync to tenant config."""

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Enable tool and sync to tenant config."""
        try:
            tenant_id = _tenant_id(request)
            tool = ToolConfig.objects.get(pk=pk, tenant_id=tenant_id)
            tool.is_active = True
            tool.save()

            # Sync all active tools to tenant config
            sync_all_active_tools_to_tenant(tenant_id)

            return JsonResponse({
                'success': True,
                'id': tool.id,
                'name': tool.name,
                'message': 'Tool enabled and synced to tenant config'
            })
        except ToolConfig.DoesNotExist:
            return JsonResponse({'error': 'Tool not found'}, status=404)
        except Exception as e:
            logger.exception(f"Enable tool error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ToolDisableView(View):
    """Disable a tool and sync to tenant config."""

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Disable tool and sync to tenant config."""
        try:
            tenant_id = _tenant_id(request)
            tool = ToolConfig.objects.get(pk=pk, tenant_id=tenant_id)
            tool.is_active = False
            tool.save()

            # Sync all active tools to tenant config
            sync_all_active_tools_to_tenant(tenant_id)

            return JsonResponse({
                'success': True,
                'id': tool.id,
                'name': tool.name,
                'message': 'Tool disabled and synced to tenant config'
            })
        except ToolConfig.DoesNotExist:
            return JsonResponse({'error': 'Tool not found'}, status=404)
        except Exception as e:
            logger.exception(f"Disable tool error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ModelEnableView(View):
    """Enable a model and sync to tenant config.

    Only one model per purpose (chatbot/copilot) can be active at a time.
    Enabling a model automatically disables other models with the same purpose
    and sets the newly enabled model as default.
    """

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Enable model, disable others with same purpose, set as default, and sync."""
        try:
            tenant_id = _tenant_id(request)
            model = LLMProviderConfig.objects.get(pk=pk, tenant_id=tenant_id)

            # Disable all other active models with the same purpose
            LLMProviderConfig.objects.filter(
                tenant_id=tenant_id,
                purpose=model.purpose,
                is_active=True,
            ).exclude(pk=pk).update(is_active=False, is_default=False)

            # Enable this model and set as default
            model.is_active = True
            model.is_default = True
            model.save()

            # Sync active model to tenant config
            sync_active_model_to_tenant(tenant_id, pk)

            return JsonResponse({
                'success': True,
                'id': model.id,
                'name': model.name,
                'message': f'Model "{model.name}" enabled (other {model.purpose} models disabled)'
            })
        except LLMProviderConfig.DoesNotExist:
            return JsonResponse({'error': 'Model not found'}, status=404)
        except Exception as e:
            logger.exception(f"Enable model error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ModelDisableView(View):
    """Disable a model and sync to tenant config."""

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Disable model, clear default flag, and sync."""
        try:
            tenant_id = _tenant_id(request)
            model = LLMProviderConfig.objects.get(pk=pk, tenant_id=tenant_id)
            model.is_active = False
            model.is_default = False
            model.save()

            # Sync (remove) model from tenant config
            sync_active_model_to_tenant(tenant_id, pk)

            return JsonResponse({
                'success': True,
                'id': model.id,
                'name': model.name,
                'message': f'Model "{model.name}" disabled'
            })
        except LLMProviderConfig.DoesNotExist:
            return JsonResponse({'error': 'Model not found'}, status=404)
        except Exception as e:
            logger.exception(f"Disable model error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


def sync_builtin_tool_state(tenant_id: str, tool_name: str, enabled: bool) -> None:
    """Update built-in tool state in tenant config_json BUILTIN_TOOLS field.

    Args:
        tenant_id: Tenant ID
        tool_name: Built-in tool name
        enabled: Whether to enable or disable the tool
    """
    tenant = Tenant.objects.get(tenant_id=tenant_id)
    config = tenant.config_json or {}

    # Initialize BUILTIN_TOOLS if not present
    if 'BUILTIN_TOOLS' not in config:
        config['BUILTIN_TOOLS'] = {}

    if enabled:
        config['BUILTIN_TOOLS'][tool_name] = True
        logger.info(f"Enabled built-in tool '{tool_name}' for tenant '{tenant_id}'")
    else:
        config['BUILTIN_TOOLS'][tool_name] = False
        logger.info(f"Disabled built-in tool '{tool_name}' for tenant '{tenant_id}'")

    tenant.config_json = config
    tenant.save()

    # Trigger tool reload to apply the change
    _trigger_tool_reload(tenant_id)

    # Also reload BuiltInToolRegistry cache
    from ...integrations.tool.builtin_registry import BuiltInToolRegistry
    BuiltInToolRegistry.reload(tenant_id)


@method_decorator(csrf_exempt, name='dispatch')
class BuiltInToolToggleView(View):
    """Toggle built-in tool enable/disable state via tenant config."""

    def post(self, request: HttpRequest, tool_name: str) -> JsonResponse:
        """Toggle built-in tool state."""
        try:
            import json
            data = json.loads(request.body)
            enable = data.get('enable')

            if enable is None:
                return JsonResponse({'error': 'Missing "enable" field'}, status=400)

            tenant_id = _tenant_id(request)
            sync_builtin_tool_state(tenant_id, tool_name, enable)

            return JsonResponse({
                'success': True,
                'name': tool_name,
                'is_enabled': enable,
                'message': f"Built-in tool {'enabled' if enable else 'disabled'}"
            })

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Tenant.DoesNotExist:
            return JsonResponse({'error': 'Tenant not found'}, status=404)
        except Exception as e:
            logger.exception(f"Built-in tool toggle error: {e}")
            return JsonResponse({'error': str(e)}, status=500)
