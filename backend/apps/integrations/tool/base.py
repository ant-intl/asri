"""
Base Tool abstract class.
"""
import logging

from abc import ABC, abstractmethod
from typing import Any, Optional, List

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for tools.
    
    Subclasses are automatically registered in ToolRegistry when the module is imported.
    The class-level ``name`` attribute is used for class lookup (client_type).
    The instance-level ``_instance_name`` is used as the unique identifier
    exposed to the LLM and stored in ToolRegistry.
    """
    
    # Basic attributes
    name: str = ''                    # Tool class name (used for __init_subclass__ class registration)
    parameters_schema: dict = {}      # JSON Schema parameter definition
    is_factory_class: bool = False    # Whether this is a factory class (factory classes are not listed individually)

    # List of fields to hide (not visible to LLM, injected from context during execution)
    hidden_fields: List[str] = []

    # Instance name (separate from class name, used for multi-instance scenarios)
    _instance_name: Optional[str] = None

    @property
    def instance_name(self) -> str:
        """Return the unique instance name for this tool.

        Falls back to the class-level ``name`` when ``_instance_name``
        is not set, preserving backward compatibility.
        """
        return self._instance_name or self.name

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        pass
    
    # Tenant isolation attributes
    tenant_id: Optional[str] = None   # Owning tenant (None means global default)
    
    # Tool configuration
    config: dict = {}                 # Tool-specific configuration

    # Whether the tool result needs to be processed by LLM after execution.
    # When False, the Agent loop skips subsequent LLM calls.
    requires_llm: bool = True

    def __init__(self, tenant_id: Optional[str] = None, config: Optional[dict] = None):
        """Initialize a Tool instance."""
        self.tenant_id = tenant_id
        self.config = config or {}
        # Allow config_json.requires_llm from DB config to override class default
        if 'requires_llm' in self.config:
            self.requires_llm = self.config['requires_llm']

    def __init_subclass__(cls, **kwargs):
        """Automatically register subclass when module is imported."""
        super().__init_subclass__(**kwargs)
        # Only register if it's a concrete class (has name defined)
        if cls.name:
            ToolRegistry.register_class(cls)
    
    @abstractmethod
    async def execute(self, input_text: str, context: Any) -> str:
        """Execute the tool and return result."""
        pass
    
    def to_tool_schema(self) -> dict:
        """Convert to OpenAI tools format function definition.

        Returns:
            Dict with 'type' and 'function' keys.
            Hidden fields are filtered out from parameters schema.
            Uses ``instance_name`` so the LLM sees the unique instance
            identifier rather than the shared class name.
        """
        func: dict = {
            "name": self.instance_name,
            "description": self.description,
        }
        if self.parameters_schema:
            func["parameters"] = self._filter_hidden_fields(self.parameters_schema)
        return {"type": "function", "function": func}

    def _filter_hidden_fields(self, schema: dict) -> dict:
        """Remove hidden fields from parameters_schema."""
        if not self.hidden_fields or not schema.get("properties"):
            return schema

        filtered = dict(schema)
        properties = dict(schema.get("properties", {}))
        required = [f for f in schema.get("required", []) if f not in self.hidden_fields]

        for field in self.hidden_fields:
            properties.pop(field, None)

        filtered["properties"] = properties
        filtered["required"] = required
        return filtered

    def _default_parameters(self) -> dict:
        """Default parameters schema (subclasses can override)."""
        return {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Input for the tool"
                }
            },
            "required": ["input"]
        }


class ToolRegistry:
    """Registry for tool instances with tenant isolation.
    
    Supports both class registration (auto-registered via __init_subclass__)
    and instance registration (for runtime-created tools like MCPDynamicTool).

    Class lookup uses ``client_type`` (the class-level ``name`` attribute),
    while instance storage uses ``instance_name`` (unique per tool instance).
    """
    
    # Storage structure:
    # - _tool_classes: {client_type: BaseTool subclass}  # class dict indexed by class name
    # - _tools: {tenant_id: {instance_name: BaseTool instance}}  # tenant-isolated instance dict
    _tool_classes: dict[str, type[BaseTool]] = {}
    _tools: dict[Optional[str], dict[str, BaseTool]] = {}
    
    @classmethod
    def register_class(cls, tool_class: type[BaseTool]) -> None:
        """Register a tool class by its name attribute.
        
        Called automatically when a BaseTool subclass is defined.
        """
        if tool_class.name:
            cls._tool_classes[tool_class.name.lower()] = tool_class
    
    @classmethod
    def get_tool_class(cls, name: str) -> type[BaseTool] | None:
        """Get a tool class by name."""
        return cls._tool_classes.get(name.lower())
    
    @classmethod
    def list_tool_classes(cls) -> list[str]:
        """List all registered tool class names."""
        return sorted(cls._tool_classes.keys())
    
    @classmethod
    def register(cls, tool: BaseTool, tenant_id: Optional[str] = None) -> None:
        """Register a tool instance by its instance_name."""
        bucket = cls._tools.setdefault(tenant_id, {})
        bucket[tool.instance_name.lower()] = tool
    
    @classmethod
    def create_and_register(
        cls,
        name: str,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
        instance_name: Optional[str] = None,
        class_type: Optional[str] = None,
    ) -> bool:
        """Create a tool instance from registered class and register it.

        Args:
            name: Tool name (used to find the class when class_type is not given)
            tenant_id: Tenant ID for isolation
            config: Optional configuration dict passed to tool constructor
            instance_name: Unique instance identifier. Falls back to ``name``
                when not provided (backward compatible).
            class_type: Explicit class lookup key. Falls back to ``name``
                when not provided (backward compatible).

        Returns:
            True if successful, False otherwise
        """
        lookup_key = class_type or name
        store_key = instance_name or name

        tool_class = cls.get_tool_class(lookup_key)
        if not tool_class:
            logger.error(f"Tool class not found: {lookup_key}. Available: {cls.list_tool_classes()}")
            return False

        try:
            # Create instance with tenant_id and config
            tool = tool_class(tenant_id=tenant_id, config=config or {})
            tool._instance_name = store_key
            cls.register(tool, tenant_id=tenant_id)
            return True
        except Exception as e:
            logger.error(f"Failed to create tool {store_key} (class={lookup_key}): {e}", exc_info=True)
            return False

    @classmethod
    async def create_and_register_async(
        cls,
        name: str,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
        tool_type: str = "class",
        instance_name: Optional[str] = None,
        class_type: Optional[str] = None,
    ) -> bool:
        """Create and register a tool instance, supporting both class and MCP types.

        Args:
            name: Tool name (used to find the class or MCP server name)
            tenant_id: Tenant ID for isolation
            config: Optional configuration dict passed to tool constructor
            tool_type: Tool type - "class" for regular tools, "mcp" for MCP servers
            instance_name: Unique instance identifier for class-based tools.
            class_type: Explicit class lookup key for class-based tools.

        Returns:
            True if successful, False otherwise
        """
        if tool_type == "mcp":
            # MCP type: register server and discover tools
            from ..mcp.mcp_server_registry import MCPServerRegistry, MCPServerConfig

            mcp_config = MCPServerConfig(name=name, **(config or {}))
            MCPServerRegistry.register_server(mcp_config, tenant_id=tenant_id)

            # Discover tools from the MCP server
            discovered_tools = await MCPServerRegistry.discover_tools(tenant_id)

            for tool in discovered_tools:
                cls.register(tool, tenant_id=tenant_id)
                logger.info(
                    f"Registered MCP tool '{tool.instance_name}' from server '{tool._server_name}'"
                )

            return True
        else:
            # Class type: use new parameters
            return cls.create_and_register(
                name, tenant_id, config,
                instance_name=instance_name,
                class_type=class_type,
            )
    
    @classmethod
    def get_tool(cls, name: str, tenant_id: Optional[str] = None) -> BaseTool | None:
        """Get a tool by instance name (tenant-specific first, then global default).

        Built-in tools (from _tool_classes) are filtered based on BuiltInToolRegistry state.
        """
        tool = None

        # 1. Query tenant-specific tools
        if tenant_id and tenant_id in cls._tools:
            tool = cls._tools[tenant_id].get(name.lower())
            if tool:
                # Check if built-in tool is disabled
                if cls._is_builtin_disabled(name, tenant_id):
                    return None
                return tool

        # 2. Fall back to global default
        if None in cls._tools:
            tool = cls._tools[None].get(name.lower())
            if tool:
                # Check if built-in tool is disabled
                if cls._is_builtin_disabled(name, tenant_id):
                    return None
                return tool

        return None

    @classmethod
    def _is_builtin_disabled(cls, name: str, tenant_id: Optional[str] = None) -> bool:
        """Check if a tool is a built-in tool that has been disabled.

        Args:
            name: Tool name
            tenant_id: Tenant ID

        Returns:
            True if the tool is a built-in (from _tool_classes) and is disabled
        """
        # Check if this is a built-in tool (registered via _tool_classes)
        from .builtin_registry import BuiltInToolRegistry

        # Check if tool name matches a registered class
        if name.lower() in cls._tool_classes:
            return not BuiltInToolRegistry.is_enabled(name.lower(), tenant_id)

        return False

    @staticmethod
    def _is_mcp_server_active(tool: 'BaseTool', tenant_id: Optional[str]) -> bool:
        """Check if an MCP tool's server is still active in the database.

        Non-MCP tools always return True. MCP tools are checked by querying
        the database for the server's is_active status.

        This method may be called from a sync function while an async event
        loop is running (e.g. list_tools_with_schemas called from
        build_function_handlers inside an async _build_pipeline). Django
        raises SynchronousOnlyOperation in that scenario, so we detect the
        running loop and offload the ORM query to a worker thread.

        Args:
            tool: Tool instance to check.
            tenant_id: Tenant ID for server lookup.

        Returns:
            True if the tool is not an MCP tool, or its MCP server is active.
        """
        # Only check MCPDynamicTool instances
        if type(tool).__name__ != 'MCPDynamicTool':
            return True

        server_name = getattr(tool, '_server_name', None)
        if not server_name:
            return True

        def _query_exists() -> bool:
            from ...entities import McpServerConfig as McpServerConfigModel
            from django.db.models import Q

            query = McpServerConfigModel.objects.filter(name=server_name, is_active=True)
            if tenant_id:
                query = query.filter(tenant_id=tenant_id)
            else:
                query = query.filter(Q(tenant_id='') | Q(tenant_id='example'))
            return query.exists()

        import asyncio
        try:
            asyncio.get_running_loop()
            # Running inside an async context — execute in a worker thread
            # to avoid Django's SynchronousOnlyOperation.
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_query_exists).result(timeout=5)
        except RuntimeError:
            # No running event loop — safe to call ORM directly.
            return _query_exists()

    @classmethod
    def unregister_by_server(cls, server_name: str, tenant_id: Optional[str] = None) -> int:
        """Remove all MCP tools belonging to a specific server.

        Args:
            server_name: MCP server name to match against tool._server_name.
            tenant_id: Tenant ID bucket to search in.

        Returns:
            Number of tools removed.
        """
        bucket = cls._tools.get(tenant_id)
        if not bucket:
            return 0

        to_remove = [
            name for name, tool in bucket.items()
            if getattr(tool, '_server_name', None) == server_name
        ]
        for name in to_remove:
            del bucket[name]

        if to_remove:
            logger.info(
                f"Unregistered {len(to_remove)} tools for MCP server "
                f"'{server_name}' (tenant={tenant_id}): {to_remove}"
            )
        return len(to_remove)

    @classmethod
    def list_tools(cls, tenant_id: Optional[str] = None) -> list:
        """List all registered tool instance names (excluding disabled built-ins)."""
        tools = set()

        # Collect tenant-specific tools
        if tenant_id and tenant_id in cls._tools:
            for name in cls._tools[tenant_id].keys():
                if not cls._is_builtin_disabled(name, tenant_id):
                    tools.add(name)

        # Collect global default tools (deduplicate, exclude disabled)
        if None in cls._tools:
            for name in cls._tools[None].keys():
                if not cls._is_builtin_disabled(name, tenant_id):
                    tools.add(name)

        return sorted(tools)

    @classmethod
    def list_tools_with_schemas(cls, tenant_id: Optional[str] = None) -> list[dict]:
        """Return OpenAI tool schema dicts for all registered tools
        (excluding disabled built-ins and inactive MCP servers).

        Tools are sorted deterministically by instance name to ensure
        stable prefix caching across requests.
        """
        from .builtin_registry import BuiltInToolRegistry

        # Ensure built-in registry is initialized
        BuiltInToolRegistry.ensure_initialized()

        tools = []
        seen_names = set()

        # Add tenant-specific tools first
        if tenant_id and tenant_id in cls._tools:
            for tool in cls._tools[tenant_id].values():
                # Skip disabled built-in tools
                if cls._is_builtin_disabled(tool.instance_name, tenant_id):
                    continue
                # Skip tools from inactive MCP servers
                if not cls._is_mcp_server_active(tool, tenant_id):
                    continue
                tools.append(tool.to_tool_schema())
                seen_names.add(tool.instance_name.lower())

        # Add global default tools (deduplicate, exclude disabled)
        if None in cls._tools:
            for tool in cls._tools[None].values():
                if tool.instance_name.lower() in seen_names:
                    continue
                # Skip disabled built-in tools
                if cls._is_builtin_disabled(tool.instance_name, tenant_id):
                    continue
                # Skip tools from inactive MCP servers
                if not cls._is_mcp_server_active(tool, tenant_id):
                    continue
                tools.append(tool.to_tool_schema())

        # Sort deterministically by tool name to ensure stable vLLM prefix cache
        tools.sort(key=lambda t: t.get('function', {}).get('name', ''))
        return tools
