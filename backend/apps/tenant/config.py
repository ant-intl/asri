"""
Multi-tenant configuration manager.

Provides tenant-aware configuration reads backed by
:class:`~apps.tenant.registry.TenantRegistry` (database table).
"""
import logging
from typing import Any, Optional

from .context import get_current_tenant_id
from .registry import get_tenant_registry

logger = logging.getLogger(__name__)


def get_chatbot_config(key: Optional[str] = None, default: Any = None) -> Any:
    """Tenant-aware replacement for ``settings.CHATBOT`` reads.

    Reads from the ``chatbot_tenant`` database table via
    :class:`~apps.tenant.registry.TenantRegistry`, falling back
    to ``settings.CHATBOT`` defaults.

    Args:
        key: A specific config key to retrieve.  If ``None``, the
             entire merged dict is returned.
        default: Fallback value when *key* is not present.

    Returns:
        The config value (if *key* given) or the full merged dict.
    """
    tenant_id = get_current_tenant_id()
    registry = get_tenant_registry()
    registry.force_reload()
    config = registry.get_config(tenant_id)

    if key is None:
        return config
    return config.get(key, default)
