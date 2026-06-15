"""
Hook system for intercepting agent lifecycle events.

Aligns with Claude Code Hooks design:
- 5 lifecycle events: on_tool_pre_execute, on_tool_post_execute,
  on_tool_execute_failure, on_user_message, on_agent_stop
- 5 control abilities: ALLOW, DENY, MODIFY, INJECT_CONTEXT, STOP
"""
from .base import HookAction, HookResult, BaseHook, HookManager

__all__ = [
    'HookAction',
    'HookResult',
    'BaseHook',
    'HookManager',
]
