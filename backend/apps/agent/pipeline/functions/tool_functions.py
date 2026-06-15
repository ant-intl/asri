"""
Tool function definitions for Pipeline Agent.

Dynamically builds pipecat FunctionSchema list and matching execution
handlers based on ToolRegistry and AgentContext capabilities.

Architecture:
- build_tool_schemas(): returns OpenAI tool schemas (LLM-visible)
- build_function_handlers(): returns handler dict (internal execution)
  - All tools route through a single _execute_tool_fn internal function
  - execute_tool itself is NOT exposed as a schema to the LLM
"""
import json
import logging
import uuid
from typing import Callable, Awaitable

from ..framework import FunctionSchema, FunctionCallParams

from ...agent.context import AgentContext
from ...executor.action_executor import ActionExecutor

logger = logging.getLogger(__name__)


def build_tool_schemas(
    context: AgentContext,
) -> list[FunctionSchema]:
    """Build pipecat FunctionSchema list from ToolRegistry.

    All tool schemas are driven by ToolRegistry — no hardcoded schemas.
    Each registered tool gets its own function schema exposed to the LLM.

    Args:
        context: Agent context with tenant_id for tool isolation.

    Returns:
        List of FunctionSchema for tools the LLM may call.
    """
    from ....integrations.tool.base import ToolRegistry

    schemas: list[FunctionSchema] = []
    registered_tool_schemas = ToolRegistry.list_tools_with_schemas(tenant_id=context.tenant_id)

    for tool_schema_dict in registered_tool_schemas:
        func = tool_schema_dict.get('function', {})
        tool_name = func.get('name', '')
        if tool_name:
            schemas.append(FunctionSchema(
                name=tool_name,
                description=func.get('description', ''),
                properties=func.get('parameters', {}).get('properties', {}),
                required=func.get('parameters', {}).get('required', []),
            ))

    return schemas


def build_function_handlers(
    executor: ActionExecutor,
    context: AgentContext,
) -> dict[str, Callable[[FunctionCallParams], Awaitable[None]]]:
    """Build function handler dict for pipecat register_function().

    All tool calls route through a single internal execution function
    (``_execute_tool_fn``) that dispatches via ActionExecutor.

    Args:
        executor: ActionExecutor instance for dispatching.
        context: Agent context for trace recording.

    Returns:
        Dict mapping function_name to async handler callable.
    """
    handlers: dict[str, Callable[[FunctionCallParams], Awaitable[None]]] = {}

    async def _execute_tool_fn(
        tool_name: str,
        tool_input: str | dict,
        params: FunctionCallParams,
    ) -> str:
        """Internal unified tool execution function.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Tool input (string or dict).
            params: Original FunctionCallParams for result_callback.

        Returns:
            Tool execution result string.
        """
        tool_call_id = f"call_{uuid.uuid4().hex[:12]}"

        if isinstance(tool_input, dict):
            tool_input_str = json.dumps(tool_input, ensure_ascii=False)
        else:
            tool_input_str = str(tool_input) if tool_input else ""

        logger.info(f"Tool execute: {tool_name} (tool_call_id={tool_call_id})")

        context.add_trace(
            "tool_call",
            status="calling",
            tool_name=tool_name,
            parameters=tool_input_str,
            tool_call_id=tool_call_id
        )

        try:
            observation = await executor.execute(
                action="TOOL",
                action_input={"name": tool_name, "arguments": tool_input_str},
                context=context,
            )
            trace_status = "success"
        except Exception as e:
            logger.exception(f"Tool '{tool_name}' execution raised exception: {e}")
            observation = f"Tool execution failed: {str(e)}"
            trace_status = "error"

        context.add_trace(
            "tool_result",
            status=trace_status,
            tool_name=tool_name,
            result={"result": observation[:500] if observation else ""},
            tool_call_id=tool_call_id
        )

        result = {"result": observation} if observation else {"result": ""}
        if params.result_callback:
            await params.result_callback(result)

        return observation or ""

    def _create_handler(tool_name: str):
        """Create a handler for a specific tool."""
        async def handler(params: FunctionCallParams) -> str:
            args = params.arguments or {}
            return await _execute_tool_fn(
                tool_name=tool_name,
                tool_input=args,
                params=params,
            )
        return handler

    # Register handlers for all tools from ToolRegistry
    from ....integrations.tool.base import ToolRegistry

    registered_tool_schemas = ToolRegistry.list_tools_with_schemas(
        tenant_id=context.tenant_id
    )
    for tool_schema_dict in registered_tool_schemas:
        func = tool_schema_dict.get('function', {})
        tool_name = func.get('name', '')
        if tool_name and tool_name not in handlers:
            handlers[tool_name] = _create_handler(tool_name)

    return handlers
