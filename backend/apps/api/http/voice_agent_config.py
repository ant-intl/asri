"""
Voice Agent configuration API views.

Endpoints:
    GET    /chatbot/api/admin/voice-agent-config/          List configs
    POST   /chatbot/api/admin/voice-agent-config/          Create config
    GET    /chatbot/api/admin/voice-agent-config/<pk>/     Get config detail
    PUT    /chatbot/api/admin/voice-agent-config/<pk>/     Update config
    DELETE /chatbot/api/admin/voice-agent-config/<pk>/     Deactivate config
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...entities import VoiceAgentConfig
from ...tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


def _tenant_id() -> str:
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        raise ValueError("tenant_id not set in request context")
    return tenant_id


def _serialize_config(config: VoiceAgentConfig) -> dict:
    """Serialize a VoiceAgentConfig to a JSON-safe dict."""
    return {
        'id': config.id,
        'name': config.name,
        'tenant_id': config.tenant_id,
        'is_active': config.is_active,
        'voice_settings': config.voice_settings or {},
        'gmt_create': config.gmt_create.isoformat(),
        'gmt_modified': config.gmt_modified.isoformat(),
    }


@method_decorator(csrf_exempt, name='dispatch')
class VoiceAgentConfigListView(View):
    """
    GET  /chatbot/api/admin/voice-agent-config/
    POST /chatbot/api/admin/voice-agent-config/
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """List voice agent configs for the current tenant."""
        configs = VoiceAgentConfig.objects.filter(
            tenant_id=_tenant_id(),
        ).order_by('-is_active', '-gmt_modified')
        return JsonResponse({
            'configs': [_serialize_config(c) for c in configs],
        })

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new voice agent config."""
        try:
            data = json.loads(request.body)
            config = VoiceAgentConfig.objects.create(
                tenant_id=_tenant_id(),
                name=data.get('name', 'default'),
                is_active=data.get('is_active', True),
                voice_settings=data.get('voice_settings', {}),
            )
            return JsonResponse(_serialize_config(config), status=201)
        except Exception as e:
            logger.exception("Create voice agent config error: %s", e)
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class VoiceAgentConfigDetailView(View):
    """
    GET    /chatbot/api/admin/voice-agent-config/<pk>/
    PUT    /chatbot/api/admin/voice-agent-config/<pk>/
    DELETE /chatbot/api/admin/voice-agent-config/<pk>/
    """

    def get(self, request: HttpRequest, pk: int) -> JsonResponse:
        try:
            config = VoiceAgentConfig.objects.get(pk=pk, tenant_id=_tenant_id())
            return JsonResponse(_serialize_config(config))
        except VoiceAgentConfig.DoesNotExist:
            return JsonResponse({'error': 'Config not found'}, status=404)

    def put(self, request: HttpRequest, pk: int) -> JsonResponse:
        try:
            data = json.loads(request.body)
            config = VoiceAgentConfig.objects.get(pk=pk, tenant_id=_tenant_id())

            for field in ('name', 'is_active', 'voice_settings'):
                if field in data:
                    setattr(config, field, data[field])

            config.save()
            return JsonResponse(_serialize_config(config))
        except VoiceAgentConfig.DoesNotExist:
            return JsonResponse({'error': 'Config not found'}, status=404)
        except Exception as e:
            logger.exception("Update voice agent config error: %s", e)
            return JsonResponse({'error': str(e)}, status=500)

    def delete(self, request: HttpRequest, pk: int) -> JsonResponse:
        try:
            config = VoiceAgentConfig.objects.get(pk=pk, tenant_id=_tenant_id())
            config.is_active = False
            config.save()
            return JsonResponse({'success': True})
        except VoiceAgentConfig.DoesNotExist:
            return JsonResponse({'error': 'Config not found'}, status=404)
