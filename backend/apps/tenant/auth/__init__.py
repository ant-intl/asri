"""
Admin authentication provider abstraction.

Provides a pluggable authentication provider for admin API routes,
with ``DefaultAdminAuthProvider`` as the default implementation that
returns the ``'example'`` tenant for all requests.

To integrate an internal authentication API in the future, create a new
provider class inheriting from :class:`BaseAdminAuthProvider` and register
it via :meth:`AdminAuthRegistry.set_provider`.
"""
from .base import BaseAdminAuthProvider
from .default import DefaultAdminAuthProvider
from .registry import AdminAuthRegistry

__all__ = [
    "BaseAdminAuthProvider",
    "DefaultAdminAuthProvider",
    "AdminAuthRegistry",
]
