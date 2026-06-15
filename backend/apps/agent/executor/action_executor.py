"""
Action executor for dispatching actions to appropriate handlers.
"""
import logging
import json
from typing import Any, Mapping, List, TYPE_CHECKING

from ..agent.context import AgentContext

if TYPE_CHECKING:
    from ..hooks.base import HookManager

logger = logging.getLogger(__name__)


class ActionExecutor:
    """
    Executes actions dispatched by the ReAct agent.
    
    Routes actions to appropriate handlers (Tool, Skill).
    """
    
    def __init__(self, hook_manager: "HookManager | None" = None):
        self._tool_registry = {}
        self._hook_manager = hook_manager
    
    async def execute(
        self,
        action: str,
        action_input: Mapping[str, Any],
        context: AgentContext
    ) -> str:
        """
        Execute an action and return the observation.
        
        Args:
            action: Action type (TOOL, SKILL)
            action_input: Input for the action
            context: Agent context
        
        Returns:
            Observation string from executing the action
        """
        action = action.upper()
        
        try:
            if action == 'TOOL':
                return await self._execute_tool(action_input, context)
            else:
                return f"Unknown action type: {action}. Available actions: TOOL, FINISH"
        
        except Exception as e:
            logger.exception(
                f"Error executing action {action} "
                f"(session={getattr(context, 'session_id', 'N/A')}): {e}"
            )
            return f"Error executing {action}: {str(e)}"
    
    async def _execute_tool(
        self,
        tool_input: Mapping[str, Any],
        context: AgentContext
    ) -> str:
        """Execute a tool with hidden parameters injected from context.

        Hook integration (4 call points aligned with Claude Code events):
        1. on_tool_pre_execute  → PreToolUse
        2. tool execution
        3. on_tool_post_execute → PostToolUse   (on success)
        4. on_tool_execute_failure → PostToolUseFailure (on error)
        """
        try:
            # Parse tool name and input
            tool_name = tool_input.get("name")
            tool_args = tool_input.get("arguments")

            from ...integrations.tool.base import ToolRegistry

            tool_registry = ToolRegistry()
            tool = tool_registry.get_tool(tool_name, tenant_id=context.tenant_id)
            logger.debug("execute tool %s %s tenant=%s", tool_name, tool_args, context.tenant_id)

            if tool is None:
                available = tool_registry.list_tools(context.tenant_id)
                return f"Tool '{tool_name}' not found. Available tools: {', '.join(available)}"

            # Inject hidden parameters from context.user_context
            hidden_fields = getattr(tool, 'hidden_fields', []) or []
            merged_args = self._inject_hidden_params(
                tool_args,
                tool_name,
                context,
                hidden_fields
            )

            # ── ① on_tool_pre_execute (PreToolUse) ──────────────────
            injected_context: dict[str, Any] | None = None
            if self._hook_manager and not self._hook_manager.is_empty:
                from ..hooks.base import HookAction
                action, data, ctx = await self._hook_manager.execute_tool_pre_hooks(
                    tool_name, merged_args, context
                )
                if action == HookAction.DENY:
                    reason = data or f"Tool '{tool_name}' execution denied"
                    return reason
                if action == HookAction.STOP:
                    context.metadata['_stop_agent'] = True
                    context.metadata['_stop_reason'] = data or f"Agent stopped by Hook"
                    return data or f"Agent execution stopped"
                if action == HookAction.MODIFY:
                    merged_args = data
                if ctx:
                    injected_context = ctx

            # ── ② tool execution ────────────────────────────────────
            try:
                result = await tool.execute(merged_args, context)
            except Exception as e:
                # ── ③ on_tool_execute_failure (PostToolUseFailure) ──
                if self._hook_manager and not self._hook_manager.is_empty:
                    fail_result = await self._hook_manager.execute_tool_failure_hooks(
                        tool_name, str(e), context
                    )
                    if fail_result.injected_context:
                        if injected_context is None:
                            injected_context = {}
                        injected_context.update(fail_result.injected_context)

                logger.exception(
                    f"Tool '{tool_name}' execution failed "
                    f"(session={getattr(context, 'session_id', 'N/A')}, "
                    f"args={str(tool_args)[:200]}): {e}"
                )
                err_msg = f"Tool execution failed: {str(e)}"
                if injected_context:
                    err_msg = json.dumps({
                        "error": err_msg,
                        "context": injected_context,
                    }, ensure_ascii=False)
                return err_msg

            # ── ④ on_tool_post_execute (PostToolUse) ─────────────────
            if self._hook_manager and not self._hook_manager.is_empty:
                post_result = await self._hook_manager.execute_tool_post_hooks(
                    tool_name, result, context
                )
                if post_result.action == HookAction.DENY:
                    return post_result.reason or f"Tool '{tool_name}' execution denied"
                if post_result.action == HookAction.STOP:
                    context.metadata['_stop_agent'] = True
                    context.metadata['_stop_reason'] = post_result.reason
                    return post_result.reason or f"Agent stopped by Hook"
                if post_result.action == HookAction.MODIFY and post_result.modified_data:
                    result = post_result.modified_data
                if post_result.injected_context:
                    if injected_context is None:
                        injected_context = {}
                    injected_context.update(post_result.injected_context)

            # Attach injected context to result for LLM consumption
            if injected_context:
                result = json.dumps({
                    "result": result,
                    "context": injected_context,
                }, ensure_ascii=False)

            return result

        except Exception as e:
            logger.exception(
                f"Tool '{tool_name}' execution failed "
                f"(session={getattr(context, 'session_id', 'N/A')}, "
                f"args={str(tool_args)[:200]}): {e}"
            )
            return f"Tool execution failed: {str(e)}"

    def _inject_hidden_params(
        self,
        tool_args: str,
        tool_name: str,
        context: AgentContext,
        hidden_fields: List[str]
    ) -> str:
        """Inject hidden parameters from context.user_context into tool arguments."""
        if not hidden_fields or not context.user_context:
            return tool_args

        # Parse raw arguments
        try:
            args_dict = json.loads(tool_args) if tool_args else {}
        except json.JSONDecodeError:
            args_dict = {"input": tool_args}

        # Get hidden parameters (tool-level first, then global)
        user_ctx = (
            context.user_context.get(tool_name) or
            context.user_context.get("_global") or
            {}
        )

        # Inject hidden parameters
        for field in hidden_fields:
            if field not in args_dict and field in user_ctx:
                args_dict[field] = user_ctx[field]

        return json.dumps(args_dict, ensure_ascii=False)
