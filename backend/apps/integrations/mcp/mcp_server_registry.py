"""
MCP Server Registry for managing multiple MCP server connections.

Supports tenant-specific server registration and dynamic tool discovery.
"""
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """
    MCP Server configuration.

    Attributes:
        name: Unique identifier for this MCP server
        endpoint: HTTP endpoint URL (for HTTP/custom client)
        timeout: Request timeout in seconds
        retry_count: Number of retry attempts
        auto_discover: Whether to auto-discover tools on registration
        client_type: Client type - "stdio", "http", or "custom" (default "stdio")
        sse_endpoint: SSE endpoint path (for custom client)
        mcp_name: MCP service name (for custom client)
        list_tools_path: Path for list_tools API (for custom client)
        execute_path: Path for execute API (for custom client)
        command: Command to execute for stdio MCP server (e.g., "npx")
        args: Command arguments for stdio MCP server (e.g., ["-y", "tavily-mcp@latest"])
        env: Environment variables for stdio MCP server
        hidden_fields: List of field names to hide from LLM (injected at runtime)
        _client: Runtime MCP client instance (not serialized)
    """
    name: str
    endpoint: Optional[str] = None
    timeout: int = 30
    retry_count: int = 3
    auto_discover: bool = True

    # Client type and custom MCP client configuration
    client_type: Optional[str] = None
    sse_endpoint: Optional[str] = None
    mcp_name: Optional[str] = None
    list_tools_path: Optional[str] = None
    execute_path: Optional[str] = None

    # Stdio MCP client configuration
    command: Optional[str] = None
    args: Optional[list] = None
    env: Optional[dict] = None

    # Hidden fields - passed to tools created from this server
    hidden_fields: Optional[list] = None

    # Runtime field (not serialized)
    _client: Optional['MCPClientWrapper'] = field(default=None, repr=False, compare=False)


class MCPServerRegistry:
    """
    Registry for MCP server instances.
    
    Supports tenant-specific server registration and tool discovery.
    
    Usage:
        # Register a server
        config = MCPServerConfig(name="example_mcp", endpoint="...", ...)
        MCPServerRegistry.register_server(config, tenant_id="tenant123")
        
        # Get server config
        server = MCPServerRegistry.get_server("example_mcp", tenant_id="tenant123")
        
        # Discover tools from all servers
        tools = await MCPServerRegistry.discover_tools(tenant_id="tenant123")
    """
    
    # Storage: {tenant_id: {server_name: MCPServerConfig}}
    _servers: dict[Optional[str], dict[str, MCPServerConfig]] = {}
    
    @classmethod
    def register_server(
        cls,
        config: MCPServerConfig,
        tenant_id: Optional[str] = None
    ) -> None:
        """
        Register an MCP server for a tenant.
        
        Args:
            config: MCP server configuration
            tenant_id: Tenant ID or None for global default
        """
        bucket = cls._servers.setdefault(tenant_id, {})
        bucket[config.name] = config
        logger.info(f"Registered MCP server '{config.name}' for tenant '{tenant_id}'")
    
    @classmethod
    def get_server(
        cls,
        name: str,
        tenant_id: Optional[str] = None
    ) -> Optional[MCPServerConfig]:
        """
        Get MCP server config by name.
        
        Args:
            name: Server name
            tenant_id: Tenant ID or None to use current tenant from context
            
        Returns:
            MCPServerConfig or None if not found
        """
        from apps.tenant.context import get_current_tenant_id
        
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        
        # Try tenant-specific first
        bucket = cls._servers.get(tenant_id, {})
        if name in bucket:
            return bucket[name]
        
        # Fallback to global default
        global_bucket = cls._servers.get(None, {})
        return global_bucket.get(name)
    
    @classmethod
    def list_servers(
        cls,
        tenant_id: Optional[str] = None
    ) -> list[str]:
        """
        List registered MCP server names for a tenant.
        
        Args:
            tenant_id: Tenant ID or None to use current tenant from context
            
        Returns:
            List of server names
        """
        from apps.tenant.context import get_current_tenant_id
        
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        
        return list(cls._servers.get(tenant_id, {}).keys())
    
    @classmethod
    async def discover_tools(
        cls,
        tenant_id: Optional[str] = None
    ) -> list['MCPDynamicTool']:
        """
        Discover tools from all registered MCP servers for a tenant.
        
        Args:
            tenant_id: Tenant ID or None to use current tenant from context
            
        Returns:
            List of MCPDynamicTool instances ready to be registered
        """
        from apps.tenant.context import get_current_tenant_id
        
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        
        discovered_tools = []
        servers = cls._servers.get(tenant_id, {})
        
        for server_config in servers.values():
            try:
                # Get or create client
                client = await cls._get_or_create_client(server_config)
                
                # List tools from server
                tools = await client.list_tools()
                
                # Create dynamic tool wrappers
                for tool_info in tools:
                    # Import here to avoid circular dependency
                    from .mcp_dynamic_tool import MCPDynamicTool

                    # Build config, pass hidden_fields
                    tool_config = {}
                    if server_config.hidden_fields:
                        tool_config["hidden_fields"] = server_config.hidden_fields

                    dynamic_tool = MCPDynamicTool(
                        name=tool_info.get('name', ''),
                        description=tool_info.get('description', ''),
                        parameters_schema=tool_info.get('inputSchema', {}),
                        server_name=server_config.name,
                        tenant_id=tenant_id,
                        config=tool_config,
                    )
                    discovered_tools.append(dynamic_tool)
                    
                logger.info(
                    f"Discovered {len(tools)} tools from MCP server '{server_config.name}'"
                )
                
            except Exception as e:
                logger.error(
                    f"Failed to discover tools from '{server_config.name}': {e}",
                    exc_info=True
                )
        
        return discovered_tools
    
    @classmethod
    async def _get_or_create_client(
        cls,
        config: MCPServerConfig
    ) -> 'MCPClientWrapper':
        """
        Get or create MCP client for a server.
        
        Args:
            config: MCP server configuration
            
        Returns:
            Connected MCPClientWrapper instance
        """
        import asyncio

        # Check if client exists and is still valid
        if config._client is not None:
            # Check if the client's event loop is still running
            try:
                loop = asyncio.get_running_loop()
                # If we can get the running loop, check if client was created in a different loop
                if hasattr(config._client, '_loop') and config._client._loop is not None:
                    if config._client._loop != loop or config._client._loop.is_closed():
                        # Loop is different or closed, need to recreate client
                        config._client = None
            except RuntimeError:
                # No running event loop, need to recreate client
                config._client = None

        if config._client is None:
            # Import here to avoid circular dependency
            from .mcp_client import MCPClientWrapper
            
            config._client = MCPClientWrapper(config)
            await config._client.connect()
            
        return config._client
    
    @classmethod
    async def call_tool(
        cls,
        server_name: str,
        tool_name: str,
        arguments: dict,
        tenant_id: Optional[str] = None
    ) -> any:
        """
        Call a tool on a specific MCP server.
        
        Args:
            server_name: MCP server name
            tool_name: Tool to call
            arguments: Tool arguments
            tenant_id: Tenant ID or None to use current tenant
            
        Returns:
            Tool execution result
        """
        server_config = cls.get_server(server_name, tenant_id)
        
        if not server_config:
            raise ValueError(f"MCP server '{server_name}' not found")
        
        client = await cls._get_or_create_client(server_config)
        return await client.call_tool(tool_name, arguments)
    
    @classmethod
    def unregister_server(
        cls,
        name: str,
        tenant_id: Optional[str] = None
    ) -> bool:
        """Remove a single MCP server from the registry and cleanup its client.

        Args:
            name: Server name to remove.
            tenant_id: Tenant ID bucket.

        Returns:
            True if a server was removed, False if not found.
        """
        bucket = cls._servers.get(tenant_id)
        if not bucket or name not in bucket:
            return False

        config = bucket.pop(name)
        if config._client:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(config._client.cleanup())
                else:
                    loop.run_until_complete(config._client.cleanup())
            except RuntimeError:
                pass
        logger.info(f"Unregistered MCP server '{name}' for tenant '{tenant_id}'")
        return True

    @classmethod
    def clear(cls, tenant_id: Optional[str] = None) -> None:
        """
        Clear registered servers.
        
        Args:
            tenant_id: Tenant ID to clear, or None to clear all
        """
        if tenant_id is None:
            # Clear all servers
            for bucket in cls._servers.values():
                for config in bucket.values():
                    if config._client:
                        import asyncio
                        try:
                            asyncio.get_event_loop().run_until_complete(
                                config._client.cleanup()
                            )
                        except RuntimeError:
                            pass
            cls._servers.clear()
            logger.info("Cleared all MCP servers")
        else:
            # Clear specific tenant
            bucket = cls._servers.pop(tenant_id, {})
            for config in bucket.values():
                if config._client:
                    import asyncio
                    try:
                        asyncio.get_event_loop().run_until_complete(
                            config._client.cleanup()
                        )
                    except RuntimeError:
                        pass
            logger.info(f"Cleared MCP servers for tenant '{tenant_id}'")
