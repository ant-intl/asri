"""
Tests using VCR cassette recordings.

These tests use recorded HTTP responses from real API calls, ensuring
mock data format matches actual API responses.

Recording new cassettes:
    LLM_TEST_MODE=record OPENAI_API_KEY=sk-xxx pytest ... -k "vcr"

Playback mode (default):
    pytest ... -k "vcr"
"""
import pytest

from apps.integrations.llm.openai_provider import OpenAIProvider
from apps.integrations.llm.ollama_provider import OllamaProvider

from .vcr_recorder import use_cassette, load_cassette
from .conftest import collect_stream


class TestOpenAIProviderVCR:
    """OpenAI Provider tests using VCR recordings."""

    @pytest.mark.asyncio
    @use_cassette('openai_chat')
    async def test_vcr_chat(self):
        """Test chat using recorded response."""
        provider = OpenAIProvider(api_key='test-key')
        messages = [{'role': 'user', 'content': 'Hello'}]

        result = await provider.chat(messages, stream=False)

        assert 'content' in result
        assert result['content'] == 'Hello! How can I assist you today?'
        assert result['model'] == 'gpt-4'
        assert result['finish_reason'] == 'stop'
        assert 'usage' in result

    @pytest.mark.asyncio
    @use_cassette('openai_chat')
    async def test_vcr_stream_chat(self):
        """Test streaming chat using recorded response."""
        provider = OpenAIProvider(api_key='test-key')
        messages = [{'role': 'user', 'content': 'Hello'}]

        generator = await provider.chat(messages, stream=True)
        chunks = await collect_stream(generator)

        assert len(chunks) > 0
        content_chunks = [c for c in chunks if c.get('type') == 'content']
        full_response = ''.join(c['content'] for c in content_chunks)
        assert 'Hello' in full_response

    @pytest.mark.asyncio
    @use_cassette('openai_embed')
    async def test_vcr_embed(self):
        """Test embedding using recorded response."""
        provider = OpenAIProvider(api_key='test-key')

        result = await provider.embed('Hello, world!')

        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(x, float) for x in result)


class TestOllamaProviderVCR:
    """Ollama Provider tests using VCR recordings."""

    @pytest.mark.asyncio
    @use_cassette('ollama_chat')
    async def test_vcr_chat(self):
        """Test chat using recorded response."""
        provider = OllamaProvider(model_name='llama2')
        messages = [{'role': 'user', 'content': 'Hello'}]

        result = await provider.chat(messages, stream=False)

        assert 'content' in result
        assert result['content'] == 'Hello! How can I assist you today?'
        assert result['model'] == 'llama2'
        assert result['finish_reason'] == 'stop'
        assert 'usage' in result

    @pytest.mark.asyncio
    @use_cassette('ollama_chat')
    async def test_vcr_stream_chat(self):
        """Test streaming chat using recorded response."""
        provider = OllamaProvider(model_name='llama2')
        messages = [{'role': 'user', 'content': 'Hello'}]

        generator = await provider.chat(messages, stream=True)
        chunks = await collect_stream(generator)

        assert len(chunks) > 0
        content_chunks = [c for c in chunks if c.get('type') == 'content']
        full_response = ''.join(c['content'] for c in content_chunks)
        assert 'Hello' in full_response

    @pytest.mark.asyncio
    @use_cassette('ollama_embed')
    async def test_vcr_embed(self):
        """Test embedding using recorded response."""
        provider = OllamaProvider(model_name='llama2')

        result = await provider.embed('Hello, world!')

        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(x, float) for x in result)



class TestCassetteDataValidation:
    """Tests to validate cassette data format matches expectations."""

    def test_openai_cassette_format(self):
        """Validate OpenAI cassette has expected structure."""
        data = load_cassette('openai_chat')
        assert data is not None

        body = data['body']
        assert 'id' in body
        assert 'object' in body
        assert body['object'] == 'chat.completion'
        assert 'choices' in body
        assert len(body['choices']) > 0
        assert 'message' in body['choices'][0]
        assert 'content' in body['choices'][0]['message']
        assert 'usage' in body

    def test_ollama_cassette_format(self):
        """Validate Ollama cassette has expected structure."""
        data = load_cassette('ollama_chat')
        assert data is not None

        body = data['body']
        assert 'model' in body
        assert 'message' in body
        assert 'content' in body['message']
        assert 'done' in body
        assert 'prompt_eval_count' in body
        assert 'eval_count' in body


    def test_stream_cassette_format(self):
        """Validate stream cassettes have expected structure."""
        for name in ['openai_chat_stream', 'ollama_chat_stream']:
            data = load_cassette(name)
            assert data is not None, f"Missing cassette: {name}"
            assert 'stream_lines' in data
            assert isinstance(data['stream_lines'], list)
            assert len(data['stream_lines']) > 0
