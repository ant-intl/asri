"""
LLM Provider configuration API views.
"""
import json
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.utils.security import mask_api_key, is_masked_value
from ...entities import LLMProviderConfig
from ...tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


def _tenant_id() -> str:
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        raise ValueError("tenant_id not set in request context")
    return tenant_id


@method_decorator(csrf_exempt, name='dispatch')
class LLMProviderListView(View):
    """
    Handle LLM provider list and creation.
    
    GET /chatbot/api/llm-providers/
    POST /chatbot/api/llm-providers/
    """
    
    def get(self, request: HttpRequest) -> JsonResponse:
        """List LLM providers."""
        providers = LLMProviderConfig.objects.filter(
            tenant_id=_tenant_id(),
        )

        return JsonResponse({
            'providers': [
                {
                    'id': p.id,
                    'name': p.name,
                    'provider_type': p.provider_type,
                    'api_base': p.api_base,
                    'model_name': p.model_name,
                    'is_default': p.is_default,
                    'is_active': p.is_active,
                    'purpose': p.purpose,
                    'config_json': p.config_json,
                    'gmt_create': p.gmt_create.isoformat(),
                    'api_key': mask_api_key(p.api_key_encrypted),
                }
                for p in providers
            ]
        })

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new LLM provider."""
        try:
            data = json.loads(request.body)

            provider = LLMProviderConfig.objects.create(
                tenant_id=_tenant_id(),
                name=data['name'],
                provider_type=data['provider_type'],
                api_base=data.get('api_base', ''),
                api_key_encrypted=data.get('api_key', ''),  # TODO: encrypt
                model_name=data['model_name'],
                purpose=data.get('purpose', 'chatbot'),
                config_json=data.get('config_json', {}),
                is_default=data.get('is_default', False),
                is_active=data.get('is_active', True),
            )

            return JsonResponse({
                'id': provider.id,
                'name': provider.name,
                'provider_type': provider.provider_type,
                'model_name': provider.model_name,
                'purpose': provider.purpose,
                'is_default': provider.is_default,
            }, status=201)

        except KeyError as e:
            return JsonResponse({'error': f'Missing required field: {e}'}, status=400)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.exception(f"Create LLM provider error: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class LLMProviderDetailView(View):
    """
    Handle single LLM provider operations.
    
    GET /chatbot/api/llm-providers/{id}/
    PUT /chatbot/api/llm-providers/{id}/
    DELETE /chatbot/api/llm-providers/{id}/
    """
    
    def get(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Get LLM provider details."""
        try:
            provider = LLMProviderConfig.objects.get(pk=pk, tenant_id=_tenant_id())
            return JsonResponse({
                'id': provider.id,
                'name': provider.name,
                'provider_type': provider.provider_type,
                'api_base': provider.api_base,
                'model_name': provider.model_name,
                'purpose': provider.purpose,
                'is_default': provider.is_default,
                'is_active': provider.is_active,
                'config_json': provider.config_json,
                'gmt_create': provider.gmt_create.isoformat(),
                'gmt_modified': provider.gmt_modified.isoformat(),
            })
        except LLMProviderConfig.DoesNotExist:
            return JsonResponse({'error': 'Provider not found'}, status=404)

    def put(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Update LLM provider."""
        try:
            data = json.loads(request.body)
            provider = LLMProviderConfig.objects.get(pk=pk, tenant_id=_tenant_id())

            if 'name' in data:
                provider.name = data['name']
            if 'api_base' in data:
                provider.api_base = data['api_base']
            if 'api_key' in data:
                if not is_masked_value(data['api_key']):
                    provider.api_key_encrypted = data['api_key']  # TODO: encrypt
            if 'model_name' in data:
                provider.model_name = data['model_name']
            if 'purpose' in data:
                provider.purpose = data['purpose']
            if 'config_json' in data:
                provider.config_json = data['config_json']
            if 'is_default' in data:
                provider.is_default = data['is_default']
            if 'is_active' in data:
                provider.is_active = data['is_active']

            provider.save()

            return JsonResponse({
                'id': provider.id,
                'name': provider.name,
                'purpose': provider.purpose,
                'gmt_modified': provider.gmt_modified.isoformat(),
            })

        except LLMProviderConfig.DoesNotExist:
            return JsonResponse({'error': 'Provider not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.exception(f"Update LLM provider error: {e}")
            return JsonResponse({'error': str(e)}, status=500)
    
    def delete(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Delete LLM provider."""
        try:
            provider = LLMProviderConfig.objects.get(pk=pk, tenant_id=_tenant_id())
            provider.is_active = False
            provider.save()
            return JsonResponse({'success': True})
        except LLMProviderConfig.DoesNotExist:
            return JsonResponse({'error': 'Provider not found'}, status=404)
