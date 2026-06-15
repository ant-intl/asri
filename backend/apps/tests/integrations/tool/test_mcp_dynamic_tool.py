"""
Tests for MCP Dynamic Tool.
"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.mcp import MCPDynamicTool, MCPServerRegistry, MCPServerConfig
from apps.integrations.mcp.mcp_dynamic_tool import resolve_schema_refs


# -----------------------------------------------------------------------------
# Tests: MCPDynamicTool
# -----------------------------------------------------------------------------

class TestMCPDynamicTool:
    """Test MCPDynamicTool implementation."""

    def test_initialization(self):
        """Initialization stores attributes correctly."""
        tool = MCPDynamicTool(
            name='get_balance',
            description='Get account balance',
            parameters_schema={'type': 'object'},
            server_name='test_server',
            tenant_id='tenant123',
            config={'timeout': 30}
        )

        assert tool.name == 'get_balance'
        assert tool._description == 'Get account balance'
        assert tool.parameters_schema == {'type': 'object'}
        assert tool._server_name == 'test_server'
        assert tool._tenant_id == 'tenant123'
        assert tool.config == {'timeout': 30}

    def test_description_property(self):
        """description property returns stored value."""
        tool = MCPDynamicTool(
            name='test_tool',
            description='Test description',
            parameters_schema={},
            server_name='test_server'
        )

        assert tool.description == 'Test description'

    def test_to_tool_schema_basic(self):
        """to_tool_schema() returns correct format."""
        tool = MCPDynamicTool(
            name='get_balance',
            description='Get balance',
            parameters_schema={'type': 'object'},
            server_name='test_server'
        )

        schema = tool.to_tool_schema()

        assert schema['type'] == 'function'
        assert schema['function']['name'] == 'get_balance'
        assert schema['function']['description'] == 'Get balance'

    def test_to_tool_schema_with_parameters(self):
        """to_tool_schema() includes parameters when provided."""
        tool = MCPDynamicTool(
            name='transfer',
            description='Transfer money',
            parameters_schema={
                'type': 'object',
                'properties': {
                    'amount': {'type': 'number'},
                    'to_account': {'type': 'string'}
                }
            },
            server_name='test_server'
        )

        schema = tool.to_tool_schema()

        assert schema['function']['parameters'] == tool.parameters_schema

    def test_to_tool_schema_default_schema(self):
        """to_tool_schema() uses default schema when none provided."""
        tool = MCPDynamicTool(
            name='test_tool',
            description='Test',
            parameters_schema={},
            server_name='test_server'
        )

        schema = tool.to_tool_schema()

        assert 'parameters' in schema['function']
        assert schema['function']['parameters']['properties']['input']

    @pytest.mark.asyncio
    async def test_execute_server_not_found(self):
        """execute() returns error when server not found."""
        tool = MCPDynamicTool(
            name='test_tool',
            description='Test',
            parameters_schema={},
            server_name='nonexistent_server'
        )

        result = await tool.execute('{}', None)

        assert 'not found' in result

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """execute() returns result on success."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id='tenant123')

        tool = MCPDynamicTool(
            name='get_balance',
            description='Get balance',
            parameters_schema={},
            server_name='test_server',
            tenant_id='tenant123'
        )

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={'balance': 100})

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            result = await tool.execute('{}', None)

        assert 'balance' in result

    @pytest.mark.asyncio
    async def test_execute_returns_formatted_result(self):
        """execute() returns formatted result."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id=None)

        tool = MCPDynamicTool(
            name='get_balance',
            description='Get balance',
            parameters_schema={},
            server_name='test_server'
        )

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={'balance': 100})

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            result = await tool.execute('{}', None)

        # Result should be JSON formatted string
        assert 'balance' in result
        assert '100' in result

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self):
        """execute() handles exceptions gracefully."""
        config = MCPServerConfig(name='test_server', endpoint='https://api.com')
        MCPServerRegistry.register_server(config, tenant_id=None)

        tool = MCPDynamicTool(
            name='test_tool',
            description='Test',
            parameters_schema={},
            server_name='test_server'
        )

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=Exception('Connection error'))

        with patch.object(MCPServerRegistry, '_get_or_create_client', return_value=mock_client):
            result = await tool.execute('{}', None)

        assert 'failed' in result
        assert 'Connection error' in result


# -----------------------------------------------------------------------------
# Tests: MCPDynamicTool Input Parsing
# -----------------------------------------------------------------------------

class TestMCPDynamicToolInputParsing:
    """Test MCPDynamicTool input parsing."""

    def test_parse_input_json(self):
        """_parse_input() parses JSON input."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._parse_input('{"key": "value"}')

        assert result == {'key': 'value'}

    def test_parse_input_key_value(self):
        """_parse_input() handles key:value format."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._parse_input('amount:100')

        # Result is an integer when value is a number without JSON
        assert result == 100 or result == {'amount': 100}

    def test_parse_input_key_value_json(self):
        """_parse_input() parses JSON after colon."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._parse_input('transfer:{"amount": 100}')

        assert result == {'amount': 100}

    def test_parse_input_plain_text(self):
        """_parse_input() treats plain text as input."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._parse_input('search query')

        assert result == {'input': 'search query'}

    def test_parse_input_empty(self):
        """_parse_input() returns empty dict for empty input."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._parse_input('')

        assert result == {}


# -----------------------------------------------------------------------------
# Tests: MCPDynamicTool Result Formatting
# -----------------------------------------------------------------------------

class TestMCPDynamicToolResultFormatting:
    """Test MCPDynamicTool result formatting."""

    def test_format_result_dict(self):
        """_format_result() handles dict result."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._format_result({'key': 'value'})

        assert 'key' in result
        assert 'value' in result

    def test_format_result_list(self):
        """_format_result() handles list result."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._format_result([{'item': 1}, {'item': 2}])

        assert 'item' in result

    def test_format_result_string(self):
        """_format_result() handles string result."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._format_result('plain text result')

        assert result == 'plain text result'

    def test_format_result_card_response(self):
        """_format_result() handles card response."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        mock_context = MagicMock()
        mock_context.metadata = {}

        card_response = {
            'businessCardMCPAnswer': True,
            'businessCardList': [{'card': 'data'}]
        }

        result = tool._format_result(card_response, mock_context)

        assert 'businessCardMCPAnswer' in result
        assert mock_context.metadata.get('card_response') is True

    def test_format_result_number(self):
        """_format_result() handles numeric result."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test'
        )

        result = tool._format_result(123)

        assert result == '123'


# -----------------------------------------------------------------------------
# Tests: resolve_schema_refs
# -----------------------------------------------------------------------------

class TestResolveSchemaRefs:
    """Test resolve_schema_refs() utility function."""

    def test_simple_ref_resolution(self):
        """$ref to a $defs entry is replaced by the definition inline."""
        schema = {
            "type": "object",
            "properties": {
                "item": {"$ref": "#/$defs/Item"}
            },
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"}
                    },
                    "required": ["id"]
                }
            }
        }

        result = resolve_schema_refs(schema)

        assert "$defs" not in result
        assert "$ref" not in json.dumps(result)
        assert result["properties"]["item"]["type"] == "object"
        assert result["properties"]["item"]["properties"]["id"]["type"] == "integer"
        assert result["properties"]["item"]["properties"]["name"]["type"] == "string"
        assert result["properties"]["item"]["required"] == ["id"]

    def test_ref_inside_array_items(self):
        """$ref inside array items is resolved."""
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/SubModel"}
                }
            },
            "$defs": {
                "SubModel": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "string"}
                    },
                    "required": ["x", "y"]
                }
            },
            "required": ["items"]
        }

        result = resolve_schema_refs(schema)

        assert "$defs" not in result
        assert "$ref" not in json.dumps(result)
        resolved_items = result["properties"]["items"]["items"]
        assert resolved_items["type"] == "object"
        assert "x" in resolved_items["properties"]
        assert "y" in resolved_items["properties"]

    def test_nested_ref_resolution(self):
        """Nested $ref (A references B, B references C) is fully resolved."""
        schema = {
            "type": "object",
            "properties": {
                "parent": {"$ref": "#/$defs/Parent"}
            },
            "$defs": {
                "Parent": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/$defs/Child"},
                        "name": {"type": "string"}
                    }
                },
                "Child": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"}
                    }
                }
            }
        }

        result = resolve_schema_refs(schema)

        assert "$ref" not in json.dumps(result)
        child = result["properties"]["parent"]["properties"]["child"]
        assert child["type"] == "object"
        assert child["properties"]["value"]["type"] == "integer"

    def test_circular_ref_guard(self):
        """Circular $ref does not cause infinite recursion."""
        schema = {
            "type": "object",
            "properties": {
                "node": {"$ref": "#/$defs/Node"}
            },
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "next": {"$ref": "#/$defs/Node"}
                    }
                }
            }
        }

        result = resolve_schema_refs(schema)

        assert "$defs" not in result
        # The circular reference should be replaced with a placeholder
        next_node = result["properties"]["node"]["properties"]["next"]
        assert next_node["type"] == "object"
        assert "circular" in next_node.get("description", "")

    def test_definitions_key(self):
        """Older 'definitions' key (JSON Schema draft-07) is also supported."""
        schema = {
            "type": "object",
            "properties": {
                "item": {"$ref": "#/definitions/Item"}
            },
            "definitions": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"}
                    }
                }
            }
        }

        result = resolve_schema_refs(schema)

        assert "definitions" not in result
        assert "$ref" not in json.dumps(result)
        assert result["properties"]["item"]["properties"]["id"]["type"] == "integer"

    def test_no_refs_passthrough(self):
        """Schema without $defs/$ref passes through unchanged."""
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search query"}
            },
            "required": ["query"]
        }

        result = resolve_schema_refs(schema)

        assert result == schema

    def test_empty_schema(self):
        """Empty schema returns empty dict."""
        assert resolve_schema_refs({}) == {}

    def test_non_dict_input(self):
        """Non-dict input is returned as-is."""
        assert resolve_schema_refs("not a dict") == "not a dict"

    def test_multiple_refs_to_same_def(self):
        """Multiple $ref pointing to the same definition are all resolved."""
        schema = {
            "type": "object",
            "properties": {
                "sender": {"$ref": "#/$defs/User"},
                "receiver": {"$ref": "#/$defs/User"}
            },
            "$defs": {
                "User": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"}
                    }
                }
            }
        }

        result = resolve_schema_refs(schema)

        assert "$ref" not in json.dumps(result)
        assert result["properties"]["sender"]["properties"]["name"]["type"] == "string"
        assert result["properties"]["receiver"]["properties"]["email"]["type"] == "string"

    def test_ref_with_extra_properties(self):
        """$ref node with sibling properties keeps only the resolved definition."""
        schema = {
            "type": "object",
            "properties": {
                "item": {
                    "$ref": "#/$defs/Item",
                    "description": "An item"
                }
            },
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}}
                }
            }
        }

        result = resolve_schema_refs(schema)

        # $ref replaces the entire node with the resolved definition
        assert result["properties"]["item"]["type"] == "object"
        assert "$ref" not in json.dumps(result)


# -----------------------------------------------------------------------------
# Tests: MCPDynamicTool schema normalization on init
# -----------------------------------------------------------------------------

class TestMCPDynamicToolSchemaNormalization:
    """Test that MCPDynamicTool normalizes parameters_schema on initialization."""

    def test_init_resolves_refs(self):
        """MCPDynamicTool.__init__() resolves $defs/$ref in parameters_schema."""
        raw_schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/SubModel"}
                }
            },
            "$defs": {
                "SubModel": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "string"}
                    },
                    "required": ["x", "y"]
                }
            },
            "required": ["items"]
        }

        tool = MCPDynamicTool(
            name="test_tool",
            description="Test",
            parameters_schema=raw_schema,
            server_name="test_server"
        )

        schema_str = json.dumps(tool.parameters_schema)
        assert "$defs" not in schema_str
        assert "$ref" not in schema_str
        assert tool.parameters_schema["properties"]["items"]["items"]["type"] == "object"

    def test_init_empty_schema(self):
        """MCPDynamicTool.__init__() handles empty parameters_schema."""
        tool = MCPDynamicTool(
            name="test_tool",
            description="Test",
            parameters_schema={},
            server_name="test_server"
        )

        assert tool.parameters_schema == {}

    def test_init_none_schema(self):
        """MCPDynamicTool.__init__() handles None parameters_schema."""
        tool = MCPDynamicTool(
            name="test_tool",
            description="Test",
            parameters_schema=None,
            server_name="test_server"
        )

        assert tool.parameters_schema == {}

    def test_init_plain_schema_unchanged(self):
        """MCPDynamicTool.__init__() leaves plain schemas untouched."""
        plain_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search query"}
            },
            "required": ["query"]
        }

        tool = MCPDynamicTool(
            name="test_tool",
            description="Test",
            parameters_schema=plain_schema,
            server_name="test_server"
        )

        assert tool.parameters_schema == plain_schema

    def test_to_tool_schema_no_refs(self):
        """to_tool_schema() output does not contain $defs/$ref."""
        raw_schema = {
            "type": "object",
            "properties": {
                "data": {"$ref": "#/$defs/DataModel"}
            },
            "$defs": {
                "DataModel": {
                    "type": "object",
                    "properties": {"value": {"type": "number"}}
                }
            }
        }

        tool = MCPDynamicTool(
            name="test_tool",
            description="Test",
            parameters_schema=raw_schema,
            server_name="test_server"
        )

        schema = tool.to_tool_schema()
        schema_str = json.dumps(schema)

        assert "$defs" not in schema_str
        assert "$ref" not in schema_str
        assert schema["function"]["parameters"]["properties"]["data"]["type"] == "object"

    def test_init_does_not_mutate_original(self):
        """MCPDynamicTool.__init__() does not mutate the original schema dict."""
        raw_schema = {
            "type": "object",
            "properties": {
                "item": {"$ref": "#/$defs/Item"}
            },
            "$defs": {
                "Item": {"type": "object", "properties": {"id": {"type": "integer"}}}
            }
        }

        original_str = json.dumps(raw_schema, sort_keys=True)

        MCPDynamicTool(
            name="test_tool",
            description="Test",
            parameters_schema=raw_schema,
            server_name="test_server"
        )

        # Original schema should not be mutated
        assert json.dumps(raw_schema, sort_keys=True) == original_str


# -----------------------------------------------------------------------------
# Tests: _check_proxy_tool_mock
# -----------------------------------------------------------------------------

class TestProxyToolMock:
    """Test _check_proxy_tool_mock() method."""

    def _make_tool(self, name='mcpToolExecute', server_name='test'):
        return MCPDynamicTool(
            name=name,
            description='Proxy tool',
            parameters_schema={'type': 'object'},
            server_name=server_name,
        )

    def test_no_mcp_execute_tools_returns_none(self):
        """Returns None when mcpExecuteTools is missing."""
        tool = self._make_tool()
        result = tool._check_proxy_tool_mock({'query': 'hello'})
        assert result is None

    def test_empty_tools_list_returns_none(self):
        """Returns None when mcpExecuteTools is empty list."""
        tool = self._make_tool()
        result = tool._check_proxy_tool_mock({'mcpExecuteTools': []})
        assert result is None

    def test_non_list_tools_returns_none(self):
        """Returns None when mcpExecuteTools is not a list."""
        tool = self._make_tool()
        result = tool._check_proxy_tool_mock({'mcpExecuteTools': 'not a list'})
        assert result is None

    def test_no_matching_mocks_returns_none(self):
        """Returns None when no mock matches."""
        tool = self._make_tool()
        arguments = {
            'mcpExecuteTools': [
                {'mcpToolName': 'someUnknownTool', 'args': {}},
            ]
        }
        result = tool._check_proxy_tool_mock(arguments)
        assert result is None


# -----------------------------------------------------------------------------
# Tests: hidden_fields in to_tool_schema
# -----------------------------------------------------------------------------

class TestMCPDynamicToolHiddenFields:
    """Test hidden_fields filtering in to_tool_schema()."""

    def test_no_hidden_fields(self):
        """to_tool_schema() returns all params when no hidden_fields."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={
                'type': 'object',
                'properties': {
                    'a': {'type': 'string'},
                    'b': {'type': 'number'},
                },
                'required': ['a'],
            },
            server_name='test',
        )
        schema = tool.to_tool_schema()
        params = schema['function']['parameters']
        assert 'a' in params['properties']
        assert 'b' in params['properties']
        assert params['required'] == ['a']

    def test_hidden_fields_removed(self):
        """to_tool_schema() removes hidden_fields from properties and required."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'secret_key': {'type': 'string'},
                    'api_token': {'type': 'string'},
                },
                'required': ['name', 'secret_key'],
            },
            server_name='test',
            config={'hidden_fields': ['secret_key', 'api_token']},
        )
        schema = tool.to_tool_schema()
        params = schema['function']['parameters']
        assert 'name' in params['properties']
        assert 'secret_key' not in params['properties']
        assert 'api_token' not in params['properties']
        assert params['required'] == ['name']

    def test_hidden_fields_empty_properties(self):
        """hidden_fields filtering works with empty properties."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={
                'type': 'object',
            },
            server_name='test',
            config={'hidden_fields': ['x', 'y']},
        )
        schema = tool.to_tool_schema()
        params = schema['function']['parameters']
        assert 'properties' not in params or params.get('properties') == {}

    def test_default_hidden_fields_empty_list(self):
        """Default hidden_fields is empty list."""
        tool = MCPDynamicTool(
            name='test',
            description='Test',
            parameters_schema={},
            server_name='test',
        )
        assert tool.hidden_fields == []
        assert tool.is_factory_class is True
