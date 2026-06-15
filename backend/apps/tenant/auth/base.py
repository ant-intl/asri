"""
Base class for admin authentication providers.

Extend this class to implement custom authentication logic for admin
API routes, such as validating tokens via an internal authentication API.
"""
from abc import ABC, abstractmethod

from django.http import HttpRequest


class BaseAdminAuthProvider(ABC):
    """Abstract base class for admin authentication providers.

    Subclasses must implement :meth:`authenticate` to return a ``tenant_id``
    string or ``None`` (which causes the middleware to return a 401 response).

    Example usage::

        class InternalApiAdminAuthProvider(BaseAdminAuthProvider):
            def authenticate(self, request):
                token = request.META.get("HTTP_X_ADMIN_TOKEN")
                if not token:
                    return None
                # Call internal auth API …
                return tenant_id
    """

    @abstractmethod
    def authenticate(self, request: HttpRequest) -> str | None:
        """Resolve the tenant ID from the current request.

        Args:
            request: The incoming HTTP request.

        Returns:
            A ``tenant_id`` string on success, or ``None`` to reject the
            request with a 401 response.
        """
        ...
