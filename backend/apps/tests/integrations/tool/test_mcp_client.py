"""
Tests for MCP Client.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.mcp import (
    BaseMCPClient,
    MCPClientWrapper,
    MCPServerConfig,
)


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def http_config():
    """HTTP MCP server config."""
    return MCPServerConfig(
        name='test_server',
        endpoint='https://mcp.example.com/api',
        timeout=30
    )


# -----------------------------------------------------------------------------
# Tests: BaseMCPClient Abstraction
# -----------------------------------------------------------------------------

class TestBaseMCPClientAbstraction:
    """Test BaseMCPClient abstract class."""

    def test_is_abstract_class(self):
        """Verify BaseMCPClient is an ABC."""
        from abc import ABC
        assert issubclass(BaseMCPClient, ABC)

    def test_cannot_instantiate_directly(self):
        """Cannot instantiate BaseMCPClient directly."""
        with pytest.raises(TypeError):
            BaseMCPClient()


# -----------------------------------------------------------------------------
# Tests: MCPClientWrapper
# -----------------------------------------------------------------------------

class TestMCPClientWrapper:
    """Test MCPClientWrapper factory."""

    def test_uses_http_client_by_default(self, http_config):
        """Default uses HTTP client."""
        wrapper = MCPClientWrapper(http_config)

        assert wrapper.config is http_config
        assert wrapper._client is None
