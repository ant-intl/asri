"""
HookRegistry — database-to-instance mapping with tenant-scoped caching.

Aligns with Claude Code's settings.json hooks configuration pattern,
but stored in DB instead of a local JSON file.
"""
import logging
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

if TYPE_CHECKING:
    from .base import BaseHook

logger = logging.getLogger(__name__)


class HookRegistry:
    """Registry that loads ``HookConfig`` rows and instantiates hook objects.

    Hook type → class mapping is populated at import time by each hook
    module calling ``register_hook_class()``.  Instances are cached
    per tenant and invalidated whenever a ``HookConfig`` is saved.

    Usage::

        # 1. Register hook class at module level
        HookRegistry.register_hook_class('tool_confirmation', ToolConfirmationHook)

        # 2. Load hooks for a tenant at request time
        hooks = await HookRegistry.get_hooks_for_tenant(tenant_id)
    """

    _hook_classes: dict[str, type["BaseHook"]] = {}
    _instances: dict[str, dict[str, "BaseHook"]] = {}

    # ── class registration ───────────────────────────────────────

    @classmethod
    def register_hook_class(cls, hook_type: str, hook_class: type["BaseHook"]) -> None:
        """Register a hook implementation class for ``hook_type``."""
        cls._hook_classes[hook_type] = hook_class
        logger.debug("Registered hook class: %s → %s", hook_type, hook_class.__name__)

    # ── tenant-level loading ─────────────────────────────────────

    @classmethod
    async def get_hooks_for_tenant(cls, tenant_id: str) -> list["BaseHook"]:
        """Return all enabled hook instances for a tenant.

        Each ``HookConfig`` row is converted into a ``BaseHook`` instance
        using the class registered for its ``hook_type``.  Results are
        cached per tenant and cleared on ``HookConfig.save()``.
        """
        if tenant_id in cls._instances:
            return list(cls._instances[tenant_id].values())

        from ...entities.hook_config import HookConfig

        configs = await sync_to_async(list, thread_sensitive=False)(
            HookConfig.objects.filter(tenant_id=tenant_id, is_active=True)
        )

        hooks: list["BaseHook"] = []
        for config in configs:
            hook_class = cls._hook_classes.get(config.hook_type)
            if hook_class is None:
                logger.warning(
                    "Unknown hook_type '%s' for hook '%s' — skipping",
                    config.hook_type, config.hook_name,
                )
                continue

            try:
                hook = hook_class(config=config.config_json or {})
                cls._instances.setdefault(tenant_id, {})[config.hook_name] = hook
                hooks.append(hook)
            except Exception:
                logger.exception(
                    "Failed to instantiate hook '%s' (type=%s)",
                    config.hook_name, config.hook_type,
                )

        logger.info(
            "Loaded %d hooks for tenant '%s': %s",
            len(hooks), tenant_id,
            [h.hook_name for h in hooks],
        )
        return hooks

    # ── cache management ─────────────────────────────────────────

    @classmethod
    def invalidate_cache(cls, tenant_id: str) -> None:
        """Clear cached instances for a tenant (called on HookConfig.save)."""
        if tenant_id in cls._instances:
            del cls._instances[tenant_id]
            logger.debug("Invalidated hook cache for tenant: %s", tenant_id)


# ── Register built-in hook types ──────────────────────────────────
# Executed at module import time so that all known hook_types are mapped.

def _register_builtin_hooks() -> None:
    from .confirmation_hook import ToolConfirmationHook
    from .tool_rule_deny_hook import ToolRuleDenyHook

    HookRegistry.register_hook_class("tool_confirmation", ToolConfirmationHook)
    HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)


_register_builtin_hooks()
