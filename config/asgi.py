"""
ASGI config for ASRI project.

It exposes the ASGI callable as a module-level variable named ``application``.
Supports both HTTP and WebSocket protocols.
"""
import os
import sys

# Add project root and backend to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'backend'))

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

from .env import env_settings
from .middleware import SSEStreamingMiddleware

# Initialize settings based on environment
env_settings()

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

# Wrap with SSE streaming middleware to store 'send' in request scope
django_asgi_app = SSEStreamingMiddleware(django_asgi_app)

# Import WebSocket routing after Django setup
from apps.routing import websocket_urlpatterns  # noqa: E402

application= ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
