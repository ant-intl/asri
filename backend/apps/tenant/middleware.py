"""
Token-based tenant authentication middleware for HTTP requests.

Extracts Bearer token from the ``Authorization`` header, resolves it
to a tenant via :class:`~apps.tenant.registry.TenantRegistry`, and
stores the tenant ID in the request-scoped contextvar.
"""
import json
import logging
import os

from django.http import JsonResponse
from django.utils.decorators import sync_and_async_middleware

from .auth import AdminAuthRegistry
from .context import tenant_id_var, set_current_tenant_id
from .registry import get_tenant_registry

logger = logging.getLogger(__name__)

# Only paths starting with these prefixes require token authentication.
# All other paths (frontend pages, static files, health checks, etc.) are exempt.
AUTH_REQUIRED_PREFIXES = (
    '/chatbot/',
)


def _extract_bearer_token(request) -> str | None:
    """Extract token from ``Authorization: Bearer <token>`` header."""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip() or None
    return None


def _extract_user_id(request) -> str | None:
    """Extract user ID from ``X-User-ID`` header or query string.
    
    Priority:
    1. ``X-User-ID`` header
    2. ``user_id`` query string parameter
    """
    # Try X-User-ID header first
    user_id = request.META.get('HTTP_X_USER_ID')
    if user_id:
        return user_id.strip() or None
    
    # Fallback to query string
    user_id = request.GET.get('user_id')
    if user_id:
        return user_id.strip() or None
    
    return None


@sync_and_async_middleware
def TokenAuthMiddleware(get_response):
    """Middleware that authenticates requests via Bearer token.

    Resolves the token to a ``tenant_id`` using :func:`TenantRegistry.get_tenant_id_by_token`
    and sets it in the contextvar.  Only requests to paths matching
    :data:`AUTH_REQUIRED_PREFIXES` require authentication; all others pass through.
    """
    import asyncio

    def _requires_auth(request) -> bool:
        """Check if the request path requires token authentication."""
        return any(request.path.startswith(p) for p in AUTH_REQUIRED_PREFIXES)

    def _reject(message: str = 'Authentication required') -> JsonResponse:
        return JsonResponse({'error': message}, status=401)

    def _authenticate(request) -> str | None:
        """Return tenant_id or None."""
        raw_token = _extract_bearer_token(request)
        if not raw_token:
            # Admin paths use the configured admin auth provider
            if request.path.startswith('/chatbot/api/admin'):
                tenant_id = AdminAuthRegistry.get_provider().authenticate(request)
                logger.debug("Admin path, tenant_id=%s via %s",
                             tenant_id, type(AdminAuthRegistry.get_provider()).__name__)
                return tenant_id
            # Local development mode: use 'example' tenant when no token provided
            # This matches the example.json configuration for development
            # Case-insensitive check for SERVER_ENV
            server_env = os.environ.get('SERVER_ENV', '').lower()
            if server_env == 'local':
                logger.debug("No Bearer token provided in local mode, using 'example' tenant")
                return 'example'
            return None

        registry = get_tenant_registry()
        token_tenant_id = registry.get_tenant_id_by_token(raw_token)

        if token_tenant_id is None:
            logger.warning("Invalid Bearer token provided")
            return None

        # For admin paths, X-Tenant-Id header takes priority over token-based
        # tenant resolution.  This allows admin UI users to switch between
        # tenants (e.g. from "default" to "alipayHK") without needing a
        # different Bearer token for each tenant.
        if request.path.startswith('/chatbot/api/admin'):
            admin_tenant_id = AdminAuthRegistry.get_provider().authenticate(request)
            if admin_tenant_id:
                logger.debug(
                    "Admin path with token: using X-Tenant-Id=%s (token tenant=%s)",
                    admin_tenant_id, token_tenant_id,
                )
                return admin_tenant_id

        return token_tenant_id

    if asyncio.iscoroutinefunction(get_response):
        async def middleware(request):
            if not _requires_auth(request):
                token = set_current_tenant_id(None)
                try:
                    return await get_response(request)
                finally:
                    tenant_id_var.reset(token)

            tenant_id = _authenticate(request)
            if tenant_id is None:
                return _reject()

            request.tenant_id = tenant_id
            request.user_id = _extract_user_id(request) or 'anonymous'
            token = set_current_tenant_id(tenant_id)
            try:
                response = await get_response(request)
            finally:
                tenant_id_var.reset(token)
            return response
    else:
        def middleware(request):
            if not _requires_auth(request):
                token = set_current_tenant_id(None)
                try:
                    return get_response(request)
                finally:
                    tenant_id_var.reset(token)

            tenant_id = _authenticate(request)
            if tenant_id is None:
                return _reject()

            request.tenant_id = tenant_id
            request.user_id = _extract_user_id(request) or 'anonymous'
            token = set_current_tenant_id(tenant_id)
            try:
                response = get_response(request)
            finally:
                tenant_id_var.reset(token)
            return response

    return middleware
