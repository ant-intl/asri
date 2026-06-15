"""
WebSocket routing configuration for Chatbot.
"""
from django.urls import re_path

from .api.websocket.chat_consumer import ChatConsumer

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<session_id>[^/]+)/$', ChatConsumer.as_asgi()),
]
