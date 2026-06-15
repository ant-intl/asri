"""
Tests for MCP Server Registry.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.mcp import MCPServerRegistry, MCPServerConfig, MCPDynamicTool


# -----------------------------------------------------------------------------
# Tests: MCPServerConfig
# -----------------------------------------------------------------------------

class TestMCPServerConfig:
    """Test MCPServerConfig dataclass."""

    def test_required_name(self):
        """name is a required field."""
        config = MCPServerConfig(name='example_mcp')
        assert config.name == 'example_mcp'

    def test_default_values(self):
        """Default values are correct."""
        config = MCPServerConfig(name='test_server')

        assert config.endpoint is None
        assert config.timeout == 30
        assert config.retry_count == 3
        assert config.auto_discover is True
        assert config._client is None

    def test_all_fields(self):
        """All fields can be set correctly."""
        config = MCPServerConfig(
            name='example_mcp',
            endpoint='https://mcp.example.com/api',
            timeout=60,
            retry_count=5,
            auto_discover=False
        )

        assert config.name == 'example_mcp'
        assert config.endpoint == 'https://mcp.example.com/api'
        assert config.timeout == 60
        assert config.retry_count == 5
        assert config.auto_discover is False


# -----------------------------------------------------------------------------
# Tests: MCPServerRegistry Registration
# -----------------------------------------------------------------------------

class TestMCPServerRegistryRegistration:
    """Test MCPServerRegistry server registration."""

    def test_register_server(self):
        """register_server() registers a server."""
        config = MCPServerConfig(name='example_mcp', endpoint='https://api.example.com')
        MCPServerRegistry.register_server(config, tenant_id=None)

        assert 'example_mcp' in MCPServerRegistry._servers[None]
        assert MCPServerRegistry._servers[None]['example_mcp'] is config

    def test_register_server_tenant_specific(self):
        """register_server() stores in tenant bucket."""
        config = MCPServerConfig(name='example_mcp', endpoint='https://api.example.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        assert 'tenant123' in MCPServerRegistry._servers
        assert 'example_mcp' in MCPServerRegistry._servers['tenant123']

    def test_get_server_tenant_specific(self):
        """get_server() returns tenant-specific server."""
        config = MCPServerConfig(name='example_mcp', endpoint='https://api.example.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        with patch('apps.tenant.context.get_current_tenant_id', return_value='tenant123'):
            result = MCPServerRegistry.get_server('example_mcp')

        assert result is config

    def test_get_server_fallback_global(self):
        """get_server() falls back to global when tenant server not found."""
        global_config = MCPServerConfig(name='example_mcp', endpoint='https://global.api.com')
        MCPServerRegistry.register_server(global_config, tenant_id=None)

        with patch('apps.tenant.context.get_current_tenant_id', return_value='tenant123'):
            result = MCPServerRegistry.get_server('example_mcp')

        assert result is global_config

    def test_get_server_not_found(self):
        """get_server() returns None when not found."""
        with patch('apps.tenant.context.get_current_tenant_id', return_value='tenant123'):
            result = MCPServerRegistry.get_server('nonexistent')

        assert result is None

    def test_get_server_explicit_tenant(self):
        """get_server() uses explicit tenant_id when provided."""
        config = MCPServerConfig(name='example_mcp', endpoint='https://api.example.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        result = MCPServerRegistry.get_server('example_mcp', tenant_id='tenant123')
        assert result is config

    def test_list_servers(self):
        """list_servers() returns server names."""
        config1 = MCPServerConfig(name='server1', endpoint='https://api1.com')
        config2 = MCPServerConfig(name='server2', endpoint='https://api2.com')
        MCPServerRegistry.register_server(config1, tenant_id='tenant123')
        MCPServerRegistry.register_server(config2, tenant_id='tenant123')

        servers = MCPServerRegistry.list_servers(tenant_id='tenant123')
        assert servers == ['server1', 'server2']

    def test_list_servers_empty(self):
        """list_servers() returns empty list when no servers."""
        servers = MCPServerRegistry.list_servers(tenant_id='empty_tenant')
        assert servers == []

    def test_register_same_name_overwrites(self):
        """Registering same name overwrites previous config."""
        config1 = MCPServerConfig(name='example_mcp', endpoint='https://old.com')
        config2 = MCPServerConfig(name='example_mcp', endpoint='https://new.com')
        MCPServerRegistry.register_server(config1, tenant_id=None)
        MCPServerRegistry.register_server(config2, tenant_id=None)

        assert MCPServerRegistry._servers[None]['example_mcp'] is config2


# -----------------------------------------------------------------------------
# Tests: MCPServerRegistry Discovery
# -----------------------------------------------------------------------------

class TestMCPServerRegistryDiscovery:
    """Test MCPServerRegistry tool discovery."""

    @pytest.mark.asyncio
    async def test_discover_tools_empty(self):
        """discover_tools() returns empty list when no servers."""
        tools = await MCPServerRegistry.discover_tools(tenant_id='empty_tenant')
        assert tools == []

    @pytest.mark.asyncio
    async def test_discover_tools_success(self):
        """discover_tools() successfully discovers tools."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {'name': 'tool1', 'description': 'Tool 1', 'inputSchema': {}},
            {'name': 'tool2', 'description': 'Tool 2', 'inputSchema': {}}
        ])

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            tools = await MCPServerRegistry.discover_tools(tenant_id='tenant123')

        assert len(tools) == 2
        assert tools[0].name == 'tool1'
        assert tools[1].name == 'tool2'

    @pytest.mark.asyncio
    async def test_discover_tools_creates_dynamic_tools(self):
        """discover_tools() creates MCPDynamicTool instances."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {'name': 'get_balance', 'description': 'Get balance', 'inputSchema': {'type': 'object'}}
        ])

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            tools = await MCPServerRegistry.discover_tools(tenant_id='tenant123')

        assert len(tools) == 1
        assert isinstance(tools[0], MCPDynamicTool)
        assert tools[0].name == 'get_balance'
        assert tools[0]._server_name == 'test_server'

    @pytest.mark.asyncio
    async def test_discover_tools_handles_client_error(self):
        """discover_tools() continues when one server fails."""
        config1 = MCPServerConfig(name='server1', endpoint='https://api1.com')
        config2 = MCPServerConfig(name='server2', endpoint='https://api2.com')
        MCPServerRegistry.register_server(config1, tenant_id='tenant123')
        MCPServerRegistry.register_server(config2, tenant_id='tenant123')

        mock_client1 = AsyncMock()
        mock_client1.list_tools = AsyncMock(side_effect=Exception('Connection error'))

        mock_client2 = AsyncMock()
        mock_client2.list_tools = AsyncMock(return_value=[
            {'name': 'tool2', 'description': 'Tool 2', 'inputSchema': {}}
        ])

        async def mock_get_client(config):
            if config.name == 'server1':
                return mock_client1
            return mock_client2

        with patch.object(MCPServerRegistry, '_get_or_create_client', side_effect=mock_get_client):
            tools = await MCPServerRegistry.discover_tools(tenant_id='tenant123')

        # Should still get tools from server2
        assert len(tools) == 1
        assert tools[0].name == 'tool2'

    @pytest.mark.asyncio
    async def test_discover_tools_returns_all(self):
        """discover_tools() returns tools from all servers."""
        config1 = MCPServerConfig(name='server1', endpoint='https://api1.com')
        config2 = MCPServerConfig(name='server2', endpoint='https://api2.com')
        MCPServerRegistry.register_server(config1, tenant_id='tenant123')
        MCPServerRegistry.register_server(config2, tenant_id='tenant123')

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(side_effect=[
            [{'name': 'tool1', 'description': 'Tool 1', 'inputSchema': {}}],
            [{'name': 'tool2', 'description': 'Tool 2', 'inputSchema': {}}]
        ])

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            tools = await MCPServerRegistry.discover_tools(tenant_id='tenant123')

        assert len(tools) == 2


# -----------------------------------------------------------------------------
# Tests: MCPServerRegistry CallTool
# -----------------------------------------------------------------------------

class TestMCPServerRegistryCallTool:
    """Test MCPServerRegistry tool calling."""

    @pytest.mark.asyncio
    async def test_call_tool_server_not_found(self):
        """call_tool() raises ValueError when server not found."""
        with pytest.raises(ValueError, match="not found"):
            await MCPServerRegistry.call_tool('nonexistent', 'tool', {}, tenant_id='tenant123')

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """call_tool() successfully calls a tool."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={'result': 'success'})

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            result = await MCPServerRegistry.call_tool('test_server', 'tool_name', {'arg': 'value'}, tenant_id='tenant123')

        assert result == {'result': 'success'}
        mock_client.call_tool.assert_called_once_with('tool_name', {'arg': 'value'})


# -----------------------------------------------------------------------------
# Tests: MCPServerRegistry Clear
# -----------------------------------------------------------------------------

class TestMCPServerRegistryClear:
    """Test MCPServerRegistry clear functionality."""

    def test_clear_all(self):
        """clear() clears all servers."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id=None)
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        MCPServerRegistry.clear()

        assert MCPServerRegistry._servers == {}

    def test_clear_tenant(self):
        """clear(tenant_id) clears specific tenant."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')
        MCPServerRegistry.register_server(config, tenant_id='tenant456')

        MCPServerRegistry.clear('tenant123')

        assert 'tenant123' not in MCPServerRegistry._servers
        assert 'tenant456' in MCPServerRegistry._servers
