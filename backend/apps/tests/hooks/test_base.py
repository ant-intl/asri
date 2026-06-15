"""
Tests for base hook infrastructure: HookResult, BaseHook, HookManager.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.agent.hooks.base import HookAction, HookResult, BaseHook, HookManager


# ====================================================================
# HookResult
# ====================================================================


class TestHookResult:
    """HookResult dataclass and convenience constructors."""

    def test_default_fields(self):
        result = HookResult()
        assert result.action == HookAction.ALLOW
        assert result.reason == ""
        assert result.modified_data is None
        assert result.injected_context is None

    def test_allow(self):
        result = HookResult.allow()
        assert result.action == HookAction.ALLOW
        assert result.reason == ""

    def test_deny(self):
        result = HookResult.deny("access denied")
        assert result.action == HookAction.DENY
        assert result.reason == "access denied"

    def test_modify(self):
        data = {"key": "new_value"}
        result = HookResult.modify(data)
        assert result.action == HookAction.MODIFY
        assert result.modified_data is data

    def test_inject_context(self):
        ctx = {"user": "admin"}
        result = HookResult.inject_context(ctx)
        assert result.action == HookAction.INJECT_CONTEXT
        assert result.injected_context is ctx

    def test_stop(self):
        result = HookResult.stop("stopped by policy")
        assert result.action == HookAction.STOP
        assert result.reason == "stopped by policy"

    def test_stop_default_reason(self):
        result = HookResult.stop()
        assert result.action == HookAction.STOP
        assert result.reason == ""


# ====================================================================
# BaseHook
# ====================================================================


class TestBaseHook:
    """BaseHook default implementations (all should return ALLOW)."""

    @pytest.fixture
    def hook(self):
        class MinimalHook(BaseHook):
            hook_name = "minimal"

        return MinimalHook()

    @pytest.mark.asyncio
    async def test_on_tool_pre_execute_default(self, hook, mock_agent_context):
        result = await hook.on_tool_pre_execute("tool", "{}", mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_on_tool_post_execute_default(self, hook, mock_agent_context):
        result = await hook.on_tool_post_execute("tool", "ok", mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_on_tool_execute_failure_default(self, hook, mock_agent_context):
        result = await hook.on_tool_execute_failure("tool", "error", mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_on_user_message_default(self, hook, mock_agent_context):
        result = await hook.on_user_message("hello", [], mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_on_agent_stop_default(self, hook, mock_agent_context):
        result = await hook.on_agent_stop("ok", [], mock_agent_context)
        assert result.action == HookAction.ALLOW


# ====================================================================
# HookManager
# ====================================================================


def _make_mock_hook(name: str, return_value: HookResult | None = None) -> MagicMock:
    """Create a MagicMock that looks like a BaseHook."""
    mock = MagicMock(spec=BaseHook)
    mock.hook_name = name

    # Set default return values for all async methods
    for method_name in [
        "on_tool_pre_execute",
        "on_tool_post_execute",
        "on_tool_execute_failure",
        "on_user_message",
        "on_agent_stop",
    ]:
        setattr(mock, method_name, AsyncMock(return_value=HookResult.allow()))

    if return_value is not None:
        mock.on_tool_pre_execute = AsyncMock(return_value=return_value)

    return mock


class TestHookManagerRegistration:
    """HookManager register / unregister / properties."""

    def test_register(self):
        manager = HookManager()
        hook = _make_mock_hook("test")
        manager.register(hook)
        assert len(manager.hooks) == 1
        assert manager.hooks[0] is hook

    def test_unregister(self):
        manager = HookManager()
        manager.register(_make_mock_hook("h1"))
        manager.register(_make_mock_hook("h2"))
        assert manager.unregister("h1") is True
        assert [h.hook_name for h in manager.hooks] == ["h2"]

    def test_unregister_nonexistent(self):
        manager = HookManager()
        assert manager.unregister("ghost") is False

    def test_is_empty_on_creation(self):
        assert HookManager().is_empty is True

    def test_is_empty_after_register(self):
        manager = HookManager()
        manager.register(_make_mock_hook("h"))
        assert manager.is_empty is False

    def test_is_empty_after_unregister_all(self):
        manager = HookManager()
        manager.register(_make_mock_hook("h"))
        manager.unregister("h")
        assert manager.is_empty is True

    def test_hooks_returns_copy(self):
        manager = HookManager()
        hook = _make_mock_hook("h")
        manager.register(hook)
        retrieved = manager.hooks
        retrieved.clear()
        # Original list should be unaffected
        assert len(manager.hooks) == 1


class TestHookManagerToolPre:
    """HookManager.execute_tool_pre_hooks."""

    @pytest.mark.asyncio
    async def test_no_hooks(self, empty_hook_manager, mock_agent_context):
        action, data, ctx = await empty_hook_manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.ALLOW
        assert data == "{}"
        assert ctx is None

    @pytest.mark.asyncio
    async def test_hook_returns_deny(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("denier", return_value=HookResult.deny("nope"))
        manager.register(hook)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.DENY
        assert data == "nope"
        assert ctx is None

    @pytest.mark.asyncio
    async def test_hook_returns_stop(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("stopper", return_value=HookResult.stop("stop now"))
        manager.register(hook)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.STOP
        assert data == "stop now"
        assert ctx is None

    @pytest.mark.asyncio
    async def test_hook_returns_modify(self, mock_agent_context):
        manager = HookManager()
        modified_args = '{"key": "modified"}'
        hook = _make_mock_hook("modifier", return_value=HookResult.modify(modified_args))
        manager.register(hook)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.ALLOW
        assert data == modified_args
        assert ctx is None

    @pytest.mark.asyncio
    async def test_hook_returns_inject_context(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook(
            "injector",
            return_value=HookResult.inject_context({"role": "admin"}),
        )
        manager.register(hook)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.ALLOW
        assert data == "{}"
        assert ctx == {"role": "admin"}

    @pytest.mark.asyncio
    async def test_multiple_inject_context_merged(self, mock_agent_context):
        manager = HookManager()
        h1 = _make_mock_hook(
            "inj1",
            return_value=HookResult.inject_context({"k1": "v1"}),
        )
        h2 = _make_mock_hook(
            "inj2",
            return_value=HookResult.inject_context({"k2": "v2"}),
        )
        manager.register(h1)
        manager.register(h2)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.ALLOW
        assert ctx == {"k1": "v1", "k2": "v2"}

    @pytest.mark.asyncio
    async def test_short_circuit_on_deny(self, mock_agent_context):
        """First DENY should prevent subsequent hooks from running."""
        manager = HookManager()
        h1 = _make_mock_hook("denier", return_value=HookResult.deny("blocked"))
        h2 = _make_mock_hook("should_not_run")
        manager.register(h1)
        manager.register(h2)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.DENY
        # h2.on_tool_pre_execute should NOT have been called
        h2.on_tool_pre_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_treated_as_allow(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("broken")
        hook.on_tool_pre_execute = AsyncMock(side_effect=ValueError("boom"))
        manager.register(hook)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_deny_after_allow_chain(self, mock_agent_context):
        """ALLOW → DENY chain: second hook should stop the chain."""
        manager = HookManager()
        h1 = _make_mock_hook("allower")
        h2 = _make_mock_hook("denier", return_value=HookResult.deny("blocked"))
        manager.register(h1)
        manager.register(h2)

        action, data, ctx = await manager.execute_tool_pre_hooks(
            "tool", "{}", mock_agent_context,
        )
        assert action == HookAction.DENY


class TestHookManagerToolPost:
    """HookManager.execute_tool_post_hooks."""

    @pytest.mark.asyncio
    async def test_no_hooks(self, empty_hook_manager, mock_agent_context):
        result = await empty_hook_manager.execute_tool_post_hooks(
            "tool", "result", mock_agent_context,
        )
        assert result.action == HookAction.ALLOW
        assert result.modified_data == "result"

    @pytest.mark.asyncio
    async def test_modify(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("modifier")
        hook.on_tool_post_execute = AsyncMock(
            return_value=HookResult.modify("modified"),
        )
        manager.register(hook)

        result = await manager.execute_tool_post_hooks("tool", "original", mock_agent_context)
        assert result.modified_data == "modified"

    @pytest.mark.asyncio
    async def test_deny(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("denier")
        hook.on_tool_post_execute = AsyncMock(
            return_value=HookResult.deny("result rejected"),
        )
        manager.register(hook)

        result = await manager.execute_tool_post_hooks("tool", "result", mock_agent_context)
        assert result.action == HookAction.DENY
        assert result.reason == "result rejected"

    @pytest.mark.asyncio
    async def test_inject_context(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("injector")
        hook.on_tool_post_execute = AsyncMock(
            return_value=HookResult.inject_context({"k": "v"}),
        )
        manager.register(hook)

        result = await manager.execute_tool_post_hooks("tool", "result", mock_agent_context)
        assert result.injected_context == {"k": "v"}

    @pytest.mark.asyncio
    async def test_exception_skipped(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("broken")
        hook.on_tool_post_execute = AsyncMock(side_effect=RuntimeError("fail"))
        manager.register(hook)

        # Exception should be caught, test should not raise
        result = await manager.execute_tool_post_hooks("tool", "result", mock_agent_context)
        assert result.action == HookAction.ALLOW


class TestHookManagerToolFailure:
    """HookManager.execute_tool_failure_hooks."""

    @pytest.mark.asyncio
    async def test_no_hooks(self, empty_hook_manager, mock_agent_context):
        result = await empty_hook_manager.execute_tool_failure_hooks(
            "tool", "error", mock_agent_context,
        )
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_inject_context(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("injector")
        hook.on_tool_execute_failure = AsyncMock(
            return_value=HookResult.inject_context({"error_info": "something broke"}),
        )
        manager.register(hook)

        result = await manager.execute_tool_failure_hooks("tool", "err", mock_agent_context)
        assert result.injected_context == {"error_info": "something broke"}

    @pytest.mark.asyncio
    async def test_exception_skipped(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("broken")
        hook.on_tool_execute_failure = AsyncMock(side_effect=Exception("fail"))
        manager.register(hook)

        result = await manager.execute_tool_failure_hooks("tool", "err", mock_agent_context)
        assert result.action == HookAction.ALLOW


class TestHookManagerUserMessage:
    """HookManager.execute_user_message_hooks."""

    @pytest.mark.asyncio
    async def test_no_hooks(self, empty_hook_manager, mock_agent_context):
        result = await empty_hook_manager.execute_user_message_hooks(
            "hello", [], mock_agent_context,
        )
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_deny(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("denier")
        hook.on_user_message = AsyncMock(return_value=HookResult.deny("bad message"))
        manager.register(hook)

        result = await manager.execute_user_message_hooks("hello", [], mock_agent_context)
        assert result.action == HookAction.DENY
        assert result.reason == "bad message"

    @pytest.mark.asyncio
    async def test_stop(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("stopper")
        hook.on_user_message = AsyncMock(return_value=HookResult.stop("stop"))
        manager.register(hook)

        result = await manager.execute_user_message_hooks("hello", [], mock_agent_context)
        assert result.action == HookAction.STOP

    @pytest.mark.asyncio
    async def test_modify(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("modifier")
        hook.on_user_message = AsyncMock(return_value=HookResult.modify("modified message"))
        manager.register(hook)

        result = await manager.execute_user_message_hooks("hello", [], mock_agent_context)
        assert result.action == HookAction.MODIFY
        assert result.modified_data == "modified message"

    @pytest.mark.asyncio
    async def test_inject_context(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("injector")
        hook.on_user_message = AsyncMock(
            return_value=HookResult.inject_context({"key": "val"}),
        )
        manager.register(hook)

        result = await manager.execute_user_message_hooks("hello", [], mock_agent_context)
        assert result.action == HookAction.INJECT_CONTEXT
        assert result.injected_context == {"key": "val"}


class TestHookManagerAgentStop:
    """HookManager.execute_agent_stop_hooks."""

    @pytest.mark.asyncio
    async def test_no_hooks(self, empty_hook_manager, mock_agent_context):
        # Should not raise
        result = await empty_hook_manager.execute_agent_stop_hooks(
            "ok", [], mock_agent_context,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_hook_called(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("stophook")
        manager.register(hook)

        await manager.execute_agent_stop_hooks("response", [{"step": 1}], mock_agent_context)
        hook.on_agent_stop.assert_called_once_with(
            "response", [{"step": 1}], mock_agent_context,
        )

    @pytest.mark.asyncio
    async def test_exception_not_propagated(self, mock_agent_context):
        manager = HookManager()
        hook = _make_mock_hook("broken")
        hook.on_agent_stop = AsyncMock(side_effect=RuntimeError("fail"))
        manager.register(hook)

        # Should not raise despite hook error
        await manager.execute_agent_stop_hooks("ok", [], mock_agent_context)
