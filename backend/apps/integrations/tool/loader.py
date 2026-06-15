"""
Unified tool loader.

Loads both MCP tools (dynamic discovery) and configured tools (name-based)
from tenant configuration at startup.

Supports multi-instance via ``client_type`` in config:
- ``name``: unique instance identifier
- ``config.client_type``: BaseTool subclass to instantiate (falls back to ``name``)
"""
import logging
from typing import Optional

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


async def load_mcp_tools_for_tenant(
    config: dict,
    tenant_id: Optional[str] = None
) -> int:
    """
    Load and register MCP tools for a tenant.
    
    This function:
    1. Reads MCP_SERVERS configuration from tenant config
    2. Registers each MCP server with MCPServerRegistry
    3. Discovers tools from all registered servers
    4. Registers discovered tools with ToolRegistry
    
    Args:
        config: Tenant configuration dict
        tenant_id: Tenant ID or None for global default
        
    Returns:
        Number of MCP tools registered
    """
    from ..mcp.mcp_server_registry import MCPServerRegistry, MCPServerConfig
    from .base import ToolRegistry
    
    mcp_servers_config = config.get('MCP_SERVERS', [])
    
    if not mcp_servers_config:
        logger.debug(f"No MCP servers configured for tenant '{tenant_id}'")
        return 0
    
    logger.info(f"Loading MCP tools for tenant '{tenant_id}'...")
    
    # Step 1: Register MCP servers
    registered_count = 0
    for server_cfg in mcp_servers_config:
        try:
            mcp_config = MCPServerConfig(**server_cfg)
            MCPServerRegistry.register_server(mcp_config, tenant_id=tenant_id)
            registered_count += 1
            logger.info(
                f"Registered MCP server '{mcp_config.name}' "
                f"(auto_discover={mcp_config.auto_discover})"
            )
        except Exception as e:
            logger.error(
                f"Failed to register MCP server from config {server_cfg}: {e}",
                exc_info=True
            )
    
    if registered_count == 0:
        logger.warning(f"No MCP servers successfully registered for tenant '{tenant_id}'")
        return 0
    
    # Step 2: Discover and register tools
    try:
        discovered_tools = await MCPServerRegistry.discover_tools(tenant_id)
        
        registered_tool_count = 0
        for tool in discovered_tools:
            try:
                ToolRegistry.register(tool)
                logger.info(
                    f"Registered MCP tool '{tool.name}' "
                    f"from server '{tool._server_name}'"
                )
                registered_tool_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to register MCP tool '{tool.name}': {e}",
                    exc_info=True
                )
        
        logger.info(
            f"Successfully loaded {registered_tool_count} MCP tools "
            f"for tenant '{tenant_id}'"
        )
        
        return registered_tool_count
        
    except Exception as e:
        logger.error(
            f"Failed to discover MCP tools for tenant '{tenant_id}': {e}",
            exc_info=True
        )
        return 0


async def load_tools_for_tenant(
    config: dict,
    tenant_id: Optional[str] = None
) -> int:
    """
    Load and register all configured tools for a tenant.

    Unified entry point supporting class-based, MCP, and multi-instance tools:
    - type="class" / "rag" / "skill" (default): Create tool from registered
      BaseTool subclass.  Uses ``config.client_type`` to find the class and
      ``name`` as the unique instance identifier.
    - type="mcp": Register MCP server and discover tools dynamically

    This function also loads MCP servers from the database (McpServerConfig table)
    in addition to the config file.

    Args:
        config: Tenant configuration dict
        tenant_id: Tenant ID or None for global default

    Returns:
        Number of tools registered
    """
    from .base import ToolRegistry
    from .config import ToolConfig

    # Step 1: Load MCP servers from database
    db_mcp_count = await _load_mcp_servers_from_database(tenant_id)

    # Step 2: Load tools from config file
    tools_config = config.get('TOOLS', [])

    if not tools_config:
        logger.debug(f"No TOOLS configuration for tenant '{tenant_id}'")
        # Note: still continue to auto-register zero-config tools below

    logger.info(f"Loading {len(tools_config)} tools for tenant '{tenant_id}'...")
    logger.debug(f"Available tool classes: {ToolRegistry.list_tool_classes()}")

    registered_count = 0

    for tool_cfg_dict in tools_config:
        try:
            # Parse tool configuration
            tool_cfg = ToolConfig.from_dict(tool_cfg_dict)

            if not tool_cfg.enabled:
                logger.debug(f"Skipping disabled tool: {tool_cfg.name}")
                continue

            # Create tool instance based on type - use factory methods
            if tool_cfg.type == "mcp":
                # MCP type: async registration via MCPServerRegistry
                success = await ToolRegistry.create_and_register_async(
                    name=tool_cfg.name,
                    tenant_id=tenant_id,
                    config=tool_cfg.config,
                    tool_type="mcp"
                )

            elif tool_cfg.type == "rag" or tool_cfg.client_type == "rag_search":
                # RAG type: use RAGRegistry factory
                from ..rag.rag_registry import RAGRegistry
                count = RAGRegistry.create_and_register_tools(
                    tenant_id, tool_cfg.name, tool_cfg.config
                )
                success = count > 0

            else:
                # Class-based type: use generic create_and_register
                success = ToolRegistry.create_and_register(
                    name=tool_cfg.client_type,
                    tenant_id=tenant_id,
                    config=tool_cfg.config,
                    instance_name=tool_cfg.name,
                    class_type=tool_cfg.client_type,
                )

            if success:
                logger.info(
                    f"Registered tool '{tool_cfg.name}' "
                    f"(type={tool_cfg.type}, class={tool_cfg.client_type}) "
                    f"for tenant '{tenant_id}'"
                )
                registered_count += 1

        except Exception as e:
            logger.error(f"Failed to load tool {tool_cfg_dict}: {e}", exc_info=True)

    logger.info(f"Loaded {registered_count}/{len(tools_config)} tools from config for tenant '{tenant_id}'")

    # Return total count (database MCP tools + config tools)
    total_count = db_mcp_count + registered_count

    # Auto-register zero-config Tools (requires_config=False)
    total_count += _auto_register_zero_config_tools(tenant_id)

    logger.info(f"Total tools loaded for tenant '{tenant_id}': {total_count}")
    return total_count


def _auto_register_zero_config_tools(tenant_id: Optional[str]) -> int:
    """Auto-register zero-config Tools.

    Scans all registered Tool classes and automatically creates and
    registers instances for Tools with requires_config=False.

    Note: Zero-config tools need separate instances per tenant,
    because the tool internally may use tenant_id to query tenant-specific data.
    """
    from .base import ToolRegistry

    registered_count = 0

    for tool_name, tool_class in ToolRegistry._tool_classes.items():
        # Check if configuration is required
        if getattr(tool_class, 'requires_config', True):
            continue  # Tool requires configuration, skip

        # Check if an instance already exists for this tenant (only check tenant-specific instances)
        if tenant_id and tenant_id in ToolRegistry._tools:
            if tool_name in ToolRegistry._tools[tenant_id]:
                continue

        # Create default instance and register
        try:
            success = ToolRegistry.create_and_register(
                name=tool_name,
                tenant_id=tenant_id,
                config={},
                instance_name=tool_name,
                class_type=tool_name,
            )
            if success:
                logger.info(f"Auto-registered zero-config tool: {tool_name} for tenant '{tenant_id}'")
                registered_count += 1
        except Exception as e:
            logger.warning(f"Failed to auto-register {tool_name}: {e}")

    return registered_count


def _has_tool_instance(tool_name: str, tenant_id: Optional[str]) -> bool:
    """Check whether a Tool instance already exists."""
    from .base import ToolRegistry

    # Check tenant-specific instance
    if tenant_id and tenant_id in ToolRegistry._tools:
        if tool_name in ToolRegistry._tools[tenant_id]:
            return True

    # Check global default instance
    if None in ToolRegistry._tools:
        if tool_name in ToolRegistry._tools[None]:
            return True

    return False


async def _load_mcp_servers_from_database(tenant_id: Optional[str] = None) -> int:
    """Load MCP servers from database and register their tools.

    Args:
        tenant_id: Tenant ID or None for global default

    Returns:
        Number of MCP tools registered from database
    """
    from ...entities import McpServerConfig
    from ..mcp.mcp_server_registry import MCPServerRegistry, MCPServerConfig
    from .base import ToolRegistry

    @sync_to_async(thread_sensitive=False)
    def _query_mcp_servers(tenant_id: Optional[str]) -> list:
        """Sync function to query MCP servers from database."""
        query = McpServerConfig.objects.filter(is_active=True)
        if tenant_id:
            query = query.filter(tenant_id=tenant_id)
        else:
            # Global default: include both tenant_id='' and tenant_id='example'
            # 'example' is used in local development mode and admin endpoints
            from django.db.models import Q
            query = query.filter(Q(tenant_id='') | Q(tenant_id='example'))
        return list(query)

    try:
        # Query active MCP servers for this tenant (async-safe)
        db_servers = await _query_mcp_servers(tenant_id)

        if not db_servers:
            logger.debug(f"No active MCP servers in database for tenant '{tenant_id}'")
            return 0

        logger.info(f"Found {len(db_servers)} active MCP servers in database for tenant '{tenant_id}'")

        # Register each server with MCPServerRegistry
        registered_count = 0
        for db_server in db_servers:
            try:
                cfg = db_server.config or {}
                mcp_config = MCPServerConfig(
                    name=db_server.name,
                    client_type=db_server.client_type or 'stdio',
                    # Stdio fields
                    command=db_server.command or '',
                    args=db_server.args or [],
                    env=db_server.env or {},
                    # HTTP / Custom fields (from config JSON)
                    endpoint=cfg.get('endpoint', ''),
                    # Custom client fields
                    sse_endpoint=cfg.get('sseEndpoint', cfg.get('sse_endpoint', '')),
                    mcp_name=cfg.get('mcpName', cfg.get('mcp_name', '')),
                    list_tools_path=cfg.get('listToolsPath', cfg.get('list_tools_path', '/sample/mcp/listTools')),
                    execute_path=cfg.get('executePath', cfg.get('execute_path', '/sample/mcp/execute')),
                    # Common
                    timeout=cfg.get('timeout', 30),
                    auto_discover=True,  # Auto-discover tools
                )
                MCPServerRegistry.register_server(mcp_config, tenant_id=tenant_id)
                registered_count += 1
                logger.info(
                    f"Registered MCP server from database: '{db_server.name}' "
                    f"(server_id={db_server.server_id}, client_type={db_server.client_type})"
                )
            except Exception as e:
                logger.error(
                    f"Failed to register MCP server '{db_server.name}' from database: {e}",
                    exc_info=True
                )

        if registered_count == 0:
            logger.warning(f"No MCP servers successfully registered from database for tenant '{tenant_id}'")
            return 0

        # Discover and register tools from all registered servers
        try:
            discovered_tools = await MCPServerRegistry.discover_tools(tenant_id)

            registered_tool_count = 0
            for tool in discovered_tools:
                try:
                    ToolRegistry.register(tool, tenant_id=tenant_id)
                    logger.info(
                        f"Registered MCP tool '{tool.name}' "
                        f"from server '{tool._server_name}' (from database)"
                    )
                    registered_tool_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to register MCP tool '{tool.name}': {e}",
                        exc_info=True
                    )

            logger.info(
                f"Successfully loaded {registered_tool_count} MCP tools "
                f"from database for tenant '{tenant_id}'"
            )

            return registered_tool_count

        except Exception as e:
            logger.error(
                f"Failed to discover MCP tools for tenant '{tenant_id}': {e}",
                exc_info=True
            )
            return 0

    except Exception as e:
        logger.error(
            f"Failed to load MCP servers from database for tenant '{tenant_id}': {e}",
            exc_info=True
        )
        return 0
