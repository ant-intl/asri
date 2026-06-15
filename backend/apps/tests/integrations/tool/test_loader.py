"""
Tests for Tool Loader.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.tool import loader
from apps.integrations.tool.base import ToolRegistry
from apps.integrations.mcp import MCPServerRegistry


# -----------------------------------------------------------------------------
# Tests: Load MCP Tools
# -----------------------------------------------------------------------------

class TestLoadMCPToolsForTenant:
    """Test load_mcp_tools_for_tenant function."""

    @pytest.mark.asyncio
    async def test_empty_config_returns_zero(self):
        """Empty config returns 0."""
        result = await loader.load_mcp_tools_for_tenant({}, tenant_id='tenant123')

        assert result == 0

    @pytest.mark.asyncio
    async def test_no_mcp_servers_configured(self):
        """No MCP_SERVERS key returns 0."""
        result = await loader.load_mcp_tools_for_tenant({'OTHER': 'value'}, tenant_id='tenant123')

        assert result == 0

    @pytest.mark.asyncio
    async def test_loads_mcp_servers(self):
        """Correctly loads MCP server configuration."""
        config = {
            'MCP_SERVERS': [
                {'name': 'server1', 'endpoint': 'https://api1.com'},
                {'name': 'server2', 'endpoint': 'https://api2.com'}
            ]
        }

        with patch.object(MCPServerRegistry, 'discover_tools', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = []

            result = await loader.load_mcp_tools_for_tenant(config, tenant_id='tenant123')

            assert result == 0

    @pytest.mark.asyncio
    async def test_discover_tools_registers(self):
        """discover_tools() results are registered to ToolRegistry."""
        config = {
            'MCP_SERVERS': [
                {'name': 'server1', 'endpoint': 'https://api1.com'}
            ]
        }

        mock_tool = MagicMock()
        mock_tool.name = 'mcp_tool'
        mock_tool._server_name = 'server1'

        with patch.object(MCPServerRegistry, 'discover_tools', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_tool]

            with patch.object(ToolRegistry, 'register') as mock_register:
                result = await loader.load_mcp_tools_for_tenant(config, tenant_id='tenant123')

                assert result == 1
                mock_register.assert_called_once_with(mock_tool)

    @pytest.mark.asyncio
    async def test_returns_correct_count(self):
        """Returns correct number of registered tools."""
        config = {
            'MCP_SERVERS': [
                {'name': 'server1', 'endpoint': 'https://api1.com'}
            ]
        }

        mock_tool1 = MagicMock()
        mock_tool1.name = 'tool1'
        mock_tool1._server_name = 'server1'

        mock_tool2 = MagicMock()
        mock_tool2.name = 'tool2'
        mock_tool2._server_name = 'server1'

        with patch.object(MCPServerRegistry, 'discover_tools', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_tool1, mock_tool2]

            result = await loader.load_mcp_tools_for_tenant(config, tenant_id='tenant123')

            assert result == 2

    @pytest.mark.asyncio
    async def test_handles_registration_failure(self):
        """Handles server registration failure gracefully."""
        config = {
            'MCP_SERVERS': [
                {'name': 'server1', 'endpoint': 'https://api1.com'}
            ]
        }

        mock_tool = MagicMock()
        mock_tool.name = 'tool1'
        mock_tool._server_name = 'server1'

        with patch.object(MCPServerRegistry, 'discover_tools', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_tool]

            with patch.object(ToolRegistry, 'register', side_effect=Exception('Registration failed')):
                result = await loader.load_mcp_tools_for_tenant(config, tenant_id='tenant123')

                # Should return 0 because registration failed
                assert result == 0


# -----------------------------------------------------------------------------
# Tests: Load Tools
# -----------------------------------------------------------------------------

class TestLoadToolsForTenant:
    """Test load_tools_for_tenant function."""

    @pytest.mark.asyncio
    async def test_empty_tools_config(self):
        """Empty config returns 0."""
        result = await loader.load_tools_for_tenant({}, tenant_id='tenant123')

        assert result == 0

    @pytest.mark.asyncio
    async def test_no_tools_key(self):
        """No TOOLS key returns 0."""
        result = await loader.load_tools_for_tenant({'OTHER': 'value'}, tenant_id='tenant123')

        assert result == 0

    @pytest.mark.asyncio
    async def test_skips_disabled_tools(self):
        """enabled=False tools are skipped."""
        config = {
            'TOOLS': [
                {'name': 'tool1', 'enabled': False}
            ]
        }

        result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

        assert result == 0

    @pytest.mark.asyncio
    async def test_loads_single_tool(self):
        """Loads a single tool."""
        # Register a tool class first
        from apps.integrations.tool.base import BaseTool
        from typing import Any, Optional

        class TestTool(BaseTool):
            name = 'test_tool'
            description = 'Test tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text, context):
                return 'result'

        config = {
            'TOOLS': [
                {'name': 'test_tool', 'config': {'key': 'value'}}
            ]
        }

        result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

        assert result == 1

        # Verify tool was registered with config
        tool = ToolRegistry.get_tool('test_tool', tenant_id='tenant123')
        assert tool is not None
        assert tool.config == {'key': 'value'}

    @pytest.mark.asyncio
    async def test_loads_multiple_tools(self):
        """Loads multiple tools."""
        from apps.integrations.tool.base import BaseTool

        class Tool1(BaseTool):
            name = 'tool_one'
            description = 'Tool 1'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text, context):
                return 'result1'

        class Tool2(BaseTool):
            name = 'tool_two'
            description = 'Tool 2'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text, context):
                return 'result2'

        config = {
            'TOOLS': [
                {'name': 'tool_one'},
                {'name': 'tool_two'}
            ]
        }

        result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

        assert result == 2

    @pytest.mark.asyncio
    async def test_skips_unknown_tool_class(self):
        """Unknown tool classes are skipped."""
        config = {
            'TOOLS': [
                {'name': 'nonexistent_tool'}
            ]
        }

        result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

        assert result == 0

    @pytest.mark.asyncio
    async def test_passes_config_to_tool(self):
        """Configuration is passed to tool constructor."""
        from apps.integrations.tool.base import BaseTool

        class ConfiguredTool(BaseTool):
            name = 'configured_tool'
            description = 'Configured tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text, context):
                return self.config

        config = {
            'TOOLS': [
                {'name': 'configured_tool', 'config': {'custom_option': 42}}
            ]
        }

        result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

        assert result == 1
        tool = ToolRegistry.get_tool('configured_tool', tenant_id='tenant123')
        assert tool.config == {'custom_option': 42}

    @pytest.mark.asyncio
    async def test_returns_correct_count(self):
        """Returns correct number of loaded tools."""
        from apps.integrations.tool.base import BaseTool

        class LoadableTool(BaseTool):
            name = 'loadable_tool'
            description = 'Loadable tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text, context):
                return 'result'

        config = {
            'TOOLS': [
                {'name': 'loadable_tool'},
                {'name': 'nonexistent1'},
                {'name': 'nonexistent2'},
                {'name': 'loadable_tool2', 'enabled': False}  # disabled
            ]
        }

        result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

        # Only 1 valid tool (loadable_tool), others are invalid or disabled
        assert result == 1

    @pytest.mark.asyncio
    async def test_loads_mcp_tools_via_type_field(self):
        """Loads MCP tools when type='mcp' is specified in TOOLS config."""
        config = {
            'TOOLS': [
                {'name': 'example_mcp', 'type': 'mcp', 'config': {'endpoint': 'https://api.example.com'}}
            ]
        }

        mock_tool = MagicMock()
        mock_tool.name = 'mcp_tool'
        mock_tool._server_name = 'example_mcp'

        with patch.object(MCPServerRegistry, 'discover_tools', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_tool]

            with patch.object(ToolRegistry, 'register') as mock_register:
                result = await loader.load_tools_for_tenant(config, tenant_id='tenant123')

                assert result == 1
                mock_register.assert_called_once_with(mock_tool, tenant_id='tenant123')

    @pytest.mark.asyncio
    async def test_mcp_type_registers_server(self):
        """type='mcp' registers the server with MCPServerRegistry."""
        from apps.integrations.mcp import MCPServerConfig

        config = {
            'TOOLS': [
                {'name': 'test_mcp', 'type': 'mcp', 'config': {'endpoint': 'https://test.com'}}
            ]
        }

        mock_tool = MagicMock()
        mock_tool.name = 'tool1'

        with patch.object(MCPServerRegistry, 'discover_tools', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [mock_tool]

            with patch('apps.integrations.mcp.MCPServerRegistry.register_server') as mock_register_server:
                await loader.load_tools_for_tenant(config, tenant_id='tenant123')

                # Verify register_server was called with correct config
                mock_register_server.assert_called_once()
                call_args = mock_register_server.call_args
                assert call_args[0][0].name == 'test_mcp'
                assert call_args[0][0].endpoint == 'https://test.com'
