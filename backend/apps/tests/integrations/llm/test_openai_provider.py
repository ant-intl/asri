"""
Tests for OpenAIProvider implementation.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

from apps.integrations.llm.openai_provider import OpenAIProvider
from .conftest import (
    MockAsyncClient,
    create_mock_response,
    collect_stream,
    real_mode_only,
    mock_mode_only,
)


class TestOpenAIProviderInitialization:
    """Test OpenAIProvider initialization."""

    def test_default_values(self):
        """Test default initialization values."""
        provider = OpenAIProvider()
        assert provider.api_base == 'https://api.openai.com/v1'
        assert provider.api_key == ''
        assert provider.model_name == 'gpt-4'
        assert provider.timeout == 60

    def test_custom_values(self):
        """Test custom initialization values."""
        provider = OpenAIProvider(
            api_base='https://custom.openai.com/v1',
            api_key='sk-custom-key',
            model_name='gpt-3.5-turbo',
            timeout=60
        )
        assert provider.api_base == 'https://custom.openai.com/v1'
        assert provider.api_key == 'sk-custom-key'
        assert provider.model_name == 'gpt-3.5-turbo'
        assert provider.timeout == 60

    def test_get_provider_type(self, openai_provider):
        """Test get_provider_type returns 'openai'."""
        assert openai_provider.get_provider_type() == 'openai'

    def test_get_model_name(self, openai_provider):
        """Test get_model_name returns correct model."""
        assert openai_provider.get_model_name() == 'gpt-4'


@mock_mode_only
class TestOpenAIProviderChatMock:
    """Test OpenAIProvider.chat() with mocked HTTP requests."""

    @pytest.mark.asyncio
    async def test_chat_non_stream_success(self, openai_provider, sample_messages, openai_chat_response):
        """Test successful non-streaming chat response."""
        mock_client = MockAsyncClient(response_data=openai_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await openai_provider.chat(sample_messages, stream=False)

        assert result['content'] == 'Hello! How can I help you today?'
        assert result['model'] == 'gpt-4'
        assert result['finish_reason'] == 'stop'
        assert result['usage']['prompt_tokens'] == 10
        assert result['usage']['completion_tokens'] == 8
        assert result['usage']['total_tokens'] == 18

    @pytest.mark.asyncio
    async def test_chat_request_payload(self, openai_provider, sample_messages, openai_chat_response):
        """Test that chat request payload is correctly formatted."""
        mock_client = MockAsyncClient(response_data=openai_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await openai_provider.chat(sample_messages, temperature=0.5, stream=False)

        assert len(mock_client.post_calls) == 1
        call = mock_client.post_calls[0]
        assert call['url'] == 'https://api.openai.com/v1/chat/completions'
        payload = call['kwargs']['json']
        assert payload['model'] == 'gpt-4'
        assert payload['messages'] == sample_messages
        assert payload['temperature'] == 0.5
        assert payload['stream'] is False
        assert 'max_tokens' not in payload

    @pytest.mark.asyncio
    async def test_chat_with_max_tokens(self, openai_provider, sample_messages, openai_chat_response):
        """Test chat with max_tokens parameter."""
        mock_client = MockAsyncClient(response_data=openai_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await openai_provider.chat(sample_messages, max_tokens=100, stream=False)

        payload = mock_client.post_calls[0]['kwargs']['json']
        assert payload['max_tokens'] == 100

    @pytest.mark.asyncio
    async def test_chat_authorization_header(self, sample_messages, openai_chat_response):
        """Test that Authorization header contains Bearer token."""
        provider = OpenAIProvider(api_key='sk-test-key-123')
        mock_client = MockAsyncClient(response_data=openai_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await provider.chat(sample_messages, stream=False)

        headers = mock_client.post_calls[0]['kwargs']['headers']
        assert headers['Authorization'] == 'Bearer sk-test-key-123'
        assert headers['Content-Type'] == 'application/json'

    @pytest.mark.asyncio
    async def test_chat_http_error_raises(self, openai_provider, sample_messages):
        """Test that HTTP errors are propagated."""
        error_response = MagicMock()
        error_response.status_code = 401
        error = httpx.HTTPStatusError(
            message='Unauthorized',
            request=MagicMock(),
            response=error_response
        )
        mock_client = MockAsyncClient(raise_exception=error)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await openai_provider.chat(sample_messages, stream=False)

    @pytest.mark.asyncio
    async def test_chat_timeout_raises(self, openai_provider, sample_messages):
        """Test that timeout errors are propagated."""
        mock_client = MockAsyncClient(raise_exception=httpx.TimeoutException('Request timed out'))

        with patch('httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(httpx.TimeoutException):
                await openai_provider.chat(sample_messages, stream=False)


@mock_mode_only
class TestOpenAIProviderStreamChatMock:
    """Test OpenAIProvider streaming chat with mocked HTTP requests."""

    @pytest.mark.asyncio
    async def test_stream_returns_async_generator(self, openai_provider, sample_messages, openai_stream_lines):
        """Test that stream=True returns an async generator."""
        mock_client = MockAsyncClient(stream_lines=openai_stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await openai_provider.chat(sample_messages, stream=True)

        # Check it's an async generator
        assert hasattr(result, '__anext__')

    @pytest.mark.asyncio
    async def test_stream_yields_content_chunks(self, openai_provider, sample_messages, openai_stream_lines):
        """Test that streaming yields structured dict chunks correctly."""
        mock_client = MockAsyncClient(stream_lines=openai_stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await openai_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 3
        assert content_chunks[0]['content'] == 'Hello'
        assert content_chunks[1]['content'] == '!'
        assert content_chunks[2]['content'] == ' How'
        # Should end with a done chunk
        assert chunks[-1] == {'type': 'done', 'content': ''}

    @pytest.mark.asyncio
    async def test_stream_handles_done_sentinel(self, openai_provider, sample_messages):
        """Test that [DONE] sentinel stops the stream."""
        stream_lines = [
            'data: {"choices":[{"delta":{"content":"Test"}}]}',
            'data: [DONE]',
            'data: {"choices":[{"delta":{"content":"Should not appear"}}]}'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await openai_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 1
        assert content_chunks[0]['content'] == 'Test'

    @pytest.mark.asyncio
    async def test_stream_skips_empty_content(self, openai_provider, sample_messages):
        """Test that empty content chunks are not yielded."""
        stream_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":""}}]}',
            'data: {"choices":[{"delta":{}}]}',
            'data: {"choices":[{"delta":{"content":"World"}}]}',
            'data: [DONE]'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await openai_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 2
        assert content_chunks[0]['content'] == 'Hello'
        assert content_chunks[1]['content'] == 'World'

    @pytest.mark.asyncio
    async def test_stream_handles_malformed_json(self, openai_provider, sample_messages):
        """Test that malformed JSON lines are skipped with warning."""
        stream_lines = [
            'data: {"choices":[{"delta":{"content":"Before"}}]}',
            'data: {invalid json}',
            'data: {"choices":[{"delta":{"content":"After"}}]}',
            'data: [DONE]'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await openai_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        # Should continue after malformed JSON
        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 2
        assert content_chunks[0]['content'] == 'Before'
        assert content_chunks[1]['content'] == 'After'

    @pytest.mark.asyncio
    async def test_stream_skips_non_data_lines(self, openai_provider, sample_messages):
        """Test that lines not starting with 'data: ' are skipped."""
        stream_lines = [
            'event: message',
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            ': comment',
            '',
            'data: [DONE]'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await openai_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 1
        assert content_chunks[0]['content'] == 'Hello'


@mock_mode_only
class TestOpenAIProviderEmbedMock:
    """Test OpenAIProvider.embed() with mocked HTTP requests."""

    @pytest.mark.asyncio
    async def test_embed_success(self, openai_provider, openai_embed_response):
        """Test successful embedding generation."""
        mock_client = MockAsyncClient(response_data=openai_embed_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await openai_provider.embed('Hello, world!')

        assert isinstance(result, list)
        assert len(result) == 500
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_embed_request_payload(self, openai_provider, openai_embed_response):
        """Test that embed request payload is correctly formatted."""
        mock_client = MockAsyncClient(response_data=openai_embed_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await openai_provider.embed('Test text')

        assert len(mock_client.post_calls) == 1
        call = mock_client.post_calls[0]
        assert call['url'] == 'https://api.openai.com/v1/embeddings'
        payload = call['kwargs']['json']
        assert payload['model'] == 'text-embedding-3-small'
        assert payload['input'] == 'Test text'

    @pytest.mark.asyncio
    async def test_embed_authorization_header(self, openai_embed_response):
        """Test that embed request has correct authorization header."""
        provider = OpenAIProvider(api_key='sk-embed-key')
        mock_client = MockAsyncClient(response_data=openai_embed_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await provider.embed('Test')

        headers = mock_client.post_calls[0]['kwargs']['headers']
        assert headers['Authorization'] == 'Bearer sk-embed-key'

    @pytest.mark.asyncio
    async def test_embed_http_error_raises(self, openai_provider):
        """Test that HTTP errors are propagated for embed."""
        error = httpx.HTTPStatusError(
            message='Rate limit exceeded',
            request=MagicMock(),
            response=MagicMock(status_code=429)
        )
        mock_client = MockAsyncClient(raise_exception=error)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await openai_provider.embed('Test')


@real_mode_only
class TestOpenAIProviderReal:
    """Test OpenAIProvider with real API calls.

    These tests require:
    - LLM_TEST_MODE=real
    - OPENAI_API_KEY set
    - OPENAI_API_BASE (optional, defaults to OpenAI)
    """

    @pytest.mark.asyncio
    async def test_real_chat(self, openai_provider):
        """Test real chat API call."""
        messages = [{'role': 'user', 'content': 'Say hello in one word.'}]
        result = await openai_provider.chat(messages, max_tokens=10, stream=False)

        assert 'content' in result
        assert len(result['content']) > 0
        assert 'usage' in result
        assert 'model' in result

    @pytest.mark.asyncio
    async def test_real_stream_chat(self, openai_provider):
        """Test real streaming chat API call."""
        messages = [{'role': 'user', 'content': 'Say hello in one word.'}]
        generator = await openai_provider.chat(messages, max_tokens=10, stream=True)
        chunks = await collect_stream(generator)

        assert len(chunks) > 0
        content_chunks = [c for c in chunks if c.get('type') == 'content']
        full_response = ''.join(c['content'] for c in content_chunks)
        assert len(full_response) > 0

    @pytest.mark.asyncio
    async def test_real_embed(self, openai_provider):
        """Test real embedding API call."""
        result = await openai_provider.embed('Hello, world!')

        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(x, float) for x in result)
