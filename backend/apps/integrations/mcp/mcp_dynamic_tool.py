"""
Dynamic tool wrapper for MCP remote tools.

Creates BaseTool instances at runtime for tools discovered from MCP servers.
"""
import copy
import json
import logging
from typing import Any, Optional, List

from ..tool.base import BaseTool


logger = logging.getLogger(__name__)

# Mock configuration for proxy tool (mcpToolExecute) inner tools
# key: mcpToolName, value: mock executeResult (static dict or callable)
_PROXY_TOOL_MOCKS: dict[str, Any] = {
}


def resolve_schema_refs(schema: dict) -> dict:
    """Resolve $defs/$ref in JSON Schema to produce a fully inlined schema.

    Many MCP servers (especially Python/Pydantic based) return parameter
    schemas with $defs and $ref.  Some LLM providers (e.g. Google Gemini)
    do not support these JSON Schema features and require all type
    definitions to be inlined.

    Args:
        schema: JSON Schema dict that may contain $defs and $ref.

    Returns:
        A new dict with all $ref replaced by their definitions and $defs removed.
    """
    if not isinstance(schema, dict):
        return schema

    defs = schema.get("$defs") or schema.get("definitions") or {}

    def _resolve(node: Any, seen: set | None = None) -> Any:
        if seen is None:
            seen = set()

        if isinstance(node, dict):
            # Handle $ref
            ref = node.get("$ref")
            if ref and isinstance(ref, str) and ref.startswith("#/"):
                # e.g. "#/$defs/ModelName" or "#/definitions/ModelName"
                parts = ref.lstrip("#/").split("/")
                resolved = defs
                for part in parts[1:]:  # skip "$defs" or "definitions" prefix
                    if isinstance(resolved, dict):
                        resolved = resolved.get(part, {})
                    else:
                        return node  # Cannot resolve, return as-is

                # Guard against circular references
                ref_key = ref
                if ref_key in seen:
                    return {"type": "object", "description": f"(circular: {parts[-1]})"}
                seen = seen | {ref_key}
                return _resolve(copy.deepcopy(resolved), seen)

            # Recursively process all keys, skip $defs/definitions
            result = {}
            for key, value in node.items():
                if key in ("$defs", "definitions"):
                    continue
                result[key] = _resolve(value, seen)
            return result

        if isinstance(node, list):
            return [_resolve(item, seen) for item in node]

        return node

    return _resolve(schema)


class MCPDynamicTool(BaseTool):
    """
    Dynamic tool that delegates execution to a remote MCP server.

    Created at runtime when discovering tools from registered MCP servers.
    Each instance represents one remote tool available on a specific MCP server.

    Attributes:
        name: Tool name (from MCP server)
        description: Tool description (from MCP server)
        parameters_schema: JSON schema for tool parameters (from MCP server)
        _server_name: Name of the MCP server hosting this tool
        _tenant_id: Tenant ID for tenant-specific isolation
    """

    # Factory class: tools are dynamically discovered via MCPServerRegistry, not shown in built-in list
    is_factory_class = True

    def __init__(
            self,
            name: str,
            description: str,
            parameters_schema: dict,
            server_name: str,
            tenant_id: Optional[str] = None,
            config: Optional[dict] = None,
    ):
        """
        Initialize a dynamic MCP tool.

        Args:
            name: Tool name
            description: Tool description
            parameters_schema: JSON schema for parameters
            server_name: Name of the MCP server
            tenant_id: Tenant ID for isolation
            config: Optional tool configuration
        """
        self.name = name
        self._description = description
        self.parameters_schema = resolve_schema_refs(parameters_schema) if parameters_schema else {}
        self._server_name = server_name
        self._tenant_id = tenant_id
        self.config = config or {}

        # Read hidden_fields from config
        self.hidden_fields: List[str] = self.config.get("hidden_fields", [])

    @property
    def description(self) -> str:
        """Description of the MCP tool."""
        return self._description

    async def execute(self, input_text: str, context: Any) -> str:
        """
        Execute the remote MCP tool.
        
        Args:
            input_text: Tool input in format "tool_name:json_args" or just "json_args"
            context: AgentContext instance (may be None)
            
        Returns:
            Tool execution result as string
        """
        # Import here to avoid circular dependency
        from .mcp_server_registry import MCPServerRegistry

        server_config = MCPServerRegistry.get_server(
            self._server_name,
            self._tenant_id
        )

        if not server_config:
            error_msg = f"MCP server '{self._server_name}' not found."
            logger.error(error_msg)
            return error_msg

        # Parse input_text as JSON arguments
        arguments = self._parse_input(input_text)

        # Check proxy tool inner tool mock
        mock_result = self._check_proxy_tool_mock(arguments)
        if mock_result is not None:
            logger.info(f"Returning mock result for proxy tool '{self.name}'")
            return self._format_result(mock_result, context)

        logger.info(
            f"Executing MCP tool '{self.name}' via server '{self._server_name}', "
            f"args: {arguments}"
        )

        try:
            # Get or create client
            client = await MCPServerRegistry._get_or_create_client(server_config)

            # Call remote tool
            result = await client.call_tool(self.name, arguments)

            # Format and return result
            return self._format_result(result, context)

        except Exception as e:
            logger.exception(
                f"MCP tool '{self.name}' execution failed "
                f"(server={self._server_name}, "
                f"args={str(arguments)[:200]}): {e}"
            )
            return f"MCP tool '{self.name}' execution failed: {str(e)}"

    def _parse_input(self, input_text: str) -> dict:
        """
        Parse input text into arguments dictionary.
        
        Args:
            input_text: Input string (JSON or plain text)
            
        Returns:
            Parsed arguments dict
        """
        input_text = input_text.strip()

        if not input_text:
            return {}

        # Try to parse as JSON first
        try:
            return json.loads(input_text)
        except json.JSONDecodeError:
            pass

        # Try to handle "tool_name:args" format
        parts = input_text.split(':', 1)
        if len(parts) > 1:
            try:
                return json.loads(parts[1].strip())
            except json.JSONDecodeError:
                return {"input": parts[1].strip()}

        # Fall back to treating entire input as a string argument
        return {"input": input_text}

    def _format_result(self, result: Any, context: Any = None) -> str:
        """
        Format tool result as string.
        
        Handles special cases like card responses from MCP servers.
        
        Args:
            result: Tool result (any type)
            context: AgentContext instance (optional)
            
        Returns:
            Formatted result string
        """
        # Handle card responses (business card MCP pattern)
        if isinstance(result, dict):
            is_card = (
                    result.get('businessCardMCPAnswer') and
                    result.get('businessCardList')
            )

            if is_card and context is not None:
                if hasattr(context, 'metadata') and isinstance(context.metadata, dict):
                    context.metadata['card_response'] = True
                logger.info("Detected card response from MCP")
                return json.dumps(result, ensure_ascii=False, indent=2)

            # Regular dict response
            return json.dumps(result, ensure_ascii=False)

        # Handle list responses
        if isinstance(result, list):
            return json.dumps(result, ensure_ascii=False)

        # Handle other types
        return str(result)

    def _check_proxy_tool_mock(self, arguments: dict) -> Optional[dict]:
        """Check if proxy tool arguments contain mocked inner tools.

        For mcpToolExecute pattern: inspect mcpExecuteTools array,
        if an inner tool's mcpToolName matches _PROXY_TOOL_MOCKS,
        fill its executeResult with mock data.
        Supports both static dict and callable mock values.

        Returns:
            Modified arguments dict with mock results filled, or None if no mock matched.
        """
        mcp_execute_tools = arguments.get('mcpExecuteTools')
        if not isinstance(mcp_execute_tools, list):
            return None

        has_mock = False
        result_tools = []
        for tool_entry in mcp_execute_tools:
            tool_name = tool_entry.get('mcpToolName', '')
            if tool_name in _PROXY_TOOL_MOCKS:
                mock_value = _PROXY_TOOL_MOCKS[tool_name]
                if callable(mock_value):
                    execute_result = mock_value(tool_entry, arguments)
                    if execute_result is None:
                        # callable returning None means no mock, skip
                        result_tools.append(tool_entry)
                        continue
                else:
                    execute_result = mock_value

                has_mock = True
                logger.info(f"Mock hit for inner tool '{tool_name}' in proxy tool '{self.name}'")
                result_tools.append({
                    **tool_entry,
                    'executeResult': execute_result,
                })
            else:
                result_tools.append(tool_entry)

        if has_mock:
            return {**arguments, 'mcpExecuteTools': result_tools}
        return None

    def to_tool_schema(self) -> dict:
        """
        Convert to OpenAI tools format.
        Hidden fields are filtered out from parameters schema.

        Returns:
            Dict with 'type' and 'function' keys
        """
        func = {
            "name": self.name,
            "description": self.description,
        }

        if self.parameters_schema:
            # Filter hidden fields
            func["parameters"] = self._filter_hidden_fields(self.parameters_schema)
        else:
            # Default schema if not provided
            func["parameters"] = {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input for the tool"
                    }
                },
                "required": ["input"]
            }

        return {"type": "function", "function": func}
