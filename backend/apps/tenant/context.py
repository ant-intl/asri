"""
Request-scoped tenant context using contextvars.

Provides thread-safe and async-safe storage for the current tenant ID.
Set by TenantMiddleware (HTTP) or ChatConsumer (WebSocket).
"""
import contextvars
from typing import Optional

tenant_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'tenant_id', default=None
)


def get_current_tenant_id() -> Optional[str]:
    """Get the tenant ID for the current request context."""
    return tenant_id_var.get()


def set_current_tenant_id(tenant_id: Optional[str]) -> contextvars.Token:
    """Set the tenant ID for the current request context.

    Returns a token that can be used to reset the contextvar.
    """
    return tenant_id_var.set(tenant_id)
