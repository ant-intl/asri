"""
Tool reload manager for dynamic tool configuration updates.

Manages tool reloading when tenant configuration changes:
- Tracks configuration hash to detect changes
- Reloads tools when configuration is updated
- Integrated with TenantRegistry refresh mechanism
"""
import hashlib
import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


def compute_tools_hash(tools: list[dict]) -> str:
    """Compute hash of tool configuration for change detection.

    Args:
        tools: List of tool configuration dicts

    Returns:
        MD5 hash string
    """
    if not tools:
        return "empty"

    # Normalize for consistent hashing
    normalized = []
    for tool in sorted(tools, key=lambda x: x.get('name', '')):
        normalized.append({
            'name': tool.get('name'),
            'type': tool.get('type'),
            'enabled': tool.get('enabled'),
            'config': tool.get('config', {}),
        })
    content = json.dumps(normalized, sort_keys=True)
    return hashlib.md5(content.encode()).hexdigest()


class ToolReloadManager:
    """Manages dynamic tool reloading based on configuration changes.

    This manager:
    - Tracks tool configuration hash per tenant
    - Detects configuration changes
    - Triggers tool reload when needed
    - Supports both immediate reload (on config change) and periodic MCP reload
    """

    _instance: Optional['ToolReloadManager'] = None
    _lock = threading.Lock()
    MCP_RELOAD_INTERVAL = 300  # 5 minutes

    def __init__(self):
        self._config_hashes: dict[Optional[str], str] = {}  # tenant_id -> config hash
        self._last_reload: float = 0.0
        self._last_mcp_reload: float = 0.0

    @classmethod
    def get_instance(cls) -> 'ToolReloadManager':
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_hash(self, tenant_id: Optional[str]) -> str:
        """Get stored hash for tenant."""
        return self._config_hashes.get(tenant_id, '')

    def update_hash(self, tenant_id: Optional[str], config: dict) -> None:
        """Update configuration hash for tenant.

        Args:
            tenant_id: Tenant ID or None for global
            config: Tenant configuration dict
        """
        tools = config.get('TOOLS', [])
        self._config_hashes[tenant_id] = compute_tools_hash(tools)
        logger.debug(f"Updated tool config hash for tenant '{tenant_id}': {self._config_hashes[tenant_id]}")

    def should_reload(self, tenant_id: Optional[str], current_config: dict) -> bool:
        """Check if tools should be reloaded for tenant.

        Args:
            tenant_id: Tenant ID or None for global
            current_config: Current tenant configuration

        Returns:
            True if configuration changed and reload is needed
        """
        current_hash = compute_tools_hash(current_config.get('TOOLS', []))
        stored_hash = self._config_hashes.get(tenant_id, '')

        if current_hash != stored_hash:
            logger.info(f"Tool config changed for tenant '{tenant_id}': {stored_hash[:8]} -> {current_hash[:8]}")
            return True

        return False

    async def reload_if_needed(
        self,
        tenant_id: Optional[str],
        config: dict,
        force: bool = False
    ) -> int:
        """Reload tools if configuration has changed.

        Args:
            tenant_id: Tenant ID or None for global
            config: Current tenant configuration
            force: Force reload regardless of hash change

        Returns:
            Number of tools reloaded, 0 if no reload needed
        """
        if not force and not self.should_reload(tenant_id, config):
            return 0

        # Clear existing tools for this tenant
        await self._clear_tools(tenant_id)

        # Reload tools
        from .loader import load_tools_for_tenant
        count = await load_tools_for_tenant(config, tenant_id)

        # Update hash after successful reload
        self.update_hash(tenant_id, config)

        logger.info(f"Reloaded {count} tools for tenant '{tenant_id}'")
        return count

    async def _clear_tools(self, tenant_id: Optional[str]) -> None:
        """Clear existing tool instances for tenant.

        Args:
            tenant_id: Tenant ID or None for global
        """
        from .base import ToolRegistry
        from ..mcp.mcp_server_registry import MCPServerRegistry

        # Clear MCP servers (this also cleans up connections)
        try:
            MCPServerRegistry.clear(tenant_id)
        except Exception as e:
            logger.warning(f"Failed to clear MCP servers for tenant '{tenant_id}': {e}")

        # Clear tool instances
        if tenant_id in ToolRegistry._tools:
            del ToolRegistry._tools[tenant_id]
            logger.debug(f"Cleared tools for tenant '{tenant_id}'")

    async def reload_all_if_needed(self, config_map: dict[str, dict]) -> dict[str, int]:
        """Reload tools for all tenants if configuration changed.

        Args:
            config_map: Dict of tenant_id -> config

        Returns:
            Dict of tenant_id -> number of tools reloaded
        """
        results = {}

        # Always check global config
        global_config = config_map.get(None, {})
        count = await self.reload_if_needed(None, global_config)
        if count > 0:
            results[None] = count

        # Check each tenant
        for tenant_id, config in config_map.items():
            if tenant_id is None:
                continue
            count = await self.reload_if_needed(tenant_id, config)
            if count > 0:
                results[tenant_id] = count

        return results

    async def reload_mcp_if_needed(self) -> int:
        """Periodically reload MCP tools to pick up server changes.

        MCP servers may add/remove/update tools dynamically, so we need to
        periodically refresh the tool list even if configuration hasn't changed.

        Returns:
            Number of MCP tools reloaded, 0 if not time for reload
        """
        now = time.time()
        if now - self._last_mcp_reload < self.MCP_RELOAD_INTERVAL:
            return 0

        logger.info("Starting periodic MCP tool refresh...")

        try:
            from ..mcp.mcp_server_registry import MCPServerRegistry
            from ...tenant.registry import get_tenant_registry

            registry = get_tenant_registry()
            total_reloaded = 0

            # Reload MCP tools for each tenant
            for tenant_id in registry.list_tenant_ids():
                config = registry.get_config(tenant_id)
                mcp_tools = [
                    t for t in config.get('TOOLS', [])
                    if t.get('type') == 'mcp' and t.get('enabled', False)
                ]

                for tool_cfg in mcp_tools:
                    try:
                        # Re-register MCP server to discover new tools
                        await MCPServerRegistry.discover_tools(
                            tenant_id=tenant_id,
                            server_name=tool_cfg.get('name')
                        )
                        total_reloaded += 1
                    except Exception as e:
                        logger.warning(f"Failed to reload MCP tool {tool_cfg.get('name')}: {e}")

            # Also check global config
            global_config = registry.get_config(None)
            global_mcp_tools = [
                t for t in global_config.get('TOOLS', [])
                if t.get('type') == 'mcp' and t.get('enabled', False)
            ]

            for tool_cfg in global_mcp_tools:
                try:
                    await MCPServerRegistry.discover_tools(
                        tenant_id=None,
                        server_name=tool_cfg.get('name')
                    )
                    total_reloaded += 1
                except Exception as e:
                    logger.warning(f"Failed to reload global MCP tool {tool_cfg.get('name')}: {e}")

            self._last_mcp_reload = now

            if total_reloaded > 0:
                logger.info(f"Periodic MCP refresh complete: {total_reloaded} tools refreshed")

            return total_reloaded

        except Exception as e:
            logger.error(f"Failed to perform periodic MCP refresh: {e}")
            return 0


# Singleton accessor
_tool_reload_manager: Optional[ToolReloadManager] = None


def get_tool_reload_manager() -> ToolReloadManager:
    """Get the singleton ToolReloadManager instance."""
    global _tool_reload_manager
    if _tool_reload_manager is None:
        _tool_reload_manager = ToolReloadManager.get_instance()
    return _tool_reload_manager
