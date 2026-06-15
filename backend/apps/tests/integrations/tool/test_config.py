"""
Tests for ToolConfig.
"""
import pytest

from apps.integrations.tool.config import ToolConfig


# -----------------------------------------------------------------------------
# Tests: ToolConfig
# -----------------------------------------------------------------------------

class TestToolConfig:
    """Test ToolConfig data class."""

    def test_name_required(self):
        """name is a required field."""
        config = ToolConfig(name='test_tool')
        assert config.name == 'test_tool'

    def test_config_default_empty_dict(self):
        """config defaults to empty dict."""
        config = ToolConfig(name='test_tool')
        assert config.config == {}

    def test_enabled_default_true(self):
        """enabled defaults to True."""
        config = ToolConfig(name='test_tool')
        assert config.enabled is True

    def test_config_set_correctly(self):
        """config is set correctly when provided."""
        config = ToolConfig(name='test_tool', config={'key': 'value'})
        assert config.config == {'key': 'value'}

    def test_enabled_set_correctly(self):
        """enabled is set correctly when provided."""
        config = ToolConfig(name='test_tool', enabled=False)
        assert config.enabled is False

    def test_module_auto_derived(self):
        """module is auto-derived from name."""
        config = ToolConfig(name='view_text_file')
        assert config.module == 'apps.integrations.tool.view_text_file_tool'

    def test_module_with_underscore(self):
        """module handles underscores correctly."""
        config = ToolConfig(name='my_custom_tool')
        assert config.module == 'apps.integrations.tool.my_custom_tool_tool'

    def test_class_name_auto_derived(self):
        """class_name is auto-derived from name."""
        config = ToolConfig(name='view_text_file')
        assert config.class_name == 'ViewTextFileTool'

    def test_class_name_single_word(self):
        """class_name handles single word names."""
        config = ToolConfig(name='calculator')
        assert config.class_name == 'CalculatorTool'

    def test_snake_to_camel_conversion(self):
        """snake_case to CamelCase conversion is correct."""
        # Multiple words
        config = ToolConfig(name='rag_search')
        assert config.class_name == 'RagSearchTool'

        # Three words
        config = ToolConfig(name='http_rag_search')
        assert config.class_name == 'HttpRagSearchTool'

    def test_from_dict_basic(self):
        """from_dict() creates config correctly."""
        data = {'name': 'test_tool', 'config': {'top_k': 5}}
        config = ToolConfig.from_dict(data)

        assert config.name == 'test_tool'
        assert config.config == {'top_k': 5}
        assert config.enabled is True

    def test_from_dict_with_all_fields(self):
        """from_dict() handles all fields."""
        data = {
            'name': 'test_tool',
            'config': {'timeout': 30},
            'enabled': False
        }
        config = ToolConfig.from_dict(data)

        assert config.name == 'test_tool'
        assert config.config == {'timeout': 30}
        assert config.enabled is False

    def test_from_dict_missing_name_raises(self):
        """from_dict() raises KeyError when name is missing."""
        with pytest.raises(KeyError):
            ToolConfig.from_dict({'config': {}})

    def test_from_dict_default_config(self):
        """from_dict() defaults config to empty dict."""
        data = {'name': 'test_tool'}
        config = ToolConfig.from_dict(data)

        assert config.config == {}

    def test_from_dict_default_enabled(self):
        """from_dict() defaults enabled to True."""
        data = {'name': 'test_tool'}
        config = ToolConfig.from_dict(data)

        assert config.enabled is True

    def test_auto_derived_with_numbers(self):
        """Auto-derived fields handle names with numbers."""
        config = ToolConfig(name='tool_v2')
        # Numbers in the middle are not capitalized
        assert 'Tool' in config.class_name

    def test_post_init_called(self):
        """__post_init__ is called on instantiation."""
        config = ToolConfig(name='rag_search')
        # If we got here without error, __post_init__ was called
        assert hasattr(config, 'module')
        assert hasattr(config, 'class_name')

    # -------------------------------------------------------------------------
    # Tests: client_type and multi-instance support
    # -------------------------------------------------------------------------

    def test_client_type_defaults_to_name(self):
        """client_type falls back to name when not in config."""
        config = ToolConfig(name='rag_search')
        assert config.client_type == 'rag_search'

    def test_client_type_from_config(self):
        """client_type is extracted from config dict."""
        config = ToolConfig(
            name='faq_rag',
            config={'client_type': 'rag_search', 'rag_url': 'https://example.com'},
        )
        assert config.client_type == 'rag_search'
        assert config.name == 'faq_rag'

    def test_module_derived_from_client_type(self):
        """module is derived from client_type, not name."""
        config = ToolConfig(
            name='faq_rag',
            config={'client_type': 'rag_search'},
        )
        assert config.module == 'apps.integrations.tool.rag_search_tool'
        assert config.class_name == 'RagSearchTool'

    def test_mcp_type_skips_derivation(self):
        """MCP type does not derive module/class_name."""
        config = ToolConfig(
            name='portal-mcp',
            type='mcp',
            config={'client_type': 'custom', 'endpoint': 'https://example.com'},
        )
        assert config.client_type == 'custom'
        assert config.module == ''
        assert config.class_name == ''

    def test_from_dict_with_client_type(self):
        """from_dict() correctly extracts client_type from config."""
        data = {
            'name': 'doc_rag',
            'type': 'rag',
            'config': {
                'client_type': 'rag_search',
                'rag_url': 'https://doc-service/api',
            },
        }
        config = ToolConfig.from_dict(data)
        assert config.name == 'doc_rag'
        assert config.type == 'rag'
        assert config.client_type == 'rag_search'
        assert config.module == 'apps.integrations.tool.rag_search_tool'

    def test_from_dict_backward_compatible(self):
        """from_dict() without client_type is backward compatible."""
        data = {'name': 'rag_search', 'config': {'rag_url': 'https://example.com'}}
        config = ToolConfig.from_dict(data)
        assert config.client_type == 'rag_search'
        assert config.module == 'apps.integrations.tool.rag_search_tool'
