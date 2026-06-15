"""
Tenant configuration API views.
"""
import json
import logging
import uuid

from asgiref.sync import sync_to_async
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.entities.tenant import Tenant

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class TenantListView(View):
    """Return a list of active tenants with their ``tenant_id`` and ``name``.

    GET  /admin/tenants/  - list active tenants
    POST /admin/tenants/  - create a new tenant (token auto-generated)
    """

    async def get(self, request):
        try:
            tenants = await sync_to_async(list)(
                Tenant.objects.filter(is_active=True).values('tenant_id', 'name')
            )
            return JsonResponse(tenants, safe=False)
        except Exception:
            logger.exception("Failed to fetch tenant list")
            return JsonResponse({'error': 'Failed to fetch tenants'}, status=500)

    async def post(self, request):
        """Create a new tenant.

        Request body (JSON):
            tenant_id  (str, required): unique tenant identifier
            name       (str, required): human-readable tenant name
            config_json (dict, optional): tenant-level config overrides

        The authentication token is generated automatically (UUID v4) and
        stored only as its SHA-256 hash — it is never returned to the caller.
        """
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)

        tenant_id = data.get('tenant_id', '').strip()
        name = data.get('name', '').strip()
        config_json = data.get('config_json', {})

        if not tenant_id or not name:
            return JsonResponse({'error': 'tenant_id and name are required'}, status=400)

        exists = await sync_to_async(Tenant.objects.filter(tenant_id=tenant_id).exists)()
        if exists:
            return JsonResponse({'error': f"Tenant '{tenant_id}' already exists"}, status=409)

        # Auto-generate a random token; store only its hash, never return raw value
        raw_token = str(uuid.uuid4())
        token_hash = Tenant.hash_token(raw_token)

        try:
            tenant = await sync_to_async(Tenant.objects.create)(
                tenant_id=tenant_id,
                name=name,
                token_hash=token_hash,
                config_json=config_json,
                is_active=True,
            )
        except Exception:
            logger.exception("Failed to create tenant '%s'", tenant_id)
            return JsonResponse({'error': 'Failed to create tenant'}, status=500)

        return JsonResponse({'tenant_id': tenant.tenant_id, 'name': tenant.name}, status=201)
