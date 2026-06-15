"""
Tests for AsriGatewayProvider.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.llm.asri_gateway_provider import AsriGatewayProvider
from apps.integrations.llm.response_parser import QwenStructureParser, OpenAIStructureParser
from apps.tests.integrations.llm.conftest import (
    create_mock_response,
    create_mock_stream_response,
    MockAsyncClient,
    collect_stream,
    mock_mode_only,
)


class TestAsriGatewayProviderInit:
    """Tests for AsriGatewayProvider initialization."""

    @mock_mode_only
    def test_init_default_values(self):
        """Test initialization with default values."""
        provider = AsriGatewayProvider()
        assert provider.api_base == ''
        assert provider.api_key == ''
        assert provider.model_name == ''
        assert provider.timeout == 60
        assert provider.agent_context == {}

    @mock_mode_only
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        provider = AsriGatewayProvider(
            api_base='https://gateway.asri.com/v1',
            api_key='test-key',
            model_name='gpt-4',
            timeout=120,
            agent_context={'tenant_id': 'test-tenant'}
        )
        assert provider.api_base == 'https://gateway.asri.com/v1'
        assert provider.api_key == 'test-key'
        assert provider.model_name == 'gpt-4'
        assert provider.timeout == 120
        assert provider.agent_context == {'tenant_id': 'test-tenant'}

    @mock_mode_only
    def test_parser_selection_openai(self):
        """Test parser selection for non-QWEN models."""
        provider = AsriGatewayProvider(model_name='gpt-4')
        assert isinstance(provider.structure_parser, OpenAIStructureParser)

    @mock_mode_only
    def test_parser_selection_qwen(self):
        """Test parser selection for QWEN models."""
        provider = AsriGatewayProvider(model_name='QWEN-3-235B')
        assert isinstance(provider.structure_parser, QwenStructureParser)

    @mock_mode_only
    def test_parser_selection_qwen_case_insensitive(self):
        """Test parser selection is case insensitive."""
        provider = AsriGatewayProvider(model_name='qwen-turbo')
        assert isinstance(provider.structure_parser, QwenStructureParser)

    @mock_mode_only
    def test_get_provider_type(self):
        """Test provider type returns correct value."""
        provider = AsriGatewayProvider()
        assert provider.get_provider_type() == 'asri_gateway'


class TestAsriGatewayProviderChatNonStream:
    """Tests for non-streaming chat."""

    @pytest.fixture
    def asri_gateway_chat_response(self):
        """Mock AsriGateway chat response."""
        return {
            'id': 'asri-gateway-123',
            'object': 'chat.completion',
            'model': 'gpt-4',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': 'Hello! How can I help you today?'
                },
                'finish_reason': 'stop'
            }],
            'usage': {
                'prompt_tokens': 10,
                'completion_tokens': 8,
                'total_tokens': 18
            }
        }

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_chat_non_stream_success(
        self, asri_gateway_provider, sample_messages, asri_gateway_chat_response
    ):
        """Test successful non-streaming chat."""
        mock_client = MockAsyncClient(response_data=asri_gateway_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await asri_gateway_provider.chat(sample_messages, stream=False)

        assert result['content'] == 'Hello! How can I help you today?'
        assert result['usage']['prompt_tokens'] == 10
        assert result['model'] == 'gpt-4'

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_chat_request_payload_with_agent_context(
        self, asri_gateway_provider, sample_messages, asri_gateway_chat_response
    ):
        """Test chat request includes agent_context in payload."""
        mock_client = MockAsyncClient(response_data=asri_gateway_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await asri_gateway_provider.chat(sample_messages, stream=False)

        call = mock_client.post_calls[0]
        payload = call['kwargs']['json']

        assert 'agent_context' in payload
        assert payload['agent_context'] == {
            'tenant_id': 'test-tenant',
            'user_id': 'test-user'
        }

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_chat_request_payload_dynamic_agent_context(
        self, asri_gateway_provider, sample_messages, asri_gateway_chat_response
    ):
        """Test chat request uses dynamic agent_context from kwargs."""
        mock_client = MockAsyncClient(response_data=asri_gateway_chat_response)
        dynamic_context = {'session_id': 'dynamic-session'}

        with patch('httpx.AsyncClient', return_value=mock_client):
            await asri_gateway_provider.chat(
                sample_messages,
                stream=False,
                agent_context=dynamic_context
            )

        call = mock_client.post_calls[0]
        payload = call['kwargs']['json']

        # Dynamic context should override default
        assert payload['agent_context'] == {'session_id': 'dynamic-session'}

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_chat_request_format(
        self, asri_gateway_provider, sample_messages, asri_gateway_chat_response
    ):
        """Test chat request has correct format."""
        mock_client = MockAsyncClient(response_data=asri_gateway_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await asri_gateway_provider.chat(
                sample_messages,
                temperature=0.5,
                max_tokens=100,
                stream=False
            )

        call = mock_client.post_calls[0]
        assert call['url'] == 'https://gateway.asri.com/v1/chat/completions'

        payload = call['kwargs']['json']
        assert payload['model'] == 'gpt-4'
        assert payload['temperature'] == 0.5
        assert payload['max_tokens'] == 100
        assert payload['stream'] is False

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_chat_authorization_header(
        self, asri_gateway_provider, sample_messages, asri_gateway_chat_response
    ):
        """Test chat request has correct Authorization header."""
        mock_client = MockAsyncClient(response_data=asri_gateway_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await asri_gateway_provider.chat(sample_messages, stream=False)

        call = mock_client.post_calls[0]
        headers = call['kwargs']['headers']
        assert headers['Authorization'] == 'Bearer test-gateway-key'
        assert headers['Content-Type'] == 'application/json'


class TestAsriGatewayProviderChatStream:
    """Tests for streaming chat."""

    @pytest.fixture
    def asri_gateway_stream_lines(self):
        """Mock AsriGateway streaming response lines."""
        return [
            'data: {"id":"asri-gateway-123","object":"chat.completion.chunk","model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}',
            'data: {"id":"asri-gateway-123","object":"chat.completion.chunk","model":"gpt-4","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}',
            'data: {"id":"asri-gateway-123","object":"chat.completion.chunk","model":"gpt-4","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":null}]}',
            'data: {"id":"asri-gateway-123","object":"chat.completion.chunk","model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]'
        ]

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_stream_chat_success(
        self, asri_gateway_provider, sample_messages, asri_gateway_stream_lines
    ):
        """Test successful streaming chat."""
        mock_client = MockAsyncClient(stream_lines=asri_gateway_stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await asri_gateway_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        contents = [c['content'] for c in chunks if c.get('type') == 'content']
        assert ''.join(contents) == 'Hello!'

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_stream_chat_includes_agent_context(
        self, asri_gateway_provider, sample_messages, asri_gateway_stream_lines
    ):
        """Test stream chat request includes agent_context."""
        mock_client = MockAsyncClient(stream_lines=asri_gateway_stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await asri_gateway_provider.chat(sample_messages, stream=True)
            # Consume the stream to trigger the httpx client call
            await collect_stream(generator)

        call = mock_client.stream_calls[0]
        payload = call['kwargs']['json']

        assert 'agent_context' in payload
        assert payload['agent_context'] == {
            'tenant_id': 'test-tenant',
            'user_id': 'test-user'
        }


class TestAsriGatewayProviderBuildUrl:
    """Tests for URL building."""

    @mock_mode_only
    def test_build_url_without_v1_suffix(self):
        """Test URL building when api_base doesn't end with /v1."""
        provider = AsriGatewayProvider(api_base='https://gateway.asri.com')
        url = provider._build_url()
        assert url == 'https://gateway.asri.com/v1/chat/completions'

    @mock_mode_only
    def test_build_url_with_v1_suffix(self):
        """Test URL building when api_base already ends with /v1."""
        provider = AsriGatewayProvider(api_base='https://gateway.asri.com/v1')
        url = provider._build_url()
        assert url == 'https://gateway.asri.com/v1/chat/completions'

    @mock_mode_only
    def test_build_url_with_trailing_slash(self):
        """Test URL building handles trailing slash."""
        provider = AsriGatewayProvider(api_base='https://gateway.asri.com/')
        url = provider._build_url()
        assert url == 'https://gateway.asri.com/v1/chat/completions'


class TestAsriGatewayProviderEmbed:
    """Tests for embedding."""

    @pytest.mark.asyncio
    @mock_mode_only
    async def test_embed_raises_not_implemented(self, asri_gateway_provider):
        """Test embed method raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            await asri_gateway_provider.embed("test text")
        assert "AsriGateway does not support embeddings" in str(exc_info.value)
