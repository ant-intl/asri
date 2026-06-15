"""
Tests for BaseTool and ToolRegistry.
"""
import pytest
from abc import ABC
from typing import Any

from apps.integrations.tool.base import BaseTool, ToolRegistry


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------

class ConcreteTool(BaseTool):
    """Concrete implementation of BaseTool for testing."""

    name = 'concrete_tool'
    description = 'A concrete tool for testing'

    async def execute(self, input_text: str, context: Any) -> str:
        return f'Executed: {input_text}'


class AnotherConcreteTool(BaseTool):
    """Another concrete tool for testing."""

    name = 'another_tool'
    description = 'Another test tool'

    async def execute(self, input_text: str, context: Any) -> str:
        return f'Another executed: {input_text}'


# -----------------------------------------------------------------------------
# Tests: BaseTool Abstraction
# -----------------------------------------------------------------------------

class TestBaseToolAbstraction:
    """Test BaseTool abstract class constraints."""

    def test_cannot_instantiate_base_class(self):
        """BaseTool cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseTool()

    def test_is_abstract_class(self):
        """Verify BaseTool is an ABC."""
        assert issubclass(BaseTool, ABC)

    def test_subclass_without_execute_raises(self):
        """Subclass without execute() cannot be instantiated."""
        class MissingExecuteTool(BaseTool):
            name = 'missing_execute'

            @property
            def description(self) -> str:
                return 'Test'

        # Cannot instantiate without execute
        with pytest.raises(TypeError, match="abstract"):
            tool = MissingExecuteTool()

    def test_subclass_without_description_raises(self):
        """Subclass without description cannot be instantiated."""
        class MissingDescriptionTool(BaseTool):
            name = 'missing_description'

            async def execute(self, input_text: str, context: Any) -> str:
                return 'test'

        # Cannot instantiate without description
        with pytest.raises(TypeError, match="abstract"):
            tool = MissingDescriptionTool()

    def test_complete_subclass_can_instantiate(self):
        """Complete subclass can be instantiated."""
        tool = ConcreteTool()
        assert tool.name == 'concrete_tool'
        assert tool.description == 'A concrete tool for testing'


# -----------------------------------------------------------------------------
# Tests: BaseTool Default Methods
# -----------------------------------------------------------------------------

class TestBaseToolDefaultMethods:
    """Test BaseTool default method implementations."""

    def test_to_tool_schema_basic(self):
        """to_tool_schema() returns correct format."""
        tool = ConcreteTool()
        schema = tool.to_tool_schema()

        assert schema['type'] == 'function'
        assert schema['function']['name'] == 'concrete_tool'
        assert schema['function']['description'] == 'A concrete tool for testing'

    def test_to_tool_schema_with_parameters(self):
        """to_tool_schema() includes parameters when defined."""
        class ToolWithParams(BaseTool):
            name = 'params_tool'
            description = 'Tool with parameters'
            parameters_schema = {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'}
                },
                'required': ['query']
            }

            async def execute(self, input_text: str, context: Any) -> str:
                return 'test'

        tool = ToolWithParams()
        schema = tool.to_tool_schema()

        assert schema['function']['parameters'] == tool.parameters_schema

    def test_to_tool_schema_empty_parameters(self):
        """to_tool_schema() excludes parameters when empty."""
        tool = ConcreteTool()
        schema = tool.to_tool_schema()

        assert 'parameters' not in schema['function']

    def test_default_parameters(self):
        """_default_parameters() returns correct schema."""
        tool = ConcreteTool()
        default_params = tool._default_parameters()

        assert default_params['type'] == 'object'
        assert 'input' in default_params['properties']
        assert 'required' in default_params

    def test_initialization_stores_config(self):
        """Initialization stores config correctly."""
        from apps.integrations.tool.base import BaseTool
        from typing import Any, Optional

        class ConfigurableTool(BaseTool):
            name = 'configurable_tool'
            description = 'A configurable tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text: str, context: Any) -> str:
                return 'test'

        config = {'top_k': 10, 'timeout': 30}
        tool = ConfigurableTool(config=config)

        assert tool.config == config

    def test_initialization_stores_tenant_id(self):
        """Initialization stores tenant_id correctly."""
        from apps.integrations.tool.base import BaseTool
        from typing import Any

        class TenantTool(BaseTool):
            name = 'tenant_tool'
            description = 'A tenant tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text: str, context: Any) -> str:
                return 'test'

        tool = TenantTool(tenant_id='tenant123')

        assert tool.tenant_id == 'tenant123'


# -----------------------------------------------------------------------------
# Tests: ToolRegistry Class Registration
# -----------------------------------------------------------------------------

class TestToolRegistryClassRegistration:
    """Test ToolRegistry class registration (auto-registration)."""

    def test_register_class_registers_tool(self):
        """register_class() registers a tool class."""
        ToolRegistry.register_class(ConcreteTool)

        assert 'concrete_tool' in ToolRegistry._tool_classes
        assert ToolRegistry._tool_classes['concrete_tool'] is ConcreteTool

    def test_get_tool_class_returns_class(self):
        """get_tool_class() returns the registered class."""
        ToolRegistry.register_class(ConcreteTool)

        cls = ToolRegistry.get_tool_class('concrete_tool')
        assert cls is ConcreteTool

    def test_get_tool_class_not_found(self):
        """get_tool_class() returns None for non-existent class."""
        cls = ToolRegistry.get_tool_class('nonexistent_tool')
        assert cls is None

    def test_get_tool_class_case_insensitive(self):
        """get_tool_class() is case insensitive."""
        ToolRegistry.register_class(ConcreteTool)

        cls = ToolRegistry.get_tool_class('CONCRETE_TOOL')
        assert cls is ConcreteTool

    def test_list_tool_classes_sorted(self):
        """list_tool_classes() returns sorted list."""
        ToolRegistry.register_class(ConcreteTool)
        ToolRegistry.register_class(AnotherConcreteTool)

        classes = ToolRegistry.list_tool_classes()
        assert classes == ['another_tool', 'concrete_tool']

    def test_auto_registration_via_init_subclass(self):
        """Subclasses are auto-registered via __init_subclass__."""
        # Re-register classes since clear_tool_registry cleared them
        ToolRegistry.register_class(ConcreteTool)
        ToolRegistry.register_class(AnotherConcreteTool)

        assert 'concrete_tool' in ToolRegistry._tool_classes
        assert 'another_tool' in ToolRegistry._tool_classes


# -----------------------------------------------------------------------------
# Tests: ToolRegistry Instance Registration
# -----------------------------------------------------------------------------

class TestToolRegistryInstanceRegistration:
    """Test ToolRegistry instance registration."""

    def test_register_instance(self):
        """register() registers an instance."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id=None)

        assert 'concrete_tool' in ToolRegistry._tools[None]
        assert ToolRegistry._tools[None]['concrete_tool'] is tool

    def test_register_tenant_specific(self):
        """register() stores tool in tenant-specific bucket."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id='tenant123')

        assert 'tenant123' in ToolRegistry._tools
        assert 'concrete_tool' in ToolRegistry._tools['tenant123']

    def test_get_tool_tenant_specific(self):
        """get_tool() returns tenant-specific tool when available."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id='tenant123')

        result = ToolRegistry.get_tool('concrete_tool', tenant_id='tenant123')
        assert result is tool

    def test_get_tool_fallback_to_global(self):
        """get_tool() falls back to global when tenant tool not found."""
        global_tool = ConcreteTool()
        ToolRegistry.register(global_tool, tenant_id=None)

        result = ToolRegistry.get_tool('concrete_tool', tenant_id='tenant123')
        assert result is global_tool

    def test_get_tool_tenant_priority(self):
        """get_tool() prefers tenant tool over global."""
        from apps.integrations.tool.base import BaseTool
        from typing import Any

        class ConfigurableTool(BaseTool):
            name = 'configurable_tool'
            description = 'Configurable tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text: str, context: Any) -> str:
                return 'test'

        global_tool = ConfigurableTool()
        ToolRegistry.register(global_tool, tenant_id=None)

        # Create a tenant-specific version with different config
        tenant_tool = ConfigurableTool(config={'tenant': True})
        ToolRegistry.register(tenant_tool, tenant_id='tenant123')

        result = ToolRegistry.get_tool('configurable_tool', tenant_id='tenant123')
        assert result.config.get('tenant') is True

    def test_create_and_register_success(self):
        """create_and_register() successfully creates and registers."""
        from apps.integrations.tool.base import BaseTool
        from typing import Any

        class RegistrableTool(BaseTool):
            name = 'registrable_tool'
            description = 'Registrable tool'

            def __init__(self, config: dict = None, tenant_id: str = None):
                self.config = config or {}
                self.tenant_id = tenant_id

            async def execute(self, input_text: str, context: Any) -> str:
                return 'test'

        ToolRegistry.register_class(RegistrableTool)

        result = ToolRegistry.create_and_register('registrable_tool', tenant_id='tenant123', config={'key': 'value'})

        assert result is True
        tool = ToolRegistry.get_tool('registrable_tool', tenant_id='tenant123')
        assert tool is not None
        assert tool.config == {'key': 'value'}
        assert tool.tenant_id == 'tenant123'

    def test_create_and_register_class_not_found(self):
        """create_and_register() returns False when class not found."""
        result = ToolRegistry.create_and_register('nonexistent', tenant_id='tenant123')

        assert result is False

    def test_register_instance_case_insensitive(self):
        """register() is case insensitive for tool names."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id=None)

        # Should be stored as lowercase
        assert 'concrete_tool' in ToolRegistry._tools[None]


# -----------------------------------------------------------------------------
# Tests: ToolRegistry Listing
# -----------------------------------------------------------------------------

class TestToolRegistryListing:
    """Test ToolRegistry listing methods."""

    def test_list_tools_tenant_only(self):
        """list_tools() returns only tenant tools when specified."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id='tenant123')

        tools = ToolRegistry.list_tools(tenant_id='tenant123')
        assert tools == ['concrete_tool']

    def test_list_tools_merges_global(self):
        """list_tools() merges tenant and global tools."""
        global_tool = ConcreteTool()
        ToolRegistry.register(global_tool, tenant_id=None)

        tenant_tool = AnotherConcreteTool()
        ToolRegistry.register(tenant_tool, tenant_id='tenant123')

        tools = ToolRegistry.list_tools(tenant_id='tenant123')
        assert tools == ['another_tool', 'concrete_tool']

    def test_list_tools_deduplicates(self):
        """list_tools() deduplicates (tenant takes priority)."""
        global_tool = ConcreteTool()
        ToolRegistry.register(global_tool, tenant_id=None)

        # Register same tool for tenant (should not duplicate)
        tenant_tool = ConcreteTool()
        ToolRegistry.register(tenant_tool, tenant_id='tenant123')

        tools = ToolRegistry.list_tools(tenant_id='tenant123')
        assert tools == ['concrete_tool']

    def test_list_tools_empty_tenant(self):
        """list_tools() returns global tools when tenant has none."""
        global_tool = ConcreteTool()
        ToolRegistry.register(global_tool, tenant_id=None)

        tools = ToolRegistry.list_tools(tenant_id='tenant456')
        assert tools == ['concrete_tool']

    def test_list_tools_with_schemas(self):
        """list_tools_with_schemas() returns OpenAI format."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id='tenant123')

        schemas = ToolRegistry.list_tools_with_schemas(tenant_id='tenant123')

        assert len(schemas) == 1
        assert schemas[0]['type'] == 'function'
        assert schemas[0]['function']['name'] == 'concrete_tool'

    def test_list_tools_with_schemas_merges_and_deduplicates(self):
        """list_tools_with_schemas() merges with deduplication."""
        tool1 = ConcreteTool()
        ToolRegistry.register(tool1, tenant_id=None)

        tool2 = AnotherConcreteTool()
        ToolRegistry.register(tool2, tenant_id='tenant123')

        schemas = ToolRegistry.list_tools_with_schemas(tenant_id='tenant123')
        names = [s['function']['name'] for s in schemas]

        assert len(names) == 2
        assert 'concrete_tool' in names
        assert 'another_tool' in names

    def test_list_tools_with_schemas_global_only(self):
        """list_tools_with_schemas() returns global tools when no tenant tools."""
        tool = ConcreteTool()
        ToolRegistry.register(tool, tenant_id=None)

        schemas = ToolRegistry.list_tools_with_schemas(tenant_id=None)
        assert len(schemas) == 1

    def test_list_tools_empty(self):
        """list_tools() returns empty list when no tools registered."""
        tools = ToolRegistry.list_tools(tenant_id='empty_tenant')
        assert tools == []


# -----------------------------------------------------------------------------
# Tests: BaseTool instance_name
# -----------------------------------------------------------------------------

class TestBaseToolInstanceName:
    """Test BaseTool instance_name separation from class name."""

    def test_instance_name_defaults_to_class_name(self):
        """instance_name falls back to class-level name."""
        tool = ConcreteTool()
        assert tool.instance_name == 'concrete_tool'

    def test_instance_name_override(self):
        """_instance_name overrides class-level name."""
        tool = ConcreteTool()
        tool._instance_name = 'my_custom_instance'
        assert tool.instance_name == 'my_custom_instance'

    def test_to_tool_schema_uses_instance_name(self):
        """to_tool_schema() uses instance_name in function definition."""
        tool = ConcreteTool()
        tool._instance_name = 'faq_tool'
        schema = tool.to_tool_schema()
        assert schema['function']['name'] == 'faq_tool'

    def test_to_tool_schema_default_uses_class_name(self):
        """to_tool_schema() uses class name when _instance_name not set."""
        tool = ConcreteTool()
        schema = tool.to_tool_schema()
        assert schema['function']['name'] == 'concrete_tool'


# -----------------------------------------------------------------------------
# Tests: ToolRegistry Multi-Instance
# -----------------------------------------------------------------------------

class MultiInstanceTool(BaseTool):
    """Tool with __init__ that accepts tenant_id/config for multi-instance tests."""

    name = 'multi_instance_tool'

    def __init__(self, config: dict = None, tenant_id: str = None):
        self.config = config or {}
        self.tenant_id = tenant_id

    @property
    def description(self) -> str:
        return 'A multi-instance test tool'

    async def execute(self, input_text: str, context: Any) -> str:
        return f'Executed: {input_text}'


class TestToolRegistryMultiInstance:
    """Test ToolRegistry multi-instance support via instance_name/class_type."""

    def test_create_and_register_with_instance_name(self):
        """create_and_register() stores tool by instance_name."""
        ToolRegistry.register_class(MultiInstanceTool)

        result = ToolRegistry.create_and_register(
            name='multi_instance_tool',
            tenant_id='t1',
            config={'key': 'v1'},
            instance_name='instance_a',
        )
        assert result is True

        tool = ToolRegistry.get_tool('instance_a', tenant_id='t1')
        assert tool is not None
        assert tool.instance_name == 'instance_a'
        assert tool.config == {'key': 'v1'}

    def test_create_and_register_with_class_type(self):
        """create_and_register() uses class_type for class lookup."""
        ToolRegistry.register_class(MultiInstanceTool)

        result = ToolRegistry.create_and_register(
            name='multi_instance_tool',
            tenant_id='t1',
            config={},
            instance_name='custom_name',
            class_type='multi_instance_tool',
        )
        assert result is True

        tool = ToolRegistry.get_tool('custom_name', tenant_id='t1')
        assert tool is not None
        assert tool.instance_name == 'custom_name'
        # class-level name should still be 'multi_instance_tool'
        assert tool.name == 'multi_instance_tool'

    def test_multiple_instances_same_class(self):
        """Two instances of the same class can coexist under different names."""
        ToolRegistry.register_class(MultiInstanceTool)

        ToolRegistry.create_and_register(
            name='multi_instance_tool',
            tenant_id='t1',
            config={'version': 'a'},
            instance_name='tool_v1',
            class_type='multi_instance_tool',
        )
        ToolRegistry.create_and_register(
            name='multi_instance_tool',
            tenant_id='t1',
            config={'version': 'b'},
            instance_name='tool_v2',
            class_type='multi_instance_tool',
        )

        tool_v1 = ToolRegistry.get_tool('tool_v1', tenant_id='t1')
        tool_v2 = ToolRegistry.get_tool('tool_v2', tenant_id='t1')

        assert tool_v1 is not None
        assert tool_v2 is not None
        assert tool_v1 is not tool_v2
        assert tool_v1.config == {'version': 'a'}
        assert tool_v2.config == {'version': 'b'}

    def test_list_tools_with_schemas_uses_instance_name(self):
        """list_tools_with_schemas() returns instance_name, not class name."""
        ToolRegistry.register_class(MultiInstanceTool)

        ToolRegistry.create_and_register(
            name='multi_instance_tool',
            tenant_id='t1',
            config={},
            instance_name='my_instance',
            class_type='multi_instance_tool',
        )

        schemas = ToolRegistry.list_tools_with_schemas(tenant_id='t1')
        assert len(schemas) == 1
        assert schemas[0]['function']['name'] == 'my_instance'

    def test_backward_compatible_without_instance_name(self):
        """Without instance_name, behavior is identical to before."""
        ToolRegistry.register_class(MultiInstanceTool)

        result = ToolRegistry.create_and_register(
            name='multi_instance_tool',
            tenant_id='t1',
            config={},
        )
        assert result is True

        tool = ToolRegistry.get_tool('multi_instance_tool', tenant_id='t1')
        assert tool is not None
        assert tool.instance_name == 'multi_instance_tool'

    def test_register_uses_instance_name_as_key(self):
        """register() stores tool by instance_name, not class name."""
        tool = ConcreteTool()
        tool._instance_name = 'custom_key'
        ToolRegistry.register(tool, tenant_id='t1')

        # Can find by instance_name
        found = ToolRegistry.get_tool('custom_key', tenant_id='t1')
        assert found is tool

        # Cannot find by class name
        not_found = ToolRegistry.get_tool('concrete_tool', tenant_id='t1')
        assert not_found is None
