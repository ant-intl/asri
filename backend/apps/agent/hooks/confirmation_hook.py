"""
ToolConfirmationHook — requires user approval before executing sensitive tools.

Configuration is read from ``HookConfig.config_json``:
    {
        "tools": ["send_email", "delete_user"],
        "timeout": 30,
        "deny_message": "操作已被安全策略拒绝"
    }

The hook pauses tool execution, notifies the communication layer,
and waits for client approval via ConfirmationStore.
"""
import logging
import time
from typing import Any, Callable, TYPE_CHECKING

from .base import BaseHook, HookResult
from .confirmation_store import ConfirmationStore

if TYPE_CHECKING:
    from ...agent.agent.context import AgentContext

logger = logging.getLogger(__name__)


class ToolConfirmationHook(BaseHook):
    """Tool execution confirmation hook.

    Reads the tool list from ``config_json``.  Only tools listed in
    ``tools`` will trigger a confirmation dialog.  The confirmation
    timeout and deny message are also configurable.
    """

    hook_name = "tool_confirmation"

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._tools_to_confirm: set[str] = set(
            self._config.get("tools", [])
        )
        self._timeout: int = self._config.get("timeout", 30)
        self._deny_message: str = self._config.get(
            "deny_message", "工具执行被拒绝: 用户未确认或超时"
        )
        self._store: ConfirmationStore | None = None
        self._notify_callback: Callable | None = None

    # ── runtime dependency injection ──────────────────────────────

    def set_runtime_deps(
        self,
        store: ConfirmationStore,
        notify_cb: Callable,
    ) -> None:
        """Inject runtime dependencies (called by ChatService).

        Args:
            store: The global ConfirmationStore singleton.
            notify_cb: Async callable(confirmation_id, tool_name, arguments, context)
                       that notifies the communication layer (WebSocket/SSE).
        """
        self._store = store
        self._notify_callback = notify_cb

    # ── hook implementation ───────────────────────────────────────

    async def on_tool_pre_execute(
        self,
        tool_name: str,
        arguments: str,
        context: "AgentContext",
    ) -> HookResult:
        """Intercept tool execution for tools in the confirmation list."""
        if tool_name not in self._tools_to_confirm:
            return HookResult.allow()

        if self._store is None:
            logger.warning(
                "ToolConfirmationHook has no store — allowing %s", tool_name
            )
            return HookResult.allow()

        # Create confirmation entry
        confirmation_id = await self._store.create(tool_name, arguments)
        logger.info(
            "Awaiting confirmation for tool '%s' id=%s (timeout=%ds)",
            tool_name, confirmation_id, self._timeout,
        )

        # Notify communication layer
        if self._notify_callback:
            try:
                await self._notify_callback(
                    confirmation_id, tool_name, arguments, context
                )
            except Exception:
                logger.exception(
                    "Notify callback failed for confirmation %s", confirmation_id
                )

        # Wait for client response (timeout → auto-reject)
        approved = await self._store.wait(confirmation_id, self._timeout)

        if approved:
            logger.info("Tool '%s' confirmed by user", tool_name)
            return HookResult.allow()
        else:
            logger.info("Tool '%s' denied (timeout or user rejection)", tool_name)
            return HookResult.deny(self._deny_message)
