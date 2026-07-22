"""
WebSocket routing configuration for Chatbot.
"""
from django.urls import re_path

from .api.websocket.chat_consumer import ChatConsumer
from .api.websocket.voice_consumer import VoiceConsumer

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<session_id>[^/]+)/$', ChatConsumer.as_asgi()),
    re_path(r'v1/realtime/audio$', VoiceConsumer.as_asgi()),
    re_path(r'v1/realtime$', VoiceConsumer.as_asgi()),
]
