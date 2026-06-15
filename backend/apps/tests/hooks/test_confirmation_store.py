"""
Tests for ConfirmationStore — singleton for async tool-execution confirmations.

Covers:
- ConfirmationEntry dataclass defaults
- Singleton pattern (get_instance)
- Core CRUD: create / wait / respond / cancel
- Timeout auto-reject
- Expired-entry cleanup
- Concurrent access safety
"""
import asyncio
import time
from unittest.mock import patch

import pytest

from apps.agent.hooks.confirmation_store import ConfirmationEntry, ConfirmationStore


# ====================================================================
# ConfirmationEntry
# ====================================================================

class TestConfirmationEntry:
    """ConfirmationEntry dataclass field defaults."""

    def test_fields_defaults(self):
        entry = ConfirmationEntry(tool_name="send_email", arguments='{"to": "a@b.com"}')
        assert entry.tool_name == "send_email"
        assert entry.arguments == '{"to": "a@b.com"}'
        assert entry.approved is None
        # event is auto-created
        assert isinstance(entry.event, asyncio.Event)
        assert not entry.event.is_set()
        # created_at is roughly now
        assert 0 < time.time() - entry.created_at < 5

    def test_fields_custom(self):
        event = asyncio.Event()
        event.set()
        entry = ConfirmationEntry(
            tool_name="delete_user",
            arguments='{"user_id": "u1"}',
            approved=True,
            event=event,
            created_at=100.0,
        )
        assert entry.tool_name == "delete_user"
        assert entry.approved is True
        assert entry.event.is_set()
        assert entry.created_at == 100.0


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def store():
    """Return a fresh ConfirmationStore with class-level singleton reset."""
    ConfirmationStore._instance = None
    return ConfirmationStore()


# ====================================================================
# Singleton
# ====================================================================

class TestConfirmationStoreSingleton:
    """ConfirmationStore singleton pattern."""

    def teardown_method(self):
        ConfirmationStore._instance = None

    def test_get_instance_returns_same(self):
        s1 = ConfirmationStore.get_instance()
        s2 = ConfirmationStore.get_instance()
        assert s1 is s2

    def test_get_instance_creates_if_none(self):
        ConfirmationStore._instance = None
        store = ConfirmationStore.get_instance()
        assert isinstance(store, ConfirmationStore)

    def test_multiple_instances_not_singleton(self):
        """Direct construction creates different instances."""
        ConfirmationStore._instance = None
        s1 = ConfirmationStore()
        s2 = ConfirmationStore()
        assert s1 is not s2

    def test_get_confirmation_store_helper(self):
        """The module-level helper returns the singleton."""
        ConfirmationStore._instance = None
        from apps.agent.hooks.confirmation_store import get_confirmation_store
        s1 = get_confirmation_store()
        s2 = get_confirmation_store()
        assert s1 is s2


# ====================================================================
# Create
# ====================================================================

class TestConfirmationStoreCreate:
    """ConfirmationStore.create() — entry creation."""

    @pytest.mark.asyncio
    async def test_create_returns_id(self, store):
        cid = await store.create("send_email", '{"to": "a@b.com"}')
        assert isinstance(cid, str)
        assert cid.startswith("confirm_")
        assert len(cid) > len("confirm_")

    @pytest.mark.asyncio
    async def test_create_unique_ids(self, store):
        cid1 = await store.create("tool_a", "{}")
        cid2 = await store.create("tool_b", "{}")
        assert cid1 != cid2

    @pytest.mark.asyncio
    async def test_create_stores_entry(self, store):
        cid = await store.create("send_email", '{"to": "a@b.com"}')
        entry = await store._get_entry(cid)
        assert entry is not None
        assert entry.tool_name == "send_email"

    @pytest.mark.asyncio
    async def test_create_entry_event_not_set(self, store):
        cid = await store.create("tool", "{}")
        entry = await store._get_entry(cid)
        assert not entry.event.is_set()

    @pytest.mark.asyncio
    async def test_create_increases_pending_count(self, store):
        assert await store.get_pending_count() == 0
        await store.create("t1", "{}")
        assert await store.get_pending_count() == 1
        await store.create("t2", "{}")
        assert await store.get_pending_count() == 2


# ====================================================================
# Respond
# ====================================================================

class TestConfirmationStoreRespond:
    """ConfirmationStore.respond() — signaling a client response."""

    @pytest.mark.asyncio
    async def test_respond_approved_sets_flag(self, store):
        cid = await store.create("tool", "{}")
        result = await store.respond(cid, approved=True)
        assert result is True
        entry = await store._get_entry(cid)
        assert entry.approved is True
        assert entry.event.is_set()

    @pytest.mark.asyncio
    async def test_respond_rejected_sets_flag(self, store):
        cid = await store.create("tool", "{}")
        result = await store.respond(cid, approved=False)
        assert result is True
        entry = await store._get_entry(cid)
        assert entry.approved is False
        assert entry.event.is_set()

    @pytest.mark.asyncio
    async def test_respond_first_only(self, store):
        """Only the first respond() should be accepted."""
        cid = await store.create("tool", "{}")
        assert await store.respond(cid, approved=True) is True
        assert await store.respond(cid, approved=False) is False
        # First response should stick
        entry = await store._get_entry(cid)
        assert entry.approved is True

    @pytest.mark.asyncio
    async def test_respond_nonexistent(self, store):
        """Responding to non-existent ID returns False."""
        result = await store.respond("confirm_noexist", approved=True)
        assert result is False


# ====================================================================
# Wait
# ====================================================================

class TestConfirmationStoreWait:
    """ConfirmationStore.wait() — blocking wait for client response."""

    @pytest.mark.asyncio
    async def test_wait_returns_true_after_approve(self, store):
        cid = await store.create("tool", "{}")
        # Start waiter and responder concurrently
        async def respond_delayed():
            await asyncio.sleep(0.02)
            await store.respond(cid, approved=True)

        _, result = await asyncio.gather(
            respond_delayed(),
            store.wait(cid, timeout=5),
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_after_reject(self, store):
        cid = await store.create("tool", "{}")

        async def respond_delayed():
            await asyncio.sleep(0.02)
            await store.respond(cid, approved=False)

        _, result = await asyncio.gather(
            respond_delayed(),
            store.wait(cid, timeout=5),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_timeout_returns_false(self, store):
        cid = await store.create("tool", "{}")
        result = await store.wait(cid, timeout=0.05)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_nonexistent_id_returns_false(self, store):
        result = await store.wait("confirm_noexist", timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_cancelled_before_timeout(self, store):
        cid = await store.create("tool", "{}")

        async def cancel_delayed():
            await asyncio.sleep(0.02)
            await store.cancel(cid)

        _, result = await asyncio.gather(
            cancel_delayed(),
            store.wait(cid, timeout=5),
        )
        # Cancel sets event but doesn't set approved, so returns False
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_immediate_response(self, store):
        """respond() before wait() should return instantly."""
        cid = await store.create("tool", "{}")
        await store.respond(cid, approved=True)
        result = await store.wait(cid, timeout=5)
        assert result is True


# ====================================================================
# Cancel
# ====================================================================

class TestConfirmationStoreCancel:
    """ConfirmationStore.cancel() — removing a pending confirmation."""

    @pytest.mark.asyncio
    async def test_cancel_removes_entry(self, store):
        cid = await store.create("tool", "{}")
        assert await store.get_pending_count() == 1

        result = await store.cancel(cid)
        assert result is True
        assert await store.get_pending_count() == 0
        assert await store._get_entry(cid) is None

    @pytest.mark.asyncio
    async def test_cancel_signals_event(self, store):
        cid = await store.create("tool", "{}")
        await store.cancel(cid)
        entry = await store._get_entry(cid)
        # After cancel, entry is gone even if event reference exists
        assert entry is None

    @pytest.mark.asyncio
    async def test_cancel_wakes_waiters(self, store):
        """cancel() should cause wait() to return False."""
        cid = await store.create("tool", "{}")

        async def cancel_delayed():
            await asyncio.sleep(0.02)
            await store.cancel(cid)

        _, result = await asyncio.gather(
            cancel_delayed(),
            store.wait(cid, timeout=5),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, store):
        result = await store.cancel("confirm_noexist")
        assert result is False


# ====================================================================
# Cleanup Expired
# ====================================================================

class TestConfirmationStoreCleanup:
    """ConfirmationStore.cleanup_expired() — removing old entries."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_stale(self, store):
        cid = await store.create("tool", "{}")
        # Manually set created_at far in the past
        entry = await store._get_entry(cid)
        entry.created_at = 0  # epoch = very old

        removed = await store.cleanup_expired(max_age_seconds=1)
        assert removed == 1
        assert await store._get_entry(cid) is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_fresh(self, store):
        cid = await store.create("tool", "{}")
        removed = await store.cleanup_expired(max_age_seconds=120)
        assert removed == 0
        assert await store._get_entry(cid) is not None

    @pytest.mark.asyncio
    async def test_cleanup_partial(self, store):
        """Only stale entries are removed; fresh entries remain."""
        fresh_cid = await store.create("fresh_tool", "{}")
        stale_cid = await store.create("stale_tool", "{}")

        entry = await store._get_entry(stale_cid)
        entry.created_at = 0

        removed = await store.cleanup_expired(max_age_seconds=1)
        assert removed == 1
        assert await store._get_entry(stale_cid) is None
        assert await store._get_entry(fresh_cid) is not None

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_when_empty(self, store):
        removed = await store.cleanup_expired()
        assert removed == 0

    @pytest.mark.asyncio
    async def test_cleanup_signals_event(self, store):
        """Stale entries should have their event set before removal."""
        cid = await store.create("tool", "{}")
        entry = await store._get_entry(cid)
        entry.created_at = 0

        # Make a waiter that will get woken up by cleanup
        async def wait_for_stale():
            return await store.wait(cid, timeout=5)

        # Start waiter, let it enter the event loop, then cleanup
        async def cleanup_after_delay():
            await asyncio.sleep(0.02)
            await store.cleanup_expired(max_age_seconds=1)

        waiter_result, _ = await asyncio.gather(
            wait_for_stale(),
            cleanup_after_delay(),
        )
        assert waiter_result is False  # Cancelled → False


# ====================================================================
# Pending Count
# ====================================================================

class TestConfirmationStorePendingCount:
    """ConfirmationStore.get_pending_count()."""

    @pytest.mark.asyncio
    async def test_zero_initially(self, store):
        assert await store.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_after_creates(self, store):
        await store.create("t1", "{}")
        await store.create("t2", "{}")
        assert await store.get_pending_count() == 2

    @pytest.mark.asyncio
    async def test_after_cancel(self, store):
        cid = await store.create("t1", "{}")
        await store.create("t2", "{}")
        await store.cancel(cid)
        assert await store.get_pending_count() == 1

    @pytest.mark.asyncio
    async def test_after_cleanup(self, store):
        cid = await store.create("t1", "{}")
        entry = await store._get_entry(cid)
        entry.created_at = 0
        await store.cleanup_expired(max_age_seconds=1)
        assert await store.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_respond_does_not_change_count(self, store):
        cid = await store.create("t1", "{}")
        await store.respond(cid, approved=True)
        # Respond doesn't remove entry
        assert await store.get_pending_count() == 1


# ====================================================================
# Concurrent access
# ====================================================================

class TestConfirmationStoreConcurrency:
    """Thread/async safety of ConfirmationStore."""

    @pytest.mark.asyncio
    async def test_concurrent_creates(self, store):
        """Multiple concurrent creates should not interfere."""
        async def create_tool(i: int):
            return await store.create(f"tool_{i}", f'{{"i": {i}}}')

        ids = await asyncio.gather(*[create_tool(i) for i in range(10)])
        assert len(set(ids)) == 10
        assert await store.get_pending_count() == 10

    @pytest.mark.asyncio
    async def test_concurrent_responds(self, store):
        """Multiple concurrent responds should be safe (first wins)."""
        cid = await store.create("tool", "{}")

        async def respond_with(v: bool):
            return await store.respond(cid, approved=v)

        results = await asyncio.gather(*[respond_with(v) for v in [True, False, True]])
        # Exactly one should return True (first response accepted)
        assert sum(results) == 1

    @pytest.mark.asyncio
    async def test_concurrent_waiters(self, store):
        """Multiple concurrent waiters should all be woken by one respond."""
        cid = await store.create("tool", "{}")

        async def delayed_respond():
            await asyncio.sleep(0.05)
            await store.respond(cid, approved=True)

        waiters = [store.wait(cid, timeout=5) for _ in range(5)]
        results = await asyncio.gather(delayed_respond(), *waiters)
        # All waiters should get True
        assert all(results[1:])  # results[0] is the respond return value


# ====================================================================
# Edge cases
# ====================================================================

class TestConfirmationStoreEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_respond_before_wait_returns_immediately(self, store):
        """If respond happens before wait, wait should return instantly."""
        cid = await store.create("tool", "{}")
        await store.respond(cid, approved=True)
        # This should return near-instantly, not wait for timeout
        start = time.time()
        result = await store.wait(cid, timeout=30)
        elapsed = time.time() - start
        assert result is True
        assert elapsed < 1  # Should be far less than 30s

    @pytest.mark.asyncio
    async def test_wait_after_respond_approved(self, store):
        cid = await store.create("tool", "{}")
        await store.respond(cid, approved=True)
        result = await store.wait(cid, timeout=0.1)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_after_respond_rejected(self, store):
        cid = await store.create("tool", "{}")
        await store.respond(cid, approved=False)
        result = await store.wait(cid, timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_entries_isolated(self, store):
        """Multiple entries should not interfere with each other."""
        cid_a = await store.create("tool_a", '{"x": 1}')
        cid_b = await store.create("tool_b", '{"y": 2}')

        await store.respond(cid_a, approved=True)
        await store.respond(cid_b, approved=False)

        result_a = await store.wait(cid_a, timeout=1)
        result_b = await store.wait(cid_b, timeout=1)

        assert result_a is True
        assert result_b is False

    @pytest.mark.asyncio
    async def test_cancel_twice_idempotent(self, store):
        cid = await store.create("tool", "{}")
        assert await store.cancel(cid) is True
        # Second cancel returns False (entry already gone)
        assert await store.cancel(cid) is False

    @pytest.mark.asyncio
    async def test_cleanup_empty_store(self, store):
        assert await store.cleanup_expired() == 0

    @pytest.mark.asyncio
    async def test_custom_timeout_short(self, store):
        """A very short timeout should not cause errors."""
        cid = await store.create("tool", "{}")
        result = await store.wait(cid, timeout=0.01)
        assert result is False
