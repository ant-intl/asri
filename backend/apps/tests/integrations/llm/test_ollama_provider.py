"""
Tests for OllamaProvider implementation.
"""
import pytest
from unittest.mock import patch, MagicMock
import httpx

from apps.integrations.llm.ollama_provider import OllamaProvider
from .conftest import (
    MockAsyncClient,
    collect_stream,
    real_mode_only,
    mock_mode_only,
)


class TestOllamaProviderInitialization:
    """Test OllamaProvider initialization."""

    def test_default_values(self):
        """Test default initialization values."""
        provider = OllamaProvider()
        assert provider.api_base == 'http://localhost:11434'
        assert provider.api_key == ''
        assert provider.model_name == 'llama2'
        assert provider.timeout == 60

    def test_custom_values(self):
        """Test custom initialization values."""
        provider = OllamaProvider(
            api_base='http://192.168.1.100:11434',
            model_name='mistral',
            timeout=120
        )
        assert provider.api_base == 'http://192.168.1.100:11434'
        assert provider.model_name == 'mistral'
        assert provider.timeout == 120

    def test_get_provider_type(self, ollama_provider):
        """Test get_provider_type returns 'ollama'."""
        assert ollama_provider.get_provider_type() == 'ollama'

    def test_get_model_name(self, ollama_provider):
        """Test get_model_name returns correct model."""
        assert ollama_provider.get_model_name() == 'llama2'


@mock_mode_only
class TestOllamaProviderChatMock:
    """Test OllamaProvider.chat() with mocked HTTP requests."""

    @pytest.mark.asyncio
    async def test_chat_non_stream_success(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test successful non-streaming chat response."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await ollama_provider.chat(sample_messages, stream=False)

        assert result['content'] == 'Hello! How can I assist you today?'
        assert result['model'] == 'llama2'
        assert result['finish_reason'] == 'stop'

    @pytest.mark.asyncio
    async def test_chat_usage_calculation(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test that usage tokens are calculated correctly."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await ollama_provider.chat(sample_messages, stream=False)

        assert result['usage']['prompt_tokens'] == 15
        assert result['usage']['completion_tokens'] == 10
        assert result['usage']['total_tokens'] == 25

    @pytest.mark.asyncio
    async def test_chat_finish_reason_done_true(self, ollama_provider, sample_messages):
        """Test finish_reason is 'stop' when done is true."""
        response = {
            'model': 'llama2',
            'message': {'role': 'assistant', 'content': 'Done'},
            'done': True,
            'prompt_eval_count': 10,
            'eval_count': 5
        }
        mock_client = MockAsyncClient(response_data=response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await ollama_provider.chat(sample_messages, stream=False)

        assert result['finish_reason'] == 'stop'

    @pytest.mark.asyncio
    async def test_chat_finish_reason_done_false(self, ollama_provider, sample_messages):
        """Test finish_reason is 'length' when done is false."""
        response = {
            'model': 'llama2',
            'message': {'role': 'assistant', 'content': 'Incomplete'},
            'done': False,
            'prompt_eval_count': 10,
            'eval_count': 5
        }
        mock_client = MockAsyncClient(response_data=response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await ollama_provider.chat(sample_messages, stream=False)

        assert result['finish_reason'] == 'length'

    @pytest.mark.asyncio
    async def test_chat_endpoint(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test that chat uses /api/chat endpoint."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.chat(sample_messages, stream=False)

        call = mock_client.post_calls[0]
        assert call['url'] == 'http://localhost:11434/api/chat'

    @pytest.mark.asyncio
    async def test_chat_no_auth_header(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test that Ollama does not send Authorization header."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.chat(sample_messages, stream=False)

        call = mock_client.post_calls[0]
        assert 'headers' not in call['kwargs']

    @pytest.mark.asyncio
    async def test_chat_request_payload(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test chat request payload structure."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.chat(sample_messages, temperature=0.5, stream=False)

        payload = mock_client.post_calls[0]['kwargs']['json']
        assert payload['model'] == 'llama2'
        assert payload['messages'] == sample_messages
        assert payload['stream'] is False
        assert payload['options']['temperature'] == 0.5

    @pytest.mark.asyncio
    async def test_chat_with_max_tokens(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test that max_tokens maps to num_predict in options."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.chat(sample_messages, max_tokens=200, stream=False)

        payload = mock_client.post_calls[0]['kwargs']['json']
        assert payload['options']['num_predict'] == 200

    @pytest.mark.asyncio
    async def test_chat_without_max_tokens(self, ollama_provider, sample_messages, ollama_chat_response):
        """Test that num_predict is not included when max_tokens is None."""
        mock_client = MockAsyncClient(response_data=ollama_chat_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.chat(sample_messages, stream=False)

        payload = mock_client.post_calls[0]['kwargs']['json']
        assert 'num_predict' not in payload['options']

    @pytest.mark.asyncio
    async def test_chat_http_error_raises(self, ollama_provider, sample_messages):
        """Test that HTTP errors are propagated."""
        error = httpx.HTTPStatusError(
            message='Server Error',
            request=MagicMock(),
            response=MagicMock(status_code=500)
        )
        mock_client = MockAsyncClient(raise_exception=error)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await ollama_provider.chat(sample_messages, stream=False)


@mock_mode_only
class TestOllamaProviderStreamChatMock:
    """Test OllamaProvider streaming chat with mocked HTTP requests."""

    @pytest.mark.asyncio
    async def test_stream_returns_async_generator(self, ollama_provider, sample_messages, ollama_stream_lines):
        """Test that stream=True returns an async generator."""
        mock_client = MockAsyncClient(stream_lines=ollama_stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await ollama_provider.chat(sample_messages, stream=True)

        assert hasattr(result, '__anext__')

    @pytest.mark.asyncio
    async def test_stream_yields_message_content(self, ollama_provider, sample_messages, ollama_stream_lines):
        """Test streaming yields structured dict chunks from Ollama format."""
        mock_client = MockAsyncClient(stream_lines=ollama_stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await ollama_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        # Based on ollama_stream_lines fixture
        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 4
        assert content_chunks[0]['content'] == 'Hello'
        assert content_chunks[1]['content'] == '!'
        assert content_chunks[2]['content'] == ' How'
        assert content_chunks[3]['content'] == ' can'
        # Should end with a done chunk
        assert chunks[-1] == {'type': 'done', 'content': ''}

    @pytest.mark.asyncio
    async def test_stream_stops_on_done(self, ollama_provider, sample_messages):
        """Test that stream stops when done=true."""
        stream_lines = [
            '{"model":"llama2","message":{"role":"assistant","content":"Test"},"done":false}',
            '{"model":"llama2","message":{"role":"assistant","content":""},"done":true}',
            '{"model":"llama2","message":{"role":"assistant","content":"Should not appear"},"done":false}'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await ollama_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 1
        assert content_chunks[0]['content'] == 'Test'

    @pytest.mark.asyncio
    async def test_stream_skips_empty_content(self, ollama_provider, sample_messages):
        """Test that empty content is not yielded."""
        stream_lines = [
            '{"model":"llama2","message":{"role":"assistant","content":"Hello"},"done":false}',
            '{"model":"llama2","message":{"role":"assistant","content":""},"done":false}',
            '{"model":"llama2","message":{"role":"assistant","content":"World"},"done":false}',
            '{"model":"llama2","message":{"role":"assistant","content":""},"done":true}'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await ollama_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 2
        assert content_chunks[0]['content'] == 'Hello'
        assert content_chunks[1]['content'] == 'World'

    @pytest.mark.asyncio
    async def test_stream_handles_malformed_json(self, ollama_provider, sample_messages):
        """Test that malformed JSON is skipped."""
        stream_lines = [
            '{"model":"llama2","message":{"role":"assistant","content":"Before"},"done":false}',
            '{invalid json}',
            '{"model":"llama2","message":{"role":"assistant","content":"After"},"done":false}',
            '{"model":"llama2","message":{"role":"assistant","content":""},"done":true}'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await ollama_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 2
        assert content_chunks[0]['content'] == 'Before'
        assert content_chunks[1]['content'] == 'After'

    @pytest.mark.asyncio
    async def test_stream_skips_empty_lines(self, ollama_provider, sample_messages):
        """Test that empty lines are skipped."""
        stream_lines = [
            '{"model":"llama2","message":{"role":"assistant","content":"Hello"},"done":false}',
            '',
            '{"model":"llama2","message":{"role":"assistant","content":""},"done":true}'
        ]
        mock_client = MockAsyncClient(stream_lines=stream_lines)

        with patch('httpx.AsyncClient', return_value=mock_client):
            generator = await ollama_provider.chat(sample_messages, stream=True)
            chunks = await collect_stream(generator)

        content_chunks = [c for c in chunks if c.get('type') == 'content']
        assert len(content_chunks) == 1
        assert content_chunks[0]['content'] == 'Hello'


@mock_mode_only
class TestOllamaProviderEmbedMock:
    """Test OllamaProvider.embed() with mocked HTTP requests."""

    @pytest.mark.asyncio
    async def test_embed_success(self, ollama_provider, ollama_embed_response):
        """Test successful embedding generation."""
        mock_client = MockAsyncClient(response_data=ollama_embed_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await ollama_provider.embed('Hello, world!')

        assert isinstance(result, list)
        assert len(result) == 500
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_embed_endpoint(self, ollama_provider, ollama_embed_response):
        """Test that embed uses /api/embeddings endpoint."""
        mock_client = MockAsyncClient(response_data=ollama_embed_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.embed('Test')

        call = mock_client.post_calls[0]
        assert call['url'] == 'http://localhost:11434/api/embeddings'

    @pytest.mark.asyncio
    async def test_embed_request_payload(self, ollama_provider, ollama_embed_response):
        """Test embed request payload uses 'prompt' key (not 'input')."""
        mock_client = MockAsyncClient(response_data=ollama_embed_response)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await ollama_provider.embed('Test text')

        payload = mock_client.post_calls[0]['kwargs']['json']
        assert payload['model'] == 'llama2'
        assert payload['prompt'] == 'Test text'
        assert 'input' not in payload

    @pytest.mark.asyncio
    async def test_embed_http_error_raises(self, ollama_provider):
        """Test that HTTP errors are propagated for embed."""
        error = httpx.HTTPStatusError(
            message='Model not found',
            request=MagicMock(),
            response=MagicMock(status_code=404)
        )
        mock_client = MockAsyncClient(raise_exception=error)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await ollama_provider.embed('Test')


@real_mode_only
class TestOllamaProviderReal:
    """Test OllamaProvider with real API calls.

    These tests require:
    - LLM_TEST_MODE=real
    - OLLAMA_API_BASE set (defaults to localhost:11434)
    - Ollama server running with a model available
    """

    @pytest.mark.asyncio
    async def test_real_chat(self, ollama_provider):
        """Test real chat API call."""
        messages = [{'role': 'user', 'content': 'Say hello in one word.'}]
        result = await ollama_provider.chat(messages, max_tokens=10, stream=False)

        assert 'content' in result
        assert len(result['content']) > 0
        assert 'usage' in result
        assert 'model' in result

    @pytest.mark.asyncio
    async def test_real_stream_chat(self, ollama_provider):
        """Test real streaming chat API call."""
        messages = [{'role': 'user', 'content': 'Say hello in one word.'}]
        generator = await ollama_provider.chat(messages, max_tokens=10, stream=True)
        chunks = await collect_stream(generator)

        assert len(chunks) > 0
        content_chunks = [c for c in chunks if c.get('type') == 'content']
        full_response = ''.join(c['content'] for c in content_chunks)
        assert len(full_response) > 0

    @pytest.mark.asyncio
    async def test_real_embed(self, ollama_provider):
        """Test real embedding API call."""
        result = await ollama_provider.embed('Hello, world!')

        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(x, float) for x in result)
