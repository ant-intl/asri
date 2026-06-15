"""
Pytest configuration and fixtures for Tool tests.

Supports two test modes:
- Mock mode (default): External services are mocked
- Real mode: Actual API calls are made (requires env vars)

Usage:
    # Mock mode (default)
    SERVER_ENV=test pytest apps/tests/integrations/tool/ -v

    # Real mode
    TOOL_TEST_MODE=real pytest ... -k "real"
"""
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.integrations.tool.base import ToolRegistry
from apps.integrations.mcp import MCPServerRegistry


# -----------------------------------------------------------------------------
# Test Mode Control
# -----------------------------------------------------------------------------

@pytest.fixture(scope='session')
def tool_test_mode() -> str:
    """Get the current tool test mode from environment."""
    return os.environ.get('TOOL_TEST_MODE', 'mock')


def is_real_mode() -> bool:
    """Check if running in real mode."""
    return os.environ.get('TOOL_TEST_MODE', 'mock') == 'real'


def real_mode_only(func_or_cls):
    """Mark a test as requiring real service calls."""
    func_or_cls = pytest.mark.real_mode(func_or_cls)
    func_or_cls = pytest.mark.skipif(
        not is_real_mode(),
        reason='Requires TOOL_TEST_MODE=real',
    )(func_or_cls)
    return func_or_cls


mock_mode_only = pytest.mark.skipif(
    is_real_mode(),
    reason='This test only runs in mock mode'
)


# -----------------------------------------------------------------------------
# Registry Cleanup
# -----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_tool_registry():
    """Clear ToolRegistry cache before and after each test."""
    ToolRegistry._tools.clear()
    ToolRegistry._tool_classes.clear()
    yield
    ToolRegistry._tools.clear()
    ToolRegistry._tool_classes.clear()


@pytest.fixture(autouse=True)
def clear_mcp_server_registry():
    """Clear MCPServerRegistry cache before and after each test."""
    MCPServerRegistry._servers.clear()
    yield
    MCPServerRegistry._servers.clear()


# -----------------------------------------------------------------------------
# Mock Tool Implementations
# -----------------------------------------------------------------------------

class MockTool:
    """Mock tool for testing."""

    name = 'mock_tool'
    description = 'A mock tool for testing'
    parameters_schema = {
        'type': 'object',
        'properties': {
            'input': {'type': 'string'}
        },
        'required': ['input']
    }

    def __init__(self, config: dict = None, tenant_id: str = None):
        self.config = config or {}
        self.tenant_id = tenant_id
        self.execute_count = 0

    async def execute(self, input_text: str, context: Any = None) -> str:
        self.execute_count += 1
        return f'MockTool executed: {input_text}'


# -----------------------------------------------------------------------------
# Test Data Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_mcp_tools():
    """Standard MCP tool definitions."""
    return [
        {
            'name': 'get_balance',
            'description': 'Get account balance',
            'inputSchema': {'type': 'object'}
        },
        {
            'name': 'transfer',
            'description': 'Transfer money',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'amount': {'type': 'number'},
                    'to_account': {'type': 'string'}
                },
                'required': ['amount', 'to_account']
            }
        }
    ]


@pytest.fixture
def sample_tool_config():
    """Standard tool configuration."""
    return [
        {'name': 'rag_search', 'config': {'top_k': 5}, 'enabled': True},
    ]


@pytest.fixture
def sample_mcp_server_config():
    """Standard MCP server configuration."""
    return [
        {
            'name': 'example_mcp',
            'endpoint': 'https://mcp.example.com/api',
            'merchant_id': 'M001',
            'user_id': 'U001',
            'wallet_id': 'W001'
        }
    ]


@pytest.fixture
def sample_rag_results():
    """Standard RAG search results."""
    return [
        {'content': 'Result 1: Information about the query', 'score': 0.95, 'doc_id': 'doc1'},
        {'content': 'Result 2: More details', 'score': 0.85, 'doc_id': 'doc2'},
        {'content': 'Result 3: Additional context', 'score': 0.75, 'doc_id': 'doc3'}
    ]


@pytest.fixture
def sample_skills():
    """Standard skill definitions."""
    return {
        'skill_one': {
            'name': 'skill_one',
            'description': 'First test skill',
            'content': 'Content of skill one'
        },
        'skill_two': {
            'name': 'skill_two',
            'description': 'Second test skill',
            'content': 'Content of skill two'
        }
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


class MockAsyncClient:
    """Mock httpx.AsyncClient for testing."""

    def __init__(self, response_data=None, raise_exception=None):
        self.response_data = response_data
        self.raise_exception = raise_exception
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, **kwargs):
        self.post_calls.append({'url': url, 'kwargs': kwargs})
        if self.raise_exception:
            raise self.raise_exception
        return create_mock_response(self.response_data)

    async def aclose(self):
        pass
