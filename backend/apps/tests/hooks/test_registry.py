"""
Tests for HookRegistry — DB-backed hook loading with tenant-scoped caching.
"""
import pytest
from asgiref.sync import sync_to_async

from apps.agent.hooks.base import BaseHook, HookResult
from apps.agent.hooks.registry import HookRegistry
from apps.agent.hooks.tool_rule_deny_hook import ToolRuleDenyHook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyHook(BaseHook):
    """A minimal hook for testing registry registration/loading."""
    hook_name = "dummy"

    async def on_tool_pre_execute(self, tool_name, arguments, context):
        return HookResult.deny(f"DummyHook blocked {tool_name}")


# ---------------------------------------------------------------------------
# State cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_hook_registry():
    """Reset HookRegistry class state before and after each test.

    HookRegistry uses class-level dicts (_hook_classes, _instances),
    so we must clean them between tests to avoid state leakage.
    """
    old_classes = HookRegistry._hook_classes.copy()
    old_instances = HookRegistry._instances.copy()
    HookRegistry._hook_classes.clear()
    HookRegistry._instances.clear()
    yield
    HookRegistry._hook_classes.clear()
    HookRegistry._instances.clear()


# ---------------------------------------------------------------------------
# Non-DB tests
# ---------------------------------------------------------------------------


class TestHookRegistryRegistration:
    """HookRegistry class registration (no DB needed)."""

    def test_register_hook_class(self):
        HookRegistry.register_hook_class("dummy", DummyHook)
        assert HookRegistry._hook_classes["dummy"] is DummyHook

    def test_register_multiple_classes(self):
        HookRegistry.register_hook_class("dummy", DummyHook)
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        assert len(HookRegistry._hook_classes) == 2
        assert HookRegistry._hook_classes["tool_rule_deny"] is ToolRuleDenyHook

    def test_register_overwrites_existing(self):
        HookRegistry.register_hook_class("dummy", DummyHook)

        class AnotherDummy(BaseHook):
            hook_name = "another"

        HookRegistry.register_hook_class("dummy", AnotherDummy)
        assert HookRegistry._hook_classes["dummy"] is AnotherDummy


class TestHookRegistryCache:
    """HookRegistry cache management (no DB needed)."""

    def test_invalidate_cache_nonexistent(self):
        """Invalidate a tenant that has no cache — should not raise."""
        HookRegistry.invalidate_cache("ghost-tenant")  # no-op

    def test_invalidate_cache_removes_entries(self):
        HookRegistry._instances["tenant-1"] = {"hook1": DummyHook()}
        assert "tenant-1" in HookRegistry._instances
        HookRegistry.invalidate_cache("tenant-1")
        assert "tenant-1" not in HookRegistry._instances

    def test_invalidate_cache_only_removes_target(self):
        HookRegistry._instances["tenant-1"] = {"h1": DummyHook()}
        HookRegistry._instances["tenant-2"] = {"h2": DummyHook()}
        HookRegistry.invalidate_cache("tenant-1")
        assert "tenant-1" not in HookRegistry._instances
        assert "tenant-2" in HookRegistry._instances

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_hooks_for_tenant_unknown(self):
        """No DB rows for this tenant -> returns empty list."""
        # Register a hook class so it doesn't cause warnings
        HookRegistry.register_hook_class("dummy", DummyHook)
        hooks = await HookRegistry.get_hooks_for_tenant("nonexistent")
        assert hooks == []


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestHookRegistryWithDB:
    """HookRegistry DB loading (requires test database).

    Uses transaction=True to ensure each test's DB changes are rolled back.
    """

    @pytest.fixture(autouse=True)
    def _clean_hook_config_db(self):
        """Remove all HookConfig rows before each DB test."""
        from apps.entities.hook_config import HookConfig
        HookConfig.objects.all().delete()
        yield

    async def _create_hook_config(self, **kwargs):
        """Create a HookConfig row asynchronously."""
        from apps.entities.hook_config import HookConfig

        defaults = {
            "tenant_id": "example",
            "hook_type": "tool_rule_deny",
            "hook_name": "test-hook",
            "is_active": True,
            "config_json": {},
        }
        defaults.update(kwargs)

        @sync_to_async
        def _create():
            return HookConfig.objects.create(**defaults)

        return await _create()

    @pytest.mark.asyncio
    async def test_get_hooks_for_tenant_with_configs(self):
        """Active config rows → hooks returned."""
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        await self._create_hook_config(
            tenant_id="t1",
            hook_type="tool_rule_deny",
            hook_name="deny-hook",
        )
        hooks = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(hooks) == 1
        assert isinstance(hooks[0], ToolRuleDenyHook)

    @pytest.mark.asyncio
    async def test_only_active_hooks_loaded(self):
        """Inactive config rows should be skipped."""
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        await self._create_hook_config(
            tenant_id="t1",
            hook_type="tool_rule_deny",
            hook_name="active-hook",
            is_active=True,
        )
        await self._create_hook_config(
            tenant_id="t1",
            hook_type="tool_rule_deny",
            hook_name="inactive-hook",
            is_active=False,
        )
        hooks = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(hooks) == 1
        assert hooks[0].hook_name == "tool_rule_deny"

    @pytest.mark.asyncio
    async def test_unknown_hook_type_skipped(self):
        """Config with unregistered hook_type should be skipped with warning."""
        # Don't register any class for "unknown_type"
        await self._create_hook_config(
            tenant_id="t1",
            hook_type="unknown_type",
            hook_name="unknown-hook",
        )
        hooks = await HookRegistry.get_hooks_for_tenant("t1")
        assert hooks == []

    @pytest.mark.asyncio
    async def test_multiple_tenants_isolation(self):
        """Each tenant gets only its own hooks."""
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        await self._create_hook_config(tenant_id="t1", hook_name="hook-t1")
        await self._create_hook_config(tenant_id="t2", hook_name="hook-t2")

        t1_hooks = await HookRegistry.get_hooks_for_tenant("t1")
        t2_hooks = await HookRegistry.get_hooks_for_tenant("t2")
        assert len(t1_hooks) == 1
        assert len(t2_hooks) == 1

    @pytest.mark.asyncio
    async def test_cache_used_on_second_call(self):
        """Second call for same tenant returns cached instances."""
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        await self._create_hook_config(tenant_id="t1")

        # First call — loads from DB
        first = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(first) == 1

        # Second call — should use cache
        second = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(second) == 1
        # The cached instance should be the same object
        assert second[0] is first[0]

    @pytest.mark.asyncio
    async def test_cache_invalidated_then_reloaded(self):
        """After invalidate_cache, next call reloads from DB."""
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        await self._create_hook_config(tenant_id="t1", hook_name="hook-v1")

        first = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(first) == 1

        # Invalidate cache and create a new config
        HookRegistry.invalidate_cache("t1")
        await self._create_hook_config(tenant_id="t1", hook_name="hook-v2")

        # Should reload and see both hooks
        second = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(second) == 2

    @pytest.mark.asyncio
    async def test_config_json_passed_to_hook(self):
        """config_json content should be passed to hook constructor."""
        HookRegistry.register_hook_class("tool_rule_deny", ToolRuleDenyHook)
        custom_config = {"rules": [{"name": "custom", "tool_name": "test_tool"}]}
        await self._create_hook_config(
            tenant_id="t1",
            config_json=custom_config,
        )
        hooks = await HookRegistry.get_hooks_for_tenant("t1")
        assert len(hooks) == 1
        # Rule has tool_name "test_tool" but no conditions — should ALLOW
        result = await hooks[0].on_tool_pre_execute(
            "test_tool", '{"x": "y"}', None,
        )
        assert result.action.value == "allow"
