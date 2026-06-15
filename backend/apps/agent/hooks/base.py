"""
Hook base classes and manager.

Provides the core Hook infrastructure:
- HookResult: 5 control abilities (ALLOW, DENY, MODIFY, INJECT_CONTEXT, STOP)
  aligned with Claude Code's permissionDecision / updatedInput /
  additionalContext / continue:false patterns.
- BaseHook: 5 lifecycle methods matching Claude Code events
  (PreToolUse, PostToolUse, PostToolUseFailure, UserPromptSubmit, Stop).
- HookManager: sequential dispatch with short-circuit semantics.
"""
import logging
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...agent.agent.context import AgentContext

logger = logging.getLogger(__name__)


# ────────────────────────── HookResult ──────────────────────────


class HookAction(Enum):
    """Hook control actions aligned with Claude Code's permission model."""

    ALLOW = "allow"              # permissionDecision: allow → continue
    DENY = "deny"                # permissionDecision: deny → block
    MODIFY = "modify"            # updatedInput → modify args / input
    INJECT_CONTEXT = "inject_context"  # additionalContext → inject into LLM
    STOP = "stop"                # continue: false / block → stop agent loop


@dataclass
class HookResult:
    """Unified result returned by every hook lifecycle method.

    Attributes:
        action: What to do next (default ALLOW).
        reason: Human-readable reason for DENY or STOP.
        modified_data: New data when action is MODIFY.
        injected_context: Additional context dict for INJECT_CONTEXT.
    """

    action: HookAction = HookAction.ALLOW
    reason: str = ""
    modified_data: Any = None
    injected_context: dict[str, Any] | None = None

    # ── convenience constructors ──────────────────────────────────

    @classmethod
    def allow(cls) -> "HookResult":
        return cls(action=HookAction.ALLOW)

    @classmethod
    def deny(cls, reason: str) -> "HookResult":
        return cls(action=HookAction.DENY, reason=reason)

    @classmethod
    def modify(cls, data: Any) -> "HookResult":
        return cls(action=HookAction.MODIFY, modified_data=data)

    @classmethod
    def inject_context(cls, data: dict[str, Any]) -> "HookResult":
        return cls(action=HookAction.INJECT_CONTEXT, injected_context=data)

    @classmethod
    def stop(cls, reason: str = "") -> "HookResult":
        return cls(action=HookAction.STOP, reason=reason)


# ─────────────────────────── BaseHook ───────────────────────────


class BaseHook(ABC):
    """Hook base class with 5 lifecycle methods (matches Claude Code events).

    Subclasses override only the methods they need. Every method
    defaults to ``HookResult.allow()``.
    """

    hook_name: str = ""

    # ── tool lifecycle (PreToolUse / PostToolUse / PostToolUseFailure) ──

    async def on_tool_pre_execute(
        self,
        tool_name: str,
        arguments: str,
        context: "AgentContext",
    ) -> HookResult:
        """Before tool execution. Can return ALLOW / DENY / MODIFY / STOP."""
        return HookResult.allow()

    async def on_tool_post_execute(
        self,
        tool_name: str,
        result: str,
        context: "AgentContext",
    ) -> HookResult:
        """After successful tool execution. Can return ALLOW / MODIFY / INJECT_CONTEXT."""
        return HookResult.allow()

    async def on_tool_execute_failure(
        self,
        tool_name: str,
        error: str,
        context: "AgentContext",
    ) -> HookResult:
        """After failed tool execution. Can return ALLOW / INJECT_CONTEXT."""
        return HookResult.allow()

    # ── user interaction (UserPromptSubmit / Stop) ───────────────

    async def on_user_message(
        self,
        message: str,
        history: list[dict],
        context: "AgentContext",
    ) -> HookResult:
        """After user message arrives, before agent processes it.
        Can return ALLOW / DENY / MODIFY / STOP."""
        return HookResult.allow()

    async def on_agent_stop(
        self,
        response_content: str,
        trace: list[dict],
        context: "AgentContext",
    ) -> HookResult:
        """After agent finishes responding. Can return ALLOW / INJECT_CONTEXT."""
        return HookResult.allow()


# ───────────────────────── HookManager ──────────────────────────


class HookManager:
    """Manages registered hooks and dispatches events sequentially.

    Short-circuit rule:
        For tool_pre / user_message hooks the first non-ALLOW result wins.
        INJECT_CONTEXT results are accumulated across all hooks.
    """

    def __init__(self) -> None:
        self._hooks: list[BaseHook] = []

    # ── registration ─────────────────────────────────────────────

    def register(self, hook: BaseHook) -> None:
        """Register a hook (executed in registration order)."""
        self._hooks.append(hook)
        logger.debug("Registered hook: %s", hook.hook_name or type(hook).__name__)

    def unregister(self, hook_name: str) -> bool:
        """Remove a hook by its ``hook_name``. Returns True if removed."""
        before = len(self._hooks)
        self._hooks = [h for h in self._hooks if h.hook_name != hook_name]
        removed = before > len(self._hooks)
        if removed:
            logger.debug("Unregistered hook: %s", hook_name)
        return removed

    @property
    def hooks(self) -> list[BaseHook]:
        return list(self._hooks)

    @property
    def is_empty(self) -> bool:
        return len(self._hooks) == 0

    # ── dispatch methods (short-circuit) ─────────────────────────

    async def _dispatch_pre(
        self,
        executor,
        *args,
    ) -> tuple[HookAction, str, Any | None]:
        """Shared dispatch for *pre* hooks (tool_pre / user_message).

        Returns (action, reason_or_message, merged_context_or_modified_data).
        """
        current_data = args[0]  # first arg is the mutable datum
        injected_contexts: list[dict[str, Any]] = []

        for hook in self._hooks:
            try:
                result = await executor(hook, *args)
            except Exception:
                logger.exception(
                    "Hook %s raised during dispatch — treating as ALLOW",
                    hook.hook_name or type(hook).__name__,
                )
                continue

            if result.action in (HookAction.DENY, HookAction.STOP):
                return (result.action, result.reason, None)

            if result.action == HookAction.MODIFY:
                if result.modified_data is not None:
                    current_data = result.modified_data
                    args = list(args)
                    args[0] = current_data
                    args = tuple(args)

            if result.action == HookAction.INJECT_CONTEXT:
                if result.injected_context:
                    injected_contexts.append(result.injected_context)

            # ALLOW → continue to next hook

        # Merge accumulated context
        merged_context: dict[str, Any] | None = None
        if injected_contexts:
            merged_context = {}
            for ctx in injected_contexts:
                merged_context.update(ctx)

        return (HookAction.ALLOW, current_data, merged_context)

    async def execute_tool_pre_hooks(
        self,
        tool_name: str,
        arguments: str,
        context: "AgentContext",
    ) -> tuple[HookAction, str, Any | None]:
        """Execute all ``on_tool_pre_execute`` hooks (short-circuit).

        Returns (action, reason_or_modified_args, injected_context).
        """
        if not self._hooks:
            return (HookAction.ALLOW, arguments, None)

        async def _run(hook, *a):
            # _dispatch_pre args order: (arguments, tool_name, context, ...)
            # so args[0] = arguments (mutable datum for MODIFY actions)
            # But hook expects on_tool_pre_execute(tool_name, arguments, context, ...)
            return await hook.on_tool_pre_execute(a[1], a[0], *a[2:])

        action, data, ctx = await self._dispatch_pre(_run, arguments, tool_name, context)
        return (action, data, ctx)

    async def execute_tool_post_hooks(
        self,
        tool_name: str,
        result: str,
        context: "AgentContext",
    ) -> "HookResult":
        """Execute all ``on_tool_post_execute`` hooks (MODIFY updates result)."""
        final_result = result
        injected_contexts: list[dict[str, Any]] = []

        for hook in self._hooks:
            try:
                r = await hook.on_tool_post_execute(tool_name, final_result, context)
            except Exception:
                logger.exception(
                    "Hook %s raised in on_tool_post_execute — skipping",
                    hook.hook_name or type(hook).__name__,
                )
                continue

            if r.action == HookAction.DENY:
                return r
            if r.action == HookAction.MODIFY and r.modified_data is not None:
                final_result = r.modified_data
            if r.action == HookAction.INJECT_CONTEXT and r.injected_context:
                injected_contexts.append(r.injected_context)

        if injected_contexts:
            merged = {}
            for ctx in injected_contexts:
                merged.update(ctx)
            return HookResult(action=HookAction.ALLOW, modified_data=final_result, injected_context=merged)

        return HookResult(action=HookAction.ALLOW, modified_data=final_result)

    async def execute_tool_failure_hooks(
        self,
        tool_name: str,
        error: str,
        context: "AgentContext",
    ) -> "HookResult":
        """Execute all ``on_tool_execute_failure`` hooks."""
        injected_contexts: list[dict[str, Any]] = []

        for hook in self._hooks:
            try:
                r = await hook.on_tool_execute_failure(tool_name, error, context)
            except Exception:
                logger.exception(
                    "Hook %s raised in on_tool_execute_failure — skipping",
                    hook.hook_name or type(hook).__name__,
                )
                continue

            if r.action == HookAction.INJECT_CONTEXT and r.injected_context:
                injected_contexts.append(r.injected_context)

        if injected_contexts:
            merged = {}
            for ctx in injected_contexts:
                merged.update(ctx)
            return HookResult.inject_context(merged)

        return HookResult.allow()

    async def execute_user_message_hooks(
        self,
        message: str,
        history: list[dict],
        context: "AgentContext",
    ) -> "HookResult":
        """Execute all ``on_user_message`` hooks (short-circuit)."""
        if not self._hooks:
            return HookResult.allow()

        async def _run(hook, *a):
            return await hook.on_user_message(*a)

        action, data, ctx = await self._dispatch_pre(_run, message, history, context)

        if action == HookAction.DENY:
            return HookResult.deny(data)
        if action == HookAction.STOP:
            return HookResult.stop(data)
        if data != message:
            if ctx:
                return HookResult(
                    action=HookAction.MODIFY,
                    modified_data=data,
                    injected_context=ctx,
                )
            return HookResult.modify(data)
        if ctx:
            return HookResult.inject_context(ctx)
        return HookResult.allow()

    async def execute_agent_stop_hooks(
        self,
        response_content: str,
        trace: list[dict],
        context: "AgentContext",
    ) -> None:
        """Execute all ``on_agent_stop`` hooks (best-effort, never blocks)."""
        for hook in self._hooks:
            try:
                await hook.on_agent_stop(response_content, trace, context)
            except Exception:
                logger.exception(
                    "Hook %s raised in on_agent_stop — ignoring",
                    hook.hook_name or type(hook).__name__,
                )
