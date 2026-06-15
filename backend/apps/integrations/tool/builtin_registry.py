"""
Built-in tool registry for managing BaseTool subclasses.

This module provides the BuiltInToolRegistry class that:
1. Reads from ToolRegistry._tool_classes to get all BaseTool subclasses
2. Manages enable/disable state via tenant configuration (BUILTIN_TOOLS field)
3. No database table required - state stored in tenant config
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BuiltInToolRegistry:
    """
    Registry for built-in tools (BaseTool subclasses).

    Built-in tools are automatically registered via BaseTool.__init_subclass__.
    Enable/disable state is stored in tenant configuration (BUILTIN_TOOLS field).

    Storage:
    - _enabled_cache: {tenant_id: {tool_name: is_enabled}}  # Memory cache
    - Config source: tenant config's BUILTIN_TOOLS field

    Tenant config example:
    {
        "BUILTIN_TOOLS": {
            "view_text_file": true,
            "rag_search": false
        }
    }
    """

    _enabled_cache: dict[Optional[str], dict[str, bool]] = {}
    _initialized: bool = False

    @classmethod
    def _load_from_tenant_config(cls, tenant_id: Optional[str] = None) -> dict[str, bool]:
        """
        Load built-in tool states from tenant configuration.

        Args:
            tenant_id: Tenant ID

        Returns:
            Dict of {tool_name: is_enabled}
        """
        from ...tenant.registry import get_tenant_registry

        # Force reload TenantRegistry to get fresh data from DB
        registry = get_tenant_registry()
        registry.force_reload()

        # Get BUILTIN_TOOLS from tenant config
        config = registry.get_config(tenant_id)
        builtin_tools_config = config.get('BUILTIN_TOOLS', {})
        return {k: bool(v) for k, v in builtin_tools_config.items()}

    @classmethod
    def initialize(cls) -> None:
        """Load enabled states from tenant configuration into memory cache."""
        if cls._initialized:
            return

        # Load states for all known tenants (cached in TenantRegistry)
        from ...tenant.registry import get_tenant_registry

        registry = get_tenant_registry()
        tenant_ids = registry.list_tenant_ids()

        for tid in tenant_ids:
            if tid:  # Skip None (global)
                cls._enabled_cache[tid] = cls._load_from_tenant_config(tid)

        # Also load for global default (None)
        cls._enabled_cache[None] = cls._load_from_tenant_config(None)

        total = sum(len(v) for v in cls._enabled_cache.values())
        logger.info(f"Loaded {total} built-in tool states from tenant configs")
        cls._initialized = True

    @classmethod
    def list_builtin_tools(cls, tenant_id: Optional[str] = None) -> list[dict]:
        """
        List all built-in tool classes with their enabled state.

        Note: This only returns the tool CLASSES (from _tool_classes),
        not the instances. Instances should be managed via:
        - RAG/Skill tools: ToolConfig database records
        - MCP tools: MCP server configuration

        Args:
            tenant_id: Tenant ID

        Returns:
            List of dicts with tool info:
            [{'name': 'xxx', 'description': 'xxx', 'is_enabled': True}, ...]
        """
        from .base import ToolRegistry

        # Ensure initialized
        cls.initialize()

        tools = []
        seen = set()

        # Only list tool classes (not instances)
        # Instances are managed via ToolConfig (RAG/Skill) or MCP server config
        for name, tool_class in ToolRegistry._tool_classes.items():
            if name in seen:
                continue
            seen.add(name)

            # Skip factory classes (they create instances via registry factories)
            if getattr(tool_class, 'is_factory_class', False):
                continue

            # For classes, just get the docstring
            desc = getattr(tool_class, '__doc__', '') or ''
            if not desc:
                desc = getattr(tool_class, 'description', '') or ''
                if callable(desc):
                    desc = ''

            tools.append({
                'name': name,
                'description': desc,
                'is_enabled': cls.is_enabled(name, tenant_id),
            })

        return tools

    @classmethod
    def is_enabled(cls, name: str, tenant_id: Optional[str] = None) -> bool:
        """
        Check if a built-in tool is enabled.

        Args:
            name: Tool name
            tenant_id: Tenant ID

        Returns:
            True if enabled, False if disabled, True by default
        """
        # Ensure initialized
        cls.initialize()

        # Check memory cache first
        cache = cls._enabled_cache.get(tenant_id, {})
        if name in cache:
            return cache[name]

        # Also check global default
        global_cache = cls._enabled_cache.get(None, {})
        if name in global_cache:
            return global_cache[name]

        # Default: enabled
        return True

    @classmethod
    def reload(cls, tenant_id: Optional[str] = None) -> None:
        """
        Reload enabled states from tenant configuration.

        Call this after tenant config is updated.

        Args:
            tenant_id: Specific tenant to reload, or None to reload all
        """
        if tenant_id is not None:
            cls._enabled_cache[tenant_id] = cls._load_from_tenant_config(tenant_id)
        else:
            # Reload all tenants
            cls._initialized = False
            cls.initialize()

    @classmethod
    def ensure_initialized(cls) -> None:
        """Ensure registry is initialized (can be called on startup)."""
        cls.initialize()
