"""
Default admin authentication provider.

Reads the ``X-Tenant-Id`` header (or ``tenant_id`` query parameter) from
admin requests to determine the tenant context.  Falls back to ``'default'``
when no tenant is specified.
"""
from .base import BaseAdminAuthProvider


class DefaultAdminAuthProvider(BaseAdminAuthProvider):
    """Reads tenant ID from request headers or query parameters.

    Priority:
    1. ``X-Tenant-Id`` HTTP header
    2. ``tenant_id`` query string parameter
    3. ``'default'`` fallback
    """

    def authenticate(self, request) -> str | None:
        tenant_id = (
            request.META.get('HTTP_X_TENANT_ID')
            or request.GET.get('tenant_id')
            or 'default'
        )
        return tenant_id
