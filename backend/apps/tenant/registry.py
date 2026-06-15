"""
In-memory tenant registry with periodic reload from database.

Provides fast token-to-tenant lookups backed by a cache that is
refreshed from the ``chatbot_tenant`` table every 60 seconds.
"""
import asyncio
import concurrent.futures
import hashlib
import logging
import threading
import time
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

RELOAD_INTERVAL = 15  # seconds (reduced from 60 for multi-instance consistency)


class TenantRegistry:
    """Singleton registry that caches tenant data in memory.

    Call :meth:`get_tenant_id_by_token` to resolve a raw Bearer token
    to its ``tenant_id``.  The cache is lazily refreshed when the
    last reload was more than :data:`RELOAD_INTERVAL` seconds ago.
    """

    def __init__(self):
        self._token_to_tenant: dict[str, str] = {}   # token_hash -> tenant_id
        self._tenant_configs: dict[str, dict] = {}    # tenant_id -> config_json
        self._last_reload: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tenant_id_by_token(self, raw_token: str) -> Optional[str]:
        """Resolve a raw token string to its tenant_id.

        Returns ``None`` if the token is unknown or the tenant is inactive.
        Triggers a reload when the cache is stale.
        """
        self._reload_if_needed()
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return self._token_to_tenant.get(token_hash)

    def get_config(self, tenant_id: Optional[str] = None) -> dict:
        """Return merged config for *tenant_id*.

        Priority logic:
        1. Environment variables (highest priority - ops deployment settings)
        2. Tenant config_json non-empty values (user customizations)
        3. settings.CHATBOT defaults (lowest priority)

        Empty strings in tenant config_json do NOT override non-empty env vars.
        """
        self._reload_if_needed()
        base = getattr(settings, 'CHATBOT', {}).copy()
        if not tenant_id:
            return base

        overrides = self._tenant_configs.get(tenant_id, {})

        # Only override with non-empty tenant config values
        # Empty strings should fall back to env vars / base config
        for key, value in overrides.items():
            if value is not None and value != '':
                base[key] = value

        return base

    def get_model_config(self, tenant_id: Optional[str] = None) -> dict:
        """Get model configuration from tenant config.

        Returns the 'model' section from config_json, or empty dict if not set.
        """
        config = self.get_config(tenant_id)
        return config.get('model', {})

    def list_tenant_ids(self) -> list[str]:
        """List all active tenant IDs.

        Returns:
            List of tenant IDs (excluding None for global).
        """
        self._reload_if_needed()
        return list(self._tenant_configs.keys())

    def force_reload(self) -> None:
        """Force an immediate synchronous reload from the database."""
        with self._lock:
            try:
                self._load_from_db()
                self._last_reload = time.time()
            except Exception:
                logger.exception('Failed to reload tenant registry from DB')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reload_if_needed(self) -> None:
        """Reload from DB if the cache is older than RELOAD_INTERVAL.

        When the cache is empty (no tenants loaded), a force-reload is
        triggered regardless of ``_last_reload``.  This handles the case
        where the registry was first loaded from an empty database during
        app startup and tenants are created shortly after (e.g. in tests).
        """
        now = time.time()
        elapsed = now - self._last_reload
        if elapsed < RELOAD_INTERVAL and self._token_to_tenant:
            return
        if elapsed < RELOAD_INTERVAL and not self._token_to_tenant:
            # Cache is empty — force reload to pick up late-added data
            self.force_reload()
            return
        self._do_reload()

    def _do_reload(self) -> None:
        """Perform the actual reload under a lock."""
        with self._lock:
            # Double-check after acquiring lock
            now = time.time()
            if now - self._last_reload < RELOAD_INTERVAL:
                return
            try:
                self._load_from_db()
                self._last_reload = time.time()
                # Trigger tool reload after successful config refresh
                self._trigger_tool_reload()
            except Exception:
                logger.exception('Failed to reload tenant registry from DB')

    def _trigger_tool_reload(self) -> None:
        """Trigger tool reload after config refresh.

        This is called automatically after TenantRegistry refreshes from DB.
        Dispatches to a worker thread when running inside an async event
        loop (ASGI) so that ``asyncio.run()`` in the worker does not
        conflict with the already-running loop.
        """
        if _in_async_context():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(self._do_tool_reload).result(timeout=30)
        else:
            self._do_tool_reload()

    def _do_tool_reload(self) -> None:
        """Execute tool reload in a clean event loop (must run in a sync thread)."""
        try:
            from ..integrations.tool.reload_manager import get_tool_reload_manager

            reload_manager = get_tool_reload_manager()

            async def _reload_all():
                # Check each tenant for config changes
                for tenant_id in list(self._tenant_configs.keys()):
                    config = self._tenant_configs.get(tenant_id, {})
                    await reload_manager.reload_if_needed(tenant_id, config)
                # Also check global config
                global_config = getattr(settings, 'CHATBOT', {})
                await reload_manager.reload_if_needed(None, global_config)
                # Also trigger periodic MCP refresh
                await reload_manager.reload_mcp_if_needed()

            asyncio.run(_reload_all())
        except Exception as e:
            logger.warning(f"Failed to trigger tool reload: {e}")

    def _load_from_db(self) -> None:
        """Read all active tenants from the database.

        Detects whether we are inside an async event loop.  If so the
        synchronous ORM query is dispatched to a worker thread so that
        Django does not raise ``SynchronousOnlyOperation``.
        """
        if _in_async_context():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(self._do_load_from_db).result(timeout=10)
        else:
            self._do_load_from_db()

    def _do_load_from_db(self) -> None:
        """Execute the actual ORM query (must run in a sync thread)."""
        from ..entities import Tenant  # lazy import to avoid AppRegistryNotReady

        tenants = Tenant.objects.filter(is_active=True).values(
            'tenant_id', 'token_hash', 'config_json',
        )

        new_token_map: dict[str, str] = {}
        new_config_map: dict[str, dict] = {}

        for t in tenants:
            new_token_map[t['token_hash']] = t['tenant_id']
            new_config_map[t['tenant_id']] = t['config_json'] or {}

        self._token_to_tenant = new_token_map
        self._tenant_configs = new_config_map

        logger.debug('Tenant registry reloaded: %d tenants', len(new_token_map))


def _in_async_context() -> bool:
    """Return True if there is a running asyncio event loop."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[TenantRegistry] = None


def get_tenant_registry() -> TenantRegistry:
    """Get or create the singleton TenantRegistry instance."""
    global _registry
    if _registry is None:
        _registry = TenantRegistry()
    return _registry
