"""
Pytest configuration and fixtures for LLM Provider tests.

Supports two test modes:
- Mock mode (default): HTTP requests are mocked
- Real mode: Actual API calls are made (requires env vars)

Usage:
    # Mock mode (default)
    SERVER_ENV=test pytest apps/tests/integrations/llm/ -v

    # Real mode
    LLM_TEST_MODE=real OPENAI_API_KEY=sk-xxx pytest ... -k "real"
"""
import os
import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.integrations.llm.openai_provider import OpenAIProvider
from apps.integrations.llm.ollama_provider import OllamaProvider
from apps.integrations.llm.asri_gateway_provider import AsriGatewayProvider
from apps.integrations.llm.registry import LLMRegistry


# -----------------------------------------------------------------------------
# Test Mode Control
# -----------------------------------------------------------------------------

@pytest.fixture(scope='session')
def llm_test_mode() -> str:
    """Get the current LLM test mode from environment."""
    return os.environ.get('LLM_TEST_MODE', 'mock')


def is_real_mode() -> bool:
    """Check if running in real mode."""
    return os.environ.get('LLM_TEST_MODE', 'mock') == 'real'


# Marker for real-mode-only tests
def real_mode_only(func_or_cls):
    """Mark a test as requiring real LLM API calls.

    Applies both ``pytest.mark.real_mode`` (for deselection via
    ``-m "not real_mode"`` in pytest.ini) and a ``skipif`` guard
    as a safety net.
    """
    func_or_cls = pytest.mark.real_mode(func_or_cls)
    func_or_cls = pytest.mark.skipif(
        not is_real_mode(),
        reason='Requires LLM_TEST_MODE=real and valid API credentials',
    )(func_or_cls)
    return func_or_cls

# Marker for mock-mode-only tests
mock_mode_only = pytest.mark.skipif(
    is_real_mode(),
    reason='This test only runs in mock mode'
)


# -----------------------------------------------------------------------------
# Registry Cleanup
# -----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_registry():
    """Clear LLM registry cache before and after each test."""
    LLMRegistry._instances.clear()
    yield
    LLMRegistry._instances.clear()


# -----------------------------------------------------------------------------
# Provider Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def openai_provider() -> OpenAIProvider:
    """Create an OpenAI provider instance for testing."""
    if is_real_mode():
        api_key = os.environ.get('OPENAI_API_KEY')
        api_base = os.environ.get('OPENAI_API_BASE', 'https://api.openai.com/v1')
        model_name = os.environ.get('OPENAI_MODEL', 'gpt-4')
        if not api_key:
            pytest.skip('OPENAI_API_KEY not set')
        return OpenAIProvider(api_base=api_base, api_key=api_key, model_name=model_name)
    else:
        return OpenAIProvider(
            api_base='https://api.openai.com/v1',
            api_key='test-api-key',
            model_name='gpt-4'
        )


@pytest.fixture
def ollama_provider() -> OllamaProvider:
    """Create an Ollama provider instance for testing."""
    if is_real_mode():
        api_base = os.environ.get('OLLAMA_API_BASE', 'http://localhost:11434')
        model_name = os.environ.get('OLLAMA_MODEL', 'llama2')
        return OllamaProvider(api_base=api_base, model_name=model_name)
    else:
        return OllamaProvider(
            api_base='http://localhost:11434',
            model_name='llama2'
        )


@pytest.fixture
def asri_gateway_provider() -> AsriGatewayProvider:
    """Create an AsriGateway provider instance for testing."""
    return AsriGatewayProvider(
        api_base='https://gateway.asri.com/v1',
        api_key='test-gateway-key',
        model_name='gpt-4',
        agent_context={'tenant_id': 'test-tenant', 'user_id': 'test-user'}
    )


# -----------------------------------------------------------------------------
# Test Data Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_messages():
    """Standard test messages for chat requests."""
    return [
        {'role': 'system', 'content': 'You are a helpful assistant.'},
        {'role': 'user', 'content': 'Hello!'}
    ]


# -----------------------------------------------------------------------------
# OpenAI Mock Response Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def openai_chat_response():
    """Mock OpenAI chat completion response."""
    return {
        'id': 'chatcmpl-123',
        'object': 'chat.completion',
        'created': 1677652288,
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


@pytest.fixture
def openai_stream_lines():
    """Mock OpenAI streaming response lines."""
    return [
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":" How"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
        'data: [DONE]'
    ]


@pytest.fixture
def openai_embed_response():
    """Mock OpenAI embedding response."""
    return {
        'object': 'list',
        'data': [{
            'object': 'embedding',
            'index': 0,
            'embedding': [0.1, 0.2, 0.3, 0.4, 0.5] * 100  # 500 dimensions
        }],
        'model': 'text-embedding-3-small',
        'usage': {
            'prompt_tokens': 5,
            'total_tokens': 5
        }
    }


# -----------------------------------------------------------------------------
# Ollama Mock Response Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def ollama_chat_response():
    """Mock Ollama chat response."""
    return {
        'model': 'llama2',
        'created_at': '2024-01-01T00:00:00Z',
        'message': {
            'role': 'assistant',
            'content': 'Hello! How can I assist you today?'
        },
        'done': True,
        'prompt_eval_count': 15,
        'eval_count': 10
    }


@pytest.fixture
def ollama_stream_lines():
    """Mock Ollama streaming response lines."""
    return [
        '{"model":"llama2","message":{"role":"assistant","content":"Hello"},"done":false}',
        '{"model":"llama2","message":{"role":"assistant","content":"!"},"done":false}',
        '{"model":"llama2","message":{"role":"assistant","content":" How"},"done":false}',
        '{"model":"llama2","message":{"role":"assistant","content":" can"},"done":false}',
        '{"model":"llama2","message":{"role":"assistant","content":""},"done":true}'
    ]


@pytest.fixture
def ollama_embed_response():
    """Mock Ollama embedding response."""
    return {
        'embedding': [0.1, 0.2, 0.3, 0.4, 0.5] * 100  # 500 dimensions
    }


# -----------------------------------------------------------------------------
# Mock HTTP Client Helpers
# -----------------------------------------------------------------------------

def create_mock_response(json_data: dict, status_code: int = 200):
    """Create a mock HTTP response object."""
    mock_response = MagicMock()
    mock_response.json.return_value = json_data
    mock_response.status_code = status_code
    mock_response.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f'HTTP {status_code}',
            request=MagicMock(),
            response=mock_response
        )
    return mock_response


def create_mock_stream_response(lines: list):
    """Create a mock streaming HTTP response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def fake_aiter_lines():
        for line in lines:
            yield line

    mock_response.aiter_lines = fake_aiter_lines
    return mock_response


class MockAsyncClient:
    """Mock httpx.AsyncClient for testing."""

    def __init__(self, response_data=None, stream_lines=None, raise_exception=None):
        self.response_data = response_data
        self.stream_lines = stream_lines
        self.raise_exception = raise_exception
        self.post_calls = []
        self.stream_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, **kwargs):
        self.post_calls.append({'url': url, 'kwargs': kwargs})
        if self.raise_exception:
            raise self.raise_exception
        return create_mock_response(self.response_data)

    def stream(self, method, url, **kwargs):
        self.stream_calls.append({'method': method, 'url': url, 'kwargs': kwargs})
        return MockStreamContext(self.stream_lines, self.raise_exception)


class MockStreamContext:
    """Mock async context manager for streaming."""

    def __init__(self, lines, raise_exception=None):
        self.lines = lines or []
        self.raise_exception = raise_exception

    async def __aenter__(self):
        if self.raise_exception:
            raise self.raise_exception
        return create_mock_stream_response(self.lines)

    async def __aexit__(self, *args):
        pass


# -----------------------------------------------------------------------------
# Async Helper Functions
# -----------------------------------------------------------------------------

async def collect_stream(generator: AsyncGenerator) -> list:
    """Collect all items from an async generator into a list."""
    items = []
    async for item in generator:
        items.append(item)
    return items
