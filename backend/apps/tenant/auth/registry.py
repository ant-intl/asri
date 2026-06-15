"""
Singleton registry for the active admin authentication provider.

Provides a global access point for the middleware to retrieve the
configured provider, and a ``set_provider()`` method for runtime
replacement (e.g. during application startup).
"""
from .base import BaseAdminAuthProvider
from .default import DefaultAdminAuthProvider


class AdminAuthRegistry:
    """Registry holding the active :class:`BaseAdminAuthProvider` instance.

    Usage::

        provider = AdminAuthRegistry.get_provider()
        tenant_id = provider.authenticate(request)
    """

    _provider: BaseAdminAuthProvider | None = None

    @classmethod
    def get_provider(cls) -> BaseAdminAuthProvider:
        """Return the active provider, lazy-initialised to the default."""
        if cls._provider is None:
            cls._provider = DefaultAdminAuthProvider()
        return cls._provider

    @classmethod
    def set_provider(cls, provider: BaseAdminAuthProvider) -> None:
        """Override the active provider at runtime (e.g. at startup)."""
        cls._provider = provider
