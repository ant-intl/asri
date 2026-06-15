"""
Prompt Template API views.
"""
import json
import logging

from django.db import transaction
from django.http import JsonResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ..chatbot.models.prompt_template import PromptTemplate
from ..services.version_service import VersionService

logger = logging.getLogger(__name__)


def _tenant_id(request) -> str:
    """Tenant ID from middleware-set ``request.tenant_id``, falling back to ``'example'``."""
    tenant_id = getattr(request, 'tenant_id', None)
    return tenant_id if isinstance(tenant_id, str) and tenant_id else 'example'


def serialize_template(t: PromptTemplate) -> dict:
    """Serialize a PromptTemplate to dict.

    ``system_template`` is the implicit first system layer (stored
    directly on the model field).  ``layers`` contains only additional
    layers — any ``_system_default`` artifact from the old table-based
    PromptLayer is filtered out.
    """
    layers = t.layers or []
    # Filter out auto-created artifacts from the PromptLayer → JSON
    # migration pipeline:
    #   - _system_default: created when no PromptLayer records existed
    #   - system_core_rules: created from system_template content in 0020
    # Both are now implied by the system_template field.
    extra_layers = [
        l for l in layers
        if not (
            l.get('target') == 'system'
            and l.get('name') in ('_system_default', 'system_core_rules')
        )
    ]
    return {
        'id': str(t.id),
        'name': t.name,
        'description': t.description,
        'system_template': t.system_template or '',
        'user_template_mode': t.user_template_mode,
        'user_template': t.user_template,
        'extractor_config': t.extractor_config,
        'is_active': t.is_active,
        'layers': extra_layers,
        'created_at': t.gmt_create.isoformat(),
        'updated_at': t.gmt_modified.isoformat(),
    }


@method_decorator(csrf_exempt, name='dispatch')
class PromptTemplateListView(View):
    """List and create prompt templates."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """List all prompt templates for the current tenant."""
        templates = PromptTemplate.objects.filter(
            tenant_id=_tenant_id(request)
        ).order_by('gmt_create')
        data = [serialize_template(t) for t in templates]
        return JsonResponse({'templates': data, 'total': len(data)})

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new prompt template."""
        try:
            data = json.loads(request.body)

            template = PromptTemplate.objects.create(
                tenant_id=_tenant_id(request),
                name=data.get('name'),
                description=data.get('description', ''),
                system_template=data.get('system_template', ''),
                user_template_mode=data.get('user_template_mode', PromptTemplate.MessageMode.GENERIC),
                user_template=data.get('user_template', ''),
                layers=data.get('layers') or [],
                extractor_config=data.get('extractor_config', {}),
                is_active=data.get('is_active', True),
            )
            # Auto-create initial version snapshot
            try:
                VersionService.create_snapshot(
                    entity_type='prompt_template',
                    entity_id=str(template.id),
                    description='Initial version',
                )
            except Exception as e:
                logger.warning(f"Failed to create version snapshot: {e}")
            return JsonResponse(serialize_template(template), status=201)
        except Exception as e:
            logger.error(f"Failed to create prompt template: {e}")
            return JsonResponse({'error': str(e)}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class PromptTemplateDetailView(View):
    """Retrieve, update, and delete prompt templates."""

    def get(self, request: HttpRequest, pk: str) -> JsonResponse:
        """Retrieve a single prompt template."""
        try:
            template = PromptTemplate.objects.get(pk=pk, tenant_id=_tenant_id(request))
            return JsonResponse(serialize_template(template))
        except PromptTemplate.DoesNotExist:
            return JsonResponse({'error': 'Prompt template not found'}, status=404)

    def put(self, request: HttpRequest, pk: str) -> JsonResponse:
        """Update a prompt template (full update)."""
        try:
            template = PromptTemplate.objects.get(pk=pk, tenant_id=_tenant_id(request))
            data = json.loads(request.body)

            template.name = data.get('name', template.name)
            template.description = data.get('description', template.description)
            template.system_template = data.get('system_template', template.system_template)
            template.user_template_mode = data.get('user_template_mode', template.user_template_mode)
            template.user_template = data.get('user_template', template.user_template)
            template.layers = data.get('layers', template.layers)
            template.extractor_config = data.get('extractor_config', template.extractor_config)
            template.is_active = data.get('is_active', template.is_active)
            template.save()

            # Auto-create version snapshot on update
            try:
                VersionService.create_snapshot(
                    entity_type='prompt_template',
                    entity_id=str(template.id),
                    description='Auto-saved',
                )
            except Exception as e:
                logger.warning(f"Failed to create version snapshot: {e}")

            return JsonResponse(serialize_template(template))
        except PromptTemplate.DoesNotExist:
            return JsonResponse({'error': 'Prompt template not found'}, status=404)
        except Exception as e:
            logger.error(f"Failed to update prompt template: {e}")
            return JsonResponse({'error': str(e)}, status=400)

    def patch(self, request: HttpRequest, pk: str) -> JsonResponse:
        """Partial update a prompt template."""
        return self.put(request, pk)

    def delete(self, request: HttpRequest, pk: str) -> JsonResponse:
        """Delete a prompt template."""
        try:
            template = PromptTemplate.objects.get(pk=pk, tenant_id=_tenant_id(request))
            template.delete()
            return JsonResponse({}, status=204)
        except PromptTemplate.DoesNotExist:
            return JsonResponse({'error': 'Prompt template not found'}, status=404)



@method_decorator(csrf_exempt, name='dispatch')
class PromptTemplateEnableView(View):
    """Enable a prompt template and disable others (max one active)."""

    def post(self, request: HttpRequest, pk: str) -> JsonResponse:
        try:
            with transaction.atomic():
                tenant_id = _tenant_id(request)
                # Use select_for_update for row-level locking to prevent concurrent conflicts
                active_templates = list(PromptTemplate.objects.select_for_update().filter(
                    is_active=True, tenant_id=tenant_id
                ))

                # Get the target template
                target_template = PromptTemplate.objects.get(pk=pk, tenant_id=tenant_id)

                # Record disabled templates
                disabled_template = None

                # Disable other activated templates
                for t in active_templates:
                    if str(t.id) != str(target_template.id):
                        t.is_active = False
                        t.save()
                        disabled_template = t

                # Enable the target template
                if not target_template.is_active:
                    target_template.is_active = True
                    target_template.save()

            # Build response
            response_data = {
                'success': True,
                'id': str(target_template.id),
                'name': target_template.name,
                'message': f"Template '{target_template.name}' enabled",
            }
            if disabled_template:
                response_data['disabled_template'] = {
                    'id': str(disabled_template.id),
                    'name': disabled_template.name
                }

            return JsonResponse(response_data)

        except PromptTemplate.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Template not found'}, status=404)
        except Exception as e:
            logger.exception(f"Enable prompt template error: {e}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class PromptTemplateDisableView(View):
    """Disable a prompt template and sync to tenant config."""

    def post(self, request: HttpRequest, pk: str) -> JsonResponse:
        try:
            tenant_id = _tenant_id(request)
            template = PromptTemplate.objects.get(pk=pk, tenant_id=tenant_id)
            template.is_active = False
            template.save()
            return JsonResponse({
                'success': True,
                'id': str(template.id),
                'name': template.name,
                'message': f"Template '{template.name}' disabled"
            })
        except PromptTemplate.DoesNotExist:
            return JsonResponse({'error': 'Prompt template not found'}, status=404)
