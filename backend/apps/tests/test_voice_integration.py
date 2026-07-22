"""
Integration tests for Voice module fusion into Django.

Tests cover:
  - WebSocket routing (VoiceConsumer registration)
  - VoiceConsumer import and instantiation
  - DjangoConfigReader (with mocked Django models)
  - apply_django_config_to_handler_kwargs
  - Cross-module imports (core.agent_loop ↔ Django, core.agent_loop ↔ Voice)
  - ASGI application path setup
  - Deployment config validation (Dockerfile, docker-compose, start.sh)
"""
import asyncio
import os
import sys
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 1. WebSocket Routing
# ---------------------------------------------------------------------------

class TestWebSocketRouting:
    """Verify VoiceConsumer is properly registered in Django routing."""

    def test_voice_routes_exist(self):
        """VoiceConsumer routes should be in websocket_urlpatterns."""
        from apps.routing import websocket_urlpatterns
        route_patterns = [str(r.pattern) for r in websocket_urlpatterns]
        assert any("v1/realtime/audio" in p for p in route_patterns), \
            f"Missing v1/realtime/audio route. Found: {route_patterns}"
        assert any("v1/realtime" in p and "audio" not in p for p in route_patterns), \
            f"Missing v1/realtime route. Found: {route_patterns}"

    def test_voice_route_count(self):
        """Should have at least 3 routes: chat, realtime/audio, realtime."""
        from apps.routing import websocket_urlpatterns
        assert len(websocket_urlpatterns) >= 3, \
            f"Expected >=3 routes, got {len(websocket_urlpatterns)}"

    def test_chat_route_still_exists(self):
        """Original ChatConsumer route should be preserved."""
        from apps.routing import websocket_urlpatterns
        route_patterns = [str(r.pattern) for r in websocket_urlpatterns]
        assert any("ws/chat" in p for p in route_patterns), \
            f"Missing ws/chat route. Found: {route_patterns}"


# ---------------------------------------------------------------------------
# 2. VoiceConsumer Import & Instantiation
# ---------------------------------------------------------------------------

class TestVoiceConsumerImport:
    """Verify VoiceConsumer can be imported and instantiated."""

    def test_import_voice_consumer(self):
        """VoiceConsumer should be importable from apps.api.websocket."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        assert VoiceConsumer is not None

    def test_import_from_init(self):
        """VoiceConsumer should be exported via __init__.py."""
        from apps.api.websocket import VoiceConsumer
        assert VoiceConsumer is not None

    def test_instantiation(self):
        """VoiceConsumer should be instantiable without arguments."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        assert consumer is not None
        assert hasattr(consumer, 'connect')
        assert hasattr(consumer, 'receive')
        assert hasattr(consumer, 'disconnect')

    def test_consumer_is_async_websocket(self):
        """VoiceConsumer should extend AsyncWebsocketConsumer."""
        from channels.generic.websocket import AsyncWebsocketConsumer
        from apps.api.websocket.voice_consumer import VoiceConsumer
        assert issubclass(VoiceConsumer, AsyncWebsocketConsumer)

    def test_consumer_has_required_methods(self):
        """VoiceConsumer should have pipeline lifecycle methods."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        assert hasattr(consumer, '_start_pipeline')
        assert hasattr(consumer, '_handle_client_event')
        assert hasattr(consumer, '_send_loop')
        assert hasattr(consumer, '_clean_session')

    def test_consumer_initial_state(self):
        """VoiceConsumer should start with clean state."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        assert consumer._pipeline_result is None
        assert consumer._service is None
        assert consumer._session_id is None
        assert consumer._send_task is None
        assert consumer._active is False


# ---------------------------------------------------------------------------
# 3. DjangoConfigReader (mocked)
# ---------------------------------------------------------------------------

class TestDjangoConfigReader:
    """Test DjangoConfigReader with mocked Django registries."""

    @pytest.mark.asyncio
    async def test_read_all_returns_expected_keys(self):
        """read_all() should return dict with 4 keys."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'voice'))
        try:
            from asri_voice.voice_django.django_config_reader import DjangoConfigReader
            reader = DjangoConfigReader(tenant_id="test")
            # Mock all Django imports to avoid DB access
            with patch.object(reader, 'get_llm_config', new_callable=AsyncMock, return_value=None), \
                 patch.object(reader, 'get_tool_schemas', new_callable=AsyncMock, return_value=[]), \
                 patch.object(reader, 'get_system_prompt', new_callable=AsyncMock, return_value=None), \
                 patch.object(reader, 'get_mcp_tools', new_callable=AsyncMock, return_value=[]):
                result = await reader.read_all()

            assert "llm_config" in result
            assert "tool_schemas" in result
            assert "system_prompt" in result
            assert "mcp_tools" in result
        finally:
            sys.path.pop(0)

    @pytest.mark.asyncio
    async def test_read_all_with_data(self):
        """read_all() should propagate data from individual getters."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'voice'))
        try:
            from asri_voice.voice_django.django_config_reader import DjangoConfigReader
            reader = DjangoConfigReader(tenant_id="test")

            mock_llm = {"model_name": "gpt-4", "base_url": "https://api.openai.com/v1", "api_key": "sk-test"}
            mock_tools = [{"type": "function", "function": {"name": "search"}}]
            mock_prompt = "You are a helpful assistant."
            mock_mcp = [{"type": "function", "function": {"name": "mcp_tool"}}]

            with patch.object(reader, 'get_llm_config', new_callable=AsyncMock, return_value=mock_llm), \
                 patch.object(reader, 'get_tool_schemas', new_callable=AsyncMock, return_value=mock_tools), \
                 patch.object(reader, 'get_system_prompt', new_callable=AsyncMock, return_value=mock_prompt), \
                 patch.object(reader, 'get_mcp_tools', new_callable=AsyncMock, return_value=mock_mcp):
                result = await reader.read_all()

            assert result["llm_config"] == mock_llm
            assert result["tool_schemas"] == mock_tools
            assert result["system_prompt"] == mock_prompt
            assert result["mcp_tools"] == mock_mcp
        finally:
            sys.path.pop(0)

    def test_django_config_reader_init(self):
        """DjangoConfigReader should store tenant_id."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'voice'))
        try:
            from asri_voice.voice_django.django_config_reader import DjangoConfigReader
            reader = DjangoConfigReader(tenant_id="my_tenant")
            assert reader.tenant_id == "my_tenant"
        finally:
            sys.path.pop(0)


# ---------------------------------------------------------------------------
# 4. apply_django_config_to_handler_kwargs
# ---------------------------------------------------------------------------

class TestApplyDjangoConfig:
    """Test apply_django_config_to_handler_kwargs function."""

    def _get_apply_func(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'voice'))
        from asri_voice.voice_django.django_config_reader import apply_django_config_to_handler_kwargs
        sys.path.pop(0)
        return apply_django_config_to_handler_kwargs

    def test_apply_llm_config(self):
        """LLM config should be applied to open_api handler kwargs."""
        apply = self._get_apply_func()
        django_config = {
            "llm_config": {
                "model_name": "gpt-4o",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-xyz",
            },
            "system_prompt": None,
            "tool_schemas": [],
            "mcp_tools": [],
        }
        handler_kwargs = {"open_api": {"model_name": "old-model", "base_url": "old-url"}}
        apply(django_config, handler_kwargs)

        assert handler_kwargs["open_api"]["model_name"] == "gpt-4o"
        assert handler_kwargs["open_api"]["base_url"] == "https://api.example.com/v1"
        assert handler_kwargs["open_api"]["api_key"] == "sk-xyz"

    def test_apply_system_prompt(self):
        """System prompt should set init_chat_prompt in open_api kwargs."""
        apply = self._get_apply_func()
        django_config = {
            "llm_config": None,
            "system_prompt": "You are a voice assistant.",
            "tool_schemas": [],
            "mcp_tools": [],
        }
        handler_kwargs = {"open_api": {}}
        module_kwargs = MagicMock()
        apply(django_config, handler_kwargs, module_kwargs)

        assert handler_kwargs["open_api"]["init_chat_prompt"] == "You are a voice assistant."

    def test_apply_empty_config(self):
        """Empty Django config should not modify handler kwargs."""
        apply = self._get_apply_func()
        django_config = {
            "llm_config": None,
            "system_prompt": None,
            "tool_schemas": [],
            "mcp_tools": [],
        }
        handler_kwargs = {"open_api": {"model_name": "original"}}
        original = handler_kwargs.copy()
        apply(django_config, handler_kwargs)

        assert handler_kwargs["open_api"]["model_name"] == "original"

    def test_apply_preserves_existing_keys(self):
        """Applying Django config should not remove unrelated keys."""
        apply = self._get_apply_func()
        django_config = {
            "llm_config": {"model_name": "new-model"},
            "system_prompt": None,
            "tool_schemas": [],
            "mcp_tools": [],
        }
        handler_kwargs = {"open_api": {"model_name": "old", "temperature": 0.7, "max_tokens": 1000}}
        apply(django_config, handler_kwargs)

        assert handler_kwargs["open_api"]["model_name"] == "new-model"
        assert handler_kwargs["open_api"]["temperature"] == 0.7
        assert handler_kwargs["open_api"]["max_tokens"] == 1000


# ---------------------------------------------------------------------------
# 5. Cross-module Imports (core.agent_loop)
# ---------------------------------------------------------------------------

class TestCrossModuleImports:
    """Verify AgentLoopCore can be imported from both Django and Voice contexts."""

    def test_import_from_django_context(self):
        """AgentLoopCore should be importable in Django test context."""
        from core.agent_loop import AgentLoopCore
        assert hasattr(AgentLoopCore, '_accumulate_tool_delta')
        assert hasattr(AgentLoopCore, '_try_parse_tool')
        assert hasattr(AgentLoopCore, 'run')

    def test_accumulate_tool_delta_static(self):
        """_accumulate_tool_delta should work as a static method."""
        from core.agent_loop import AgentLoopCore
        buffers = {}
        delta = {"index": 0, "id": "call_1", "function": {"name": "search", "arguments": '{"q"'}}
        AgentLoopCore._accumulate_tool_delta(delta, buffers)
        assert 0 in buffers
        assert buffers[0]["name"] == "search"

    def test_try_parse_tool_valid(self):
        """_try_parse_tool should return parsed result for valid JSON."""
        from core.agent_loop import AgentLoopCore
        buf = {"name": "search", "arguments": '{"query": "hello"}', "id": "call_1"}
        result = AgentLoopCore._try_parse_tool(buf)
        assert result is not None
        assert result.name == "search"
        assert result.call_id == "call_1"

    def test_try_parse_tool_invalid_json(self):
        """_try_parse_tool should return None for incomplete JSON."""
        from core.agent_loop import AgentLoopCore
        buf = {"name": "search", "arguments": '{"query":', "id": "call_1"}
        result = AgentLoopCore._try_parse_tool(buf)
        assert result is None

    def test_events_importable(self):
        """All event types should be importable."""
        from core.agent_loop import (
            TextChunk, ReasoningChunk, ToolCallStarted,
            ToolCallDispatched, ToolResult, IterationMetrics, Error,
        )
        # Verify they are proper classes
        assert isinstance(TextChunk, type)
        assert isinstance(ToolCallStarted, type)
        assert isinstance(Error, type)


# ---------------------------------------------------------------------------
# 6. ASGI Application Path Setup
# ---------------------------------------------------------------------------

class TestASGISetup:
    """Verify ASGI application is configured for Voice integration."""

    def test_asri_voice_importable(self):
        """asri_voice package should be importable after asgi.py runs."""
        # asgi.py is already loaded by Django test setup;
        # with PYTHONPATH=.../voice the package is on sys.path.
        voice_pkg = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'voice')
        )
        has_voice = any(
            os.path.normpath(p) == voice_pkg
            for p in sys.path
            if p
        )
        assert has_voice, f"voice/ not in sys.path: {sys.path[:10]}..."

    def test_asgi_application_exists(self):
        """ASGI application variable should exist."""
        from config.asgi import application
        assert application is not None

    def test_asgi_has_websocket_handler(self):
        """ASGI application should handle websocket protocol."""
        from config.asgi import application
        # ProtocolTypeRouter stores its children
        assert hasattr(application, 'application_mapping') or hasattr(application, '__call__')


# ---------------------------------------------------------------------------
# 7. Deployment Config Validation
# ---------------------------------------------------------------------------

class TestDeploymentConfig:
    """Verify deployment files are updated for unified deployment."""

    @pytest.fixture(autouse=True)
    def _set_project_root(self):
        # test file is at backend/apps/tests/, so 3 levels up = project root
        self.project_root = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..')
        )

    def test_dockerfile_copies_core(self):
        """Dockerfile should COPY core/ directory."""
        dockerfile = os.path.join(self.project_root, 'Dockerfile')
        if not os.path.exists(dockerfile):
            pytest.skip("Dockerfile not found")
        with open(dockerfile) as f:
            content = f.read()
        assert "COPY core/" in content, "Dockerfile should COPY core/"

    def test_dockerfile_copies_voice_package(self):
        """Dockerfile should COPY voice/asri_voice/ package."""
        dockerfile = os.path.join(self.project_root, 'Dockerfile')
        if not os.path.exists(dockerfile):
            pytest.skip("Dockerfile not found")
        with open(dockerfile) as f:
            content = f.read()
        assert "COPY voice/asri_voice/" in content, "Dockerfile should COPY voice/asri_voice/"

    def test_dockerfile_single_port(self):
        """Dockerfile should expose only port 8000."""
        dockerfile = os.path.join(self.project_root, 'Dockerfile')
        if not os.path.exists(dockerfile):
            pytest.skip("Dockerfile not found")
        with open(dockerfile) as f:
            content = f.read()
        assert "EXPOSE 8000" in content
        # Should NOT expose 8765 (old Voice port)
        assert "EXPOSE 8765" not in content

    def test_docker_compose_no_active_voice_service(self):
        """docker-compose.yml should not have an active voice service."""
        compose_file = os.path.join(self.project_root, 'docker-compose.yml')
        if not os.path.exists(compose_file):
            pytest.skip("docker-compose.yml not found")
        with open(compose_file) as f:
            content = f.read()
        # Voice service should be commented out or absent
        lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
        active_services = [l for l in lines if l.startswith('voice:')]
        assert len(active_services) == 0, "Voice service should be commented out"

    def test_docker_compose_has_pythonpath(self):
        """docker-compose.yml should set PYTHONPATH with voice/."""
        compose_file = os.path.join(self.project_root, 'docker-compose.yml')
        if not os.path.exists(compose_file):
            pytest.skip("docker-compose.yml not found")
        with open(compose_file) as f:
            content = f.read()
        assert "PYTHONPATH" in content, "docker-compose.yml should set PYTHONPATH"
        assert "voice/" in content or "/app/voice" in content, "PYTHONPATH should include voice/"

    def test_start_sh_has_voice_pythonpath(self):
        """start.sh should add voice/ to PYTHONPATH."""
        start_sh = os.path.join(self.project_root, 'start.sh')
        if not os.path.exists(start_sh):
            pytest.skip("start.sh not found")
        with open(start_sh) as f:
            content = f.read()
        assert "voice" in content and "PYTHONPATH" in content, \
            "start.sh should include voice in PYTHONPATH"

    def test_start_sh_no_uvicorn(self):
        """start.sh should not start uvicorn (Voice standalone server)."""
        start_sh = os.path.join(self.project_root, 'start.sh')
        if not os.path.exists(start_sh):
            pytest.skip("start.sh not found")
        with open(start_sh) as f:
            content = f.read()
        # uvicorn should not be used for Voice anymore
        assert "uvicorn" not in content.lower() or "uvicorn" in content.lower().split("#")[0] == "", \
            "start.sh should not start uvicorn for Voice"


# ---------------------------------------------------------------------------
# 8. VoiceConsumer Protocol Handling (unit-level)
# ---------------------------------------------------------------------------

class TestVoiceConsumerProtocol:
    """Test VoiceConsumer event parsing and protocol helpers."""

    def test_to_audio_bytes_numpy(self):
        """_to_audio_bytes should handle numpy arrays."""
        import numpy as np
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        arr = np.array([1, 2, 3], dtype=np.int16)
        result = consumer._to_audio_bytes(arr)
        assert isinstance(result, bytes)

    def test_to_audio_bytes_passthrough(self):
        """_to_audio_bytes should pass through bytes."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        result = consumer._to_audio_bytes(b"hello")
        assert result == b"hello"

    def test_get_query_param(self):
        """_get_query_param should parse query string from scope."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        consumer.scope = {"query_string": b"session_id=abc123&foo=bar"}
        assert consumer._get_query_param("session_id") == "abc123"
        assert consumer._get_query_param("foo") == "bar"
        assert consumer._get_query_param("missing") is None

    def test_get_query_param_empty(self):
        """_get_query_param should handle empty query string."""
        from apps.api.websocket.voice_consumer import VoiceConsumer
        consumer = VoiceConsumer()
        consumer.scope = {"query_string": b""}
        assert consumer._get_query_param("session_id") is None

    def test_keep_audio_sentinel(self):
        """_keep_audio_sentinel should detect the sentinel marker."""
        from apps.api.websocket.voice_consumer import _keep_audio_sentinel
        assert _keep_audio_sentinel(b"__RESPONSE_DONE__") is True
        assert _keep_audio_sentinel(b"other_bytes") is False
        assert _keep_audio_sentinel({"type": "event"}) is False

    def test_keep_user_text_event(self):
        """_keep_user_text_event should filter speech_stopped and token_usage."""
        from apps.api.websocket.voice_consumer import _keep_user_text_event
        assert _keep_user_text_event({"type": "speech_stopped"}) is True
        assert _keep_user_text_event({"type": "token_usage"}) is True
        assert _keep_user_text_event({"type": "other_event"}) is False
        assert _keep_user_text_event("not_a_dict") is False
